#!/usr/bin/env python3
"""
LMStudio integration for AI-generated image captions.

Requires the 'lmstudio' Python SDK (pip install lmstudio) and
LMStudio running on localhost:1234 with a vision-capable model loaded.
"""

import json
from typing import Optional

from config import get_config, CAPTION_DEFAULTS


_CHANNEL_MARKER = '<channel|>'


def _strip_think_tags(text: str) -> str:
    """
    Remove model routing/thinking artifacts from caption text:
    - Content between the first <think (or <think1, <think8, etc.) and the last </think>.
    - Everything before and including the last <channel|> marker.
    If a <think opening tag exists but no </think closing tag follows it, keep the text as-is.
    """
    first_open = text.find('<think')
    if first_open != -1:
        last_close = text.rfind('</think')
        if last_close != -1 and last_close >= first_open:
            end_of_closing = text.find('>', last_close)
            if end_of_closing != -1:
                text = text[:first_open] + text[end_of_closing + 1:]

    channel_pos = text.rfind(_CHANNEL_MARKER)
    if channel_pos != -1:
        text = text[channel_pos + len(_CHANNEL_MARKER):]

    return text


def _get_caption_settings():
    """Load caption settings from config (uses system defaults if not set)."""
    settings = get_config().load_settings()
    return {
        'lms_host': settings.get('caption_lms_host') or CAPTION_DEFAULTS['caption_lms_host'],
        'system_prompt': settings.get('caption_system_prompt') or CAPTION_DEFAULTS['caption_system_prompt'],
        'user_prompt': settings.get('caption_user_prompt') or CAPTION_DEFAULTS['caption_user_prompt'],
        'max_words': settings.get('caption_max_words', CAPTION_DEFAULTS['caption_max_words']),
        'temperature': settings.get('caption_temperature', CAPTION_DEFAULTS['caption_temperature']),
    }


def _get_last_lm_model_key() -> Optional[str]:
    settings = get_config().load_settings()
    key = (settings.get("caption_last_lm_model_key") or "").strip()
    if not key:
        key = (CAPTION_DEFAULTS.get("caption_last_lm_model_key") or "").strip()
    return key or None


def _persist_last_lm_model_key(model_key: str) -> None:
    model_key = (model_key or "").strip()
    if not model_key:
        return
    if _get_last_lm_model_key() == model_key:
        return
    get_config().update_setting("caption_last_lm_model_key", model_key)


def _model_key_from_handle(model) -> Optional[str]:
    try:
        info = model.get_info()
        return (getattr(info, "model_key", None) or "").strip() or None
    except Exception:
        return None


_VISION_REQUIRED_MSG = (
    "The loaded model does not support image input.\n\n"
    "Please load a vision-capable model (VLM) in LMStudio."
)


def _loaded_model_supports_vision(model) -> bool | None:
    """Return True/False from LM Studio model info, or None if unknown."""
    try:
        info = model.get_info()
    except Exception:
        return None
    if info is None:
        return None
    vision = getattr(info, "vision", None)
    if vision is None:
        return None
    return bool(vision)


def _require_vision_capable_model(model) -> None:
    """Raise RuntimeError when the loaded LLM cannot accept images."""
    supports = _loaded_model_supports_vision(model)
    if supports is not False:
        return
    display_name = ""
    try:
        info = model.get_info()
        display_name = (getattr(info, "display_name", None) or "").strip()
    except Exception:
        pass
    if display_name:
        raise RuntimeError(f"{_VISION_REQUIRED_MSG}\n\nLoaded model: {display_name}")
    raise RuntimeError(_VISION_REQUIRED_MSG)


def _remember_loaded_lm_model_keys(client) -> None:
    """Persist modelKey of the first loaded LLM (used before unload / after caption)."""
    try:
        for model in client.llm.list_loaded():
            key = _model_key_from_handle(model)
            if key:
                _persist_last_lm_model_key(key)
                return
    except Exception:
        pass


def _ensure_caption_model(client):
    """Return a loaded LLM handle, reloading the last persisted model if needed."""
    loaded_models = client.llm.list_loaded()
    if loaded_models:
        model = loaded_models[0]
        key = _model_key_from_handle(model)
        if key:
            _persist_last_lm_model_key(key)
        return model

    saved_key = _get_last_lm_model_key()
    if not saved_key:
        raise RuntimeError(
            "No model is currently loaded in LMStudio.\n\n"
            "Please load a vision-capable model (VLM) before using AI captioning."
        )
    try:
        model = client.llm.model(saved_key)
    except Exception as e:
        raise RuntimeError(
            f"Could not reload the last LM Studio caption model.\n\n"
            f"Saved model: {saved_key}\n\nDetail: {e}"
        ) from e
    _persist_last_lm_model_key(saved_key)
    return model


def is_lmstudio_sdk_available() -> bool:
    """Return True if the lmstudio SDK package is importable."""
    try:
        import lmstudio  # noqa: F401
        return True
    except ImportError:
        return False


def unload_all_lmstudio_models() -> None:
    """Unload every LLM currently loaded in the LM Studio server (frees RAM for image models)."""
    try:
        import lmstudio as lms
    except ImportError:
        return
    cap_settings = _get_caption_settings()
    lms_host = cap_settings["lms_host"]
    try:
        if not lms.Client.is_valid_api_host(lms_host):
            return
    except Exception:
        return
    try:
        with lms.Client(lms_host) as client:
            _remember_loaded_lm_model_keys(client)
            for model in list(client.llm.list_loaded()):
                try:
                    ident = getattr(model, "identifier", None) or str(model)
                    client.llm.unload(ident)
                except Exception:
                    try:
                        model.unload()
                    except Exception:
                        pass
    except Exception:
        pass


