#!/usr/bin/env python3
"""Add missing LoRA trigger words to the generation prompt at job time."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from imagegen_plugins.lora_catalog import get_lora_entry
from imagegen_plugins.mflux_lora_presets import effective_lora_ids_from_values

TRIGGER_USER_PROMPT_SEPARATOR = "------"


def prompt_contains_lora_trigger(prompt: str, trigger: str) -> bool:
    """True when trigger appears in prompt as a phrase or whole token."""
    prompt_s = (prompt or "").strip()
    trigger_s = (trigger or "").strip()
    if not trigger_s:
        return True
    if not prompt_s:
        return False
    if " " in trigger_s:
        return trigger_s.lower() in prompt_s.lower()
    pattern = r"(?<!\w)" + re.escape(trigger_s) + r"(?!\w)"
    return re.search(pattern, prompt_s, re.IGNORECASE) is not None


def _format_prompt_with_triggers(prompt_s: str, trigger_block: str) -> str:
    """Insert trigger text per thumbnails.thumbnail_constants.TRIGGER_POSITION."""
    from thumbnails.thumbnail_constants import TRIGGER_POSITION

    block = (trigger_block or "").strip()
    if not block:
        return prompt_s
    if not prompt_s:
        return block
    sep = TRIGGER_USER_PROMPT_SEPARATOR
    if TRIGGER_POSITION == 0:
        return f"{block}\n\n{sep}\n\n{prompt_s}"
    if TRIGGER_POSITION == 2:
        return f"{block}\n\n{sep}\n\n{prompt_s}\n\n{sep}\n\n{block}"
    return f"{prompt_s}\n\n{sep}\n\n{block}"


def ensure_triggers_in_prompt(prompt: str, triggers: Iterable[str]) -> str:
    """Return prompt with any missing trigger words added (TRIGGER_POSITION)."""
    prompt_s = (prompt or "").strip()
    missing: List[str] = []
    seen = set()
    for raw in triggers:
        trigger = str(raw or "").strip()
        if not trigger:
            continue
        key = trigger.lower()
        if key in seen:
            continue
        seen.add(key)
        if not prompt_contains_lora_trigger(prompt_s, trigger):
            missing.append(trigger)
    if not missing:
        return prompt_s
    return _format_prompt_with_triggers(prompt_s, "\n\n".join(missing))


def _missing_lora_trigger_words(values: Dict[str, Any]) -> List[str]:
    from imagegen_plugins.job_values_snapshot import (
        LORA_TRIGGER_WORDS_KEY,
        job_values_snapshotted,
    )

    prompt = (values.get("prompt") or "").strip()
    if job_values_snapshotted(values):
        snap = values.get(LORA_TRIGGER_WORDS_KEY)
        if isinstance(snap, list):
            missing: List[str] = []
            for item in snap:
                trigger = str(item or "").strip()
                if trigger and not prompt_contains_lora_trigger(prompt, trigger):
                    missing.append(trigger)
            return missing
    stack = effective_lora_ids_from_values(values, pop=False)
    missing: List[str] = []
    for lora_id in stack:
        entry = get_lora_entry(lora_id)
        if entry is None:
            continue
        trigger = (entry.trigger_word or "").strip()
        if not trigger or prompt_contains_lora_trigger(prompt, trigger):
            continue
        missing.append(trigger)
    return missing


def augment_prompt_with_missing_lora_triggers(
    prompt: str,
    values: Dict[str, Any],
) -> str:
    """Return prompt with any missing LoRA trigger words added."""
    probe = dict(values)
    probe["prompt"] = prompt
    missing = _missing_lora_trigger_words(probe)
    if not missing:
        return (prompt or "").strip()
    return _format_prompt_with_triggers((prompt or "").strip(), "\n\n".join(missing))


def apply_lora_triggers_for_run(values: Dict[str, Any]) -> None:
    """Mutate ``values['prompt']`` in place; does not affect persisted dialog text."""
    prompt = (values.get("prompt") or "").strip()
    values["prompt"] = augment_prompt_with_missing_lora_triggers(prompt, values)


def _collect_known_lora_triggers(values: Dict[str, Any]) -> List[str]:
    from imagegen_plugins.job_values_snapshot import (
        LORA_TRIGGER_WORDS_KEY,
        job_values_snapshotted,
    )

    if job_values_snapshotted(values):
        snap = values.get(LORA_TRIGGER_WORDS_KEY)
        if isinstance(snap, list):
            return [str(item or "").strip() for item in snap if str(item or "").strip()]
    stack = effective_lora_ids_from_values(values, pop=False)
    triggers: List[str] = []
    for lora_id in stack:
        entry = get_lora_entry(lora_id)
        if entry is None:
            continue
        trigger = (entry.trigger_word or "").strip()
        if trigger:
            triggers.append(trigger)
    return triggers


def _is_trigger_block(text: str, triggers: List[str]) -> bool:
    block = (text or "").strip()
    if not block or not triggers:
        return False
    parts = [part.strip() for part in block.split("\n\n") if part.strip()]
    if not parts:
        return False
    trigger_set = {trigger.lower() for trigger in triggers}
    return all(part.lower() in trigger_set for part in parts)


def strip_auto_added_lora_triggers_from_prompt(
    prompt: str,
    values: Dict[str, Any] | None,
) -> str:
    """Remove auto-added LoRA trigger blocks from a formatted prompt."""
    prompt_s = (prompt or "").strip()
    if not prompt_s or not isinstance(values, dict):
        return prompt_s
    user = (values.get("prompt") or "").strip()
    if prompt_s == user:
        return user
    augmented = augment_prompt_with_missing_lora_triggers(user, values)
    if prompt_s == augmented:
        return user
    triggers = _collect_known_lora_triggers(values)
    if not triggers:
        return prompt_s
    sep = TRIGGER_USER_PROMPT_SEPARATOR
    parts = [part.strip() for part in prompt_s.split(f"\n\n{sep}\n\n")]
    if len(parts) <= 1:
        return prompt_s
    filtered = [part for part in parts if not _is_trigger_block(part, triggers)]
    if not filtered:
        return user
    return "\n\n".join(filtered).strip()


def include_triggers_in_exif(settings: Dict[str, Any] | None = None) -> bool:
    if settings is None:
        from config import get_config

        settings = get_config().load_settings()
    return bool(settings.get("imagegen_include_triggers_in_exif", False))


def prompt_text_for_exif(
    values: Dict[str, Any] | None,
    prompt_override: str | None = None,
    *,
    include_triggers: bool | None = None,
) -> str:
    """Prompt body for generated-image EXIF UserComment."""
    prompt = str(
        prompt_override
        if prompt_override is not None
        else (values or {}).get("prompt") or ""
    ).strip()
    if not isinstance(values, dict):
        return prompt
    if include_triggers is None:
        include_triggers = include_triggers_in_exif()
    if include_triggers:
        return augment_prompt_with_missing_lora_triggers(prompt, values)
    return strip_auto_added_lora_triggers_from_prompt(prompt, values)
