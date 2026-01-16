import argparse
import json
import os
import signal
import threading
import time
from queue import Queue, Empty
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
import uvicorn

from ableton_client import AbletonTCPClient
from config_manager import ConfigManager
from udp_receiver import UDPReceiver
from udp_sender import UDPSender


def log(msg: str):
    """Simple logging helper"""
    print(f"[SmartRouter] {msg}", flush=True)


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


class SmartRouter:
    def __init__(self, config_path: str, streams_cache_path: str, stream_values_path: str):
        self.config_manager = ConfigManager(config_path, streams_cache_path)
        self.queue = Queue()
        self._receiver = None
        self._sender = None
        self._ableton_client: Optional[AbletonTCPClient] = None
        self._running = False
        self._last_values: Dict[str, float] = {}
        self._current_stream_values: Dict[str, float] = {}
        self._values_lock = threading.Lock()
        self._stream_values_path = stream_values_path
        self._last_stream_values_write = 0.0
        self._api_app = self._create_api_app()
        self._api_thread: Optional[threading.Thread] = None
        self._api_server: Optional[uvicorn.Server] = None

    def start(self, host: str = "0.0.0.0"):
        settings = self.config_manager.get_settings()
        mocap_port = int(settings.get("mocap_port", 9877))
        ableton_host = settings.get("ableton_host", "localhost")
        ableton_port = int(settings.get("ableton_port", 9878))
        ableton_tcp_port = int(settings.get("ableton_tcp_port", 9877))
        api_host = settings.get("api_host", "0.0.0.0")
        api_port = int(settings.get("api_port", 9090))

        log(f"Starting Smart Router...")
        log(f"  MoCap UDP: {host}:{mocap_port}")
        log(f"  Ableton UDP: {ableton_host}:{ableton_port}")
        log(f"  Ableton TCP: {ableton_host}:{ableton_tcp_port}")
        log(f"  Router API: {api_host}:{api_port}")

        self._receiver = UDPReceiver(host, mocap_port, self.queue)
        self._sender = UDPSender(ableton_host, ableton_port)
        self._ableton_client = AbletonTCPClient(ableton_host, ableton_tcp_port)

        self.config_manager.start_watcher()
        self._start_api_server(api_host, api_port)
        self._receiver.start()
        self._running = True
        log("Smart Router running. Press Ctrl+C to stop.")
        self._main_loop()

    def stop(self):
        self._running = False
        if self._receiver:
            self._receiver.stop()
        self.config_manager.stop_watcher()
        if self._api_server:
            self._api_server.should_exit = True
        if self._ableton_client:
            self._ableton_client.disconnect()

    def _write_stream_values(self):
        """Write current stream values to JSON file for web UI"""
        try:
            self._last_stream_values_write = time.time()
            with self._values_lock:
                values_snapshot = dict(self._current_stream_values)
            with open(self._stream_values_path, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": self._last_stream_values_write,
                    "values": values_snapshot
                }, f)
        except Exception as e:
            # Don't crash on write errors
            pass

    def _main_loop(self):
        last_log_time = 0
        while self._running:
            try:
                payload = self.queue.get(timeout=0.1)
            except Empty:
                # Still write stream values even if no new data
                now = time.time()
                if now - self._last_stream_values_write > 0.05:  # 50ms = 20Hz
                    self._write_stream_values()
                continue

            if not isinstance(payload, dict):
                continue

            stream_names = list(payload.keys())
            self.config_manager.register_streams(stream_names)

            # Log periodically (every 2 seconds) to avoid spam
            now = time.time()
            if now - last_log_time > 2.0:
                log(f"Received motion data: {list(payload.keys())}")
                last_log_time = now

            # Update current stream values
            with self._values_lock:
                for stream_name, raw_value in payload.items():
                    if isinstance(raw_value, (int, float)):
                        self._current_stream_values[stream_name] = float(raw_value)

            # Write stream values periodically
            if now - self._last_stream_values_write > 0.05:  # 50ms = 20Hz
                self._write_stream_values()

            for stream_name, raw_value in payload.items():
                if not isinstance(raw_value, (int, float)):
                    continue
                mappings = self.config_manager.get_mappings_for_stream(stream_name)
                if mappings and now - last_log_time < 0.1:  # Only log if we just logged above
                    log(f"  '{stream_name}' -> {len(mappings)} mapping(s)")
                for mapping in mappings:
                    self._apply_mapping(stream_name, float(raw_value), mapping)

    def _apply_mapping(self, stream_name: str, raw_value: float, mapping: Dict):
        target = mapping.get("target", {})
        track_index = target.get("track_index")
        device_index = target.get("device_index")
        parameter_index = target.get("parameter_index")

        if track_index is None or device_index is None or parameter_index is None:
            return

        normalized = clamp(raw_value, 0.0, 1.0)

        smoothing = float(mapping.get("smoothing", 0.0))
        smoothing = clamp(smoothing, 0.0, 1.0)
        key = f"{stream_name}:{track_index}:{device_index}:{parameter_index}"
        if smoothing > 0.0:
            previous = self._last_values.get(key, normalized)
            normalized = (smoothing * previous) + ((1.0 - smoothing) * normalized)
        self._last_values[key] = normalized

        output_range = mapping.get("range", [0.0, 1.0])
        try:
            out_min = float(output_range[0])
            out_max = float(output_range[1])
        except Exception:
            out_min, out_max = 0.0, 1.0

        value = out_min + normalized * (out_max - out_min)
        value = clamp(value, out_min, out_max)

        self._sender.send_set_device_parameter(
            int(track_index),
            int(device_index),
            int(parameter_index),
            float(value)
        )

    def _create_api_app(self) -> FastAPI:
        app = FastAPI(title="Smart Router API")

        @app.get("/api/streams")
        def list_streams():
            return self.config_manager.get_streams_cache()

        @app.get("/api/stream-values")
        def stream_values():
            with self._values_lock:
                values_snapshot = dict(self._current_stream_values)
            return {"timestamp": time.time(), "values": values_snapshot}

        @app.get("/api/mappings")
        def list_mappings():
            return {"mappings": self.config_manager.list_mappings()}

        @app.post("/api/mappings")
        def create_mapping(payload: Dict[str, Any]):
            try:
                mapping = self._normalize_mapping_payload(payload)
                self.config_manager.add_mapping(mapping)
                return {"status": "ok", "mapping": mapping}
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.put("/api/mappings/{motion_stream}")
        def update_mapping(motion_stream: str, payload: Dict[str, Any]):
            try:
                existing = next(
                    (m for m in self.config_manager.list_mappings() if m.get("motion_stream") == motion_stream),
                    None
                )
                if not existing:
                    raise HTTPException(status_code=404, detail="Mapping not found")
                payload["motion_stream"] = motion_stream
                merged = {**existing, **payload}
                mapping = self._normalize_mapping_payload(merged)
                self.config_manager.update_mapping(motion_stream, mapping)
                return {"status": "ok", "mapping": mapping}
            except HTTPException:
                raise
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.delete("/api/mappings/{motion_stream}")
        def delete_mapping(motion_stream: str):
            try:
                self.config_manager.delete_mapping(motion_stream)
                return {"status": "ok"}
            except Exception as e:
                raise HTTPException(status_code=404, detail=str(e))

        @app.post("/api/mappings/create-from-last")
        def create_from_last(payload: Dict[str, Any]):
            try:
                motion_stream = payload.get("motion_stream")
                if not motion_stream:
                    raise ValueError("motion_stream is required")
                mapping = self.create_mapping_from_last_param(
                    motion_stream=motion_stream,
                    range_min=payload.get("range_min", 0.0),
                    range_max=payload.get("range_max", 1.0),
                    smoothing=payload.get("smoothing", 0.0),
                    enabled=payload.get("enabled", True)
                )
                return {"status": "ok", "mapping": mapping}
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.get("/api/ableton/last-selected")
        def last_selected():
            try:
                return self.get_last_selected_parameter()
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.get("/api/observe")
        def observe_state():
            try:
                return {
                    "streams": self.config_manager.get_streams_cache().get("streams", []),
                    "mappings": self.config_manager.list_mappings(),
                    "last_selected": self.get_last_selected_parameter()
                }
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        @app.post("/api/ableton/command")
        def ableton_command(payload: Dict[str, Any]):
            try:
                if not self._ableton_client:
                    raise RuntimeError("Ableton client not initialized")
                command_type = payload.get("type")
                params = payload.get("params", {})
                if not command_type:
                    raise ValueError("type is required")
                result = self._ableton_client.send_command(command_type, params)
                return {"status": "ok", "result": result}
            except Exception as e:
                raise HTTPException(status_code=400, detail=str(e))

        return app

    def _start_api_server(self, host: str, port: int):
        config = uvicorn.Config(self._api_app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        self._api_server = server
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        self._api_thread = thread

    def get_last_selected_parameter(self) -> Dict[str, Any]:
        if not self._ableton_client:
            raise RuntimeError("Ableton client not initialized")
        return self._ableton_client.send_command("get_last_selected_parameter")

    def create_mapping_from_last_param(
        self,
        motion_stream: str,
        range_min: float = 0.0,
        range_max: float = 1.0,
        smoothing: float = 0.0,
        enabled: bool = True
    ) -> Dict[str, Any]:
        last_selected = self.get_last_selected_parameter()
        if last_selected.get("type") != "parameter":
            raise ValueError("Last selected item is not a parameter")
        data = last_selected.get("data", {})
        track_index = data.get("track_index")
        device_index = data.get("device_index")
        param_index = data.get("param_index", data.get("parameter_index"))
        if track_index is None or device_index is None or param_index is None:
            raise ValueError("Last selected parameter is missing indices")
        device_name = data.get("device_name") or f"Device {device_index}"
        param_name = data.get("param_name") or f"Param {param_index}"
        display_name = f"Track {track_index} {device_name} {param_name}"
        mapping = {
            "motion_stream": motion_stream,
            "target": {
                "track_index": int(track_index),
                "device_index": int(device_index),
                "parameter_index": int(param_index)
            },
            "target_meta": {
                "track_name": data.get("track_name"),
                "device_name": device_name,
                "param_name": param_name
            },
            "display_name": display_name,
            "range": [float(range_min), float(range_max)],
            "smoothing": float(smoothing),
            "enabled": bool(enabled),
            "updated_at": time.time()
        }
        self.config_manager.add_mapping(mapping)
        return mapping

    def _normalize_mapping_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        motion_stream = payload.get("motion_stream")
        if not motion_stream:
            raise ValueError("motion_stream is required")

        target = payload.get("target", {})
        if "track_index" in payload:
            target["track_index"] = payload["track_index"]
        if "device_index" in payload:
            target["device_index"] = payload["device_index"]
        if "parameter_index" in payload:
            target["parameter_index"] = payload["parameter_index"]

        if target.get("track_index") is None or target.get("device_index") is None or target.get("parameter_index") is None:
            raise ValueError("track_index, device_index, parameter_index are required")

        range_min = float(payload.get("range_min", payload.get("range", [0.0, 1.0])[0]))
        range_max = float(payload.get("range_max", payload.get("range", [0.0, 1.0])[1]))
        smoothing = float(payload.get("smoothing", 0.0))
        enabled = bool(payload.get("enabled", True))
        display_name = payload.get("display_name")
        if not display_name:
            display_name = f"Track {target['track_index']} Device {target['device_index']} Param {target['parameter_index']}"
        target_meta = payload.get("target_meta")

        return {
            "motion_stream": motion_stream,
            "target": {
                "track_index": int(target["track_index"]),
                "device_index": int(target["device_index"]),
                "parameter_index": int(target["parameter_index"])
            },
            "target_meta": target_meta,
            "display_name": display_name,
            "range": [range_min, range_max],
            "smoothing": smoothing,
            "enabled": enabled,
            "updated_at": time.time()
        }


def _parse_args():
    parser = argparse.ArgumentParser(description="Smart Router for motion data → Ableton")
    parser.add_argument("--config", default=None, help="Path to mappings.json")
    parser.add_argument("--streams-cache", default=None, help="Path to streams cache JSON")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind UDP receiver")
    return parser.parse_args()


def main():
    args = _parse_args()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config or os.path.join(base_dir, "mappings.json")
    streams_cache = args.streams_cache or os.path.join(base_dir, "streams.json")
    stream_values_path = os.path.join(base_dir, "stream_values.json")

    router = SmartRouter(config_path, streams_cache, stream_values_path)

    def _handle_exit(signum, frame):
        router.stop()

    signal.signal(signal.SIGINT, _handle_exit)
    signal.signal(signal.SIGTERM, _handle_exit)

    router.start(host=args.host)


if __name__ == "__main__":
    main()
