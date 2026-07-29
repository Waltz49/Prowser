#!/usr/bin/env python3
"""Best-effort lookup of LoRA reinstall metadata (Civitai, Hugging Face, URLs)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from imagegen_plugins.lora_entry import FluxLoraEntry

_CIVITAI_API = "https://civitai.com/api/v1"
_CIVIT_HOSTS = ("civitai.com", "civit.red", "www.civitai.com", "www.civit.red")
_HF_HOSTS = ("huggingface.co", "hf.co", "www.huggingface.co")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_CIVIT_MODEL_RE = re.compile(
    r"https?://(?:www\.)?(?:civitai\.com|civit\.red)/models/(\d+)",
    re.IGNORECASE,
)
_CIVIT_DOWNLOAD_RE = re.compile(
    r"https?://(?:www\.)?(?:civitai\.com|civit\.red)/api/download/models/(\d+)",
    re.IGNORECASE,
)
_HF_RESOLVE_RE = re.compile(
    r"https?://(?:www\.)?(?:huggingface\.co|hf\.co)/([^/]+/[^/]+)/(?:resolve|blob)/[^/]+/(.+)",
    re.IGNORECASE,
)
_USER_AGENT = "Prowser/1.0 (+local LoRA origin lookup)"


@dataclass(frozen=True)
class LoraOriginMatch:
  """Candidate reinstall metadata discovered online."""

  source_kind: str  # huggingface | civitai | url
  confidence: str  # high | medium | low
  repo_id: str = ""
  filename: str = ""
  download_url: str = ""
  page_url: str = ""
  trigger_word: Optional[str] = None
  display_name: Optional[str] = None
  note: str = ""


def entry_needs_origin_lookup(entry: FluxLoraEntry) -> bool:
  """True when we lack online reinstall metadata (HF repo or remote download URL)."""
  if (entry.repo_id or "").strip() and (entry.filename or "").strip():
    return False
  source = (entry.source_path or "").strip().lower()
  if source.startswith(("http://", "https://")):
    if (
      "civitai.com" in source
      or "civit.red" in source
      or "huggingface.co" in source
      or "hf.co" in source
    ):
      return False
  return True


def lookup_lora_origin(
  entry: FluxLoraEntry,
  *,
  timeout_s: float = 6.0,
) -> Optional[LoraOriginMatch]:
  """Try a few bounded strategies to find reinstall metadata for a LoRA."""
  hints = _text_hints(entry)
  for match in _matches_from_urls(hints):
    return match

  weights = _weights_path(entry)
  if weights is not None and weights.is_file():
    match = _lookup_civitai_by_hash(weights, timeout_s=timeout_s)
    if match is not None:
      return match
    stem = weights.stem.strip()
    if stem:
      match = _lookup_civitai_by_name(stem, weights.name, timeout_s=timeout_s)
      if match is not None:
        return match
      match = _lookup_huggingface_by_name(stem, weights.name, timeout_s=timeout_s)
      if match is not None:
        return match
  return None


def origin_match_to_metadata(match: LoraOriginMatch) -> Dict[str, str]:
  """Map a lookup result to user_entries metadata fields."""
  out: Dict[str, str] = {}
  if match.repo_id and match.filename:
    out["repo_id"] = match.repo_id
    out["filename"] = match.filename
  if match.download_url:
    out["source_path"] = match.download_url
  elif match.page_url:
    out["source_path"] = match.page_url
  return out


def _text_hints(entry: FluxLoraEntry) -> str:
  parts = [
    entry.source_path or "",
    entry.comment or "",
    entry.local_path or "",
    entry.display_name or "",
  ]
  return "\n".join(p for p in parts if p)


def _weights_path(entry: FluxLoraEntry) -> Optional[Path]:
  for raw in (entry.local_path, entry.source_path):
    text = str(raw or "").strip()
    if not text or text.lower().startswith(("http://", "https://")):
      continue
    path = Path(text).expanduser()
    if path.is_file() and path.suffix.lower() == ".safetensors":
      return path
  return None


def _matches_from_urls(text: str) -> Iterable[LoraOriginMatch]:
  for url in _URL_RE.findall(text or ""):
    parsed = urllib.parse.urlparse(url)
    host = (parsed.netloc or "").lower()
    if any(host.endswith(h) for h in _HF_HOSTS):
      match = _match_huggingface_url(url)
      if match is not None:
        yield match
    if any(host.endswith(h) for h in _CIVIT_HOSTS):
      match = _match_civitai_url(url)
      if match is not None:
        yield match


def _match_huggingface_url(url: str) -> Optional[LoraOriginMatch]:
  m = _HF_RESOLVE_RE.search(url)
  if m:
    repo_id = m.group(1).strip()
    filename = urllib.parse.unquote(m.group(2).strip())
    if repo_id and filename.endswith(".safetensors"):
      return LoraOriginMatch(
        source_kind="huggingface",
        confidence="high",
        repo_id=repo_id,
        filename=filename,
        page_url=url.split("/resolve/")[0] if "/resolve/" in url else url,
        note="Parsed Hugging Face URL",
      )
  parsed = urllib.parse.urlparse(url)
  parts = [p for p in parsed.path.split("/") if p]
  if len(parts) >= 2 and parts[0] not in ("models", "datasets", "spaces"):
    repo_id = f"{parts[0]}/{parts[1]}"
    tail = parts[2:]
    if tail and tail[-1].endswith(".safetensors"):
      filename = urllib.parse.unquote(tail[-1])
      return LoraOriginMatch(
        source_kind="huggingface",
        confidence="medium",
        repo_id=repo_id,
        filename=filename,
        page_url=url,
        note="Parsed Hugging Face repo link",
      )
  return None


def _match_civitai_url(url: str) -> Optional[LoraOriginMatch]:
  dm = _CIVIT_DOWNLOAD_RE.search(url)
  if dm:
    vid = dm.group(1)
    return LoraOriginMatch(
      source_kind="civitai",
      confidence="high",
      download_url=f"https://civitai.com/api/download/models/{vid}",
      page_url=url,
      note="Civitai download URL",
    )
  mm = _CIVIT_MODEL_RE.search(url)
  if mm:
    return LoraOriginMatch(
      source_kind="civitai",
      confidence="medium",
      page_url=url,
      note="Civitai model page (download URL not resolved)",
    )
  return None


def _lookup_civitai_by_hash(path: Path, *, timeout_s: float) -> Optional[LoraOriginMatch]:
  try:
    digest = _sha256_file(path)
  except OSError:
    return None
  data = _http_json(f"{_CIVITAI_API}/model-versions/by-hash/{digest}", timeout_s=timeout_s)
  if not isinstance(data, dict):
    return None
  return _civitai_version_to_match(data, confidence="high", note="Civitai file hash match")


def _lookup_civitai_by_name(
  stem: str,
  filename: str,
  *,
  timeout_s: float,
) -> Optional[LoraOriginMatch]:
  query = urllib.parse.quote(stem[:80])
  data = _http_json(
    f"{_CIVITAI_API}/models?types=LORA&limit=5&query={query}",
    timeout_s=timeout_s,
  )
  if not isinstance(data, dict):
    return None
  items = data.get("items")
  if not isinstance(items, list):
    return None
  for item in items:
    if not isinstance(item, dict):
      continue
    model_versions = item.get("modelVersions")
    if not isinstance(model_versions, list):
      continue
    for version in model_versions:
      if not isinstance(version, dict):
        continue
      files = version.get("files")
      if not isinstance(files, list):
        continue
      for file_info in files:
        if not isinstance(file_info, dict):
          continue
        name = str(file_info.get("name") or "")
        if name != filename:
          continue
        match = _civitai_version_to_match(
          version,
          confidence="medium",
          note="Civitai name search",
          model_name=str(item.get("name") or ""),
        )
        if match is not None:
          return match
  return None


def _civitai_version_to_match(
  version: Dict[str, Any],
  *,
  confidence: str,
  note: str,
  model_name: str = "",
) -> Optional[LoraOriginMatch]:
  vid = version.get("id")
  if vid is None:
    return None
  download_url = f"https://civitai.com/api/download/models/{vid}"
  trained = version.get("trainedWords")
  trigger = None
  if isinstance(trained, list) and trained:
    trigger = str(trained[0]).strip() or None
  files = version.get("files")
  filename = ""
  if isinstance(files, list):
    for file_info in files:
      if isinstance(file_info, dict) and file_info.get("primary"):
        filename = str(file_info.get("name") or "")
        break
    if not filename:
      for file_info in files:
        if isinstance(file_info, dict):
          name = str(file_info.get("name") or "")
          if name.endswith(".safetensors"):
            filename = name
            break
  page_url = ""
  model_id = version.get("modelId")
  if model_id is not None:
    page_url = f"https://civitai.com/models/{model_id}"
  display = (model_name or str(version.get("name") or "")).strip() or None
  return LoraOriginMatch(
    source_kind="civitai",
    confidence=confidence,
    download_url=download_url,
    filename=filename,
    page_url=page_url,
    trigger_word=trigger,
    display_name=display,
    note=note,
  )


def _lookup_huggingface_by_name(
  stem: str,
  filename: str,
  *,
  timeout_s: float,
) -> Optional[LoraOriginMatch]:
  try:
    from huggingface_hub import HfApi
  except ImportError:
    return None
  api = HfApi()
  try:
    models = list(api.list_models(search=stem[:64], limit=6))
  except Exception:
    return None
  for model in models:
    repo_id = getattr(model, "id", None) or getattr(model, "modelId", None)
    if not repo_id:
      continue
    try:
      files = api.list_repo_files(str(repo_id), repo_type="model")
    except Exception:
      continue
    if filename not in files:
      continue
    if not any(f.endswith(".safetensors") for f in files if f == filename):
      continue
    return LoraOriginMatch(
      source_kind="huggingface",
      confidence="low",
      repo_id=str(repo_id),
      filename=filename,
      page_url=f"https://huggingface.co/{repo_id}",
      note="Hugging Face filename search",
    )
  return None


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
  h = hashlib.sha256()
  with path.open("rb") as f:
    while True:
      chunk = f.read(chunk_size)
      if not chunk:
        break
      h.update(chunk)
  return h.hexdigest()


def _http_json(url: str, *, timeout_s: float) -> Optional[Any]:
  req = urllib.request.Request(
    url,
    headers={
      "User-Agent": _USER_AGENT,
      "Accept": "application/json",
    },
  )
  token = (os.environ.get("CIVITAI_API_TOKEN") or os.environ.get("CIVITAI_TOKEN") or "").strip()
  if token and "civitai.com" in url:
    req.add_header("Authorization", f"Bearer {token}")
  try:
    with urllib.request.urlopen(req, timeout=max(1.0, timeout_s)) as resp:
      raw = resp.read()
  except (urllib.error.URLError, TimeoutError, OSError, ValueError):
    return None
  try:
    return json.loads(raw.decode("utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError):
    return None
