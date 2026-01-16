import json
import os
import threading
import time
from typing import Dict, List, Optional

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    WATCHDOG_AVAILABLE = True
except Exception:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object

def log(msg: str):
    """Simple logging helper"""
    print(f"[ConfigManager] {msg}", flush=True)


DEFAULT_CONFIG = {
    "settings": {
        "mocap_port": 9877,
        "ableton_host": "localhost",
        "ableton_port": 9878,
        "auto_discover_streams": True,
        "streams_cache_interval": 0.5,
        "streams_ttl_seconds": 5.0
    },
    "mappings": []
}


class _ConfigFileHandler(FileSystemEventHandler):
    def __init__(self, manager: "ConfigManager"):
        super().__init__()
        self.manager = manager

    def on_any_event(self, event):
        """Log all events for debugging"""
        log(f"File event: {event.event_type} on {event.src_path}")
        
    def on_modified(self, event):
        target = os.path.abspath(self.manager.config_path)
        actual = os.path.abspath(event.src_path)
        log(f"Modified event - target: {target}, actual: {actual}, match: {target == actual}")
        if target == actual:
            log(f"Config file modified, reloading...")
            self.manager.load_config()

    def on_created(self, event):
        target = os.path.abspath(self.manager.config_path)
        actual = os.path.abspath(event.src_path)
        if target == actual:
            log(f"Config file created, reloading...")
            self.manager.load_config()


class ConfigManager:
    def __init__(self, config_path: str, streams_cache_path: str):
        self.config_path = config_path
        self.streams_cache_path = streams_cache_path
        self._lock = threading.Lock()
        self._config = {}
        self._observer: Optional[Observer] = None
        self._stream_last_seen: Dict[str, float] = {}
        self._last_streams_write = 0.0
        self.load_config()
        self._ensure_streams_cache_file()

    def _ensure_config_file(self):
        if not os.path.exists(self.config_path):
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)

    def _ensure_streams_cache_file(self):
        if not os.path.exists(self.streams_cache_path):
            os.makedirs(os.path.dirname(self.streams_cache_path), exist_ok=True)
            with open(self.streams_cache_path, "w", encoding="utf-8") as f:
                json.dump({"streams": []}, f, indent=2)

    def load_config(self):
        self._ensure_config_file()
        with self._lock:
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                mapping_count = len(data.get("mappings", []))
                log(f"Config loaded: {mapping_count} mapping(s) from {self.config_path}")
            except Exception as e:
                log(f"Failed to load config: {e}, using defaults")
                data = DEFAULT_CONFIG

            # Normalize structure
            if "settings" not in data or not isinstance(data["settings"], dict):
                data["settings"] = DEFAULT_CONFIG["settings"].copy()
            if "mappings" not in data or not isinstance(data["mappings"], list):
                data["mappings"] = []

            self._config = data

    def get_settings(self) -> Dict:
        with self._lock:
            return dict(self._config.get("settings", {}))

    def get_mappings_for_stream(self, stream_name: str) -> List[Dict]:
        with self._lock:
            mappings = self._config.get("mappings", [])
            return [m for m in mappings if m.get("motion_stream") == stream_name and m.get("enabled", True)]

    def register_streams(self, streams: List[str]):
        now = time.time()
        with self._lock:
            for name in streams:
                self._stream_last_seen[name] = now

        if self.get_settings().get("auto_discover_streams", True):
            self._maybe_write_streams_cache(now)

    def _maybe_write_streams_cache(self, now: float):
        interval = float(self.get_settings().get("streams_cache_interval", 0.5))
        if now - self._last_streams_write < interval:
            return
        self._last_streams_write = now

        ttl = float(self.get_settings().get("streams_ttl_seconds", 5.0))
        streams = [
            {"name": name, "last_seen": ts}
            for name, ts in self._stream_last_seen.items()
            if now - ts <= ttl
        ]
        streams.sort(key=lambda x: x["last_seen"], reverse=True)

        try:
            with open(self.streams_cache_path, "w", encoding="utf-8") as f:
                json.dump({"streams": streams}, f, indent=2)
        except Exception:
            pass

    def get_recent_streams(self, within_seconds: float = 5.0) -> List[str]:
        now = time.time()
        with self._lock:
            return [
                name for name, ts in self._stream_last_seen.items()
                if now - ts <= within_seconds
            ]

    def start_watcher(self):
        if not WATCHDOG_AVAILABLE:
            log("WARNING: watchdog not available, hot-reload disabled")
            return
        if self._observer:
            log("File watcher already running")
            return
        directory = os.path.dirname(self.config_path)
        handler = _ConfigFileHandler(self)
        observer = Observer()
        observer.schedule(handler, directory, recursive=False)
        observer.daemon = True
        observer.start()
        self._observer = observer
        log(f"File watcher started on directory: {directory}")

    def stop_watcher(self):
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=1.0)
            self._observer = None
