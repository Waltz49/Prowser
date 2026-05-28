#!/usr/bin/env python3
"""
Non-Qt thumbnail disk cache for the background worker.
Matches ImageCacheManager disk paths and cache keys (thumbnail_cache_key module).
"""

import os
from typing import Optional, Set, TYPE_CHECKING

from config import get_config
from thumbnail_cache_key import (
    compute_thumbnail_cache_key,
    is_path_in_app_cache_directory,
)

if TYPE_CHECKING:
    from PIL import Image as PILImage


class BackgroundThumbnailCache:
    """Disk-backed thumbnail access without Qt."""

    def __init__(self) -> None:
        config = get_config()
        self._app_cache_dir = str(config.cache_dir)
        self.thumbnail_cache_dir = str(config.thumbnail_cache_dir)
        os.makedirs(self.thumbnail_cache_dir, exist_ok=True)
        self._stat_cache: dict = {}
        self._stat_cache_max_age = 60.0

    def _ignore_exif_rotation(self) -> bool:
        try:
            return bool(get_config().load_settings().get("ignore_exif_rotation", False))
        except Exception:
            return False

    def get_cache_key(self, image_path: str, extra: str = "") -> str:
        return compute_thumbnail_cache_key(
            image_path,
            app_cache_dir=self._app_cache_dir,
            ignore_exif_rotation=self._ignore_exif_rotation(),
            stat_cache=self._stat_cache,
            stat_cache_max_age=self._stat_cache_max_age,
            extra=extra,
        )

    def is_in_app_cache_directory(self, image_path: str) -> bool:
        return is_path_in_app_cache_directory(image_path, self._app_cache_dir)

    def get_thumbnail_sync(
        self,
        image_path: str,
        size: int,
        thumbnail_dir_listing: Optional[Set[str]] = None,
    ) -> Optional["PILImage.Image"]:
        """Return cached thumbnail as PIL Image if present on disk, else None."""
        from PIL import Image

        cache_key_base = self.get_cache_key(image_path)
        exact_cache_key = f"{cache_key_base}_{size}"
        disk_path = os.path.join(self.thumbnail_cache_dir, f"{exact_cache_key}.jpg")
        if os.path.exists(disk_path):
            try:
                im = Image.open(disk_path)
                im.load()
                return im.convert("RGB")
            except Exception:
                pass

        best_disk_size = 0
        best_disk_path = None
        try:
            if thumbnail_dir_listing is None:
                thumbnail_files = (
                    set(os.listdir(self.thumbnail_cache_dir))
                    if os.path.exists(self.thumbnail_cache_dir)
                    else set()
                )
            else:
                thumbnail_files = thumbnail_dir_listing

            prefix = cache_key_base + "_"
            scanned = 0
            max_disk_scan = 200
            for filename in thumbnail_files:
                scanned += 1
                if scanned > max_disk_scan:
                    break
                if filename.startswith(prefix) and filename.endswith(".jpg"):
                    try:
                        cached_size = int(filename.split("_")[-1].replace(".jpg", ""))
                        if cached_size >= size and cached_size > best_disk_size:
                            best_disk_size = cached_size
                            best_disk_path = os.path.join(self.thumbnail_cache_dir, filename)
                    except (ValueError, IndexError):
                        continue

            if best_disk_path and os.path.exists(best_disk_path):
                im = Image.open(best_disk_path)
                im.load()
                im = im.convert("RGB")
                if im.width != size or im.height != size:
                    im.thumbnail((size, size), Image.Resampling.LANCZOS)
                return im
        except Exception:
            pass

        return None

    def cache_thumbnail_sync(self, image_path: str, pil_image: "PILImage.Image", size: int) -> None:
        """Write JPEG to the same path ImageCacheManager uses."""
        if self.is_in_app_cache_directory(image_path):
            return

        cache_key = f"{self.get_cache_key(image_path)}_{size}"
        try:
            disk_path = os.path.join(self.thumbnail_cache_dir, f"{cache_key}.jpg")
            rgb = pil_image.convert("RGB")
            rgb.save(disk_path, "JPEG", quality=85)
        except Exception:
            pass
