#!/usr/bin/env python3
"""Optional faster-whisper dictation into QPlainTextEdit fields."""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from theme.theme_base import asset_path

DEFAULT_WHISPER_MODEL = os.environ.get(
    "WHISPER_MODEL", "Systran/faster-whisper-tiny.en"
)
SAMPLE_RATE = 16_000
FRAME_MS = 30
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)
SPEECH_THRESHOLD = float(os.environ.get("VAD_THRESHOLD", "0.012"))
DEFAULT_SILENCE_END_MS = int(os.environ.get("SILENCE_END_MS", "1200"))
SILENCE_END_MS_MIN = 400
SILENCE_END_MS_MAX = 5000
MAX_RECORD_SEC = int(os.environ.get("MAX_RECORD_SEC", "30"))
VOICE_MIC_OFFSET_X = 2  # inset from right border
VOICE_MIC_OFFSET_Y = 2  # inset from bottom border
VOICE_MIC_ICON_HEIGHT = 24
VOICE_MIC_ICON_WIDTH = max(12, round(VOICE_MIC_ICON_HEIGHT * 112 / 181))


def voice_mic_button_stylesheet() -> str:
    """Override dialog-wide QPushButton min sizes so the mic stays compact."""
    return f"""
        QPushButton#voice_mic_btn {{
            background-color: transparent;
            border: none;
            padding: 0px;
            margin: 0px;
            min-width: {VOICE_MIC_ICON_WIDTH}px;
            max-width: {VOICE_MIC_ICON_WIDTH}px;
            min-height: {VOICE_MIC_ICON_HEIGHT}px;
            max-height: {VOICE_MIC_ICON_HEIGHT}px;
        }}
    """


def _position_voice_mic(edit: QPlainTextEdit, mic: QWidget) -> None:
    """Place mic at the bottom-right of the text field with a small inset."""
    parent = mic.parentWidget()
    if parent is None:
        return
    from PySide6.QtCore import QPoint

    bottom_right = edit.mapTo(parent, QPoint(edit.width(), edit.height()))
    mic.move(
        bottom_right.x() - mic.width() - VOICE_MIC_OFFSET_X,
        bottom_right.y() - mic.height() - VOICE_MIC_OFFSET_Y,
    )
    mic.raise_()

_whisper_deps_available: Optional[bool] = None
_whisper_model = None
_whisper_model_name: Optional[str] = None
_model_lock = threading.Lock()


def is_whisper_voice_input_available() -> bool:
    """True when faster-whisper, sounddevice, and numpy can be imported."""
    global _whisper_deps_available
    if _whisper_deps_available is None:
        try:
            from bundle_capabilities import voice_input_ui_enabled

            if not voice_input_ui_enabled():
                _whisper_deps_available = False
                return False
        except ImportError:
            pass
        try:
            import faster_whisper  # noqa: F401
            import numpy  # noqa: F401
            import sounddevice  # noqa: F401

            _whisper_deps_available = True
        except ImportError:
            _whisper_deps_available = False
    return _whisper_deps_available


def insert_dictation_at_cursor(edit: QPlainTextEdit, text: str) -> None:
    """Insert transcribed text at the cursor, replacing any selection."""
    text = (text or "").strip()
    if not text:
        return
    cursor = edit.textCursor()
    if cursor.hasSelection():
        cursor.removeSelectedText()
    cursor.insertText(text)
    edit.setTextCursor(cursor)


@dataclass
class RecordResult:
    pcm: object | None
    peak_rms: float = 0.0
    threshold: float = SPEECH_THRESHOLD
    error: str | None = None


def _rms(chunk) -> float:
    import numpy as np

    if chunk.size == 0:
        return 0.0
    samples = chunk.astype(np.float32) / 32768.0
    return float(np.sqrt(np.mean(samples * samples)))


def _release_sounddevice() -> None:
    if not is_whisper_voice_input_available():
        return
    import sounddevice as sd

    with contextlib.suppress(Exception):
        sd.stop()


