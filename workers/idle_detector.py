#!/usr/bin/env python3
"""
Idle Detector for Image Browser
Tracks user activity (mouse/keyboard events) and detects when the system is idle.

Idle also requires that no image-generation job is active (see set_generation_busy).
"""

from PySide6.QtCore import QObject, QTimer, Signal, QEvent
from PySide6.QtWidgets import QApplication
from thumbnails.thumbnail_constants import BACKGROUND_CLIP_IDLE_TIMEOUT_SECONDS


class IdleDetector(QObject):
    """Detects when the user has been idle for a specified duration"""
    
    idle_detected = Signal()  # Emitted when idle threshold is reached
    user_activity_detected = Signal()  # Emitted when user activity is detected
    
    def __init__(self, main_window, parent=None):
        """
        Initialize idle detector
        
        Args:
            main_window: Reference to the main ImageBrowserWindow instance
            parent: Parent QObject
        """
        super().__init__(parent)
        self.main_window = main_window
        self.idle_timer = QTimer()
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._on_idle_timeout)
        self.idle_timeout_ms = BACKGROUND_CLIP_IDLE_TIMEOUT_SECONDS * 1000
        self._enabled = False
        self._generation_busy = False
        # True after idle_detected until activity pauses scanning again.
        self._idle_scan_active = False
        # Keep re-sending pause while generation runs (long extractions / 2-min wait).
        self._generation_pause_reassert_timer = QTimer(self)
        self._generation_pause_reassert_timer.setInterval(2000)
        self._generation_pause_reassert_timer.timeout.connect(
            self._reassert_generation_pause
        )
        
        # Install event filter on QApplication to catch user activity events
        # This ensures we catch keypresses and mouse clicks over child widgets too
        app = QApplication.instance()
        if app:
            app.installEventFilter(self)
    
    def start(self):
        """Start idle detection"""
        self._enabled = True
        self.reset()
    
    def stop(self):
        """Stop idle detection"""
        self._enabled = False
        self.idle_timer.stop()
        self._generation_pause_reassert_timer.stop()
        self._idle_scan_active = False

    def is_generation_busy(self) -> bool:
        """True while image generation is treating the system as non-idle."""
        return self._generation_busy

    def set_generation_busy(self, busy: bool) -> None:
        """Treat an active image-generation job as non-idle (memory pressure)."""
        busy = bool(busy)
        if busy == self._generation_busy:
            return
        self._generation_busy = busy
        bc = getattr(self.main_window, "background_clip_controller", None)
        if busy:
            # Always pause background scanning for the job's full lifetime.
            self.idle_timer.stop()
            self._idle_scan_active = False
            self._pause_for_generation(bc)
            self._generation_pause_reassert_timer.start()
        else:
            self._generation_pause_reassert_timer.stop()
            if self._enabled:
                # Require a fresh idle window after generation ends.
                self.reset()
        debug = bool(getattr(self.main_window, "debug_mode", False))
        if debug:
            print(
                f"[idle] generation_busy={busy} enabled={self._enabled} "
                f"timer_active={self.idle_timer.isActive()}",
                flush=True,
            )

    def _pause_for_generation(self, bc=None) -> None:
        """Flush+pause background CLIP for an active generation job (memory pressure)."""
        if bc is None:
            bc = getattr(self.main_window, "background_clip_controller", None)
        if bc is None:
            return
        # Direct call only — do not also emit user_activity_detected (double pause).
        bc.flush_and_pause_process()
        bc.mark_paused_for_generation()

    def _reassert_generation_pause(self) -> None:
        """Resend pause while generation is busy so long worker cycles still stop."""
        if not self._generation_busy:
            self._generation_pause_reassert_timer.stop()
            return
        bc = getattr(self.main_window, "background_clip_controller", None)
        if bc is not None:
            # Reassert with plain pause (flush already done on transition to busy).
            bc.pause_process()
    
    def reset(self):
        """Reset idle timer (call when user activity detected)"""
        was_running = self.idle_timer.isActive()
        self.idle_timer.stop()
        if self._generation_busy:
            # Stay non-idle while a generation job is running.
            return
        if not self._enabled:
            return
        # Pause scanning on real activity even after idle already fired (timer stopped).
        if was_running or self._idle_scan_active:
            self._idle_scan_active = False
            self.user_activity_detected.emit()
        self.idle_timer.start(self.idle_timeout_ms)
    
    def _on_idle_timeout(self):
        """Called when idle timeout is reached"""
        if self._generation_busy or not self._enabled:
            return
        self._idle_scan_active = True
        debug = bool(getattr(self.main_window, "debug_mode", False))
        if debug:
            print("[idle] idle timeout → resume background scanning", flush=True)
        self.idle_detected.emit()
    
    def eventFilter(self, obj, event):
        """Event filter to detect user activity"""
        # Process events from any widget in the application
        # This ensures we catch mouse clicks and keypresses over child widgets
        
        # Press only — KeyRelease/MouseButtonRelease often fire from focus/fullscreen
        # churn and were preventing post-generation idle resume.
        event_type = event.type()
        if event_type in (
            QEvent.KeyPress,
            QEvent.MouseButtonPress,
            QEvent.MouseButtonDblClick,
        ):
            self.reset()
        
        return False  # Don't consume the event, let it propagate
