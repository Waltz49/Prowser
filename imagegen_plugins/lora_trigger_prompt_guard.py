#!/usr/bin/env python3
"""Confirm LoRA trigger words appear in the generation prompt before run."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from PySide6.QtWidgets import QMessageBox

from imagegen_plugins.lora_catalog import get_lora_entry, lora_base_display_name
from imagegen_plugins.mflux_lora_presets import coerce_lora_preset_id
from utils import styled_message_box


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


def validate_lora_trigger_before_generate(
    dialog: Any,
    values: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    When the selected LoRA defines a trigger, ensure the prompt contains it.

    Returns updated values, unchanged values (Ignore), or None (Cancel).
    """
    lora_id = coerce_lora_preset_id(values.get("mflux_lora", "none"))
    if lora_id == "none":
        return values
    entry = get_lora_entry(lora_id)
    if entry is None:
        return values
    trigger = (entry.trigger_word or "").strip()
    if not trigger:
        return values

    prompt = (values.get("prompt") or "").strip()
    if prompt_contains_lora_trigger(prompt, trigger):
        return values

    plugin = getattr(dialog, "plugin", None)
    model_key = str(
        getattr(plugin, "hf_model_id", None) or values.get("hf_model_id") or ""
    )
    lora_name = lora_base_display_name(entry, model_key=model_key)

    msg_box = styled_message_box(
        dialog,
        QMessageBox.Question,
        "LoRA trigger",
        f"This generation has specified LoRA {lora_name} which requires a trigger.",
        buttons=(
            QMessageBox.StandardButton.Cancel
            | QMessageBox.StandardButton.Ignore
            | QMessageBox.StandardButton.Apply
        ),
        default_button=QMessageBox.StandardButton.Cancel,
        button_label_overrides={
            QMessageBox.StandardButton.Apply: "Add and proceed",
        },
    )
    msg_box.exec()
    choice = msg_box.result_data["button"]

    if choice == QMessageBox.StandardButton.Cancel:
        return None
    if choice == QMessageBox.StandardButton.Ignore:
        return values
    if choice == QMessageBox.StandardButton.Apply:
        updated = dict(values)
        new_prompt = prompt_with_lora_trigger_added(prompt, trigger)
        updated["prompt"] = new_prompt
        apply_prompt = getattr(dialog, "set_prompt_text", None)
        if callable(apply_prompt):
            apply_prompt(new_prompt)
        return updated
    return None
