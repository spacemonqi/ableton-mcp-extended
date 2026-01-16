import argparse
import json
import math
import socket
import time
from typing import List


def _parse_args():
    parser = argparse.ArgumentParser(description="Dummy motion capture UDP sender")
    parser.add_argument("--host", default="127.0.0.1", help="Destination host")
    parser.add_argument("--port", type=int, default=9877, help="Destination UDP port")
    parser.add_argument("--rate", type=float, default=60.0, help="Packets per second")
    parser.add_argument("--streams", default="wrist-bend,forearm-angle,elbow-height",
                        help="Comma-separated list of motion streams")
    return parser.parse_args()


def _sine(t: float, freq: float, phase: float = 0.0) -> float:
    return 0.5 + 0.5 * math.sin(2.0 * math.pi * freq * t + phase)


def main():
    args = _parse_args()
    stream_names: List[str] = [s.strip() for s in args.streams.split(",") if s.strip()]
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    start = time.time()
    while True:
        t = time.time() - start
        payload = {}
        for i, name in enumerate(stream_names):
            payload[name] = _sine(t, freq=0.1 + (i * 0.05), phase=i * 0.5)

        message = json.dumps(payload).encode("utf-8")
        sock.sendto(message, (args.host, args.port))
        time.sleep(max(0.0, 1.0 / args.rate))


if __name__ == "__main__":
    main()
