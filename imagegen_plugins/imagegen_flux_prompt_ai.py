#!/usr/bin/env python3
"""AI / Undo AI buttons for image-gen dialogs: refine prompts via LM Studio for FLUX."""

from __future__ import annotations

import os
from typing import Any, Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from imagegen_plugins.image_gen_form_layout import (
    IMAGE_GEN_FIELD_BORDER_PAD,
    image_gen_prompt_edit_set_plain_text,
    image_gen_prompt_stream_session_begin,
    image_gen_prompt_stream_session_end,
    make_image_gen_field_label,
)
from thumbnails.thumbnail_constants import ALT_SYMBOL, ENTER_SYMBOL, SHIFT_SYMBOL
from imagegen_plugins.image_gen_persistence import (
    load_flux_prompt_job_with_generate,
    load_pass_image_to_ai_with_prompt,
    save_flux_prompt_job_with_generate,
    save_pass_image_to_ai_with_prompt,
)
from imagegen_plugins.flux_prompt_job import (
    allow_empty_prompt_for_ai_refine,
    attach_flux_prompt_ai_job_to_values,
    resolve_flux_prompt_refine_image_paths,
)
from imagegen_plugins.lmstudio_caption import is_lmstudio_services_available
from workers.model_tasks_worker import flux_prompt_system_message
from utils import get_main_window


def _flux_prompt_shortcut_owner(host: Any) -> Any:
    panel = getattr(host, "_current_panel", None)
    if panel is not None:
        return panel
    return host


def flux_prompt_gen_shortcut_active(owner: Any) -> bool:
    """True when Option+Enter should trigger the Gen Prompt button."""
    flux_ai = getattr(owner, "_flux_prompt_ai", None)
    if flux_ai is None:
        return False
    if not flux_ai.ai_controls_active(owner):
        return False
    btn = flux_ai._ai_btn
    return btn is not None and btn.isVisible() and btn.isEnabled()


def click_flux_prompt_gen_if_active(host: Any) -> bool:
    """Click Gen Prompt / Cancel when AI controls are active. Returns True if handled."""
    owner = _flux_prompt_shortcut_owner(host)
    if not flux_prompt_gen_shortcut_active(owner):
        return False
    flux_ai = owner._flux_prompt_ai
    btn = flux_ai._ai_btn if flux_ai is not None else None
    if btn is None or not btn.isEnabled():
        return False
    btn.click()
    return True


def flux_prompt_undo_shortcut_active(owner: Any) -> bool:
    """True when Shift+Option+Enter should trigger Undo AI."""
    flux_ai = getattr(owner, "_flux_prompt_ai", None)
    if flux_ai is None:
        return False
    if not flux_ai.ai_controls_active(owner):
        return False
    btn = flux_ai._undo_btn
    return btn is not None and btn.isVisible() and btn.isEnabled()


def click_flux_prompt_undo_if_active(host: Any) -> bool:
    """Click Undo AI when shown. Returns True if handled."""
    owner = _flux_prompt_shortcut_owner(host)
    if not flux_prompt_undo_shortcut_active(owner):
        return False
    flux_ai = owner._flux_prompt_ai
    btn = flux_ai._undo_btn if flux_ai is not None else None
    if btn is None or not btn.isEnabled():
        return False
    btn.click()
    return True


def _host_image_gen_dialog(widget: QWidget) -> QWidget | None:
    host: QWidget | None = widget
    while host is not None:
        if getattr(host, "_image_gen_footer_key_filter", None) is not None:
            return host
        host = host.parentWidget()
    return None


def refresh_flux_prompt_keyboard_shortcuts(owner: Any) -> None:
    """Attach footer key filter to flux-prompt widgets added after initial dialog setup."""
    dialog = _host_image_gen_dialog(owner if isinstance(owner, QWidget) else None)
    if dialog is None and isinstance(owner, QWidget):
        dialog = _host_image_gen_dialog(owner.window())
    if dialog is None:
        return
    from imagegen_plugins.image_gen_function_switcher import (
        refresh_image_gen_footer_keyboard_shortcuts,
    )

    refresh_image_gen_footer_keyboard_shortcuts(dialog)


