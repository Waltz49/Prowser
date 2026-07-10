#!/usr/bin/env python3
"""Background worker for LM Studio chat streaming."""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Qt

from chat_plugins.chat_lmstudio import finalize_chat_response, stream_chat_response
from chat_plugins.chat_session import ChatMessage


class _RunDispatcher(QObject):
    """Main-thread helper to queue work onto the LM Studio worker thread."""

    run_requested = Signal(list, str)


class _RequestBridge(QObject):
    """Relays worker-thread signals onto the main GUI thread."""

    chunk = Signal(str)
    finished = Signal(str)
    error = Signal(str)
    cancelled = Signal()


class _ChatLmStudioWorker(QObject):
    """Runs on a dedicated long-lived QThread; one stream at a time."""

    chunk = Signal(str)
    finished = Signal(str)
    error = Signal(str)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run_stream(self, messages: list[ChatMessage], system_prompt: str = "") -> None:
        self._cancel_requested = False
        try:
            accumulated = ""
            for piece in stream_chat_response(messages, system_prompt=system_prompt):
                if self._cancel_requested:
                    self.cancelled.emit()
                    return
                accumulated += piece
                self.chunk.emit(piece)
            if self._cancel_requested:
                self.cancelled.emit()
                return
            final = finalize_chat_response(accumulated)
            if not final:
                self.error.emit("The model returned an empty response.")
                return
            self.finished.emit(final)
        except Exception as e:
            if self._cancel_requested:
                self.cancelled.emit()
            else:
                self.error.emit(str(e))


class ChatLmStudioService(QObject):
    """Single LM Studio worker thread shared by the chat pane."""

    _instance: ChatLmStudioService | None = None

    @classmethod
    def instance(cls) -> ChatLmStudioService:
        if cls._instance is None:
            cls._instance = ChatLmStudioService()
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        self._thread = QThread(self)
        self._worker = _ChatLmStudioWorker()
        self._worker.moveToThread(self._thread)
        self._dispatch = _RunDispatcher(self)
        self._dispatch.run_requested.connect(
            self._worker.run_stream,
            Qt.ConnectionType.QueuedConnection,
        )
        self._busy = False
        self._active_bridge: _RequestBridge | None = None
        self._thread.start()
        app = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def shutdown(self) -> None:
        if self._busy:
            self._worker.request_cancel()
        if self._thread.isRunning():
            self._thread.quit()
            self._thread.wait(5000)

    def is_busy(self) -> bool:
        return self._busy

    def _disconnect_request(self, bridge: _RequestBridge, handlers: dict) -> None:
        for worker_sig, bridge_sig in (
            (self._worker.chunk, bridge.chunk),
            (self._worker.finished, bridge.finished),
            (self._worker.error, bridge.error),
            (self._worker.cancelled, bridge.cancelled),
        ):
            try:
                worker_sig.disconnect(bridge_sig)
            except RuntimeError:
                pass
        for bridge_sig, handler in handlers.items():
            try:
                bridge_sig.disconnect(handler)
            except RuntimeError:
                pass

    def submit(
        self,
        messages: list[ChatMessage],
        *,
        on_chunk,
        on_finished,
        on_error,
        on_cancelled=None,
        system_prompt: str = "",
    ) -> bool:
        """Queue one stream request. Returns False if a stream is already active."""
        if self._busy:
            return False
        self._busy = True

        bridge = _RequestBridge(self)
        self._active_bridge = bridge
        queued = Qt.ConnectionType.QueuedConnection

        def _release() -> None:
            self._busy = False
            self._disconnect_request(bridge, handlers)
            if self._active_bridge is bridge:
                self._active_bridge = None
            bridge.deleteLater()

        def _finished(final: str) -> None:
            _release()
            on_finished(final)

        def _errored(err: str) -> None:
            _release()
            on_error(err)

        def _cancelled() -> None:
            _release()
            if on_cancelled is not None:
                on_cancelled()

        handlers = {
            bridge.chunk: on_chunk,
            bridge.finished: _finished,
            bridge.error: _errored,
            bridge.cancelled: _cancelled,
        }
        for bridge_sig, handler in handlers.items():
            bridge_sig.connect(handler)

        self._worker.chunk.connect(bridge.chunk, queued)
        self._worker.finished.connect(bridge.finished, queued)
        self._worker.error.connect(bridge.error, queued)
        self._worker.cancelled.connect(bridge.cancelled, queued)
        self._dispatch.run_requested.emit(list(messages), system_prompt)
        return True

    def cancel(self) -> None:
        if not self._busy:
            return
        self._worker.request_cancel()


def run_chat_worker(
    messages: list[ChatMessage],
    *,
    on_chunk,
    on_finished,
    on_error,
    on_thread_finished=None,
    system_prompt: str = "",
) -> bool:
    """Submit a chat stream to the shared LM Studio service."""
    del on_thread_finished  # legacy kwarg; service thread is never torn down per request
    return ChatLmStudioService.instance().submit(
        messages,
        on_chunk=on_chunk,
        on_finished=on_finished,
        on_error=on_error,
        system_prompt=system_prompt,
    )
