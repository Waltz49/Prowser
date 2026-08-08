#!/usr/bin/env python3
"""Jobs pane vs floating panel display mode (mutually exclusive)."""

from __future__ import annotations

JOBS_DISPLAY_PANE = "pane"
JOBS_DISPLAY_PANEL = "panel"
_JOBS_DISPLAY_MODES = (JOBS_DISPLAY_PANE, JOBS_DISPLAY_PANEL)


def normalize_jobs_display_mode(mode: str | None) -> str:
    if mode in _JOBS_DISPLAY_MODES:
        return mode
    return JOBS_DISPLAY_PANE


def get_jobs_display_mode(main_window) -> str:
    mode = getattr(main_window, "jobs_display_mode", None)
    if mode is None and hasattr(main_window, "config"):
        mode = main_window.config.get_setting("jobs_display_mode", JOBS_DISPLAY_PANE)
    return normalize_jobs_display_mode(mode)


def _hide_job_queue_dialog(main_window) -> None:
    dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
    if dlg is not None and dlg.isVisible():
        dlg.hide()


def is_jobs_pane_showing(main_window) -> bool:
    if get_jobs_display_mode(main_window) != JOBS_DISPLAY_PANE:
        return False
    rs = getattr(main_window, "right_sidebar", None)
    return rs is not None and rs.is_jobs_visible()


def is_jobs_panel_showing(main_window) -> bool:
    dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
    return dlg is not None and dlg.isVisible()


def hide_jobs_pane(main_window) -> None:
    rs = getattr(main_window, "right_sidebar", None)
    if rs is not None and hasattr(rs, "set_jobs_visible"):
        rs.set_jobs_visible(False)
    main_window.jobs_visible = False
    if hasattr(main_window, "config"):
        main_window.config.update_setting("jobs_visible", False)
    _sync_jobs_menu_actions(main_window)


def ensure_jobs_pane_exclusive(main_window) -> None:
    """Claim sidebar pane ownership: hide floating dialog and mark mode as pane."""
    showing_panel = is_jobs_panel_showing(main_window)
    mode = get_jobs_display_mode(main_window)
    if not showing_panel and mode == JOBS_DISPLAY_PANE:
        return
    if showing_panel:
        _hide_job_queue_dialog(main_window)
    if mode != JOBS_DISPLAY_PANE:
        main_window.jobs_display_mode = JOBS_DISPLAY_PANE
        if hasattr(main_window, "config"):
            main_window.config.update_setting("jobs_display_mode", JOBS_DISPLAY_PANE)
    _refresh_flyout_buttons(main_window)
    _sync_jobs_menu_actions(main_window)


def _show_job_queue_dialog(main_window) -> None:
    from imagegen_plugins.image_gen_job_queue_dialog import open_imagegen_job_queue_dialog

    open_imagegen_job_queue_dialog(main_window)


def set_jobs_display_mode(main_window, mode: str, *, persist: bool = True) -> str:
    """Show jobs in sidebar pane or floating panel (never both)."""
    mode = normalize_jobs_display_mode(mode)
    prev = get_jobs_display_mode(main_window)
    main_window.jobs_display_mode = mode
    if persist and hasattr(main_window, "config"):
        main_window.config.update_setting("jobs_display_mode", mode)

    rs = getattr(main_window, "right_sidebar", None)
    chrome_suppressed = getattr(main_window, "_chrome_suppressed", False)
    if mode == JOBS_DISPLAY_PANE:
        _hide_job_queue_dialog(main_window)
        if rs is not None and hasattr(rs, "set_jobs_visible"):
            rs.set_jobs_visible(True)
        main_window.jobs_visible = True
    else:
        if rs is not None and hasattr(rs, "set_jobs_visible"):
            rs.set_jobs_visible(False)
        main_window.jobs_visible = False
        _show_job_queue_dialog(main_window)
        if chrome_suppressed:
            # F4 hide: floating panel only — do not resurrect sidebars via pane state.
            cs = getattr(main_window, "combined_sidebar", None)
            if cs is not None:
                cs.hide()
            if rs is not None:
                rs.hide()
                if hasattr(rs, "hide_info"):
                    rs.hide_info()
            splitter = getattr(main_window, "main_splitter", None)
            total_width = splitter.width() if splitter is not None else 0
            if total_width and hasattr(main_window, "_set_splitter_sizes_safe"):
                main_window._set_splitter_sizes_safe([0, total_width, 0])

    if prev != mode or persist:
        _refresh_flyout_buttons(main_window)
        _sync_jobs_menu_actions(main_window)
    return mode


def toggle_jobs_display_mode(main_window) -> str:
    current = get_jobs_display_mode(main_window)
    next_mode = (
        JOBS_DISPLAY_PANEL if current == JOBS_DISPLAY_PANE else JOBS_DISPLAY_PANE
    )
    return set_jobs_display_mode(main_window, next_mode)


def show_jobs_pane(main_window) -> str:
    return set_jobs_display_mode(main_window, JOBS_DISPLAY_PANE)


def show_jobs_panel(main_window) -> str:
    return set_jobs_display_mode(main_window, JOBS_DISPLAY_PANEL)


def toggle_jobs_pane(main_window) -> str:
    """J: hide jobs pane when visible; otherwise show sidebar pane mode."""
    if is_jobs_pane_showing(main_window):
        hide_jobs_pane(main_window)
        return JOBS_DISPLAY_PANE
    return show_jobs_pane(main_window)


def toggle_jobs_panel(main_window) -> str:
    """Cmd+J: hide floating job dialog when visible; otherwise show panel mode."""
    if is_jobs_panel_showing(main_window):
        _hide_job_queue_dialog(main_window)
        return get_jobs_display_mode(main_window)
    return show_jobs_panel(main_window)


def cycle_active_jobs_surface_size(main_window) -> bool:
    """⌃J: size-cycle the active jobs surface (floating dialog or sidebar pane)."""
    if is_jobs_panel_showing(main_window):
        dlg = getattr(main_window, "_imagegen_job_queue_dialog", None)
        if dlg is not None and hasattr(dlg, "cycle_header_size"):
            dlg.cycle_header_size()
            return True
        return False
    rs = getattr(main_window, "right_sidebar", None)
    if rs is None or not getattr(rs, "_jobs_feature_enabled", False):
        return False
    if hasattr(rs, "_expand_jobs_pane_to_fit"):
        rs._expand_jobs_pane_to_fit()
        return True
    return False


def apply_saved_jobs_display_mode(main_window) -> None:
    """Apply persisted mode after UI is constructed."""
    mode = get_jobs_display_mode(main_window)
    set_jobs_display_mode(main_window, mode, persist=False)


def _refresh_flyout_buttons(main_window) -> None:
    from imagegen_plugins.job_queue_panel import refresh_jobs_flyout_buttons

    refresh_jobs_flyout_buttons(main_window)


def sync_jobs_menu_actions(main_window) -> None:
    _sync_jobs_menu_actions(main_window)


def _sync_jobs_menu_actions(main_window) -> None:
    pane_showing = is_jobs_pane_showing(main_window)
    if hasattr(main_window, "toggle_jobs_action"):
        main_window.toggle_jobs_action.setChecked(pane_showing)
        main_window.toggle_jobs_action.setText(
            "Hide Jobs Pane" if pane_showing else "Show Jobs Pane"
        )
