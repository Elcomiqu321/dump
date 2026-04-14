"""Transcript Manager - Handles loading, saving, and managing transcript data."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from utils import (
    format_time_hms_ms,
    parse_time_hms_ms,
    parse_flexible_timestamp,
    format_flexible_timestamp,
)


@dataclass
class TranscriptSegment:
    """Represents a single transcript segment with timing and speaker info."""

    speaker: str
    start: float  # in seconds
    end: float  # in seconds
    text: str
    index: int
    speaker_validated: bool = False
    content_validated: bool = False
    validated_by: Optional[str] = None
    validated_at: Optional[str] = None

    def format_time(self, seconds: float) -> str:
        """Format seconds using flexible format (MM:SS.mmm or HH:MM:SS.mmm)."""
        return format_flexible_timestamp(seconds)

    def get_display_text(self) -> str:
        """Get formatted text for display."""
        return f"[{self.format_time(self.start)}] {self.speaker}: {self.text}"


class TranscriptManager:
    """Manages transcript loading, editing, and saving."""

    def __init__(self):
        self.segments: List[TranscriptSegment] = []
        self.original_file: str = ""
        self.output_file: str = ""

    def load_transcript(self, file_path: str) -> bool:
        """Load transcript from JSON or TXT file."""
        try:
            _, ext = os.path.splitext(file_path)

            if ext.lower() == ".json":
                success = self._load_json(file_path)
            elif ext.lower() == ".txt":
                success = self._load_txt(file_path)
            else:
                print(f"Unsupported file format: {ext}")
                return False

            if success:
                self.original_file = file_path
                # Always output as _EDITED.txt
                base, _ = os.path.splitext(file_path)
                if base.lower().endswith("_edited"):
                    base = base[: -len("_edited")]
                self.output_file = f"{base}_EDITED.txt"
            return success

        except Exception as e:
            print(f"Error loading transcript: {e}")
            return False

    def _load_json(self, file_path: str) -> bool:
        """Load transcript from JSON file."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.segments = []
        for idx, item in enumerate(data):
            segment = TranscriptSegment(
                speaker=item.get("speaker", ""),
                start=float(item["start"]),
                end=float(item["end"]),
                text=item["text"],
                index=idx,
                speaker_validated=item.get("speaker_validated", False),
                content_validated=item.get("content_validated", False),
                validated_by=item.get("validated_by"),
                validated_at=item.get("validated_at"),
            )
            self.segments.append(segment)

        return True

    def _load_txt(self, file_path: str) -> bool:
        """Load transcript from TXT file.

        Supported formats:
            [MM:SS.mmm --> MM:SS.mmm]  [SPEAKER_XX]: Text
            [HH:MM:SS.mmm --> HH:MM:SS.mmm]  [SPEAKER_XX]: Text
            [MM:SS.mmm --> MM:SS.mmm]  Text  (no speaker)
        Also supports the older format:
            [HH:MM:SS.mmm - HH:MM:SS.mmm] Speaker: Text
        """
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.segments = []

        # New format: [timestamp --> timestamp]  [SPEAKER]: text
        pattern_new = (
            r"\[([^\]]+?)\s*-->\s*([^\]]+?)\]"   # [start --> end]
            r"\s*"                                  # whitespace
            r"(?:\[([^\]]*)\]\s*:)?"               # optional [SPEAKER]:
            r"\s*(.*)"                              # text
        )

        # Old format: [HH:MM:SS.mmm - HH:MM:SS.mmm] Speaker: Text
        pattern_old = (
            r"\[(\d{2}:\d{2}:\d{2}\.\d{3})\s*-\s*(\d{2}:\d{2}:\d{2}\.\d{3})\]"
            r"\s*([^:]+):\s*(.+)"
        )

        idx = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Try new format first
            match = re.match(pattern_new, line)
            if match:
                start_str, end_str, speaker_raw, text = match.groups()
                try:
                    start_seconds = parse_flexible_timestamp(start_str)
                    end_seconds = parse_flexible_timestamp(end_str)
                except ValueError:
                    continue

                speaker = speaker_raw.strip() if speaker_raw else ""
                segment = TranscriptSegment(
                    speaker=speaker,
                    start=start_seconds,
                    end=end_seconds,
                    text=text.strip(),
                    index=idx,
                )
                self.segments.append(segment)
                idx += 1
                continue

            # Try old format
            match = re.match(pattern_old, line)
            if match:
                start_str, end_str, speaker, text = match.groups()
                try:
                    start_seconds = parse_time_hms_ms(start_str)
                    end_seconds = parse_time_hms_ms(end_str)
                except ValueError:
                    continue

                segment = TranscriptSegment(
                    speaker=speaker.strip(),
                    start=start_seconds,
                    end=end_seconds,
                    text=text.strip(),
                    index=idx,
                )
                self.segments.append(segment)
                idx += 1

        return len(self.segments) > 0

    def save_transcript(self, file_path: str = None) -> bool:
        """Save transcript. Always writes the new --> format as TXT."""
        try:
            target_file = file_path if file_path else self.output_file
            _, ext = os.path.splitext(target_file)

            if ext.lower() == ".json":
                return self._save_json(target_file)
            else:
                return self._save_txt(target_file)

        except Exception as e:
            print(f"Error saving transcript: {e}")
            return False

    def _save_json(self, file_path: str) -> bool:
        """Save transcript as JSON with atomic write."""
        if os.path.exists(file_path):
            backup_path = f"{file_path}.backup"
            shutil.copy2(file_path, backup_path)

        file_dir = os.path.dirname(file_path) or "."
        temp_fd, temp_path = tempfile.mkstemp(suffix=".json", dir=file_dir, text=True)

        try:
            data = []
            for segment in self.segments:
                data.append(
                    {
                        "speaker": segment.speaker,
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text,
                        "speaker_validated": segment.speaker_validated,
                        "content_validated": segment.content_validated,
                        "validated_by": segment.validated_by,
                        "validated_at": segment.validated_at,
                    }
                )

            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            shutil.move(temp_path, file_path)
            return True

        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            print(f"Error saving JSON: {e}")
            return False

    def _save_txt(self, file_path: str) -> bool:
        """Save transcript as TXT in the --> format with atomic write."""
        if os.path.exists(file_path):
            backup_path = f"{file_path}.backup"
            shutil.copy2(file_path, backup_path)

        file_dir = os.path.dirname(file_path) or "."
        temp_fd, temp_path = tempfile.mkstemp(suffix=".txt", dir=file_dir, text=True)

        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                for segment in self.segments:
                    start_str = format_flexible_timestamp(segment.start)
                    end_str = format_flexible_timestamp(segment.end)
                    if segment.speaker:
                        line = f"[{start_str} --> {end_str}]  [{segment.speaker}]: {segment.text}\n"
                    else:
                        line = f"[{start_str} --> {end_str}]  {segment.text}\n"
                    f.write(line)

            shutil.move(temp_path, file_path)
            return True

        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            print(f"Error saving TXT: {e}")
            return False

    # ── Segment access / mutation ──────────────────────────────────────

    def update_segment_text(self, index: int, new_text: str):
        if 0 <= index < len(self.segments):
            self.segments[index].text = new_text

    def update_segment_speaker(self, index: int, new_speaker: str):
        if 0 <= index < len(self.segments):
            self.segments[index].speaker = new_speaker

    def get_segment(self, index: int) -> Optional[TranscriptSegment]:
        if 0 <= index < len(self.segments):
            return self.segments[index]
        return None

    def get_segment_count(self) -> int:
        return len(self.segments)

    def get_segments_range(self, start_idx: int, count: int) -> List[TranscriptSegment]:
        end_idx = min(start_idx + count, len(self.segments))
        return self.segments[start_idx:end_idx]

    def get_time_range_for_segments(self, start_idx: int, count: int) -> tuple:
        segments = self.get_segments_range(start_idx, count)
        if not segments:
            return (0, 0)
        return (min(s.start for s in segments), max(s.end for s in segments))

    def get_total_duration(self) -> float:
        if not self.segments:
            return 0.0
        return max(seg.end for seg in self.segments)

    def insert_segment(
        self, position: int, speaker: str, start: float, end: float, text: str
    ) -> bool:
        try:
            new_segment = TranscriptSegment(
                speaker=speaker, start=start, end=end, text=text, index=position
            )
            self.segments.insert(position, new_segment)
            for idx in range(position + 1, len(self.segments)):
                self.segments[idx].index = idx
            return True
        except Exception as e:
            print(f"Error inserting segment: {e}")
            return False

    def delete_segment(self, index: int) -> bool:
        """Delete a segment and re-index."""
        if 0 <= index < len(self.segments):
            del self.segments[index]
            for idx in range(index, len(self.segments)):
                self.segments[idx].index = idx
            return True
        return False

    # ── Validation ─────────────────────────────────────────────────────

    def validate_speaker(self, index: int, validated_by: str) -> bool:
        if 0 <= index < len(self.segments):
            self.segments[index].speaker_validated = True
            self.segments[index].validated_by = validated_by
            self.segments[index].validated_at = datetime.now().isoformat()
            return True
        return False

    def validate_content(self, index: int, validated_by: str) -> bool:
        if 0 <= index < len(self.segments):
            self.segments[index].content_validated = True
            self.segments[index].validated_by = validated_by
            self.segments[index].validated_at = datetime.now().isoformat()
            return True
        return False

    def validate_row(self, index: int, validated_by: str) -> bool:
        if 0 <= index < len(self.segments):
            self.segments[index].speaker_validated = True
            self.segments[index].content_validated = True
            self.segments[index].validated_by = validated_by
            self.segments[index].validated_at = datetime.now().isoformat()
            return True
        return False

    def validate_to_index(self, end_index: int, validated_by: str) -> int:
        count = 0
        now = datetime.now().isoformat()
        for idx in range(min(end_index + 1, len(self.segments))):
            self.segments[idx].speaker_validated = True
            self.segments[idx].content_validated = True
            self.segments[idx].validated_by = validated_by
            self.segments[idx].validated_at = now
            count += 1
        return count

    def is_fully_validated(self, index: int) -> bool:
        if 0 <= index < len(self.segments):
            seg = self.segments[index]
            return seg.speaker_validated and seg.content_validated
        return False

    def get_validation_status(self, index: int) -> dict:
        if 0 <= index < len(self.segments):
            seg = self.segments[index]
            return {
                "speaker_validated": seg.speaker_validated,
                "content_validated": seg.content_validated,
                "validated_by": seg.validated_by,
                "validated_at": seg.validated_at,
            }
        return {
            "speaker_validated": False,
            "content_validated": False,
            "validated_by": None,
            "validated_at": None,
        }

    def get_validation_progress(self) -> dict:
        if not self.segments:
            return {
                "total": 0,
                "fully_validated": 0,
                "speaker_only": 0,
                "content_only": 0,
                "unvalidated": 0,
                "percentage": 0.0,
            }

        total = len(self.segments)
        fully = sum(1 for s in self.segments if s.speaker_validated and s.content_validated)
        sp_only = sum(1 for s in self.segments if s.speaker_validated and not s.content_validated)
        ct_only = sum(1 for s in self.segments if s.content_validated and not s.speaker_validated)
        unval = sum(1 for s in self.segments if not s.speaker_validated and not s.content_validated)

        return {
            "total": total,
            "fully_validated": fully,
            "speaker_only": sp_only,
            "content_only": ct_only,
            "unvalidated": unval,
            "percentage": (fully / total * 100) if total > 0 else 0.0,
        }
