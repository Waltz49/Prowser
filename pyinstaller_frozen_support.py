#!/usr/bin/env python3
"""PyInstaller frozen-app helpers (MLX native libs, mflux availability)."""

from __future__ import annotations

import importlib.util
import os
import sys


def frozen_bundle_roots() -> list[str]:
    """Directories that may contain mlx/lib when running a frozen macOS app."""
    roots: list[str] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    exe = getattr(sys, "executable", None)
    if exe:
        macos_dir = os.path.dirname(os.path.abspath(exe))
        roots.append(macos_dir)
        contents = os.path.normpath(os.path.join(macos_dir, ".."))
        for sub in ("Frameworks", "Resources"):
            candidate = os.path.join(contents, sub)
            if os.path.isdir(candidate):
                roots.append(candidate)
    seen: set[str] = set()
    unique: list[str] = []
    for root in roots:
        norm = os.path.normpath(root)
        if norm not in seen and os.path.isdir(norm):
            seen.add(norm)
            unique.append(norm)
    return unique


def configure_frozen_native_paths() -> None:
    """Help dyld find MLX shared libraries inside a PyInstaller bundle (GUI + workers)."""
    if not getattr(sys, "frozen", False):
        return

    dyld_dirs: list[str] = []
    for root in frozen_bundle_roots():
        for rel in ("mlx/lib", "mlx", "."):
            candidate = os.path.join(root, rel)
            if os.path.isdir(candidate):
                dyld_dirs.append(candidate)

    if not dyld_dirs:
        return

    existing = os.environ.get("DYLD_LIBRARY_PATH", "")
    extra = ":".join(dyld_dirs)
    os.environ["DYLD_LIBRARY_PATH"] = (
        f"{extra}:{existing}" if existing else extra
    )


_SANA_SPRINT_PIPELINE_REL = os.path.join(
    "diffusers", "pipelines", "sana", "pipeline_sana_sprint.py"
)
_Z_IMAGE_PIPELINE_REL = os.path.join(
    "diffusers", "pipelines", "z_image", "pipeline_z_image.py"
)


def _sana_sprint_pipeline_bundled() -> bool:
    """True when the SANA Sprint pipeline file exists in a PyInstaller bundle (no imports)."""
    for root in frozen_bundle_roots():
        if os.path.isfile(os.path.join(root, _SANA_SPRINT_PIPELINE_REL)):
            return True
    return False


def _z_image_pipeline_bundled() -> bool:
    """True when the Z-Image pipeline file exists in a PyInstaller bundle (no imports)."""
    for root in frozen_bundle_roots():
        if os.path.isfile(os.path.join(root, _Z_IMAGE_PIPELINE_REL)):
            return True
    return False


def _pipeline_module_on_disk(module_name: str) -> bool:
    """True if module_name resolves to a real file (dev / non-frozen)."""
    if getattr(sys, "frozen", False):
        if module_name == "diffusers.pipelines.sana.pipeline_sana_sprint":
            return _sana_sprint_pipeline_bundled()
        # Avoid find_spec in frozen builds: importing parents pulls transformers metadata.
        rel = module_name.replace(".", os.sep) + ".py"
        for root in frozen_bundle_roots():
            if os.path.isfile(os.path.join(root, rel)):
                return True
        return False
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, AttributeError, ValueError):
        return False
    if spec is None:
        return False
    origin = getattr(spec, "origin", None)
    if origin and origin != "namespace" and os.path.isfile(origin):
        return True
    locations = getattr(spec, "submodule_search_locations", None) or ()
    for loc in locations:
        if loc and os.path.isdir(loc):
            return True
    return False


def _package_importable(module_name: str) -> bool:
    """True when module_name is importable (find_spec + import for frozen bundles)."""
    if _pipeline_module_on_disk(module_name):
        return True
    if not getattr(sys, "frozen", False):
        try:
            importlib.import_module(module_name)
            return True
        except ImportError:
            return False
    try:
        importlib.import_module(module_name)
    except ImportError:
        return False
    return True


def mflux_is_installed() -> bool:
    """True when the mflux package is importable (find_spec fails in some frozen builds)."""
    return _package_importable("mflux")


def sdnq_is_installed() -> bool:
    """True when the sdnq package is importable (Z-Image quantized weights)."""
    return _package_importable("sdnq")


def diffusers_is_installed() -> bool:
    """True when diffusers SANA Sprint backend is present (menu + worker)."""
    if getattr(sys, "frozen", False):
        return _sana_sprint_pipeline_bundled() or _z_image_pipeline_bundled()
    if _pipeline_module_on_disk("diffusers.pipelines.sana.pipeline_sana_sprint"):
        return True
    try:
        importlib.import_module("diffusers")
        from diffusers import SanaSprintPipeline  # noqa: F401
        return True
    except Exception as exc:
        log_frozen_diagnostic(
            f"[imagegen] diffusers/SANA availability check failed: {exc!r}"
        )
        return False


def log_frozen_diagnostic(message: str) -> None:
    """Write to stdout (View log) without requiring Qt."""
    try:
        print(message, flush=True)
    except Exception:
        pass


def bundled_whisper_model_dir() -> str | None:
    """Path to bundled faster-whisper-tiny.en when model.bin is in the app bundle."""
    rel = os.path.join("whisper_models", "faster-whisper-tiny.en")
    for root in frozen_bundle_roots():
        candidate = os.path.join(root, rel)
        if os.path.isfile(os.path.join(candidate, "model.bin")):
            return candidate
    return None


def whisper_voice_input_is_bundled() -> bool:
    """True when faster-whisper runtime and the tiny.en weights are in the bundle."""
    if not getattr(sys, "frozen", False):
        return False
    try:
        import faster_whisper  # noqa: F401
        import sounddevice  # noqa: F401
    except ImportError:
        return False
    return bundled_whisper_model_dir() is not None
