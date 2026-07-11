#!/usr/bin/env python3
"""Model plugin registry (Create menu entries referencing shared pipelines)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from imagegen_plugins.image_gen_fields import (
    FieldLayoutBuilder,
    FieldSpec,
    flatten_field_specs,
    resolve_plugin_field_layout,
)
from imagegen_plugins.image_gen_pipeline_modes import (
    build_worker_payload,
    get_pipeline,
    merge_defaults,
    pipeline_is_available,
    worker_script_path,
)

_MFLUX_QUANT_STATUS_PIPELINES = frozenset(
    {
        "flux_schnell_mflux_play",
        "mflux_fill_expand",
        "mflux_fill_infill",
        "mflux_flux2_klein_create",
        "mflux_flux2_klein_edit",
        "mflux_flux2_klein_expand",
    }
)


def format_quantize_status_value(key: str, value: Any) -> str | None:
    """Display digits for job status / EXIF Q: from a plugin quantize_status_key."""
    if value is None:
        return None
    if key == "mlx_tier":
        from imagegen_plugins.sceneworks_klein_mlx import mlx_tier_status_quant_label

        return mlx_tier_status_quant_label(value)
    try:
        return str(int(value))
    except (TypeError, ValueError):
        text = str(value).strip()
        return text or None


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
        max_generation_dimension: int = 1024,
        field_layout_builder: Optional[FieldLayoutBuilder] = None,
        quantize_status_key: str = "mflux_quantize",
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
        self.max_generation_dimension = int(max_generation_dimension)
        self.field_layout_builder = field_layout_builder
        self.quantize_status_key = quantize_status_key

    def pipeline_reports_quantization(self) -> bool:
        return self.pipeline_id in _MFLUX_QUANT_STATUS_PIPELINES

    def quantize_status_value(
        self, values: Optional[Dict[str, Any]] = None
    ) -> str | None:
        if not self.pipeline_reports_quantization():
            return None
        data = dict(values or {})
        return format_quantize_status_value(
            self.quantize_status_key,
            data.get(self.quantize_status_key),
        )

    def quantize_for_exif(
        self, values: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        label = self.quantize_status_value(values)
        if label is None:
            return None
        try:
            return int(label)
        except ValueError:
            return None

    def is_available(self) -> bool:
        return pipeline_is_available(self.pipeline_id)

    def model_label(self, saved: Optional[Dict[str, Any]] = None) -> str:
        return self.display_name

    def menu_label(self, saved: Optional[Dict[str, Any]] = None) -> str:
        """Backward-compatible alias for model dropdown labels."""
        return self.model_label(saved)

    def merged_values(
        self, saved: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin
        from imagegen_plugins.image_gen_pipeline_modes import clamp_output_dims_in_values

        out = merge_defaults(self.pipeline_id, self.model_defaults, saved)
        if self.quantize_status_key != "mflux_quantize":
            out.pop("mflux_quantize", None)
        if self.hf_model_id:
            out["hf_model_id"] = self.hf_model_id
        effective_max = effective_max_for_plugin(self)
        return clamp_output_dims_in_values(
            self.pipeline_id,
            out,
            effective_max_side=effective_max,
        )

    def field_specs(self, saved: Optional[Dict[str, Any]] = None) -> List[FieldSpec]:
        from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin

        values = self.merged_values(saved)
        layout = resolve_plugin_field_layout(
            self,
            values,
            effective_max_side=effective_max_for_plugin(self),
        )
        return flatten_field_specs(layout)

    def worker_script(self) -> str:
        return worker_script_path(self.pipeline_id)

    def build_payload(
        self,
        values: Dict[str, Any],
        output_path: str,
        *,
        apply_image_exit: bool = True,
    ) -> Dict[str, Any]:
        from imagegen_plugins.image_gen_dim_limits import effective_max_for_plugin

        get_pipeline(self.pipeline_id)
        return build_worker_payload(
            self.pipeline_id,
            values,
            output_path,
            self.hf_model_id,
            effective_max_side=effective_max_for_plugin(self),
            apply_image_exit=apply_image_exit,
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
