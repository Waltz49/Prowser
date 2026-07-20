#!/usr/bin/env python3
"""Shared service references for browser managers and views."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class BrowserServices:
    """Facade for dependencies that views/managers need without the full main window."""

    event_bus: Any
    file_data_model: Any
    selection_model: Any
    main_window: Any
    cache_manager: Optional[Any] = None
    config: Optional[Any] = None

    @property
    def displayed_images(self):
        return self.file_data_model.get_displayed_images()

    @property
    def current_image_path(self):
        return self.file_data_model.get_current_image_path()

    @property
    def selected_files(self):
        return self.selection_model.selected_files
