"""Audit Logger - Tracks all changes made to transcript files."""
import json
import os
import hashlib
import getpass
from datetime import datetime
from typing import Optional, Dict, Any, List


class AuditLogger:
    """Manages audit logging for transcript editing sessions."""
    
    def __init__(self, transcript_file_path: str):
        self.transcript_file_path = transcript_file_path
        self.audit_file_path = self._get_audit_file_path(transcript_file_path)
        
        # Session data
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_start_time = datetime.now().isoformat()
        self.session_end_time = None
        self.user = getpass.getuser()
        
        # Current session changes
        self.session_changes = []
        self.segments_affected = set()
        self.session_properly_closed = False
        self.pending_save = False  # Track if changes need to be saved
        
        # Load or create audit log
        self.audit_data = self._load_or_create_audit_log()
        
        # Start new session in audit log
        self._start_new_session()
        
    def _get_audit_file_path(self, transcript_path: str) -> str:
        """Generate audit log file path based on transcript filename."""
        base, ext = os.path.splitext(transcript_path)
        return f"{base}_audit.json"
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of the transcript file."""
        try:
            if not os.path.exists(file_path):
                return ""
            
            sha256_hash = hashlib.sha256()
            with open(file_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    sha256_hash.update(byte_block)
            return sha256_hash.hexdigest()
        except Exception as e:
            print(f"Error calculating file hash: {e}")
            return ""
    
    def _load_or_create_audit_log(self) -> Dict[str, Any]:
        """Load existing audit log or create new one."""
        if os.path.exists(self.audit_file_path):
            try:
                with open(self.audit_file_path, 'r', encoding='utf-8') as f:
                    audit_data = json.load(f)
                print(f"Loaded existing audit log: {self.audit_file_path}")
                return audit_data
            except Exception as e:
                print(f"Error loading audit log: {e}")
                return self._create_new_audit_structure()
        else:
            return self._create_new_audit_structure()
    
    def _create_new_audit_structure(self) -> Dict[str, Any]:
        """Create new audit log structure."""
        return {
            "transcript_file": os.path.basename(self.transcript_file_path),
            "transcript_path": self.transcript_file_path,
            "created_date": datetime.now().isoformat(),
            "file_hash_on_load": self._calculate_file_hash(self.transcript_file_path),
            "sessions": []
        }
    
    def _start_new_session(self):
        """Start a new session and mark previous session as crashed if not properly closed."""
        # Check if last session was properly closed
        if self.audit_data["sessions"] and len(self.audit_data["sessions"]) > 0:
            last_session = self.audit_data["sessions"][-1]
            if not last_session.get("properly_closed", False):
                # Mark as crashed
                last_session["crashed"] = True
                last_session["notes"] = "Session ended unexpectedly (crash or forced close)"
                # Save this update
                self._save_audit_log()
        
        # Initialize current session in the audit data
        self.current_session = {
            "session_id": self.session_id,
            "user": self.user,
            "start_time": self.session_start_time,
            "end_time": None,
            "properly_closed": False,
            "duration_seconds": 0,
            "duration_formatted": "0s",
            "total_changes": 0,
            "segments_affected_count": 0,
            "segments_affected": [],
            "change_types": {},
            "file_hash_on_close": "",
            "changes": []
        }
        
        # Append to audit data immediately
        self.audit_data["sessions"].append(self.current_session)
        self._save_audit_log()
    
    def _update_current_session(self):
        """Update current session data in the audit log."""
        if self.audit_data["sessions"]:
            # Update the last session (current session)
            self.audit_data["sessions"][-1] = {
                "session_id": self.session_id,
                "user": self.user,
                "start_time": self.session_start_time,
                "end_time": self.session_end_time,
                "properly_closed": self.session_properly_closed,
                "duration_seconds": self._calculate_duration(),
                "duration_formatted": self._format_duration(self._calculate_duration()),
                "total_changes": len(self.session_changes),
                "segments_affected_count": len(self.segments_affected),
                "segments_affected": sorted(list(self.segments_affected)),
                "change_types": self._count_change_types(),
                "file_hash_on_close": self._calculate_file_hash(self.transcript_file_path) if self.session_properly_closed else "",
                "changes": self.session_changes
            }
    
    def _calculate_duration(self) -> float:
        """Calculate session duration in seconds."""
        start = datetime.fromisoformat(self.session_start_time)
        end_time = self.session_end_time if self.session_end_time else datetime.now().isoformat()
        end = datetime.fromisoformat(end_time)
        return (end - start).total_seconds()
    
    def _auto_save(self):
        """Mark that changes are pending save (actual save done by GUI timer)."""
        self.pending_save = True
    
    def save_if_needed(self) -> bool:
        """Save audit log if there are pending changes."""
        if self.pending_save:
            self._update_current_session()
            result = self._save_audit_log()
            if result:
                self.pending_save = False
            return result
        return True
    
    def log_edit(self, segment_index: int, start_time: float, end_time: float,
                 field: str, old_value: str, new_value: str):
        """Log an edit to a segment."""
        if old_value == new_value:
            return  # No actual change
        
        change = {
            "type": "edit",
            "timestamp": datetime.now().isoformat(),
            "segment_index": segment_index,
            "segment_start_time": start_time,
            "segment_end_time": end_time,
            "field": field,  # "speaker" or "text"
            "old_value": old_value,
            "new_value": new_value
        }
        
        self.session_changes.append(change)
        self.segments_affected.add(segment_index)
        self._auto_save()  # Auto-save after each change
    
    def log_insert(self, segment_index: int, start_time: float, end_time: float,
                   speaker: str, text: str):
        """Log insertion of a new segment."""
        change = {
            "type": "insert",
            "timestamp": datetime.now().isoformat(),
            "segment_index": segment_index,
            "segment_start_time": start_time,
            "segment_end_time": end_time,
            "speaker": speaker,
            "text": text
        }
        
        self.session_changes.append(change)
        self.segments_affected.add(segment_index)
        self._auto_save()  # Auto-save after each change
    
    def log_delete(self, segment_index: int, start_time: float, end_time: float,
                   speaker: str, text: str):
        """Log deletion of a segment."""
        change = {
            "type": "delete",
            "timestamp": datetime.now().isoformat(),
            "segment_index": segment_index,
            "segment_start_time": start_time,
            "segment_end_time": end_time,
            "speaker": speaker,
            "text": text
        }
        
        self.session_changes.append(change)
        self.segments_affected.add(segment_index)
        self._auto_save()  # Auto-save after each change
    
    def log_undo(self, action_type: str, segment_index: int, start_time: float, 
                 end_time: float, details: str = ""):
        """Log an undo action."""
        change = {
            "type": "undo",
            "timestamp": datetime.now().isoformat(),
            "undone_action": action_type,  # "edit", "insert", "delete"
            "segment_index": segment_index,
            "segment_start_time": start_time,
            "segment_end_time": end_time,
            "details": details
        }
        
        self.session_changes.append(change)
        self.segments_affected.add(segment_index)
        self._auto_save()  # Auto-save after each change
    
    def log_export(self, export_path: str, format: str):
        """Log file export action."""
        change = {
            "type": "export",
            "timestamp": datetime.now().isoformat(),
            "export_path": export_path,
            "format": format,
            "file_hash": self._calculate_file_hash(export_path)
        }
        
        self.session_changes.append(change)
        self._auto_save()  # Auto-save after each change
    
    def log_validation(self, validation_type: str, segment_index: int, start_time: float,
                      end_time: float, field: Optional[str] = None, end_index: Optional[int] = None,
                      count: Optional[int] = None):
        """Log validation action.
        
        Args:
            validation_type: 'row', 'speaker', 'content', 'to_index'
            segment_index: Index of the segment being validated
            start_time: Start time of the segment
            end_time: End time of the segment
            field: 'speaker', 'content', or 'both' for row validation
            end_index: For 'to_index' validation, the last index validated
            count: Number of segments validated (for 'to_index')
        """
        change = {
            "type": "validation",
            "validation_type": validation_type,
            "timestamp": datetime.now().isoformat(),
            "segment_index": segment_index,
            "segment_start_time": start_time,
            "segment_end_time": end_time
        }
        
        if field:
            change["field"] = field
        if end_index is not None:
            change["end_index"] = end_index
        if count is not None:
            change["segments_validated_count"] = count
        
        self.session_changes.append(change)
        if segment_index is not None:
            self.segments_affected.add(segment_index)
        if end_index is not None:
            for idx in range(segment_index, end_index + 1):
                self.segments_affected.add(idx)
        self._auto_save()  # Auto-save after each change
    
    def end_session(self) -> bool:
        """End the current session and save audit log."""
        try:
            self.session_end_time = datetime.now().isoformat()
            self.session_properly_closed = True
            
            # Update and save final session state
            self._update_current_session()
            return self._save_audit_log()
            
        except Exception as e:
            print(f"Error ending session: {e}")
            return False
    
    def _format_duration(self, seconds: float) -> str:
        """Format duration in human-readable format."""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"
    
    def _count_change_types(self) -> Dict[str, int]:
        """Count occurrences of each change type."""
        counts = {}
        for change in self.session_changes:
            change_type = change.get("type", "unknown")
            counts[change_type] = counts.get(change_type, 0) + 1
        return counts
    
    def _save_audit_log(self) -> bool:
        """Save audit log to file."""
        try:
            with open(self.audit_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.audit_data, f, indent=2, ensure_ascii=False)
            print(f"Audit log saved: {self.audit_file_path}")
            return True
        except Exception as e:
            print(f"Error saving audit log: {e}")
            return False
    
    def get_session_summary(self) -> Dict[str, Any]:
        """Get current session summary without ending it."""
        return {
            "session_id": self.session_id,
            "user": self.user,
            "start_time": self.session_start_time,
            "total_changes": len(self.session_changes),
            "segments_affected": len(self.segments_affected),
            "change_types": self._count_change_types()
        }
