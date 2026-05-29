#!/usr/bin/env python3
"""Infill dialog: settings + Pixelmator export on Generate."""

from __future__ import annotations

from typing import List, Optional

from imagegen_plugins.image_gen_dialog import ImageGenDialog, validate_copies_require_random_seed
from imagegen_plugins.image_gen_pipeline_modes import finalize_run_values
from imagegen_plugins.image_gen_persistence import save_dialog_settings
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.pixelmator_export import (
    export_pixelmator_base_and_mask,
    persist_pixelmator_exports,
)
from utils import show_styled_warning

INFILL_IMAGE_DIALOG_TITLE = "Infill"


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
        window_title: str = INFILL_IMAGE_DIALOG_TITLE,
    ):
        super().__init__(
            plugins,
            function,
            parent,
            initial_plugin_id=initial_plugin_id,
            initial_prompt=initial_prompt,
            window_title=window_title,
        )

    def _on_generate(self) -> None:
        values = finalize_run_values(self.plugin.pipeline_id, self.collect_values())
        if not validate_copies_require_random_seed(self, values):
            return

        ok, meta, err = export_pixelmator_base_and_mask()
        if not ok:
            show_styled_warning(
                self,
                "Infill",
                err or "Could not export base and mask from Pixelmator Pro.",
            )
            return

        values.update(persist_pixelmator_exports(meta))
        save_dialog_settings(self._function, values)
        from imagegen_plugins.image_gen_active_model import save_active_plugin_id_for_function

        save_active_plugin_id_for_function(self._function, self.plugin.plugin_id)
        self._result_values = values
        self.accept()
