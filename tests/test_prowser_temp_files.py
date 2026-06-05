import os

import pytest

import tempfile

from prowser_temp_files import (
    default_temporary_files_directory,
    ensure_temporary_files_directory,
    invalidate_temporary_files_directory_cache,
    resolve_temporary_files_directory,
    validate_temporary_files_directory_for_settings,
)


def test_default_path_is_absolute():
    path = default_temporary_files_directory("testuser")
    assert path == os.path.abspath("/tmp/prowser_testuser")


def test_resolve_expands_and_absolutizes(tmp_path):
    custom = tmp_path / "work" / "temp"
    resolved = resolve_temporary_files_directory(
        {"temporary_files_directory": str(custom)}
    )
    assert resolved == os.path.abspath(str(custom))


def test_resolve_blank_uses_default():
    resolved = resolve_temporary_files_directory({"temporary_files_directory": None})
    assert resolved == default_temporary_files_directory()


def test_validate_rejects_file_path(tmp_path):
    file_path = tmp_path / "not_a_dir"
    file_path.write_text("x", encoding="utf-8")
    err = validate_temporary_files_directory_for_settings(str(file_path))
    assert err is not None
    assert "not a directory" in err.lower()


def test_ensure_creates_custom_settings_dir(tmp_path):
    invalidate_temporary_files_directory_cache()
    custom = tmp_path / "prowser_temp"
    settings = {"temporary_files_directory": str(custom)}
    base = ensure_temporary_files_directory(settings)
    assert base == os.path.abspath(str(custom))
    fd, path = tempfile.mkstemp(prefix="unit-", suffix=".bin", dir=base)
    os.close(fd)
    try:
        assert os.path.isfile(path)
    finally:
        os.unlink(path)


def test_validate_permission_error_on_unwritable_parent(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can write anywhere")
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    os.chmod(blocked, 0o500)
    try:
        nested = blocked / "child"
        err = validate_temporary_files_directory_for_settings(str(nested))
        assert err is not None
    finally:
        os.chmod(blocked, 0o700)
