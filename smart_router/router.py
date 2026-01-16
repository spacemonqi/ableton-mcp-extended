import argparse
import json
import os
import signal
import time
from queue import Queue, Empty
from typing import Dict

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
        self._running = False
        self._last_values: Dict[str, float] = {}
        self._current_stream_values: Dict[str, float] = {}
        self._stream_values_path = stream_values_path
        self._last_stream_values_write = 0.0

    def start(self, host: str = "0.0.0.0"):
        settings = self.config_manager.get_settings()
        mocap_port = int(settings.get("mocap_port", 9877))
        ableton_host = settings.get("ableton_host", "localhost")
        ableton_port = int(settings.get("ableton_port", 9878))

        log(f"Starting Smart Router...")
        log(f"  MoCap UDP: {host}:{mocap_port}")
        log(f"  Ableton UDP: {ableton_host}:{ableton_port}")

        self._receiver = UDPReceiver(host, mocap_port, self.queue)
        self._sender = UDPSender(ableton_host, ableton_port)

        self.config_manager.start_watcher()
        self._receiver.start()
        self._running = True
        log("Smart Router running. Press Ctrl+C to stop.")
        self._main_loop()

    def stop(self):
        self._running = False
        if self._receiver:
            self._receiver.stop()
        self.config_manager.stop_watcher()

    def _write_stream_values(self):
        """Write current stream values to JSON file for web UI"""
        try:
            self._last_stream_values_write = time.time()
            with open(self._stream_values_path, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": self._last_stream_values_write,
                    "values": self._current_stream_values
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
