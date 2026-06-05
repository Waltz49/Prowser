#!/usr/bin/env python3
"""Export base/mask WebP layers from Pixelmator Pro for MFLUX infill."""

from __future__ import annotations

import os
import shutil
import subprocess
from prowser_temp_files import prowser_mkdtemp, prowser_temp_subdir
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from imagegen_plugins.outpaint_mask import fit_infill_paint_dims
from pil_image_io import open_pil_with_exif_correction

_IMAGE_REFERENCE_EXTS = frozenset(
    {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
)

_SCRIPT_PATH = Path(__file__).resolve().parent / "applescript_pixelmator_export.applescript"

_PIXELMATOR_PRO_INSTALLED: Optional[bool] = None


def is_pixelmator_pro_installed() -> bool:
    """Return True if Pixelmator Pro is installed as a macOS app (checked once)."""
    global _PIXELMATOR_PRO_INSTALLED
    if _PIXELMATOR_PRO_INSTALLED is None:
        paths = (
            "/Applications/Pixelmator Pro.app",
            os.path.expanduser("~/Applications/Pixelmator Pro.app"),
        )
        _PIXELMATOR_PRO_INSTALLED = any(os.path.isdir(path) for path in paths)
    return _PIXELMATOR_PRO_INSTALLED


def pixelmator_export_dir() -> str:
    """Directory for Pixelmator WebP exports (base.webp, mask.webp)."""
    return prowser_temp_subdir("pixelmator")


def pixelmator_base_path() -> str:
    return os.path.join(pixelmator_export_dir(), "base.webp")


def pixelmator_mask_path() -> str:
    return os.path.join(pixelmator_export_dir(), "mask.webp")


def _run_pixelmator_applescript(script: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        text = (result.stdout or "").strip()
        return text or None
    except (subprocess.CalledProcessError, OSError):
        return None


def is_pixelmator_running() -> bool:
    result = subprocess.run(
        ["pgrep", "-x", "Pixelmator Pro"], capture_output=True
    )
    return result.returncode == 0


def get_pixelmator_front_document_name() -> Optional[str]:
    """Name of Pixelmator Pro front document (no path)."""
    return _run_pixelmator_applescript(
        'tell application "Pixelmator Pro"\n'
        'if not (exists front document) then return ""\n'
        'return name of front document\n'
        'end tell'
    )


def get_pixelmator_front_document_path() -> Optional[str]:
    """POSIX path of front Pixelmator document when saved to disk."""
    path = _run_pixelmator_applescript(
        'tell application "Pixelmator Pro"\n'
        'if not (exists front document) then return ""\n'
        'try\n'
        'return POSIX path of (file of front document)\n'
        'on error\n'
        'return ""\n'
        'end try\n'
        'end tell'
    )
    if path and os.path.isfile(path):
        return os.path.normpath(path)
    return None


def pixelmator_mask_to_mflux(mask: Image.Image) -> Image.Image:
    """Pixelmator mask export: opaque = fill, transparent = keep → MFLUX L (white = fill)."""
    alpha = mask.convert("RGBA").getchannel("A")
    return alpha.point(lambda a: 255 if a > 127 else 0, mode="L")


def _clean_existing_exports() -> None:
    for file_path in (pixelmator_base_path(), pixelmator_mask_path()):
        if os.path.isfile(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass


def _applescript_source() -> str:
    export_dir = pixelmator_export_dir()
    template = _SCRIPT_PATH.read_text(encoding="utf-8")
    return template.replace("__EXPORT_DIR__", export_dir)


def export_pixelmator_base_and_mask() -> Tuple[bool, Dict[str, Any], Optional[str]]:
    """Run export AppleScript; return (ok, paths/metadata, error_message)."""
    if not is_pixelmator_running():
        return (
            False,
            {},
            "Pixelmator Pro is not running. Open an image with a mask layer first.",
        )

    _clean_existing_exports()
    meta: Dict[str, Any] = {
        "pixelmator_doc_name": get_pixelmator_front_document_name(),
        "pixelmator_doc_path": get_pixelmator_front_document_path(),
    }

    try:
        subprocess.run(
            ["osascript", "-"],
            input=_applescript_source(),
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or e.stdout or str(e)).strip()
        return False, meta, f"Pixelmator export failed: {err[:500]}"

    time.sleep(1)

    base_path = pixelmator_base_path()
    mask_path = pixelmator_mask_path()
    if not os.path.isfile(base_path) or not os.path.isfile(mask_path):
        return (
            False,
            meta,
            f"Export did not create base.webp and mask.webp in {pixelmator_export_dir()}. "
            "Use a square canvas with at least two layers (mask on top, image below).",
        )

    name_after = get_pixelmator_front_document_name()
    if name_after:
        meta["pixelmator_doc_name"] = name_after
    path_after = get_pixelmator_front_document_path()
    if path_after:
        meta["pixelmator_doc_path"] = path_after

    meta["pixelmator_base_path"] = base_path
    meta["pixelmator_mask_path"] = mask_path
    return True, meta, None


def persist_pixelmator_exports(meta: Dict[str, Any]) -> Dict[str, Any]:
    """Copy base/mask exports to a dedicated directory for multi-copy infill runs."""
    base_path = str(meta.get("pixelmator_base_path") or "")
    mask_path = str(meta.get("pixelmator_mask_path") or "")
    if not base_path or not mask_path:
        return meta
    if not os.path.isfile(base_path) or not os.path.isfile(mask_path):
        return meta
    job_dir = prowser_mkdtemp(prefix="imagegen-infill-")
    base_dest = os.path.join(job_dir, "base.webp")
    mask_dest = os.path.join(job_dir, "mask.webp")
    shutil.copy2(base_path, base_dest)
    shutil.copy2(mask_path, mask_dest)
    out = dict(meta)
    out["pixelmator_base_path"] = base_dest
    out["pixelmator_mask_path"] = mask_dest
    out["_pixelmator_batch_dir"] = job_dir
    return out


def persist_paint_infill_exports(source_path: str, mask_image) -> Dict[str, Any]:
    """Write working-size base + painted mask into a temp batch dir for infill runs."""
    source_path = os.path.normpath(os.path.abspath(source_path))
    if not os.path.isfile(source_path):
        raise ValueError(f"Source image not found: {source_path}")

    if hasattr(mask_image, "width") and hasattr(mask_image, "height"):
        mask_w, mask_h = int(mask_image.width()), int(mask_image.height())
    else:
        mask_w, mask_h = mask_image.size

    job_dir = prowser_mkdtemp(prefix="imagegen-infill-")
    _, src_ext = os.path.splitext(source_path)
    ext = src_ext if src_ext else ".png"
    base_dest = os.path.join(job_dir, f"base{ext}")
    mask_dest = os.path.join(job_dir, "mask.png")

    pil_img = open_pil_with_exif_correction(
        source_path, ignore_exif=False, cr2_half_size=False
    )
    if pil_img is None:
        with Image.open(source_path) as fallback:
            pil_img = fallback.convert("RGB")
    work_w, work_h = fit_infill_paint_dims(pil_img.width, pil_img.height)
    if (work_w, work_h) != (pil_img.width, pil_img.height):
        pil_img = pil_img.resize((work_w, work_h), Image.Resampling.LANCZOS)
    if (mask_w, mask_h) != (work_w, work_h):
        pil_img = pil_img.resize((mask_w, mask_h), Image.Resampling.LANCZOS)
    try:
        pil_img.save(base_dest)
    finally:
        if hasattr(pil_img, "close"):
            pil_img.close()

    if hasattr(mask_image, "save"):
        if not mask_image.save(mask_dest, "PNG"):
            raise RuntimeError("Could not save painted mask.")
    else:
        mask_image.convert("RGBA").save(mask_dest, "PNG")

    return {
        "pixelmator_base_path": base_dest,
        "pixelmator_mask_path": mask_dest,
        "pixelmator_doc_name": os.path.basename(source_path),
        "pixelmator_doc_path": source_path,
        "_pixelmator_batch_dir": job_dir,
    }


def remove_persisted_pixelmator_batch(values: Dict[str, Any]) -> None:
    """Remove infill batch directory created by :func:`persist_pixelmator_exports`."""
    job_dir = values.get("_pixelmator_batch_dir")
    if not job_dir:
        return
    try:
        shutil.rmtree(str(job_dir), ignore_errors=True)
    except OSError:
        pass


def resolve_paint_reference_in_dir(
    output_path: str, doc_name: Optional[str]
) -> Optional[Tuple[str, str]]:
    """Resolve (./basename EXIF line, absolute path) for infill References."""
    name = (doc_name or "").strip()
    if not name:
        return None
    out_dir = os.path.normpath(os.path.dirname(os.path.abspath(output_path)))
    base = os.path.basename(name)
    stem, ext = os.path.splitext(base)
    if ext.lower() in _IMAGE_REFERENCE_EXTS:
        candidate = os.path.normpath(os.path.join(out_dir, base))
        if os.path.isfile(candidate):
            return (f"./{base}", candidate)
    for try_ext in (".webp", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".tif"):
        candidate = os.path.normpath(os.path.join(out_dir, stem + try_ext))
        if os.path.isfile(candidate):
            return (f"./{stem}{try_ext}", candidate)
    return None


def resolve_infill_reference(
    output_path: str,
    doc_name: Optional[str],
    *,
    pixelmator_file_path: Optional[str] = None,
    fallback_paths: Optional[List[str]] = None,
) -> Optional[Tuple[str, str]]:
    """Best reference (EXIF line, path) for infill output."""
    if pixelmator_file_path:
        ap = os.path.normpath(os.path.abspath(pixelmator_file_path))
        out_dir = os.path.normpath(os.path.dirname(os.path.abspath(output_path)))
        if os.path.isfile(ap):
            if os.path.dirname(ap) == out_dir:
                return (f"./{os.path.basename(ap)}", ap)
            return (ap, ap)
    hit = resolve_paint_reference_in_dir(output_path, doc_name)
    if hit:
        return hit
    for p in fallback_paths or []:
        if not p or not os.path.isfile(p):
            continue
        ap = os.path.normpath(os.path.abspath(p))
        out_dir = os.path.normpath(os.path.dirname(os.path.abspath(output_path)))
        if os.path.dirname(ap) == out_dir:
            return (f"./{os.path.basename(ap)}", ap)
        return (ap, ap)
    return None
