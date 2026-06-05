#!/usr/bin/env python3
"""Persistent QProcess for image generation and LM Studio captions (one model at a time)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, QProcess, Signal

from model_tasks_launch import model_tasks_worker_program_and_args


class ModelTasksController(QObject):
    """Single background worker subprocess; at most one job at a time."""

    task_started = Signal(str)  # job kind: queued locally ("generate" | "caption")
    job_processing_started = Signal(str)  # worker actually running the job
    task_finished = Signal(str, bool, str)  # job kind, success, error_message

    generation_started = Signal()
    generation_finished = Signal(bool, str, str)  # success, output_path, error_message

    caption_chunk = Signal(str)
    caption_ready = Signal(str)
    caption_error = Signal(str)

    flux_prompt_chunk = Signal(str)
    flux_prompt_ready = Signal(str)
    flux_prompt_error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: Optional[QProcess] = None
        self._worker_ready = False
        self._stdout_buffer = ""
        self._stderr_buffer: list[str] = []
        self._active_job_id: str = ""
        self._active_kind: str = ""  # "generate" | "caption" | "flux_prompt"
        self._pending_command: Optional[Dict[str, Any]] = None
        self._progress_callback = None
        self._worker_result: Optional[Dict[str, Any]] = None
        self._generate_perf_start: Optional[float] = None
        self._cancelling = False

    def is_running(self) -> bool:
        return bool(self._active_job_id)

    @property
    def active_kind(self) -> str:
        return self._active_kind

    def _is_process_alive(self) -> bool:
        proc = self._process
        if proc is None:
            return False
        return proc.state() != QProcess.ProcessState.NotRunning

    def start_generate_job(self, payload: Dict[str, Any]) -> bool:
        if self.is_running():
            return False
        job_id = uuid.uuid4().hex
        self._active_job_id = job_id
        self._active_kind = "generate"
        self._stderr_buffer = []
        cmd = {
            "command": "generate",
            "job_id": job_id,
            "payload": payload,
        }
        return self._start_job("generate", cmd)

    def start_caption_job(
        self, file_path: str, user_prompt_override: str | None = None
    ) -> bool:
        if self.is_running():
            return False
        job_id = uuid.uuid4().hex
        self._active_job_id = job_id
        self._active_kind = "caption"
        self._stderr_buffer = []
        cmd = {
            "command": "caption",
            "job_id": job_id,
            "file_path": file_path,
            "user_prompt_override": user_prompt_override,
        }
        return self._start_job("caption", cmd)

    def start_flux_prompt_job(self, system_prompt: str, user_prompt: str) -> bool:
        if self.is_running():
            return False
        job_id = uuid.uuid4().hex
        self._active_job_id = job_id
        self._active_kind = "flux_prompt"
        self._stderr_buffer = []
        cmd = {
            "command": "flux_prompt",
            "job_id": job_id,
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
        }
        return self._start_job("flux_prompt", cmd)

    def cancel_task(self) -> None:
        """Kill worker process and clear in-flight job (unload all models)."""
        kind = self._active_kind
        self._cancelling = True
        try:
            self._terminate_worker()
            self._finish_job(kind, False, "Cancelled")
        finally:
            self._cancelling = False

    def _start_job(self, kind: str, cmd: Dict[str, Any]) -> bool:
        self._pending_command = cmd
        if not self._ensure_worker():
            self._clear_job()
            return False
        if not self._send_command(cmd):
            self._clear_job()
            return False
        self.task_started.emit(kind)
        return True

    def _ensure_worker(self) -> bool:
        if self._is_process_alive() and self._worker_ready:
            return True
        self._terminate_worker()
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_process_finished)
        proc.errorOccurred.connect(self._on_process_error)

        program, arguments = model_tasks_worker_program_and_args()
        proc.setProgram(program)
        proc.setArguments(arguments)
        proc.start()
        if not proc.waitForStarted(180000):
            self._process = None
            return False
        self._process = proc
        self._worker_ready = False
        self._stdout_buffer = ""
        return True

    def _send_command(self, cmd: Dict[str, Any]) -> bool:
        proc = self._process
        if proc is None:
            return False
        if not self._worker_ready:
            self._pending_command = cmd
            return True
        line = json.dumps(cmd) + "\n"
        proc.write(line.encode("utf-8"))
        self._pending_command = None
        return True

    def _on_stdout(self) -> None:
        proc = self._process
        if proc is None:
            return
        data = bytes(proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        if not data:
            return
        self._stdout_buffer += data
        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            line = line.strip()
            if line:
                self._handle_worker_line(line)

    def _handle_worker_line(self, line: str) -> None:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return

        msg_type = msg.get("type")
        if msg_type == "ready":
            self._worker_ready = True
            if self._pending_command:
                self._send_command(self._pending_command)
            return

        if msg_type == "job_started":
            command = str(msg.get("command") or self._active_kind)
            if command == "generate":
                self._generate_perf_start = time.perf_counter()
            self.job_processing_started.emit(command)
            if command == "generate":
                self.generation_started.emit()
            return

        job_id = str(msg.get("job_id") or "")
        if self._active_job_id and job_id and job_id != self._active_job_id:
            return

        if msg_type == "progress":
            if self._active_kind == "generate":
                self._on_generate_progress(msg)
            return

        if msg_type == "caption_chunk":
            text = msg.get("text")
            if text:
                self.caption_chunk.emit(str(text))
            return

        if msg_type == "flux_prompt_chunk":
            text = msg.get("text")
            if text:
                self.flux_prompt_chunk.emit(str(text))
            return

        if msg_type == "result":
            self._on_worker_result(msg)
            return

        if msg_type == "error":
            if not self._active_job_id:
                return
            err = str(msg.get("message") or "Task failed.")
            self._finish_job(self._active_kind, False, err)
            return

    def _on_worker_result(self, msg: Dict[str, Any]) -> None:
        kind = str(msg.get("command") or self._active_kind)
        if kind == "caption":
            caption = str(msg.get("caption") or "").strip()
            if caption:
                self.caption_ready.emit(caption)
                self._finish_job("caption", True, "")
            else:
                self._finish_job("caption", False, "Empty caption.")
            return
        if kind == "flux_prompt":
            prompt = str(msg.get("prompt") or "").strip()
            if prompt:
                self.flux_prompt_ready.emit(prompt)
                self._finish_job("flux_prompt", True, "")
            else:
                self._finish_job("flux_prompt", False, "Empty prompt.")
            return
        if kind == "generate":
            self._finish_generate_success(msg)
            return
        self._finish_job(kind, False, "Unknown result.")

    def _on_generate_progress(self, msg: Dict[str, Any]) -> None:
        if hasattr(self, "_progress_callback") and self._progress_callback:
            self._progress_callback(msg)

    def set_generate_progress_callback(self, callback) -> None:
        self._progress_callback = callback

    def _finish_generate_success(self, msg: Dict[str, Any]) -> None:
        output_path = str(msg.get("output_path") or "")
        self._worker_result = {
            k: v
            for k, v in msg.items()
            if k not in ("type", "job_id", "command")
        }
        if self._generate_perf_start is not None:
            local_elapsed = time.perf_counter() - self._generate_perf_start
            if "generation_time_seconds" not in self._worker_result:
                self._worker_result["generation_time_seconds"] = local_elapsed
        self._finish_job("generate", True, "", output_path=output_path)

    def _finish_job(
        self,
        kind: str,
        success: bool,
        error_message: str,
        *,
        output_path: str = "",
    ) -> None:
        if not kind:
            return
        if kind == "generate":
            self.generation_finished.emit(success, output_path, error_message)
        elif kind == "caption":
            if not success and error_message != "Cancelled":
                self.caption_error.emit(error_message or "Caption failed.")
        elif kind == "flux_prompt":
            if not success and error_message != "Cancelled":
                self.flux_prompt_error.emit(error_message or "Prompt refinement failed.")
        self.task_finished.emit(kind, success, error_message)
        self._clear_job()

    def _clear_job(self) -> None:
        self._active_job_id = ""
        self._active_kind = ""
        self._worker_result = None
        self._generate_perf_start = None

    def _on_stderr(self) -> None:
        proc = self._process
        if proc is None:
            return
        data = bytes(proc.readAllStandardError()).decode("utf-8", errors="replace")
        if data:
            self._stderr_buffer.append(data)

    def _on_process_error(self, _error) -> None:
        if self._process and self._process.state() == QProcess.ProcessState.NotRunning:
            self._on_process_finished(self._process.exitCode(), self._process.exitStatus())

    def _on_process_finished(self, exit_code: int, exit_status) -> None:
        if not self._active_job_id or self._cancelling:
            self._worker_ready = False
            self._process = None
            return
        stderr = "".join(self._stderr_buffer).strip()
        normal_exit = (
            exit_status == QProcess.ExitStatus.NormalExit
            if exit_status is not None
            else True
        )
        kind = self._active_kind
        err = stderr or "Worker process exited."
        if exit_code != 0:
            err = f"Worker exited with code {exit_code}.\n{err}"
        if not normal_exit and not err:
            err = "Worker crashed."
        self._process = None
        self._worker_ready = False
        self._finish_job(kind, False, err)

    def _terminate_worker(self) -> None:
        proc = self._process
        if proc is not None and proc.state() != QProcess.ProcessState.NotRunning:
            try:
                proc.write(b'{"command":"shutdown"}\n')
                proc.closeWriteChannel()
                proc.waitForFinished(2000)
            except Exception:
                pass
            if proc.state() != QProcess.ProcessState.NotRunning:
                proc.kill()
                proc.waitForFinished(3000)
        self._process = None
        self._worker_ready = False
        self._stdout_buffer = ""
        self._stderr_buffer = []
        self._pending_command = None

    def cleanup(self) -> None:
        if self.is_running():
            self.cancel_task()
        else:
            self._terminate_worker()

    def pop_worker_result(self) -> Optional[Dict[str, Any]]:
        result = getattr(self, "_worker_result", None)
        self._worker_result = None
        return result

    def stderr_text(self) -> str:
        return "".join(self._stderr_buffer).strip()


_controller: Optional[ModelTasksController] = None


def get_model_tasks_controller(parent=None) -> ModelTasksController:
    global _controller
    if _controller is None:
        _controller = ModelTasksController(parent)
    return _controller
