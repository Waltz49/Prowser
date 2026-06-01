#!/usr/bin/env python3
"""Pre-formatted status-bar task info for image generation and AI caption jobs."""

from __future__ import annotations

import html
import os
import re
from typing import Any, Dict, Optional

from imagegen_plugins.image_gen_model_availability import _resolve_mflux_repo_id
from imagegen_plugins.image_gen_pipeline_modes import get_pipeline
from imagegen_plugins.image_gen_registry import ImageGenModelPlugin
from imagegen_plugins.mflux_lora_presets import MFLUX_LORA_UI_CHOICES


def _escape(text: str) -> str:
    return html.escape(text or "", quote=True)


PROMPT_DISPLAY_MAX_LEN = 100


def _truncate(text: str, limit: int = PROMPT_DISPLAY_MAX_LEN) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def parse_queue_status_title(html_text: str) -> str:
    """Centered title from a job queue / status HTML table (may include '(Running)')."""
    match = _QUEUE_TITLE_ROW_RE.search(html_text or "")
    if not match:
        return ""
    return html.unescape(match.group(1).strip())


def parse_queue_status_elapsed(html_text: str) -> str:
    """Elapsed / estimate cell from queue status HTML, or empty when absent."""
    match = _QUEUE_ELAPSED_ROW_RE.search(html_text or "")
    if not match:
        return ""
    raw = re.sub(r"<[^>]+>", "", match.group(1))
    return html.unescape(raw).strip()


def elide_prompt_for_sidebar(prompt: str, *, max_len: int = 48) -> str:
    return _truncate(prompt, max_len)


def full_prompt_tooltip_text(full_prompt: str) -> str:
    """Return full prompt for a hover tooltip when status display truncates it."""
    full = (full_prompt or "").strip()
    if not full:
        return ""
    if _truncate(full) == full:
        return ""
    return full


def _table_row(label: str, value: str) -> str:
    return (
        f"<tr><td><b>{_escape(label)}</b></td>"
        f"<td>{_escape(value)}</td></tr>"
    )


def _table_row_html_value(label: str, value_html: str) -> str:
    return (
        f"<tr><td><b>{_escape(label)}</b></td>"
        f"<td>{value_html}</td></tr>"
    )


def _exif_style_link(label: str, href: str = "reflevel://") -> str:
    from theme_service import get_active_theme

    accent = get_active_theme().accent_color_hex
    return (
        f'<a href="{href}" style="color:{accent};text-decoration:underline;">'
        f"{_escape(label)}</a>"
    )


def _normalize_reference_paths(*path_groups: list[str] | str | None) -> list[str]:
    """Unique existing paths in order (for status-bar / queue reference rows)."""
    out: list[str] = []
    seen: set[str] = set()
    for group in path_groups:
        if isinstance(group, str):
            group = [group] if group else []
        elif not group:
            continue
        for raw in group:
            p = os.path.normpath(str(raw or ""))
            if not p or not os.path.isfile(p) or p in seen:
                continue
            seen.add(p)
            out.append(p)
    return out


def _reference_labels_for_paths(paths: list[str]) -> list[str]:
    return [os.path.basename(p) for p in paths if p and os.path.isfile(p)]


_EXPAND_ELAPSED_ROW_RE = re.compile(
    r"(<tr><td><b>Elapsed:</b></td><td>)(.*?)(</td></tr>)",
    re.DOTALL,
)
_QUEUE_TITLE_ROW_RE = re.compile(
    r'<tr><td colspan="2"[^>]*>\s*<b><span[^>]*>([^<]*)</span>',
    re.DOTALL | re.IGNORECASE,
)
_QUEUE_ELAPSED_ROW_RE = re.compile(
    r"<tr><td><b>Elapsed:</b></td><td>(.*?)</td></tr>",
    re.DOTALL,
)
_EXPAND_REFERENCES_ROW_RE = re.compile(
    r"<tr><td><b>References:</b></td><td>.*?</td></tr>"
)


def strip_references_from_status_html(html_text: str) -> str:
    """Remove the References table row (sidebar jobs pane hides text links)."""
    if not html_text:
        return ""
    return _EXPAND_REFERENCES_ROW_RE.sub("", html_text)


def _table_title_row(title: str, *, running: bool = False) -> str:
    display = f"{title} (Running)" if running else title
    return (
        '<tr><td colspan="2" align="center" style="padding-bottom:4px;">'
        f'<b><span style="font-size:13px;">{_escape(display)}</span></b>'
        "</td></tr>"
    )


def _series_after_this_one_value(count: int) -> str:
    noun = "image" if count == 1 else "images"
    return f"{count} {noun} after this one."


