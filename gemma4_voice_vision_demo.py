#!/usr/bin/env python3
"""
Voice + Vision Demo (Path 2: STT → LLM → TTS)

Standalone PySide6 demo. Hands-free voice chat with optional image drag-and-drop.
Uses LM Studio (OpenAI-compatible API) for local chat / vision LLMs, faster-whisper
for speech-to-text, and Piper for text-to-speech.

Prerequisites:
  - LM Studio installed (lms CLI on PATH or ~/.cache/lm-studio/bin/lms)
  - Local server on http://localhost:1234 (started from LM Studio or `lms server start`)
  - Gemma 4 E4B or 12B downloaded locally (`lms ls`); loaded on demand via `lms load`
  - Piper voice model(s) in ~/piper-voices/ (or set PIPER_VOICE env var)

Install (project venv):
  pip install PySide6 faster-whisper sounddevice openai numpy piper-tts
  pip install pocket-tts   # optional; enables pocket-tts engine in Settings

Run:
  python gemma4_voice_vision_demo.py

"""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import mimetypes
import queue
import re
import os
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from copy import deepcopy
from math import cos, pi, sin
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    print(
        "Missing sounddevice. Activate the project venv and install:\n"
        "  source venv_image_browser/bin/activate\n"
        "  pip install sounddevice",
        file=sys.stderr,
    )
    raise

from PySide6.QtCore import (
    Qt,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QBuffer,
    QByteArray,
    QIODevice,
    QSocketNotifier,
    QSize,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

try:
    from faster_whisper import WhisperModel
except ImportError:
    print("Missing faster-whisper. Run: pip install faster-whisper", file=sys.stderr)
    raise

try:
    from openai import OpenAI
except ImportError:
    print("Missing openai. Run: pip install openai", file=sys.stderr)
    raise

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LM_STUDIO_BASE = os.environ.get("LM_STUDIO_BASE", "http://localhost:1234/v1")
LMS_LOAD_TIMEOUT_SEC = int(os.environ.get("LMS_LOAD_TIMEOUT_SEC", "600"))
PIPER_VOICES_DIR = Path(
    os.environ.get("PIPER_VOICES_DIR", str(Path.home() / "piper-voices"))
)
PIPER_VOICE = os.environ.get(
    "PIPER_VOICE",
    str(PIPER_VOICES_DIR / "en_US-kristin-medium.onnx"),
)
TTS_ENGINE_PIPER = "piper"
TTS_ENGINE_POCKET = "pocket"
TTS_ENGINE_OPTIONS = (TTS_ENGINE_PIPER, TTS_ENGINE_POCKET)
POCKET_MAX_CHUNK_CHARS = 900
_FALLBACK_POCKET_VOICES = (
    "alba",
    "marius",
    "javert",
    "jean",
    "fantine",
    "cosette",
    "eponine",
    "azelma",
)
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "base.en")
WHISPER_MODEL_OPTIONS = ("tiny.en", "base.en", "small.en", "medium.en", "large-v3")

TRANSCRIPT_USER_LABEL_COLOR = "#b77217"
TRANSCRIPT_ASSISTANT_LABEL_COLOR = "#5AADAD"
STATUS_BAR_FRAME_STYLE = (
    "QFrame#voiceStatusBar { background-color: #1a1a1a; border-top: 1px solid #505050; }"
)
STATUS_LABEL_STYLE = "color: #ffffff; background: transparent; font-size: 13px;"
TOOLTIP_STYLE = (
    "QToolTip { background-color: #000000; color: #ffffff; border: 1px solid #444; padding: 4px; font-size: 16pt; }"
)

SAMPLE_RATE = 16_000
PIPER_SAMPLE_RATE = 22_050
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)
SPEECH_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", "0.012"))
DEFAULT_SILENCE_END_MS = int(os.environ.get("SILENCE_END_MS", "1200"))
SILENCE_END_MS_MIN = 400
SILENCE_END_MS_MAX = 5000
SILENCE_END_MS = DEFAULT_SILENCE_END_MS
MAX_RECORD_SEC = int(os.environ.get("MAX_RECORD_SEC", "30"))
DEFAULT_LLM_MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", "1024"))
LLM_MAX_TOKENS_MIN = 64
LLM_MAX_TOKENS_MAX = 8192
DEFAULT_LLM_TEMPERATURE = 0.7
LLM_TEMPERATURE_MIN = 0.0
LLM_TEMPERATURE_MAX = 3.0
LLM_TEMPERATURE_SLIDER_SCALE = 100
DEFAULT_TTS_SPEECH_SPEED = 1.0
TTS_SPEECH_SPEED_MIN = 0.5
TTS_SPEECH_SPEED_MAX = 2.0
TTS_SPEECH_SPEED_SLIDER_SCALE = 100
BEEP_SCRIPT = Path(os.environ.get("BEEP_SCRIPT", str(Path.home() / "bin" / "beep")))
BEEP_AUDIO_FALLBACK = Path(
    os.environ.get("BEEP_AUDIO", str(Path.home() / "Sites/roku/beephi.mp3"))
)
BEEP_PLAYBACK_RATE = float(os.environ.get("BEEP_PLAYBACK_RATE", "4"))
GEMMA4_THINKING_SKIP_PREFILL = "<|channel>thought\n<|channel|>"
GEMMA4_NO_THINK_SYSTEM = (
    "Thinking and planning are disabled. Reply with only the final spoken answer. "
    "Never output analysis, plans, numbered steps, or commentary about the user or these instructions."
)
GEMMA4_NO_THINK_APPEND = (
    "\n\nThinking is disabled. Reply with ONLY the final spoken answer — "
    "no planning, bullet points, or meta commentary."
)

# Legacy preset names (migrated from older demo_prompts.json).
MODEL_PRESETS = {
    "Gemma 4 E4B": {
        "hints": ("e4b", "gemma-4-e4b", "gemma_4_e4b"),
        "fallback": "google/gemma-4-e4b",
    },
    "Gemma 4 12B": {
        "hints": ("12b", "gemma-4-12b", "gemma_4_12b", "12b-unified"),
        "fallback": "google/gemma-4-12b",
    },
}
DEFAULT_MODEL_KEY = "google/gemma-4-e4b"

_DEMO_EXCLUDED_KINDS = frozenset({"LoRA", "Embedding", "Vision", "Audio"})
_DEMO_EXCLUDED_FRAGMENTS = (
    "lora",
    "adapter",
    "embed",
    "whisper",
    "mmproj",
    "controlnet",
    "flux",
    "sdxl",
    "stable-diffusion",
    "vae",
    "diffusion",
    "unet",
    "tts",
    "speech",
)
_VISION_NAME_HINTS = (
    "gemma-4",
    "gemma_4",
    "llava",
    "qwen2-vl",
    "qwen-vl",
    "qwen3-vl",
    "minicpm-v",
    "phi-3-v",
    "phi3-v",
    "bakllava",
    "moondream",
    "pixtral",
    "vl-",
    "-vl",
    "vision",
    "vlm",
)


@dataclass(frozen=True)
class DemoChatModel:
    model_key: str
    label: str
    supports_vision: bool
    quant: str = ""

DEMO_PROMPTS_PATH = Path.home() / "demo_prompts.json"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
VISION_ICON_HEIGHT = 16
VISION_ICON_GAP = 6
_VISION_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAB4AAAAQCAYAAAABOs/SAAAEAUlEQVR4nLVVX0xbZRT/nXtvyy3gaNmC5f+aGZxI"
    "Fo2a+CcL82HLssdlncsE7t1MwKnxYS8++ECI2auGLVrEIBR0M3szJm5GI2yLcW4QmRpkM4PZUtqyQCcr0Pbe9pj7"
    "UaAdXTQxnuTmfve75/x+5993PmKGhMDRMthsH8JVtBOxVAaAhIcJQ4bECiwtZDUzZIKQfqgNkIHLLmEhOY6q8h6"
    "iD64RL7SXYSXRA1nuI3f/d/gfhWeOP42t6hVI6W4FSaMbkvQJufu/Z/baAaQxMkdCc08FA40ETDBGGole7jJ5Rns"
    "KlcUnEVkxhY7boSC8/D7V+Md5uFPBnokcm1wcyESf/sw3vC+g3vkj8az+G1UNNPGt/UXUcDGZ5yGDiGAZgblTQTT"
    "wEyRsh1Mth5nNtSIB9xILSOMO3LbniXqNB23X8b7eX0QHLiZ5RrskQUKc2SsjtJJXI8sQQa8q1rHXBoG7BhySC2k"
    "Mkd1HVPzx6mP3WdUdQrFcjpSU4vnjZ1YRtCKBkSuOlbTgkqUScFi/LsCHm5U84tF2m3inTvTxUvsdnmnrXf83cbi"
    "Jk6+3crKjjSeP7FrfD2rfML/DHDnWl4ux/j/LYXHmkeWnuNfgoDaAZPoAbsWfo2fO/sncbsPNxSdQu+UK7MVbrBZ"
    "HHUf5dts+2jH4C1T5EBKLh8B8igPaENX1thZKOQodG8tLS5FDWg9qnBoWVr4UpNOaimCiAo9tu4yUcRp/RJ9EYP4V"
    "MMrgso1wuMWDbX1xcvj6wXwZta4WDuk+gTWaH3lB4hxRsRAH7ifeE1/blw1QmkDSfZj2v6jh8wmqHzwPQz6DRxw"
    "MQ0phrGM1g+amADfJplTTs73Ganr8Ooc0oN71K48d3AU0hlDTFcJ060l4POd5Vq+G066A5Fdxe/5FPN5wF7VgHjt"
    "YD5fajGDMT3X+E2tlw7+JWKSH221U7ddhl8+hqfoSfp8qE7UqxQ2koxpAASgUxFR4N+08N0nUlcLUza1Ct0j+iur8"
    "+lrZCnGAI/pVq8U3dTWDOOB1iPW9jgE23gxz+NiFghgxzckh/QKbb01aumIv4HU8eJx4uFkRXBH96sYACbeUwF2cyk"
    "3LqmGnTNRlclQ/C9W2GwrVQMriWbHYJCCWCCDNc3A79hH5YpYVZ/K7ma0TEVm2U+VnSxanAqJRjuh7yT3w7ZpXGz5"
    "WMEZGxNQi6jrK43tLsMPjw2IigwxZZTLFyDQz3VTlH2OvVxYDIjsyeTg7MmGVTwRkWFxgGiWe1pxQcQru0gqEl8JU"
    "NfB2wZr8R+FZ/TQqSyoRic8hgXeFRxx9oxQV9BLCS19AVaaRMFi02Gax2s66SDbkH69FZqg2QsL0oLLkCOb4B3r0"
    "o/jflUnwvUvwxZkAAAAASUVORK5CYII="
)
_VISION_PIXMAP: QPixmap | None = None
ICON_BTN_SIZE = 22
ICON_DRAW_SIZE = 16
_ICON_BTN_STYLE = "QPushButton { border: none; background: transparent; }"
_QMARK_PNG_BYTES = (ASSETS_DIR / "qmark.png").read_bytes()
_QMARK_ICON_DATA_URL = (
    "data:image/png;base64," + base64.standard_b64encode(_QMARK_PNG_BYTES).decode("ascii")
)
VOICE_COMMANDS_TOOLTIP = (
    "Say only that word:\n"
    "redo - repanswer last question\n"
    "clear - wipe chat\n"
    "copy - last reply to clipboard\n"
    "undo - remove last turn\n"
    "stop - end hands-free"
)

DEFAULT_PROMPT_SUGGESTION = (
    "You are a helpful voice assistant in a hands-free demo. "
    "Reply with only the final spoken answer — no analysis, bullet points, or planning. "
    "Keep replies concise: one or two short paragraphs at most. "
    "If the user shares an image, describe or answer questions about it clearly."
)

SYSTEM_DEFAULT_ID = "__system_default__"


def _icon_pixmap(draw: Callable[[QPainter, int], None], size: int = ICON_DRAW_SIZE) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(painter, size)
    painter.end()
    return pix


def _brighten_pixmap(pix: QPixmap, factor: float = 1.45) -> QPixmap:
    img = pix.toImage()
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.alpha() == 0:
                continue
            c.setRed(min(255, int(c.red() * factor)))
            c.setGreen(min(255, int(c.green() * factor)))
            c.setBlue(min(255, int(c.blue() * factor)))
            img.setPixelColor(x, y, c)
    return QPixmap.fromImage(img)


def _draw_stop_sign_icon(painter: QPainter, size: int) -> None:
    cx, cy = size / 2, size / 2
    radius = size / 2 - 0.5
    points = [
        QPointF(cx + radius * cos(pi / 8 + i * pi / 4), cy + radius * sin(pi / 8 + i * pi / 4))
        for i in range(8)
    ]
    painter.setPen(QPen(QColor("#8B0000"), 0.8))
    painter.setBrush(QColor("#E41C1C"))
    painter.drawPolygon(QPolygonF(points))


def _draw_prohibited_icon(painter: QPainter, size: int) -> None:
    margin = 1.5
    painter.setPen(QPen(QColor("#CC0000"), 1.6))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
    painter.drawLine(
        QPointF(margin + 1.5, size - margin - 1.5),
        QPointF(size - margin - 1.5, margin + 1.5),
    )


def _draw_clear_chat_icon(painter: QPainter, size: int) -> None:
    margin = 2.0
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#00FFFF"))
    painter.drawRect(QRectF(margin, margin, size - 2 * margin, size - 2 * margin))
    inner_margin = 4.5
    painter.setBrush(QColor("#000000"))
    painter.drawRect(
        QRectF(
            inner_margin,
            inner_margin,
            size - 2 * inner_margin,
            size - 2 * inner_margin,
        )
    )


