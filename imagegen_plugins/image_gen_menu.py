#!/usr/bin/env python3
"""Image menu (local AI image generation; shown even when no models are registered)."""

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
    effective_last_function,
    remember_last_function,
    set_active_plugin_for_function,
)
from imagegen_plugins.image_gen_controller import get_imagegen_controller
from imagegen_plugins.image_gen_job_queue_dialog import show_imagegen_job_queue_dialog
from imagegen_plugins.image_gen_edit_dialog import (
    MAX_EDIT_SOURCE_IMAGES,
    active_image_paths_for_edit,
)
from imagegen_plugins.image_gen_expand_dialog import active_image_path_for_expand
from imagegen_plugins.image_gen_infill_paint_dialog import active_image_path_for_infill
from imagegen_plugins.image_gen_naming import resolve_source_image_paths
from imagegen_plugins.image_gen_session_state import FunctionSessionState
from imagegen_plugins.image_gen_unified_dialog import ImageGenUnifiedDialog
from imagegen_plugins.image_gen_install_hint import imagegen_backend_missing_message
from imagegen_plugins.image_gen_persistence import (
    load_imagegen_dialog_geometry_hex,
    save_imagegen_dialog_geometry_hex,
)
from imagegen_plugins.image_gen_model_availability import confirm_model_download_if_needed
from imagegen_plugins.image_gen_model_selector import available_plugins
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.pixelmator_export import is_pixelmator_pro_installed
from menu_manager import TextSeparator
from utils import (
    restore_dialog_geometry_hex,
    save_dialog_geometry_hex,
    show_styled_information,
    show_styled_warning,
)

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
    from utils import present_auxiliary_dialog

    present_auxiliary_dialog(dlg)


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


def start_imagegen_without_closing(
    dialog,
    function: str,
    plugin: ImageGenModelPlugin,
    values: Dict[str, Any],
) -> bool:
    """Start generation from a persistent panel without closing it."""
    from imagegen_plugins.image_gen_source_nav import resolve_image_gen_main_window

    main_window = resolve_image_gen_main_window(dialog)
    if main_window is None:
        return False
    controller = get_imagegen_controller(main_window)
    if not confirm_model_download_if_needed(plugin, main_window):
        return False
    set_active_plugin_for_function(main_window, function, plugin)
    return bool(controller.start_generation(plugin, values))


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
    if getattr(dlg, "_image_gen_persistent_panel", False):
        return
    _start_generation_from_function_dialog(main_window, controller, function, dlg)


def _show_imagegen_function_dialog(
    main_window,
    controller,
    function: str,
    dlg: QDialog,
) -> None:
    """Show the unified image-generation dialog (non-modal)."""
    existing = getattr(main_window, "_imagegen_function_dialog", None)
    if existing is not None and existing is not dlg and existing.isVisible():
        existing.close()

    main_window._imagegen_function_dialog = dlg
    main_window._imagegen_dialog_open = True
    if not getattr(dlg, "_imagegen_finished_connected", False):
        dlg.finished.connect(
            lambda result, d=dlg: _on_imagegen_function_dialog_finished(
                main_window, controller, function, d, result
            )
        )
        dlg._imagegen_finished_connected = True
    _raise_imagegen_function_dialog(dlg)


def _job_session_state(
    function: str,
    job_values: Dict[str, Any],
    plugin_id: str,
) -> FunctionSessionState:
    placement = None
    keys = ("placement_x", "placement_y", "placement_w", "placement_h")
    if all(k in job_values for k in keys):
        try:
            placement = (
                int(job_values["placement_x"]),
                int(job_values["placement_y"]),
                int(job_values["placement_w"]),
                int(job_values["placement_h"]),
            )
        except (TypeError, ValueError):
            placement = None

    mask_png_bytes = None
    mask_path = str(job_values.get("pixelmator_mask_path") or "")
    if mask_path and os.path.isfile(mask_path):
        try:
            with open(mask_path, "rb") as fh:
                mask_png_bytes = fh.read()
        except OSError:
            mask_png_bytes = None

    source_paths = None
    source_path = None
    if function == FUNCTION_EDIT:
        paths = [
            p for p in resolve_source_image_paths(job_values) if p and os.path.isfile(p)
        ]
        source_paths = paths or None
        source_path = paths[0] if paths else None
    elif function in (FUNCTION_EXPAND, FUNCTION_INFILL_PAINT):
        source_path = str(
            job_values.get("source_image_path")
            or job_values.get("pixelmator_doc_path")
            or ""
        ).strip() or None

    return FunctionSessionState(
        values=dict(job_values),
        plugin_id=plugin_id,
        source_path=source_path,
        source_paths=source_paths,
        placement=placement,
        mask_png_bytes=mask_png_bytes,
    )


