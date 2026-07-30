#!/usr/bin/env python3
"""Civitai API token resolution and authenticated downloads."""

from __future__ import annotations

import email.message
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

_CIVITAI_API = "https://civitai.com/api/v1"
_CIVIT_HOSTS = ("civitai.com", "civit.red", "www.civitai.com", "www.civit.red")
_CIVIT_DOWNLOAD_RE = re.compile(
    r"https?://(?:www\.)?(?:civitai\.com|civit\.red)/api/download/models/(\d+)",
    re.IGNORECASE,
)
_USER_AGENT = "Prowser/1.0"
_UNAUTHORIZED_HELP = (
    "Civitai returned 401 Unauthorized for this download. Many Civitai LoRAs require "
    "a Civitai API token (creator login requirement or NSFW content).\n\n"
    "Create a token at https://civitai.com/user/account, then either:\n"
    "  • Set environment variable CIVITAI_API_TOKEN (or CIVITAI_TOKEN), or\n"
    "  • Add civitai_api_token under imagegen in your Prowser settings file.\n\n"
    "Restart the app after setting the token."
)


def is_civitai_url(url: str) -> bool:
    host = (urllib.parse.urlparse(str(url or "")).netloc or "").lower()
    return any(host.endswith(h) for h in _CIVIT_HOSTS)


def civitai_api_token() -> str:
    token = (
        os.environ.get("CIVITAI_API_TOKEN")
        or os.environ.get("CIVITAI_TOKEN")
        or ""
    ).strip()
    if token:
        return token
    try:
        from config import get_config

        settings = get_config().load_settings()
        imagegen = settings.get("imagegen")
        if isinstance(imagegen, dict):
            token = str(imagegen.get("civitai_api_token") or "").strip()
            if token:
                return token
    except Exception:
        pass
    return ""


def civitai_version_id_from_download_url(url: str) -> Optional[str]:
    match = _CIVIT_DOWNLOAD_RE.search(str(url or ""))
    return match.group(1) if match else None


def civitai_http_json(url: str, *, timeout_s: float = 6.0) -> Optional[Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": _USER_AGENT,
            "Accept": "application/json",
        },
    )
    token = civitai_api_token()
    if token and is_civitai_url(url):
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


def civitai_primary_filename(version_id: str) -> str:
    data = civitai_http_json(f"{_CIVITAI_API}/model-versions/{version_id}")
    if not isinstance(data, dict):
        return ""
    files = data.get("files")
    if not isinstance(files, list):
        return ""
    for file_info in files:
        if isinstance(file_info, dict) and file_info.get("primary"):
            return str(file_info.get("name") or "").strip()
    for file_info in files:
        if isinstance(file_info, dict):
            name = str(file_info.get("name") or "").strip()
            if name.endswith(".safetensors"):
                return name
    return ""


def _filename_from_content_disposition(value: str) -> str:
    msg = email.message.EmailMessage()
    msg["content-disposition"] = value
    filename = msg.get_param("filename", header="content-disposition")
    if filename:
        return str(filename).strip()
    filename_star = msg.get_param("filename*", header="content-disposition")
    if filename_star:
        return str(filename_star).strip()
    return ""


def download_url_to_path(
    url: str,
    dest: Path,
    *,
    filename_hint: str = "",
    timeout_s: float = 120.0,
) -> Path:
    """Download a remote URL to dest (streaming, follows Civitai redirects)."""
    url = str(url or "").strip()
    if not url:
        raise ValueError("Download URL is empty.")

    token = civitai_api_token()
    headers = {"User-Agent": _USER_AGENT}
    if token and is_civitai_url(url):
        headers["Authorization"] = f"Bearer {token}"

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=max(1.0, timeout_s)) as resp:
            final_name = (filename_hint or "").strip()
            if not final_name:
                cd = resp.headers.get("Content-Disposition") or ""
                if cd:
                    final_name = _filename_from_content_disposition(cd)
            if not final_name:
                tail = urllib.parse.urlparse(resp.url or url).path.rsplit("/", 1)[-1]
                if tail.endswith(".safetensors"):
                    final_name = tail
            if not final_name:
                version_id = civitai_version_id_from_download_url(url)
                if version_id:
                    final_name = civitai_primary_filename(version_id)
            if not final_name:
                final_name = dest.name if dest.name else "download.safetensors"
            if not final_name.endswith(".safetensors"):
                final_name = f"{final_name}.safetensors"

            out = dest.parent / final_name
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("wb") as handle:
                while True:
                    chunk = resp.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    except urllib.error.HTTPError as exc:
        if exc.code == 401 and is_civitai_url(url):
            raise ValueError(_UNAUTHORIZED_HELP) from exc
        raise ValueError(f"Download failed ({exc.code}): {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"Download failed: {exc.reason}") from exc

    if out.stat().st_size < 1024:
        try:
            out.unlink()
        except OSError:
            pass
        if is_civitai_url(url) and not token:
            raise ValueError(_UNAUTHORIZED_HELP)
        raise ValueError("Downloaded LoRA file is too small to be valid.")
    return out.resolve()
