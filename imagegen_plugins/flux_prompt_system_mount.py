#!/usr/bin/env python3
"""Mount flux-prompt system prompt UI on image-gen dialogs."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget
from imagegen_plugins.image_gen_persistence import (
    load_flux_prompt_system_prompt_settings,
    save_flux_prompt_system_prompt_settings,
)
from imagegen_plugins.imagegen_flux_prompt_ai import ImageGenFluxPromptAi
from imagegen_plugins.lmstudio_instructions_pane import LmStudioInstructionsPane
from imagegen_plugins.lmstudio_caption import (
    is_lmstudio_sdk_installed,
    is_lmstudio_services_available,
)


def _image_prompt_label_row(
    owner: Any,
) -> Optional[tuple[QHBoxLayout, QWidget, QPushButton]]:
    """Heading row above the image prompt field (label / clear / AI toggle)."""
    from imagegen_plugins.image_gen_form_layout import ImageGenFieldsPanel

    panel: Optional[ImageGenFieldsPanel] = getattr(owner, "_fields_panel", None)
    if panel is None or panel._prompt_group is None:
        return None
    label_row = panel.prompt_field_label_row_widget()
    if label_row is None:
        return None
    layout = label_row.layout()
    if not isinstance(layout, QHBoxLayout):
        return None
    clear_btn = panel._prompt_group.findChild(QPushButton, "imageGenPromptClearBtn")
    if clear_btn is None:
        return None
    return layout, label_row, clear_btn


def _insert_flux_toggle_after_clear(
    label_layout: QHBoxLayout,
    label_row: QWidget,
    btn: QPushButton,
    *,
    clear_btn: QPushButton,
) -> None:
    """Place AI toggle to the right of the prompt clear button in the heading row."""
    btn.setParent(label_row)
    for i in range(label_layout.count()):
        item = label_layout.itemAt(i)
        if item is not None and item.widget() is btn:
            return
    insert_at = label_layout.count()
    for i in range(label_layout.count()):
        item = label_layout.itemAt(i)
        if item is not None and item.widget() is clear_btn:
            insert_at = i + 1
            break
    label_layout.insertWidget(
        insert_at,
        btn,
        0,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    )


def _remove_button_from_layout(layout, btn: QPushButton) -> None:
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is not None and item.widget() is btn:
            layout.removeWidget(btn)
            return


def sync_flux_prompt_system_toggle_location(owner: Any) -> None:
    """Keep the AI toggle in the image-prompt heading row (label / clear / AI)."""
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
        if layout is not None:
            _remove_button_from_layout(layout, btn)

    if not _flux_lmstudio_ui_entry_allowed(pane):
        btn.hide()
        return

    found = _image_prompt_label_row(owner)
    if found is None:
        return
    label_layout, label_row, clear_btn = found
    _insert_flux_toggle_after_clear(
        label_layout,
        label_row,
        btn,
        clear_btn=clear_btn,
    )
    btn.show()


from imagegen_plugins.image_gen_form_layout import ImageGenFieldsPanel


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


def _flux_lmstudio_ui_entry_allowed(pane: Optional[LmStudioInstructionsPane]) -> bool:
    """Show AI toggle / system-prompt entry when LM Studio is up, or pane already open."""
    if is_lmstudio_services_available():
        return True
    return pane is not None and pane.is_visible()


def _hide_flux_system_prompt_toggle(owner: Any) -> None:
    btn = getattr(owner, "_flux_system_prompt_toggle_btn", None)
    if btn is None:
        return
    try:
        from shiboken6 import isValid

        if not isValid(btn):
            return
    except Exception:
        return
    btn.hide()


def _load_flux_prompt_system_prompt_into_pane(pane: LmStudioInstructionsPane) -> None:
    already_open = pane.is_visible()
    text, saved_visible, sizes, saved_expanded = load_flux_prompt_system_prompt_settings()
    pane.set_plain_text(text)
    pane.set_editor_expanded(saved_expanded)
    if is_lmstudio_services_available():
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
        repopulate = getattr(owner, "_repopulate_side_buttons", None)
        if callable(repopulate):
            repopulate()
        if getattr(owner, "_panel_mode", False) and hasattr(owner, "state_changed"):
            owner.state_changed.emit()

    def _on_editor_expanded_changed() -> None:
        _persist_flux_prompt_system_prompt(owner)

    pane = LmStudioInstructionsPane(
        owner,
        image_gen_styled=True,
        on_visibility_changed=_on_visibility_changed,
        on_text_changed=_on_text_changed,
        on_editor_expanded_changed=_on_editor_expanded_changed,
    )
    _load_flux_prompt_system_prompt_into_pane(pane)
    owner._flux_system_prompt_pane = pane
    return pane


def mount_flux_prompt_system_toggle(owner: Any) -> None:
    """Place the AI toggle in the image prompt heading row beside the clear button."""
    pane = ensure_flux_prompt_system_pane(owner)
    if pane is None:
        return
    if not _flux_lmstudio_ui_entry_allowed(pane):
        _hide_flux_system_prompt_toggle(owner)
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
    btn.show()
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
    repopulate = getattr(owner, "_repopulate_side_buttons", None)
    if callable(repopulate):
        repopulate()


def remount_flux_prompt_system_splitter(owner: Any) -> None:
    """Place system prompt below image prompt; mount toggle and AI toolbar."""
    pane = ensure_flux_prompt_system_pane(owner)
    panel: Optional[ImageGenFieldsPanel] = getattr(owner, "_fields_panel", None)
    if pane is None or panel is None or panel._prompt_group is None:
        return
    panel.mount_system_prompt_below_image_prompt(pane.widget())
    _load_flux_prompt_system_prompt_into_pane(pane)
    if not _flux_lmstudio_ui_entry_allowed(pane):
        _hide_flux_system_prompt_toggle(owner)
        return
    mount_flux_prompt_system_toggle(owner)
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
    repopulate = getattr(owner, "_repopulate_side_buttons", None)
    if callable(repopulate):
        repopulate()


def flux_prompt_system_override_for(owner: Any) -> Optional[str]:
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None:
        return None
    return pane.effective_override_text()


def flux_prompt_ai_controls_visible(owner: Any) -> bool:
    """True when the flux system-prompt pane (AI controls) is shown."""
    if not is_lmstudio_services_available():
        return False
    pane = getattr(owner, "_flux_system_prompt_pane", None)
    if pane is None:
        return False
    return pane.is_visible()
