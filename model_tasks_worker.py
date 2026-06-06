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
from typing import Any, Callable, Dict, Optional

_LOADED_KIND: Optional[str] = None  # None | "image" | "lmstudio"
_SHUTDOWN = object()
_active_emit: Optional[Callable[[Dict[str, Any]], None]] = None


def _stdout_emit(msg: Dict[str, Any]) -> None:
    print(json.dumps(msg), flush=True)


def emit_worker_message(msg: Dict[str, Any]) -> None:
    """Send a worker JSON message to stdout (subprocess) or the inline-worker callback."""
    if _active_emit is not None:
        _active_emit(msg)
    else:
        _stdout_emit(msg)


def _emit(msg: Dict[str, Any]) -> None:
    emit_worker_message(msg)


def _worker_setup() -> None:
    try:
        from print_log_redirect import setup_stdout_print_log

        setup_stdout_print_log(truncate=False)
    except Exception:
        pass
    try:
        from imagegen_plugins.mflux_macos_shim import apply_mflux_macos_subprocess_shim

        apply_mflux_macos_subprocess_shim()
    except ImportError:
        pass


def _unload_lmstudio_models() -> None:
    global _LOADED_KIND
    from lmstudio_caption import unload_all_lmstudio_models

    unload_all_lmstudio_models()
    if _LOADED_KIND == "lmstudio":
        _LOADED_KIND = None


def _unload_image_model(*, reason: str = "explicit") -> None:
    global _LOADED_KIND
    try:
        from imagegen_plugins.mflux_model_session import release_all_mflux_sessions

        release_all_mflux_sessions(reason=reason)
    except Exception:
        pass
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
    _unload_image_model(reason="caption")


def _log_worker_error(context: str, exc: BaseException) -> None:
    try:
        print(f"[model_tasks_worker] {context}: {exc}", flush=True)
        traceback.print_exc()
    except Exception:
        pass


def _run_generate(payload: Dict[str, Any], job_id: str) -> None:
    global _LOADED_KIND
    import time

    try:
        from imagegen_plugins.mflux_macos_shim import apply_mflux_macos_subprocess_shim

        apply_mflux_macos_subprocess_shim()
    except ImportError:
        pass

    from imagegen_plugins.imagegen_perf_log import PerfTimer, set_perf_debug

    set_perf_debug(bool(payload.get("debug_mode")))
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

    from imagegen_plugins.mflux_model_session import (
        note_image_model_loaded,
        prepare_image_model_for_payload,
    )

    prepare_image_model_for_payload(payload)
    _LOADED_KIND = "image"
    job_t0 = time.perf_counter()
    try:
        with PerfTimer("worker_job", job_id=job_id, pipeline=pipeline_id):
            result = run_from_payload(payload)
        _emit({"type": "result", "job_id": job_id, "command": "generate", **result})
    except Exception as e:
        _log_worker_error("generate failed", e)
        raise
    finally:
        note_image_model_loaded(payload)
        from imagegen_plugins.imagegen_perf_log import perf_log_kv

        perf_log_kv(
            "worker_job_done",
            job_id=job_id,
            pipeline=pipeline_id,
            elapsed=time.perf_counter() - job_t0,
        )


def _run_flux_prompt(system_prompt: str, user_prompt: str, job_id: str) -> None:
    global _LOADED_KIND
    _emit({"type": "job_started", "job_id": job_id, "command": "flux_prompt"})
    _ensure_lmstudio_mode()
    from lmstudio_flux_prompt import finalize_flux_prompt_text, get_flux_prompt_stream

    _LOADED_KIND = "lmstudio"
    accumulated = []
    try:
        for chunk in get_flux_prompt_stream(system_prompt, user_prompt):
            if chunk:
                accumulated.append(chunk)
                _emit({"type": "flux_prompt_chunk", "job_id": job_id, "text": chunk})
        full_text = finalize_flux_prompt_text("".join(accumulated))
        if not full_text:
            raise RuntimeError(
                "The model returned an empty response.\n\n"
                "Try again, or load a text-capable model in LMStudio."
            )
        _emit(
            {
                "type": "result",
                "job_id": job_id,
                "command": "flux_prompt",
                "prompt": full_text,
            }
        )
    finally:
        pass


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


def _handle_command(cmd: Dict[str, Any]) -> Any:
    command = cmd.get("command")
    job_id = str(cmd.get("job_id") or "")

    from imagegen_plugins.mflux_model_session import maybe_unload_idle_image_model

    maybe_unload_idle_image_model()

    if command == "shutdown":
        _unload_image_model(reason="shutdown")
        _unload_lmstudio_models()
        return _SHUTDOWN

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

    if command == "flux_prompt":
        system_prompt = str(cmd.get("system_prompt") or "")
        user_prompt = str(cmd.get("user_prompt") or "")
        _run_flux_prompt(system_prompt, user_prompt, job_id)
        return

    raise ValueError(f"Unknown command: {command!r}")


def run_worker_event_loop(
    read_line: Callable[[], str | None],
    emit: Callable[[Dict[str, Any]], None],
) -> None:
    """Run the worker command loop (stdin subprocess or in-process queue)."""
    global _active_emit
    # emit must be a leaf writer (_stdout_emit or inline bridge), never _emit.
    if emit is _emit:
        raise RuntimeError("run_worker_event_loop: pass _stdout_emit, not _emit")
    _worker_setup()
    _active_emit = emit
    try:
        emit_worker_message({"type": "ready"})
        while True:
            line = read_line()
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError as e:
                emit_worker_message({"type": "error", "message": f"Invalid JSON command: {e}"})
                continue
            job_id = str(cmd.get("job_id") or "")
            try:
                if _handle_command(cmd) is _SHUTDOWN:
                    break
            except Exception as e:
                _log_worker_error(f"command {cmd.get('command')!r} failed", e)
                emit_worker_message({"type": "error", "job_id": job_id, "message": str(e)})
    finally:
        _active_emit = None
        _unload_image_model()
        _unload_lmstudio_models()


def main() -> int:
    def _read_stdin() -> str | None:
        line = sys.stdin.readline()
        if not line:
            return None
        return line

    run_worker_event_loop(_read_stdin, _stdout_emit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
