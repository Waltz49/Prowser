#!/usr/bin/env python3
"""
Persistent subprocess worker for local image generation and LM Studio captions.

Reads newline-delimited JSON commands on stdin; writes newline-delimited JSON on stdout.
Keeps at most one model family loaded: image (mflux) or LM Studio VLM.
"""

from __future__ import annotations

import gc
import ctypes
import ctypes.util
import os
import time
import json
import sys
import traceback
from typing import Any, Callable, Dict, Optional

# Spawned as `python workers/model_tasks_worker.py` — put repo root on sys.path.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from debug_log import debug_timestamp
from print_call_decorator import log_exception, print_call

from imagegen_plugins.image_gen_active_model import (
    FUNCTION_CREATE,
    FUNCTION_EDIT,
    FUNCTION_EXPAND,
    FUNCTION_INFILL,
    FUNCTION_INFILL_PAINT,
)
from imagegen_plugins.lmstudio_caption import (
    _ensure_caption_model,
    _get_caption_settings,
    _strip_think_tags,
)


_APPLIED = False


def _sysctl_string(name: str) -> str:
    libc = ctypes.CDLL(ctypes.util.find_library("c"))
    key = name.encode()
    size = ctypes.c_size_t(0)
    libc.sysctlbyname(key, None, ctypes.byref(size), None, 0)
    buf = ctypes.create_string_buffer(size.value)
    libc.sysctlbyname(key, buf, ctypes.byref(size), None, 0)
    return buf.value.decode()


def apply_mflux_macos_subprocess_shim() -> None:
    """Patch mflux AppleSiliconUtil + BatterySaver before first generation."""
    global _APPLIED
    if _APPLIED:
        return

    try:
        from mflux.callbacks.instances import battery_saver as battery_mod
        from mflux.utils import apple_silicon as apple_mod
    except ImportError:
        return

    _APPLIED = True

    @classmethod
    def _get_chip_name_no_subprocess(cls) -> str:
        if cls._chip_name is not None:
            return cls._chip_name
        try:
            cls._chip_name = _sysctl_string("machdep.cpu.brand_string")
        except OSError:
            cls._chip_name = ""
        return cls._chip_name

    apple_mod.AppleSiliconUtil._get_chip_name = _get_chip_name_no_subprocess

    @classmethod
    def _is_machine_battery_powered_noop(cls) -> bool:
        return False

    battery_mod.BatterySaver._is_machine_battery_powered = _is_machine_battery_powered_noop

    def _call_before_loop_noop(self, **kwargs) -> None:
        return

    battery_mod.BatterySaver.call_before_loop = _call_before_loop_noop


_perf_debug = False


def set_perf_debug(enabled: bool) -> None:
    global _perf_debug
    _perf_debug = bool(enabled)


def perf_debug_enabled() -> bool:
    return _perf_debug


def perf_log(message: str) -> None:
    if _perf_debug:
        print(f"{debug_timestamp()} [imagegen-perf] {message}", flush=True)


def perf_log_kv(event: str, **fields: Any) -> None:
    if not _perf_debug:
        return
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, float):
            parts.append(f"{key}={value:.3f}s")
        else:
            parts.append(f"{key}={value}")
    perf_log(" ".join(parts))


class PerfTimer:
    """Context manager: logs elapsed on exit when perf debug is on."""

    def __init__(self, event: str, **fields: Any) -> None:
        self._event = event
        self._fields = dict(fields)
        self._t0: Optional[float] = None

    def __enter__(self) -> PerfTimer:
        self._t0 = time.perf_counter()
        perf_log_kv(f"{self._event}_start", **self._fields)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._t0 is None:
            return
        elapsed = time.perf_counter() - self._t0
        status = "error" if exc is not None else "ok"
        perf_log_kv(
            self._event,
            elapsed=elapsed,
            status=status,
            **self._fields,
        )

_LOADED_KIND: Optional[str] = None  # None | "image" | "lmstudio"
_SHUTDOWN = object()
_active_emit: Optional[Callable[[Dict[str, Any]], None]] = None

_WORKER_LOG_SKIP_TYPES = frozenset({"flux_prompt_chunk"})


def _log_worker_message_to_view_log(msg: Dict[str, Any]) -> None:
    """Selectively mirror worker IPC messages into Tools > Debug > View log."""
    msg_type = msg.get("type")
    if msg_type in _WORKER_LOG_SKIP_TYPES:
        return
    if msg_type == "result":
        print(json.dumps(msg, indent=2, ensure_ascii=False), flush=True)


