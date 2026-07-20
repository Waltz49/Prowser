#!/usr/bin/env python3
"""Forward SelectionModel Qt signals to EventBus."""

from typing import TYPE_CHECKING

from event_bus import SELECTION_CHANGED

if TYPE_CHECKING:
    from event_bus import EventBus
    from selection_model import SelectionModel


class SelectionModelBridge:
    """Connects selection model signals to the event bus."""

    def __init__(self, model: "SelectionModel", event_bus: "EventBus"):
        self._model = model
        self._event_bus = event_bus

    def connect(self) -> None:
        self._model.selection_changed.connect(self._on_selection_changed)

    def _on_selection_changed(self, selected: set, highlight_index=None) -> None:
        self._event_bus.emit(SELECTION_CHANGED, (selected, highlight_index))
