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
