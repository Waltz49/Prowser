#!/usr/bin/env python3
"""Persist chat image snapshots under temp or profile data directories."""

from __future__ import annotations

import os
import shutil
import uuid

from prowser_temp_files import prowser_temp_subdir
from utils import validate_image_file

CHAT_TEMP_SUBDIR = "chat_conversation"
MAX_CHAT_IMAGES = 4


def chat_storage_root() -> str:
    from prowser_temp_files import ensure_temporary_files_directory

    return os.path.join(ensure_temporary_files_directory(), CHAT_TEMP_SUBDIR)


def cleanup_all_chat_storage() -> None:
    """Remove every chat temp session folder (current and prior app runs)."""
    root = chat_storage_root()
    try:
        if os.path.isdir(root):
            shutil.rmtree(root, ignore_errors=True)
    except OSError:
        pass


def reset_image_store_session(
    image_store: "ChatImageStore",
    *,
    persistent: bool | None = None,
) -> None:
    if persistent is None:
        persistent = image_store.is_persistent
    if persistent:
        from chat_plugins.chat_persistence import session_images_dir

        image_store._persistent = True
        image_store._session_id = "persisted"
        image_store._session_dir = str(session_images_dir())
        os.makedirs(image_store._session_dir, mode=0o700, exist_ok=True)
        return
    image_store._persistent = False
    image_store._session_id = uuid.uuid4().hex
    image_store._session_dir = os.path.join(
        prowser_temp_subdir(CHAT_TEMP_SUBDIR),
        image_store._session_id,
    )
    os.makedirs(image_store._session_dir, mode=0o700, exist_ok=True)


class ChatImageStore:
    """Copy dropped images into a session folder so chat context stays stable."""

    def __init__(self, *, persistent: bool = False) -> None:
        self._persistent = persistent
        if persistent:
            from chat_plugins.chat_persistence import session_images_dir

            self._session_id = "persisted"
            self._session_dir = str(session_images_dir())
        else:
            self._session_id = uuid.uuid4().hex
            self._session_dir = os.path.join(
                prowser_temp_subdir(CHAT_TEMP_SUBDIR),
                self._session_id,
            )
        os.makedirs(self._session_dir, mode=0o700, exist_ok=True)

    @property
    def is_persistent(self) -> bool:
        return self._persistent

    @property
    def session_dir(self) -> str:
        return self._session_dir

    def reset_session(self) -> None:
        """Clear chat images for the current storage mode and start fresh."""
        if self._persistent:
            try:
                if os.path.isdir(self._session_dir):
                    shutil.rmtree(self._session_dir, ignore_errors=True)
            except OSError:
                pass
            reset_image_store_session(self, persistent=True)
            return
        cleanup_all_chat_storage()
        reset_image_store_session(self, persistent=False)

    def store_images(
        self,
        source_paths: list[str],
        *,
        message_id: str,
    ) -> list[str]:
        """Copy up to MAX_CHAT_IMAGES valid images into the session directory."""
        stored: list[str] = []
        session_root = os.path.abspath(self._session_dir)
        for idx, src in enumerate(source_paths[:MAX_CHAT_IMAGES]):
            if not src or not os.path.isfile(src):
                continue
            abs_src = os.path.abspath(src)
            if abs_src.startswith(session_root + os.sep) and validate_image_file(abs_src):
                stored.append(abs_src)
                continue
            if not validate_image_file(src):
                continue
            ext = os.path.splitext(src)[1] or ".png"
            dest = os.path.join(
                self._session_dir,
                f"{message_id}_{idx}{ext.lower()}",
            )
            shutil.copy2(src, dest)
            stored.append(os.path.abspath(dest))
        return stored

    def replace_message_images(
        self,
        old_paths: list[str],
        new_source_paths: list[str],
        *,
        message_id: str,
        still_referenced: set[str] | None = None,
    ) -> list[str]:
        """Update stored images for a message, removing files no longer referenced."""
        kept = self.store_images(new_source_paths, message_id=message_id)
        kept_set = set(kept)
        for path in old_paths:
            if path not in kept_set:
                self.remove_message_images(
                    [path], still_referenced=still_referenced
                )
        return kept

    def remove_message_images(
        self,
        image_paths: list[str],
        *,
        still_referenced: set[str] | None = None,
    ) -> None:
        chat_root = os.path.abspath(
            os.path.join(os.path.abspath(self._session_dir), os.pardir)
        )
        keep = still_referenced or set()
        for path in image_paths:
            if not path:
                continue
            try:
                ap = os.path.abspath(path)
                if ap in keep:
                    continue
                if ap.startswith(chat_root + os.sep) and os.path.isfile(ap):
                    os.unlink(ap)
            except OSError:
                pass

    def restage_message_images(self, messages) -> None:
        """Copy message images into the current session directory and update paths."""
        from chat_plugins.chat_image_paths import align_source_image_paths

        for msg in messages:
            if msg.role != "user" or not msg.image_paths:
                continue
            sources = list(msg.source_image_paths or msg.image_paths)
            msg.image_paths = self.store_images(
                msg.image_paths,
                message_id=msg.message_id,
            )
            msg.source_image_paths = align_source_image_paths(
                msg.image_paths, sources
            )
