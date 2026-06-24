#!/usr/bin/env python3
"""imagegen-NNNN path allocation and optional EXIF metadata."""

from __future__ import annotations

import os
import re
import json
from typing import Any, Dict, List, Optional, Tuple

from exif.exif_utils import TAG_USERCOMMENT

FILE_PATTERN_RE = re.compile(r"imagegen-(\d{4})\.[^.]+$", re.IGNORECASE)


def downloads_dir() -> str:
    return os.path.expanduser("~/Downloads")


def image_creation_dir() -> str:
    """Directory for generated images: custom path when enabled and valid, else ~/Downloads."""
    try:
        from config import get_config

        entry = get_config().load_settings().get("image_creation_directory") or {}
        if isinstance(entry, dict) and entry.get("enabled"):
            path = entry.get("path")
            if path:
                path = os.path.expanduser(str(path))
                if os.path.isdir(path):
                    return path
    except Exception:
        pass
    return downloads_dir()


def find_highest_imagegen_index(directory: str) -> int:
    """Highest NNNN from imagegen-NNNN.* in directory."""
    if not os.path.isdir(directory):
        return 0
    indices = []
    for name in os.listdir(directory):
        m = FILE_PATTERN_RE.match(name)
        if m:
            indices.append(int(m.group(1)))
    return max(indices, default=0)


def next_imagegen_path(directory: Optional[str] = None, ext: str = ".png") -> str:
    """Next available imagegen-NNNN path in directory (default from settings or ~/Downloads)."""
    directory = directory or image_creation_dir()
    os.makedirs(directory, exist_ok=True)
    new_index = find_highest_imagegen_index(directory) + 1
    if not ext.startswith("."):
        ext = "." + ext
    return os.path.join(directory, f"imagegen-{new_index:04d}{ext}")


def format_elapsed_hms(seconds: float) -> str:
    """Format seconds as h:mm:ss; minutes always shown (even when zero)."""
    total = int(round(max(0.0, seconds)))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _parse_elapsed_seconds(raw: Any) -> Optional[float]:
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _elapsed_from_metadata_dict(meta: Any) -> Optional[float]:
    if not isinstance(meta, dict):
        return None
    for key in ("generation_time_seconds", "generation_time"):
        value = _parse_elapsed_seconds(meta.get(key))
        if value is not None:
            return value
    return None


def _elapsed_from_xmp_generation_tags(image_path: str) -> Optional[float]:
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(image_path) as img:
            xmp_data = img.info.get("XML:com.adobe.xmp")
    except Exception:
        return None
    if not xmp_data:
        return None
    for open_tag, close_tag in (
        ("<mflux:generationTimeSeconds>", "</mflux:generationTimeSeconds>"),
        ("<mflux:generationTime>", "</mflux:generationTime>"),
    ):
        if open_tag not in xmp_data:
            continue
        start = xmp_data.index(open_tag) + len(open_tag)
        end = xmp_data.index(close_tag, start)
        value = _parse_elapsed_seconds(xmp_data[start:end].strip())
        if value is not None:
            return value
    return None


def elapsed_seconds_from_image_metadata(image_path: str) -> Optional[float]:
    """Read generation time from mflux EXIF JSON or XMP on the output file."""
    if not image_path or not os.path.isfile(image_path):
        return None
    value = _elapsed_from_xmp_generation_tags(image_path)
    if value is not None:
        return value
    try:
        from mflux.utils.metadata_reader import MetadataReader
    except ImportError:
        return None
    try:
        all_meta = MetadataReader.read_all_metadata(image_path)
    except Exception:
        return None
    if not isinstance(all_meta, dict):
        return None
    for section in ("exif", "xmp"):
        value = _elapsed_from_metadata_dict(all_meta.get(section))
        if value is not None:
            return value
    return None


def resolve_generation_elapsed_seconds(
    worker_result: Optional[Dict[str, Any]],
    output_path: str,
    *,
    local_elapsed: Optional[float] = None,
) -> Optional[float]:
    """Prefer embedded image metadata, then worker result, then local timing."""
    if output_path:
        value = elapsed_seconds_from_image_metadata(output_path)
        if value is not None:
            return value
    if worker_result:
        value = _elapsed_from_metadata_dict(worker_result)
        if value is not None:
            return value
    return _parse_elapsed_seconds(local_elapsed)


