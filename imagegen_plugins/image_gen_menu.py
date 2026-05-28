#!/usr/bin/env python3
"""Create menu (only when imagegen plugins are available)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QWidgetAction

from imagegen_plugins import (
    create_menu_plugins,
    discover_plugins,
    function_has_plugins,
    plugins_for_function,
)
from imagegen_plugins.image_gen_active_model import (
    FUNCTION_CREATE,
    FUNCTION_EDIT,
    FUNCTION_EXPAND,
    FUNCTION_INFILL,
    FUNCTION_INFILL_PAINT,
    load_last_function,
    save_last_function,
    set_active_plugin_for_function,
)
from imagegen_plugins.image_gen_controller import get_imagegen_controller
from imagegen_plugins.image_gen_job_queue_dialog import show_imagegen_job_queue_dialog
from imagegen_plugins.image_gen_dialog import ImageGenDialog
from imagegen_plugins.image_gen_edit_dialog import (
    ImageGenEditDialog,
    active_image_path_for_edit,
)
from imagegen_plugins.image_gen_expand_dialog import (
    ImageGenExpandDialog,
    active_image_path_for_expand,
)
from imagegen_plugins.image_gen_infill_dialog import ImageGenInfillDialog
from imagegen_plugins.image_gen_infill_paint_dialog import (
    ImageGenInfillPaintDialog,
    active_image_path_for_infill,
)
from imagegen_plugins.image_gen_install_hint import imagegen_backend_missing_message
from imagegen_plugins.image_gen_model_availability import confirm_model_download_if_needed
from imagegen_plugins.image_gen_model_selector import available_plugins
from imagegen_plugins.pixelmator_export import is_pixelmator_pro_installed
from menu_manager import TextSeparator
from utils import show_styled_information, show_styled_warning

_ALT_SLASH = QKeySequence(Qt.AltModifier | Qt.Key_Slash)

_CREATE_FUNCTION_ACTIONS = (
    (FUNCTION_CREATE, "Create an image from text..."),
    (FUNCTION_EDIT, "Edit an image with AI..."),
    (FUNCTION_EXPAND, "Expand existing image..."),
    (FUNCTION_INFILL, "Infill with Pixelmator..."),
    (FUNCTION_INFILL_PAINT, "Infill by painting..."),
)

_FUNCTION_LABELS = {fn: label for fn, label in _CREATE_FUNCTION_ACTIONS}


def _menu_function_actions():
    """Create-menu function items, omitting Pixelmator infill when the app is missing."""
    for function, label in _CREATE_FUNCTION_ACTIONS:
        if function == FUNCTION_INFILL and not is_pixelmator_pro_installed():
            continue
        yield function, label


def _function_menu_label(function: str, *, show_shortcut: bool) -> str:
    label = _FUNCTION_LABELS[function]
    if show_shortcut:
        return f"{label}\t⌥/"
    return label


def _sync_function_menu_shortcuts(main_window) -> None:
    """Show ⌥/ on the last-used Create action and bind the shortcut to it."""
    actions = getattr(main_window, "imagegen_function_actions", None) or {}
    last_fn = load_last_function()
    if last_fn not in actions and actions:
        last_fn = next(iter(actions))
    for function, action in actions.items():
        is_active = function == last_fn
        action.setText(_function_menu_label(function, show_shortcut=is_active))
        action.setShortcut(_ALT_SLASH if is_active else QKeySequence())


def imagegen_plugins_available() -> bool:
    """True when at least one image-generation plugin is registered."""
    try:
        return bool(discover_plugins())
    except Exception:
        return False


def imagegen_edit_plugins_available() -> bool:
    """True when at least one edit-function plugin is registered."""
    try:
        return function_has_plugins(FUNCTION_EDIT)
    except Exception:
        return False


def initial_prompt_from_usercomment(raw: Optional[str]) -> Optional[str]:
    """Prompt text from EXIF user comment (same rules as image-gen Import)."""
    if not raw:
        return None
    from exif_utils import truncate_usercomment_before_prompt

    text = truncate_usercomment_before_prompt(raw).strip()
    return text or None


def open_imagegen_prompt_dialog(
    main_window, *, user_comment: Optional[str] = None
) -> None:
    """Open the last-used function dialog (⌥/), optionally primed."""
    start_active_imagegen_generation(
        main_window,
        initial_prompt=initial_prompt_from_usercomment(user_comment),
    )


def open_imagegen_edit_dialog(
    main_window, *, user_comment: Optional[str] = None
) -> None:
    """Open the AI image edit dialog, optionally primed from user comment."""
    if not imagegen_edit_plugins_available():
        return
    controller = get_imagegen_controller(main_window)
    _schedule_open_dialog_for_function(
        FUNCTION_EDIT,
        main_window,
        controller,
        initial_prompt=initial_prompt_from_usercomment(user_comment),
    )


def _function_error_title(function: str) -> str:
    return _FUNCTION_LABELS.get(function, "Image generation")


def _no_plugins_message(function: str) -> str:
    label = _function_error_title(function).lower()
    return f"No models are registered for {label}."


def _no_available_plugins_message(function: str) -> str:
    plugins = plugins_for_function(function)
    if plugins:
        return imagegen_backend_missing_message(plugins[0])
    return _no_plugins_message(function)


def _open_dialog_for_function(
    function: str,
    main_window,
    controller,
    *,
    initial_prompt: Optional[str] = None,
) -> None:
    if getattr(main_window, "_imagegen_dialog_open", False):
        return

    plugins = plugins_for_function(function)
    if not plugins:
        show_styled_information(
            main_window,
            _function_error_title(function),
            _no_plugins_message(function),
        )
        return

    usable = available_plugins(plugins)
    if not usable:
        show_styled_information(
            main_window,
            "Image generation not installed",
            _no_available_plugins_message(function),
        )
        return

    save_last_function(function)
    _sync_function_menu_shortcuts(main_window)
    main_window._imagegen_dialog_open = True
    try:
        if function == FUNCTION_INFILL_PAINT:
            source_path = active_image_path_for_infill(main_window)
            if not source_path:
                show_styled_warning(
                    main_window,
                    "Infill",
                    "Select an image in browse view, or select a single thumbnail, "
                    "before using infill by painting.",
                )
                return
            dlg = ImageGenInfillPaintDialog(
                plugins,
                source_path,
                controller,
                main_window,
                main_window,
                initial_prompt=initial_prompt,
            )
            dlg.exec()
            return
        if function == FUNCTION_INFILL:
            dlg = ImageGenInfillDialog(
                plugins,
                function,
                main_window,
                initial_prompt=initial_prompt,
            )
        elif function == FUNCTION_EXPAND:
            source_path = active_image_path_for_expand(main_window)
            if not source_path:
                show_styled_warning(
                    main_window,
                    "Expand",
                    "Select an image in browse view, or select a single thumbnail, "
                    "before using expand.",
                )
                return
            dlg = ImageGenExpandDialog(
                plugins,
                function,
                source_path,
                main_window,
                initial_prompt=initial_prompt,
            )
        elif function == FUNCTION_EDIT:
            source_path = active_image_path_for_edit(main_window)
            if not source_path:
                show_styled_warning(
                    main_window,
                    "Edit",
                    "Select an image in browse view, or select a single thumbnail, "
                    "before using edit.",
                )
                return
            dlg = ImageGenEditDialog(
                plugins,
                function,
                source_path,
                main_window,
                initial_prompt=initial_prompt,
            )
        else:
            dlg = ImageGenDialog(
                plugins,
                function,
                main_window,
                initial_prompt=initial_prompt,
            )

        if dlg.exec() != ImageGenDialog.DialogCode.Accepted:
            return
        values = dlg.accepted_values()
        plugin = dlg.accepted_plugin()
        if not values or plugin is None:
            return
        if not confirm_model_download_if_needed(plugin, main_window):
            return
        set_active_plugin_for_function(main_window, function, plugin)
        controller.start_generation(plugin, values)
    finally:
        main_window._imagegen_dialog_open = False


def _schedule_open_dialog_for_function(
    function: str,
    main_window,
    controller,
    *,
    initial_prompt: Optional[str] = None,
) -> None:
    """Open the function dialog on the next event-loop turn (after menu handlers)."""
    QTimer.singleShot(
        0,
        lambda: _open_dialog_for_function(
            function, main_window, controller, initial_prompt=initial_prompt
        ),
    )


def _refresh_create_menu_availability(main_window) -> None:
    """Re-check backend installs and enable Create menu function items."""
    actions = getattr(main_window, "imagegen_function_actions", None) or {}
    if not actions:
        return
    for function, action in actions.items():
        plugins = plugins_for_function(function)
        usable = available_plugins(plugins)
        action.setEnabled(bool(plugins))
        if not plugins:
            action.setToolTip("No models are registered for this action.")
        elif not usable:
            action.setToolTip(
                "Install optional dependencies (see Help or minimal_requirements.txt)"
            )
        else:
            action.setToolTip("")


def start_active_imagegen_generation(
    main_window, *, initial_prompt: Optional[str] = None
) -> None:
    """Run the dialog for the last-used Create function (⌥/)."""
    if not create_menu_plugins():
        return
    actions = getattr(main_window, "imagegen_function_actions", None) or {}
    function = load_last_function()
    plugins = plugins_for_function(function)
    if not plugins or function not in actions:
        for fn, _label in _menu_function_actions():
            if plugins_for_function(fn):
                function = fn
                break
        else:
            return
    controller = get_imagegen_controller(main_window)
    _schedule_open_dialog_for_function(
        function, main_window, controller, initial_prompt=initial_prompt
    )


def setup_create_menu(menubar, main_window) -> None:
    all_plugins = discover_plugins()
    if not all_plugins:
        return

    create_menu = menubar.addMenu("Create")
    main_window.imagegen_create_menu = create_menu
    controller = get_imagegen_controller(main_window)
    main_window.imagegen_function_actions = {}

    experimental_note = QWidgetAction(main_window)
    experimental_note.setDefaultWidget(
        TextSeparator("Image generation is rudimentary")
    )
    create_menu.addAction(experimental_note)

    def _on_function_selected(function: str) -> None:
        _schedule_open_dialog_for_function(function, main_window, controller)

    for function, label in _menu_function_actions():
        action = QAction(label, main_window)
        action.setData(function)
        plugins = plugins_for_function(function, all_plugins)
        action.setEnabled(bool(plugins))
        if not plugins:
            action.setToolTip("No models are registered for this action.")
        action.triggered.connect(
            lambda _checked=False, fn=function: _on_function_selected(fn)
        )
        create_menu.addAction(action)
        main_window.imagegen_function_actions[function] = action

    _sync_function_menu_shortcuts(main_window)

    create_menu.addSeparator()
    queue_action = QAction("Job Queue...", main_window)
    queue_action.setShortcut(QKeySequence("Ctrl+J"))
    queue_action.triggered.connect(
        lambda: show_imagegen_job_queue_dialog(main_window)
    )
    create_menu.addAction(queue_action)

    cancel_action = QAction("Cancel Generation / Caption", main_window)
    cancel_action.setEnabled(False)
    cancel_action.triggered.connect(controller.cancel_generation)
    create_menu.addAction(cancel_action)
    main_window.imagegen_cancel_action = cancel_action

    def _sync_cancel_action_enabled() -> None:
        cancel_action.setEnabled(controller.has_pending_work())

    controller.generation_started.connect(_sync_cancel_action_enabled)
    controller.generation_finished.connect(
        lambda _ok, _path, _err: _sync_cancel_action_enabled()
    )
    controller.queue_changed.connect(_sync_cancel_action_enabled)
    controller.caption_finished.connect(_sync_cancel_action_enabled)

    QTimer.singleShot(0, lambda: _refresh_create_menu_availability(main_window))
    QTimer.singleShot(500, lambda: _refresh_create_menu_availability(main_window))
