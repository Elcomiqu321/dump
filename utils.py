"""Shared utility helpers."""
from __future__ import annotations


def format_time_hms(seconds: float) -> str:
    """Format seconds to HH:MM:SS."""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_time_hms_ms(seconds: float) -> str:
    """Format seconds to HH:MM:SS.mmm."""
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def parse_time_hms_ms(timestamp_str: str) -> float:
    """Parse HH:MM:SS.mmm to seconds."""
    parts = timestamp_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp: {timestamp_str}")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_flexible_timestamp(timestamp_str: str) -> float:
    """Parse MM:SS.mmm or HH:MM:SS.mmm to seconds.

    Supports:
        59:54.110     ->  3594.110   (MM:SS.mmm)
        01:00:00.190  ->  3600.190   (HH:MM:SS.mmm)
        00:19.680     ->    19.680   (MM:SS.mmm)
    """
    parts = timestamp_str.strip().split(':')
    if len(parts) == 2:
        # MM:SS.mmm
        minutes = int(parts[0])
        seconds = float(parts[1])
        return minutes * 60 + seconds
    elif len(parts) == 3:
        # HH:MM:SS.mmm
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    else:
        raise ValueError(f"Invalid timestamp: {timestamp_str}")


def format_flexible_timestamp(seconds: float) -> str:
    """Format seconds to MM:SS.mmm or HH:MM:SS.mmm.

    Uses MM:SS.mmm for times under one hour, HH:MM:SS.mmm otherwise.
    """
    if seconds < 0:
        seconds = 0.0
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
    else:
        return f"{minutes:02d}:{secs:06.3f}"
