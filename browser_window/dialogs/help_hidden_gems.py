#!/usr/bin/env python3
"""
Hidden Gems Help Dialog — modifier + click (and related modifier + drag) actions.

MAINTAINER: When you add or change behavior that uses Option, Control, Command, or
Shift together with a mouse click or drag, update ``_get_markdown_content()`` below
and keep the in-app tooltips in sync where they exist.
"""

from markdown_dialog import MarkdownDialog
from thumbnails.thumbnail_constants import (
    CMD_SYMBOL,
    CTRL_SYMBOL,
    OPTION_SYMBOL,
    SHIFT_SYMBOL,
)


class HiddenGemsHelpDialog(MarkdownDialog):
    """Dialog listing modifier + click hidden actions across Prowser."""

    def __init__(self, parent=None):
        markdown_content = self._get_markdown_content()
        super().__init__("Hidden Gems", markdown_content, parent)

    def _get_markdown_content(self) -> str:
        # MAINTAINER: Add new modifier+click / modifier+drag rows here when implementing them.
        opt = OPTION_SYMBOL
        cmd = CMD_SYMBOL
        ctrl = CTRL_SYMBOL
        shift = SHIFT_SYMBOL
        return f"""#
# Hidden Gems: Modifier + Click

Many useful actions are not in the menus. Some are hinted in tooltips only; this page collects them.

This page is really just a development aid to guide future design and possibly document some design shortcomings.

#

## macOS key names

Qt reports keyboard modifiers differently from menu shortcuts:

| Label | Key | Qt note |
|-------|-----|---------|
| **{cmd}** Command | ⌘ | `ControlModifier` in Qt |
| **{ctrl}** Control | ⌃ | `MetaModifier` in Qt |
| **{opt}** Option | ⌥ | `AltModifier` in Qt |
| **{shift}** Shift | ⇧ | `ShiftModifier` in Qt |

Throughout Prowser, **{cmd}+click** means Command, **{ctrl}+click** means Control (not Command).

#

## Thumbnails and list view

| Modifier + click | Where | Action |
|------------------|-------|--------|
| **{cmd}+click** | Thumbnail grid or list | Add or toggle the clicked image in the selection (multiselect). |
| **{shift}+click** | Thumbnail grid or list | Extend selection from the anchor to the clicked image (range select). |
| **{ctrl}+click** or **right-click** | Thumbnail grid or list | Open the thumbnail context menu. **{cmd}+click** does *not* open the menu — it is reserved for multiselect. |
| plain click | Thumbnail grid or list | Select and open browse mode (when preview is hidden). |

#

## Drag and drop (modifier held while dragging)

| Modifier | Where | Action |
|----------|-------|--------|
| **{opt}** (hold while dragging) | Thumbnail grid | Force **copy** when dragging files to another folder or app. Default is move (macOS still copies across volumes). |
| **{opt}** (hold while dragging) | Browse mode | Force **copy** when dragging the current image out of the viewer. |
| **{cmd}** (hold while dragging) | Browse mode | When the image is zoomed enough to pan, prefer **file drag** over panning. |
| **{opt}** (at drop) | Folder tree drop | Copy **locked** files instead of moving them (move is blocked for locked files). |

#

## Information sidebar (EXIF / description links)

These links appear in the information pane when a user comment is present.

| Modifier + click | Link | Action |
|------------------|------|--------|
| click | **References** level link | Show the full reference graph (complete history). |
| **{opt}+click** | **References** level link | Show only this image and its **direct** references. |
| click | **Copy** link | Copy the prompt text (truncated before generation metadata). |
| **{opt}+click** | **Copy** link | Copy the **full** raw user comment. |

#

## Edit EXIF user comment dialog

| Modifier + click | Control | Action |
|------------------|---------|--------|
| click | Copy button | Copy processed comment text (prompt portion, semicolons normalized). |
| **{opt}+click** or **{ctrl}+click** | Copy button | Copy **raw** text from the editor without processing. |

#

## Settings dialog

| Modifier | Control | Action |
|----------|---------|--------|
| Hold **{opt}**, then click | **Reset to Defaults** button (label changes) | **Save as Defaults** — save the current tab as your personal defaults. |
| Hold **{opt}{shift}**, then click | **Reset to Defaults** button (label changes) | **System Defaults** — reset the current tab to built-in factory defaults. |
| click (no modifier) | **Reset to Defaults** button | Reset the current tab to your saved defaults. |
| **{opt}+click** | Any **Theme** section header (▶ / ▼) | Expand or collapse **all** theme groups at once. |

#

## Image generation

| Modifier + click | Where | Action |
|------------------|-------|--------|
| **{opt}+click** | Job queue — **Cancel** (trash) | Cancel this job **and all later jobs** with no confirmation. |
| **{opt}+click** | Job queue — series **minus** (-) | Remove **all** remaining images in the series (not just one). |

Related (modifier + drag, not click):

| Modifier | Where | Action |
|----------|-------|--------|
| **{opt}** (hold while painting) | Infill paint canvas | **Erase** mask instead of painting. |
| **{opt}** (hold while resizing placement) | Expand placement canvas | Resize with **free aspect ratio** (corner drag). |

#

## Not finding something?

Press **F1** or **/** for the full keyboard-shortcut list. This page only covers **mouse** actions with modifier keys.
"""


def main():
    """Test function to run the dialog independently."""
    import sys

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = HiddenGemsHelpDialog()
    dialog.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