def _show_ai_caption_error_dialog(*args, **kwargs):
    from browser_window.managers.lmstudio_launcher import show_ai_caption_error_dialog

    return show_ai_caption_error_dialog(*args, **kwargs)


def configure_flux_prompt_toolbar_button(button: QPushButton) -> None:
    button.setObjectName("imageGenFluxPromptToolbarBtn")
    button.setCursor(Qt.CursorShape.PointingHandCursor)


def configure_flux_prompt_toolbar_checkbox(checkbox: QCheckBox) -> None:
    checkbox.setObjectName("imageGenFluxPromptToolbarPassImage")


_FLUX_PROMPT_GEN_LABEL = "Gen Prompt"
_FLUX_PROMPT_GEN_BUTTON_LABEL = f"{_FLUX_PROMPT_GEN_LABEL} {ALT_SYMBOL}{ENTER_SYMBOL}"
_FLUX_PROMPT_CANCEL_LABEL = "Cancel"
_FLUX_PROMPT_GEN_TOOLTIP = (
    "Refine the image prompt for FLUX using LMStudio\n"
    f"({ALT_SYMBOL}{ENTER_SYMBOL})\n"
    "(requires a text model loaded in LM Studio)"
)
_FLUX_PROMPT_CANCEL_TOOLTIP = "Stop the in-progress prompt refinement"
_FLUX_PROMPT_UNDO_TOOLTIP = (
    "Restore the prompt from before the last AI refinement\n"
    f"({SHIFT_SYMBOL}{ALT_SYMBOL}{ENTER_SYMBOL})"
)
_FLUX_PROMPT_UNDO_LABEL = "Undo AI"
_FLUX_PROMPT_UNDO_BUTTON_LABEL = (
    f"{_FLUX_PROMPT_UNDO_LABEL} {SHIFT_SYMBOL}{ALT_SYMBOL}{ENTER_SYMBOL}"
)
_FLUX_PROMPT_TOOLBAR_SPACING = 16
_FLUX_PROMPT_PRIMARY_BTN_WIDTH = 88


def apply_flux_prompt_primary_button_width(button: QPushButton) -> None:
    button.setFixedWidth(_FLUX_PROMPT_PRIMARY_BTN_WIDTH)
    button.setSizePolicy(
        QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
    )


def cancel_dialog_flux_prompt_refine(owner: Any) -> None:
    """Stop in-progress Gen Prompt toolbar refinement (not submitted job AI stages)."""
    panels = getattr(owner, "_panels", None)
    if isinstance(panels, dict):
        for panel in panels.values():
            cancel_dialog_flux_prompt_refine(panel)
        return
    flux_ai = getattr(owner, "_flux_prompt_ai", None)
    if flux_ai is not None:
        flux_ai.cancel_running()