def _series_queued_value(count: int) -> str:
    noun = "image" if count == 1 else "images"
    return f"{count} {noun}."


def _series_refinement_suffix(values: Dict[str, Any]) -> str:
    """Suffix when the job dialog exposed 'use last generated image'."""
    if "use_last_generated_image" not in values:
        return ""
    if values.get("use_last_generated_image"):
        return "\u00A0\u00A0\u00A0\u00A0(Refinement)"
   
    return "\u00A0\u00A0\u00A0\u00A0(No Refinement)"


def format_series_line_value(base: str, values: Dict[str, Any]) -> str:
    """Series cell text with optional refinement label."""
    return base + _series_refinement_suffix(values)


def _task_menu_title_for_pipeline(pipeline_id: str) -> str:
    if pipeline_id == "mflux_fill_expand":
        return "Image Expansion"
    if pipeline_id == "mflux_fill_infill":
        return "Image Infill"
    if pipeline_id == "mflux_flux2_klein_edit":
        return "Image Edit"
    return "Image Generation"


def _append_table_rows(html_text: str, rows: list[str]) -> str:
    if not rows or "</table>" not in html_text:
        return html_text
    return html_text.replace("</table>", "".join(rows) + "</table>", 1)


def _generation_status_table_rows(
    fields: dict[str, str],
    *,
    steps_value: str | None = None,
) -> list[str]:
    """Model / size / steps / … / prompt rows — same order as the status-bar menu."""
    rows: list[str] = []
    if fields.get("model"):
        rows.append(_table_row("Model:", fields["model"]))
    if fields.get("lora"):
        rows.append(_table_row("LoRA:", fields["lora"]))
    if fields.get("size"):
        rows.append(_table_row("Size:", fields["size"]))
    steps_display = steps_value if steps_value is not None else fields.get("steps", "")
    if steps_display:
        rows.append(_table_row("Steps:", steps_display))
    if fields.get("quant"):
        rows.append(_table_row("Quant:", fields["quant"]))
    if fields.get("prompt"):
        rows.append(_table_row(fields["prompt_label"], fields["prompt"]))
    if fields.get("neg"):
        rows.append(_table_row("Neg:", fields["neg"]))
    return rows


def _steps_display_with_progress(
    fields_steps: str,
    *,
    step: int | None = None,
    step_total: int | None = None,
) -> str:
    """Steps cell text — step count only; timing lives on the Elapsed row."""
    steps_value = fields_steps or ""
    if step is not None and step_total is not None and step_total > 0:
        step_i = max(0, min(int(step), int(step_total)))
        steps_value = f"{step_i} of {int(step_total)}"
    return steps_value


def refresh_expand_task_status_html_for_display(
    html_text: str,
    *,
    elapsed_seconds: float | None,
    source_path: str = "",
    base_path: str = "",
    reference_paths: list[str] | None = None,
) -> tuple[str, list[str]]:
    """Insert elapsed + reference links when the task status menu is shown."""
    if not html_text:
        return html_text, []

    html_text = _EXPAND_ELAPSED_ROW_RE.sub("", html_text)
    html_text = _EXPAND_REFERENCES_ROW_RE.sub("", html_text)

    insert_rows: list[str] = []
    if elapsed_seconds is not None:
        insert_rows.append(
            _table_row("Elapsed:", _format_elapsed_cell_value(elapsed_seconds))
        )

    ref_paths = _normalize_reference_paths(reference_paths, source_path)
    base_norm = (
        os.path.normpath(base_path)
        if base_path and os.path.isfile(base_path)
        else ""
    )
    source_paths = [p for p in ref_paths if p != base_norm]
    ref_links = [_exif_style_link(os.path.basename(p)) for p in source_paths]
    if base_norm:
        ref_paths.append(base_norm)
        ref_links.append(_exif_style_link("base"))
    if ref_links:
        insert_rows.append(
            _table_row_html_value(
                "References:",
                f'<span style="white-space:normal;">{", ".join(ref_links)}</span>',
            )
        )

    if insert_rows and "</table>" in html_text:
        html_text = html_text.replace(
            "</table>", "".join(insert_rows) + "</table>", 1
        )
    return html_text, ref_paths


def _table_html(
    rows: list[str], *, title: Optional[str] = None, running: bool = False
) -> str:
    if not rows and not title:
        return ""
    parts: list[str] = []
    if title:
        parts.append(_table_title_row(title, running=running))
    parts.extend(rows)
    return "<table cellspacing=\"2\" cellpadding=\"0\">" + "".join(parts) + "</table>"


