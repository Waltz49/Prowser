#!/usr/bin/env python3
"""Debug-mode model input/output logging to Tools > Debug > View log."""

from __future__ import annotations

import json
from typing import Any

from config import get_config
from debug_log import debug_timestamp
from print_call_decorator import relax_json_for_log

# Ephemeral worker keys omitted from imagegen payload logs.
_IMAGEGEN_OMIT_KEYS = frozenset(
    {
        "debug_mode",
        "_aspect_pad_temp_paths",
    }
)


def debug_mode_enabled() -> bool:
    return bool(get_config().load_settings().get("debug_mode", False))


def debug_mode_enabled_for_payload(payload: dict | None) -> bool:
    if isinstance(payload, dict) and "debug_mode" in payload:
        return bool(payload.get("debug_mode"))
    return debug_mode_enabled()


def _write_json_log(tag: str, kind: str, payload: dict) -> None:
    body = relax_json_for_log(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    )
    print(f"{debug_timestamp()} {tag} {kind}\n{body}\n", flush=True)


def log_model_input(tag: str, payload: dict) -> None:
    if not debug_mode_enabled():
        return
    _write_json_log(tag, "input", payload)


def log_model_output(tag: str, text: str) -> None:
    if not debug_mode_enabled():
        return
    _write_json_log(tag, "output", {"text": text})


def _imagegen_log_payload(payload: dict, **text_overrides: Any) -> dict:
    data = {k: v for k, v in payload.items() if k not in _IMAGEGEN_OMIT_KEYS}
    data.update(text_overrides)
    return data


def _effective_imagegen_prompt(payload: dict) -> str | None:
    """Return the prompt string as passed to the image model when known."""
    pipeline_id = str(payload.get("pipeline_id") or "")
    raw = str(payload.get("prompt") or "")
    if pipeline_id in ("mflux_fill_expand", "mflux_fill_infill"):
        try:
            from imagegen_plugins.pipelines.mflux_fill_expand import _outfill_prompt

            return _outfill_prompt(raw)
        except ImportError:
            return raw.strip() or None
    stripped = raw.strip()
    return stripped or None


def log_imagegen_payload(payload: dict, **text_overrides: Any) -> None:
    """Log the final worker payload text sent to an image generation model."""
    if not debug_mode_enabled_for_payload(payload):
        return
    pipeline_id = str(payload.get("pipeline_id") or "unknown")
    overrides = dict(text_overrides)
    if "prompt" not in overrides:
        effective = _effective_imagegen_prompt(payload)
        if effective is not None:
            overrides["prompt"] = effective
    log_data = _imagegen_log_payload(payload, **overrides)
    _write_json_log(f"imagegen.{pipeline_id}", "input", log_data)
