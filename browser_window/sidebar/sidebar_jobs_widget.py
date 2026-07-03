#!/usr/bin/env python3
"""Job queue list for the right combined sidebar Jobs pane (matches dialog data)."""

from __future__ import annotations

from imagegen_plugins.job_queue_panel import JobQueuePanelWidget


def _jobs_header(main_window):
    right_sidebar = getattr(main_window, "right_sidebar", None)
    if right_sidebar is None:
        return None
    return getattr(right_sidebar, "jobs_header", None)


class SidebarJobsWidget(JobQueuePanelWidget):
    """Scrollable job queue for the right combined sidebar (dialog-equivalent data)."""

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)
        self.set_header_getter(lambda: _jobs_header(main_window))
        self.set_on_compact_geometry_changed(self._sync_sidebar_compact_geometry)

    def attach_titlebar_tools(self) -> None:
        """Wire the Job Control titlebar tools menu (after right sidebar exists)."""
        self.attach_header_tools()

    def _sync_sidebar_compact_geometry(self) -> None:
        if not self.is_queue_compact():
            return
        sidebar = getattr(self.main_window, "right_sidebar", None)
        if sidebar is not None and getattr(sidebar, "_jobs_pane_compact", False):
            sidebar._sync_jobs_compact_geometry()
