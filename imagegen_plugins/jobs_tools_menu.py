#!/usr/bin/env python3
"""Job Control pane header tools and context menu."""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QMenu, QPushButton

from theme.theme_service import get_active_theme

_MENU_ACTION_ORDER = ("intermediate_images", "hold_queue", "skip_copy")


def _populate_jobs_menu(
    menu: QMenu,
    panel,
    *,
    job_queue_dialog=None,
) -> None:
    specs = {spec["action_id"]: spec for spec in panel.jobs_toolbar_action_specs()}
    toolbar = getattr(panel, "_toolbar", None)
    for action_id in _MENU_ACTION_ORDER:
        spec = specs.get(action_id)
        if spec is None or not spec["visible"]:
            continue
        icon = toolbar.action_icon(action_id) if toolbar is not None else None
        if icon is not None and not icon.isNull():
            action = menu.addAction(icon, str(spec["label"]))
        else:
            action = menu.addAction(str(spec["label"]))
        action.setEnabled(bool(spec["enabled"]))
        if spec.get("tooltip"):
            action.setToolTip(str(spec["tooltip"]))
        if spec.get("checkable"):
            action.setCheckable(True)
            action.setChecked(bool(spec.get("checked")))
            action.toggled.connect(
                lambda checked, aid=action_id: panel.trigger_jobs_toolbar_action(
                    aid, checked
                )
            )
        else:
            action.triggered.connect(
                lambda _checked=False, aid=action_id: panel.trigger_jobs_toolbar_action(
                    aid
                )
            )

    if job_queue_dialog is not None and hasattr(
        job_queue_dialog, "is_job_queue_always_on_top"
    ):
        menu.addSeparator()
        top_action = menu.addAction("Always on Top")
        top_action.setCheckable(True)
        top_action.setChecked(job_queue_dialog.is_job_queue_always_on_top())
        top_action.toggled.connect(
            lambda checked: job_queue_dialog.set_job_queue_always_on_top(bool(checked))
        )

    menu.addSeparator()
    show_bar = menu.addAction("Show Toolbar")
    show_bar.setCheckable(True)
    show_bar.setChecked(panel.is_jobs_toolbar_visible())
    show_bar.toggled.connect(panel.set_jobs_toolbar_visible)


def show_jobs_tools_menu(
    panel,
    anchor: QPushButton,
    *,
    job_queue_dialog=None,
) -> None:
    # Parentless menu avoids macOS popup warnings on embedded sidebar widgets.
    menu = QMenu()
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    _populate_jobs_menu(menu, panel, job_queue_dialog=job_queue_dialog)
    menu.exec(anchor.mapToGlobal(QPoint(0, anchor.height())))


def show_jobs_context_menu(
    panel,
    global_pos,
    *,
    job_queue_dialog=None,
) -> None:
    # Parentless menu avoids macOS popup warnings on embedded sidebar widgets.
    menu = QMenu()
    t = get_active_theme()
    menu.setStyleSheet(t.status_bar_context_menu_stylesheet())
    _populate_jobs_menu(menu, panel, job_queue_dialog=job_queue_dialog)
    menu.exec(global_pos)
