#!/usr/bin/env python3
"""LM Studio chat completion with full session context."""

from __future__ import annotations

from typing import Generator, Iterable

from chat_plugins.chat_prompt_config import load_system_prompt_config, save_system_prompt_config
from config import CAPTION_DEFAULTS, CHAT_DEFAULTS, get_config
from imagegen_plugins.ai_prompt_exit import apply_text_ai_exit
from thumbnails.thumbnail_constants import CHAT_REJECTED_RESPONSE_PHRASES

from chat_plugins.chat_debug_log import log_chat_llm_input
from chat_plugins.chat_session import ChatMessage
from chat_plugins.chat_image_gen_trigger import strip_image_gen_commands_from_user_message
from chat_plugins.chat_image_paths import paths_for_vision_model
from chat_plugins.chat_selection_image_trigger import strip_selection_image_trigger

DEFAULT_CHAT_SYSTEM_PROMPT = CHAT_DEFAULTS["chat_system_prompt"]
CHAT_REJECTION_MAX_RETRIES = 5


def chat_response_contains_rejected_phrase(text: str) -> str | None:
    """Return the matched apology/refusal phrase, or None (case-insensitive)."""
    if not text:
        return None
    lower = text.lower()
    for phrase in CHAT_REJECTED_RESPONSE_PHRASES:
        if phrase.lower() in lower:
            return phrase
    return None


def load_chat_system_prompt() -> str:
    config = load_system_prompt_config()
    prompt = config.get("system_prompt")
    if isinstance(prompt, str) and prompt.strip():
        return prompt
    return DEFAULT_CHAT_SYSTEM_PROMPT


def save_chat_system_prompt(prompt: str) -> None:
    config = load_system_prompt_config()
    config["system_prompt"] = prompt
    save_system_prompt_config(config)


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
        "system_prompt": load_chat_system_prompt(),
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


def _messages_as_sent_to_llm(messages: list[ChatMessage]) -> list[dict]:
    out: list[dict] = []
    for msg in messages:
        if msg.role == "user":
            user_text = strip_image_gen_commands_from_user_message(
                strip_selection_image_trigger(msg.text)
            )
            entry: dict = {"role": "user", "text": user_text}
            vision_paths = paths_for_vision_model(msg)
            if vision_paths:
                entry["image_paths"] = vision_paths
            out.append(entry)
        else:
            out.append({"role": "assistant", "text": msg.text})
    return out


def _build_chat(
    client,
    messages: list[ChatMessage],
    *,
    system_prompt: str | None = None,
):
    import lmstudio as lms

    cfg = _chat_settings()
    prompt_text = system_prompt if system_prompt is not None else cfg["system_prompt"]
    prompt_text = apply_text_ai_exit(prompt_text)
    chat = lms.Chat(prompt_text)
    for msg in messages:
        if msg.role == "user":
            handles = []
            for path in paths_for_vision_model(msg):
                try:
                    handles.append(client.files.prepare_image(path))
                except Exception as e:
                    raise RuntimeError(
                        f"Could not prepare image for the model.\n\nDetail: {e}"
                    ) from e
            user_text = strip_image_gen_commands_from_user_message(
                strip_selection_image_trigger(msg.text)
            )
            if handles:
                chat.add_user_message(user_text, images=handles)
            else:
                chat.add_user_message(user_text)
        else:
            chat.add_assistant_response(msg.text)
    return chat


def stream_chat_response(
    messages: list[ChatMessage],
    *,
    system_prompt: str | None = None,
) -> Generator[str, None, None]:
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
        prompt_text = system_prompt if system_prompt is not None else cfg["system_prompt"]
        prompt_text = apply_text_ai_exit(prompt_text)
        chat = _build_chat(client, messages, system_prompt=system_prompt)
        temperature = cfg["temperature"]
        log_chat_llm_input(
            _messages_as_sent_to_llm(messages),
            system_prompt=prompt_text,
            temperature=temperature,
        )
        try:
            prediction_stream = model.respond_stream(
                chat,
                config={"temperature": temperature},
            )
            for fragment in prediction_stream:
                if fragment.content:
                    yield fragment.content
        except Exception as e:
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
