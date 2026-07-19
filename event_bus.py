#!/usr/bin/env python3
"""
Event Bus
Central event dispatch for the image browser. Components subscribe to events
and react independently, enabling loose coupling and event-driven architecture.
"""

from typing import Any, Callable, Dict, List
from PySide6.QtCore import QObject, QTimer


# Event type constants
DIRECTORY_REQUESTED = "directory_requested"  # payload: (path: str, external_load: bool)
DIRECTORY_LOADED = "directory_loaded"  # payload: str (path)
DIRECTORY_CHANGED = "directory_changed"  # payload: str (path)
DISPLAYED_IMAGES_CHANGED = "displayed_images_changed"  # payload: List[str]
CURRENT_IMAGE_CHANGED = "current_image_changed"  # payload: str (path)
CURRENT_INDEX_CHANGED = "current_index_changed"  # payload: int (index in displayed_images)
SELECTION_CHANGED = "selection_changed"  # payload: Set[str]
FILES_CHANGED_ON_DISK = "files_changed_on_disk"  # payload: str (directory path)
REFRESH_REQUESTED = "refresh_requested"  # payload: bool (force)
VIEW_MODE_CHANGED = "view_mode_changed"  # payload: str (mode)
THUMBNAIL_CLICKED = "thumbnail_clicked"  # payload: (index, cmd_pressed, shift_pressed, macos_ctrl_pressed)
SETTINGS_CHANGED = "settings_changed"  # payload: dict (changed settings)
FILE_OPERATION_COMPLETE = "file_operation_complete"  # payload: (operation_type, paths, success)
DELETED_PLACEHOLDERS_CHANGED = "deleted_placeholders_changed"  # payload: None - views should repaint
FILE_METADATA_CHANGED = "file_metadata_changed"  # payload: (path: str, fields: Optional[set])


class EventBus(QObject):
    """
    Central event bus for the image browser.
    Components subscribe to event types and receive callbacks when events are emitted.
    Uses QTimer.singleShot for main-thread execution when emitting from background threads.
    """

    def __init__(self):
        super().__init__()
        self._subscribers: Dict[str, List[Callable]] = {}
        self._next_token = 0
        self._tokens: Dict[int, tuple] = {}  # token -> (event_type, callback)

    def subscribe(self, event_type: str, callback: Callable) -> int:
        """
        Subscribe to an event type.
        Returns an unsubscribe token that can be passed to unsubscribe().
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        token = self._next_token
        self._next_token += 1
        self._tokens[token] = (event_type, callback)
        return token

    def unsubscribe(self, token: int) -> None:
        """Unsubscribe using the token returned from subscribe()."""
        if token not in self._tokens:
            return
        event_type, callback = self._tokens.pop(token)
        if event_type in self._subscribers:
            try:
                self._subscribers[event_type].remove(callback)
            except ValueError:
                pass

    def emit(self, event_type: str, payload: Any = None) -> None:
        """
        Emit an event to all subscribers.
        If called from a non-main thread, defers to main thread via QTimer.singleShot.
        """
        if event_type not in self._subscribers or not self._subscribers[event_type]:
            return

        callbacks = list(self._subscribers[event_type])

        def invoke():
            for cb in callbacks:
                try:
                    if payload is not None:
                        # Only unpack tuples (multi-arg payloads like path, external_load, refresh_mode)
                        # Never unpack lists - they are single payloads (e.g. displayed_images)
                        if isinstance(payload, tuple) and len(payload) > 1:
                            cb(*payload)
                        else:
                            cb(payload)
                    else:
                        cb()
                except Exception:
                    import traceback
                    traceback.print_exc()

        # Invoke synchronously - all UI events originate on main thread.
        # Use QTimer.singleShot(0, invoke) if emitting from background thread.
        invoke()
