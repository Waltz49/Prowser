#!/usr/bin/env python3
"""Create menu (only when imagegen plugins are available)."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QDialog, QMenu, QWidgetAction

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
    MAX_EDIT_SOURCE_IMAGES,
    ImageGenEditDialog,
    active_image_paths_for_edit,
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
from imagegen_plugins.image_gen_naming import resolve_source_image_paths
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
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

_PAINT_INFILL_SOURCE_EXTS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
)


def _is_paint_infill_job_values(values: Dict[str, Any]) -> bool:
    doc_path = str(values.get("pixelmator_doc_path") or "").strip()
    if not doc_path or not os.path.isfile(doc_path):
        return False
    _, ext = os.path.splitext(doc_path)
    return ext.lower() in _PAINT_INFILL_SOURCE_EXTS


def _raise_imagegen_function_dialog(dlg: QDialog) -> None:
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


def _start_generation_from_function_dialog(
    main_window,
    controller,
    function: str,
    dlg,
) -> None:
    values = dlg.accepted_values()
    plugin = dlg.accepted_plugin()
    if not values or plugin is None:
        return
    if not confirm_model_download_if_needed(plugin, main_window):
        return
    set_active_plugin_for_function(main_window, function, plugin)
    QTimer.singleShot(
        0,
        lambda: controller.start_generation(plugin, values),
    )


def _on_imagegen_function_dialog_finished(
    main_window,
    controller,
    function: str,
    dlg,
    result: int,
) -> None:
    if getattr(main_window, "_imagegen_function_dialog", None) is dlg:
        main_window._imagegen_function_dialog = None
    main_window._imagegen_dialog_open = False
    if result != QDialog.DialogCode.Accepted:
        return
    if isinstance(dlg, ImageGenInfillPaintDialog):
        return
    _start_generation_from_function_dialog(main_window, controller, function, dlg)


def _show_imagegen_function_dialog(
    main_window,
    controller,
    function: str,
    dlg: QDialog,
    *,
    keep_open_on_generate: bool = False,
) -> None:
    """Show one function dialog at a time (non-modal)."""
    existing = getattr(main_window, "_imagegen_function_dialog", None)
    if existing is not None and existing.isVisible():
        if keep_open_on_generate and type(existing) is type(dlg):
            dlg.deleteLater()
            _raise_imagegen_function_dialog(existing)
            return
        existing.close()

    main_window._imagegen_function_dialog = dlg
    main_window._imagegen_dialog_open = True
    dlg.finished.connect(
        lambda result, d=dlg: _on_imagegen_function_dialog_finished(
            main_window, controller, function, d, result
        )
    )
    _raise_imagegen_function_dialog(dlg)


def _warn_missing_job_paths(main_window, missing: list[str]) -> None:
    if not missing:
        return
    preview = "\n".join(f"• {p}" for p in missing[:6])
    extra = f"\n…and {len(missing) - 6} more." if len(missing) > 6 else ""
    show_styled_warning(
        main_window,
        "Missing job files",
        "Some files from the original job are no longer available:\n"
        f"{preview}{extra}\n\nThe dialog will open with what could be restored.",
    )


def open_imagegen_dialog_from_job(
    main_window,
    plugin: ImageGenModelPlugin,
    values: Dict[str, Any],
) -> None:
    """Reopen the function dialog prefilled from a queue job (active or pending)."""
    controller = get_imagegen_controller(main_window)
    job_values = dict(values)
    function = plugin.function
    initial_plugin_id = plugin.plugin_id
    initial_prompt = str(job_values.get("prompt") or "").strip() or None

    missing: list[str] = []

    if function == FUNCTION_EDIT:
        source_paths = resolve_source_image_paths(job_values)
        source_paths = [p for p in source_paths if p and os.path.isfile(p)]
        for raw in resolve_source_image_paths(job_values):
            if raw and not os.path.isfile(raw):
                missing.append(raw)
        if not source_paths:
            show_styled_warning(
                main_window,
                "Edit",
                "Source image files for this job are no longer available.",
            )
            return
        plugins = plugins_for_function(function)
        dlg = ImageGenEditDialog(
            plugins,
            function,
            source_paths[0],
            main_window,
            source_paths=source_paths,
            initial_plugin_id=initial_plugin_id,
            initial_prompt=initial_prompt,
            initial_values=job_values,
        )
    elif function == FUNCTION_EXPAND:
        source_path = str(job_values.get("source_image_path") or "").strip()
        if not source_path or not os.path.isfile(source_path):
            missing.append(source_path or "(source image)")
            show_styled_warning(
                main_window,
                "Expand",
                "Source image for this job is no longer available.",
            )
            return
        plugins = plugins_for_function(function)
        dlg = ImageGenExpandDialog(
            plugins,
            function,
            source_path,
            main_window,
            initial_plugin_id=initial_plugin_id,
            initial_prompt=initial_prompt,
            initial_values=job_values,
        )
    elif function == FUNCTION_INFILL:
        if _is_paint_infill_job_values(job_values):
            source_path = str(job_values.get("pixelmator_doc_path") or "").strip()
            mask_path = str(job_values.get("pixelmator_mask_path") or "")
            if mask_path and not os.path.isfile(mask_path):
                missing.append(mask_path)
            plugins = plugins_for_function(FUNCTION_INFILL_PAINT)
            dlg = ImageGenInfillPaintDialog(
                plugins,
                source_path,
                controller,
                main_window,
                main_window,
                initial_plugin_id=initial_plugin_id,
                initial_prompt=initial_prompt,
                initial_values=job_values,
            )
            _warn_missing_job_paths(main_window, missing)
            _show_imagegen_function_dialog(
                main_window,
                controller,
                FUNCTION_INFILL_PAINT,
                dlg,
                keep_open_on_generate=True,
            )
            return
        base_path = str(job_values.get("pixelmator_base_path") or "")
        mask_path = str(job_values.get("pixelmator_mask_path") or "")
        for path in (base_path, mask_path):
            if path and not os.path.isfile(path):
                missing.append(path)
        plugins = plugins_for_function(function)
        dlg = ImageGenInfillDialog(
            plugins,
            function,
            main_window,
            initial_plugin_id=initial_plugin_id,
            initial_prompt=initial_prompt,
            initial_values=job_values,
        )
    else:
        plugins = plugins_for_function(function)
        dlg = ImageGenDialog(
            plugins,
            function,
            main_window,
            initial_plugin_id=initial_plugin_id,
            initial_prompt=initial_prompt,
            initial_values=job_values,
        )

    _warn_missing_job_paths(main_window, missing)
    _show_imagegen_function_dialog(main_window, controller, function, dlg)


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


def imagegen_create_from_text_available() -> bool:
    """True when Create-from-text can run (plugin registered and pipeline backend installed)."""
    try:
        if not function_has_plugins(FUNCTION_CREATE):
            return False
        from imagegen_plugins.image_gen_model_selector import available_plugins

        return bool(available_plugins(plugins_for_function(FUNCTION_CREATE)))
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


def open_imagegen_create_from_text_dialog(
    main_window, *, user_comment: Optional[str] = None
) -> None:
    """Open Create > Create an image from text..., optionally primed."""
    if not function_has_plugins(FUNCTION_CREATE):
        return
    controller = get_imagegen_controller(main_window)
    _schedule_open_dialog_for_function(
        FUNCTION_CREATE,
        main_window,
        controller,
        initial_prompt=initial_prompt_from_usercomment(user_comment),
    )


def open_imagegen_edit_dialog(
    main_window, *, user_comment: Optional[str] = None
) -> None:
    """Open the AI image edit dialog (File Information pane entry)."""
    if not imagegen_edit_plugins_available():
        return
    controller = get_imagegen_controller(main_window)
    _schedule_open_dialog_for_function(
        FUNCTION_EDIT,
        main_window,
        controller,
        initial_prompt=initial_prompt_from_usercomment(user_comment),
        auto_import_available=True,
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
    auto_import_available: bool = False,
) -> None:
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
        _show_imagegen_function_dialog(
            main_window,
            controller,
            function,
            dlg,
            keep_open_on_generate=True,
        )
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
        if (
            main_window.current_view_mode == "thumbnail"
            and hasattr(main_window, "selection_manager")
            and main_window.selection_manager
            and getattr(main_window, "selected_files", None)
            and len(main_window.selection_manager.get_selected_files())
            > MAX_EDIT_SOURCE_IMAGES
        ):
            show_styled_warning(
                main_window,
                "Edit",
                f"Select at most {MAX_EDIT_SOURCE_IMAGES} images before using edit.",
            )
            return
        source_paths = active_image_paths_for_edit(main_window)
        if not source_paths:
            show_styled_warning(
                main_window,
                "Edit",
                "Select an image in browse view, or select up to "
                f"{MAX_EDIT_SOURCE_IMAGES} thumbnails, before using edit.",
            )
            return
        dlg = ImageGenEditDialog(
            plugins,
            function,
            source_paths[0],
            main_window,
            source_paths=source_paths,
            initial_prompt=initial_prompt,
            auto_import_available=auto_import_available,
        )
    else:
        dlg = ImageGenDialog(
            plugins,
            function,
            main_window,
            initial_prompt=initial_prompt,
        )

    _show_imagegen_function_dialog(main_window, controller, function, dlg)


def _schedule_open_dialog_for_function(
    function: str,
    main_window,
    controller,
    *,
    initial_prompt: Optional[str] = None,
    auto_import_available: bool = False,
) -> None:
    """Open the function dialog on the next event-loop turn (after menu handlers)."""
    QTimer.singleShot(
        0,
        lambda: _open_dialog_for_function(
            function,
            main_window,
            controller,
            initial_prompt=initial_prompt,
            auto_import_available=auto_import_available,
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
    cancel_action.triggered.connect(
        lambda: controller.confirm_cancel_generation(main_window)
    )
    create_menu.addAction(cancel_action)
    main_window.imagegen_cancel_action = cancel_action

    def _sync_cancel_action_enabled() -> None:
        try:
            cancel_action.setEnabled(controller.has_pending_work())
        except Exception:
            pass

    controller.generation_started.connect(_sync_cancel_action_enabled)
    controller.generation_finished.connect(
        lambda _ok, _path, _err: _sync_cancel_action_enabled()
    )
    controller.queue_changed.connect(_sync_cancel_action_enabled)
    controller.caption_finished.connect(_sync_cancel_action_enabled)

    QTimer.singleShot(0, lambda: _refresh_create_menu_availability(main_window))
    QTimer.singleShot(500, lambda: _refresh_create_menu_availability(main_window))
