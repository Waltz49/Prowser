#!/usr/bin/env python3
"""Shared helpers for image-gen panels embedded in ImageGenUnifiedDialog."""

from __future__ import annotations

from typing import Any, Optional


class ImageGenPanelMixin:
    """Common panel-mode API used by the unified dialog shell."""

    def connect_panel_dirty_tracking(self) -> None:
        if not getattr(self, "_panel_mode", False):
            return
        from imagegen_plugins.image_gen_panel_dirty import connect_panel_field_widgets

        connect_panel_field_widgets(self, self.state_changed.emit)

    def selected_plugin_installed(self) -> bool:
        checker = getattr(self, "_selected_plugin_installed", None)
        if callable(checker):
            return bool(checker())
        return False

    def import_available(self) -> None:
        handler = getattr(self, "_on_import_available", None)
        if callable(handler):
            handler()

    def reflow_for_shell_resize(self) -> None:
        fields_panel = getattr(self, "_fields_panel", None)
        if fields_panel is None:
            return
        reflow = getattr(fields_panel, "reflow_controls_for_shell_resize", None)
        if callable(reflow):
            reflow()

    def prompt_edit_widget(self) -> Optional[Any]:
        getter = getattr(self, "_prompt_edit_widget", None)
        if callable(getter):
            return getter()
        return None

    def get_source_nav(self) -> Optional[Any]:
        return getattr(self, "_source_nav", None)