def _open_or_switch_unified_dialog(
    main_window,
    controller,
    function: str,
    *,
    initial_prompt: Optional[str] = None,
    auto_import_available: bool = False,
    geometry_hex: Optional[str] = None,
    seed_state: Optional[FunctionSessionState] = None,
) -> None:
    existing = getattr(main_window, "_imagegen_function_dialog", None)
    if isinstance(existing, ImageGenUnifiedDialog) and existing.isVisible():
        if not existing.switch_to_function(
            function,
            initial_prompt=initial_prompt,
            auto_import_available=auto_import_available,
            seed_state=seed_state,
        ):
            return
        _raise_imagegen_function_dialog(existing)
        return

    dlg = ImageGenUnifiedDialog(main_window, controller, main_window)
    apply_preserved_imagegen_dialog_geometry(dlg, geometry_hex)
    if not dlg.switch_to_function(
        function,
        initial_prompt=initial_prompt,
        auto_import_available=auto_import_available,
        seed_state=seed_state,
    ):
        dlg.deleteLater()
        return
    _show_imagegen_function_dialog(main_window, controller, function, dlg)


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
    elif function == FUNCTION_INFILL:
        if _is_paint_infill_job_values(job_values):
            function = FUNCTION_INFILL_PAINT
            mask_path = str(job_values.get("pixelmator_mask_path") or "")
            if mask_path and not os.path.isfile(mask_path):
                missing.append(mask_path)
        else:
            base_path = str(job_values.get("pixelmator_base_path") or "")
            mask_path = str(job_values.get("pixelmator_mask_path") or "")
            for path in (base_path, mask_path):
                if path and not os.path.isfile(path):
                    missing.append(path)

    _warn_missing_job_paths(main_window, missing)
    seed_state = _job_session_state(function, job_values, initial_plugin_id)
    _open_or_switch_unified_dialog(
        main_window,
        controller,
        function,
        initial_prompt=initial_prompt,
        seed_state=seed_state,
    )


def _menu_function_actions():
    """Create-menu function items, omitting Pixelmator infill when the app is missing."""
    for function, label in _CREATE_FUNCTION_ACTIONS:
        if function == FUNCTION_INFILL and not is_pixelmator_pro_installed():
            continue
        yield function, label


def _resolved_last_function(main_window) -> str:
    actions = getattr(main_window, "imagegen_function_actions", None) or {}
    last_fn = effective_last_function(main_window)
    if last_fn not in actions and actions:
        last_fn = next(iter(actions))
    return last_fn


def remember_imagegen_last_function(main_window, function: str) -> None:
    """Update ⌥/ target after switching mode in the combined dialog."""
    remember_last_function(main_window, function)
    _sync_function_menu_shortcuts(main_window)


def _primary_imagegen_menu_label(last_fn: str) -> str:
    label = _FUNCTION_LABELS.get(last_fn, _FUNCTION_LABELS[FUNCTION_EDIT])
    return f"Create or Modify — {label}\t⌥/"


def apply_preserved_imagegen_dialog_geometry(dialog, geometry_hex: Optional[str]) -> None:
    """Apply saved geometry before first show (e.g. when switching dialog type in place)."""
    if not geometry_hex:
        return
    dialog._geometry_restore_attempted = True
    try:
        dialog._geometry_was_restored = restore_dialog_geometry_hex(
            dialog, geometry_hex, dialog.parent()
        )
    except Exception:
        dialog._geometry_was_restored = False


def _sync_function_menu_shortcuts(main_window) -> None:
    """Bind ⌥/ to the primary action and show the last-used type in its label."""
    actions = getattr(main_window, "imagegen_function_actions", None) or {}
    last_fn = _resolved_last_function(main_window)
    primary = getattr(main_window, "imagegen_primary_action", None)
    if primary is not None:
        primary.setText(_primary_imagegen_menu_label(last_fn))
    for function, action in actions.items():
        action.setText(_FUNCTION_LABELS[function])
        action.setShortcut(QKeySequence())


def imagegen_plugins_available() -> bool:
    """True when at least one image-generation plugin is registered."""
    try:
        from bundle_capabilities import imagegen_ui_enabled

        if not imagegen_ui_enabled():
            return False
        return bool(discover_plugins())
    except Exception:
        return False


def imagegen_edit_plugins_available() -> bool:
    """True when at least one edit-function plugin is registered."""
    try:
        from bundle_capabilities import imagegen_ui_enabled

        if not imagegen_ui_enabled():
            return False
        return function_has_plugins(FUNCTION_EDIT)
    except Exception:
        return False


def imagegen_create_from_text_available() -> bool:
    """True when Create-from-text can run (plugin registered and pipeline backend installed)."""
    try:
        from bundle_capabilities import imagegen_ui_enabled

        if not imagegen_ui_enabled():
            return False
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
    from exif.exif_utils import truncate_usercomment_before_prompt

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


def switch_imagegen_function_dialog_in_place(
    dialog,
    target_function: str,
    main_window,
) -> None:
    """Switch function inside the unified dialog without closing the window."""
    if not isinstance(dialog, ImageGenUnifiedDialog):
        return
    try:
        geometry_hex = save_dialog_geometry_hex(dialog)
        save_imagegen_dialog_geometry_hex(geometry_hex)
    except Exception:
        pass
    dialog.switch_to_function(target_function)


