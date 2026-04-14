"""Audio Player - Handles audio/video playback using VLC."""
from __future__ import annotations

import time
from threading import Thread
from typing import Optional, Any


class AudioPlayer:
    """Manages audio/video playback with timestamp control."""

    def __init__(self):
        try:
            import vlc
            self.instance = vlc.Instance("--no-video", "--quiet")
            self.player = self.instance.media_player_new()
            self.available = True
            self.media: Optional[Any] = None
            self.duration = 0
            self.is_loaded = False
            self.stop_at_time = None
            self.monitor_thread = None
            self.monitoring = False
        except Exception as e:
            print(f"Warning: VLC initialization failed ({e}). Audio playback disabled.")
            self.available = False
            self.instance = None
            self.player = None
            self.media = None
            self.duration = 0
            self.is_loaded = False
            self.stop_at_time = None
            self.monitor_thread = None
            self.monitoring = False

    def load_media(self, file_path: str) -> bool:
        if not self.available:
            return False
        try:
            self.media = self.instance.media_new(file_path)
            self.player.set_media(self.media)
            self.is_loaded = True
            self.media.parse()
            self.duration = self.media.get_duration() / 1000.0
            return True
        except Exception as e:
            print(f"Error loading media: {e}")
            return False

    def play(self):
        if not self.available or not self.is_loaded:
            return
        self.player.play()

    def pause(self):
        if not self.available or not self.is_loaded:
            return
        self.player.pause()

    def stop(self):
        if not self.available or not self.is_loaded:
            return
        self.player.stop()
        self.monitoring = False

    def is_playing(self) -> bool:
        if not self.available or not self.is_loaded:
            return False
        return self.player.is_playing()

    def set_position(self, seconds: float):
        if not self.available or not self.is_loaded or self.duration <= 0:
            return
        position = seconds / self.duration
        self.player.set_position(position)

    def get_position(self) -> float:
        if not self.available or not self.is_loaded or self.duration <= 0:
            return 0.0
        position = self.player.get_position() * self.duration
        return max(0.0, position)

    def set_volume(self, volume: int):
        if not self.available or not self.is_loaded:
            return
        self.player.audio_set_volume(volume)

    def get_volume(self) -> int:
        if not self.available or not self.is_loaded:
            return 100
        return self.player.audio_get_volume()

    def play_segment(self, start_time: float, end_time: float):
        if not self.available or not self.is_loaded:
            return
        self.set_position(start_time)
        self.stop_at_time = end_time
        self.play()
        self._start_monitoring()

    def _start_monitoring(self):
        if not self.available or self.monitoring:
            return
        self.monitoring = True
        self.monitor_thread = Thread(target=self._monitor_playback, daemon=True)
        self.monitor_thread.start()

    def _monitor_playback(self):
        while self.monitoring and self.is_loaded:
            if self.stop_at_time is not None:
                current_pos = self.get_position()
                if current_pos >= self.stop_at_time:
                    self.pause()
                    self.stop_at_time = None
                    self.monitoring = False
                    break
            time.sleep(0.1)

    def get_duration(self) -> float:
        return self.duration

    def release(self):
        if not self.available:
            return
        self.monitoring = False
        if self.player:
            self.player.stop()
            self.player.release()
        if self.instance:
            self.instance.release()