def record_utterance(
    stop_event: threading.Event,
    *,
    silence_end_ms: int | None = None,
) -> RecordResult:
    """Record from the mic until silence after speech."""
    import numpy as np
    import sounddevice as sd

    frames: list = []
    speech_started = False
    silent_frames = 0
    end_ms = silence_end_ms if silence_end_ms is not None else DEFAULT_SILENCE_END_MS
    end_ms = max(SILENCE_END_MS_MIN, min(SILENCE_END_MS_MAX, int(end_ms)))
    silent_limit = max(1, end_ms // FRAME_MS)
    max_frames = max(1, (MAX_RECORD_SEC * 1000) // FRAME_MS)
    calibration_frames = max(5, int(500 / FRAME_MS))
    peak_rms = 0.0
    noise_levels: list[float] = []
    threshold = SPEECH_THRESHOLD

    stream_kwargs = {
        "samplerate": SAMPLE_RATE,
        "channels": 1,
        "dtype": "int16",
        "blocksize": FRAME_SAMPLES,
    }

    stream = None
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
            error=f"Could not open microphone: {open_error}",
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
                        if frame_idx == calibration_frames - 1:
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
                    "Microphone captured no audio. Check macOS Privacy → Microphone."
                ),
            )
        return RecordResult(
            None,
            peak_rms=peak_rms,
            threshold=threshold,
            error="No speech detected.",
        )

    pcm = np.concatenate(frames)
    if int(np.max(np.abs(pcm))) == 0:
        return RecordResult(
            None,
            peak_rms=peak_rms,
            threshold=threshold,
            error="Microphone returned silence.",
        )
    return RecordResult(pcm, peak_rms=peak_rms, threshold=threshold)


def transcribe_audio(model, pcm) -> str:
    import numpy as np

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


def _get_whisper_model():
    global _whisper_model, _whisper_model_name
    from faster_whisper import WhisperModel

    from pyinstaller_whisper_models import resolve_whisper_model_path

    model_name = resolve_whisper_model_path()
    with _model_lock:
        if _whisper_model is None or _whisper_model_name != model_name:
            print(f"DEBUG whisper_voice_input: loading model {model_name}")
            _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _whisper_model_name = model_name
        return _whisper_model


class WhisperDictationWorker(QThread):
    transcribed = Signal(str)
    failed = Signal(str)
    session_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stop = threading.Event()

    def cancel(self) -> None:
        self._stop.set()

    def run(self) -> None:
        try:
            if self._stop.is_set():
                return
            model = _get_whisper_model()
            if self._stop.is_set():
                return
            record = record_utterance(self._stop)
            if self._stop.is_set():
                return
            if record.error or record.pcm is None:
                if record.error:
                    self.failed.emit(record.error)
                return
            try:
                text = transcribe_audio(model, record.pcm)
            except Exception as exc:
                self.failed.emit(f"Transcription failed: {exc}")
                return
            if text:
                self.transcribed.emit(text)
            else:
                self.failed.emit("Could not transcribe speech.")
        finally:
            self.session_finished.emit()