class ImageGenFluxPromptAi:
    """Prompt AI controls for image-gen dialogs (toolbar under system prompt)."""

    def __init__(
        self,
        dialog: QWidget,
        *,
        task_kind: str,
        get_prompt_text: Callable[[], str],
        set_prompt_text: Callable[[str], None],
        get_pass_image: Optional[Callable[[], bool]] = None,
        get_image_path: Optional[Callable[[], str]] = None,
        get_image_paths: Optional[Callable[[], list[str]]] = None,
        get_prompt_edit: Optional[Callable[[], Optional[QPlainTextEdit]]] = None,
        get_system_prompt_override: Optional[Callable[[], Optional[str]]] = None,
    ):
        self._dialog = dialog
        self._task_kind = task_kind
        self._get_prompt_text = get_prompt_text
        self._set_prompt_text = set_prompt_text
        self._get_pass_image = get_pass_image
        self._get_image_path = get_image_path
        self._get_image_paths = get_image_paths
        self._get_prompt_edit = get_prompt_edit
        self._get_system_prompt_override = get_system_prompt_override
        self._ai_btn: Optional[QPushButton] = None
        self._undo_btn: Optional[QPushButton] = None
        self._pass_image_cb: Optional[QCheckBox] = None
        self._job_cb: Optional[QCheckBox] = None
        self._toolbar: Optional[QWidget] = None
        self._connected = False
        self._streaming_started = False
        self._running = False
        self._user_cancelled = False
        self._prompt_before_ai = ""
        self._undo_available = False
        self._dot_phase = 0
        self._dot_timer = QTimer(dialog)
        self._dot_timer.setInterval(400)
        self._dot_timer.timeout.connect(self._on_dot_tick)

    def make_action_buttons(self) -> list[QPushButton]:
        """Legacy side-column hook; controls live in the system-prompt toolbar."""
        return []

    def create_toolbar(
        self,
        owner: Any,
        *,
        image_noun: str = "source image",
    ) -> Optional[QWidget]:
        if not is_lmstudio_services_available():
            return None
        row = QWidget()
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(_FLUX_PROMPT_TOOLBAR_SPACING)
        layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        # controls_label = make_image_gen_field_label("AI Controls:", row)
        # layout.addWidget(controls_label, 0)

        self._ai_btn = QPushButton(_FLUX_PROMPT_GEN_BUTTON_LABEL)
        self._ai_btn.setObjectName("flux_prompt_ai_btn")
        self._ai_btn.setToolTip(_FLUX_PROMPT_GEN_TOOLTIP)
        configure_flux_prompt_toolbar_button(self._ai_btn)
        apply_flux_prompt_primary_button_width(self._ai_btn)
        self._ai_btn.clicked.connect(self._on_primary_ai_clicked)

        self._pass_image_cb = QCheckBox("Pass image to Prompt Generator")
        self._pass_image_cb.setToolTip(
            f"Include the {image_noun} when refining the prompt with AI "
            "(requires a vision-capable model in LM Studio)."
        )
        self._pass_image_cb.setChecked(load_pass_image_to_ai_with_prompt())
        self._pass_image_cb.toggled.connect(
            lambda checked, o=owner: self._on_pass_image_toggled(o, checked)
        )
        configure_flux_prompt_toolbar_checkbox(self._pass_image_cb)
        owner._pass_image_to_ai_cb = self._pass_image_cb

        self._job_cb = QCheckBox("Include AI Prompt Refinement in jobs")
        self._job_cb.setObjectName("flux_prompt_job_cb")
        self._job_cb.setToolTip(
            "When checked, Generate runs AI prompt refinement as the first stage "
            "of the image job (queued or immediate)."
        )
        self._job_cb.setChecked(load_flux_prompt_job_with_generate())
        self._job_cb.toggled.connect(
            lambda checked, o=owner: self._on_job_toggled(o, checked)
        )
        configure_flux_prompt_toolbar_checkbox(self._job_cb)

        self._undo_btn = QPushButton(_FLUX_PROMPT_UNDO_BUTTON_LABEL)
        self._undo_btn.setObjectName("flux_prompt_undo_ai_btn")
        self._undo_btn.setToolTip(_FLUX_PROMPT_UNDO_TOOLTIP)
        configure_flux_prompt_toolbar_button(self._undo_btn)
        self._undo_btn.clicked.connect(self._on_undo_clicked)
        self._undo_btn.setVisible(False)

        layout.addWidget(self._ai_btn, 0)
        layout.addWidget(self._pass_image_cb, 0)
        layout.addWidget(self._job_cb, 0)
        layout.addWidget(self._undo_btn, 0)

        self._toolbar = row
        refresh_flux_prompt_keyboard_shortcuts(owner)
        return row

    def ai_controls_mounted(self) -> bool:
        """True when the flux prompt AI toolbar was created."""
        return self._job_cb is not None

    def ai_controls_active(self, owner: Any | None = None) -> bool:
        """True when AI toolbar exists and the system-prompt pane is visible."""
        if not self.ai_controls_mounted():
            return False
        from imagegen_plugins.flux_prompt_system_mount import (
            flux_prompt_ai_controls_visible,
        )

        o = owner if owner is not None else self._dialog
        return flux_prompt_ai_controls_visible(o)

    def _on_pass_image_toggled(self, owner: Any, checked: bool) -> None:
        try:
            save_pass_image_to_ai_with_prompt(bool(checked))
        except Exception:
            pass
        if getattr(owner, "_panel_mode", False) and hasattr(owner, "state_changed"):
            owner.state_changed.emit()

    def _on_job_toggled(self, owner: Any, checked: bool) -> None:
        try:
            save_flux_prompt_job_with_generate(bool(checked))
        except Exception:
            pass
        if getattr(owner, "_panel_mode", False) and hasattr(owner, "state_changed"):
            owner.state_changed.emit()

    def job_checkbox_checked(self, owner: Any | None = None) -> bool:
        if not self.ai_controls_active(owner):
            return False
        return self._job_cb.isChecked()

    def attach_job_ai_meta_to_values(self, owner: Any, values: dict) -> bool:
        return attach_flux_prompt_ai_job_to_values(owner, values, force=False)

    def attach_job_ai_meta_for_queue(self, owner: Any, values: dict) -> bool:
        return attach_flux_prompt_ai_job_to_values(owner, values, force=True)

    def _pass_image_checked(self) -> bool:
        from imagegen_plugins.flux_prompt_job import pass_image_checked_for_owner

        if self._pass_image_cb is not None:
            return self._pass_image_cb.isChecked()
        return pass_image_checked_for_owner(self._dialog)

    def _update_action_buttons(self) -> None:
        if self._undo_btn is not None:
            self._undo_btn.setVisible(
                not self._running and self._undo_available and bool(self._prompt_before_ai)
            )

    def _set_ai_button_idle(self) -> None:
        if self._ai_btn is None:
            return
        self._ai_btn.setEnabled(True)
        self._ai_btn.setText(_FLUX_PROMPT_GEN_BUTTON_LABEL)
        self._ai_btn.setToolTip(_FLUX_PROMPT_GEN_TOOLTIP)

    def _set_ai_button_running(self) -> None:
        if self._ai_btn is None:
            return
        self._ai_btn.setEnabled(True)
        self._ai_btn.setText(_FLUX_PROMPT_CANCEL_LABEL)
        self._ai_btn.setToolTip(_FLUX_PROMPT_CANCEL_TOOLTIP)

    def _on_primary_ai_clicked(self) -> None:
        if self._running:
            self._on_cancel_clicked()
        else:
            self._on_ai_clicked()

    def _on_undo_clicked(self) -> None:
        if not self._prompt_before_ai:
            return
        self._set_prompt_text(self._prompt_before_ai)
        self._prompt_before_ai = ""
        self._undo_available = False
        self._update_action_buttons()

    def _imagegen_controller(self):
        from imagegen_plugins.image_gen_controller import get_imagegen_controller

        mw = get_main_window() or self._dialog.parent()
        if mw is None:
            return None
        return get_imagegen_controller(mw)

    def _on_cancel_clicked(self) -> None:
        controller = self._imagegen_controller()
        if controller is None:
            return
        self._user_cancelled = True
        controller.cancel_flux_prompt_refine()

    def cancel_running(self) -> None:
        """Public entry for dialog dismiss (Close, Cancel, Escape)."""
        if not self._running:
            return
        self._on_cancel_clicked()

    def _on_ai_clicked(self) -> None:
        if self._ai_btn is None:
            return
        controller = self._imagegen_controller()
        if controller is None:
            return
        if controller.has_pending_work():
            _show_ai_caption_error_dialog(
                self._dialog,
                "Wait for the job queue to finish or cancel queued jobs "
                "before refining a prompt with AI.",
                window_title="AI Prompt Error",
                cancel_label="Cancel",
                on_run_now=lambda: self._start_ai_refine(foreground=True),
                run_now_tooltip=(
                    "Run AI prompt refinement concurrent with image generation. "
                    "May be slow."
                ),
                on_queue_job=self._queue_generate_with_ai,
                queue_job_tooltip=(
                    "Queue image generation with AI prompt refinement as the first stage."
                ),
            )
            return
        self._start_ai_refine(foreground=False)

    def _resolve_generate_owner(self) -> Any:
        owner = self._dialog
        panel = getattr(owner, "_current_panel", None)
        if panel is not None:
            return panel
        return owner

    def _queue_generate_with_ai(self) -> None:
        owner = self._resolve_generate_owner()
        prepare = getattr(owner, "_prepare_run_values", None)
        plugin = getattr(owner, "plugin", None)
        if prepare is None or plugin is None:
            _show_ai_caption_error_dialog(
                self._dialog,
                "Could not queue a job from this dialog.",
                window_title="AI Prompt Error",
                cancel_label="Cancel",
            )
            return
        try:
            values = prepare(force_flux_ai_job=True)
        except TypeError:
            values = prepare()
        if values is None:
            return
        controller = self._imagegen_controller()
        if controller is None:
            return
        from imagegen_plugins.image_gen_active_model import set_active_plugin_for_function
        from imagegen_plugins.image_gen_model_availability import (
            confirm_model_download_if_needed,
        )
        from imagegen_plugins.image_gen_persistence import save_plugin_dialog_settings

        function = getattr(owner, "_function", None)
        mw = get_main_window() or self._dialog.parent()
        if mw is None or function is None:
            return
        if not confirm_model_download_if_needed(plugin, mw):
            return
        save_plugin_dialog_settings(function, plugin.plugin_id, values)
        set_active_plugin_for_function(mw, function, plugin)
        if not controller.enqueue_generation(plugin, values):
            _show_ai_caption_error_dialog(
                self._dialog,
                "Could not queue the job.",
                window_title="AI Prompt Error",
                cancel_label="Cancel",
            )

    def _start_ai_refine(self, *, foreground: bool = False) -> None:
        if self._ai_btn is None:
            return
        controller = self._imagegen_controller()
        if controller is None:
            return
        if foreground and controller.is_foreground_caption_running():
            _show_ai_caption_error_dialog(
                self._dialog,
                "A foreground AI text task is already running.",
                window_title="AI Prompt Error",
                cancel_label="Cancel",
            )
            return

        preflight_error = self._preflight_ai_refine()
        if preflight_error:
            _show_ai_caption_error_dialog(
                self._dialog,
                preflight_error,
                window_title="AI Prompt Error",
                cancel_label="Cancel",
            )
            return

        self._prompt_before_ai = self._get_prompt_text()
        self._undo_available = False
        self._user_cancelled = False
        self._running = True
        self._update_action_buttons()
        self._begin_prompt_stream_scroll_session()

        self._set_ai_button_running()
        self._dot_phase = 0
        self._dot_timer.start()

        if not self._connected:
            controller.flux_prompt_chunk.connect(self._on_chunk)
            controller.flux_prompt_ready.connect(self._on_ready)
            controller.flux_prompt_error.connect(self._on_error)
            controller.flux_prompt_finished.connect(self._on_finished)
            self._connected = True

        user_prompt = self._prompt_before_ai.strip()
        image_paths = self._resolve_image_paths_for_refine()
        override = None
        if self._get_system_prompt_override is not None:
            override = self._get_system_prompt_override()
        if override:
            system_prompt = override
        else:
            system_prompt = flux_prompt_system_message(
                self._task_kind,
                with_image=bool(image_paths),
                image_count=len(image_paths),
            )
        self._streaming_started = False
        if foreground:
            started = controller.start_flux_prompt_refine_foreground(
                system_prompt, user_prompt, image_paths=image_paths
            )
        else:
            started = controller.start_flux_prompt_refine(
                system_prompt, user_prompt, image_paths=image_paths
            )
        if not started:
            self._on_finished()
            _show_ai_caption_error_dialog(
                self._dialog,
                "Could not start AI prompt refinement (another task may be running).",
                window_title="AI Prompt Error",
                cancel_label="Cancel",
            )

    def _resolve_image_paths_for_refine(self) -> list[str]:
        if not self._pass_image_checked():
            return []
        paths = resolve_flux_prompt_refine_image_paths(self._dialog)
        if paths:
            return paths
        raw_paths: list[str] = []
        if self._get_image_paths is not None:
            raw_paths = list(self._get_image_paths() or [])
        elif self._get_image_path is not None:
            single = (self._get_image_path() or "").strip()
            if single:
                raw_paths = [single]
        resolved: list[str] = []
        for raw in raw_paths:
            path = (raw or "").strip()
            if path and os.path.isfile(path) and path not in resolved:
                resolved.append(path)
        return resolved

    def _preflight_ai_refine(self) -> Optional[str]:
        """Return an error message when refine cannot start, else None."""
        if allow_empty_prompt_for_ai_refine(self, self._dialog):
            return None
        if self._pass_image_checked():
            return (
                "Pass image is checked but no image is available.\n\n"
                "Select an image or enter a prompt."
            )
        return None

    def _prompt_edit_widget(self) -> QPlainTextEdit | None:
        if self._get_prompt_edit is None:
            return None
        return self._get_prompt_edit()

    def _begin_prompt_stream_scroll_session(self) -> None:
        edit = self._prompt_edit_widget()
        if edit is not None:
            image_gen_prompt_stream_session_begin(edit)

    def _end_prompt_stream_scroll_session(self) -> None:
        edit = self._prompt_edit_widget()
        if edit is not None:
            image_gen_prompt_stream_session_end(edit)

    def _set_streaming_prompt_text(self, text: str) -> None:
        edit = self._prompt_edit_widget()
        if edit is not None:
            image_gen_prompt_edit_set_plain_text(edit, text, streaming=True)
            return
        self._set_prompt_text(text)

    def _on_dot_tick(self) -> None:
        if not self._running:
            return
        self._dot_phase = (self._dot_phase + 1) % 4
        dots = "." * (self._dot_phase + 1)
        self._set_streaming_prompt_text(dots)

    def _stop_dots(self) -> None:
        self._dot_timer.stop()

    def _on_chunk(self, chunk: str) -> None:
        if not self._running:
            return
        if not self._streaming_started:
            self._streaming_started = True
            self._stop_dots()
            self._set_streaming_prompt_text(chunk)
        else:
            self._set_streaming_prompt_text(self._get_prompt_text() + chunk)

    def _on_ready(self, text: str) -> None:
        if not self._running:
            return
        self._set_streaming_prompt_text(text)

    def _on_error(self, error_msg: str) -> None:
        if not self._running:
            return
        self._end_prompt_stream_scroll_session()
        self._set_prompt_text(self._prompt_before_ai)
        self._prompt_before_ai = ""
        self._undo_available = False
        self._running = False
        self._user_cancelled = False
        self._update_action_buttons()
        self._set_ai_button_idle()
        _show_ai_caption_error_dialog(
            self._dialog, error_msg, window_title="AI Prompt Error", cancel_label="Cancel"
        )

    def _on_finished(self) -> None:
        if not self._running and not self._user_cancelled:
            return
        self._stop_dots()
        self._end_prompt_stream_scroll_session()
        self._set_ai_button_idle()
        self._running = False
        if self._user_cancelled:
            self._set_prompt_text(self._prompt_before_ai)
            self._prompt_before_ai = ""
            self._undo_available = False
            self._user_cancelled = False
        else:
            self._undo_available = bool(self._prompt_before_ai)
        self._update_action_buttons()
