#!/usr/bin/env python3
"""Window-level wrappers for FileDataModel writes (status bar, etc.)."""

from typing import List, Optional, TYPE_CHECKING

from model_sync import (
    set_current_directory as model_set_current_directory,
    set_current_image_path as model_set_current_image_path,
    set_displayed_images as model_set_displayed_images,
)

if TYPE_CHECKING:
    from image_browser_window import ImageBrowserWindow


def set_displayed_images_for_window(
    main_window: "ImageBrowserWindow", images: List[str], sync: bool = True
) -> None:
    if sync and getattr(main_window, "file_data_model", None):
        model_set_displayed_images(main_window.file_data_model, images, sync=True)
    else:
        main_window.displayed_images = images  # property setter when sync=True path unavailable


def set_current_image_path_for_window(
    main_window: "ImageBrowserWindow", path: Optional[str], sync: bool = True
) -> None:
    old_path = main_window.current_image_path
    path_changed = old_path != path

    if getattr(main_window, "file_data_model", None):
        model_set_current_image_path(main_window.file_data_model, path, sync=sync)
    elif not sync:
        main_window.current_image_path = path

    if (
        sync
        and path_changed
        and not getattr(main_window, "browse_view_exit_in_progress", False)
    ):
        try:
            displayed = main_window.displayed_images
            if hasattr(main_window, "update_status_bar_current_image"):
                main_window.update_status_bar_current_image(path, displayed)
                main_window._last_status_bar_image_path = path
        except Exception:
            pass


def set_current_directory_for_window(
    main_window: "ImageBrowserWindow", directory: Optional[str], sync: bool = True
) -> None:
    if getattr(main_window, "file_data_model", None):
        model_set_current_directory(main_window.file_data_model, directory, sync=sync)
    elif not sync:
        main_window.current_directory = directory