def _stdout_emit(msg: Dict[str, Any]) -> None:
    from print_log_redirect import write_process_stdout_line

    write_process_stdout_line(json.dumps(msg, ensure_ascii=False))


def emit_worker_message(msg: Dict[str, Any]) -> None:
    """Send a worker JSON message to stdout (subprocess) or the inline-worker callback."""
    _log_worker_message_to_view_log(msg)
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
        apply_mflux_macos_subprocess_shim()
    except ImportError:
        pass


def _unload_lmstudio_models() -> None:
    global _LOADED_KIND
    from imagegen_plugins.lmstudio_caption import unload_all_lmstudio_models

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
        from imagegen_plugins.pipelines.sana_sprint import unload_pipeline as unload_sana

        unload_sana()
    except Exception:
        pass
    try:
        from imagegen_plugins.pipelines.sd15_diffusers import unload_pipeline as unload_sd15

        unload_sd15()
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

    try:
        apply_mflux_macos_subprocess_shim()
    except ImportError:
        pass

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
    elif pipeline_id == "sd15_diffusers":
        from imagegen_plugins.pipelines.sd15_diffusers import run_from_payload
    elif pipeline_id == "z_image_turbo_sdnq":
        from imagegen_plugins.pipelines.z_image_turbo import run_from_payload
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
    elif pipeline_id in (
        "mflux_flux2_klein_edit",
        "mflux_flux2_klein_create",
        "mflux_flux2_klein_expand",
    ):
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
        if pipeline_id == "mflux_flux2_klein_create":
            from imagegen_plugins.pipelines.mflux_flux2_klein_create import (
                run_from_payload,
            )
        else:
            from imagegen_plugins.pipelines.mflux_flux2_klein_edit import (
                run_from_payload,
            )
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
        perf_log_kv(
            "worker_job_done",
            job_id=job_id,
            pipeline=pipeline_id,
            elapsed=time.perf_counter() - job_t0,
        )


_TASK_INSTRUCTIONS: dict[str, str] = {
    FUNCTION_CREATE: (
      "", # "The user is creating a brand-new image from text only (text-to-image). "
      # "Refine their notes into one cohesive scene description for FLUX Schnell or a similar FLUX model."
    ),
    FUNCTION_EDIT: (
       "", # "Create a new image description based on the incoming image(s) and the user's instructions."
    ),
    FUNCTION_EXPAND: (
       "", # "Create a new image description based on the incoming image(s) and the user's instructions."
    ),
    FUNCTION_INFILL: (
       "", # "Create a description of changes to the image based on the user's instructions."
    ),
    FUNCTION_INFILL_PAINT: (
       "", # "Create a description of changes to the image based on the user's instructions."
    ),
}


def flux_prompt_system_message(
    task_kind: str,
    *,
    with_image: bool = False,
    image_count: int = 0,
) -> str:
    """System prompt for FLUX prompt refinement for a Create-menu function."""
    max_words = _get_caption_settings()["max_words"]
    flux_realism = (
        f"You write {max_words} word prompts for FLUX diffusion models. "
        "Do NOT add conversation, titles, labels, quotes, markdown, or explanations. "
    )
    task = _TASK_INSTRUCTIONS.get(task_kind, _TASK_INSTRUCTIONS[FUNCTION_CREATE])
    base = f"{flux_realism} {task}"
    if not with_image:
        return base
    if image_count > 1:
        photo_phrase = f"{image_count} reference photographs"
    else:
        photo_phrase = "a reference photograph"
    return (
        f"{base} "
        f"The user message includes {photo_phrase}. Use them as visual context, "
        "but treat the user's text as the edit goal—refine their instructions into the "
        "FLUX prompt; do not ignore them in favor of a generic image description."
    )


_FLUX_PROMPT_EMPTY_USER_TEXT = (
    "The prompt field is empty. Suggest a strong photographic FLUX prompt "
    "appropriate for this task."
)


def flux_prompt_user_message(user_prompt: str, *, with_image: bool) -> str:
    """User message for FLUX prompt refinement (optionally with a reference image)."""
    user_text = (user_prompt or "").strip()
    if with_image:
        if user_text:
            return (
                "Create a new image description based on the incoming image(s) and the user's instructions."
                f"\n\nUser instructions:\n{user_text}"
            )
        return (
            "Create a new image description based on the incoming image(s) and the user's instructions."
        )
    if user_text:
        return user_text
    return _FLUX_PROMPT_EMPTY_USER_TEXT


