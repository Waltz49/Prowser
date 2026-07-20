#!/usr/bin/env python3
"""
Browser Controller
Central command handler: receives user actions, delegates to services, updates model.
"""

from typing import Any, Dict, List, Optional

from event_bus import THUMBNAIL_CLICKED


class BrowserController:
    """
    Command controller: subscribes to user-intent events and delegates to registered services.
    Views emit commands; controller updates model via services.
    """

    def __init__(self, model, event_bus, main_window=None):
        self.model = model
        self.event_bus = event_bus
        self.main_window = main_window
        self._services: Dict[str, Any] = {}
        self._subscription_tokens: List[int] = []

    def register_service(self, name: str, service: Any) -> None:
        """Register a service (navigation, selection, directory_loader, etc.)."""
        self._services[name] = service

    def _get_service(self, name: str) -> Optional[Any]:
        return self._services.get(name)

    def wire_event_bus(self) -> None:
        """Subscribe to command events. Call after services are registered."""
        tok = self.event_bus.subscribe(THUMBNAIL_CLICKED, self._on_thumbnail_clicked)
        if tok is not None:
            self._subscription_tokens.append(tok)

    def _on_thumbnail_clicked(
        self,
        index: int,
        cmd_pressed: bool,
        shift_pressed: bool,
        macos_ctrl_pressed: bool,
    ) -> None:
        """Handle thumbnail click — sole THUMBNAIL_CLICKED command handler."""
        nav = self._get_service("navigation")
        if nav:
            nav.handle_thumbnail_click(index, cmd_pressed, shift_pressed, macos_ctrl_pressed)

    def set_displayed_images(self, images: List[str], notify: bool = True) -> None:
        self.model.set_displayed_images(images, notify=notify)

    def set_current_index(self, index: int, notify: bool = True) -> None:
        self.model.set_current_index(index, notify=notify)

    def set_current_image_path(self, path: Optional[str], notify: bool = True) -> None:
        self.model.set_current_image_path(path, notify=notify)

    def set_current_directory(self, directory: Optional[str], notify: bool = True) -> None:
        self.model.set_current_directory(directory, notify=notify)

    def set_view_mode(self, mode: str, notify: bool = True) -> None:
        self.model.set_current_view_mode(mode, notify=notify)