class _WhisperDictationCoordinator(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._worker: Optional[WhisperDictationWorker] = None
        self._active_mic: Optional[VoiceMicButton] = None
        self._active_edit: Optional[QPlainTextEdit] = None

    def toggle(self, edit: QPlainTextEdit, mic_btn: "VoiceMicButton") -> None:
        edit.setFocus(Qt.FocusReason.MouseFocusReason)
        if (
            self._active_mic is mic_btn
            and self._worker is not None
            and self._worker.isRunning()
        ):
            self.cancel()
            return
        self.cancel()
        self._active_mic = mic_btn
        self._active_edit = edit
        mic_btn.set_listening(True)
        worker = WhisperDictationWorker(self)
        worker.transcribed.connect(self._on_transcribed)
        worker.failed.connect(self._on_failed)
        worker.session_finished.connect(self._on_session_finished)
        self._worker = worker
        worker.start()

    def cancel(self) -> None:
        worker = self._worker
        if worker is not None and worker.isRunning():
            worker.cancel()
            if not worker.wait(5000):
                worker.terminate()
                worker.wait(1000)
        self._worker = None
        if self._active_mic is not None:
            self._active_mic.set_listening(False)
            self._active_mic = None
        self._active_edit = None

    def _on_transcribed(self, text: str) -> None:
        edit = self._active_edit
        if edit is not None:
            edit.setFocus(Qt.FocusReason.OtherFocusReason)
            insert_dictation_at_cursor(edit, text)

    def _on_failed(self, message: str) -> None:
        print(f"DEBUG whisper_voice_input: {message}")

    def _on_session_finished(self) -> None:
        if self._active_mic is not None:
            self._active_mic.set_listening(False)
        self._worker = None
        self._active_mic = None
        self._active_edit = None


_coordinator: Optional[_WhisperDictationCoordinator] = None


def _dictation_coordinator() -> _WhisperDictationCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = _WhisperDictationCoordinator()
    return _coordinator


def stop_whisper_dictation() -> None:
    """Stop any in-progress dictation (e.g. when a dialog closes)."""
    if _coordinator is not None:
        _coordinator.cancel()


def _watch_edit_lifetime(edit: QPlainTextEdit) -> None:
    def _on_destroyed(_obj=None) -> None:
        if _coordinator is not None and _coordinator._active_edit is edit:
            _coordinator.cancel()

    edit.destroyed.connect(_on_destroyed)


class VoiceMicButton(QPushButton):
    """Microphone icon button for plain-text dictation."""

    def __init__(
        self,
        target_edit: QPlainTextEdit,
        parent: QWidget | None = None,
        *,
        sidebar: bool = False,
        sidebar_size: int = 20,
    ):
        super().__init__(parent)
        self._target_edit = target_edit
        self._listening = False
        self._sidebar = sidebar
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Voice input (click again to cancel)")
        self._icon_normal = QIcon(asset_path("mic.png"))
        self._icon_hover = QIcon(asset_path("mic_hover.png"))
        self._icon_active = QIcon(asset_path("mic_active.png"))
        self.setIcon(self._icon_normal)
        if sidebar:
            self.setObjectName("imageGenPromptVoiceMicBtn")
            self.setFlat(False)
            icon_h = max(12, int(sidebar_size) - 6)
            icon_w = max(12, round(icon_h * 112 / 181))
            self.setIconSize(QSize(icon_w, icon_h))
            self.setFixedSize(int(sidebar_size), int(sidebar_size))
        else:
            self.setObjectName("voice_mic_btn")
            self.setFlat(True)
            self.setStyleSheet(voice_mic_button_stylesheet())
            self.setIconSize(QSize(VOICE_MIC_ICON_WIDTH, VOICE_MIC_ICON_HEIGHT))
            self.setFixedSize(VOICE_MIC_ICON_WIDTH, VOICE_MIC_ICON_HEIGHT)
        self.clicked.connect(self._on_clicked)
        self.installEventFilter(self)
        _watch_edit_lifetime(target_edit)

    def set_listening(self, listening: bool) -> None:
        self._listening = listening
        if listening:
            self.setIcon(self._icon_active)
        else:
            self.setIcon(self._icon_normal)

    def _on_clicked(self) -> None:
        self._target_edit.setFocus(Qt.FocusReason.MouseFocusReason)
        _dictation_coordinator().toggle(self._target_edit, self)

    def eventFilter(self, obj, event) -> bool:
        if obj is self and not self._listening:
            if event.type() == QEvent.Type.Enter:
                self.setIcon(self._icon_hover)
            elif event.type() == QEvent.Type.Leave:
                self.setIcon(self._icon_normal)
        return super().eventFilter(obj, event)


class _VoiceMicResizeFilter(QObject):
    def __init__(self, wrapper: "VoiceMicTextEditWrapper") -> None:
        super().__init__(wrapper)
        self._wrapper = wrapper

    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._wrapper._position_mic()
        return False


class VoiceMicTextEditWrapper(QWidget):
    """QPlainTextEdit with a lower-right microphone overlay."""

    def __init__(self, edit: QPlainTextEdit, parent: QWidget | None = None):
        super().__init__(parent)
        self._edit = edit
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(edit)
        self._mic_btn = VoiceMicButton(edit, self)
        _watch_edit_lifetime(edit)
        filt = _VoiceMicResizeFilter(self)
        self.installEventFilter(filt)
        self._resize_filter = filt
        edit.installEventFilter(filt)
        self._position_mic()

    @property
    def text_edit(self) -> QPlainTextEdit:
        return self._edit

    def _position_mic(self) -> None:
        _position_voice_mic(self._edit, self._mic_btn)


def create_sidebar_voice_mic_button(
    edit: QPlainTextEdit,
    parent: QWidget | None = None,
    *,
    size: int = 20,
) -> Optional[VoiceMicButton]:
    """Compact mic button for a field action column (e.g. beside copy)."""
    if not is_whisper_voice_input_available():
        return None
    return VoiceMicButton(edit, parent, sidebar=True, sidebar_size=size)


def maybe_wrap_plain_text_edit_with_voice_mic(
    edit: QPlainTextEdit,
) -> QWidget:
    """Return a mic-overlay wrapper when whisper is available, else the edit."""
    if not is_whisper_voice_input_available():
        return edit
    return VoiceMicTextEditWrapper(edit)


def attach_voice_mic_to_plain_text_edit(
    edit: QPlainTextEdit,
    *,
    parent: QWidget | None = None,
) -> Optional[VoiceMicButton]:
    """Attach a mic button overlay to an existing text edit (in-place parent)."""
    if not is_whisper_voice_input_available():
        return None
    host = parent or edit
    mic = VoiceMicButton(edit, edit if host is edit else host)
    mic.show()

    def position() -> None:
        _position_voice_mic(edit, mic)

    class _PosFilter(QObject):
        def eventFilter(self, obj, event) -> bool:
            if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
                position()
            return False

    filt = _PosFilter(edit)
    edit.installEventFilter(filt)
    if host is not edit:
        host.installEventFilter(filt)
    edit._voice_mic_position_filter = filt  # type: ignore[attr-defined]
    edit._voice_mic_button = mic  # type: ignore[attr-defined]
    position()
    return mic
