#!/usr/bin/env python3
"""
Why Was This Written Dialog
Displays markdown-formatted text explaining the motivation behind the image browser
"""

from markdown_dialog import MarkdownDialog


class WhyWasThisWrittenDialog(MarkdownDialog):
    """Dialog showing markdown-formatted text explaining why this application was written"""

    def __init__(self, parent=None):
        markdown_content = self._get_markdown_content()
        super().__init__("Notes and Trivia", markdown_content, parent)

    def _get_markdown_content(self):
        """Get the markdown content for this dialog"""
        return """### 
# Quick Start: Major Keys

| Key | Description |
|-----|-------------|
| --- | **Navigation and Selection** |  
| **Arrow Keys** (↑ ↓ ← →) | Move the highlight cursor around the thumbnails to change the current selection. In some modes, used for navigation or scrolling. |
| **Enter** | Switch between thumbnail and browse mode. Note that **shift-spacebar** will toggle behavior to allow you to use **spacebar** to advance to the next image in browse mode. |
| --- |**Appearance** |  
| **T** | Toggle the visibility of the folder tree sidebar on and off. |
| **P** | Toggle the preview pane, letting you quickly see a larger version of the highlighted image. |
| **J** | Toggle the Jobs pane on the right sidebar (or open the imagegen task menu when a model job is running). Works in browse and thumbnail views. |
| **I** | Show or hide the Information sidebar, revealing EXIF, filename, and other details about the image. |
| **B** | Toggle status bar visibility. |
| --- |**Search Functions** |  
| **Cmd+K** | Find images that are similar to the currently selected image(s). |
| **Cmd+F** | Search by describing something in the image. |
| **Ctrl+P** | Search by face recognition. |
| --- |**Other keys** |  
| **F1** or **/** | Open the "Help" dialog with context-aware keyboard shortcuts. |

#

# Useful Tips

- Search functions rely on open source models that will be downloaded **once** from HuggingFace the first time they are used. This, and the initial "feature extraction" from images, can be slow. The models can be large and are downloaded to the `~/.cache/huggingface` directory.
- Some sections of the status bar are clickable, allowing for fast changes to various settings.
- Some tree actions require double **Enter** or double-click. This is by design.
- The keyboard help is dynamically generated at runtime to help with development, and it may contain some keys that are not used in the current mode.
- There are key combinations that are not exposed in the menu system, so it can be helpful to peruse the context-sensitive help shown by pressing **F1** or the slash key (**/**).
- ⚠️ There may still be some problems with refreshing the thumbnails. If thumbnails don't have an image, use refresh (**Cmd-R**), an arrow key (↑ ↓ ← →), or reload the directory by clicking in the tree view.
- ⚠️ Occasionally, you may see beachballs related to background thumbnail loading, but **wait them out**. They usually complete eventually. Rarely, the application may need to be force-quit.

#
---

# Workflow for Organizing Files in a Directory with Locking *(experimental)*

When locking is enabled in the Settings dialog, you can lock files to keep them in a specific order. Locked files are always grouped together at the top of the display, according to their locked sequence. This lets you arrange thumbnails using drag and drop, and ensures their order is preserved. The general workflow is: group the files you want together (using search functions and drag-and-drop), lock your changes, and repeat as needed, then rename the files to permanenty preserve their order.

- Enable locking by checking the "Allow Thumbnail Locking" checkbox in the Settings dialog.
- In thumbnail view, lock the files that are ordered the way you want them by selecting them and pressing **Cmd-L**. To unlock files, select them and press **Shift-Cmd-L**. You can lock or unlock multiple files at once using multiselect.
- Use search functions (**Cmd-K** or **Cmd-F**) and drag and drop to arrange the thumbnails in your preferred order. 
- If you want to rename the files, use Quick rename (**Shift-Cmd-M**) or Custom rename (**Cmd-N**) to rename files in their current order.
- Repeat the above steps as needed.

Locked files always show at the top, regardless of the sort (**N**, **D**, **R**, etc.). For clarity, use "custom" sort (**C**) and "Rename with custom prefix" (**Cmd-N**), which uses "Top becomes 1" and sets the top file as newest. This is fully automated by the quick rename (**Shift-Cmd-M**).

Note 2: Use Tools>Backup Custom Sort to save your custom sort order, and Tools>Restore Custom Sort to restore it. This will preserve the order even if you rename or re-date the files.

> ⚠️ **Warning:** Lock functions are not yet fully compatible with limits or multi-directory thumbnail views, such as results from recursive searches.


#
---

# Developer's notes

#

## Why Was This Written?

I could give you some nonsense like how this image browser was created to fill a gap in the macOS ecosystem, or some mid-level management bullshit about how this would synergistically align with your strategic plan to execute on your vision.

But really, I just like to write code.  
So here it is.

#

## Purpose

I wanted something that:

- Is designed for organizing images but also works as a general purpose image browser.
- Works the way I do, and fits my workflow, is keyboard controlled, and which allows me to sort images as I want and rename them accordingly.
- Helps me organize my images with compare and search functions.
- Helps me find images by description or similarity.
- Brings together the few features that I actually used in the other image viewers, such as Xee³, FastStone on Windows, PicArrange and others.

#

## Key Features

The application includes features that were important to me.

- Thumbnail view with drag-and-drop support for flexible ordering and support for images from multiple directories.
- Rapid fullscreen browsing with zoom, pan, transparency, rotation, and more.
- Advanced search: by description or similarity.
- Full keyboard control and helpful UI elements like a clickable status bar.
- Ability to focus on image subsets using multiselect and **Return**.
- Navigation via tree, history, and favorites.
- Deletion (with undo), rename, format conversion, and rapid moves to user-defined locations.
- Integration with external editors.
- Straightforward API for launching from other programs (via pipe).
- Various filters for images and directories, plus extras like slideshows and wallpaper changes with undo.

#

## Coding Philosophy

This is mostly AI generated code, based on a project I originally wrote by hand in another language. 

#

## Contributing

If you find a bug or have a feature request, please report it.  

#

## Known issues

1. Still occasionally need to refresh or reload the directory from the tree to see the latest changes.
3. `Esc` out of a thumbnail rename may blank out the name. Any `Arrow key` fixes that.
4. Creating Multiple selections uses more or less standard keyboard and mouse behavior, but anchor management needs to be improved.
"""


def main():
    """Test function to run the dialog independently"""
    import sys
    from PySide6.QtWidgets import QApplication

    # Create QApplication instance
    app = QApplication(sys.argv)

    # Create and show the dialog
    dialog = WhyWasThisWrittenDialog()
    dialog.show()

    # Run the application event loop
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
