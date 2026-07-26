#!/usr/bin/env python3
"""Mount flux-prompt system prompt UI on image-gen dialogs."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import QTimer
from imagegen_plugins.image_gen_persistence import (
    load_flux_prompt_system_prompt_settings,
    save_flux_prompt_system_prompt_settings,
)
from imagegen_plugins.imagegen_flux_prompt_ai import (
    ImageGenFluxPromptAi,
    refresh_flux_prompt_keyboard_shortcuts,
)
from imagegen_plugins.lmstudio_instructions_pane import LmStudioInstructionsPane
from imagegen_plugins.lmstudio_caption import (
    is_lmstudio_sdk_installed,
    is_lmstudio_services_available,
)


from imagegen_plugins.image_gen_form_layout import ImageGenFieldsPanel


def _owner_deferring_flux_extras(owner: Any) -> bool:
    return bool(getattr(owner, "_defer_flux_prompt_extras", False))


def _persist_flux_prompt_system_prompt(owner: Any) -> None:
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None:
        return
    save_flux_prompt_system_prompt_settings(
        pane.plain_text(),
        pane.is_visible(),
        pane.splitter_sizes(),
        editor_expanded=pane.is_editor_expanded(),
    )


def _load_flux_prompt_system_prompt_into_pane(pane: LmStudioInstructionsPane) -> None:
    already_open = pane.is_visible()
    text, saved_visible, sizes, saved_expanded = load_flux_prompt_system_prompt_settings()
    pane.set_plain_text(text)
    pane.set_editor_expanded(saved_expanded)
    owner = getattr(pane, "_parent", None)
    if owner is not None and _owner_deferring_flux_extras(owner):
        pane.set_visible(already_open)
    elif is_lmstudio_services_available():
        pane.set_visible(saved_visible or already_open)
    else:
        pane.set_visible(already_open)
    pane.set_splitter_sizes(sizes)


def _flux_pass_image_noun(owner: Any) -> str:
    if getattr(owner, "_multi_source", False):
        return "source images"
    if getattr(owner, "source_path", None):
        return "source image"
    return "active image"


def ensure_flux_prompt_system_pane(owner: Any) -> Optional[LmStudioInstructionsPane]:
    if not is_lmstudio_sdk_installed():
        return None
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is not None:
        return pane

    def _on_text_changed() -> None:
        _persist_flux_prompt_system_prompt(owner)
        if getattr(owner, "_panel_mode", False) and hasattr(owner, "state_changed"):
            owner.state_changed.emit()

    def _on_visibility_changed() -> None:
        _persist_flux_prompt_system_prompt(owner)
        refresh_flux_prompt_keyboard_shortcuts(owner)
        if getattr(owner, "_panel_mode", False) and hasattr(owner, "state_changed"):
            owner.state_changed.emit()

    def _on_editor_expanded_changed() -> None:
        _persist_flux_prompt_system_prompt(owner)

    pane = LmStudioInstructionsPane(
        owner,
        image_gen_styled=True,
        label_text="System Prompt",
        section_label_text="AI Prompt Enhancement",
        on_visibility_changed=_on_visibility_changed,
        on_text_changed=_on_text_changed,
        on_editor_expanded_changed=_on_editor_expanded_changed,
    )
    _load_flux_prompt_system_prompt_into_pane(pane)
    owner._flux_system_prompt_pane = pane
    return pane


def mount_flux_prompt_ai_toolbar(owner: Any, flux_ai: ImageGenFluxPromptAi) -> None:
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None:
        return
    image_noun = _flux_pass_image_noun(owner)
    toolbar = flux_ai.create_toolbar(owner, image_noun=image_noun)
    if toolbar is None:
        return
    pane.set_toolbar_widget(toolbar)
    job_row = flux_ai.create_job_checkbox_row(owner, image_noun=image_noun)
    if job_row is not None:
        pane.set_below_section_widget(job_row)
    refresh_flux_prompt_keyboard_shortcuts(owner)


def remount_flux_prompt_system_splitter(owner: Any) -> None:
    """Place AI prompt enhancement below image prompt; mount AI controls."""
    pane = ensure_flux_prompt_system_pane(owner)
    panel: Optional[ImageGenFieldsPanel] = getattr(owner, "_fields_panel", None)
    if pane is None or panel is None or panel._prompt_group is None:
        return
    panel.mount_system_prompt_below_image_prompt(pane.widget())
    _load_flux_prompt_system_prompt_into_pane(pane)
    pane.sync_image_gen_content_visibility()
    if not is_lmstudio_services_available():
        return
    ensure_flux = getattr(owner, "_ensure_flux_prompt_ai", None)
    if callable(ensure_flux):
        mount_flux_prompt_ai_toolbar(owner, ensure_flux())


def schedule_deferred_flux_prompt_extras(owner: Any) -> None:
    """Defer LM Studio network probe and flux prompt UI mount until after first paint."""
    if getattr(owner, "_flux_extras_deferred", False):
        return
    owner._flux_extras_deferred = True
    QTimer.singleShot(50, lambda: _deferred_mount_flux_prompt_extras(owner))


def _deferred_mount_flux_prompt_extras(owner: Any) -> None:
    if not is_lmstudio_sdk_installed():
        return
    if not is_lmstudio_services_available():
        return
    setattr(owner, "_defer_flux_prompt_extras", False)
    remount_flux_prompt_system_splitter(owner)


def flux_prompt_system_override_for(owner: Any) -> Optional[str]:
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None:
        return None
    return pane.effective_override_text()


def flux_prompt_ai_controls_visible(owner: Any) -> bool:
    """True when the AI Prompt Enhancement section is expanded."""
    if _owner_deferring_flux_extras(owner):
        return False
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None or not pane.is_visible():
        return False
    return is_lmstudio_services_available()
