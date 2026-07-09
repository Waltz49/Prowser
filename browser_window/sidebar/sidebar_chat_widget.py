#!/usr/bin/env python3
"""Chat pane wrapper for the right combined sidebar."""

from __future__ import annotations

from chat_plugins.chat_pane_widget import ChatPaneWidget, MIN_CHAT_PANE_WIDTH


def _chat_header(main_window):
    combined_sidebar = getattr(main_window, "combined_sidebar", None)
    if combined_sidebar is None:
        return None
    return getattr(combined_sidebar, "chat_header", None)


class SidebarChatWidget(ChatPaneWidget):
    """LM Studio chat for the left combined sidebar."""

    def __init__(self, main_window, parent=None):
        super().__init__(main_window, parent)
        self.set_header_getter(lambda: _chat_header(main_window))

    def attach_titlebar_tools(self) -> None:
        super().attach_titlebar_tools()
