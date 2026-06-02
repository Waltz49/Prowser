#!/usr/bin/env python3
"""
LM Studio text-only prompt refinement for FLUX image generation dialogs.

Uses the same server host and temperature as AI captioning; any loaded LLM
(non-vision) is sufficient.
"""

from __future__ import annotations

from imagegen_plugins.image_gen_active_model import (
    FUNCTION_CREATE,
    FUNCTION_EDIT,
    FUNCTION_EXPAND,
    FUNCTION_INFILL,
    FUNCTION_INFILL_PAINT,
)
from lmstudio_caption import (
    _ensure_caption_model,
    _get_caption_settings,
    _strip_think_tags,
)

__all__ = [
    "flux_prompt_system_message",
    "get_flux_prompt_stream",
]

_FLUX_REALISM = (
    "You write 120 word prompts for FLUX diffusion models (text-to-image and image-conditioned pipelines). "
    "Return exactly one prompt the user can paste into FLUX. Do NOT add conversation, titles, labels, quotes, markdown, or explanations. "
    "Favor photographic realism: natural light, realistic materials and textures, believable depth of field, "
    "accurate human anatomy when people appear, and physically plausible scenes. "
    "Use concrete nouns and adjectives; avoid negative-prompt syntax, bracketed camera tags unless essential, "
    "and filler words."
)

_TASK_INSTRUCTIONS: dict[str, str] = {
    FUNCTION_CREATE: (
        "The user is creating a brand-new image from text only (text-to-image). "
        "Refine their notes into one cohesive scene description for FLUX Schnell or a similar FLUX model."
    ),
    FUNCTION_EDIT: (
        "The user is editing or transforming one or more reference images with an image-to-image / edit model. "
        "Describe what should change or stay the same relative to the incoming image(s)—identity, pose, "
        "background, wardrobe, style, or local edits—not an unrelated scene unless they clearly want that."
    ),
    FUNCTION_EXPAND: (
        "The user is outpainting or expanding an existing photograph (canvas extension). "
        "Emphasize seamless continuation of the visible frame: match perspective, lighting, color, and style at "
        "the new edges; describe what should appear in the expanded regions only."
    ),
    FUNCTION_INFILL: (
        "The user is inpainting a masked region inside an existing photograph. "
        "Describe only what belongs inside the mask while matching surrounding context, lighting, and materials; "
        "do not re-describe the entire image."
    ),
    FUNCTION_INFILL_PAINT: (
        "The user is painting a mask and inpainting that region in an existing photograph. "
        "Describe only what belongs inside the painted mask while matching surrounding context, lighting, and materials."
    ),
}


def flux_prompt_system_message(task_kind: str) -> str:
    """System prompt for FLUX prompt refinement for a Create-menu function."""
    task = _TASK_INSTRUCTIONS.get(task_kind, _TASK_INSTRUCTIONS[FUNCTION_CREATE])
    return f"{_FLUX_REALISM} {task}"


def get_flux_prompt_stream(system_prompt: str, user_prompt: str):
    """
    Yield text chunks from LM Studio for a text-only FLUX prompt refinement.

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

    system_prompt = (system_prompt or "").strip()
    if not system_prompt:
        system_prompt = flux_prompt_system_message(FUNCTION_CREATE)

    user_text = (user_prompt or "").strip()
    if not user_text:
        user_text = (
            "The prompt field is empty. Suggest a strong photographic FLUX prompt "
            "appropriate for this task."
        )

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

        chat = lms.Chat(system_prompt)
        chat.add_user_message(user_text)

        try:
            prediction_stream = model.respond_stream(
                chat,
                config={"temperature": temperature},
            )
            for fragment in prediction_stream:
                if fragment.content:
                    yield fragment.content
        except Exception as e:
            raise RuntimeError(f"Prompt refinement failed.\n\nDetail: {e}")


def finalize_flux_prompt_text(accumulated: str) -> str:
    """Strip model artifacts and return the final prompt string."""
    return _strip_think_tags(accumulated).strip()
