#!/usr/bin/env python3
"""Best-effort LoRA trigger-word resolution (file metadata, heuristics, online)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from imagegen_plugins.lora_entry import FluxLoraEntry

_TRIGGER_CACHE: Dict[str, Tuple[float, Optional[str], str]] = {}
_GENERIC_TAGS = frozenset(
    {
        "1girl",
        "1boy",
        "solo",
        "portrait",
        "photo",
        "image",
        "picture",
        "test",
        "woman",
        "man",
        "girl",
        "boy",
    }
)
_FILENAME_NOISE_RE = re.compile(
    r"(?i)(?:_lora|_flux|_sdxl|_sd15|aitoolkit|rank\d+|bf16|fp16|step\d+|v\d+)$"
)
_TRIGGER_LINE_RE = re.compile(
    r"(?im)^(?:trigger(?:\s*word)?s?|activation(?:\s*text)?|trained\s*words?)"
    r"\s*[:=-]\s*(.+?)\s*$"
)


@dataclass(frozen=True)
class TriggerResolveResult:
    trigger: Optional[str]
    source: str  # catalog | metadata | filename | online | ""


def resolve_lora_trigger(
    entry: FluxLoraEntry,
    *,
    weights_path: Optional[str | Path] = None,
    allow_online: bool = True,
    timeout_s: float = 5.0,
) -> TriggerResolveResult:
    """
    Resolve a probe/generation trigger for a LoRA entry.

    Order: catalog trigger → safetensors metadata → filename → online → none.
    Network/parse failures are tolerated (returns empty trigger).
    """
    catalog = (entry.trigger_word or "").strip()
    if catalog:
        return TriggerResolveResult(trigger=catalog, source="catalog")

    path = _resolve_weights_path(entry, weights_path)
    if path is not None:
        cached = _cache_get(path)
        if cached is not None:
            trigger, source = cached
            return TriggerResolveResult(trigger=trigger, source=source)

    trigger: Optional[str] = None
    source = ""

    if path is not None:
        trigger = _trigger_from_safetensors_metadata(path)
        if trigger:
            source = "metadata"

    if not trigger and path is not None:
        trigger = _trigger_from_filename(path.stem)
        if trigger:
            source = "filename"

    if not trigger and allow_online:
        trigger = _trigger_from_online(entry, path=path, timeout_s=timeout_s)
        if trigger:
            source = "online"

    if path is not None:
        _cache_put(path, trigger, source)

    return TriggerResolveResult(trigger=trigger, source=source)


def lora_probe_prompt_with_resolved_trigger(
    entry: FluxLoraEntry,
    *,
    fallback: str = "test",
    weights_path: Optional[str | Path] = None,
    allow_online: bool = True,
) -> str:
    """Build probe prompt: optional trigger + user fallback text."""
    from imagegen_plugins.lora_host_registry import HOST_FLUX2_KLEIN

    fb = (fallback or "test").strip() or "test"
    trigger = (entry.trigger_word or "").strip()
    if not trigger:
        resolved = resolve_lora_trigger(
            entry,
            weights_path=weights_path,
            allow_online=allow_online,
            timeout_s=4.0,
        )
        trigger = (resolved.trigger or "").strip()
    if not trigger:
        name = (entry.display_name or "").strip()
        if name:
            return f"{name}, {fb}"
        return fb
    if entry.host_id == HOST_FLUX2_KLEIN:
        return f"Transform into {trigger}"
    return f"{trigger}, {fb}"


def _resolve_weights_path(
    entry: FluxLoraEntry,
    weights_path: Optional[str | Path],
) -> Optional[Path]:
    if weights_path is not None:
        path = Path(weights_path).expanduser()
        if path.is_file():
            return path.resolve()
    for raw in (entry.local_path, entry.source_path):
        text = str(raw or "").strip()
        if not text or text.lower().startswith(("http://", "https://")):
            continue
        path = Path(text).expanduser()
        if path.is_file() and path.suffix.lower() == ".safetensors":
            return path.resolve()
    return None


def _cache_key(path: Path) -> str:
    try:
        st = path.stat()
        return f"{path}:{st.st_mtime_ns}:{st.st_size}"
    except OSError:
        return str(path)


def _cache_get(path: Path) -> Optional[Tuple[Optional[str], str]]:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    key = _cache_key(path)
    row = _TRIGGER_CACHE.get(key)
    if row is None:
        return None
    cached_mtime, trigger, source = row
    if cached_mtime != mtime:
        return None
    return trigger, source


def _cache_put(path: Path, trigger: Optional[str], source: str) -> None:
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return
    if len(_TRIGGER_CACHE) > 512:
        _TRIGGER_CACHE.clear()
    _TRIGGER_CACHE[_cache_key(path)] = (mtime, trigger, source)


def _trigger_from_safetensors_metadata(path: Path) -> Optional[str]:
    try:
        from safetensors import safe_open
    except ImportError:
        return None
    try:
        with safe_open(str(path), framework="pt") as handle:
            metadata = handle.metadata() or {}
    except Exception:
        return None
    if not isinstance(metadata, dict):
        return None

    for key in (
        "trigger_word",
        "activation_text",
        "ss_trigger_words",
        "trained_words",
        "modelspec.trigger_word",
    ):
        value = metadata.get(key)
        trigger = _clean_trigger(str(value) if value is not None else "")
        if trigger:
            return trigger

    tag_freq = metadata.get("ss_tag_frequency")
    if tag_freq:
        trigger = _trigger_from_tag_frequency(str(tag_freq))
        if trigger:
            return trigger

    return None


def _trigger_from_tag_frequency(raw: str) -> Optional[str]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return _trigger_from_free_text(raw)
    if not isinstance(data, dict) or not data:
        return None

    ranked: List[Tuple[int, str]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            for tag, count in value.items():
                ranked.extend(_rank_tag_candidate(str(tag), count))
        else:
            ranked.extend(_rank_tag_candidate(str(key), value))

    if not ranked:
        return None
    ranked.sort(key=lambda row: (-row[0], _tag_preference_score(row[1]), len(row[1])))
    return ranked[0][1]


def _rank_tag_candidate(tag: str, count: Any) -> List[Tuple[int, str]]:
    text = _clean_trigger(tag)
    if not text or text.lower() in _GENERIC_TAGS:
        return []
    if not _tag_looks_like_trigger(text):
        return []
    try:
        weight = int(count)
    except (TypeError, ValueError):
        weight = 0
    return [(weight, text)]


def _tag_looks_like_trigger(text: str) -> bool:
    if len(text) > 64:
        return False
    words = text.split()
    if len(words) > 6:
        return False
    lowered = text.lower()
    if lowered.startswith(("a ", "an ", "the ")):
        return False
    return True


def _tag_preference_score(text: str) -> int:
    """Lower is better: prefer short style-like tags over long captions."""
    words = text.split()
    if len(words) <= 3:
        return 0
    if len(words) <= 5:
        return 1
    return 2


def _trigger_from_filename(stem: str) -> Optional[str]:
    text = str(stem or "").strip()
    if not text:
        return None
    text = text.replace("-", " ").replace("_", " ")
    while True:
        cleaned = _FILENAME_NOISE_RE.sub("", text).strip()
        if cleaned == text:
            break
        text = cleaned
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < 3:
        return None
    if text.lower() in _GENERIC_TAGS:
        return None
    return text


def _trigger_from_free_text(raw: str) -> Optional[str]:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed:
            return _trigger_from_tag_frequency(text)
    # First comma-separated token chunk or first line.
    line = text.splitlines()[0].strip()
    for part in re.split(r"[,;|]", line):
        candidate = _clean_trigger(part)
        if candidate and candidate.lower() not in _GENERIC_TAGS:
            return candidate
    return None


def _trigger_from_online(
    entry: FluxLoraEntry,
    *,
    path: Optional[Path],
    timeout_s: float,
) -> Optional[str]:
    from imagegen_plugins.lora_origin_lookup import lookup_lora_origin

    try:
        match = lookup_lora_origin(entry, timeout_s=timeout_s)
        if match is not None and match.trigger_word:
            return _clean_trigger(match.trigger_word)
    except Exception:
        pass

    repo_id = (entry.repo_id or "").strip()
    if repo_id:
        trigger = _trigger_from_hf_readme(repo_id, timeout_s=timeout_s)
        if trigger:
            return trigger

    if path is not None:
        try:
            stub = FluxLoraEntry(
                host_id=entry.host_id,
                lora_id=entry.lora_id,
                display_name=entry.display_name,
                local_path=str(path),
                base_hf_model_id=entry.base_hf_model_id,
            )
            match = lookup_lora_origin(stub, timeout_s=timeout_s)
            if match is not None and match.trigger_word:
                return _clean_trigger(match.trigger_word)
        except Exception:
            pass
    return None


def _trigger_from_hf_readme(repo_id: str, *, timeout_s: float) -> Optional[str]:
    import urllib.error
    import urllib.request

    url = f"https://huggingface.co/{repo_id}/raw/main/README.md"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Prowser/1.0 (+LoRA trigger lookup)", "Accept": "text/plain"},
    )
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout_s)) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    for match in _TRIGGER_LINE_RE.finditer(text):
        candidate = _clean_trigger(match.group(1))
        if candidate:
            return candidate
    return None


def _clean_trigger(text: str) -> Optional[str]:
    value = str(text or "").strip().strip("\"'`")
    value = re.sub(r"\s+", " ", value)
    if not value or value.lower() in {"none", "n/a", "null"}:
        return None
    if len(value) > 120:
        value = value[:120].strip()
    return value or None
