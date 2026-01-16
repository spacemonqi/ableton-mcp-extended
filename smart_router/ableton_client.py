import json
import socket
import threading
from typing import Any, Dict, Optional


class AbletonTCPClient:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        if self._sock:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        self._sock = sock

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None

    def _receive_full_response(self, sock: socket.socket, buffer_size: int = 8192) -> Dict[str, Any]:
        chunks = []
        sock.settimeout(10.0)
        while True:
            chunk = sock.recv(buffer_size)
            if not chunk:
                break
            chunks.append(chunk)
            try:
                data = b"".join(chunks)
                return json.loads(data.decode("utf-8"))
            except json.JSONDecodeError:
                continue
        if chunks:
            data = b"".join(chunks)
            return json.loads(data.decode("utf-8"))
        raise RuntimeError("No data received from Ableton")

    def send_command(self, command_type: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        with self._lock:
            try:
                self.connect()
                payload = {"type": command_type, "params": params or {}}
                self._sock.sendall(json.dumps(payload).encode("utf-8"))
                response = self._receive_full_response(self._sock)
                if response.get("status") == "error":
                    raise RuntimeError(response.get("message", "Unknown error from Ableton"))
                return response.get("result", {})
            except Exception:
                self.disconnect()
                raise