def _draw_curved_arrow_icon(painter: QPainter, size: int, *, redo: bool) -> None:
    pen = QPen(QColor("#D0D0D0"), 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    rect = QRectF(2.5, 2.5, size - 5, size - 5)
    path = QPainterPath()
    if redo:
        path.arcMoveTo(rect, 130)
        path.arcTo(rect, 130, -260)
        painter.drawPath(path)
        painter.drawLine(QPointF(4.5, 7.5), QPointF(7.5, 5.0))
        painter.drawLine(QPointF(4.5, 7.5), QPointF(7.0, 9.5))
    else:
        path.arcMoveTo(rect, 50)
        path.arcTo(rect, 50, 260)
        painter.drawPath(path)
        painter.drawLine(QPointF(11.5, 7.5), QPointF(8.5, 5.0))
        painter.drawLine(QPointF(11.5, 7.5), QPointF(9.0, 9.5))


class IconToolButton(QPushButton):
    _TOOLTIP_DELAY_MS = 100

    def __init__(
        self,
        tooltip: str,
        pixmap: QPixmap,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tooltip_text = tooltip
        self._normal_pix = pixmap
        self._hover_pix = _brighten_pixmap(pixmap)
        self.setFlat(True)
        self.setFixedSize(ICON_BTN_SIZE, ICON_BTN_SIZE)
        self.setIconSize(QSize(ICON_DRAW_SIZE, ICON_DRAW_SIZE))
        self.setIcon(QIcon(self._normal_pix))
        self.setStyleSheet(_ICON_BTN_STYLE)
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.setInterval(self._TOOLTIP_DELAY_MS)
        self._tooltip_timer.timeout.connect(self._show_tooltip)

    def enterEvent(self, event) -> None:
        self.setIcon(QIcon(self._hover_pix))
        self._tooltip_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setIcon(QIcon(self._normal_pix))
        self._tooltip_timer.stop()
        QToolTip.hideText()
        super().leaveEvent(event)

    def _show_tooltip(self) -> None:
        if not self._tooltip_text:
            return
        QToolTip.showText(
            self.mapToGlobal(QPoint(self.width() // 2, self.height())),
            self._tooltip_text,
            self,
        )


def _make_icon_tool_button(
    tooltip: str,
    pixmap: QPixmap,
    on_click: Callable[[], None] | None = None,
    parent: QWidget | None = None,
) -> IconToolButton:
    btn = IconToolButton(tooltip, pixmap, parent)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


class SymbolToolButton(QPushButton):
    _TOOLTIP_DELAY_MS = 100
    _NORMAL_COLOR = "#D0D0D0"
    _HOVER_COLOR = "#FFFFFF"

    def __init__(
        self,
        tooltip: str,
        symbol: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(symbol, parent)
        self._tooltip_text = tooltip
        self.setFlat(True)
        self.setFixedSize(ICON_BTN_SIZE, ICON_BTN_SIZE)
        self.setStyleSheet(
            _ICON_BTN_STYLE
            + f" QPushButton {{ font-size: 14px; color: {self._NORMAL_COLOR}; }}"
        )
        self._tooltip_timer = QTimer(self)
        self._tooltip_timer.setSingleShot(True)
        self._tooltip_timer.setInterval(self._TOOLTIP_DELAY_MS)
        self._tooltip_timer.timeout.connect(self._show_tooltip)

    def enterEvent(self, event) -> None:
        self.setStyleSheet(
            _ICON_BTN_STYLE
            + f" QPushButton {{ font-size: 14px; color: {self._HOVER_COLOR}; }}"
        )
        self._tooltip_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setStyleSheet(
            _ICON_BTN_STYLE
            + f" QPushButton {{ font-size: 14px; color: {self._NORMAL_COLOR}; }}"
        )
        self._tooltip_timer.stop()
        QToolTip.hideText()
        super().leaveEvent(event)

    def _show_tooltip(self) -> None:
        if not self._tooltip_text:
            return
        QToolTip.showText(
            self.mapToGlobal(QPoint(self.width() // 2, self.height())),
            self._tooltip_text,
            self,
        )


def _make_symbol_tool_button(
    tooltip: str,
    symbol: str,
    on_click: Callable[[], None] | None = None,
    parent: QWidget | None = None,
) -> SymbolToolButton:
    btn = SymbolToolButton(tooltip, symbol, parent)
    if on_click is not None:
        btn.clicked.connect(on_click)
    return btn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rms(chunk: np.ndarray) -> float:
    if chunk.size == 0:
        return 0.0
    samples = chunk.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples * samples)))


def list_input_devices() -> list[tuple[int | None, str]]:
    """Return (device_index, label) pairs for audio inputs. None = system default."""
    items: list[tuple[int | None, str]] = [(None, "System default")]
    try:
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev.get("max_input_channels", 0)) > 0:
                items.append((idx, str(dev.get("name", f"Device {idx}"))))
    except Exception:
        pass
    return items


def input_device_label(device: int | None) -> str:
    for idx, name in list_input_devices():
        if idx == device:
            return name
    return "System default"


def default_piper_voice_path() -> str:
    return PIPER_VOICE


def list_piper_voices() -> list[tuple[str, str]]:
    """Return (absolute .onnx path, display label) pairs for Piper TTS voices."""
    voices: list[tuple[str, str]] = []
    seen: set[str] = set()
    if PIPER_VOICES_DIR.is_dir():
        for path in sorted(PIPER_VOICES_DIR.rglob("*.onnx")):
            resolved = str(path.resolve())
            if resolved in seen:
                continue
            seen.add(resolved)
            if path.parent == PIPER_VOICES_DIR:
                label = path.stem
            else:
                label = f"{path.parent.name}/{path.stem}"
            voices.append((resolved, label))
    default = str(Path(default_piper_voice_path()).expanduser().resolve())
    if default not in seen and Path(default).is_file():
        voices.append((default, Path(default).stem))
        voices.sort(key=lambda item: item[1].lower())
    return voices


def resolve_piper_voice(path: str) -> str:
    """Return a usable Piper .onnx path, falling back when needed."""
    candidate = str(Path(path).expanduser())
    if candidate and Path(candidate).is_file():
        return str(Path(candidate).resolve())
    default = str(Path(default_piper_voice_path()).expanduser())
    if default and Path(default).is_file():
        return str(Path(default).resolve())
    voices = list_piper_voices()
    if voices:
        return voices[0][0]
    return candidate or default


def piper_voice_label(path: str) -> str:
    resolved = str(Path(path).expanduser().resolve())
    for voice_path, label in list_piper_voices():
        if voice_path == resolved:
            return label
    return Path(path).stem


def list_pocket_voices() -> list[tuple[str, str]]:
    """Return (voice_id, display_label) for built-in pocket-tts voices (discovered at runtime)."""
    try:
        from pocket_tts.utils.utils import PREDEFINED_VOICES

        return [(name, name) for name in sorted(PREDEFINED_VOICES)]
    except Exception:
        return [(name, name) for name in _FALLBACK_POCKET_VOICES]


def default_pocket_voice() -> str:
    voices = list_pocket_voices()
    return voices[0][0] if voices else "alba"


def resolve_pocket_voice(name: str) -> str:
    needle = name.strip().lower()
    for voice_id, _ in list_pocket_voices():
        if voice_id.lower() == needle:
            return voice_id
    return default_pocket_voice()


def pocket_voice_label(name: str) -> str:
    resolved = resolve_pocket_voice(name)
    for voice_id, label in list_pocket_voices():
        if voice_id == resolved:
            return label
    return name.strip() or resolved


def tts_settings_label(engine: str, piper_voice: str, pocket_voice: str) -> str:
    if engine == TTS_ENGINE_POCKET:
        return f"pocket-tts/{pocket_voice_label(pocket_voice)}"
    return f"piper/{piper_voice_label(piper_voice)}"


def _transcript_role_label(role: str) -> str:
    color = (
        TRANSCRIPT_USER_LABEL_COLOR
        if role == "You"
        else TRANSCRIPT_ASSISTANT_LABEL_COLOR
    )
    return f"<span style='color:{color}'><b>{role}:</b></span>"


@dataclass
class RecordResult:
    pcm: np.ndarray | None
    peak_rms: float = 0.0
    threshold: float = SPEECH_THRESHOLD
    error: str | None = None


def _is_gemma4_model(model_id: str) -> bool:
    low = model_id.lower()
    return "gemma-4" in low or "gemma_4" in low


def _clean_gemma_output_text(text: str) -> str:
    cleaned = text.strip()
    for tag in ("<|channel>thought", "<|/channel|>", "<|channel|>", "<|think|>"):
        cleaned = cleaned.replace(tag, "")
    if cleaned.lower().startswith("thought\n"):
        cleaned = cleaned[7:]
    return cleaned.strip()


def _normalize_gemma_content(text: str) -> str:
    """Keep the post-channel segment; Gemma sometimes prefixes stale assistant text."""
    text = text.strip()
    if "<|/channel|>" in text:
        text = text.split("<|/channel|>")[-1].strip()
    if "<|channel|>" in text:
        text = text.split("<|channel|>")[-1].strip()
    return _clean_gemma_output_text(text)


def _looks_like_planning(text: str) -> bool:
    markers = (
        "*draft",
        "internal monologue",
        "refining for",
        "option 1",
        "user asks:",
        "user is asking",
        "the user is asking",
        "the user has",
        "constraint:",
        "constraint checklist",
        "thinking process",
        "analyze the request",
        "determine persona",
        "final polish",
        "draft response",
        "format:",
        "\nplan:",
        "i should ",
    )
    low = text.lower()
    if any(marker in low for marker in markers):
        return True
    return text.count("\n    *") >= 2 or text.count("\n*   ") >= 2


def _line_is_meta_planning(line: str) -> bool:
    if re.match(r"^\d+\.\s", line):
        return True
    low = line.lower()
    meta_fragments = (
        "the user has",
        "the user is",
        "the user asks",
        "user has sent",
        "i should ",
        "plan:",
        "keep it very short",
        "acknowledge the",
        "state that i",
        "prompt the user",
    )
    return any(frag in low for frag in meta_fragments)


def _extract_after_plan_block(text: str) -> str:
    """Take speakable text after a Gemma 'Plan:' numbered list."""
    match = re.search(
        r"(?is)\bplan:\s*\n((?:\s*\d+\.\s+[^\n]+\n?)+)(.*)",
        text,
    )
    if match:
        tail = match.group(2).strip()
        if len(tail) > 15:
            return tail
    return ""


def _extract_after_thinking_process(text: str, user_text: str = "") -> str:
    """Strip Gemma 'Thinking Process:' numbered analysis before the spoken answer."""
    low = text.lower()
    if "thinking process" not in low and not re.search(r"(?m)^\d+\.\s+\*+", text):
        return ""

    # Gemma markdown headers are often asymmetric (*Final Polish:**).
    step_headers = (
        "final polish",
        "draft response",
        "spoken answer",
        "final answer",
    )
    for header in step_headers:
        match = re.search(
            rf"(?is)\*+{re.escape(header)}[^.\n]*\**:?\s*[^.]*\.(.+)$",
            text,
        )
        if match:
            candidate = match.group(1).strip()
            if len(candidate) > 15 and not _echoes_user_text(candidate, user_text):
                return candidate

    glued = _extract_glued_answer_tail(text, user_text=user_text)
    if glued:
        return glued
    return ""


def _is_speakable_segment(text: str) -> bool:
    t = text.strip()
    if len(t) < 15:
        return False
    if _looks_like_planning(t):
        return False
    first_line = t.split("\n", 1)[0]
    if _line_is_meta_planning(first_line) or re.match(r"^\d+\.\s", first_line):
        return False
    return True


def _extract_glued_answer_tail(text: str, user_text: str = "") -> str:
    """Answer glued after planning with no blank line (e.g. '...punchy.Ugh, literally...')."""
    tail_region = text[max(0, len(text) // 4) :]
    for match in reversed(list(re.finditer(r"\.([A-Z][^\n]{15,})", tail_region))):
        candidate = tail_region[match.start(1) :].strip()
        if not _is_speakable_segment(candidate):
            continue
        if not _echoes_user_text(candidate, user_text):
            return candidate
    return ""


def _extract_trailing_non_planning_lines(text: str, user_text: str = "") -> str:
    """Take contiguous non-planning lines from the end of a mixed block."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    collected: list[str] = []
    for line in reversed(lines):
        if _line_is_meta_planning(line):
            break
        if re.match(r"^\d+\.\s", line):
            glued = _extract_glued_answer_tail(line, user_text=user_text)
            if glued:
                collected.append(glued)
            break
        collected.append(line)
    if not collected:
        return ""
    candidate = "\n".join(reversed(collected)).strip()
    if _is_speakable_segment(candidate) and not _echoes_user_text(candidate, user_text):
        return candidate
    return ""


def _echoes_user_text(candidate: str, user_text: str) -> bool:
    if not user_text:
        return False
    return candidate.strip().lower() == user_text.strip().lower()


def _is_channel_artifact(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped == GEMMA4_THINKING_SKIP_PREFILL.strip():
        return True
    return "<|channel" in stripped or stripped in {"thought", "thought\n"}


def _is_garbage_assistant_history(text: str) -> bool:
    """Skip polluted assistant turns when building chat history."""
    if _is_channel_artifact(text) or _looks_like_planning(text):
        return True
    t = text.strip()
    if len(t) < 20:
        return True
    # Lowercase fragment echoes (e.g. "when the American Revolution began.")
    if (
        t[0].islower()
        and t.endswith(".")
        and t.count(".") == 1
        and len(t) < 80
        and not _looks_like_answer_paragraph(t)
    ):
        return True
    return False


def _looks_like_answer_paragraph(text: str) -> bool:
    return len(text.strip()) >= 40 and _is_speakable_segment(text)


def _extract_speakable_reply(text: str, user_text: str = "") -> str:
    """Strip Gemma planning/meta preamble and return only the spoken answer."""
    text = _normalize_gemma_content(text)
    if not text or _is_channel_artifact(text):
        return ""

    if not _looks_like_planning(text):
        if not _echoes_user_text(text, user_text):
            return text
        return ""

    after_plan = _extract_after_plan_block(text)
    if after_plan and not _looks_like_planning(after_plan) and not _echoes_user_text(after_plan, user_text):
        return after_plan

    after_thinking = _extract_after_thinking_process(text, user_text=user_text)
    if after_thinking:
        return after_thinking

    glued = _extract_glued_answer_tail(text, user_text=user_text)
    if glued:
        return glued

    trailing = _extract_trailing_non_planning_lines(text, user_text=user_text)
    if trailing:
        return trailing

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    answer_paras = [
        para
        for para in paragraphs
        if _looks_like_answer_paragraph(para) and not _echoes_user_text(para, user_text)
    ]
    if answer_paras:
        return "\n\n".join(answer_paras)

    for para in reversed(paragraphs):
        if _looks_like_planning(para) or _line_is_meta_planning(para):
            continue
        if len(para) > 50 and not _echoes_user_text(para, user_text):
            return para

    quotes = re.findall(r'"([^"]{50,})"', text)
    for candidate in reversed(quotes):
        candidate = candidate.strip()
        if not _line_is_meta_planning(candidate) and not _echoes_user_text(candidate, user_text):
            return candidate

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in reversed(lines):
        if _line_is_meta_planning(line):
            continue
        if len(line) > 40 and not line.endswith(":") and not _echoes_user_text(line, user_text):
            return line

    return ""


def _extract_assistant_reply(choice: Any, user_text: str = "") -> str:
    msg = choice.message
    msg_dict = msg.model_dump() if hasattr(msg, "model_dump") else {}
    content = str(msg_dict.get("content") or getattr(msg, "content", None) or "")
    reasoning = str(msg_dict.get("reasoning_content") or getattr(msg, "reasoning_content", None) or "")

    for raw in (content, reasoning):
        speakable = _extract_speakable_reply(raw, user_text=user_text)
        if speakable and not _is_channel_artifact(speakable):
            return speakable
    return ""


def _gemma_disable_thinking_extra_body() -> dict[str, Any]:
    """LM Studio may honor one or both of these; harmless if ignored."""
    return {
        "chat_template_kwargs": {"enable_thinking": False},
        "enable_thinking": False,
    }


def _prepare_gemma_api_messages(
    messages: list[dict[str, Any]],
    model_id: str,
    *,
    disable_thinking: bool,
) -> list[dict[str, Any]]:
    if not _is_gemma4_model(model_id) or not disable_thinking:
        return messages

    out: list[dict[str, Any]] = []
    system_added = False
    for msg in messages:
        if msg.get("role") == "system":
            content = str(msg.get("content") or "")
            if GEMMA4_NO_THINK_APPEND.strip() not in content:
                content = content + GEMMA4_NO_THINK_APPEND
            out.append({"role": "system", "content": content})
            system_added = True
        else:
            out.append(dict(msg))

    if not system_added:
        out.insert(0, {"role": "system", "content": GEMMA4_NO_THINK_SYSTEM})

    out.append({"role": "assistant", "content": GEMMA4_THINKING_SKIP_PREFILL})
    return out


_LMSTUDIO_PASSTHROUGH_IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


def _image_bytes_for_lmstudio(path: Path) -> tuple[str, bytes]:
    """Return (mime, raw_bytes) for LM Studio's vision API.

    LM Studio rejects WebP (and some other formats) in data URIs; decode via Qt
    and re-encode as PNG when needed.
    """
    path = path.expanduser()
    suffix = path.suffix.lower()
    if suffix in _LMSTUDIO_PASSTHROUGH_IMAGE_SUFFIXES:
        mime, _ = mimetypes.guess_type(str(path))
        mime = mime or ("image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png")
        return mime, path.read_bytes()

    image = QImage(str(path))
    if image.isNull():
        raise ValueError(f"Could not load image: {path}")
    buffer = QByteArray()
    io = QBuffer(buffer)
    io.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(io, "PNG"):
        raise ValueError(f"Could not encode image as PNG: {path}")
    return "image/png", bytes(buffer.data())


def encode_image_b64(path: Path) -> tuple[str, str]:
    mime, raw = _image_bytes_for_lmstudio(path)
    data = base64.standard_b64encode(raw).decode("ascii")
    return mime, data


def _image_path_key(path: Path | str | None) -> str | None:
    """Canonical path string for comparing/storing image attachments."""
    if not path:
        return None
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return str(path)


def _user_message_image_content(user_text: str, image_path: Path) -> list[dict[str, Any]]:
    """OpenAI-compatible multimodal user content (image first — Gemma/VLM convention)."""
    mime, b64 = encode_image_b64(image_path)
    return [
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
        {"type": "text", "text": user_text},
    ]


def _message_has_image_url(msg: dict[str, Any]) -> bool:
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(
        isinstance(part, dict) and part.get("type") == "image_url"
        for part in content
    )


def _find_last_user_message_index(messages: list[dict[str, Any]], user_text: str) -> int | None:
    for idx in range(len(messages) - 1, -1, -1):
        msg = messages[idx]
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if content == user_text:
            return idx
        if isinstance(content, list):
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "text"
                    and part.get("text") == user_text
                ):
                    return idx
    return None


def _messages_include_user_image(messages: list[dict[str, Any]]) -> bool:
    return any(
        msg.get("role") == "user" and _message_has_image_url(msg) for msg in messages
    )


def find_lms_cli() -> str:
    candidates = [
        os.environ.get("LMS_CLI"),
        shutil.which("lms"),
        str(Path.home() / ".cache/lm-studio/bin/lms"),
    ]
    for path in candidates:
        if path and Path(path).is_file():
            return path
    raise FileNotFoundError(
        "lms CLI not found. Install LM Studio or set LMS_CLI to the lms binary."
    )


def _lms_json(args: list[str], timeout: int = 60) -> Any:
    cli = find_lms_cli()
    cmd = [cli, *args, "--json"]
    result = subprocess.run(
        cmd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"lms {' '.join(args)} failed: {err}")
    return json.loads(result.stdout or "null")


def _heuristic_vision_capable(model_key: str) -> bool:
    low = model_key.lower()
    return any(hint in low for hint in _VISION_NAME_HINTS)


def _demo_model_eligible(model_key: str, kind: str = "LLM") -> bool:
    if not model_key.strip():
        return False
    if kind in _DEMO_EXCLUDED_KINDS:
        return False
    low = model_key.lower()
    return not any(fragment in low for fragment in _DEMO_EXCLUDED_FRAGMENTS)


def _model_keys_match(left: str, right: str) -> bool:
    a = left.strip().lower()
    b = right.strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    a_tail = a.split("/")[-1]
    b_tail = b.split("/")[-1]
    return a.endswith(b) or b.endswith(a) or a_tail == b_tail


def _format_quant_label(quant: Any) -> str:
    if isinstance(quant, dict):
        return str(quant.get("name") or quant.get("bits") or "").strip()
    return str(quant or "").strip()


def _demo_model_label(model_key: str, quant: Any = "") -> str:
    quant_text = _format_quant_label(quant)
    quant_bit = f" ({quant_text})" if quant_text else ""
    return f"{model_key}{quant_bit}"


def _vision_pixmap() -> QPixmap:
    global _VISION_PIXMAP
    if _VISION_PIXMAP is None:
        pixmap = QPixmap()
        pixmap.loadFromData(base64.standard_b64decode(_VISION_PNG_B64))
        if pixmap.isNull():
            _VISION_PIXMAP = QPixmap()
        else:
            _VISION_PIXMAP = pixmap.scaledToHeight(
                VISION_ICON_HEIGHT,
                Qt.TransformationMode.SmoothTransformation,
            )
    return _VISION_PIXMAP


def discover_demo_chat_models() -> list[DemoChatModel]:
    """List local LM Studio chat models suitable for this voice/vision demo."""
    seen: set[str] = set()
    models: list[DemoChatModel] = []

    try:
        entries = _lms_json(["ls", "--llm"])
    except Exception:
        entries = []

    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("modelKey") or entry.get("path") or "").strip()
            if not key or key in seen:
                continue
            kind = str(entry.get("type") or entry.get("kind") or "LLM")
            if not _demo_model_eligible(key, kind):
                continue
            quant = _format_quant_label(entry.get("quantization") or entry.get("quant"))
            seen.add(key)
            models.append(
                DemoChatModel(
                    model_key=key,
                    label=_demo_model_label(key, quant),
                    supports_vision=_heuristic_vision_capable(key),
                    quant=quant,
                )
            )

    # Only `lms ls --llm` keys are valid for `lms load`. Disk-scan IDs can differ and
    # cause `lms load` to open an interactive picker that hangs headless subprocesses.

    models.sort(key=lambda item: item.label.lower())
    return models


def resolve_default_model_key(models: list[DemoChatModel] | None = None) -> str:
    items = models if models is not None else discover_demo_chat_models()
    for item in items:
        low = item.model_key.lower()
        if "gemma-4-e4b" in low or "gemma_4_e4b" in low:
            return item.model_key
    if items:
        return items[0].model_key
    return DEFAULT_MODEL_KEY


def migrate_legacy_model_name(active_model: str) -> str:
    result = active_model
    if active_model in MODEL_PRESETS:
        hints = tuple(h.lower() for h in MODEL_PRESETS[active_model]["hints"])
        for item in discover_demo_chat_models():
            low = item.model_key.lower()
            if any(h in low for h in hints):
                result = item.model_key
                break
        else:
            result = MODEL_PRESETS[active_model]["fallback"]
    if result:
        with contextlib.suppress(Exception):
            result = resolve_lms_load_key(result)
    return result


def list_lms_llm_keys() -> list[str]:
    """Model keys known to `lms load` (`lms ls --llm`)."""
    try:
        entries = _lms_json(["ls", "--llm"])
    except Exception:
        return []
    keys: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict):
                key = str(entry.get("modelKey") or "").strip()
                if key:
                    keys.append(key)
    return keys


def resolve_lms_load_key(model_key: str) -> str:
    """Map a UI model key to a key accepted by `lms load`."""
    model_key = model_key.strip()
    if not model_key:
        raise ValueError("No LLM selected.")
    lms_keys = list_lms_llm_keys()
    if not lms_keys:
        raise RuntimeError("No LLM models reported by `lms ls --llm`.")
    for key in lms_keys:
        if _model_keys_match(key, model_key):
            return key
    target = model_key.lower().replace("_", "-")
    for key in lms_keys:
        key_low = key.lower()
        key_tail = key_low.split("/")[-1]
        if key_low in target or key_tail in target:
            return key
    raise RuntimeError(
        f"Model {model_key!r} is not registered with LM Studio. "
        "Pick a model from the LLM dropdown (Refresh if needed)."
    )


def get_loaded_model_entries() -> list[dict[str, Any]]:
    loaded = _lms_json(["ps"])
    return loaded if isinstance(loaded, list) else []


def find_loaded_model_key(
    model_key: str,
    loaded: list[dict[str, Any]] | None = None,
) -> str | None:
    for entry in loaded if loaded is not None else get_loaded_model_entries():
        for field in ("identifier", "modelKey"):
            value = str(entry.get(field) or "")
            if value and _model_keys_match(value, model_key):
                return str(entry.get("identifier") or entry.get("modelKey") or value)
    return None


def _run_cli_interruptible(
    cmd: list[str],
    *,
    stop_event: threading.Event | None = None,
    timeout_sec: float | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an lms CLI command; abort if stop_event is set."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + timeout_sec if timeout_sec is not None else None
    while proc.poll() is None:
        if stop_event is not None and stop_event.is_set():
            proc.terminate()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
            raise InterruptedError("stopped")
        if deadline is not None and time.monotonic() >= deadline:
            proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)
            raise subprocess.TimeoutExpired(cmd, timeout_sec)
        time.sleep(0.1)
    stdout, stderr = proc.communicate()
    return subprocess.CompletedProcess(cmd, proc.returncode or 0, stdout, stderr)


def unload_all_lms_models(
    status_cb: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> None:
    """Unload every model from LM Studio memory (`lms unload --all`)."""
    loaded = get_loaded_model_entries()
    if not loaded:
        return

    if status_cb:
        names = [
            str(e.get("identifier") or e.get("modelKey") or "unknown")
            for e in loaded
        ]
        status_cb(f"Unloading {len(loaded)} model(s): {', '.join(names)}")

    cli = find_lms_cli()
    result = _run_cli_interruptible(
        [cli, "unload", "--all"],
        stop_event=stop_event,
        timeout_sec=120,
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"lms unload --all failed: {err}")


def ensure_lms_model_loaded(
    model_key: str,
    status_cb: Callable[[str], None] | None = None,
    stop_event: threading.Event | None = None,
) -> str:
    """Unload other models, then load the selected model if needed."""
    def emit(msg: str) -> None:
        if status_cb:
            status_cb(msg)

    if not model_key.strip():
        raise ValueError("No LLM selected.")

    load_key = resolve_lms_load_key(model_key)
    loaded = get_loaded_model_entries()
    loaded_id = find_loaded_model_key(load_key, loaded)

    # Fast path: only the selected model is in memory — nothing to do.
    if loaded_id and len(loaded) == 1:
        emit(f"Model already loaded: {loaded_id}")
        return loaded_id

    # Free memory on small machines before loading the target model.
    if loaded:
        unload_all_lms_models(status_cb=emit, stop_event=stop_event)

    emit(f"Loading {load_key} via lms (may take a minute)...")
    cli = find_lms_cli()
    result = _run_cli_interruptible(
        [cli, "load", load_key],
        stop_event=stop_event,
        timeout_sec=float(LMS_LOAD_TIMEOUT_SEC),
    )
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"lms load {load_key} failed: {err}")

    loaded_id = find_loaded_model_key(load_key)
    if loaded_id:
        emit(f"Model loaded: {loaded_id}")
        return loaded_id

    emit(f"Model loaded: {load_key}")
    return load_key


def resolve_lm_model(client: OpenAI, model_key: str, preferred_id: str | None = None) -> str:
    if preferred_id:
        return preferred_id

    try:
        models = client.models.list()
        names = [m.id for m in models.data]
    except Exception:
        return model_key

    for name in names:
        if _model_keys_match(name, model_key):
            return name
    if names:
        return names[0]
    return model_key


def _release_sounddevice() -> None:
    """Reset PortAudio after a stream was interrupted (macOS input can fail until this)."""
    with contextlib.suppress(Exception):
        sd.stop()


def _resolve_input_device(device: int | None) -> int | None:
    """Return device index if still valid, else system default (None)."""
    if device is None:
        return None
    try:
        dev = sd.query_devices(device)
        if int(dev.get("max_input_channels", 0)) > 0:
            return device
    except Exception:
        pass
    return None


def _piper_length_scale(speech_speed: float) -> float:
    """Map speech speed (1.0 = normal) to Piper --length-scale (inverse; clamped)."""
    speed = max(TTS_SPEECH_SPEED_MIN, min(TTS_SPEECH_SPEED_MAX, float(speech_speed)))
    return max(0.1, min(3.0, 1.0 / speed))


_EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"  # regional indicators (flags)
    "\U0001F300-\U0001FAFF"  # symbols & pictographs
    "\U00002700-\U000027BF"  # dingbats
    "\U000024C2-\U0001F251"  # enclosed characters
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U00002600-\U000026FF"  # misc symbols
    "\u200d"  # ZWJ (compound emoji joiner)
    "\ufe0f"  # variation selector-16
    "\u20e3"  # combining enclosing keycap
    "]+",
    flags=re.UNICODE,
)


def _text_for_tts(text: str) -> str:
    """Remove emoji and collapse whitespace before speech synthesis."""
    if not text:
        return ""
    cleaned = _EMOJI_RE.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


def play_input_beep() -> None:
    """Short ack when the user finishes speaking (end of VAD utterance)."""
    try:
        if BEEP_SCRIPT.is_file():
            subprocess.Popen(
                ["/bin/sh", str(BEEP_SCRIPT)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        afplay = shutil.which("afplay")
        if afplay and BEEP_AUDIO_FALLBACK.is_file():
            subprocess.Popen(
                [afplay, "-r", str(BEEP_PLAYBACK_RATE), str(BEEP_AUDIO_FALLBACK)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
    except OSError:
        pass


def _piper_write_wav(
    text: str,
    voice_path: str,
    out_path: str,
    *,
    speech_speed: float = DEFAULT_TTS_SPEECH_SPEED,
) -> bool:
    text = _text_for_tts(text)
    if not text or not Path(voice_path).is_file():
        return False
    piper_cmd = [
        sys.executable,
        "-m",
        "piper",
        "--model",
        voice_path,
        "--output_file",
        out_path,
    ]
    if abs(speech_speed - 1.0) > 0.01:
        piper_cmd.extend(["--length-scale", f"{_piper_length_scale(speech_speed):.3f}"])
    proc = subprocess.run(
        piper_cmd,
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=120,
    )
    return proc.returncode == 0 and Path(out_path).is_file()


def synthesize_text_to_wav(
    text: str,
    out_path: str,
    *,
    engine: str,
    piper_voice_path: str,
    pocket_voice: str,
    speech_speed: float = DEFAULT_TTS_SPEECH_SPEED,
    pocket_engine: PocketTTSEngine | None = None,
    stop_events: tuple[threading.Event, ...] = (),
) -> bool:
    if not text.strip():
        return False
    if engine == TTS_ENGINE_POCKET:
        voice_id = resolve_pocket_voice(pocket_voice)
        if pocket_engine is not None:
            try:
                return pocket_engine.write_wav(text, voice_id, out_path, stop_events)
            except Exception:
                pass
        return _pocket_generate_wav(text, voice_id, out_path, *stop_events)
    return _piper_write_wav(
        text,
        piper_voice_path,
        out_path,
        speech_speed=speech_speed,
    )


def _read_pipe_chunk(pipe: Any, timeout_sec: float = 0.2) -> bytes | None:
    """Read from a pipe, or None if no data within timeout (poll stop events meanwhile)."""
    ready, _, _ = select.select([pipe], [], [], timeout_sec)
    if not ready:
        return None
    return pipe.read(4096)


def piper_speak(
    text: str,
    voice_path: str,
    *stop_events: threading.Event,
    speech_speed: float = DEFAULT_TTS_SPEECH_SPEED,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> None:
    text = _text_for_tts(text)
    if not text:
        return
    if not Path(voice_path).exists():
        raise FileNotFoundError(f"Piper voice not found: {voice_path}")

    piper_cmd = [sys.executable, "-m", "piper", "--model", voice_path, "--output-raw"]
    if abs(speech_speed - 1.0) > 0.01:
        piper_cmd.extend(["--length-scale", f"{_piper_length_scale(speech_speed):.3f}"])
    proc = subprocess.Popen(
        piper_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(text.encode("utf-8"))
    proc.stdin.close()

    interrupted = False
    try:
        with sd.OutputStream(
            samplerate=PIPER_SAMPLE_RATE,
            channels=1,
            dtype="int16",
        ) as out:
            if on_active is not None:
                on_active(proc, out)
            while True:
                if stop_events and any(event.is_set() for event in stop_events):
                    interrupted = True
                    proc.terminate()
                    break
                chunk = _read_pipe_chunk(proc.stdout)
                if chunk is None:
                    continue
                if not chunk:
                    break
                try:
                    audio = np.frombuffer(chunk, dtype=np.int16)
                    out.write(audio.reshape(-1, 1))
                except Exception:
                    if stop_events and any(event.is_set() for event in stop_events):
                        interrupted = True
                        with contextlib.suppress(Exception):
                            proc.terminate()
                    break
    finally:
        if on_inactive is not None:
            on_inactive()
        with contextlib.suppress(Exception):
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=5)
        if interrupted:
            _release_sounddevice()


def _pocket_prepare_text(text: str) -> str:
    text = _text_for_tts(text)
    text = re.sub(r"\s+", " ", text.replace("#", " ").replace("*", " ")).strip()
    text = re.sub(r"honest", "onest", text, flags=re.I)
    return text.replace(". ", "... ")


class PocketTTSEngine:
    """In-process pocket-tts: load TTSModel once, cache voice states, stream to speakers."""

    def __init__(self) -> None:
        self._model: Any = None
        self._sample_rate: int | None = None
        self._voice_states: dict[str, Any] = {}

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        from pocket_tts.models.tts_model import TTSModel
        from pocket_tts.utils.logging_utils import enable_logging

        with enable_logging("pocket_tts", logging.ERROR):
            model = TTSModel.load_model()
            model.to("cpu")
        self._model = model
        self._sample_rate = int(model.config.mimi.sample_rate)
        return model

    def warmup(self, voice: str) -> None:
        """Load model weights and cache conditioning state for voice."""
        self._voice_state(voice)

    def _voice_state(self, voice: str) -> Any:
        voice_id = resolve_pocket_voice(voice)
        cached = self._voice_states.get(voice_id)
        if cached is not None:
            return cached
        model = self._load_model()
        state = model.get_state_for_audio_prompt(voice_id)
        self._voice_states[voice_id] = state
        return state

    def release(self) -> None:
        self._voice_states.clear()
        self._model = None
        self._sample_rate = None

    def write_wav(
        self,
        text: str,
        voice: str,
        out_path: str,
        stop_events: tuple[threading.Event, ...],
    ) -> bool:
        """Synthesize one pocket-tts utterance to a WAV file (in-process)."""
        prepared = _pocket_prepare_text(text)
        if not prepared.strip():
            return False
        model = self._load_model()
        assert self._sample_rate is not None
        model_state = self._voice_state(voice)
        frames: list[np.ndarray] = []
        for chunk in model.generate_audio_stream(
            model_state=model_state,
            text_to_generate=prepared,
            copy_state=True,
        ):
            if stop_events and any(event.is_set() for event in stop_events):
                return False
            samples = chunk.detach().cpu().numpy().astype(np.float32, copy=False)
            if samples.ndim > 1:
                samples = samples.reshape(-1)
            frames.append(samples)
        if not frames:
            return False
        audio = np.clip(np.concatenate(frames), -1.0, 1.0)
        pcm = (audio * 32767.0).astype(np.int16)
        with wave.open(out_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self._sample_rate)
            wf.writeframes(pcm.tobytes())
        return True

    def speak(
        self,
        text: str,
        voice: str,
        stop_events: tuple[threading.Event, ...],
        on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
        on_inactive: Callable[[], None] | None = None,
    ) -> None:
        prepared = _pocket_prepare_text(text)
        if not prepared.strip():
            return
        model = self._load_model()
        assert self._sample_rate is not None
        model_state = self._voice_state(voice)
        interrupted = False
        try:
            with sd.OutputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
            ) as out:
                if on_active is not None:
                    on_active(None, out)
                for chunk in model.generate_audio_stream(
                    model_state=model_state,
                    text_to_generate=prepared,
                    copy_state=True,
                ):
                    if stop_events and any(event.is_set() for event in stop_events):
                        interrupted = True
                        break
                    samples = chunk.detach().cpu().numpy().astype(np.float32, copy=False)
                    if samples.ndim > 1:
                        samples = samples.reshape(-1)
                    out.write(samples.reshape(-1, 1))
        finally:
            if on_inactive is not None:
                on_inactive()
            if interrupted:
                _release_sounddevice()


def _pocket_cli_argv() -> list[str]:
    exe = shutil.which("pocket-tts")
    if exe:
        return [exe]
    return [sys.executable, "-m", "pocket_tts"]


def _chunk_text_for_pocket(text: str) -> list[str]:
    max_chunk = max(200, POCKET_MAX_CHUNK_CHARS)
    text = (text or "").strip()
    if len(text) <= max_chunk:
        return [text] if text else []
    parts = re.split(r"(?<=[.!?])\s+", text)
    parts = [p.strip() for p in parts if p.strip()]
    chunks: list[str] = []
    cur = ""
    for part in parts:
        if len(part) > max_chunk:
            if cur:
                chunks.append(cur.strip())
                cur = ""
            for i in range(0, len(part), max_chunk):
                piece = part[i : i + max_chunk].strip()
                if piece:
                    chunks.append(piece)
            continue
        joined = f"{cur} {part}".strip() if cur else part
        if len(joined) <= max_chunk:
            cur = joined
        else:
            if cur:
                chunks.append(cur.strip())
            cur = part
    if cur:
        chunks.append(cur.strip())
    return [chunk for chunk in chunks if chunk]


def _pocket_run_chunk(
    text: str,
    voice: str,
    out_path: str,
    *stop_events: threading.Event,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> bool:
    cmd = [
        *_pocket_cli_argv(),
        "generate",
        "--voice",
        voice,
        "--text",
        _pocket_prepare_text(text),
        "--output-path",
        out_path,
        "-q",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        if on_active is not None:
            on_active(proc, None)
        while proc.poll() is None:
            if stop_events and any(event.is_set() for event in stop_events):
                proc.terminate()
                return False
            time.sleep(0.05)
    finally:
        if on_inactive is not None:
            on_inactive()
        with contextlib.suppress(Exception):
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=120)
    return proc.returncode == 0 and Path(out_path).is_file()


def _concat_wavs(paths: list[str], out_path: str) -> bool:
    if not paths:
        return False
    try:
        with wave.open(paths[0], "rb") as w0:
            nch, sw, fr = w0.getnchannels(), w0.getsampwidth(), w0.getframerate()
            data = w0.readframes(w0.getnframes())
        for path in paths[1:]:
            with wave.open(path, "rb") as wf:
                if (wf.getnchannels(), wf.getsampwidth(), wf.getframerate()) != (nch, sw, fr):
                    return False
                data += wf.readframes(wf.getnframes())
        with wave.open(out_path, "wb") as out:
            out.setnchannels(nch)
            out.setsampwidth(sw)
            out.setframerate(fr)
            out.writeframes(data)
        return True
    except Exception:
        return False


def _pocket_generate_wav(
    text: str,
    voice: str,
    out_path: str,
    *stop_events: threading.Event,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> bool:
    chunks = _chunk_text_for_pocket(text)
    if not chunks:
        return False
    if len(chunks) == 1:
        return _pocket_run_chunk(
            chunks[0],
            voice,
            out_path,
            *stop_events,
            on_active=on_active,
            on_inactive=on_inactive,
        )
    part_paths: list[str] = []
    try:
        for chunk in chunks:
            if stop_events and any(event.is_set() for event in stop_events):
                return False
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                part_path = tmp.name
            part_paths.append(part_path)
            if not _pocket_run_chunk(
                chunk,
                voice,
                part_path,
                *stop_events,
                on_active=on_active,
                on_inactive=on_inactive,
            ):
                return False
        return _concat_wavs(part_paths, out_path)
    finally:
        for part_path in part_paths:
            Path(part_path).unlink(missing_ok=True)


def _afplay_wav(
    wav_path: str,
    speech_speed: float,
    *stop_events: threading.Event,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> None:
    """Play a WAV via macOS afplay with rate-scaled playback (-r / -q)."""
    afplay = shutil.which("afplay")
    if not afplay:
        raise RuntimeError("afplay not found (required for pocket-tts speech speed on macOS)")
    speed = max(TTS_SPEECH_SPEED_MIN, min(TTS_SPEECH_SPEED_MAX, float(speech_speed)))
    cmd = [afplay, "-r", f"{speed}", "-q", "1", wav_path]
    proc = subprocess.Popen(cmd)
    try:
        if on_active is not None:
            on_active(proc, None)
        while proc.poll() is None:
            if stop_events and any(event.is_set() for event in stop_events):
                proc.terminate()
                break
            time.sleep(0.05)
    finally:
        if on_inactive is not None:
            on_inactive()
        with contextlib.suppress(Exception):
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=2)


def play_wav_file(
    wav_path: str,
    *stop_events: threading.Event,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> None:
    interrupted = False
    try:
        with wave.open(wav_path, "rb") as wf:
            channels = wf.getnchannels()
            sample_rate = wf.getframerate()
            with sd.OutputStream(
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
            ) as out:
                if on_active is not None:
                    on_active(None, out)
                while True:
                    if stop_events and any(event.is_set() for event in stop_events):
                        interrupted = True
                        break
                    frames = wf.readframes(4096)
                    if not frames:
                        break
                    audio = np.frombuffer(frames, dtype=np.int16)
                    if channels > 1:
                        out.write(audio.reshape(-1, channels))
                    else:
                        out.write(audio.reshape(-1, 1))
    finally:
        if on_inactive is not None:
            on_inactive()
        if interrupted:
            _release_sounddevice()


def _pocket_text_to_wav(
    text: str,
    voice: str,
    out_path: str,
    stop_events: tuple[threading.Event, ...],
    pocket_engine: PocketTTSEngine | None = None,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> bool:
    voice_id = resolve_pocket_voice(voice)
    chunks = _chunk_text_for_pocket(text)
    if not chunks:
        return False
    if len(chunks) == 1 and pocket_engine is not None:
        try:
            return pocket_engine.write_wav(chunks[0], voice_id, out_path, stop_events)
        except Exception:
            pass
    return _pocket_generate_wav(
        text,
        voice_id,
        out_path,
        *stop_events,
        on_active=on_active,
        on_inactive=on_inactive,
    )


def _pocket_speak_cli(
    text: str,
    voice: str,
    *stop_events: threading.Event,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> None:
    """Subprocess fallback when pocket_tts is not importable in this Python env."""
    if not text.strip():
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        if not _pocket_generate_wav(
            text,
            resolve_pocket_voice(voice),
            wav_path,
            *stop_events,
            on_active=on_active,
            on_inactive=on_inactive,
        ):
            raise RuntimeError("pocket-tts failed to generate audio")
        if stop_events and any(event.is_set() for event in stop_events):
            return
        play_wav_file(
            wav_path,
            *stop_events,
            on_active=on_active,
            on_inactive=on_inactive,
        )
    finally:
        Path(wav_path).unlink(missing_ok=True)


def _pocket_speak_afplay(
    text: str,
    voice: str,
    speech_speed: float,
    stop_events: tuple[threading.Event, ...],
    pocket_engine: PocketTTSEngine | None = None,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> None:
    """Render pocket-tts to a temp WAV, play with afplay rate scaling, then delete."""
    if not text.strip():
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        if not _pocket_text_to_wav(
            text,
            voice,
            wav_path,
            stop_events,
            pocket_engine=pocket_engine,
            on_active=on_active,
            on_inactive=on_inactive,
        ):
            raise RuntimeError("pocket-tts failed to generate audio")
        if stop_events and any(event.is_set() for event in stop_events):
            return
        _afplay_wav(
            wav_path,
            speech_speed,
            *stop_events,
            on_active=on_active,
            on_inactive=on_inactive,
        )
    finally:
        Path(wav_path).unlink(missing_ok=True)


def speak_text(
    text: str,
    *,
    engine: str,
    piper_voice_path: str,
    pocket_voice: str,
    stop_events: tuple[threading.Event, ...],
    speech_speed: float = DEFAULT_TTS_SPEECH_SPEED,
    pocket_engine: PocketTTSEngine | None = None,
    on_active: Callable[[subprocess.Popen[Any], Any], None] | None = None,
    on_inactive: Callable[[], None] | None = None,
) -> None:
    if engine == TTS_ENGINE_POCKET:
        if abs(speech_speed - 1.0) > 0.01:
            _pocket_speak_afplay(
                text,
                pocket_voice,
                speech_speed,
                stop_events,
                pocket_engine=pocket_engine,
                on_active=on_active,
                on_inactive=on_inactive,
            )
            return
        if pocket_engine is not None:
            try:
                pocket_engine.speak(
                    text,
                    pocket_voice,
                    stop_events,
                    on_active=on_active,
                    on_inactive=on_inactive,
                )
                return
            except ImportError:
                pass
        _pocket_speak_cli(
            text,
            pocket_voice,
            *stop_events,
            on_active=on_active,
            on_inactive=on_inactive,
        )
        return
    piper_speak(
        text,
        piper_voice_path,
        *stop_events,
        speech_speed=speech_speed,
        on_active=on_active,
        on_inactive=on_inactive,
    )


def record_utterance(
    stop_event: threading.Event,
    *,
    device: int | None = None,
    vad_threshold: float | None = None,
    silence_end_ms: int | None = None,
) -> RecordResult:
    """Record from mic until silence after speech (energy VAD with noise calibration)."""
    frames: list[np.ndarray] = []
    speech_started = False
    silent_frames = 0
    end_ms = silence_end_ms if silence_end_ms is not None else DEFAULT_SILENCE_END_MS
    end_ms = max(SILENCE_END_MS_MIN, min(SILENCE_END_MS_MAX, int(end_ms)))
    silent_limit = max(1, end_ms // FRAME_MS)
    max_frames = max(1, (MAX_RECORD_SEC * 1000) // FRAME_MS)
    calibration_frames = max(5, int(500 / FRAME_MS))
    peak_rms = 0.0
    noise_levels: list[float] = []
    threshold = vad_threshold if vad_threshold is not None else SPEECH_THRESHOLD

    stream_kwargs: dict[str, Any] = {
        "samplerate": SAMPLE_RATE,
        "channels": 1,
        "dtype": "int16",
        "blocksize": FRAME_SAMPLES,
    }
    resolved_device = _resolve_input_device(device)
    if resolved_device is not None:
        stream_kwargs["device"] = resolved_device

    stream: sd.InputStream | None = None
    open_error: Exception | None = None
    for attempt in range(2):
        try:
            stream = sd.InputStream(**stream_kwargs)
            open_error = None
            break
        except Exception as exc:
            open_error = exc
            if attempt == 0:
                _release_sounddevice()
                continue
    if stream is None:
        return RecordResult(
            None,
            error=(
                f"Could not open microphone ({input_device_label(device)}): "
                f"{open_error}"
            ),
        )

    try:
        with stream:
            for frame_idx in range(max_frames):
                if stop_event.is_set():
                    return RecordResult(None, peak_rms=peak_rms, threshold=threshold)
                try:
                    chunk, _ = stream.read(FRAME_SAMPLES)
                except Exception:
                    if stop_event.is_set():
                        return RecordResult(None, peak_rms=peak_rms, threshold=threshold)
                    raise
                mono = chunk[:, 0] if chunk.ndim > 1 else chunk.flatten()
                level = _rms(mono)
                peak_rms = max(peak_rms, level)

                if not speech_started:
                    if frame_idx < calibration_frames:
                        noise_levels.append(level)
                        if frame_idx == calibration_frames - 1 and vad_threshold is None:
                            floor = max(noise_levels) if noise_levels else 0.0
                            threshold = max(SPEECH_THRESHOLD, floor * 3.5 + 0.003)
                        continue
                    if level >= threshold:
                        speech_started = True
                        frames.append(mono.copy())
                    continue

                frames.append(mono.copy())
                if level < threshold:
                    silent_frames += 1
                    if silent_frames >= silent_limit:
                        break
                else:
                    silent_frames = 0
    finally:
        if stop_event.is_set():
            _release_sounddevice()

    if not frames:
        if peak_rms < 0.0001:
            return RecordResult(
                None,
                peak_rms=peak_rms,
                threshold=threshold,
                error=(
                    "Microphone captured no audio. Check macOS System Settings → "
                    "Privacy & Security → Microphone, then pick the correct input device in Settings."
                ),
            )
        return RecordResult(
            None,
            peak_rms=peak_rms,
            threshold=threshold,
            error=(
                f"No speech detected (peak level {peak_rms:.4f}, threshold {threshold:.4f}). "
                "Speak closer to the mic or choose a different input in Settings."
            ),
        )

    pcm = np.concatenate(frames)
    if int(np.max(np.abs(pcm))) == 0:
        return RecordResult(
            None,
            peak_rms=peak_rms,
            threshold=threshold,
            error="Microphone returned silence. Try a different input device in Settings.",
        )
    return RecordResult(pcm, peak_rms=peak_rms, threshold=threshold)


def transcribe_audio(model: WhisperModel, pcm: np.ndarray) -> str:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    try:
        with wave.open(wav_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm.astype(np.int16).tobytes())

        segments, _ = model.transcribe(wav_path, beam_size=1, vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip()
    finally:
        Path(wav_path).unlink(missing_ok=True)


def _normalize_voice_command(text: str) -> str | None:
    """Return a voice command only when the utterance is exactly that word."""
    normalized = text.strip().lower().rstrip(".!?,")
    if normalized in ("redo", "clear", "stop", "copy", "undo"):
        return normalized
    return None


# ---------------------------------------------------------------------------
# Voice worker thread
# ---------------------------------------------------------------------------


@dataclass
class ChatTurn:
    role: str
    text: str
    image_path: str | None = None


class VoiceLoopWorker(QThread):
    status = Signal(str)
    user_said = Signal(str)
    assistant_said = Signal(str)
    error = Signal(str)
    chat_cleared = Signal()
    conversation_display_refresh = Signal()
    stop_requested = Signal()
    copy_to_clipboard = Signal(str)
    command_feedback = Signal(str)
    session_exited = Signal()
    request_image_sync = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stop = threading.Event()
        self._tts_stop = threading.Event()
        self._tts_proc: subprocess.Popen[Any] | None = None
        self._tts_lock = threading.Lock()
        self._continuous = False
        self._model_key = DEFAULT_MODEL_KEY
        self._whisper_model = WHISPER_MODEL
        self._attached_image: Path | None = None
        self._image_lock = threading.Lock()
        self._history: list[ChatTurn] = []
        self._history_lock = threading.Lock()
        self._whisper: WhisperModel | None = None
        self._client: OpenAI | None = None
        self._lm_model_id = ""
        self._system_prompt: str | None = None
        self._max_tokens = DEFAULT_LLM_MAX_TOKENS
        self._temperature = DEFAULT_LLM_TEMPERATURE
        self._input_device: int | None = None
        self._vad_threshold: float | None = None
        self._silence_end_ms = DEFAULT_SILENCE_END_MS
        self._disable_gemma_thinking = True
        self._supports_vision = True
        self._tts_engine = TTS_ENGINE_PIPER
        self._piper_voice = default_piper_voice_path()
        self._pocket_voice = default_pocket_voice()
        self._tts_speech_speed = DEFAULT_TTS_SPEECH_SPEED
        self._pocket_engine: PocketTTSEngine | None = None
        self._ui_commands: queue.Queue[str] = queue.Queue()
        self._pending_redo_turn: ChatTurn | None = None
        self._redo_only = False
        self._command_wav_cache: dict[str, str] = {}

    def set_system_prompt(self, prompt: str | None) -> None:
        self._system_prompt = prompt.strip() if prompt and prompt.strip() else None

    def set_max_tokens(self, value: int) -> None:
        self._max_tokens = max(LLM_MAX_TOKENS_MIN, min(LLM_MAX_TOKENS_MAX, int(value)))

    def set_temperature(self, value: float) -> None:
        self._temperature = max(
            LLM_TEMPERATURE_MIN, min(LLM_TEMPERATURE_MAX, float(value))
        )

    def set_input_device(self, device: int | None) -> None:
        self._input_device = device

    def set_vad_threshold(self, value: float | None) -> None:
        self._vad_threshold = value if value and value > 0 else None

    def set_silence_end_ms(self, value: int) -> None:
        self._silence_end_ms = max(
            SILENCE_END_MS_MIN, min(SILENCE_END_MS_MAX, int(value))
        )

    def set_disable_gemma_thinking(self, enabled: bool) -> None:
        self._disable_gemma_thinking = enabled

    def set_model_key(self, model_key: str) -> None:
        self._model_key = model_key.strip()
        if self._client is not None:
            self._lm_model_id = resolve_lm_model(self._client, self._model_key)

    def set_supports_vision(self, enabled: bool) -> None:
        self._supports_vision = enabled
        if not enabled:
            with self._image_lock:
                self._attached_image = None

    def set_whisper_model(self, model_name: str) -> None:
        self._whisper_model = model_name.strip() or WHISPER_MODEL

    def set_tts_engine(self, engine: str) -> None:
        engine = engine.strip().lower()
        self._tts_engine = engine if engine in TTS_ENGINE_OPTIONS else TTS_ENGINE_PIPER

    def set_piper_voice(self, voice_path: str) -> None:
        self._piper_voice = resolve_piper_voice(voice_path)

    def set_pocket_voice(self, voice_name: str) -> None:
        self._pocket_voice = resolve_pocket_voice(voice_name)

    def set_tts_speech_speed(self, value: float) -> None:
        self._tts_speech_speed = max(
            TTS_SPEECH_SPEED_MIN, min(TTS_SPEECH_SPEED_MAX, float(value))
        )

    def _ensure_pocket_engine(self) -> PocketTTSEngine:
        if self._pocket_engine is None:
            self._pocket_engine = PocketTTSEngine()
        return self._pocket_engine

    def set_continuous(self, enabled: bool) -> None:
        self._continuous = enabled

    def set_attached_image(self, path: Path | None) -> None:
        with self._image_lock:
            self._attached_image = path.expanduser() if path is not None else None

    def set_pending_redo(self, turn: ChatTurn | None) -> None:
        self._pending_redo_turn = turn
        self._redo_only = turn is not None

    def request_ui_undo(self) -> None:
        self._ui_commands.put("undo")

    def request_ui_redo(self) -> None:
        self._abort_tts_playback()
        self._ui_commands.put("redo")

    def request_ui_clear(self) -> None:
        self._ui_commands.put("clear")

    def _drain_ui_commands(self) -> None:
        while True:
            try:
                command = self._ui_commands.get_nowait()
            except queue.Empty:
                break
            self._handle_voice_command(command)

    def clear_history(self) -> None:
        with self._history_lock:
            self._history.clear()

    def _pop_last_exchange(self) -> ChatTurn | None:
        """Remove the last user turn and any assistant reply after it (if present)."""
        with self._history_lock:
            if not self._history:
                return None
            while self._history and self._history[-1].role == "assistant":
                self._history.pop()
            if not self._history or self._history[-1].role != "user":
                return None
            return self._history.pop()

    def _user_turn_for_redo(self) -> ChatTurn | None:
        """User turn to re-ask: drop a trailing assistant if present, else last user only."""
        with self._history_lock:
            if not self._history:
                return None
            if self._history[-1].role == "assistant":
                self._history.pop()
            if not self._history or self._history[-1].role != "user":
                return None
            return self._history[-1]

    def _last_assistant_reply(self) -> str:
        with self._history_lock:
            if self._history and self._history[-1].role == "assistant":
                return self._history[-1].text
        return ""

    def _command_note(self, message: str) -> None:
        self.command_feedback.emit(message)
        self.status.emit(message)

    def _ensure_command_wav(self, message: str) -> str | None:
        cached = self._command_wav_cache.get(message)
        if cached and Path(cached).is_file():
            return cached
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, prefix="cmdfb_") as tmp:
            wav_path = tmp.name
        pocket_engine: PocketTTSEngine | None = None
        if self._tts_engine == TTS_ENGINE_POCKET:
            try:
                pocket_engine = self._ensure_pocket_engine()
                if not pocket_engine.loaded:
                    pocket_engine.warmup(self._pocket_voice)
            except Exception:
                pocket_engine = None
        ok = synthesize_text_to_wav(
            message,
            wav_path,
            engine=self._tts_engine,
            piper_voice_path=self._piper_voice,
            pocket_voice=self._pocket_voice,
            speech_speed=self._tts_speech_speed,
            pocket_engine=pocket_engine,
        )
        if not ok:
            Path(wav_path).unlink(missing_ok=True)
            return None
        self._command_wav_cache[message] = wav_path
        return wav_path

    def _speak_command_feedback(self, message: str) -> None:
        self._command_note(message)
        wav_path = self._ensure_command_wav(message)
        if wav_path is None:
            return
        self._tts_stop.clear()
        try:
            if self._tts_engine == TTS_ENGINE_POCKET and abs(self._tts_speech_speed - 1.0) > 0.01:
                _afplay_wav(
                    wav_path,
                    self._tts_speech_speed,
                    self._tts_stop,
                    on_active=self._set_tts_active,
                    on_inactive=self._clear_tts_active,
                )
            else:
                play_wav_file(
                    wav_path,
                    self._tts_stop,
                    on_active=self._set_tts_active,
                    on_inactive=self._clear_tts_active,
                )
        except Exception:
            pass
        finally:
            self._tts_stop.clear()

    def _handle_voice_command(self, command: str) -> bool:
        """Handle redo/clear/stop/copy/undo. Returns False to exit the hands-free listen loop."""
        if command == "copy":
            last_reply = self._last_assistant_reply()
            if not last_reply:
                self._speak_command_feedback("Nothing to copy.")
                return True
            self.copy_to_clipboard.emit(last_reply)
            self._speak_command_feedback("Last response copied to clipboard.")
            return True

        if command == "clear":
            self.clear_history()
            self.chat_cleared.emit()
            self._speak_command_feedback("Conversation cleared.")
            return True

        if command == "stop":
            self._continuous = False
            self.stop_requested.emit()
            self._speak_command_feedback("Stopped.")
            self._stop.set()
            return False

        if command == "undo":
            if self._pop_last_exchange() is None:
                self._speak_command_feedback("Nothing to undo.")
                return True
            self.conversation_display_refresh.emit()
            self._speak_command_feedback("Undone.")
            return True

        if command == "redo":
            user_turn = self._user_turn_for_redo()
            if user_turn is None:
                self._command_note("Nothing to redo.")
                return True
            self.conversation_display_refresh.emit()
            image_path = (
                Path(user_turn.image_path)
                if user_turn.image_path and Path(user_turn.image_path).exists()
                else None
            )
            self.status.emit("Redoing last response...")
            self._process_turn(
                user_turn.text,
                image_path=image_path,
                show_user=False,
                append_user=False,
            )
            return True

        return True

    def _set_tts_active(self, proc: subprocess.Popen[Any], _stream: Any) -> None:
        with self._tts_lock:
            self._tts_proc = proc

    def _clear_tts_active(self) -> None:
        with self._tts_lock:
            self._tts_proc = None

    def _abort_tts_playback(self) -> None:
        """Request TTS stop from the UI thread; worker closes audio on its own thread."""
        self._tts_stop.set()
        with self._tts_lock:
            proc = self._tts_proc
        if proc is not None and proc.poll() is None:
            with contextlib.suppress(Exception):
                proc.terminate()

    def stop_talking_now(self) -> None:
        """Abort Piper playback only; keep the voice loop running."""
        self._abort_tts_playback()

    def stop_now(self) -> None:
        """Request stop. Never touch PortAudio streams here — record runs on this thread."""
        self._stop.set()
        self._abort_tts_playback()

    def _get_attached_image(self) -> Path | None:
        with self._image_lock:
            return self._attached_image

    def _coerce_image_path(self, image_path: Path | None) -> Path | None:
        if not self._supports_vision or image_path is None:
            return None
        return image_path if image_path.exists() else None

    def _ensure_lm_model_loaded_for_api(self) -> bool:
        """Unload other LM Studio models, load the selected one, sync API model id."""
        if self.isInterruptionRequested() or self._stop.is_set():
            return False
        try:
            loaded_id = ensure_lms_model_loaded(
                self._model_key,
                status_cb=lambda msg: self.status.emit(msg),
                stop_event=self._stop,
            )
        except InterruptedError:
            return False
        if self.isInterruptionRequested() or self._stop.is_set():
            return False
        if self._client is None:
            self._client = OpenAI(base_url=LM_STUDIO_BASE, api_key="lm-studio")
        self._lm_model_id = resolve_lm_model(
            self._client, self._model_key, preferred_id=loaded_id
        )
        return True

    def _init_models(self) -> bool:
        if self.isInterruptionRequested() or self._stop.is_set():
            return False
        self.status.emit("Ensuring LLM is loaded in LM Studio...")
        if not self._ensure_lm_model_loaded_for_api():
            return False
        self.status.emit(f"LM Studio model: {self._lm_model_id}")
        self.status.emit(f"Loading Whisper model ({self._whisper_model})...")
        # num_workers must be >= 1 on Python 3.14 (0 causes IndexError in transcribe).
        self._whisper = WhisperModel(
            self._whisper_model,
            device="cpu",
            compute_type="int8",
            num_workers=1,
        )
        if self._tts_engine == TTS_ENGINE_POCKET:
            if self.isInterruptionRequested() or self._stop.is_set():
                return False
            self.status.emit("Loading pocket-tts model...")
            try:
                self._ensure_pocket_engine().warmup(self._pocket_voice)
            except ImportError:
                self.status.emit(
                    "pocket-tts not in this Python env — will use CLI if available."
                )
            except Exception as exc:
                self.error.emit(f"pocket-tts load failed: {exc}")
                return False
        return True

    def _build_messages(self, user_text: str, image_path: Path | None) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = []
        if self._system_prompt:
            messages.append({"role": "system", "content": self._system_prompt})
        with self._history_lock:
            history = list(self._history)
        for turn in history:
            if turn.role == "assistant":
                if _is_garbage_assistant_history(turn.text):
                    continue
            if turn.role == "user":
                hist_image = Path(turn.image_path) if turn.image_path else None
                if (
                    self._supports_vision
                    and hist_image is not None
                    and hist_image.expanduser().exists()
                ):
                    messages.append(
                        {
                            "role": "user",
                            "content": _user_message_image_content(
                                turn.text, hist_image.expanduser()
                            ),
                        }
                    )
                else:
                    messages.append({"role": "user", "content": turn.text})
            else:
                messages.append({"role": "assistant", "content": turn.text})

        image_path = self._coerce_image_path(image_path)
        last = history[-1] if history else None
        image_key = _image_path_key(image_path)
        last_image_key = _image_path_key(last.image_path) if last and last.image_path else None
        already_pending = (
            last is not None
            and last.role == "user"
            and last.text == user_text
            and (image_key is None or image_key == last_image_key)
        )
        if not already_pending:
            if image_path:
                messages.append(
                    {
                        "role": "user",
                        "content": _user_message_image_content(user_text, image_path),
                    }
                )
            else:
                messages.append({"role": "user", "content": user_text})
        elif image_path:
            # History already has this user turn; ensure it still carries the image.
            idx = _find_last_user_message_index(messages, user_text)
            if idx is not None and not _message_has_image_url(messages[idx]):
                messages[idx] = {
                    "role": "user",
                    "content": _user_message_image_content(user_text, image_path),
                }
        return messages

    def _query_llm(self, user_text: str, image_path: Path | None) -> str:
        if not self._ensure_lm_model_loaded_for_api():
            raise InterruptedError("stopped")
        assert self._client is not None
        messages = self._build_messages(user_text, image_path)
        api_messages = _prepare_gemma_api_messages(
            messages,
            self._lm_model_id,
            disable_thinking=self._disable_gemma_thinking,
        )
        self.status.emit("Generating reply...")
        create_kwargs: dict[str, Any] = {
            "model": self._lm_model_id,
            "messages": api_messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
        }
        if self._disable_gemma_thinking and _is_gemma4_model(self._lm_model_id):
            create_kwargs["extra_body"] = _gemma_disable_thinking_extra_body()
        response = self._client.chat.completions.create(**create_kwargs)
        choice = response.choices[0]
        return _extract_assistant_reply(choice, user_text=user_text)

    def _process_turn(
        self,
        user_text: str,
        *,
        image_path: Path | None = None,
        show_user: bool = True,
        append_user: bool = True,
    ) -> None:
        if self._stop.is_set() or self.isInterruptionRequested():
            return
        if image_path is None:
            image_path = self._get_attached_image()
        image_path = self._coerce_image_path(image_path)
        img_note = f" [+image: {image_path.name}]" if image_path else ""
        if show_user:
            self.user_said.emit(user_text + img_note)

        if append_user:
            with self._history_lock:
                self._history.append(
                    ChatTurn("user", user_text, _image_path_key(image_path))
                )

        try:
            reply = self._query_llm(user_text, image_path)
        except Exception as exc:
            self.error.emit(f"LM Studio error: {exc}")
            return
        if self._stop.is_set() or self.isInterruptionRequested():
            return

        if not reply:
            self.error.emit(
                "Empty response from model. The model may have used all tokens on internal "
                "reasoning — try a custom system prompt that asks for a short spoken answer."
            )
            return

        if _is_garbage_assistant_history(reply) or _echoes_user_text(reply, user_text):
            self.error.emit("Could not extract a speakable reply from the model response.")
            return

        self.assistant_said.emit(reply)
        with self._history_lock:
            self._history.append(ChatTurn("assistant", reply))

        self.status.emit("Speaking...")
        self._tts_stop.clear()
        try:
            pocket_engine: PocketTTSEngine | None = None
            if self._tts_engine == TTS_ENGINE_POCKET:
                try:
                    pocket_engine = self._ensure_pocket_engine()
                    if not pocket_engine.loaded:
                        self.status.emit("Loading pocket-tts model...")
                    pocket_engine.warmup(self._pocket_voice)
                except ImportError:
                    pocket_engine = None
                except Exception as exc:
                    self.error.emit(f"pocket-tts load failed: {exc}")
                    return
            speak_text(
                reply,
                engine=self._tts_engine,
                piper_voice_path=self._piper_voice,
                pocket_voice=self._pocket_voice,
                speech_speed=self._tts_speech_speed,
                stop_events=(self._tts_stop, self._stop),
                pocket_engine=pocket_engine,
                on_active=self._set_tts_active,
                on_inactive=self._clear_tts_active,
            )
        except Exception as exc:
            self.error.emit(f"TTS error: {exc}")
            return
        if self._tts_stop.is_set() and not self._stop.is_set():
            self.status.emit("Speech stopped — ready for input.")
        self._tts_stop.clear()
        self._drain_ui_commands()

    def _listen_and_respond(self) -> bool:
        """One mic → STT → LLM → TTS cycle. Returns False if interrupted."""
        if self.isInterruptionRequested() or self._stop.is_set():
            return False
        self.request_image_sync.emit()
        self._drain_ui_commands()
        self._tts_stop.clear()
        mic_name = input_device_label(self._input_device)
        self.status.emit(f"Listening on {mic_name}…")
        record = record_utterance(
            self._stop,
            device=self._input_device,
            vad_threshold=self._vad_threshold,
            silence_end_ms=self._silence_end_ms,
        )
        if self.isInterruptionRequested() or self._stop.is_set():
            return False
        if record.error or record.pcm is None:
            if record.error:
                self.status.emit(record.error)
                if "Could not open microphone" in record.error:
                    self.error.emit(record.error)
                    return False
            elif not self._continuous:
                self.status.emit("No speech detected.")
            return True

        play_input_beep()
        self.status.emit("Transcribing...")
        assert self._whisper is not None
        try:
            text = transcribe_audio(self._whisper, record.pcm)
        except Exception as exc:
            if not self._continuous:
                self.status.emit(f"STT error: {exc}")
            return True
        if not text:
            if not self._continuous:
                self.status.emit(
                    f"Could not transcribe speech (recorded {len(record.pcm) / SAMPLE_RATE:.1f}s, "
                    f"peak level {record.peak_rms:.4f})."
                )
            return True

        command = _normalize_voice_command(text)
        if command:
            return self._handle_voice_command(command)

        self._process_turn(text)
        return True

    def _release_resources(self) -> None:
        whisper = self._whisper
        self._whisper = None
        self._client = None
        for path in self._command_wav_cache.values():
            Path(path).unlink(missing_ok=True)
        self._command_wav_cache.clear()
        if whisper is not None:
            del whisper
        if self._pocket_engine is not None:
            self._pocket_engine.release()
            self._pocket_engine = None

    def run(self) -> None:
        try:
            try:
                if not self._init_models():
                    return
            except Exception as exc:
                self.error.emit(f"Init failed: {exc}")
                return

            if self._pending_redo_turn is not None:
                turn = self._pending_redo_turn
                self._pending_redo_turn = None
                image_path = (
                    Path(turn.image_path)
                    if turn.image_path and Path(turn.image_path).expanduser().exists()
                    else None
                )
                self.status.emit("Redoing last response...")
                self._process_turn(
                    turn.text,
                    image_path=image_path,
                    show_user=False,
                    append_user=False,
                )

            if self._continuous:
                self.status.emit("Hands-free listening — speak anytime.")
                while self._continuous and not self.isInterruptionRequested():
                    if not self._listen_and_respond():
                        break
                self.status.emit("Hands-free stopped.")
            elif not self._redo_only:
                self._listen_and_respond()
                self.status.emit("Ready.")
            else:
                self._redo_only = False
                self.status.emit("Ready.")
        finally:
            self._release_resources()
            self.session_exited.emit()


# ---------------------------------------------------------------------------
# System prompt settings
# ---------------------------------------------------------------------------


@dataclass
class PromptEntry:
    id: str
    name: str
    text: str


@dataclass
class PromptStore:
    active_id: str | None = None
    prompts: list[PromptEntry] = field(default_factory=list)
    max_tokens: int = DEFAULT_LLM_MAX_TOKENS
    temperature: float = DEFAULT_LLM_TEMPERATURE
    input_device: int | None = None
    vad_threshold: float | None = None
    silence_end_ms: int = DEFAULT_SILENCE_END_MS
    disable_gemma_thinking: bool = True
    active_model: str = DEFAULT_MODEL_KEY
    whisper_model: str = WHISPER_MODEL
    tts_engine: str = TTS_ENGINE_PIPER
    piper_voice: str = field(default_factory=default_piper_voice_path)
    pocket_voice: str = field(default_factory=default_pocket_voice)
    tts_speech_speed: float = DEFAULT_TTS_SPEECH_SPEED

    @classmethod
    def load(cls, path: Path = DEMO_PROMPTS_PATH) -> PromptStore:
        if not path.is_file():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        prompts = [
            PromptEntry(
                id=str(item.get("id", "")),
                name=str(item.get("name", "Untitled")),
                text=str(item.get("text", "")),
            )
            for item in raw.get("prompts", [])
            if item.get("id")
        ]
        active_id = raw.get("active_id")
        if active_id in (None, "", SYSTEM_DEFAULT_ID):
            active_id = None
        else:
            active_id = str(active_id)
            if not any(p.id == active_id for p in prompts):
                active_id = None
        max_tokens = int(raw.get("max_tokens", DEFAULT_LLM_MAX_TOKENS))
        max_tokens = max(LLM_MAX_TOKENS_MIN, min(LLM_MAX_TOKENS_MAX, max_tokens))

        temperature = float(raw.get("temperature", DEFAULT_LLM_TEMPERATURE))
        temperature = max(LLM_TEMPERATURE_MIN, min(LLM_TEMPERATURE_MAX, temperature))

        input_device = raw.get("input_device")
        if input_device in (None, "", -1, "default"):
            input_device = None
        else:
            input_device = int(input_device)
            valid_ids = {idx for idx, _ in list_input_devices() if idx is not None}
            if input_device not in valid_ids:
                input_device = None

        vad_raw = raw.get("vad_threshold")
        vad_threshold = float(vad_raw) if vad_raw not in (None, "", 0) else None

        silence_end_ms = int(raw.get("silence_end_ms", DEFAULT_SILENCE_END_MS))
        silence_end_ms = max(SILENCE_END_MS_MIN, min(SILENCE_END_MS_MAX, silence_end_ms))

        disable_gemma_thinking = bool(raw.get("disable_gemma_thinking", True))

        active_model = migrate_legacy_model_name(str(raw.get("active_model", "")).strip())
        if not active_model:
            active_model = resolve_default_model_key()

        whisper_model = str(raw.get("whisper_model", WHISPER_MODEL)).strip() or WHISPER_MODEL
        if whisper_model not in WHISPER_MODEL_OPTIONS:
            whisper_model = WHISPER_MODEL

        piper_voice = resolve_piper_voice(
            str(raw.get("piper_voice", default_piper_voice_path())).strip()
        )
        tts_engine = str(raw.get("tts_engine", TTS_ENGINE_PIPER)).strip().lower()
        if tts_engine not in TTS_ENGINE_OPTIONS:
            tts_engine = TTS_ENGINE_PIPER
        pocket_voice = resolve_pocket_voice(
            str(raw.get("pocket_voice", default_pocket_voice())).strip()
        )

        tts_speech_speed = float(raw.get("tts_speech_speed", DEFAULT_TTS_SPEECH_SPEED))
        tts_speech_speed = max(
            TTS_SPEECH_SPEED_MIN, min(TTS_SPEECH_SPEED_MAX, tts_speech_speed)
        )

        return cls(
            active_id=active_id,
            prompts=prompts,
            max_tokens=max_tokens,
            temperature=temperature,
            input_device=input_device,
            vad_threshold=vad_threshold,
            silence_end_ms=silence_end_ms,
            disable_gemma_thinking=disable_gemma_thinking,
            active_model=active_model,
            whisper_model=whisper_model,
            tts_engine=tts_engine,
            piper_voice=piper_voice,
            pocket_voice=pocket_voice,
            tts_speech_speed=tts_speech_speed,
        )

    def save(self, path: Path = DEMO_PROMPTS_PATH) -> None:
        payload = {
            "active_id": self.active_id if self.active_id else SYSTEM_DEFAULT_ID,
            "active_model": self.active_model,
            "whisper_model": self.whisper_model,
            "tts_engine": self.tts_engine,
            "piper_voice": self.piper_voice,
            "pocket_voice": self.pocket_voice,
            "tts_speech_speed": self.tts_speech_speed,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "input_device": self.input_device,
            "vad_threshold": self.vad_threshold,
            "silence_end_ms": self.silence_end_ms,
            "disable_gemma_thinking": self.disable_gemma_thinking,
            "prompts": [
                {"id": p.id, "name": p.name, "text": p.text}
                for p in self.prompts
            ],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def active_system_prompt(self) -> str | None:
        if not self.active_id or self.active_id == SYSTEM_DEFAULT_ID:
            return None
        for entry in self.prompts:
            if entry.id == self.active_id:
                text = entry.text.strip()
                return text or None
        return None

    def active_label(self) -> str:
        if not self.active_id or self.active_id == SYSTEM_DEFAULT_ID:
            return "System default (LM Studio)"
        for entry in self.prompts:
            if entry.id == self.active_id:
                return entry.name
        return "System default (LM Studio)"

    def find_prompt(self, prompt_id: str) -> PromptEntry | None:
        for entry in self.prompts:
            if entry.id == prompt_id:
                return entry
        return None


def _asset_path(name: str) -> str:
    return (ASSETS_DIR / name).as_posix()


def _icon_button_stylesheet(icon_name: str, *, hover_icon_name: str | None = None) -> str:
    icon_url = f"url({_asset_path(icon_name)})"
    if hover_icon_name:
        hover_url = f"url({_asset_path(hover_icon_name)})"
    else:
        hover_url = icon_url.replace(".png", "_hover.png")
        if hover_url == icon_url and icon_name.endswith(".svg"):
            hover_url = f"url({_asset_path(icon_name.replace('.svg', '_hover.svg'))})"
    sz = ICON_BTN_SIZE
    return f"""
        QPushButton {{
            background-color: #f4f4f4;
            border: 1px solid #c8c8c8;
            border-radius: 3px;
            padding: 0px;
            min-width: {sz}px;
            max-width: {sz}px;
            min-height: {sz}px;
            max-height: {sz}px;
            image: {icon_url};
        }}
        QPushButton:hover {{
            background-color: #e8e8e8;
            border: 1px solid #b0b0b0;
            image: {hover_url};
        }}
        QPushButton:pressed {{
            background-color: #d0d0d0;
        }}
    """


def _trash_button_stylesheet() -> str:
    return _icon_button_stylesheet("trash_icon.png", hover_icon_name="trash_icon_hover.png")


def _edit_button_stylesheet() -> str:
    return _icon_button_stylesheet("edit_icon.png", hover_icon_name="edit_icon_hover.png")


class PromptEditDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        title: str = "Edit prompt",
        name: str = "",
        text: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Name:"))
        self.name_edit = QLineEdit(name)
        layout.addWidget(self.name_edit)
        layout.addWidget(QLabel("System prompt:"))
        self.text_edit = QTextEdit()
        self.text_edit.setPlainText(text)
        self.text_edit.setMinimumHeight(180)
        layout.addWidget(self.text_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self.name_edit.text().strip(), self.text_edit.toPlainText()


class PromptDeleteConfirmDialog(QDialog):
    def __init__(self, entry: PromptEntry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Delete prompt")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f'Delete “{entry.name}”?'))

        preview = QTextEdit()
        preview.setReadOnly(True)
        preview.setPlainText(entry.text or "(empty prompt)")
        preview.setMinimumHeight(120)
        preview.setMaximumHeight(260)
        preview.setStyleSheet(
            "QTextEdit {"
            "  border: 1px solid #aaa;"
            "  border-radius: 4px;"
            "  padding: 8px;"
            "  background: #fafafa;"
            "  color: #333;"
            "}"
        )
        layout.addWidget(preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Delete")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PromptSettingsDialog(QDialog):
    def __init__(self, store: PromptStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 460)
        self._store = deepcopy(store)
        self._radio_by_id: dict[str, QRadioButton] = {}

        layout = QVBoxLayout(self)

        tokens_row = QHBoxLayout()
        tokens_row.addWidget(QLabel("Max tokens:"))
        self._max_tokens_spin = QSpinBox()
        self._max_tokens_spin.setRange(LLM_MAX_TOKENS_MIN, LLM_MAX_TOKENS_MAX)
        self._max_tokens_spin.setSingleStep(64)
        self._max_tokens_spin.setValue(self._store.max_tokens)
        self._max_tokens_spin.setToolTip(
            "Maximum completion tokens per reply. Increase for Gemma 4 if replies are cut off; "
            "decrease to save memory and latency on a small machine."
        )
        tokens_row.addWidget(self._max_tokens_spin)
        tokens_row.addStretch(1)
        layout.addLayout(tokens_row)

        temp_row = QHBoxLayout()
        temp_row.addWidget(QLabel("Temperature:"))
        self._temp_slider = QSlider(Qt.Orientation.Horizontal)
        self._temp_slider.setRange(
            int(LLM_TEMPERATURE_MIN * LLM_TEMPERATURE_SLIDER_SCALE),
            int(LLM_TEMPERATURE_MAX * LLM_TEMPERATURE_SLIDER_SCALE),
        )
        self._temp_slider.setValue(int(round(self._store.temperature * LLM_TEMPERATURE_SLIDER_SCALE)))
        self._temp_slider.setToolTip(
            "LLM sampling temperature (0 = deterministic, higher = more varied). "
            "Takes effect on the next voice session."
        )
        self._temp_slider.valueChanged.connect(self._on_temp_slider_changed)
        temp_row.addWidget(self._temp_slider, stretch=1)
        self._temp_value_label = QLabel(f"{self._store.temperature:.2f}")
        self._temp_value_label.setMinimumWidth(36)
        temp_row.addWidget(self._temp_value_label)
        layout.addLayout(temp_row)

        self._disable_thinking_cb = QCheckBox("Disable Gemma 4 thinking (recommended for voice)")
        self._disable_thinking_cb.setChecked(self._store.disable_gemma_thinking)
        self._disable_thinking_cb.setToolTip(
            "Applies only to Gemma 4 models. Skips reasoning/planning via API flags, "
            "system instructions, and an empty thought-channel prefill."
        )
        layout.addWidget(self._disable_thinking_cb)

        stt_row = QHBoxLayout()
        stt_row.addWidget(QLabel("Speech-to-text:"))
        self._whisper_combo = QComboBox()
        for model_name in WHISPER_MODEL_OPTIONS:
            self._whisper_combo.addItem(model_name, model_name)
        whisper_idx = self._whisper_combo.findData(self._store.whisper_model)
        if whisper_idx >= 0:
            self._whisper_combo.setCurrentIndex(whisper_idx)
        self._whisper_combo.setToolTip(
            "faster-whisper model used for microphone transcription. Takes effect on the next voice session."
        )
        stt_row.addWidget(self._whisper_combo, stretch=1)
        layout.addLayout(stt_row)

        tts_engine_row = QHBoxLayout()
        tts_engine_row.addWidget(QLabel("TTS engine:"))
        self._tts_engine_combo = QComboBox()
        self._tts_engine_combo.addItem("Piper", TTS_ENGINE_PIPER)
        self._tts_engine_combo.addItem("pocket-tts", TTS_ENGINE_POCKET)
        engine_idx = self._tts_engine_combo.findData(self._store.tts_engine)
        if engine_idx >= 0:
            self._tts_engine_combo.setCurrentIndex(engine_idx)
        self._tts_engine_combo.setToolTip(
            "Speech synthesis backend. Piper uses local .onnx files; "
            "pocket-tts uses the pocket-tts CLI (pip install pocket-tts)."
        )
        self._tts_engine_combo.currentIndexChanged.connect(self._on_tts_engine_changed)
        tts_engine_row.addWidget(self._tts_engine_combo, stretch=1)
        layout.addLayout(tts_engine_row)

        tts_voice_row = QHBoxLayout()
        tts_voice_row.addWidget(QLabel("TTS voice:"))
        self._tts_voice_combo = QComboBox()
        tts_voice_row.addWidget(self._tts_voice_combo, stretch=1)
        layout.addLayout(tts_voice_row)
        self._on_tts_engine_changed()

        speech_speed_row = QHBoxLayout()
        speech_speed_row.addWidget(QLabel("Speech speed:"))
        self._speech_speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speech_speed_slider.setRange(
            int(TTS_SPEECH_SPEED_MIN * TTS_SPEECH_SPEED_SLIDER_SCALE),
            int(TTS_SPEECH_SPEED_MAX * TTS_SPEECH_SPEED_SLIDER_SCALE),
        )
        self._speech_speed_slider.setValue(
            int(round(self._store.tts_speech_speed * TTS_SPEECH_SPEED_SLIDER_SCALE))
        )
        self._speech_speed_slider.setToolTip(
            "1.0 = normal. Piper uses synthesis timing; pocket-tts uses afplay rate scaling."
        )
        self._speech_speed_slider.valueChanged.connect(self._on_speech_speed_slider_changed)
        speech_speed_row.addWidget(self._speech_speed_slider, stretch=1)
        self._speech_speed_value_label = QLabel(f"{self._store.tts_speech_speed:.2f}×")
        self._speech_speed_value_label.setMinimumWidth(40)
        speech_speed_row.addWidget(self._speech_speed_value_label)
        layout.addLayout(speech_speed_row)

        mic_row = QHBoxLayout()
        mic_row.addWidget(QLabel("Microphone:"))
        self._mic_combo = QComboBox()
        self._mic_device_ids: list[int | None] = []
        for device_id, label in list_input_devices():
            self._mic_combo.addItem(label)
            self._mic_device_ids.append(device_id)
        if self._store.input_device in self._mic_device_ids:
            self._mic_combo.setCurrentIndex(self._mic_device_ids.index(self._store.input_device))
        self._mic_combo.setToolTip("Select the audio input device for voice capture.")
        mic_row.addWidget(self._mic_combo, stretch=1)
        layout.addLayout(mic_row)

        vad_row = QHBoxLayout()
        vad_row.addWidget(QLabel("VAD sensitivity:"))
        self._vad_combo = QComboBox()
        self._vad_combo.addItem("Auto (calibrated)", None)
        self._vad_combo.addItem("High (0.006)", 0.006)
        self._vad_combo.addItem("Normal (0.012)", 0.012)
        self._vad_combo.addItem("Low (0.025)", 0.025)
        if self._store.vad_threshold is not None:
            for i in range(self._vad_combo.count()):
                if self._vad_combo.itemData(i) == self._store.vad_threshold:
                    self._vad_combo.setCurrentIndex(i)
                    break
        self._vad_combo.setToolTip(
            "Voice-activity detection threshold. Use Auto unless the mic is too sensitive or deaf."
        )
        vad_row.addWidget(self._vad_combo, stretch=1)
        layout.addLayout(vad_row)

        silence_row = QHBoxLayout()
        silence_row.addWidget(QLabel("Silence before end:"))
        self._silence_end_spin = QSpinBox()
        self._silence_end_spin.setRange(SILENCE_END_MS_MIN, SILENCE_END_MS_MAX)
        self._silence_end_spin.setSingleStep(100)
        self._silence_end_spin.setSuffix(" ms")
        self._silence_end_spin.setValue(self._store.silence_end_ms)
        self._silence_end_spin.setToolTip(
            "How long to wait in silence after you stop speaking before the utterance ends. "
            "Increase for longer pauses mid-sentence (default 1200 ms)."
        )
        silence_row.addWidget(self._silence_end_spin)
        silence_row.addStretch(1)
        layout.addLayout(silence_row)

        layout.addWidget(QLabel("Active system prompt:"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_host = QWidget()
        self._list_layout = QVBoxLayout(list_host)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        scroll.setWidget(list_host)
        layout.addWidget(scroll, stretch=1)

        self._button_group = QButtonGroup(self)
        self._button_group.setExclusive(True)
        self._rebuild_prompt_list()

        add_btn = QPushButton("Add prompt…")
        add_btn.clicked.connect(self._add_prompt)
        layout.addWidget(add_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_store(self) -> PromptStore:
        return self._store

    def _on_temp_slider_changed(self, value: int) -> None:
        self._temp_value_label.setText(f"{value / LLM_TEMPERATURE_SLIDER_SCALE:.2f}")

    def _on_speech_speed_slider_changed(self, value: int) -> None:
        speed = value / TTS_SPEECH_SPEED_SLIDER_SCALE
        self._speech_speed_value_label.setText(f"{speed:.2f}×")

    def _populate_tts_voice_combo(self) -> None:
        engine = str(self._tts_engine_combo.currentData() or TTS_ENGINE_PIPER)
        self._tts_voice_combo.blockSignals(True)
        self._tts_voice_combo.clear()
        if engine == TTS_ENGINE_POCKET:
            voices = list_pocket_voices()
            stored_voice = resolve_pocket_voice(self._store.pocket_voice)
            empty_label = "(pocket-tts not available)"
            self._tts_voice_combo.setToolTip(
                "Built-in pocket-tts voices (discovered at runtime from the pocket-tts install)."
            )
        else:
            voices = list_piper_voices()
            stored_voice = resolve_piper_voice(self._store.piper_voice)
            empty_label = f"(no Piper voices in {PIPER_VOICES_DIR})"
            self._tts_voice_combo.setToolTip(
                f"Piper .onnx voices scanned at runtime from {PIPER_VOICES_DIR}."
            )
        if not voices:
            self._tts_voice_combo.addItem(empty_label, "")
            self._tts_voice_combo.setEnabled(False)
        else:
            self._tts_voice_combo.setEnabled(True)
            seen: set[str] = set()
            for value, label in voices:
                self._tts_voice_combo.addItem(label, value)
                seen.add(value)
            if engine == TTS_ENGINE_PIPER and stored_voice not in seen and Path(stored_voice).is_file():
                self._tts_voice_combo.addItem(f"{Path(stored_voice).stem} (custom)", stored_voice)
            voice_idx = self._tts_voice_combo.findData(stored_voice)
            if voice_idx >= 0:
                self._tts_voice_combo.setCurrentIndex(voice_idx)
        self._tts_voice_combo.blockSignals(False)

    def _on_tts_engine_changed(self, _index: int = 0) -> None:
        self._populate_tts_voice_combo()

    def _rebuild_prompt_list(self) -> None:
        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._radio_by_id.clear()
        for btn in self._button_group.buttons():
            self._button_group.removeButton(btn)

        default_radio = QRadioButton("System default (use LM Studio template)")
        self._button_group.addButton(default_radio)
        self._list_layout.addWidget(default_radio)
        self._radio_by_id[SYSTEM_DEFAULT_ID] = default_radio

        for entry in self._store.prompts:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            radio = QRadioButton(entry.name or "Untitled")
            radio.setToolTip(entry.text[:200] + ("…" if len(entry.text) > 200 else ""))
            self._button_group.addButton(radio)
            self._radio_by_id[entry.id] = radio
            row_layout.addWidget(radio, stretch=1)

            edit_btn = QPushButton()
            edit_btn.setToolTip("Edit prompt")
            edit_btn.setStyleSheet(_edit_button_stylesheet())
            edit_btn.clicked.connect(lambda _=False, pid=entry.id: self._edit_prompt(pid))
            row_layout.addWidget(edit_btn)

            del_btn = QPushButton()
            del_btn.setToolTip("Delete prompt")
            del_btn.setStyleSheet(_trash_button_stylesheet())
            del_btn.clicked.connect(lambda _=False, pid=entry.id: self._delete_prompt(pid))
            row_layout.addWidget(del_btn)

            self._list_layout.addWidget(row)

        self._list_layout.addStretch(1)
        self._select_active_radio()

    def _select_active_radio(self) -> None:
        active = self._store.active_id or SYSTEM_DEFAULT_ID
        radio = self._radio_by_id.get(active) or self._radio_by_id.get(SYSTEM_DEFAULT_ID)
        if radio:
            radio.setChecked(True)

    def _sync_active_from_ui(self) -> None:
        for prompt_id, radio in self._radio_by_id.items():
            if radio.isChecked():
                self._store.active_id = None if prompt_id == SYSTEM_DEFAULT_ID else prompt_id
                return

    def _add_prompt(self) -> None:
        dlg = PromptEditDialog(
            self,
            title="New prompt",
            name="New prompt",
            text=DEFAULT_PROMPT_SUGGESTION,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, text = dlg.values()
        if not name:
            name = "Untitled"
        entry = PromptEntry(id=uuid.uuid4().hex[:10], name=name, text=text)
        self._store.prompts.append(entry)
        self._store.active_id = entry.id
        self._rebuild_prompt_list()

    def _edit_prompt(self, prompt_id: str) -> None:
        entry = self._store.find_prompt(prompt_id)
        if entry is None:
            return
        dlg = PromptEditDialog(self, title="Edit prompt", name=entry.name, text=entry.text)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, text = dlg.values()
        entry.name = name or "Untitled"
        entry.text = text
        self._rebuild_prompt_list()

    def _delete_prompt(self, prompt_id: str) -> None:
        entry = self._store.find_prompt(prompt_id)
        if entry is None:
            return
        dlg = PromptDeleteConfirmDialog(entry, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._store.prompts = [p for p in self._store.prompts if p.id != prompt_id]
        if self._store.active_id == prompt_id:
            self._store.active_id = None
        self._rebuild_prompt_list()

    def accept(self) -> None:
        self._sync_active_from_ui()
        self._store.max_tokens = self._max_tokens_spin.value()
        self._store.temperature = self._temp_slider.value() / LLM_TEMPERATURE_SLIDER_SCALE
        self._store.disable_gemma_thinking = self._disable_thinking_cb.isChecked()
        self._store.whisper_model = str(self._whisper_combo.currentData() or WHISPER_MODEL)
        engine = str(self._tts_engine_combo.currentData() or TTS_ENGINE_PIPER)
        self._store.tts_engine = engine
        voice_data = self._tts_voice_combo.currentData()
        if engine == TTS_ENGINE_POCKET:
            if voice_data:
                self._store.pocket_voice = resolve_pocket_voice(str(voice_data))
        else:
            self._store.piper_voice = resolve_piper_voice(
                str(voice_data or default_piper_voice_path())
            )
        self._store.tts_speech_speed = (
            self._speech_speed_slider.value() / TTS_SPEECH_SPEED_SLIDER_SCALE
        )
        self._store.input_device = self._mic_device_ids[self._mic_combo.currentIndex()]
        self._store.vad_threshold = self._vad_combo.currentData()
        self._store.silence_end_ms = self._silence_end_spin.value()
        super().accept()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

_MODEL_DROPDOWN_TRIGGER_STYLE = (
    "QFrame#modelDropdownTrigger { border: 1px solid #767676; border-radius: 4px; "
    "background: palette(base); }"
    "QLabel#modelDropdownTriggerLabel { background: transparent; border: none; "
    "padding: 4px 0px 4px 8px; }"
    "QLabel#modelDropdownTriggerVision { background: transparent; border: none; "
    "padding: 4px 8px 4px 4px; }"
)
_MODEL_DROPDOWN_POPUP_STYLE = (
    "QFrame { border: 1px solid #767676; background: palette(base); }"
    "QListWidget { border: none; outline: none; background: palette(base); }"
    "QListWidget::item { padding: 4px 8px; }"
    "QListWidget::item:selected { background: palette(highlight); "
    "color: palette(highlighted-text); }"
)


class _DropdownTrigger(QFrame):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class _ModelDropdownRowDelegate(QStyledItemDelegate):
    VISION_ROLE = Qt.ItemDataRole.UserRole + 1

    def __init__(self, vision_pixmap: QPixmap, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._vision_pixmap = vision_pixmap
        self._vision_icon = QIcon(vision_pixmap) if not vision_pixmap.isNull() else QIcon()
        self._icon_w = vision_pixmap.width() if not vision_pixmap.isNull() else 0
        self._icon_h = vision_pixmap.height() if not vision_pixmap.isNull() else 0

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem,
            opt,
            painter,
            opt.widget,
        )

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        show_vision = bool(index.data(self.VISION_ROLE))
        inner = opt.rect.adjusted(8, 0, -8, 0)
        painter.setPen(opt.palette.color(
            QPalette.ColorRole.HighlightedText
            if opt.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        ))
        painter.drawText(
            inner,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            text,
        )
        if show_vision and not self._vision_icon.isNull():
            text_w = painter.fontMetrics().horizontalAdvance(text)
            icon_x = inner.left() + text_w + VISION_ICON_GAP
            icon_y = inner.center().y() - self._icon_h // 2
            self._vision_icon.paint(
                painter,
                QRect(icon_x, icon_y, self._icon_w, self._icon_h),
                Qt.AlignmentFlag.AlignCenter,
                QIcon.Mode.Normal,
                QIcon.State.Off,
            )
        painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(base.height(), self._icon_h + 8))


class ModelDropdown(QWidget):
    """Select-only model picker: popup list opens below the field, not over it."""

    currentIndexChanged = Signal(int)

    _MAX_VISIBLE_ROWS = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, Any, bool]] = []
        self._current_index = -1
        self._popup: QFrame | None = None
        self._list: QListWidget | None = None
        self._vision_pixmap = _vision_pixmap()
        self._vision_icon_w = self._vision_pixmap.width() if not self._vision_pixmap.isNull() else 0
        self._vision_icon_h = self._vision_pixmap.height() if not self._vision_pixmap.isNull() else 0

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self._trigger = _DropdownTrigger()
        self._trigger.setObjectName("modelDropdownTrigger")
        self._trigger.setStyleSheet(_MODEL_DROPDOWN_TRIGGER_STYLE)
        self._trigger.setCursor(Qt.CursorShape.PointingHandCursor)
        trigger_row = QHBoxLayout(self._trigger)
        trigger_row.setContentsMargins(0, 0, 0, 0)
        trigger_row.setSpacing(0)
        self._name_box = QWidget()
        self._name_box.setStyleSheet("background: transparent; border: none;")
        name_row = QHBoxLayout(self._name_box)
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(VISION_ICON_GAP)
        self._trigger_label = QLabel()
        self._trigger_label.setObjectName("modelDropdownTriggerLabel")
        self._trigger_vision = QLabel()
        self._trigger_vision.setObjectName("modelDropdownTriggerVision")
        if self._vision_icon_w and self._vision_icon_h:
            self._trigger_vision.setFixedSize(self._vision_icon_w, self._vision_icon_h)
        self._trigger_vision.setScaledContents(True)
        self._trigger_vision.hide()
        name_row.addWidget(self._trigger_label, 0)
        name_row.addWidget(self._trigger_vision, 0)
        name_row.addStretch(1)
        trigger_row.addWidget(self._name_box, stretch=1)
        self._trigger.clicked.connect(self._toggle_popup)
        row.addWidget(self._trigger, stretch=1)

    def _ensure_popup(self) -> None:
        if self._popup is not None:
            return
        self._popup = QFrame(None, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._popup.setStyleSheet(_MODEL_DROPDOWN_POPUP_STYLE)
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(1, 1, 1, 1)
        popup_layout.setSpacing(0)
        self._list = QListWidget(self._popup)
        self._list.setItemDelegate(_ModelDropdownRowDelegate(self._vision_pixmap, self._list))
        self._list.itemClicked.connect(self._on_list_item_clicked)
        popup_layout.addWidget(self._list)

    def _toggle_popup(self) -> None:
        self._ensure_popup()
        assert self._popup is not None
        if self._popup.isVisible():
            self._popup.hide()
            return
        self._show_popup()

    def _show_popup(self) -> None:
        self._ensure_popup()
        assert self._popup is not None and self._list is not None
        self._list.clear()
        for label, _, vision in self._items:
            row_item = QListWidgetItem(label)
            row_item.setData(_ModelDropdownRowDelegate.VISION_ROLE, vision)
            self._list.addItem(row_item)
        if not self._items:
            return
        if 0 <= self._current_index < self._list.count():
            self._list.setCurrentRow(self._current_index)
        row_h = max(self._list.sizeHintForRow(0), 24)
        visible_rows = min(len(self._items), self._MAX_VISIBLE_ROWS)
        self._popup.setFixedWidth(self._trigger.width())
        self._list.setFixedHeight(row_h * visible_rows + 2)
        anchor = self._trigger.mapToGlobal(QPoint(0, self._trigger.height()))
        self._popup.move(anchor)
        self._popup.show()
        self._list.setFocus()

    def _on_list_item_clicked(self) -> None:
        assert self._list is not None and self._popup is not None
        row = self._list.currentRow()
        if self._set_current_index(row, emit=True) and self._popup.isVisible():
            self._popup.hide()

    def _set_current_index(self, index: int, *, emit: bool) -> bool:
        if index < 0 or index >= len(self._items):
            return False
        self._current_index = index
        label, _, vision = self._items[index]
        self._trigger_label.setText(label)
        if vision and not self._vision_pixmap.isNull():
            self._trigger_vision.setPixmap(self._vision_pixmap)
            self._trigger_vision.show()
        else:
            self._trigger_vision.clear()
            self._trigger_vision.hide()
        if emit and not self.signalsBlocked():
            self.currentIndexChanged.emit(index)
        return True

    def addItem(self, text: str, userData: Any = None, *, vision: bool = False) -> None:
        self._items.append((text, userData, vision))

    def clear(self) -> None:
        self._items.clear()
        self._current_index = -1
        self._trigger_label.setText("")
        self._trigger_vision.clear()
        self._trigger_vision.hide()

    def count(self) -> int:
        return len(self._items)

    def itemData(self, index: int) -> Any:
        if 0 <= index < len(self._items):
            return self._items[index][1]
        return None

    def currentData(self) -> Any:
        return self.itemData(self._current_index)

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        self._set_current_index(index, emit=False)

    def setToolTip(self, text: str) -> None:
        self._trigger.setToolTip(text)
        self._trigger_label.setToolTip(text)
        super().setToolTip(text)


_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _is_image_path(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_SUFFIXES


def _first_image_path_from_mime(mime) -> Path | None:
    if not mime.hasUrls():
        return None
    for url in mime.urls():
        path = Path(url.toLocalFile())
        if _is_image_path(path):
            return path
    return None


class ImageDropZone(QLabel):
    image_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(160)
        self.setStyleSheet(
            "QLabel { border: 2px dashed #888; border-radius: 8px; "
            "color: #666; background: #000000; }"
        )
        self._image_path: Path | None = None
        self.setText("Drag & drop an image here\n(jpeg, png, webp, gif)")
        self.setWordWrap(True)

    @property
    def image_path(self) -> Path | None:
        return self._image_path

    def clear_image(self) -> None:
        self._image_path = None
        self.setPixmap(QPixmap())
        self.setText("Drag & drop an image here\n(jpeg, png, webp, gif)")

    def load_image(self, path: Path | str) -> bool:
        path = Path(path)
        if not _is_image_path(path) or not path.is_file():
            return False
        self._image_path = path
        pix = QPixmap(str(path))
        if not pix.isNull():
            scaled = pix.scaled(
                self.width() - 20,
                self.height() - 20,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.setPixmap(scaled)
            self.setText("")
        else:
            self.setPixmap(QPixmap())
            self.setText(path.name)
        return True

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _first_image_path_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if _first_image_path_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        path = _first_image_path_from_mime(event.mimeData())
        if path is None:
            return
        if self.load_image(path):
            self.image_dropped.emit(str(path))
            event.acceptProposedAction()


class TranscriptEdit(QTextEdit):
    image_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _first_image_path_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if _first_image_path_from_mime(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        path = _first_image_path_from_mime(event.mimeData())
        if path is not None:
            self.image_dropped.emit(str(path))
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Voice + Vision Demo")
        self.resize(720, 680)

        self._worker: VoiceLoopWorker | None = None
        self._pending_continuous: bool | None = None
        self._restarting_voice = False
        self._awaiting_worker_stop = False
        self._chat_history: list[ChatTurn] = []
        self._pending_redo_on_start: ChatTurn | None = None
        self._prompt_store = PromptStore.load()
        self._chat_models: list[DemoChatModel] = []

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Model + controls
        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("LLM:"))
        self.model_combo = ModelDropdown()
        self.model_combo.setToolTip(
            "Local LM Studio chat models. Vision-capable models show the eye icon and support image drop."
        )
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        model_row.addWidget(self.model_combo, stretch=1)

        refresh_models_btn = QPushButton("Refresh")
        refresh_models_btn.setToolTip("Rescan local LM Studio models")
        refresh_models_btn.clicked.connect(self._refresh_model_list)
        model_row.addWidget(refresh_models_btn)

        settings_btn = QPushButton("Settings…")
        settings_btn.clicked.connect(self._open_settings)
        model_row.addWidget(settings_btn)
        layout.addLayout(model_row)

        content_row = QHBoxLayout()

        transcript_group = QGroupBox("Conversation")
        transcript_layout = QVBoxLayout(transcript_group)
        self.transcript = TranscriptEdit()
        self.transcript.setReadOnly(True)
        self.transcript.image_dropped.connect(self._attach_image)
        transcript_layout.addWidget(self.transcript)
        content_row.addWidget(transcript_group, stretch=1)

        self.img_group = QGroupBox("Image (optional — attached to next voice turn)")
        self.img_group.setMinimumWidth(220)
        img_layout = QVBoxLayout(self.img_group)
        self.drop_zone = ImageDropZone()
        self.drop_zone.image_dropped.connect(self._on_image_dropped)
        img_layout.addWidget(self.drop_zone, stretch=1)
        self.clear_img_btn = QPushButton("Clear image")
        self.clear_img_btn.clicked.connect(self._clear_image)
        img_layout.addWidget(self.clear_img_btn)
        self.img_group.hide()
        content_row.addWidget(self.img_group)

        layout.addLayout(content_row, stretch=1)

        # Buttons
        btn_row = QHBoxLayout()
        self.talk_btn = QPushButton("Talk (once)")
        self.talk_btn.clicked.connect(self._talk_once)
        btn_row.addWidget(self.talk_btn)

        self.hands_free_btn = QPushButton("Start hands-free")
        self.hands_free_btn.setCheckable(True)
        self.hands_free_btn.toggled.connect(self._toggle_hands_free)
        btn_row.addWidget(self.hands_free_btn)

        btn_row.addStretch(1)

        self.undo_btn = _make_icon_tool_button(
            "Undo last turn",
            _icon_pixmap(lambda p, s: _draw_curved_arrow_icon(p, s, redo=False)),
            self._undo_turn,
        )
        btn_row.addWidget(self.undo_btn)

        self.redo_btn = _make_icon_tool_button(
            "Redo last response",
            _icon_pixmap(lambda p, s: _draw_curved_arrow_icon(p, s, redo=True)),
            self._redo_turn,
        )
        btn_row.addWidget(self.redo_btn)

        self.copy_btn = _make_symbol_tool_button(
            "Copy last response to clipboard",
            "⧉",
            self._copy_last_response,
        )
        btn_row.addWidget(self.copy_btn)

        self.clear_btn = _make_icon_tool_button(
            "Clear conversation",
            _icon_pixmap(_draw_clear_chat_icon),
            self._clear_conversation,
        )
        btn_row.addWidget(self.clear_btn)

        self.stop_talking_btn = _make_icon_tool_button(
            "Stop talking (abort speech)",
            _icon_pixmap(_draw_prohibited_icon),
            self._stop_talking,
        )
        btn_row.addWidget(self.stop_talking_btn)

        self.stop_btn = _make_icon_tool_button(
            "Stop voice session",
            _icon_pixmap(_draw_stop_sign_icon),
            self._stop_all,
        )
        # btn_row.addWidget(self.stop_btn)

        qmark_pix = QPixmap()
        qmark_pix.loadFromData(_QMARK_PNG_BYTES)
        help_btn = _make_icon_tool_button(VOICE_COMMANDS_TOOLTIP, qmark_pix)
        btn_row.addWidget(help_btn)

        layout.addLayout(btn_row)

        status_frame = QFrame()
        status_frame.setObjectName("voiceStatusBar")
        status_frame.setStyleSheet(STATUS_BAR_FRAME_STYLE)
        status_frame.setMinimumHeight(36)
        status_layout = QVBoxLayout(status_frame)
        status_layout.setContentsMargins(10, 8, 10, 8)
        self.status_label = QLabel("Ready. Start LM Studio server and pick a local LLM.")
        self.status_label.setStyleSheet(STATUS_LABEL_STYLE)
        self.status_label.setWordWrap(True)
        status_layout.addWidget(self.status_label)
        layout.addWidget(status_frame)

        self._refresh_model_list()

    def _append_system(self, text: str) -> None:
        self.transcript.append(f"<span style='color:#666'><i>{text}</i></span>")

    def _append_command_feedback(self, text: str) -> None:
        self.transcript.append(f"<span style='color:cyan'><i>{text}</i></span>")

    @Slot(str)
    def _on_command_feedback(self, text: str) -> None:
        self._append_command_feedback(text)

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)

    @Slot(str)
    def _on_status(self, text: str) -> None:
        self._set_status(text)
        if self._awaiting_worker_stop and not self._restarting_voice:
            if text in ("Hands-free stopped.", "Ready."):
                QTimer.singleShot(0, self._maybe_finalize_worker_stop_ui)

    @Slot(str)
    def _on_user(self, text: str) -> None:
        self.transcript.append(f"{_transcript_role_label('You')} {text}")

    @Slot(str)
    def _on_assistant(self, text: str) -> None:
        self.transcript.append(f"{_transcript_role_label('Assistant')} {text}")
        self.transcript.append("")

    @Slot(str)
    def _on_error(self, text: str) -> None:
        self.transcript.append(f"<span style='color:#c00'><b>Error:</b> {text}</span>")
        self._set_status(text)

    @Slot()
    def _on_chat_cleared(self) -> None:
        self.transcript.clear()
        self._chat_history.clear()

    @Slot()
    def _on_conversation_display_refresh(self) -> None:
        self._refresh_conversation_display()

    @Slot(str)
    def _on_copy_to_clipboard(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    @Slot()
    def _on_stop_requested(self) -> None:
        if self.hands_free_btn.isChecked():
            self.hands_free_btn.blockSignals(True)
            self.hands_free_btn.setChecked(False)
            self.hands_free_btn.setText("Start hands-free")
            self.hands_free_btn.blockSignals(False)
        self._stop_running_worker()
        self._set_idle_ui_after_stop()

    def _finalize_worker_stop_ui(self) -> None:
        if self._restarting_voice or not self._awaiting_worker_stop:
            return
        self._awaiting_worker_stop = False
        self.talk_btn.setEnabled(True)
        if self.hands_free_btn.isChecked():
            self._sync_hands_free_ui(False)
        else:
            self.hands_free_btn.setText("Start hands-free")
        self._set_status("Stopped.")

    def _maybe_finalize_worker_stop_ui(self) -> None:
        if not self._awaiting_worker_stop or self._restarting_voice:
            return
        if self._worker is None or not self._worker.isRunning():
            self._finalize_worker_stop_ui()

    def _poll_worker_shutdown(self) -> None:
        if not self._awaiting_worker_stop or self._restarting_voice:
            return
        worker = self._worker
        if worker is not None and worker.isRunning():
            QTimer.singleShot(100, self._poll_worker_shutdown)
            return
        if worker is not None:
            self._sync_history_from_worker(worker)
        self._worker = None
        self._finalize_worker_stop_ui()

    def _set_idle_ui_after_stop(self) -> None:
        """Re-enable Talk only after the worker thread has released PortAudio."""
        self._awaiting_worker_stop = True
        if self._worker is None or not self._worker.isRunning():
            self._finalize_worker_stop_ui()
        else:
            self.talk_btn.setEnabled(False)
            self._set_status("Stopping…")
            QTimer.singleShot(100, self._poll_worker_shutdown)

    @Slot()
    def _on_worker_session_exited(self) -> None:
        if not self._awaiting_worker_stop or self._restarting_voice:
            return
        worker = self.sender()
        if worker is self._worker:
            self._sync_history_from_worker()
            self._worker = None
        self._finalize_worker_stop_ui()

    def _append_history_turn(self, turn: ChatTurn) -> None:
        if turn.role == "user":
            img_note = ""
            if turn.image_path:
                img_note = f" [+image: {Path(turn.image_path).name}]"
            self.transcript.append(f"{_transcript_role_label('You')} {turn.text}{img_note}")
        elif turn.role == "assistant":
            self.transcript.append(f"{_transcript_role_label('Assistant')} {turn.text}")
            self.transcript.append("")

    def _refresh_conversation_display(self) -> None:
        """Rebuild transcript from chat history (user/assistant turns only)."""
        self._sync_history_from_worker()
        self.transcript.clear()
        for turn in self._chat_history:
            self._append_history_turn(turn)

    def _refresh_model_list(self) -> None:
        previous_key = self._selected_model_key()
        self._chat_models = discover_demo_chat_models()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        if not self._chat_models:
            self.model_combo.addItem("(no eligible models found)", "")
        else:
            for item in self._chat_models:
                self.model_combo.addItem(
                    item.label, item.model_key, vision=item.supports_vision
                )
        target_key = previous_key or self._prompt_store.active_model
        if target_key and self._select_model_key(target_key):
            pass
        elif self._chat_models:
            self._select_model_key(resolve_default_model_key(self._chat_models))
        self.model_combo.blockSignals(False)
        if self.model_combo.currentData():
            self._on_model_changed(self.model_combo.currentIndex())

    def _selected_model_key(self) -> str:
        return str(self.model_combo.currentData() or "").strip()

    def _model_supports_vision(self, model_key: str) -> bool:
        if not model_key:
            return False
        for item in self._chat_models:
            if _model_keys_match(item.model_key, model_key):
                return item.supports_vision
        return _heuristic_vision_capable(model_key)

    def _refresh_image_section_visibility(self) -> None:
        has_image = self.drop_zone.image_path is not None
        supports_vision = self._model_supports_vision(self._selected_model_key())
        self.img_group.setVisible(has_image and supports_vision)

    def _update_image_section_visibility(self) -> None:
        supports_vision = self._model_supports_vision(self._selected_model_key())
        if not supports_vision:
            self._clear_image()
        else:
            self._refresh_image_section_visibility()
            self._sync_worker_attached_image()
        if self._worker is not None:
            self._worker.set_supports_vision(supports_vision)

    def _select_model_key(self, model_key: str) -> bool:
        for idx in range(self.model_combo.count()):
            if _model_keys_match(str(self.model_combo.itemData(idx) or ""), model_key):
                self.model_combo.setCurrentIndex(idx)
                return True
        return False

    def _active_system_prompt(self) -> str | None:
        return self._prompt_store.active_system_prompt()

    def _apply_prompt_store_to_worker(self, worker: VoiceLoopWorker) -> None:
        worker.set_tts_engine(self._prompt_store.tts_engine)
        worker.set_piper_voice(self._prompt_store.piper_voice)
        worker.set_pocket_voice(self._prompt_store.pocket_voice)
        worker.set_tts_speech_speed(self._prompt_store.tts_speech_speed)
        worker.set_whisper_model(self._prompt_store.whisper_model)
        worker.set_input_device(self._prompt_store.input_device)
        worker.set_vad_threshold(self._prompt_store.vad_threshold)
        worker.set_silence_end_ms(self._prompt_store.silence_end_ms)
        worker.set_max_tokens(self._prompt_store.max_tokens)
        worker.set_temperature(self._prompt_store.temperature)
        worker.set_disable_gemma_thinking(self._prompt_store.disable_gemma_thinking)
        worker.set_system_prompt(self._active_system_prompt())

    def _open_settings(self) -> None:
        dlg = PromptSettingsDialog(self._prompt_store, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._prompt_store = dlg.result_store()
        self._prompt_store.save()
        if self._worker is not None:
            self._apply_prompt_store_to_worker(self._worker)

    def _on_model_changed(self, index: int) -> None:
        if index < 0:
            return
        model_key = str(self.model_combo.itemData(index) or "").strip()
        if not model_key:
            return
        self._prompt_store.active_model = model_key
        self._prompt_store.save()
        if self._worker is not None:
            self._worker.set_model_key(model_key)
        self._update_image_section_visibility()

    def _on_image_dropped(self, path: str) -> None:
        self._attach_image(path)

    def _attach_image(self, path: str) -> None:
        if not self._model_supports_vision(self._selected_model_key()):
            self._append_system("Selected model does not support vision; image not attached.")
            return
        if not self.drop_zone.load_image(path):
            return
        self._refresh_image_section_visibility()
        self._sync_worker_attached_image()
        self._append_system(f"Image attached to turns: {Path(path).name}")

    def _clear_image_ui(self) -> None:
        self.drop_zone.clear_image()
        self.img_group.hide()

    def _clear_image(self) -> None:
        self._clear_image_ui()
        self._sync_worker_attached_image()

    def _sync_worker_attached_image(self) -> None:
        worker = self._worker
        if worker is None:
            return
        if (
            self._model_supports_vision(self._selected_model_key())
            and self.drop_zone.image_path
        ):
            worker.set_attached_image(self.drop_zone.image_path)
        else:
            worker.set_attached_image(None)

    def _halt_worker(self) -> None:
        """Signal the worker to stop. Never blocks the UI thread."""
        worker = self._worker
        if worker is None or not worker.isRunning():
            return
        self._sync_history_from_worker(worker)
        worker.set_continuous(False)
        worker.stop_now()
        worker.requestInterruption()

    def _stop_running_worker(self) -> None:
        self._pending_continuous = None
        self._restarting_voice = False
        self._halt_worker()

    def _make_worker(self) -> VoiceLoopWorker:
        # No QObject parent — QThread must not be parented to the GUI thread.
        worker = VoiceLoopWorker()
        model_key = self._selected_model_key() or self._prompt_store.active_model
        worker.set_model_key(model_key)
        self._apply_prompt_store_to_worker(worker)
        worker.set_supports_vision(self._model_supports_vision(model_key))
        with worker._history_lock:
            worker._history = list(self._chat_history)
        if self._pending_redo_on_start is not None:
            worker.set_pending_redo(self._pending_redo_on_start)
            self._pending_redo_on_start = None
        worker.status.connect(self._on_status)
        worker.user_said.connect(self._on_user)
        worker.assistant_said.connect(self._on_assistant)
        worker.error.connect(self._on_error)
        worker.chat_cleared.connect(self._on_chat_cleared)
        worker.conversation_display_refresh.connect(self._on_conversation_display_refresh)
        worker.stop_requested.connect(self._on_stop_requested)
        worker.copy_to_clipboard.connect(self._on_copy_to_clipboard)
        worker.command_feedback.connect(self._on_command_feedback)
        worker.request_image_sync.connect(
            self._sync_worker_attached_image,
            Qt.ConnectionType.BlockingQueuedConnection,
        )
        worker.finished.connect(self._on_worker_finished)
        worker.session_exited.connect(self._on_worker_session_exited)
        return worker

    def _sync_history_from_worker(self, worker: VoiceLoopWorker | None = None) -> None:
        w = worker if worker is not None else self._worker
        if w is not None:
            with w._history_lock:
                self._chat_history = list(w._history)

    def _queue_image_for_turn(self) -> None:
        self._sync_worker_attached_image()

    def _launch_worker(self, continuous: bool) -> None:
        self._awaiting_worker_stop = False
        self._worker = self._make_worker()
        self._queue_image_for_turn()
        self._worker.set_continuous(continuous)
        self._worker.start()

    def _sync_hands_free_ui(self, active: bool) -> None:
        self.hands_free_btn.blockSignals(True)
        self.hands_free_btn.setChecked(active)
        self.hands_free_btn.setText("Stop hands-free" if active else "Start hands-free")
        self.hands_free_btn.blockSignals(False)
        self.talk_btn.setEnabled(not active)

    @Slot()
    def _deferred_start_worker(self) -> None:
        continuous = self._pending_continuous
        self._pending_continuous = None
        if continuous is None:
            self._restarting_voice = False
            return
        if self._worker is not None and self._worker.isRunning():
            return
        # Brief gap after the previous worker exits so macOS can release the mic.
        QTimer.singleShot(150, lambda c=continuous: self._finish_deferred_start(c))

    def _finish_deferred_start(self, continuous: bool) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._restarting_voice = False
            return
        self._launch_worker(continuous)
        self._restarting_voice = False
        if continuous:
            self._sync_hands_free_ui(True)

    def _start_worker(self, continuous: bool) -> None:
        old = self._worker
        if old is not None and old.isRunning():
            self._pending_continuous = continuous
            self._restarting_voice = True
            old.finished.connect(
                self._deferred_start_worker,
                Qt.ConnectionType.SingleShotConnection,
            )
            self._halt_worker()
            return
        self._pending_continuous = None
        self._restarting_voice = False
        self._launch_worker(continuous)

    def _on_worker_finished(self) -> None:
        finished_worker = self.sender()
        was_current = finished_worker is self._worker
        if was_current:
            self._sync_history_from_worker()
            self._worker = None
        if self._restarting_voice:
            return
        if self._awaiting_worker_stop:
            self._finalize_worker_stop_ui()
        elif was_current:
            self.talk_btn.setEnabled(True)
            if self.hands_free_btn.isChecked():
                self._sync_hands_free_ui(False)
            else:
                self.hands_free_btn.setText("Start hands-free")

    def _talk_once(self) -> None:
        self.talk_btn.setEnabled(False)
        self._start_worker(continuous=False)

    def _toggle_hands_free(self, checked: bool) -> None:
        if checked:
            self._sync_hands_free_ui(True)
            self._start_worker(continuous=True)
        else:
            self._stop_running_worker()
            self._sync_hands_free_ui(False)
            self._set_idle_ui_after_stop()

    def _pop_history_exchange(self) -> bool:
        if not self._chat_history:
            return False
        while self._chat_history and self._chat_history[-1].role == "assistant":
            self._chat_history.pop()
        if not self._chat_history or self._chat_history[-1].role != "user":
            return False
        self._chat_history.pop()
        return True

    def _clear_conversation(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.request_ui_clear()
            return
        self._chat_history.clear()
        self.transcript.clear()
        self._set_status("Conversation cleared.")

    def _undo_turn(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.request_ui_undo()
            return
        self._sync_history_from_worker()
        if not self._pop_history_exchange():
            self._append_command_feedback("Nothing to undo.")
            return
        self._refresh_conversation_display()
        self._set_status("Undone.")

    def _last_assistant_reply_text(self) -> str:
        self._sync_history_from_worker()
        for turn in reversed(self._chat_history):
            if turn.role == "assistant":
                return turn.text
        return ""

    def _copy_last_response(self) -> None:
        text = self._last_assistant_reply_text()
        if not text:
            self._append_command_feedback("Nothing to copy.")
            return
        QGuiApplication.clipboard().setText(text)
        self._append_command_feedback("Last response copied to clipboard.")

    def _redo_turn(self) -> None:
        self._stop_talking()
        self._sync_history_from_worker()
        if not self._chat_history:
            self._append_command_feedback("Nothing to redo.")
            return
        if self._chat_history[-1].role == "assistant":
            self._chat_history.pop()
        if not self._chat_history or self._chat_history[-1].role != "user":
            self._append_command_feedback("Nothing to redo.")
            return
        user_turn = self._chat_history[-1]
        self._refresh_conversation_display()
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.request_ui_redo()
            return
        self._pending_redo_on_start = user_turn
        self.talk_btn.setEnabled(False)
        self._start_worker(continuous=False)

    def _stop_all(self) -> None:
        self._stop_running_worker()
        if self.hands_free_btn.isChecked():
            self.hands_free_btn.blockSignals(True)
            self.hands_free_btn.setChecked(False)
            self.hands_free_btn.blockSignals(False)
        self._set_idle_ui_after_stop()

    def _stop_talking(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.stop_talking_now()

    def shutdown(self) -> None:
        """Stop voice worker before process exit (non-blocking)."""
        if getattr(self, "_shutdown_done", False):
            return
        self._shutdown_done = True
        self._pending_continuous = None
        self._halt_worker()
        with contextlib.suppress(Exception):
            sd.stop()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)


def _install_signal_handlers(app: QApplication, window: "MainWindow") -> None:
    """Quit on SIGINT/SIGTERM/SIGUSR1 (kill / kill -USR1).

    Uses signal.set_wakeup_fd + QSocketNotifier so signals wake the Qt loop on macOS.
    The write socket must stay open (closing it spuriously quits at startup).
    """

    def _exit_app() -> None:
        if getattr(app, "_exit_requested", False):
            return
        app._exit_requested = True  # type: ignore[attr-defined]
        notifier = getattr(app, "_signal_notifier", None)
        if notifier is not None:
            notifier.setEnabled(False)
        with contextlib.suppress(Exception):
            sd.stop()
        window.shutdown()
        app.quit()
        QTimer.singleShot(1500, lambda: os._exit(0))

    def _on_wakeup() -> None:
        read_sock = getattr(app, "_signal_read_sock", None)
        got_signal = False
        if read_sock is not None:
            with contextlib.suppress(BlockingIOError, OSError):
                while True:
                    chunk = read_sock.recv(4096)
                    if not chunk:
                        break
                    got_signal = True
        if got_signal:
            _exit_app()

    wakeup_fd = getattr(signal, "set_wakeup_fd", None)
    if wakeup_fd is not None:
        read_sock, write_sock = socket.socketpair()
        read_sock.setblocking(False)
        write_sock.setblocking(False)
        try:
            wakeup_fd(write_sock.fileno())
        except (ValueError, OSError):
            wakeup_fd = None
        else:
            notifier = QSocketNotifier(
                read_sock.fileno(), QSocketNotifier.Type.Read, app
            )
            notifier.activated.connect(_on_wakeup)
            app._signal_read_sock = read_sock  # type: ignore[attr-defined]
            app._signal_write_sock = write_sock  # type: ignore[attr-defined]
            app._signal_notifier = notifier  # type: ignore[attr-defined]

    def _signal_handler(_signum: int, _frame: Any) -> None:
        if wakeup_fd is None:
            QTimer.singleShot(0, _exit_app)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGUSR1):
        with contextlib.suppress(ValueError, OSError):
            signal.signal(sig, _signal_handler)


def main() -> int:
    if not list_piper_voices() and not list_pocket_voices():
        print(
            f"Warning: No TTS voices found.\n"
            f"  Piper: install .onnx files under {PIPER_VOICES_DIR}\n"
            "  pocket-tts: pip install pocket-tts",
            file=sys.stderr,
        )
    elif not list_piper_voices():
        print(
            f"Note: No Piper voices under {PIPER_VOICES_DIR} (pocket-tts may still work).",
            file=sys.stderr,
        )
    app = QApplication(sys.argv)
    app.setStyleSheet(TOOLTIP_STYLE)
    win = MainWindow()
    app.aboutToQuit.connect(win.shutdown)
    _install_signal_handlers(app, win)
    win.show()
    exit_code = app.exec()
    # QThread or sounddevice can keep the interpreter alive after app.exec() returns.
    os._exit(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
