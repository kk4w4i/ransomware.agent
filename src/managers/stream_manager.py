import asyncio
import base64
import json
import logging
import os
import time
from contextlib import suppress
from typing import Any, Dict, Optional, Set, TYPE_CHECKING

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

if TYPE_CHECKING:
    from websockets.server import Serve


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
        self._frame_task: Optional[asyncio.Task] = None
        self._page = None
        self._server: Optional["Serve"] = None
        self._server_lock: Optional[asyncio.Lock] = None
        self._streaming = False
        self._metadata: Dict[str, str] = {}
        self._status = "idle"
        self._last_frame_ts: Optional[float] = None
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
            self._server = await serve(self._handle_connection, self._host, self._port)
            self._logger.info("Streaming websocket server listening on %s:%s%s", self._host, self._port, self._path)

    async def start_stream(self, page, metadata: Optional[Dict[str, str]] = None) -> None:
        await self.ensure_server()

        if self._frame_task:
            await self.stop_stream()

        self._page = page
        self._metadata = metadata or {}
        self._streaming = True
        self._status = "starting"
        self._frame_task = asyncio.create_task(self._capture_loop())
        await self._broadcast_status("starting")

    async def stop_stream(self) -> None:
        if not self._streaming:
            return
        self._streaming = False
        self._status = "idle"
        if self._frame_task:
            self._frame_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._frame_task
        self._frame_task = None
        self._page = None
        await self._broadcast_status("stopped")

    @property
    def active(self) -> bool:
        return self._streaming

    def info(self) -> Dict[str, object]:
        return {
            "host": self._host,
            "port": self._port,
            "path": self._path,
            "active": self.active,
            "status": self._status,
            "lastFrameTs": self._last_frame_ts,
            "metadata": self._metadata,
            "clients": len(self._clients),
        }

    async def push_event(self, event_type: str, data: Optional[Dict[str, Any]] = None) -> None:
        await self.ensure_server()
        message = self._build_event_message(event_type, data or {})
        await self._broadcast(message)

    async def shutdown(self) -> None:
        await self.stop_stream()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _capture_loop(self) -> None:
        try:
            while self._streaming:
                if not self._page or self._page.is_closed():
                    await asyncio.sleep(self._frame_interval)
                    continue

                if not self._clients:
                    await asyncio.sleep(self._frame_interval)
                    continue

                try:
                    buffer = await self._page.screenshot(type="jpeg", quality=60, full_page=True)
                except Exception as exc:  # pylint: disable=broad-except
                    self._logger.warning("Screenshot capture failed: %s", exc)
                    await asyncio.sleep(self._frame_interval)
                    continue

                payload = self._build_frame_message(buffer)
                await self._broadcast(payload)
                self._last_frame_ts = time.time()

                if self._status != "streaming":
                    self._status = "streaming"
                    await self._broadcast_status("streaming")

                await asyncio.sleep(self._frame_interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.error("Unexpected error in capture loop: %s", exc)
        finally:
            self._frame_task = None

    async def _handle_connection(self, websocket: WebSocketServerProtocol) -> None:
        if websocket.path != self._path:
            await websocket.close(code=1008, reason="Unsupported path")
            return
        self._clients.add(websocket)
        await self._send_safe(websocket, self._build_status_message(self._status))
        try:
            await websocket.wait_closed()
        finally:
            self._clients.discard(websocket)

    async def _broadcast_status(self, state: str) -> None:
        if not self._clients:
            return
        await self._broadcast(self._build_status_message(state))

    def _build_status_message(self, state: str) -> str:
        payload = {
            "type": "status",
            "state": state,
            "metadata": self._metadata,
            "timestamp": time.time(),
        }
        return json.dumps(payload, default=str)

    def _build_frame_message(self, buffer: bytes) -> str:
        data = base64.b64encode(buffer).decode("ascii")
        payload = {
            "type": "frame",
            "timestamp": time.time(),
            "contentType": "image/jpeg",
            "data": data,
        }
        return json.dumps(payload)

    def _build_event_message(self, event_type: str, data: Dict[str, Any]) -> str:
        payload = {
            "type": "event",
            "event": event_type,
            "timestamp": time.time(),
            "data": data,
        }
        return json.dumps(payload, default=str)

    async def _broadcast(self, payload: str) -> None:
        if not self._clients:
            return
        await asyncio.gather(*(self._send_safe(ws, payload) for ws in list(self._clients)))

    async def _send_safe(self, websocket: WebSocketServerProtocol, payload: str) -> None:
        try:
            await websocket.send(payload)
        except ConnectionClosed:
            self._clients.discard(websocket)
        except Exception as exc:  # pylint: disable=broad-except
            self._logger.debug("Failed to send frame: %s", exc)
            self._clients.discard(websocket)


__all__ = ["StreamManager"]
