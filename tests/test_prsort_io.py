import tempfile
import os

from files.prsort_io import (
    parse_custom_sort_file,
    parse_locked_filenames,
    read_prsort_lines,
    strip_prsort_warning_lines,
)


def test_strip_warning_lines():
    lines = [
        "# THIS FILE IS ONLY FOR custom sort",
        "# DO NOT USE for locks",
        "#reversed:false",
        "a.jpg",
    ]
    out = strip_prsort_warning_lines(lines)
    assert out[0] == "#reversed:false"
    assert out[1] == "a.jpg"


def test_parse_locked_filenames():
    lines = ["#reversed:false", "*locked.jpg", "free.jpg"]
    locked = parse_locked_filenames(lines)
    assert locked == {"locked.jpg"}


def test_parse_custom_sort_file():
    lines = ["#reversed:true", "*a.jpg", "b.jpg"]
    parsed = parse_custom_sort_file(lines)
    assert parsed is not None
    names, is_rev, locked = parsed
    assert is_rev is True
    assert names == ["a.jpg", "b.jpg"]
    assert locked == {"a.jpg"}


def test_read_prsort_file_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, ".prsort")
        with open(path, "w", encoding="utf-8") as f:
            f.write("#reversed:false\none.jpg\n*two.jpg\n")
        lines = read_prsort_lines(path)
        assert lines is not None
        assert parse_locked_filenames(lines) == {"two.jpg"}