def _open_dialog_for_function(
    function: str,
    main_window,
    controller,
    *,
    initial_prompt: Optional[str] = None,
    auto_import_available: bool = False,
    geometry_hex: Optional[str] = None,
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

    if function == FUNCTION_INFILL_PAINT and not active_image_path_for_infill(main_window):
        show_styled_warning(
            main_window,
            "Infill",
            "Select an image in browse view, or select a single thumbnail, "
            "before using infill by painting.",
        )
        return
    if function == FUNCTION_EXPAND and not active_image_path_for_expand(main_window):
        show_styled_warning(
            main_window,
            "Expand",
            "Select an image in browse view, or select a single thumbnail, "
            "before using expand.",
        )
        return
    if function == FUNCTION_EDIT:
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
        if not active_image_paths_for_edit(main_window):
            show_styled_warning(
                main_window,
                "Edit",
                "Select an image in browse view, or select up to "
                f"{MAX_EDIT_SOURCE_IMAGES} thumbnails, before using edit.",
            )
            return

    _open_or_switch_unified_dialog(
        main_window,
        controller,
        function,
        initial_prompt=initial_prompt,
        auto_import_available=auto_import_available,
        geometry_hex=geometry_hex,
    )


def _schedule_open_dialog_for_function(
    function: str,
    main_window,
    controller,
    *,
    initial_prompt: Optional[str] = None,
    auto_import_available: bool = False,
    geometry_hex: Optional[str] = None,
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
            geometry_hex=geometry_hex,
        ),
    )


def _refresh_create_menu_availability(main_window) -> None:
    """Re-check backend installs and enable Image menu function items."""
    actions = getattr(main_window, "imagegen_function_actions", None) or {}
    if not actions:
        return
    any_usable = False
    for function, action in actions.items():
        plugins = plugins_for_function(function)
        usable = available_plugins(plugins)
        action.setEnabled(bool(plugins))
        if usable:
            any_usable = True
        if not plugins:
            action.setToolTip("No models are registered for this action.")
        elif not usable:
            action.setToolTip(
                "Install optional dependencies (see Help or minimal_requirements.txt)"
            )
        else:
            action.setToolTip("")
    primary = getattr(main_window, "imagegen_primary_action", None)
    if primary is not None:
        primary.setEnabled(any_usable)


def start_active_imagegen_generation(
    main_window, *, initial_prompt: Optional[str] = None
) -> None:
    """Run the dialog for the last-used Image menu function (⌥/)."""
    if not create_menu_plugins():
        return
    actions = getattr(main_window, "imagegen_function_actions", None) or {}
    function = effective_last_function(main_window)
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


def _open_download_models_dialog(main_window) -> None:
    from imagegen_plugins.debug_download_models_dialog import run_download_models_dialog

    run_download_models_dialog(main_window)


def _open_download_loras_dialog(main_window) -> None:
    from imagegen_plugins.debug_download_script_dialog import (
        run_flux_lora_download_script_dialog,
    )

    run_flux_lora_download_script_dialog(main_window)


def setup_create_menu(menubar, main_window) -> None:
    try:
        from bundle_capabilities import imagegen_ui_enabled

        if not imagegen_ui_enabled():
            return
    except ImportError:
        pass

    all_plugins = discover_plugins()

    create_menu = menubar.addMenu("Image")
    main_window.imagegen_create_menu = create_menu
    controller = get_imagegen_controller(main_window)
    main_window.imagegen_function_actions = {}

    experimental_note = QWidgetAction(main_window)
    experimental_note.setDefaultWidget(
        TextSeparator("Image generation is rudimentary")
    )
    create_menu.addAction(experimental_note)

    main_window._imagegen_last_function = effective_last_function(main_window)
    primary_action = QAction(
        _primary_imagegen_menu_label(_resolved_last_function(main_window)),
        main_window,
    )
    primary_action.setShortcut(_ALT_SLASH)
    primary_action.triggered.connect(
        lambda: start_active_imagegen_generation(main_window)
    )
    create_menu.addAction(primary_action)
    main_window.imagegen_primary_action = primary_action
    create_menu.addSeparator()

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
    create_menu.aboutToShow.connect(
        lambda: _sync_function_menu_shortcuts(main_window)
    )

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

    create_menu.addSeparator()
    download_models_action = QAction("Manage models...", main_window)
    download_models_action.triggered.connect(
        lambda: _open_download_models_dialog(main_window)
    )
    create_menu.addAction(download_models_action)

    download_loras_action = QAction("Download LoRAs...", main_window)
    download_loras_action.triggered.connect(
        lambda: _open_download_loras_dialog(main_window)
    )
    create_menu.addAction(download_loras_action)

    QTimer.singleShot(0, lambda: _refresh_create_menu_availability(main_window))
    QTimer.singleShot(500, lambda: _refresh_create_menu_availability(main_window))
