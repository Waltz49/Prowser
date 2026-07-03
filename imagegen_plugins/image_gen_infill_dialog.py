#!/usr/bin/env python3
"""Infill dialog: settings + Pixelmator export on Generate."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from imagegen_plugins.image_gen_dialog import ImageGenDialog, validate_copies_require_random_seed
from imagegen_plugins.image_gen_pipeline_modes import finalize_run_values
from imagegen_plugins.image_gen_persistence import save_dialog_settings
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.pixelmator_export import (
    export_pixelmator_base_and_mask,
    persist_pixelmator_exports,
)
from utils import show_styled_warning

INFILL_IMAGE_DIALOG_TITLE = "Infill with Pixelmator"


class ImageGenInfillDialog(ImageGenDialog):
    """Image-gen settings dialog; exports Pixelmator base/mask when Generate is clicked."""

    def __init__(
        self,
        plugins: List[ImageGenModelPlugin],
        function: str,
        parent=None,
        *,
        initial_plugin_id: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        initial_values: Optional[Dict[str, Any]] = None,
        window_title: str = INFILL_IMAGE_DIALOG_TITLE,
        panel_mode: bool = False,
        installed: Optional[List[ImageGenModelPlugin]] = None,
        plugins_by_id: Optional[Dict[str, ImageGenModelPlugin]] = None,
        installed_flags: Optional[Dict[str, bool]] = None,
    ):
        super().__init__(
            plugins,
            function,
            parent,
            initial_plugin_id=initial_plugin_id,
            initial_prompt=initial_prompt,
            initial_values=initial_values,
            window_title=window_title,
            persistent_panel=True,
            panel_mode=panel_mode,
            installed=installed,
            plugins_by_id=plugins_by_id,
            installed_flags=installed_flags,
        )

    def _prepare_pixelmator_values(self) -> Optional[Dict[str, Any]]:
        values = finalize_run_values(self.plugin.pipeline_id, self.collect_values())
        if not validate_copies_require_random_seed(self, values):
            return None

        base_path = str(values.get("pixelmator_base_path") or "")
        mask_path = str(values.get("pixelmator_mask_path") or "")
        if not (
            base_path
            and mask_path
            and os.path.isfile(base_path)
            and os.path.isfile(mask_path)
        ):
            ok, meta, err = export_pixelmator_base_and_mask()
            if not ok:
                show_styled_warning(
                    self,
                    "Infill",
                    err or "Could not export base and mask from Pixelmator Pro.",
                )
                return None

            values.update(persist_pixelmator_exports(meta))
        return values

    def run_generate(self) -> bool:
        values = self._prepare_pixelmator_values()
        if values is None:
            return False
        save_dialog_settings(
            self._function, values, active_plugin_id=self.plugin.plugin_id
        )
        from imagegen_plugins.image_gen_menu import start_imagegen_without_closing

        return start_imagegen_without_closing(
            self, self._function, self.plugin, values
        )

    def _on_generate(self) -> None:
        if self._panel_mode:
            self.run_generate()
            return
        values = self._prepare_pixelmator_values()
        if values is None:
            return
        save_dialog_settings(
            self._function, values, active_plugin_id=self.plugin.plugin_id
        )
        from imagegen_plugins.image_gen_menu import start_imagegen_without_closing

        start_imagegen_without_closing(self, self._function, self.plugin, values)