def _exif_scalar_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def lora_name_for_exif(lora_value: Any) -> Optional[str]:
    """LoRA label for EXIF (display name, not filesystem path)."""
    if not _exif_scalar_present(lora_value):
        return None
    from imagegen_plugins.flux_lora_catalog import get_lora_entry
    from imagegen_plugins.mflux_lora_presets import coerce_lora_preset_id

    preset_id = coerce_lora_preset_id(lora_value)
    if preset_id == "none":
        return None
    entry = get_lora_entry(preset_id)
    if entry is not None:
        return entry.display_name
    text = str(lora_value).strip()
    if not text or text.lower() == "none":
        return None
    if os.sep in text or text.endswith(".safetensors"):
        return os.path.basename(text)
    return text


_EXIF_PARAM_LINE_INT = re.compile(
    r"^\s*(Seed|Steps|Quantization)\s*:\s*(\d+)\s*$", re.IGNORECASE
)
_EXIF_PARAM_LINE_GUIDANCE = re.compile(
    r"^\s*Guidance\s*:\s*([\d.]+)\s*$", re.IGNORECASE
)
_EXIF_PARAM_LINE_LORA = re.compile(r"^\s*LoRA\s*:\s*(.+?)\s*$", re.IGNORECASE)
_EXIF_MODEL_STEPS_SUFFIX = re.compile(r"\[(\d+)\]\s*$")


def parse_exif_generation_metadata(full_comment: str) -> Dict[str, Any]:
    """Parse generation fields from EXIF UserComment (Seed, Steps, etc.)."""
    out: Dict[str, Any] = {}
    if not full_comment or not str(full_comment).strip():
        return out

    in_model_block = False
    for line in full_comment.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower().rstrip(":")
        if lower in ("image model", "image model:"):
            in_model_block = True
            continue
        if lower.startswith("prompt") or lower.startswith("references"):
            in_model_block = False

        if in_model_block:
            m_steps = _EXIF_MODEL_STEPS_SUFFIX.search(stripped)
            if m_steps is not None and "steps" not in out:
                out["steps"] = int(m_steps.group(1))

        m_int = _EXIF_PARAM_LINE_INT.match(stripped)
        if m_int is not None:
            label = m_int.group(1).lower()
            value = int(m_int.group(2))
            if label == "quantization":
                out["quantization"] = value
            else:
                out[label] = value
            continue

        m_guidance = _EXIF_PARAM_LINE_GUIDANCE.match(stripped)
        if m_guidance is not None:
            try:
                out["guidance"] = float(m_guidance.group(1))
            except ValueError:
                pass
            continue

        m_lora = _EXIF_PARAM_LINE_LORA.match(stripped)
        if m_lora is not None:
            name = m_lora.group(1).strip()
            if name:
                out["lora"] = name

    return out


def format_image_exif_prompt(
    model_name: str,
    prompt_text: str,
    iterations: Optional[int] = None,
    elapsed_seconds: Optional[float] = None,
    *,
    seed: Optional[int] = None,
    steps: Optional[int] = None,
    quantization: Optional[int] = None,
    lora: Optional[str] = None,
    guidance: Optional[float] = None,
) -> str:
    """EXIF UserComment body: Image Model block then Prompt."""
    prompt_text = (prompt_text or "").strip()
    param_lines: List[str] = []
    if _exif_scalar_present(seed):
        try:
            param_lines.append(f"Seed: {int(seed)}")
        except (TypeError, ValueError):
            pass
    if _exif_scalar_present(steps):
        try:
            param_lines.append(f"Steps: {int(steps)}")
        except (TypeError, ValueError):
            pass
    if _exif_scalar_present(quantization):
        try:
            param_lines.append(f"Quantization: {int(quantization)}")
        except (TypeError, ValueError):
            pass
    if _exif_scalar_present(lora):
        param_lines.append(f"LoRA: {str(lora).strip()}")
    if _exif_scalar_present(guidance):
        try:
            param_lines.append(f"Guidance: {float(guidance):g}")
        except (TypeError, ValueError):
            pass

    if model_name:
        iter_suffix = f" [{iterations}]" if iterations is not None else ""
        model_block = f"Image Model:\n{model_name}{iter_suffix}"
        if param_lines:
            model_block += "\n" + "\n".join(param_lines)
        if elapsed_seconds is not None:
            elapsed_str = format_elapsed_hms(elapsed_seconds)
            elapsed_line = f"Elapsed: {elapsed_str}"
            step_count = steps if _exif_scalar_present(steps) else iterations
            if step_count is not None and step_count > 0:
                elapsed_line += (
                    f" ({format_elapsed_hms(elapsed_seconds / step_count)}/iter)"
                )
            model_block += f"\n{elapsed_line}"
        return f"{model_block}\n\nPrompt:\n{prompt_text}"

    if param_lines:
        header = "\n".join(param_lines)
        if prompt_text:
            return f"{header}\n\nPrompt:\n{prompt_text}"
        return header
    return f"Prompt:\n{prompt_text}"


