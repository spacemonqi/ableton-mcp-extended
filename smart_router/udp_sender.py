import json
import socket
from typing import List


class UDPSender:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_set_device_parameter(self, track_index: int, device_index: int, parameter_index: int, value: float):
        message = {
            "type": "set_device_parameter",
            "params": {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_index": parameter_index,
                "value": value
            }
        }
        self._send(message)

    def send_batch_set_device_parameters(self, track_index: int, device_index: int, parameter_indices: List[int], values: List[float]):
        message = {
            "type": "batch_set_device_parameters",
            "params": {
                "track_index": track_index,
                "device_index": device_index,
                "parameter_indices": parameter_indices,
                "values": values
            }
        }
        self._send(message)

    def _send(self, message):
        payload = json.dumps(message).encode("utf-8")
        self._sock.sendto(payload, (self.host, self.port))
