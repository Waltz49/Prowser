#!/usr/bin/env python3
"""Append missing LoRA trigger words to the generation prompt at job time."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from imagegen_plugins.lora_catalog import get_lora_entry
from imagegen_plugins.mflux_lora_presets import effective_lora_ids_from_values


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


def prompt_with_lora_trigger_added(prompt: str, trigger: str) -> str:
    """Append the trigger to the prompt when it is missing."""
    prompt_s = (prompt or "").strip()
    trigger_s = (trigger or "").strip()
    if not trigger_s or prompt_contains_lora_trigger(prompt_s, trigger_s):
        return prompt_s
    if prompt_s:
        return f"{prompt_s}\n\n{trigger_s}"
    return trigger_s


def _missing_lora_trigger_words(values: Dict[str, Any]) -> List[str]:
    stack = effective_lora_ids_from_values(values, pop=False)
    prompt = (values.get("prompt") or "").strip()
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
    """Return prompt with any missing LoRA trigger words appended."""
    probe = dict(values)
    probe["prompt"] = prompt
    out = (prompt or "").strip()
    for trigger in _missing_lora_trigger_words(probe):
        out = prompt_with_lora_trigger_added(out, trigger)
    return out


def apply_lora_triggers_for_run(values: Dict[str, Any]) -> None:
    """Mutate ``values['prompt']`` in place; does not affect persisted dialog text."""
    prompt = (values.get("prompt") or "").strip()
    values["prompt"] = augment_prompt_with_missing_lora_triggers(prompt, values)