def _resolve_hf_model_name(pipeline_id: str, hf_model_id: str) -> str:
    hf_model_id = (hf_model_id or "").strip()
    if pipeline_id == "flux_schnell_mflux_play":
        return _resolve_mflux_repo_id(hf_model_id) if hf_model_id else ""
    return hf_model_id


def _lora_display_label(preset_id: str) -> Optional[str]:
    preset_id = (preset_id or "none").strip()
    if not preset_id or preset_id == "none":
        return None
    for label, pid in MFLUX_LORA_UI_CHOICES:
        if pid == preset_id:
            return label
    return preset_id


def _collect_generation_status_fields(
    plugin: ImageGenModelPlugin,
    values: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
) -> dict[str, str]:
    """Collect generation status labels/values keyed by logical field name."""
    pipeline_id = plugin.pipeline_id
    effective = dict(values)
    if payload:
        effective.update(payload)
    fields: dict[str, str] = {}
    hf_id = _resolve_hf_model_name(
        pipeline_id,
        str(effective.get("hf_model_id") or plugin.hf_model_id or ""),
    )
    if hf_id:
        fields["model"] = hf_id

    if pipeline_id in ("flux_schnell_mflux_play", "mflux_fill_expand"):
        lora_label = _lora_display_label(str(values.get("mflux_lora") or "none"))
        if lora_label:
            fields["lora"] = lora_label

    width = effective.get("width")
    height = effective.get("height")
    if width is not None and height is not None:
        try:
            fields["size"] = f"{int(width)} x {int(height)}"
        except (TypeError, ValueError):
            pass

    steps = effective.get("steps")
    if steps is not None:
        try:
            fields["steps"] = str(int(steps))
        except (TypeError, ValueError):
            pass

    if pipeline_id in (
        "flux_schnell_mflux_play",
        "mflux_fill_expand",
        "mflux_flux2_klein_edit",
    ):
        quant = effective.get("mflux_quantize")
        if quant is not None:
            try:
                fields["quant"] = str(int(quant))
            except (TypeError, ValueError):
                pass

    prompt = _truncate(str(effective.get("prompt") or ""))
    if prompt:
        fields["prompt"] = prompt
        fields["prompt_label"] = get_pipeline(pipeline_id).prompt_status_label

    neg = _truncate(str(effective.get("negative_prompt") or ""))
    if neg:
        fields["neg"] = neg

    return fields


def _references_row_for_values(
    plugin: ImageGenModelPlugin,
    values: Dict[str, Any],
    *,
    source_path: str = "",
    base_path: str = "",
) -> Optional[str]:
    """References table row (one comma-separated line) when the job has sources."""
    pipeline_id = plugin.pipeline_id
    ref_paths: list[str] = []
    if get_pipeline(pipeline_id).requires_source_image:
        from imagegen_plugins.image_gen_naming import resolve_source_image_paths

        ref_paths = resolve_source_image_paths(values)
        if not ref_paths and source_path:
            ref_paths = _normalize_reference_paths(source_path)
    elif source_path:
        ref_paths = _normalize_reference_paths(source_path)
    base_norm = (
        os.path.normpath(base_path)
        if base_path and os.path.isfile(base_path)
        else ""
    )
    labels = _reference_labels_for_paths([p for p in ref_paths if p != base_norm])
    if base_norm:
        labels.append("base")
    if not labels:
        return None
    return _table_row("References:", ", ".join(labels))


def format_image_generation_status_html(
    plugin: ImageGenModelPlugin,
    values: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
) -> str:
    """Rich-text block for the status-bar task menu (image generation)."""
    pipeline_id = plugin.pipeline_id
    fields = _collect_generation_status_fields(plugin, values, payload)
    rows = _generation_status_table_rows(fields)
    ref_row = _references_row_for_values(plugin, values)
    if ref_row:
        rows.append(ref_row)
    return _table_html(rows, title=_task_menu_title_for_pipeline(pipeline_id))


