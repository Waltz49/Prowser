#!/usr/bin/env python3
"""Forward FileDataModel Qt signals to EventBus (main-thread, named handlers)."""

from typing import TYPE_CHECKING

from event_bus import (
    CURRENT_IMAGE_CHANGED,
    CURRENT_INDEX_CHANGED,
    DIRECTORY_CHANGED,
    DISPLAYED_IMAGES_CHANGED,
    VIEW_MODE_CHANGED,
)

if TYPE_CHECKING:
    from event_bus import EventBus
    from file_data_model import FileDataModel


class WindowModelBridge:
    """Connects model signals to the event bus for loose-coupled subscribers."""

    def __init__(self, model: "FileDataModel", event_bus: "EventBus"):
        self._model = model
        self._event_bus = event_bus

    def connect(self) -> None:
        self._model.displayed_images_changed.connect(self._on_displayed_images_changed)
        self._model.current_image_changed.connect(self._on_current_image_changed)
        self._model.directory_changed.connect(self._on_directory_changed)
        self._model.current_index_changed.connect(self._on_current_index_changed)
        self._model.view_mode_changed.connect(self._on_view_mode_changed)

    def _on_displayed_images_changed(self, images: list) -> None:
        self._event_bus.emit(DISPLAYED_IMAGES_CHANGED, images)

    def _on_current_image_changed(self, path: str) -> None:
        self._event_bus.emit(CURRENT_IMAGE_CHANGED, path)

    def _on_directory_changed(self, path: str) -> None:
        self._event_bus.emit(DIRECTORY_CHANGED, path)

    def _on_current_index_changed(self, index: int) -> None:
        self._event_bus.emit(CURRENT_INDEX_CHANGED, index)

    def _on_view_mode_changed(self, mode: str) -> None:
        self._event_bus.emit(VIEW_MODE_CHANGED, mode)
