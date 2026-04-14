"""Edit Session — All non-GUI editing logic for a transcript session."""
from __future__ import annotations

import difflib
import getpass
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from transcript_manager import TranscriptManager
from audit_logger import AuditLogger


# ─── Data types ────────────────────────────────────────────────────────

@dataclass
class EditAction:
    type: str  # "edit" | "insert"
    segment_index: int
    old_speaker: str = ""
    old_text: str = ""
    new_speaker: str = ""
    new_text: str = ""
    # insert-specific
    speaker: str = ""
    start: float = 0.0
    end: float = 0.0
    text: str = ""


@dataclass
class SearchResult:
    segment_index: int
    char_start: int  # -1 = speaker match
    char_end: int


# ─── Session ───────────────────────────────────────────────────────────

class EditSession:
    """Holds all mutable editing state and logic, independent of any GUI toolkit."""

    def __init__(self, transcript: TranscriptManager,
                 audit: Optional[AuditLogger] = None):
        self.transcript = transcript
        self.audit = audit

        # Tracking
        self.segment_original: Dict[int, Dict[str, Any]] = {}  # seg_id -> original data
        self.index_to_id: Dict[int, int] = {}                  # seg index -> unique id
        self._next_id = 0
        self.edited: Set[int] = set()
        self.inserted: Set[int] = set()

        # Undo
        self.undo_stack: List[EditAction] = []

        # Pending (pre-commit) edits — keyed by segment index
        self.pending_before: Dict[int, Dict[str, str]] = {}

        # Save state
        self.unsaved = False

        # Search
        self.search_matches: List[SearchResult] = []
        self.search_index = -1
        self.active_search_pattern = ""  # regex pattern string for highlighting

        # Init tracking for all loaded segments
        self._init_tracking()

    # ═══════════════════════════════════════════════════════════════════
    #  TRACKING INIT
    # ═══════════════════════════════════════════════════════════════════

    def _init_tracking(self):
        self.segment_original.clear()
        self.index_to_id.clear()
        self._next_id = 0
        self.edited.clear()
        self.inserted.clear()
        self.undo_stack.clear()
        self.pending_before.clear()
        self.unsaved = False

        for idx, seg in enumerate(self.transcript.segments):
            sid = self._next_id; self._next_id += 1
            self.index_to_id[idx] = sid
            self.segment_original[sid] = {
                "speaker": seg.speaker, "text": seg.text,
                "start": seg.start, "end": seg.end,
            }

    def get_original(self, seg_idx: int) -> Dict[str, Any]:
        sid = self.index_to_id.get(seg_idx)
        if sid is not None and sid in self.segment_original:
            return self.segment_original[sid]
        seg = self.transcript.get_segment(seg_idx)
        if seg:
            return {"speaker": seg.speaker, "text": seg.text,
                    "start": seg.start, "end": seg.end}
        return {"speaker": "", "text": "", "start": 0.0, "end": 0.0}

    # ═══════════════════════════════════════════════════════════════════
    #  EDIT MANAGEMENT (debounce-friendly)
    # ═══════════════════════════════════════════════════════════════════

    def begin_edit(self, seg_idx: int):
        """Capture the 'before' snapshot if not already captured."""
        if seg_idx not in self.pending_before:
            seg = self.transcript.segments[seg_idx]
            self.pending_before[seg_idx] = {
                "speaker": seg.speaker, "text": seg.text,
            }

    def apply_text(self, seg_idx: int, new_text: str) -> bool:
        """Apply text change in memory. Returns True if changed."""
        old = self.transcript.segments[seg_idx].text
        if old == new_text:
            return False
        self.begin_edit(seg_idx)
        self.transcript.update_segment_text(seg_idx, new_text)
        self._mark_unsaved(seg_idx)
        return True

    def apply_speaker(self, seg_idx: int, new_speaker: str) -> bool:
        """Apply speaker change in memory. Returns True if changed."""
        old = self.transcript.segments[seg_idx].speaker
        if old == new_speaker:
            return False
        self.begin_edit(seg_idx)
        self.transcript.update_segment_speaker(seg_idx, new_speaker)
        self._mark_unsaved(seg_idx)
        return True

    def commit_edit(self, seg_idx: int):
        """Finalise a pending edit: push to undo stack + audit log."""
        before = self.pending_before.pop(seg_idx, None)
        if before is None:
            return
        seg = self.transcript.segments[seg_idx]
        if before["speaker"] == seg.speaker and before["text"] == seg.text:
            return  # no actual change

        self.undo_stack.append(EditAction(
            type="edit", segment_index=seg_idx,
            old_speaker=before["speaker"], old_text=before["text"],
            new_speaker=seg.speaker, new_text=seg.text,
        ))

        if self.audit:
            if before["text"] != seg.text:
                self.audit.log_edit(seg_idx, seg.start, seg.end,
                                    "text", before["text"], seg.text)
            if before["speaker"] != seg.speaker:
                self.audit.log_edit(seg_idx, seg.start, seg.end,
                                    "speaker", before["speaker"], seg.speaker)

    def flush_all_pending(self):
        """Commit all pending edits (call before save)."""
        for seg_idx in list(self.pending_before.keys()):
            self.commit_edit(seg_idx)

    # ═══════════════════════════════════════════════════════════════════
    #  UNDO
    # ═══════════════════════════════════════════════════════════════════

    def undo_row(self, seg_idx: int) -> bool:
        """Undo all changes for a specific row. Returns True if view needs refresh."""
        if seg_idx in self.inserted:
            seg = self.transcript.segments[seg_idx]
            if self.audit:
                self.audit.log_delete(seg_idx, seg.start, seg.end,
                                      seg.speaker, seg.text)
            self.transcript.delete_segment(seg_idx)
            self._shift_after_delete(seg_idx)
        else:
            orig = self.get_original(seg_idx)
            self.transcript.update_segment_speaker(seg_idx, orig["speaker"])
            self.transcript.update_segment_text(seg_idx, orig["text"])
            if self.audit:
                seg = self.transcript.segments[seg_idx]
                self.audit.log_undo("edit", seg_idx, seg.start, seg.end,
                                    "Restored original")
            self.edited.discard(seg_idx)
        self.unsaved = True
        return True

    def undo_last(self) -> bool:
        """Undo the most recent action from the stack. Returns True if something was undone."""
        if not self.undo_stack:
            return False
        action = self.undo_stack.pop()

        if action.type == "edit":
            idx = action.segment_index
            if idx >= len(self.transcript.segments):
                return False
            self.transcript.update_segment_speaker(idx, action.old_speaker)
            self.transcript.update_segment_text(idx, action.old_text)
            orig = self.get_original(idx)
            if (action.old_speaker == orig.get("speaker") and
                    action.old_text == orig.get("text")):
                self.edited.discard(idx)
            self.unsaved = True
            return True

        elif action.type == "insert":
            idx = action.segment_index
            if idx >= len(self.transcript.segments):
                return False
            self.transcript.delete_segment(idx)
            self._shift_after_delete(idx)
            self.unsaved = True
            return True

        return False

    # ═══════════════════════════════════════════════════════════════════
    #  INSERT / DELETE
    # ═══════════════════════════════════════════════════════════════════

    def insert_segment(self, after_idx: int, speaker: str,
                       start: float, end: float, text: str) -> int:
        """Insert a new segment. Returns the insertion index."""
        pos = after_idx + 1
        self.transcript.insert_segment(pos, speaker, start, end, text)

        new_id = self._next_id; self._next_id += 1
        self._shift_after_insert(pos, new_id)

        self.undo_stack.append(EditAction(
            type="insert", segment_index=pos,
            speaker=speaker, start=start, end=end, text=text,
        ))
        if self.audit:
            self.audit.log_insert(pos, start, end, speaker, text)

        self.unsaved = True
        return pos

    # ═══════════════════════════════════════════════════════════════════
    #  INDEX SHIFTING
    # ═══════════════════════════════════════════════════════════════════

    def _shift_after_insert(self, pos: int, new_id: int):
        nm = {}
        for i, s in self.index_to_id.items():
            nm[i + 1 if i >= pos else i] = s
        nm[pos] = new_id
        self.index_to_id = nm
        self.inserted = {(i + 1 if i >= pos else i) for i in self.inserted}
        self.inserted.add(pos)
        self.edited = {(i + 1 if i >= pos else i) for i in self.edited}

    def _shift_after_delete(self, pos: int):
        self.inserted.discard(pos)
        self.edited.discard(pos)
        nm = {}
        for i, s in self.index_to_id.items():
            if i < pos:
                nm[i] = s
            elif i > pos:
                nm[i - 1] = s
        self.index_to_id = nm
        self.inserted = {(i - 1 if i > pos else i) for i in self.inserted}
        self.edited = {(i - 1 if i > pos else i) for i in self.edited}

    # ═══════════════════════════════════════════════════════════════════
    #  VALIDATION
    # ═══════════════════════════════════════════════════════════════════

    def validate_row(self, seg_idx: int) -> bool:
        user = getpass.getuser()
        if self.transcript.validate_row(seg_idx, user):
            if self.audit:
                seg = self.transcript.segments[seg_idx]
                self.audit.log_validation("row", seg_idx, seg.start, seg.end, field="both")
            self.unsaved = True
            return True
        return False

    def validate_speaker(self, seg_idx: int) -> bool:
        user = getpass.getuser()
        if self.transcript.validate_speaker(seg_idx, user):
            if self.audit:
                seg = self.transcript.segments[seg_idx]
                self.audit.log_validation("speaker", seg_idx, seg.start, seg.end, field="speaker")
            self.unsaved = True
            return True
        return False

    def validate_content(self, seg_idx: int) -> bool:
        user = getpass.getuser()
        if self.transcript.validate_content(seg_idx, user):
            if self.audit:
                seg = self.transcript.segments[seg_idx]
                self.audit.log_validation("content", seg_idx, seg.start, seg.end, field="content")
            self.unsaved = True
            return True
        return False

    def validate_to_index(self, end_idx: int) -> int:
        user = getpass.getuser()
        count = self.transcript.validate_to_index(end_idx, user)
        if self.audit and count:
            first = self.transcript.segments[0]
            last = self.transcript.segments[end_idx]
            self.audit.log_validation("to_index", 0, first.start, last.end,
                                      field="both", end_index=end_idx, count=count)
        if count:
            self.unsaved = True
        return count

    # ═══════════════════════════════════════════════════════════════════
    #  SEARCH
    # ═══════════════════════════════════════════════════════════════════

    def build_search(self, query: str, is_regex: bool = False,
                     case_sensitive: bool = False) -> int:
        """Build search matches. Returns match count.

        In non-regex mode, ``*`` is treated as "any characters" and ``?``
        as "any single character" (glob-style wildcards).  For example
        ``FI*MA`` matches ``FINMA``, ``FIMA``, ``FIXXMA``, etc.
        """
        self.search_matches.clear()
        self.search_index = -1

        if not query:
            self.active_search_pattern = ""
            return 0

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            if is_regex:
                pattern = re.compile(query, flags)
            else:
                # Escape everything, then convert glob wildcards
                escaped = re.escape(query)
                escaped = escaped.replace(r"\*", ".*").replace(r"\?", ".")
                pattern = re.compile(escaped, flags)
        except re.error:
            self.active_search_pattern = ""
            return -1  # invalid regex

        self.active_search_pattern = pattern.pattern

        for seg in self.transcript.segments:
            for m in pattern.finditer(seg.text):
                self.search_matches.append(
                    SearchResult(seg.index, m.start(), m.end()))
            for m in pattern.finditer(seg.speaker):
                self.search_matches.append(
                    SearchResult(seg.index, -1, -1))

        return len(self.search_matches)

    def search_next(self) -> Optional[int]:
        """Advance to next match. Returns segment index or None."""
        if not self.search_matches:
            return None
        self.search_index = (self.search_index + 1) % len(self.search_matches)
        return self.search_matches[self.search_index].segment_index

    def search_prev(self) -> Optional[int]:
        """Go to previous match. Returns segment index or None."""
        if not self.search_matches:
            return None
        self.search_index = (self.search_index - 1) % len(self.search_matches)
        return self.search_matches[self.search_index].segment_index

    def clear_search(self):
        self.search_matches.clear()
        self.search_index = -1
        self.active_search_pattern = ""

    def search_status_text(self) -> str:
        if not self.search_matches:
            return ""
        return (f"Match {self.search_index + 1}/{len(self.search_matches)} "
                f"(segment #{self.search_matches[self.search_index].segment_index + 1})")

    # ═══════════════════════════════════════════════════════════════════
    #  SAVE
    # ═══════════════════════════════════════════════════════════════════

    def save(self, file_path: str = None) -> bool:
        ok = self.transcript.save_transcript(file_path)
        if ok and file_path is None:
            self.unsaved = False
        return ok

    def log_export(self):
        if self.audit:
            out = self.transcript.output_file
            ext = out.rsplit(".", 1)[-1] if "." in out else ""
            self.audit.log_export(out, ext)

    def end_session(self):
        if self.audit:
            self.audit.end_session()

    def save_audit_if_needed(self):
        if self.audit:
            self.audit.save_if_needed()

    # ═══════════════════════════════════════════════════════════════════
    #  HELPERS
    # ═══════════════════════════════════════════════════════════════════

    def _mark_unsaved(self, seg_idx: int):
        self.unsaved = True
        self.edited.add(seg_idx)

    def next_edited_index(self, after: int) -> Optional[int]:
        """Find the next edited segment index after *after*, wrapping."""
        if not self.edited:
            return None
        es = sorted(self.edited)
        return next((i for i in es if i > after), es[0])

    def find_segment_at_time(self, seconds: float) -> int:
        """Return index of the segment containing or nearest to *seconds*."""
        best = 0
        for i, seg in enumerate(self.transcript.segments):
            if seg.start <= seconds <= seg.end:
                return i
            if seg.start > seconds:
                return max(0, i - 1)
            best = i
        return best

    @staticmethod
    def compute_diff_ops(original: str, current: str):
        """Return difflib opcodes for highlighting."""
        if original == current:
            return [("equal", 0, len(current), 0, len(current))]
        return difflib.SequenceMatcher(None, original, current).get_opcodes()
