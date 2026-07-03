#!/usr/bin/env python3
"""Mount flux-prompt system prompt UI on image-gen dialogs."""

from __future__ import annotations

from typing import Any, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget
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


def _image_prompt_action_column(
    owner: Any,
) -> Optional[tuple[QVBoxLayout, QWidget, QPushButton, Optional[QPushButton]]]:
    """VBox to the right of the image prompt field (copy / mic button column)."""
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
    mic_btn = panel._prompt_group.findChild(
        QPushButton, "imageGenPromptVoiceMicBtn"
    )
    return layout, action_col, copy_btn, mic_btn


def _insert_flux_toggle_below_mic(
    action_layout: QVBoxLayout,
    action_col: QWidget,
    btn: QPushButton,
    *,
    copy_btn: Optional[QPushButton],
    mic_btn: Optional[QPushButton],
) -> None:
    """Stack AI toggle under copy and optional mic in a prompt action column."""
    btn.setParent(action_col)
    for i in range(action_layout.count()):
        item = action_layout.itemAt(i)
        if item is not None and item.widget() is btn:
            return
    insert_at = action_layout.count()
    anchor = mic_btn if mic_btn is not None else copy_btn
    if anchor is not None:
        for i in range(action_layout.count()):
            item = action_layout.itemAt(i)
            if item is not None and item.widget() is anchor:
                insert_at = i + 1
                break
    action_layout.insertWidget(
        insert_at,
        btn,
        0,
        Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter,
    )


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
        btn.show()
        return

    if not _flux_lmstudio_ui_entry_allowed(pane):
        btn.hide()
        return

    found = _image_prompt_action_column(owner)
    if found is None:
        return
    action_layout, action_col, copy_btn, mic_btn = found
    _insert_flux_toggle_below_mic(
        action_layout,
        action_col,
        btn,
        copy_btn=copy_btn,
        mic_btn=mic_btn,
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
    text, saved_visible, sizes = load_flux_prompt_system_prompt_settings()
    pane.set_plain_text(text)
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


def remount_flux_prompt_system_splitter(owner: Any) -> None:
    """Place system prompt above Image Prompt label; mount toggle and AI toolbar."""
    pane = ensure_flux_prompt_system_pane(owner)
    panel: Optional[ImageGenFieldsPanel] = getattr(owner, "_fields_panel", None)
    if pane is None or panel is None or panel._prompt_group is None:
        return
    panel.mount_system_prompt_above_image_prompt(pane.widget())
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
