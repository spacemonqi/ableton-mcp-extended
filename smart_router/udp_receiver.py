import json
import socket
import threading
from queue import Queue
from typing import Dict, Optional


class UDPReceiver:
    def __init__(self, host: str, port: int, queue: Queue):
        self.host = host
        self.port = port
        self.queue = queue
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _run(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((self.host, self.port))

        while self._running:
            try:
                data, _ = self._sock.recvfrom(65535)
                payload = json.loads(data.decode("utf-8"))
                if isinstance(payload, dict):
                    self.queue.put(payload)
            except Exception:
                continue