def apply_refinement_source_for_next_copy(
    values: Dict[str, Any], output_path: str
) -> Dict[str, Any]:
    """Refinement series: next copy replaces the first source image with the last result."""
    out = dict(values)
    if not output_path or not os.path.isfile(output_path):
        return out
    ap = os.path.normpath(os.path.abspath(output_path))
    multi = out.get("source_image_paths")
    if isinstance(multi, list) and multi:
        paths = [
            os.path.normpath(os.path.abspath(str(raw or "")))
            for raw in multi
            if raw
        ]
    else:
        paths = resolve_source_image_paths(out)
    if paths:
        paths[0] = ap
    else:
        paths = [ap]
    out["source_image_path"] = ap
    out["source_image_paths"] = list(paths)
    return out


def resolve_source_image_paths(values: Dict[str, Any]) -> List[str]:
    """Ordered unique source paths from dialog/worker values (1–N images)."""
    paths: List[str] = []
    seen: set[str] = set()
    multi = values.get("source_image_paths")
    if isinstance(multi, list):
        for raw in multi:
            ap = os.path.normpath(os.path.abspath(str(raw or "")))
            if ap and os.path.isfile(ap) and ap not in seen:
                seen.add(ap)
                paths.append(ap)
    primary = str(values.get("source_image_path") or "").strip()
    if primary:
        ap = os.path.normpath(os.path.abspath(primary))
        if ap and os.path.isfile(ap) and ap not in seen:
            paths.insert(0, ap)
    return paths


def source_paths_for_generation_exif(
    values: Dict[str, Any],
    *,
    extra_paths: Optional[List[str]] = None,
) -> List[str]:
    """Source paths for EXIF References: values first, then optional fallbacks."""
    paths = resolve_source_image_paths(values)
    if paths:
        return paths
    if not extra_paths:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for raw in extra_paths:
        ap = os.path.normpath(os.path.abspath(str(raw or "")))
        if ap and os.path.isfile(ap) and ap not in seen:
            seen.add(ap)
            out.append(ap)
    return out


def reference_entry_for_source(
    source_path: str, output_path: str
) -> Optional[Tuple[str, str]]:
    """(exif_line, source_path) for References block; matches expand-reference style."""
    if not source_path or not os.path.isfile(source_path):
        return None
    ap = os.path.normpath(os.path.abspath(source_path))
    out_dir = os.path.normpath(os.path.dirname(os.path.abspath(output_path)))
    if os.path.dirname(ap) == out_dir:
        return (f"./{os.path.basename(ap)}", ap)
    return (ap, ap)


def reference_entries_for_source_paths(
    source_paths: List[str], output_path: str
) -> List[Tuple[str, str]]:
    """One EXIF reference entry per source path (same-dir uses ./basename lines)."""
    entries: List[Tuple[str, str]] = []
    seen_abs: set[str] = set()
    for source_path in source_paths:
        entry = reference_entry_for_source(source_path, output_path)
        if entry is None:
            continue
        _line, abs_path = entry
        ap = os.path.normpath(os.path.abspath(abs_path))
        if ap in seen_abs:
            continue
        seen_abs.add(ap)
        entries.append(entry)
    return entries


def inject_references_exif_section(
    base_comment: str,
    new_file_path: str,
    reference_entries: Optional[List[Tuple[str, Optional[str]]]] = None,
    *,
    allow_cross_directory: bool = False,
) -> str:
    """Insert References block (path label + file mtime per file) after Image Model / before Prompt."""
    out_dir = os.path.normpath(os.path.dirname(os.path.abspath(new_file_path)))
    pairs: List[Tuple[str, str]] = []
    seen_abs: set = set()

    if reference_entries:
        for item in reference_entries:
            if not item or len(item) != 2:
                continue
            exif_line, path_opt = item[0], item[1]
            if not exif_line or not isinstance(exif_line, str):
                continue
            path = path_opt
            if not path or not isinstance(path, str) or not os.path.isfile(path):
                rel = exif_line.lstrip("./")
                if rel:
                    candidate = os.path.normpath(os.path.join(out_dir, rel))
                    if os.path.isfile(candidate):
                        path = candidate
            if not path or not os.path.isfile(path):
                continue
            ap = os.path.normpath(os.path.abspath(path))
            if not allow_cross_directory and os.path.dirname(ap) != out_dir:
                continue
            if ap in seen_abs:
                continue
            seen_abs.add(ap)
            line = exif_line.strip()
            if allow_cross_directory and os.path.dirname(ap) != out_dir:
                line = ap
            try:
                mtime_stamp = f"{os.path.getmtime(ap):.6f}"
            except OSError:
                continue
            pairs.append((line, mtime_stamp))

    if not pairs:
        return base_comment
    ref_lines = ["References:"]
    for line, mtime_stamp in pairs:
        ref_lines.append(line)
        ref_lines.append(mtime_stamp)
    ref_block = "\n".join(ref_lines)
    marker = "\n\nPrompt:\n"
    if marker in base_comment:
        return base_comment.replace(marker, "\n\n" + ref_block + "\n\nPrompt:\n", 1)
    if base_comment.startswith("Prompt:\n"):
        return ref_block + "\n\n" + base_comment
    return base_comment + "\n\n" + ref_block


