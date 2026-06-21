#!/usr/bin/env python3
"""
MVC Controller
Thin controller: receives user actions, updates model only.
Treats thumbnail, list, browse, and slideshow as views - all read from model.
"""

from typing import Any, Dict, List, Optional

from event_bus import THUMBNAIL_CLICKED


class MVCController:
    """
    Thin controller: receives user actions, updates model only.
    Subscribes to EventBus for user actions; calls services for side effects;
    updates FileDataModel as single source of truth.
    """

    def __init__(self, model, event_bus):
        """
        Args:
            model: FileDataModel instance (single source of truth)
            event_bus: EventBus instance for subscribing to user actions
        """
        self.model = model
        self.event_bus = event_bus
        self._services: Dict[str, Any] = {}
        self._subscription_tokens: List[int] = []

    def register_service(self, name: str, service: Any) -> None:
        """Register a service (directory_loader, sorting_manager, etc.) for controller to call."""
        self._services[name] = service

    def _get_service(self, name: str) -> Optional[Any]:
        return self._services.get(name)

    def wire_event_bus(self) -> None:
        """Subscribe to EventBus events. Call after services are registered."""
        tok = self.event_bus.subscribe(THUMBNAIL_CLICKED, self._on_thumbnail_clicked)
        if tok is not None:
            self._subscription_tokens.append(tok)

    def _on_thumbnail_clicked(self, index: int, cmd_pressed: bool, shift_pressed: bool, macos_ctrl_pressed: bool) -> None:
        """Handle thumbnail click.

        NavigationManager is subscribed before this handler and updates FileDataModel via
        _set_current_image_path_with_sync(path) using the path from the thumbnail widget.
        set_current_image_path() syncs _current_index from that path.

        The event payload index is the canvas/visual slot index; it is not always the index in
        displayed_images. Using model.get_displayed_images()[index] here overwrote the model
        with the wrong file after menu actions (subscriber order: nav, context menu, MVC).
        """
        # Multi-select is handled by SelectionManager; model current path/index come from NavigationManager

    def set_displayed_images(self, images: List[str], notify: bool = True) -> None:
        """Set displayed images via model."""
        self.model.set_displayed_images(images, notify=notify)

    def set_current_index(self, index: int, notify: bool = True) -> None:
        """Set current index via model."""
        self.model.set_current_index(index, notify=notify)

    def set_current_image_path(self, path: Optional[str], notify: bool = True) -> None:
        """Set current image path via model."""
        self.model.set_current_image_path(path, notify=notify)

    def set_current_directory(self, directory: Optional[str], notify: bool = True) -> None:
        """Set current directory via model."""
        self.model.set_current_directory(directory, notify=notify)

    def set_view_mode(self, mode: str, notify: bool = True) -> None:
        """Set view mode via model."""
        self.model.set_current_view_mode(mode, notify=notify)