def format_image_generation_queue_status_html(
    plugin: ImageGenModelPlugin,
    values: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
    *,
    step: int | None = None,
    step_total: int | None = None,
    elapsed_seconds: float | None = None,
    estimate_seconds: float | None = None,
    source_path: str = "",
    base_path: str = "",
    running: bool = False,
    series_images_after: int | None = None,
    series_copies_total: int | None = None,
) -> str:
    """Rich-text block for the job queue — same field order as the status-bar menu."""
    pipeline_id = plugin.pipeline_id
    fields = _collect_generation_status_fields(plugin, values, payload)
    steps_value = _steps_display_with_progress(
        fields.get("steps", ""),
        step=step,
        step_total=step_total,
    )
    rows = _generation_status_table_rows(fields, steps_value=steps_value)
    if (
        step is not None
        and step_total is not None
        and step_total > 0
        and step > 0
        and elapsed_seconds is not None
    ):
        rows.append(
            _table_row(
                "Elapsed:",
                _format_elapsed_cell_value(elapsed_seconds, estimate_seconds),
            )
        )

    ref_row = _references_row_for_values(
        plugin, values, source_path=source_path, base_path=base_path
    )
    if ref_row:
        rows.append(ref_row)

    if series_images_after is not None and series_images_after > 0:
        rows.append(
            _table_row(
                "Series:",
                format_series_line_value(
                    _series_after_this_one_value(series_images_after), values
                ),
            )
        )
    elif series_copies_total is not None and series_copies_total > 1:
        rows.append(
            _table_row(
                "Series:",
                format_series_line_value(
                    _series_queued_value(series_copies_total), values
                ),
            )
        )

    return _table_html(
        rows,
        title=_task_menu_title_for_pipeline(pipeline_id),
        running=running,
    )