def parse_mflux_metadata_json(text: str) -> Optional[Dict[str, Any]]:
    """Parse compact mflux generation JSON from EXIF UserComment text."""
    if not text or not str(text).strip():
        return None
    stripped = str(text).strip()
    if stripped[0] not in ("{", "["):
        return None
    try:
        data = json.loads(stripped)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if "mflux_version" in data:
        return data
    if "prompt" in data and any(k in data for k in ("seed", "steps", "model", "quantize")):
        return data
    return None


_LEGACY_MODEL_QUANT_SUFFIX_RE = re.compile(r"\s*Q\d+")


def _strip_legacy_model_quant_suffix(name: str) -> str:
    """Old EXIF / labels used Q{n} in the model name; strip for display and lookup."""
    return _LEGACY_MODEL_QUANT_SUFFIX_RE.sub("", name, count=1).strip()


def _strip_quant_from_image_model_block(text: str) -> str:
    """Remove legacy Q{n} from the model name line when displaying old EXIF."""
    lines = text.splitlines()
    result: List[str] = []
    after_image_model = False
    for line in lines:
        if line.strip().lower().rstrip(":") == "image model":
            result.append(line)
            after_image_model = True
            continue
        if after_image_model and line.strip():
            line = _strip_legacy_model_quant_suffix(line)
            after_image_model = False
        result.append(line)
    return "\n".join(result)


def menu_label_for_hf_model_id(
    model_id: str,
    values: Optional[Dict[str, Any]] = None,
) -> str:
    """Human-facing model label from generation metadata or hf_model_id."""
    model_id = str(model_id or "").strip()
    if not model_id or model_id.lower() == "none":
        return ""
    legacy_id = _strip_legacy_model_quant_suffix(model_id)
    try:
        from imagegen_plugins import discover_plugins

        for plugin in discover_plugins():
            if (
                plugin.hf_model_id == model_id
                or plugin.display_name == model_id
                or plugin.display_name == legacy_id
            ):
                return plugin.display_name
    except Exception:
        pass
    if "/" in model_id:
        return model_id.rsplit("/", 1)[-1]
    return legacy_id


def format_exif_comment_from_mflux_metadata(
    meta: Dict[str, Any],
    *,
    model_name: str = "",
    values: Optional[Dict[str, Any]] = None,
    elapsed_seconds: Optional[float] = None,
    seed: Optional[int] = None,
    include_quantization: bool = True,
) -> str:
    """Build Image Model / Prompt EXIF body from mflux JSON metadata."""
    values = dict(values or {})
    if not model_name:
        model_name = menu_label_for_hf_model_id(
            str(meta.get("model_config") or meta.get("model") or ""),
            values,
        )
    prompt_text = str(values.get("prompt") or meta.get("prompt") or "").strip()
    steps = values.get("steps")
    if steps is None:
        steps = meta.get("steps")
    quant = None
    if include_quantization:
        quant = values.get("mflux_quantize")
        if quant is None:
            quant = meta.get("quantize")
    guidance = values.get("guidance_scale")
    if guidance is None:
        guidance = meta.get("guidance")
    if seed is None and not values.get("random_seed"):
        try:
            seed = int(values.get("seed"))
        except (TypeError, ValueError):
            seed = None
    if seed is None:
        try:
            seed = int(meta.get("seed"))
        except (TypeError, ValueError):
            seed = None
    if elapsed_seconds is None:
        elapsed_seconds = _parse_elapsed_seconds(meta.get("generation_time_seconds"))
        if elapsed_seconds is None:
            elapsed_seconds = _parse_elapsed_seconds(meta.get("generation_time"))
    return format_image_exif_prompt(
        model_name,
        prompt_text,
        iterations=steps,
        elapsed_seconds=elapsed_seconds,
        seed=seed,
        steps=steps,
        quantization=quant,
        lora=lora_name_for_exif(values.get("mflux_lora")),
        guidance=guidance,
    )


