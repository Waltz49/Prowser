#!/usr/bin/env python3
"""LM Studio chat completion with full session context."""

from __future__ import annotations

from typing import Generator, Iterable

from config import CAPTION_DEFAULTS, get_config
from imagegen_plugins.ai_prompt_exit import apply_text_ai_exit
from print_call_decorator import log_exception, print_call

from chat_plugins.chat_session import ChatMessage

_CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant. Respond clearly and conversationally."
)


def _strip_think_tags(text: str) -> str:
    first_open = text.find("<think")
    if first_open != -1:
        last_close = text.rfind("</think")
        if last_close != -1 and last_close >= first_open:
            end_of_closing = text.find(">", last_close)
            if end_of_closing != -1:
                text = text[:first_open] + text[end_of_closing + 1 :]
    marker = "<channel|>"
    channel_pos = text.rfind(marker)
    if channel_pos != -1:
        text = text[channel_pos + len(marker) :]
    return text


def _chat_settings() -> dict:
    settings = get_config().load_settings()
    return {
        "lms_host": settings.get("caption_lms_host") or CAPTION_DEFAULTS["caption_lms_host"],
        "temperature": settings.get("caption_temperature", CAPTION_DEFAULTS["caption_temperature"]),
        "system_prompt": _CHAT_SYSTEM_PROMPT,
    }


def is_lmstudio_chat_available() -> bool:
    try:
        from imagegen_plugins.lmstudio_caption import is_lmstudio_services_available

        return is_lmstudio_services_available()
    except ImportError:
        return False


def lmstudio_unavailable_message() -> str:
    try:
        from imagegen_plugins.lmstudio_caption import is_lmstudio_sdk_installed

        if not is_lmstudio_sdk_installed():
            return (
                "LM Studio is not available.\n\n"
                "Install the lmstudio Python package and run LM Studio with a model loaded."
            )
    except ImportError:
        pass
    host = _chat_settings()["lms_host"]
    return (
        f"LM Studio is not available at {host}.\n\n"
        "Start LM Studio, enable the local API server, and load a model."
    )


def _ensure_model(client):
    from imagegen_plugins.lmstudio_caption import _ensure_caption_model

    return _ensure_caption_model(client)


def _require_vision_if_needed(model, messages: Iterable[ChatMessage]) -> None:
    has_images = any(msg.image_paths for msg in messages if msg.role == "user")
    if not has_images:
        return
    from imagegen_plugins.lmstudio_caption import _require_vision_capable_model

    _require_vision_capable_model(model)


def _build_chat(client, messages: list[ChatMessage]):
    import lmstudio as lms

    cfg = _chat_settings()
    system_prompt = apply_text_ai_exit(cfg["system_prompt"])
    chat = lms.Chat(system_prompt)
    for msg in messages:
        if msg.role == "user":
            handles = []
            for path in msg.image_paths:
                try:
                    handles.append(client.files.prepare_image(path))
                except Exception as e:
                    raise RuntimeError(
                        f"Could not prepare image for the model.\n\nDetail: {e}"
                    ) from e
            if handles:
                chat.add_user_message(msg.text, images=handles)
            else:
                chat.add_user_message(msg.text)
        else:
            chat.add_assistant_response(msg.text)
    return chat


def stream_chat_response(messages: list[ChatMessage]) -> Generator[str, None, None]:
    """Yield text chunks for the next assistant turn given full history."""
    try:
        import lmstudio as lms
    except ImportError as e:
        raise RuntimeError(
            "The LMStudio Python SDK is not installed.\n\n"
            "Install it with:  pip install lmstudio"
        ) from e

    cfg = _chat_settings()
    lms_host = cfg["lms_host"]
    try:
        available = lms.Client.is_valid_api_host(lms_host)
    except Exception as e:
        raise RuntimeError(
            f"Could not contact LMStudio server at {lms_host}.\n\nDetail: {e}"
        ) from e
    if not available:
        raise RuntimeError(
            f"LMStudio server is not running at {lms_host}.\n\n"
            "Please start LMStudio and enable the local API server."
        )

    with lms.Client(lms_host) as client:
        try:
            model = _ensure_model(client)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Could not retrieve or load a model from LMStudio.\n\nDetail: {e}"
            ) from e

        _require_vision_if_needed(model, messages)
        chat = _build_chat(client, messages)
        temperature = cfg["temperature"]
        try:
            respond_stream = print_call(model.respond_stream, wrap=True, tee_terminal=False)
            prediction_stream = respond_stream(
                chat,
                config={"temperature": temperature},
            )
            for fragment in prediction_stream:
                if fragment.content:
                    yield fragment.content
        except Exception as e:
            log_exception(e, tee_terminal=False)
            err_lower = str(e).lower()
            if any(
                k in err_lower
                for k in ("vision", "image", "multimodal", "vlm", "visual")
            ):
                raise RuntimeError(
                    "The loaded model does not support image input.\n\n"
                    "Please load a vision-capable model (VLM) in LMStudio."
                ) from e
            raise RuntimeError(f"Chat generation failed.\n\nDetail: {e}") from e


def finalize_chat_response(accumulated: str) -> str:
    return _strip_think_tags(accumulated).strip()
