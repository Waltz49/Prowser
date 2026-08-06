#!/usr/bin/env python3
"""Forward FilterSettingsModel Qt signals to EventBus."""

from typing import TYPE_CHECKING

from event_bus import FILTER_PATTERN_CHANGED, FILTER_TREE_MODE_CHANGED

if TYPE_CHECKING:
    from event_bus import EventBus
    from filter_settings_model import FilterSettingsModel


class FilterSettingsBridge:
    """Connects filter settings model signals to the event bus."""

    def __init__(self, model: "FilterSettingsModel", event_bus: "EventBus"):
        self._model = model
        self._event_bus = event_bus

    def connect(self) -> None:
        self._model.filter_pattern_changed.connect(self._on_filter_pattern_changed)
        self._model.filtered_tree_changed.connect(self._on_filtered_tree_changed)

    def _on_filter_pattern_changed(self, pattern: str) -> None:
        self._event_bus.emit(FILTER_PATTERN_CHANGED, pattern)

    def _on_filtered_tree_changed(self, mode: str) -> None:
        self._event_bus.emit(FILTER_TREE_MODE_CHANGED, mode)