def format_user_comment_text_for_display(
    text: str,
    *,
    values: Optional[Dict[str, Any]] = None,
    model_name: str = "",
) -> str:
    """Show mflux JSON UserComment using the same layout as finished EXIF."""
    meta = parse_mflux_metadata_json(text)
    if meta is None:
        return _strip_quant_from_image_model_block(text)
    return format_exif_comment_from_mflux_metadata(
        meta,
        model_name=model_name,
        values=values,
    )


def _mflux_json_from_user_comment(image_path: str) -> Optional[Dict[str, Any]]:
    """Parse mflux generation JSON from EXIF UserComment when present."""
    try:
        from exif.exif_utils import decode_usercomment, get_usercomment_from_path

        raw = get_usercomment_from_path(image_path)
        if not raw:
            return None
        text = decode_usercomment(raw).strip()
        return parse_mflux_metadata_json(text)
    except Exception:
        return None


def make_readable_user_comment_before_browse(
    image_path: str,
    *,
    model_name: str,
    values: Dict[str, Any],
    elapsed_seconds: Optional[float] = None,
    completed_step: int,
    total_steps: int,
    seed: Optional[int] = None,
    reference_entries: Optional[List[Tuple[str, Optional[str]]]] = None,
    allow_cross_directory_references: bool = False,
    include_quantization: bool = True,
) -> None:
    """Write final-style Image Model / Prompt EXIF for in-progress step previews."""
    if not image_path or not os.path.isfile(image_path):
        return
    if completed_step >= total_steps:
        return
    try:
        from exif.exif_utils import decode_usercomment, get_usercomment_from_path

        raw = get_usercomment_from_path(image_path)
        if raw:
            text = decode_usercomment(raw).strip()
            if text.startswith("Image Model:"):
                return
    except Exception:
        pass

    meta = _mflux_json_from_user_comment(image_path)
    if meta is not None:
        comment = format_exif_comment_from_mflux_metadata(
            meta,
            model_name=model_name,
            values=values,
            elapsed_seconds=elapsed_seconds,
            seed=seed,
            include_quantization=include_quantization,
        )
    else:
        if seed is None and not values.get("random_seed"):
            try:
                seed = int(values.get("seed"))
            except (TypeError, ValueError):
                seed = None
        comment = format_image_exif_prompt(
            model_name,
            str(values.get("prompt") or "").strip(),
            iterations=values.get("steps"),
            elapsed_seconds=elapsed_seconds,
            seed=seed,
            steps=values.get("steps"),
            quantization=(
                values.get("mflux_quantize")
                if include_quantization
                else None
            ),
            lora=lora_name_for_exif(values.get("mflux_lora")),
            guidance=values.get("guidance_scale"),
        )
    if not write_exif_user_comment(
        image_path,
        comment,
        reference_entries=reference_entries,
        allow_cross_directory_references=allow_cross_directory_references,
    ):
        return


def _write_exif_user_comment_pil(image_path: str, user_comment: str) -> None:
    """Write UserComment via PIL save (in-progress mflux JSON pretty-print only)."""
    if not image_path or not user_comment:
        return
    try:
        from PIL import Image
    except ImportError:
        return
    try:
        with Image.open(image_path) as img:
            exif = img.getexif()
            if exif is None:
                exif = {}
            exif[TAG_USERCOMMENT] = user_comment
            img.save(image_path, exif=exif)
    except Exception:
        pass


def write_exif_user_comment(
    image_path: str,
    base_comment: str,
    *,
    reference_entries: Optional[List[Tuple[str, Optional[str]]]] = None,
    allow_cross_directory_references: bool = False,
) -> bool:
    """Write EXIF UserComment (0x9286) on a PNG/JPEG/WebP with proper UTF-8/Unicode encoding."""
    user_comment = inject_references_exif_section(
        base_comment,
        image_path,
        reference_entries=reference_entries,
        allow_cross_directory=allow_cross_directory_references,
    )
    from exif.exif_utils import encode_usercomment, restore_usercomment_to_file

    return restore_usercomment_to_file(image_path, encode_usercomment(user_comment))
