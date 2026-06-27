import os

import pytest

from imagegen_plugins.image_gen_naming import exif_reference_line_for_path
from search.reference_graph import resolve_reference_path_with_swap


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()

    def _expanduser(path):
        if path == "~":
            return str(home)
        if path.startswith("~/"):
            return str(home / path[2:])
        return path

    monkeypatch.setattr(os.path, "expanduser", _expanduser)
    return home


def test_same_directory_uses_relative_basename(fake_home):
    out_dir = fake_home / "Downloads"
    out_dir.mkdir()
    source = out_dir / "source.png"
    source.write_bytes(b"x")
    output = out_dir / "imagegen-0001.png"

    line = exif_reference_line_for_path(str(source), str(output))
    assert line == "./source.png"


def test_cross_directory_under_home_uses_tilde(fake_home):
    src_dir = fake_home / "Pictures"
    out_dir = fake_home / "Downloads"
    src_dir.mkdir()
    out_dir.mkdir()
    source = src_dir / "source.png"
    source.write_bytes(b"x")
    output = out_dir / "imagegen-0001.png"

    line = exif_reference_line_for_path(str(source), str(output))
    assert line == "~/Pictures/source.png"


def test_cross_directory_outside_home_uses_absolute_path(fake_home, tmp_path):
    out_dir = fake_home / "Downloads"
    out_dir.mkdir()
    source = tmp_path / "external" / "source.png"
    source.parent.mkdir()
    source.write_bytes(b"x")
    output = out_dir / "imagegen-0001.png"

    line = exif_reference_line_for_path(str(source), str(output))
    assert line == os.path.normpath(str(source))


def test_stored_line_resolves_back_to_source(fake_home):
    src_dir = fake_home / "Pictures"
    out_dir = fake_home / "Downloads"
    src_dir.mkdir()
    out_dir.mkdir()
    source = src_dir / "source.png"
    source.write_bytes(b"x")
    output = out_dir / "imagegen-0001.png"
    output.write_bytes(b"y")

    line = exif_reference_line_for_path(str(source), str(output))
    resolved, swapped = resolve_reference_path_with_swap(
        str(out_dir), line, os.path.getmtime(source)
    )
    assert swapped is False
    assert resolved == os.path.normpath(str(source))
