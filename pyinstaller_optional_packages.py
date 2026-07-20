#!/usr/bin/env python3
"""Optional PyInstaller bundle packages (--min builds omit these)."""

from __future__ import annotations

import os

MIN_BUILD_ENV = "PYINSTALLER_MIN_BUILD"

# Unused in application code — never bundle (all builds).
ALWAYS_EXCLUDE_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "skimage",
        "imagehash",
    }
)

# Dev / demo modules excluded from import-tree analysis.
ANALYZER_SKIP_FILENAMES: frozenset[str] = frozenset(
    {
        "gemma4_voice_vision_demo.py",
        "list_models.py",
        "hfmodels.py",
        "generate_minimal_requirements.py",
        "generate_minimal_requirements_questionable.py",
        "block_test.py",
        "fast_test.py",
        "jit_test.py",
    }
)

# Omitted from --min bundles (AI generation, LM Studio SDK, audio, faces, orphans).
MIN_EXCLUDE_IMPORT_ROOTS: frozenset[str] = frozenset(
    {
        "mflux",
        "mlx",
        "diffusers",
        "accelerate",
        "sdnq",
        "lmstudio",
        "faster_whisper",
        "ctranslate2",
        "sounddevice",
        "_sounddevice",
        "pocket_tts",
        "openai",
        "pyinstaller_whisper_models",
        "whisper_voice_input",
        "face_recognition",
        "face_recognition_models",
        "dlib",
        "onnxruntime",
        "cv2",
        "scipy",
        "matplotlib",
        "av",
        "piper",
        "fastapi",
        "uvicorn",
        "starlette",
        "imagegen_plugins",
        "chat_plugins",
    }
)

# PyInstaller --exclude-module names for --min (top-level modules).
MIN_EXCLUDE_MODULES: tuple[str, ...] = (
    "mflux",
    "mlx",
    "diffusers",
    "accelerate",
    "sdnq",
    "lmstudio",
    "faster_whisper",
    "ctranslate2",
    "sounddevice",
    "pocket_tts",
    "openai",
    "face_recognition",
    "face_recognition_models",
    "dlib",
    "onnxruntime",
    "cv2",
    "scipy",
    "matplotlib",
    "av",
    "piper",
    "fastapi",
    "uvicorn",
    "starlette",
    "imagegen_plugins",
    "chat_plugins",
    "skimage",
    "imagehash",
)

# collect_all targets for full (non-min) builds beyond analyzer output.
FULL_BUILD_COLLECT_ALL: tuple[str, ...] = (
    "face_recognition_models",
    "mflux",
    "mlx",
    "diffusers",
    "accelerate",
    "peft",
    "sdnq",
    "transformers",
    "requests",
    "huggingface_hub",
    "safetensors",
    "regex",
    "tokenizers",
    "faster_whisper",
    "ctranslate2",
)

# collect_all targets for --min (CLIP / similarity only; transformers via hook).
MIN_BUILD_COLLECT_ALL: tuple[str, ...] = (
    "requests",
    "huggingface_hub",
    "safetensors",
    "regex",
    "tokenizers",
)

# Packages passed to collect_all() inside the generated .spec Analysis preamble.
FULL_SPEC_COLLECT_PACKAGES: tuple[str, ...] = (
    "diffusers",
    "accelerate",
    "peft",
    "mflux",
    "mlx",
    "face_recognition_models",
    "transformers",
    "requests",
    "huggingface_hub",
    "safetensors",
    "regex",
    "tokenizers",
    "faster_whisper",
    "ctranslate2",
)

MIN_SPEC_COLLECT_PACKAGES: tuple[str, ...] = (
    "requests",
    "huggingface_hub",
    "safetensors",
    "regex",
    "tokenizers",
)

# dist-info dirs required by transformers.dependency_versions_check at import.
TRANSFORMERS_RUNTIME_METADATA: tuple[str, ...] = (
    "packaging",
    "filelock",
    "tqdm",
    "regex",
    "PyYAML",
)

