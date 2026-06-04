import os
import tempfile

from path_exclusions import _is_excluded_path, prune_walk_dirs


def test_is_excluded_path_prefix():
    excl = ["/tmp/cache"]
    assert _is_excluded_path("/tmp/cache", excl)
    assert _is_excluded_path("/tmp/cache/nested", excl)
    assert not _is_excluded_path("/tmp/other", excl)


def test_prune_walk_dirs_clears_on_exclude():
    with tempfile.TemporaryDirectory() as tmp:
        excluded = [tmp]
        dirs = ["sub"]
        skipped = prune_walk_dirs(tmp, dirs, excluded_paths=excluded, process_hidden=True)
        assert skipped is True
        assert dirs == []


def test_prune_walk_dirs_hidden():
    root = "/fake/root"
    dirs = [".hidden", "visible"]
    skipped = prune_walk_dirs(
        root,
        dirs,
        excluded_paths=[],
        process_hidden=False,
        skipped_patterns=(),
    )
    assert skipped is False
    assert dirs == ["visible"]