def is_lmstudio_services_available() -> bool:
    """Return True if LMStudio SDK is installed, server is reachable, and a model is loaded."""
    try:
        import lmstudio as lms
    except ImportError:
        return False
    cap_settings = _get_caption_settings()
    lms_host = cap_settings['lms_host']
    try:
        if not lms.Client.is_valid_api_host(lms_host):
            return False
    except Exception:
        return False
    try:
        with lms.Client(lms_host) as client:
            if client.llm.list_loaded():
                return True
            return bool(_get_last_lm_model_key())
    except Exception:
        return False


def get_image_caption_stream(file_path: str, user_prompt_override: str | None = None):
    """
    Generator that yields text chunks as they stream from LMStudio.
    The caller should accumulate chunks and apply _strip_think_tags to the final result.
    Raises RuntimeError for the same cases as get_image_caption.
    """
    try:
        import lmstudio as lms
    except ImportError:
        raise RuntimeError(
            "The LMStudio Python SDK is not installed.\n\n"
            "Install it with:  pip install lmstudio"
        )

    cap_settings = _get_caption_settings()
    lms_host = cap_settings['lms_host']

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

    with lms.Client(lms_host) as client:
        try:
            model = _ensure_caption_model(client)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Could not retrieve or load a model from LMStudio.\n\nDetail: {e}"
            )

        _require_vision_capable_model(model)

        word_count = cap_settings['max_words']
        system_prompt = cap_settings['system_prompt'].format(CAPTION_WORD_COUNT=word_count)
        if user_prompt_override and user_prompt_override.strip():
            user_prompt = user_prompt_override.strip()
        else:
            user_prompt = cap_settings['user_prompt'].format(CAPTION_WORD_COUNT=word_count)
        temperature = cap_settings['temperature']

        try:
            image_handle = client.files.prepare_image(file_path)
        except Exception as e:
            raise RuntimeError(
                f"Could not prepare image for the model.\n\nDetail: {e}"
            )

        chat = lms.Chat(system_prompt)
        chat.add_user_message(user_prompt, images=[image_handle])

        try:
            prediction_stream = model.respond_stream(
                chat,
                config={"temperature": temperature},
            )
            for fragment in prediction_stream:
                yield fragment.content
        except Exception as e:
            err_lower = str(e).lower()
            if any(k in err_lower for k in ("vision", "image", "multimodal", "vlm", "visual")):
                raise RuntimeError(
                    "The loaded model does not support image input.\n\n"
                    "Please load a vision-capable model (VLM) in LMStudio."
                )
            raise RuntimeError(f"Caption generation failed.\n\nDetail: {e}")


def get_image_caption(file_path: str, user_prompt_override: str | None = None) -> str:
    """
    Generate an AI caption for the image at file_path using LMStudio.

    Uses the scoped resource API so connections are released cleanly.
    Raises RuntimeError with a user-friendly message for all known error cases.

    Args:
        file_path: Path to the image file.
        user_prompt_override: Optional user prompt. When provided (non-empty),
            used as the "user" element instead of the config caption_user_prompt.
    """
    try:
        import lmstudio as lms
    except ImportError:
        raise RuntimeError(
            "The LMStudio Python SDK is not installed.\n\n"
            "Install it with:  pip install lmstudio"
        )

    cap_settings = _get_caption_settings()
    lms_host = cap_settings['lms_host']

    # Check server reachability before opening a full client connection.
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

    try:
        with lms.Client(lms_host) as client:
            try:
                model = _ensure_caption_model(client)
            except RuntimeError:
                raise
            except Exception as e:
                raise RuntimeError(
                    f"Could not retrieve or load a model from LMStudio.\n\nDetail: {e}"
                )

            _require_vision_capable_model(model)

            word_count = cap_settings['max_words']
            system_prompt = cap_settings['system_prompt'].format(CAPTION_WORD_COUNT=word_count)
            if user_prompt_override and user_prompt_override.strip():
                user_prompt = user_prompt_override.strip()
            else:
                user_prompt = cap_settings['user_prompt'].format(CAPTION_WORD_COUNT=word_count)
            temperature = cap_settings['temperature']

            # Prepare the image handle.
            try:
                image_handle = client.files.prepare_image(file_path)
            except Exception as e:
                raise RuntimeError(
                    f"Could not prepare image for the model.\n\nDetail: {e}"
                )

            # Build fresh chat with only system and user nodes (no previous context).
            # New Chat each time guarantees no assistant history or prior turns.
            chat = lms.Chat(system_prompt)
            chat.add_user_message(user_prompt, images=[image_handle])

            payload = {
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt, "images": [file_path]},
                ],
                "config": {"temperature": temperature},
            }
            if get_config().load_settings().get('debug_mode', False):
                print("LMStudio caption request JSON:")
                print(json.dumps(payload, indent=2))

            try:
                prediction = model.respond(
                    chat,
                    config={"temperature": temperature},
                )
            except Exception as e:
                err_lower = str(e).lower()
                if any(k in err_lower for k in ("vision", "image", "multimodal", "vlm", "visual")):
                    raise RuntimeError(
                        "The loaded model does not support image input.\n\n"
                        "Please load a vision-capable model (VLM) in LMStudio."
                    )
                raise RuntimeError(f"Caption generation failed.\n\nDetail: {e}")

            result = _strip_think_tags(str(prediction)).strip()
            if not result:
                raise RuntimeError(
                    "The model returned an empty response.\n\n"
                    "Try again, or check that the loaded model supports vision."
                )
            return result

    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Unexpected error during caption generation.\n\nDetail: {e}")