def _normalize_flux_prompt_image_paths(
    image_path: str | None = None,
    image_paths: list[str] | None = None,
) -> list[str]:
    paths: list[str] = []
    if image_paths:
        for raw in image_paths:
            path = (raw or "").strip()
            if path and os.path.isfile(path) and path not in paths:
                paths.append(path)
    else:
        path = (image_path or "").strip()
        if path and os.path.isfile(path):
            paths.append(path)
    return paths


def get_flux_prompt_stream(
    system_prompt: str,
    user_prompt: str,
    image_path: str | None = None,
    image_paths: list[str] | None = None,
):
    """
    Yield text chunks from LM Studio for FLUX prompt refinement.

    When image_path or image_paths is set, the images are sent with the user
    prompt (vision model).

    Raises RuntimeError with a user-friendly message on failure.
    """
    try:
        import lmstudio as lms
    except ImportError:
        raise RuntimeError(
            "The LMStudio Python SDK is not installed.\n\n"
            "Install it with:  pip install lmstudio"
        )

    cap_settings = _get_caption_settings()
    lms_host = cap_settings["lms_host"]

    try:
        available = lms.Client.is_valid_api_host(lms_host)
    except Exception as e:
        raise RuntimeError(
            f"Could not contact LMStudio server at {lms_host}.\n\nDetail: {e}"
        )

    if not available:
        raise RuntimeError(
            f"LMStudio server is not running at {lms_host}.\n\n"
            "Please start LMStudio and enable the local API server."
        )

    image_files = _normalize_flux_prompt_image_paths(
        image_path=image_path, image_paths=image_paths
    )
    use_image = bool(image_files)

    system_prompt = (system_prompt or "").strip()
    if not system_prompt:
        system_prompt = flux_prompt_system_message(
            FUNCTION_CREATE,
            with_image=use_image,
            image_count=len(image_files),
        )

    user_text = flux_prompt_user_message(user_prompt, with_image=use_image)

    temperature = cap_settings["temperature"]

    with lms.Client(lms_host) as client:
        try:
            model = _ensure_caption_model(client)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Could not retrieve or load a model from LMStudio.\n\nDetail: {e}"
            )

        image_handles = []
        if use_image:
            from imagegen_plugins.lmstudio_caption import _require_vision_capable_model

            _require_vision_capable_model(model)
            for image_file in image_files:
                try:
                    image_handles.append(client.files.prepare_image(image_file))
                except Exception as e:
                    raise RuntimeError(
                        f"Could not prepare image for the model.\n\nDetail: {e}"
                    ) from e

        chat = lms.Chat(system_prompt)
        if use_image:
            chat.add_user_message(user_text, images=image_handles)
        else:
            chat.add_user_message(user_text)

        try:
            respond_stream = print_call(model.respond_stream, wrap=True)
            prediction_stream = respond_stream(
                chat,
                config={"temperature": temperature},
            )
            for fragment in prediction_stream:
                if fragment.content:
                    yield fragment.content
        except Exception as e:
            log_exception(e)
            err_lower = str(e).lower()
            if use_image and any(
                k in err_lower
                for k in ("vision", "image", "multimodal", "vlm", "visual")
            ):
                raise RuntimeError(
                    "The loaded model does not support image input.\n\n"
                    "Please load a vision-capable model (VLM) in LMStudio."
                ) from e
            raise RuntimeError(f"Prompt refinement failed.\n\nDetail: {e}") from e


def finalize_flux_prompt_text(accumulated: str) -> str:
    """Strip model artifacts and return the final prompt string."""
    return _strip_think_tags(accumulated).strip()


def _run_flux_prompt(
    system_prompt: str,
    user_prompt: str,
    job_id: str,
    image_path: str | None = None,
    image_paths: list[str] | None = None,
) -> None:
    global _LOADED_KIND
    _emit({"type": "job_started", "job_id": job_id, "command": "flux_prompt"})
    _ensure_lmstudio_mode()

    _LOADED_KIND = "lmstudio"
    accumulated = []
    try:
        for chunk in get_flux_prompt_stream(
            system_prompt,
            user_prompt,
            image_path=image_path,
            image_paths=image_paths,
        ):
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
    from imagegen_plugins.lmstudio_caption import get_image_caption_stream, _strip_think_tags

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
        image_path = cmd.get("image_path")
        if image_path is not None and not str(image_path).strip():
            image_path = None
        raw_paths = cmd.get("image_paths")
        image_paths = None
        if isinstance(raw_paths, list):
            image_paths = [str(p) for p in raw_paths if str(p or "").strip()]
        _run_flux_prompt(
            system_prompt,
            user_prompt,
            job_id,
            str(image_path) if image_path else None,
            image_paths=image_paths,
        )
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
