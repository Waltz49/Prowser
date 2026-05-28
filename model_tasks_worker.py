#!/usr/bin/env python3
"""
Persistent subprocess worker for local image generation and LM Studio captions.

Reads newline-delimited JSON commands on stdin; writes newline-delimited JSON on stdout.
Keeps at most one model family loaded: image (mflux) or LM Studio VLM.
"""

from __future__ import annotations

import gc
import json
import sys
import traceback
from typing import Any, Dict, Optional

_LOADED_KIND: Optional[str] = None  # None | "image" | "lmstudio"


def _emit(msg: Dict[str, Any]) -> None:
    print(json.dumps(msg), flush=True)


def _unload_lmstudio_models() -> None:
    global _LOADED_KIND
    from lmstudio_caption import unload_all_lmstudio_models

    unload_all_lmstudio_models()
    if _LOADED_KIND == "lmstudio":
        _LOADED_KIND = None


def _unload_image_model() -> None:
    global _LOADED_KIND
    try:
        from imagegen_plugins.pipelines.sana_sprint import unload_pipeline

        unload_pipeline()
    except Exception:
        pass
    gc.collect()
    if _LOADED_KIND == "image":
        _LOADED_KIND = None


def _ensure_image_mode() -> None:
    _unload_lmstudio_models()


def _ensure_lmstudio_mode() -> None:
    _unload_image_model()


def _log_worker_error(context: str, exc: BaseException) -> None:
    try:
        print(f"[model_tasks_worker] {context}: {exc}", flush=True)
        traceback.print_exc()
    except Exception:
        pass


def _run_generate(payload: Dict[str, Any], job_id: str) -> None:
    global _LOADED_KIND
    _emit({"type": "job_started", "job_id": job_id, "command": "generate"})
    _ensure_image_mode()
    pipeline_id = str(payload.get("pipeline_id") or "flux_schnell_mflux_play")
    if pipeline_id == "flux_schnell_mflux_play":
        if getattr(sys, "frozen", False):
            try:
                import mlx.core as mx

                mx.default_device()
            except Exception as e:
                _log_worker_error("MLX native extension failed to load", e)
                detail = str(e)
                if "mlx._reprlib_fix" in detail:
                    detail = (
                        "MLX Python modules are incomplete in this app bundle "
                        "(missing mlx._reprlib_fix). Rebuild with ./pyInstallerBuild.sh."
                    )
                raise RuntimeError(
                    f"{detail} See Tools > Debug > View log for details."
                ) from e
        from imagegen_plugins.pipelines.mflux_schnell import run_from_payload
    elif pipeline_id == "sana_sprint_600m":
        from imagegen_plugins.pipelines.sana_sprint import run_from_payload
    elif pipeline_id in ("mflux_fill_expand", "mflux_fill_infill"):
        if getattr(sys, "frozen", False):
            try:
                import mlx.core as mx

                mx.default_device()
            except Exception as e:
                _log_worker_error("MLX native extension failed to load", e)
                detail = str(e)
                if "mlx._reprlib_fix" in detail:
                    detail = (
                        "MLX Python modules are incomplete in this app bundle "
                        "(missing mlx._reprlib_fix). Rebuild with ./pyInstallerBuild.sh."
                    )
                raise RuntimeError(
                    f"{detail} See Tools > Debug > View log for details."
                ) from e
        from imagegen_plugins.pipelines.mflux_fill_expand import run_from_payload
    elif pipeline_id == "mflux_flux2_klein_edit":
        if getattr(sys, "frozen", False):
            try:
                import mlx.core as mx

                mx.default_device()
            except Exception as e:
                _log_worker_error("MLX native extension failed to load", e)
                detail = str(e)
                if "mlx._reprlib_fix" in detail:
                    detail = (
                        "MLX Python modules are incomplete in this app bundle "
                        "(missing mlx._reprlib_fix). Rebuild with ./pyInstallerBuild.sh."
                    )
                raise RuntimeError(
                    f"{detail} See Tools > Debug > View log for details."
                ) from e
        from imagegen_plugins.pipelines.mflux_flux2_klein_edit import run_from_payload
    else:
        raise ValueError(f"Unknown imagegen pipeline_id: {pipeline_id!r}")

    _LOADED_KIND = "image"
    try:
        result = run_from_payload(payload)
        _emit({"type": "result", "job_id": job_id, "command": "generate", **result})
    except Exception as e:
        _log_worker_error("generate failed", e)
        raise
    finally:
        _unload_image_model()


def _run_caption(
    file_path: str, user_prompt_override: str | None, job_id: str
) -> None:
    global _LOADED_KIND
    _emit({"type": "job_started", "job_id": job_id, "command": "caption"})
    _ensure_lmstudio_mode()
    from lmstudio_caption import get_image_caption_stream, _strip_think_tags

    _LOADED_KIND = "lmstudio"
    accumulated = []
    try:
        for chunk in get_image_caption_stream(file_path, user_prompt_override):
            if chunk:
                accumulated.append(chunk)
                _emit({"type": "caption_chunk", "job_id": job_id, "text": chunk})
        full_text = _strip_think_tags("".join(accumulated)).strip()
        if not full_text:
            raise RuntimeError(
                "The model returned an empty response.\n\n"
                "Try again, or check that the loaded model supports vision."
            )
        _emit(
            {
                "type": "result",
                "job_id": job_id,
                "command": "caption",
                "caption": full_text,
            }
        )
    finally:
        pass


def _handle_command(cmd: Dict[str, Any]) -> None:
    command = cmd.get("command")
    job_id = str(cmd.get("job_id") or "")

    if command == "shutdown":
        _unload_image_model()
        _unload_lmstudio_models()
        raise SystemExit(0)

    if command == "generate":
        payload = cmd.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("generate requires payload dict")
        _run_generate(payload, job_id)
        return

    if command == "caption":
        file_path = cmd.get("file_path")
        if not file_path:
            raise ValueError("caption requires file_path")
        override = cmd.get("user_prompt_override")
        if override is not None and not str(override).strip():
            override = None
        _run_caption(str(file_path), override, job_id)
        return

    raise ValueError(f"Unknown command: {command!r}")


def main() -> int:
    _emit({"type": "ready"})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError as e:
            _emit({"type": "error", "message": f"Invalid JSON command: {e}"})
            continue
        job_id = str(cmd.get("job_id") or "")
        try:
            _handle_command(cmd)
        except SystemExit:
            raise
        except Exception as e:
            _log_worker_error(f"command {cmd.get('command')!r} failed", e)
            _emit({"type": "error", "job_id": job_id, "message": str(e)})
    _unload_image_model()
    _unload_lmstudio_models()
    return 0


if __name__ == "__main__":
    sys.exit(main())
