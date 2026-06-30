#!/usr/bin/env python3
"""Mount flux-prompt system prompt UI on image-gen dialogs."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget
from imagegen_plugins.image_gen_persistence import (
    load_flux_prompt_system_prompt_settings,
    save_flux_prompt_system_prompt_settings,
)
from imagegen_plugins.imagegen_flux_prompt_ai import ImageGenFluxPromptAi
from imagegen_plugins.lmstudio_instructions_pane import LmStudioInstructionsPane
from imagegen_plugins.lmstudio_caption import is_lmstudio_services_available


def _image_prompt_action_column(
    owner: Any,
) -> Optional[tuple[QVBoxLayout, QWidget, QPushButton]]:
    """VBox to the right of the image prompt field (copy button column)."""
    from imagegen_plugins.image_gen_form_layout import ImageGenFieldsPanel

    panel: Optional[ImageGenFieldsPanel] = getattr(owner, "_fields_panel", None)
    if panel is None or panel._prompt_group is None:
        return None
    copy_btn = panel._prompt_group.findChild(QPushButton, "imageGenPromptCopyBtn")
    if copy_btn is None:
        return None
    action_col = copy_btn.parentWidget()
    if action_col is None:
        return None
    layout = action_col.layout()
    if not isinstance(layout, QVBoxLayout):
        return None
    return layout, action_col, copy_btn


def _remove_button_from_layout(layout: QVBoxLayout, btn: QPushButton) -> None:
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is not None and item.widget() is btn:
            layout.removeWidget(btn)
            return


def sync_flux_prompt_system_toggle_location(owner: Any) -> None:
    """System-prompt action column when open; image-prompt column when collapsed."""
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    btn = getattr(owner, "_flux_system_prompt_toggle_btn", None)
    if pane is None or btn is None:
        return
    try:
        from shiboken6 import isValid

        if not isValid(btn):
            return
    except Exception:
        return

    parent = btn.parentWidget()
    if parent is not None:
        layout = parent.layout()
        if isinstance(layout, QVBoxLayout):
            _remove_button_from_layout(layout, btn)

    if pane.is_visible():
        pane.mount_toggle_in_action_column(btn)
        return

    found = _image_prompt_action_column(owner)
    if found is None:
        return
    action_layout, action_col, copy_btn = found
    btn.setParent(action_col)
    insert_at = 0
    for i in range(action_layout.count()):
        item = action_layout.itemAt(i)
        if item is not None and item.widget() is copy_btn:
            insert_at = i + 1
            break
    action_layout.insertWidget(
        insert_at,
        btn,
        0,
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
    )


from imagegen_plugins.image_gen_form_layout import ImageGenFieldsPanel


def _persist_flux_prompt_system_prompt(owner: Any) -> None:
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None:
        return
    save_flux_prompt_system_prompt_settings(
        pane.plain_text(),
        pane.is_visible(),
        pane.splitter_sizes(),
    )


def _load_flux_prompt_system_prompt_into_pane(pane: LmStudioInstructionsPane) -> None:
    text, visible, sizes = load_flux_prompt_system_prompt_settings()
    pane.set_plain_text(text)
    pane.set_visible(visible)
    pane.set_splitter_sizes(sizes)


def _flux_pass_image_noun(owner: Any) -> str:
    if getattr(owner, "source_path", None):
        return "source image"
    return "active image"


def ensure_flux_prompt_system_pane(owner: Any) -> Optional[LmStudioInstructionsPane]:
    if not is_lmstudio_services_available():
        return None
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is not None:
        return pane

    def _on_changed() -> None:
        _persist_flux_prompt_system_prompt(owner)
        if getattr(owner, "_panel_mode", False) and hasattr(owner, "state_changed"):
            owner.state_changed.emit()

    pane = LmStudioInstructionsPane(
        owner,
        image_gen_styled=True,
        on_visibility_changed=_on_changed,
        on_text_changed=_on_changed,
    )
    _load_flux_prompt_system_prompt_into_pane(pane)
    owner._flux_system_prompt_pane = pane
    return pane


def mount_flux_prompt_system_toggle(owner: Any) -> None:
    """Place the system-prompt AI toggle in the system prompt action column."""
    pane = ensure_flux_prompt_system_pane(owner)
    if pane is None:
        return

    old = getattr(owner, "_flux_system_prompt_toggle_btn", None)
    if old is not None:
        try:
            from shiboken6 import isValid

            if isValid(old):
                old.deleteLater()
        except Exception:
            pass
        owner._flux_system_prompt_toggle_btn = None

    btn = pane.toggle_button(recreate=True)
    owner._flux_system_prompt_toggle_btn = btn
    sync_flux_prompt_system_toggle_location(owner)
    pane.sync_toggle_highlight()


def mount_flux_prompt_ai_toolbar(owner: Any, flux_ai: ImageGenFluxPromptAi) -> None:
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None:
        return
    toolbar = flux_ai.create_toolbar(
        owner, image_noun=_flux_pass_image_noun(owner)
    )
    if toolbar is None:
        return
    pane.set_toolbar_widget(toolbar)


def remount_flux_prompt_system_splitter(owner: Any) -> None:
    """Place system prompt above Image Prompt label; mount toggle and AI toolbar."""
    pane = ensure_flux_prompt_system_pane(owner)
    panel: Optional[ImageGenFieldsPanel] = getattr(owner, "_fields_panel", None)
    if pane is None or panel is None or panel._prompt_group is None:
        return
    panel.mount_system_prompt_above_image_prompt(pane.widget())
    _load_flux_prompt_system_prompt_into_pane(pane)
    mount_flux_prompt_system_toggle(owner)
    ensure_flux = getattr(owner, "_ensure_flux_prompt_ai", None)
    if callable(ensure_flux):
        mount_flux_prompt_ai_toolbar(owner, ensure_flux())


def flux_prompt_system_override_for(owner: Any) -> Optional[str]:
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None:
        return None
    return pane.effective_override_text()