FULL_SPEC_COPY_METADATA: tuple[str, ...] = (
    "transformers",
    "requests",
    "diffusers",
    "huggingface_hub",
    "accelerate",
    "peft",
    "tokenizers",
    "safetensors",
) + TRANSFORMERS_RUNTIME_METADATA

MIN_SPEC_COPY_METADATA: tuple[str, ...] = (
    "transformers",
    "requests",
    "huggingface_hub",
    "tokenizers",
    "safetensors",
) + TRANSFORMERS_RUNTIME_METADATA

# Similarity / CLIP — included in all bundles (including --min).
SIMILARITY_EXTRA_HIDDEN: tuple[str, ...] = (
    "torch",
    "torchvision",
    "transformers",
    "transformers.models.clip",
    "transformers.models.clip.modeling_clip",
    "transformers.models.clip.processing_clip",
)

# Extra hidden imports merged into the spec (full builds only).
FULL_BUILD_EXTRA_HIDDEN: tuple[str, ...] = SIMILARITY_EXTRA_HIDDEN + (
    "face_recognition",
    "face_recognition_models",
    "mflux",
    "mlx",
    "mlx._reprlib_fix",
    "diffusers",
    "diffusers.pipelines",
    "diffusers.pipelines.sana",
    "diffusers.pipelines.z_image",
    "sdnq",
    "accelerate",
    "peft",
    "requests",
    "faster_whisper",
    "ctranslate2",
    "sounddevice",
    "_sounddevice",
    "whisper_voice_input",
    "pyinstaller_whisper_models",
)

# Similarity / CLIP only (--min drops imagegen, audio, faces).
MIN_BUILD_EXTRA_HIDDEN: tuple[str, ...] = SIMILARITY_EXTRA_HIDDEN

MANDATORY_PYOBJC_HIDDEN: tuple[str, ...] = (
    "AppKit",
    "LaunchServices",
    "CoreServices",
    "Foundation",
)

MANDATORY_HIDDEN: tuple[str, ...] = (
    "pyinstaller_frozen_support",
)

# --collect-submodules CLI args (after feature packages) for the initial pyinstaller run.
FULL_EXTRA_COLLECT_SUBMODULES: tuple[str, ...] = (
    "imagegen_plugins",
    "mflux",
    "mlx",
    "diffusers",
    "accelerate",
    "peft",
)

MIN_EXTRA_COLLECT_SUBMODULES: tuple[str, ...] = ()


def is_min_build() -> bool:
    return os.environ.get(MIN_BUILD_ENV, "").strip() in ("1", "true", "yes")


def import_root_is_excluded(import_root: str, *, min_build: bool | None = None) -> bool:
    root = (import_root or "").replace("-", "_").split(".")[0]
    if root in ALWAYS_EXCLUDE_IMPORT_ROOTS:
        return True
    if min_build if min_build is not None else is_min_build():
        return root in MIN_EXCLUDE_IMPORT_ROOTS
    return False


def package_name_is_excluded(package_name: str, *, min_build: bool | None = None) -> bool:
    return import_root_is_excluded(package_name.replace("-", "_"), min_build=min_build)


def filter_hidden_imports(names: list[str] | set[str], *, min_build: bool | None = None) -> list[str]:
    min_flag = min_build if min_build is not None else is_min_build()
    out: set[str] = set()
    for name in names:
        root = name.split(".")[0]
        if import_root_is_excluded(root, min_build=min_flag):
            continue
        if root in ALWAYS_EXCLUDE_IMPORT_ROOTS:
            continue
        out.add(name)
    return sorted(out)


def filter_collect_all(names: list[str] | set[str], *, min_build: bool | None = None) -> list[str]:
    min_flag = min_build if min_build is not None else is_min_build()
    out: set[str] = set()
    for name in names:
        pkg = name.replace("-", "_").split(".")[0]
        if import_root_is_excluded(pkg, min_build=min_flag):
            continue
        if pkg in ALWAYS_EXCLUDE_IMPORT_ROOTS:
            continue
        out.add(name)
    return sorted(out)
