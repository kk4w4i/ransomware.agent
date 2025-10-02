import asyncio
import base64
import json
import logging
import os
import threading
import time
from contextlib import suppress
from typing import Any, Dict, Optional, Set, TYPE_CHECKING, Coroutine, TypeVar

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

if TYPE_CHECKING:
    from websockets.server import Serve


T = TypeVar("T")


def _default_logger() -> logging.Logger:
    logger = logging.getLogger("StreamManager")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


class StreamManager:
    _instance: Optional["StreamManager"] = None

    def __init__(self) -> None:
        self._clients: Set[WebSocketServerProtocol] = set()
        self._clients_lock = threading.RLock()
        self._server: Optional["Serve"] = None
        self._server_lock: Optional[asyncio.Lock] = None
        self._server_loop: Optional[asyncio.AbstractEventLoop] = None
        self._server_thread: Optional[threading.Thread] = None
        self._server_ready = threading.Event()
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._jobs_lock = threading.RLock()
        self._server_error: Optional[BaseException] = None
        self._logger = _default_logger()
        self._frame_interval = float(os.getenv("STREAM_FRAME_INTERVAL", "0.5"))
        self._host = os.getenv("STREAM_SERVER_HOST", "0.0.0.0")
        self._port = int(os.getenv("STREAM_SERVER_PORT", "8765"))
        self._path = os.getenv("STREAM_SERVER_PATH", "/ws/agent")

    @classmethod
    def get_instance(cls) -> "StreamManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def ensure_server(self) -> None:
        if self._server:
            return
        if self._server_lock is None:
            self._server_lock = asyncio.Lock()
        async with self._server_lock:
            if self._server:
                return
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._start_server_thread)
            if self._server_error:
                raise RuntimeError("Failed to start streaming websocket server") from self._server_error
            if not self._server:
                raise RuntimeError("Streaming websocket server failed to start")

    def _start_server_thread(self) -> None:
        if self._server and self._server_thread and self._server_thread.is_alive():
            return

        self._server_ready.clear()
        self._server_error = None
        loop = asyncio.new_event_loop()
        self._server_loop = loop

        def runner() -> None:
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._start_server())
            except Exception as exc:  # pylint: disable=broad-except
                self._server_error = exc
                self._logger.error("Unable to start streaming websocket server: %s", exc)
            else:
                self._server_ready.set()
                try:
                    loop.run_forever()
                finally:
                    pass
            finally:
                if not self._server_ready.is_set():
                    self._server_ready.set()
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                for task in pending:
                    task.cancel()
                if pending:
                    with suppress(asyncio.CancelledError):
                        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                if self._server:
                    self._server.close()
                    loop.run_until_complete(self._server.wait_closed())
                    self._server = None
                loop.close()
                self._server_loop = None

        self._server_thread = threading.Thread(target=runner, name="StreamManagerServer", daemon=True)
        self._server_thread.start()
        self._server_ready.wait()

    async def _start_server(self) -> None:
        self._server = await serve(self._handle_connection, self._host, self._port)
        self._logger.info("Streaming websocket server listening on %s:%s%s", self._host, self._port, self._path)

    async def _close_server(self) -> None:
        if not self._server:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _run_on_server_loop(self, coro: Coroutine[Any, Any, T]) -> T:
        if not self._server_loop:
            raise RuntimeError("Streaming websocket server is not running")
        current = asyncio.get_running_loop()
        if current is self._server_loop:
            return await coro
        future = asyncio.run_coroutine_threadsafe(coro, self._server_loop)
        return await asyncio.wrap_future(future)

    async def _cancel_task(self, task: asyncio.Task[Any]) -> None:
        if task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def start_stream(self, job_id: str, page, metadata: Optional[Dict[str, str]] = None) -> None:
        await self.ensure_server()

        await self.stop_stream(job_id)

        job = {
            "page": page,
            "metadata": metadata or {},
            "status": "starting",
            "task": None,
            "lastFrameTs": None,
            "loop": asyncio.get_running_loop(),
        }
        with self._jobs_lock:
            self._jobs[job_id] = job
        job["task"] = asyncio.create_task(self._capture_loop(job_id))
        await self._run_on_server_loop(self._broadcast_status(job_id, "starting"))

    async def stop_stream(self, job_id: str) -> None:
        with self._jobs_lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job["status"] = "stopped"
            task: Optional[asyncio.Task] = job.get("task")
            task_loop: Optional[asyncio.AbstractEventLoop] = job.get("loop")

        if task:
            if task_loop and task_loop is not asyncio.get_running_loop():
                if task_loop.is_closed():
                    task.cancel()
                else:
                    future = asyncio.run_coroutine_threadsafe(self._cancel_task(task), task_loop)
                    await asyncio.wrap_future(future)
            else:
                await self._cancel_task(task)

        with self._jobs_lock:
            stored = self._jobs.get(job_id)
            if stored is job:
                job["task"] = None
                self._jobs.pop(job_id, None)

        await self._run_on_server_loop(self._broadcast_status(job_id, "stopped"))

    @property
    def active(self) -> bool:
        with self._jobs_lock:
            return any(job.get("status") == "streaming" for job in self._jobs.values())

    @property
    def _client_count(self) -> int:
        with self._clients_lock:
            return len(self._clients)

    def info(self, job_id: Optional[str] = None) -> Dict[str, object]:
        base: Dict[str, Any] = {
            "host": self._host,
            "port": self._port,
            "path": self._path,
            "active": self.active,
            "clients": self._client_count,
        }
        with self._jobs_lock:
            if job_id:
                job = self._jobs.get(job_id)
                if job:
                    base["jobId"] = job_id
                    base["job"] = {
                        "status": job.get("status"),
                        "metadata": job.get("metadata", {}),
                        "lastFrameTs": job.get("lastFrameTs"),
                    }
                else:
                    base["jobId"] = job_id
                    base["job"] = None
            else:
                base["jobs"] = {
                    jid: {
                        "status": job.get("status"),
                        "metadata": job.get("metadata", {}),
                        "lastFrameTs": job.get("lastFrameTs"),
                    }
                    for jid, job in self._jobs.items()
                }
        return base

    async def push_event(self, job_id: str, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        await self.ensure_server()
        message = self._build_event_message(job_id, event_type, data or {})
        await self._run_on_server_loop(self._broadcast(message))

    async def shutdown(self) -> None:
        with self._jobs_lock:
            job_ids = list(self._jobs.keys())
        for job_id in job_ids:
            await self.stop_stream(job_id)

        if self._server_loop and self._server:
            await self._run_on_server_loop(self._close_server())
            self._server_loop.call_soon_threadsafe(self._server_loop.stop)
        if self._server_thread and self._server_thread.is_alive() and threading.current_thread() is not self._server_thread:
            self._server_thread.join(timeout=5)
        self._server_thread = None

    async def _capture_loop(self, job_id: str) -> None:
        try:
            while True:
                with self._jobs_lock:
                    job = self._jobs.get(job_id)
                    page = job.get("page") if job else None
                if not job:
                    break
                if not page or page.is_closed():
                    await asyncio.sleep(self._frame_interval)
                    continue

                with self._clients_lock:
                    has_clients = bool(self._clients)
                if not has_clients:
                    await asyncio.sleep(self._frame_interval)
                    continue

                try:
                    buffer = await page.screenshot(
                        type="jpeg",
                        quality=80,
                        full_page=False,
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    self._logger.warning("Screenshot capture failed: %s", exc)
                    await asyncio.sleep(self._frame_interval)
                    continue

                payload = self._build_frame_message(job_id, buffer)
                await self._run_on_server_loop(self._broadcast(payload))
                timestamp = time.time()

                notify_streaming = False
                with self._jobs_lock:
                    job = self._jobs.get(job_id)
                    if job:
                        job["lastFrameTs"] = timestamp
                        if job.get("status") != "streaming":
                            job["status"] = "streaming"
                            notify_streaming = True
                    else:
                        notify_streaming = False

                if notify_streaming:
                    await self._run_on_server_loop(self._broadcast_status(job_id, "streaming"))

                await asyncio.sleep(self._frame_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.error("Unexpected error in capture loop: %s", exc)
        finally:
            with self._jobs_lock:
                job = self._jobs.get(job_id)
                if job:
                    job["task"] = None

    async def _handle_connection(self, websocket: WebSocketServerProtocol) -> None:
        if websocket.path != self._path:
            await websocket.close(code=1008, reason="Unsupported path")
            return
        with self._clients_lock:
            self._clients.add(websocket)
        with self._jobs_lock:
            jobs_snapshot = {
                jid: job.get("status", "unknown")
                for jid, job in self._jobs.items()
            }
        if not jobs_snapshot:
            await self._send_safe(websocket, self._build_status_message(None, "idle"))
        else:
            for job_id, status in jobs_snapshot.items():
                await self._send_safe(websocket, self._build_status_message(job_id, status))
        try:
            await websocket.wait_closed()
        finally:
            with self._clients_lock:
                self._clients.discard(websocket)

    async def _broadcast_status(self, job_id: Optional[str], state: str) -> None:
        with self._clients_lock:
            has_clients = bool(self._clients)
        if not has_clients:
            return
        await self._broadcast(self._build_status_message(job_id, state))

    def _build_status_message(self, job_id: Optional[str], state: str) -> str:
        metadata = {}
        if job_id:
            with self._jobs_lock:
                job = self._jobs.get(job_id)
                if job:
                    metadata = job.get("metadata", {})
        payload = {
            "type": "status",
            "jobId": job_id,
            "state": state,
            "metadata": metadata,
            "timestamp": time.time(),
        }
        return json.dumps(payload, default=str)

    def _build_frame_message(self, job_id: str, buffer: bytes) -> str:
        data = base64.b64encode(buffer).decode("ascii")
        payload = {
            "type": "frame",
            "jobId": job_id,
            "timestamp": time.time(),
            "contentType": "image/jpeg",
            "data": data,
        }
        return json.dumps(payload)

    def _build_event_message(self, job_id: str, event_type: str, data: Dict[str, Any]) -> str:
        payload = {
            "type": "event",
            "event": event_type,
            "jobId": job_id,
            "timestamp": time.time(),
            "data": data,
        }
        return json.dumps(payload, default=str)

    async def _broadcast(self, payload: str) -> None:
        with self._clients_lock:
            targets = list(self._clients)
        if not targets:
            return
        await asyncio.gather(*(self._send_safe(ws, payload) for ws in targets))

    async def _send_safe(self, websocket: WebSocketServerProtocol, payload: str) -> None:
        try:
            await websocket.send(payload)
        except ConnectionClosed:
            with self._clients_lock:
                self._clients.discard(websocket)
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.debug("Failed to send frame: %s", exc)
            with self._clients_lock:
                self._clients.discard(websocket)


__all__ = ["StreamManager"]
