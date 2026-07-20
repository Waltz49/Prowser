#!/usr/bin/env python3
"""Backward-compatible alias for BrowserController."""

from browser_window.infra.browser_controller import BrowserController

MVCController = BrowserController

__all__ = ["MVCController", "BrowserController"]
