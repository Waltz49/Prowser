#!/usr/bin/env python3
"""
FileDataModel write helpers (replaces ConfigurationSyncManager _set_*_with_sync).

Navigation contract: prefer set_current_image_path when the path is known (e.g. thumbnail
click, tree selection). Use set_current_index only when the index in displayed_images is
authoritative. Never use canvas/visual slot index as displayed_images index.
"""

from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from file_data_model import FileDataModel


def set_displayed_images(model: "FileDataModel", images: List[str], sync: bool = True) -> None:
    if sync:
        model.set_displayed_images(images, notify=True)
    else:
        model._displayed_images = list(images)


def set_current_image_path(model: "FileDataModel", path: Optional[str], sync: bool = True) -> None:
    if sync:
        model.set_current_image_path(path, notify=True)
    else:
        model._current_image_path = path


def set_current_directory(model: "FileDataModel", directory: Optional[str], sync: bool = True) -> None:
    if sync:
        model.set_current_directory(directory, notify=True)
    else:
        model._current_directory = directory
