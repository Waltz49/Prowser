#!/usr/bin/env python3
"""Model plugin registry (Create menu entries referencing shared pipelines)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from imagegen_plugins.image_gen_fields import FieldSpec
from imagegen_plugins.image_gen_pipeline_modes import (
    build_worker_payload,
    field_specs_for_pipeline,
    get_pipeline,
    menu_label_with_quant,
    merge_defaults,
    pipeline_is_available,
    worker_script_path,
)


class ImageGenModelPlugin:
    """One image-gen model; delegates run/fields to a pipeline."""

    def __init__(
        self,
        plugin_id: str,
        pipeline_id: str,
        display_name: str,
        model_defaults: Optional[Dict[str, Any]] = None,
        hf_model_id: str = "",
        *,
        function: str = "create",
        model_comment: str = "",
        lora_host_id: Optional[str] = None,
    ):
        # AI/dev: ``function`` is create | edit | expand | infill. Multiple plugins may
        # share a pipeline; the user picks the model in the function dialog dropdown.
        # ``model_comment`` is shown under the model pulldown (e.g. speed/quality notes).
        self.plugin_id = plugin_id
        self.pipeline_id = pipeline_id
        self.display_name = display_name
        self.model_defaults = dict(model_defaults or {})
        self.hf_model_id = hf_model_id
        self.function = function
        self.model_comment = model_comment.strip()
        self.lora_host_id = lora_host_id

    def is_available(self) -> bool:
        return pipeline_is_available(self.pipeline_id)

    def model_label(self, saved: Optional[Dict[str, Any]] = None) -> str:
        return menu_label_with_quant(self.display_name, saved or {})

    def menu_label(self, saved: Optional[Dict[str, Any]] = None) -> str:
        """Backward-compatible alias for model dropdown labels."""
        return self.model_label(saved)

    def merged_values(
        self, saved: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        out = merge_defaults(self.pipeline_id, self.model_defaults, saved)
        if self.hf_model_id:
            out["hf_model_id"] = self.hf_model_id
        return out

    def field_specs(self, saved: Optional[Dict[str, Any]] = None) -> List[FieldSpec]:
        values = self.merged_values(saved)
        return field_specs_for_pipeline(
            self.pipeline_id,
            values,
            plugin_hf_model_id=self.hf_model_id,
            lora_host_id=self.lora_host_id,
        )

    def worker_script(self) -> str:
        return worker_script_path(self.pipeline_id)

    def build_payload(
        self, values: Dict[str, Any], output_path: str
    ) -> Dict[str, Any]:
        get_pipeline(self.pipeline_id)
        return build_worker_payload(
            self.pipeline_id,
            values,
            output_path,
            self.hf_model_id,
        )

    def persist_reproducible_seed(
        self,
        run_values: Dict[str, Any],
        worker_result: Optional[Dict[str, Any]],
    ) -> None:
        """Store seed used on last run when random seed was enabled (pipeline-specific parsing)."""
        from imagegen_plugins.image_gen_seed_persistence import persist_used_seed_if_random

        persist_used_seed_if_random(
            self.function,
            self.pipeline_id,
            run_values,
            worker_result,
            fallback_plugin_id=self.plugin_id,
        )