def _format_duration(seconds: float) -> str:
    """Format seconds as hh:mm:ss, omitting hours when zero."""
    total = max(0, int(round(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


_ELAPSED_EST_SEPARATOR = "\u00A0" * 5


def _format_elapsed_cell_value(
    elapsed_seconds: float,
    estimate_seconds: float | None = None,
) -> str:
    """Elapsed row cell: duration, optional estimate after five NBSPs."""
    value = _format_duration(elapsed_seconds)
    if estimate_seconds is not None and estimate_seconds > 0:
        value += f"{_ELAPSED_EST_SEPARATOR}Est: {_format_duration(estimate_seconds)}"
    return value


_TIME_RE = r"\d+:\d{2}(?::\d{2})?"
_STEPS_ROW_RE = re.compile(
    rf"(<tr><td><b>Steps:</b></td><td>)[^<]*(?:   {_TIME_RE})?"
    rf"(?:   \(Est: {_TIME_RE}\))?(</td></tr>)"
)


def update_status_html_steps_progress(
    html_text: str,
    step: int,
    total: int,
    *,
    elapsed_seconds: float | None = None,
    estimate_seconds: float | None = None,
) -> str:
    """Replace the Steps line and refresh the Elapsed row with live timing."""
    if not html_text or total <= 0:
        return html_text
    step = max(0, min(int(step), int(total)))
    total = int(total)

    step_value = f"{step} of {total}"
    updated, count = _STEPS_ROW_RE.subn(
        lambda m: m.group(1) + _escape(step_value) + m.group(2),
        html_text,
        count=1,
    )
    html_text = updated if count else html_text
    if step > 0 and elapsed_seconds is not None:
        elapsed_cell = _escape(
            _format_elapsed_cell_value(elapsed_seconds, estimate_seconds)
        )
        html_text = _set_elapsed_row(html_text, elapsed_cell)
    return html_text


def _set_elapsed_row(html_text: str, elapsed_cell: str) -> str:
    """Replace or insert the Elapsed: table row."""
    if not html_text:
        return html_text
    row_html = f"<tr><td><b>Elapsed:</b></td><td>{elapsed_cell}</td></tr>"
    updated, count = _EXPAND_ELAPSED_ROW_RE.subn(
        lambda m: f"{m.group(1)}{elapsed_cell}{m.group(3)}",
        html_text,
        count=1,
    )
    if count:
        return updated
    if "</table>" in html_text:
        return html_text.replace("</table>", row_html + "</table>", 1)
    return html_text


def remove_elapsed_row(html_text: str) -> str:
    """Remove the Elapsed: table row if present."""
    if not html_text:
        return html_text
    return _EXPAND_ELAPSED_ROW_RE.sub("", html_text, count=1)


def freeze_status_html_generation_elapsed(
    html_text: str,
    elapsed_seconds: float,
    *,
    step: int | None = None,
    step_total: int | None = None,
) -> str:
    """Lock elapsed on its own row and leave Steps showing step count only."""
    if not html_text:
        return html_text
    if step is not None and step_total is not None and step_total > 0:
        step_i = max(0, min(int(step), int(step_total)))
        step_value = f"{step_i} of {int(step_total)}"
        updated, count = _STEPS_ROW_RE.subn(
            lambda m: m.group(1) + _escape(step_value) + m.group(2),
            html_text,
            count=1,
        )
        if count:
            html_text = updated
    elapsed_cell = _escape(_format_elapsed_cell_value(elapsed_seconds))
    return _set_elapsed_row(html_text, elapsed_cell)


_ELAPSED_ROW_RE = _EXPAND_ELAPSED_ROW_RE
_COOLDOWN_SUFFIX_RE = re.compile(r"\s+\(Cooldown\)\s+\d+")
_SKIP_COOLDOWN_LINK_RE = re.compile(
    r'\s*<a href="skipcooldown://".*?</a>',
    re.DOTALL,
)
_CACHED_SKIP_COOLDOWN_ICON_HTML: str | None = None


def cooldown_skip_icon_html() -> str:
    """Inline skip-cooldown icon (16×16 PNG) for task-info HTML."""
    global _CACHED_SKIP_COOLDOWN_ICON_HTML
    cached = _CACHED_SKIP_COOLDOWN_ICON_HTML
    if cached is not None:
        return cached
    from theme_base import asset_file_url

    url = asset_file_url("skip_cooldown_icon.png")
    cached = (
        f'<a href="skipcooldown://" title="Skip cooldown">'
        f'<img src="{url}" width="16" height="16" '
        f'style="margin:0 0 0 4px;padding:0;vertical-align:middle;border:none;">'
        f"</a>"
    )
    _CACHED_SKIP_COOLDOWN_ICON_HTML = cached
    return cached


def apply_cooldown_to_status_html(
    html_text: str,
    remaining_seconds: int,
    *,
    skip_icon_html: str = "",
) -> str:
    """Append cooldown countdown (and optional skip icon) to the Elapsed row."""
    if not html_text:
        return html_text
    remaining = max(0, int(remaining_seconds))
    suffix = f"   (Cooldown) {remaining}"
    if skip_icon_html:
        suffix += f" {skip_icon_html}"

    def _replace_row(match: re.Match[str]) -> str:
        prefix, content, closing = match.group(1), match.group(2), match.group(3)
        clean = _SKIP_COOLDOWN_LINK_RE.sub("", content)
        clean = _COOLDOWN_SUFFIX_RE.sub("", clean).rstrip()
        return prefix + clean + suffix + closing

    updated, count = _ELAPSED_ROW_RE.subn(_replace_row, html_text, count=1)
    return updated if count else html_text


def strip_cooldown_from_status_html(html_text: str) -> str:
    """Remove cooldown countdown and skip icon from the Elapsed row."""
    if not html_text:
        return html_text

    def _replace_row(match: re.Match[str]) -> str:
        prefix, content, closing = match.group(1), match.group(2), match.group(3)
        clean = _SKIP_COOLDOWN_LINK_RE.sub("", content)
        clean = _COOLDOWN_SUFFIX_RE.sub("", clean).rstrip()
        return prefix + clean + closing

    updated, count = _ELAPSED_ROW_RE.subn(_replace_row, html_text, count=1)
    return updated if count else html_text


def _caption_model_name() -> str:
    try:
        import lmstudio as lms
    except ImportError:
        pass
    else:
        from config import get_config, CAPTION_DEFAULTS
        from lmstudio_caption import _get_last_lm_model_key, _model_key_from_handle

        settings = get_config().load_settings()
        lms_host = settings.get("caption_lms_host") or CAPTION_DEFAULTS[
            "caption_lms_host"
        ]
        try:
            if lms.Client.is_valid_api_host(lms_host):
                with lms.Client(lms_host) as client:
                    loaded = client.llm.list_loaded()
                    if loaded:
                        key = _model_key_from_handle(loaded[0])
                        if key:
                            return key
        except Exception:
            pass
        saved = _get_last_lm_model_key()
        if saved:
            return saved
    from lmstudio_caption import _get_last_lm_model_key

    return _get_last_lm_model_key() or ""


def _caption_prompt_text(user_prompt_override: Optional[str]) -> str:
    from config import CAPTION_DEFAULTS, get_config

    settings = get_config().load_settings()
    word_count = settings.get(
        "caption_max_words", CAPTION_DEFAULTS["caption_max_words"]
    )
    if user_prompt_override and user_prompt_override.strip():
        return user_prompt_override.strip()
    user_prompt = settings.get("caption_user_prompt") or CAPTION_DEFAULTS[
        "caption_user_prompt"
    ]
    return user_prompt.format(CAPTION_WORD_COUNT=word_count)


def format_caption_status_html(user_prompt_override: Optional[str] = None) -> str:
    """Rich-text block for the status-bar task menu (AI caption / text generation)."""
    rows: list[str] = []
    model = _caption_model_name()
    if model:
        rows.append(_table_row("Model:", model))

    prompt = _truncate(_caption_prompt_text(user_prompt_override))
    if prompt:
        rows.append(_table_row("Prompt:", prompt))

    return _table_html(rows, title="Text Generation")
