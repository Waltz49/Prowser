#!/usr/bin/env python3
"""Download and resolve the bundled faster-whisper model for PyInstaller builds."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

DEFAULT_WHISPER_MODEL_ID = "Systran/faster-whisper-tiny.en"
BUNDLED_WHISPER_DIRNAME = "faster-whisper-tiny.en"
WHISPER_MODEL_FILES = (
    "config.json",
    "model.bin",
    "tokenizer.json",
    "vocabulary.txt",
)


def whisper_models_cache_dir(root: str | None = None) -> Path:
    base = Path(root or os.environ.get("SCRIPT_DIR", os.getcwd()))
    return base / ".pyinstaller_whisper_models" / BUNDLED_WHISPER_DIRNAME


def download_whisper_model(
    *,
    root: str | None = None,
    model_id: str = DEFAULT_WHISPER_MODEL_ID,
) -> Path:
    """Download only the files required for tiny.en into .pyinstaller_whisper_models/."""
    target = whisper_models_cache_dir(root)
    target.mkdir(parents=True, exist_ok=True)

    missing = [
        name
        for name in WHISPER_MODEL_FILES
        if not (target / name).is_file() or (target / name).stat().st_size < 1
    ]
    if not missing:
        return target

    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=model_id,
        allow_patterns=list(WHISPER_MODEL_FILES),
        local_dir=str(target),
        local_dir_use_symlinks=False,
    )

    still_missing = [name for name in WHISPER_MODEL_FILES if not (target / name).is_file()]
    if still_missing:
        raise RuntimeError(
            f"Whisper model download incomplete; missing: {', '.join(still_missing)}"
        )
    return target


def bundled_whisper_model_ready(root: str | None = None) -> bool:
    target = whisper_models_cache_dir(root)
    return all((target / name).is_file() for name in WHISPER_MODEL_FILES)


def pyinstaller_datas_entries(root: str | None = None) -> list[tuple[str, str]]:
    """Datas tuples for Prowser.spec (repo-relative src paths)."""
    base = Path(root or os.environ.get("SCRIPT_DIR", os.getcwd()))
    model_dir = whisper_models_cache_dir(base)
    if not bundled_whisper_model_ready(base):
        raise FileNotFoundError(
            f"Whisper model not ready under {model_dir}; run download first."
        )
    rel_root = model_dir.relative_to(base)
    dest = f"whisper_models/{BUNDLED_WHISPER_DIRNAME}"
    return [
        (str(rel_root / name).replace(os.sep, "/"), dest) for name in WHISPER_MODEL_FILES
    ]


def format_pyinstaller_datas(root: str | None = None) -> str:
    lines = []
    for src, dest in pyinstaller_datas_entries(root):
        lines.append(f"        ('{src}', '{dest}'),")
    return "\n".join(lines)


def resolve_whisper_model_path() -> str:
    """Local bundled model directory when frozen, else Hugging Face model id/path."""
    model_id = os.environ.get("WHISPER_MODEL", DEFAULT_WHISPER_MODEL_ID).strip()
    use_bundled = model_id in {
        DEFAULT_WHISPER_MODEL_ID,
        BUNDLED_WHISPER_DIRNAME,
        "tiny.en",
    }
    if getattr(sys, "frozen", False) and use_bundled:
        try:
            from pyinstaller_frozen_support import frozen_bundle_roots
        except ImportError:
            frozen_bundle_roots = lambda: []  # type: ignore[assignment, misc]
        for root in frozen_bundle_roots():
            candidate = os.path.join(
                root, "whisper_models", BUNDLED_WHISPER_DIRNAME
            )
            if os.path.isfile(os.path.join(candidate, "model.bin")):
                return candidate
    if os.path.isdir(model_id) and os.path.isfile(
        os.path.join(model_id, "model.bin")
    ):
        return model_id
    return model_id or DEFAULT_WHISPER_MODEL_ID


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("download",),
        help="download the bundled whisper model",
    )
    parser.add_argument(
        "--format",
        choices=("pyinstaller",),
        help="emit PyInstaller datas lines for the spec file",
    )
    parser.add_argument(
        "--root",
        default=os.environ.get("SCRIPT_DIR", os.getcwd()),
        help="repository root (default: SCRIPT_DIR or cwd)",
    )
    args = parser.parse_args()

    if args.format == "pyinstaller":
        print(format_pyinstaller_datas(args.root))
        return

    if args.command == "download":
        path = download_whisper_model(root=args.root)
        print(f"Whisper model ready: {path}")
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
