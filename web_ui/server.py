import json
import os
import time
from typing import Any, Dict, Optional

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

try:
    import fcntl
    HAS_FCNTL = True
except Exception:
    HAS_FCNTL = False


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAPPINGS_PATH = os.environ.get("MAPPINGS_PATH", os.path.join(PROJECT_ROOT, "smart_router", "mappings.json"))
STREAMS_PATH = os.environ.get("STREAMS_PATH", os.path.join(PROJECT_ROOT, "smart_router", "streams.json"))
LAST_SELECTED_PATH = os.environ.get("LAST_SELECTED_PATH", os.path.join(PROJECT_ROOT, "smart_router", "last_selected.json"))

app = FastAPI(title="Ableton Motion Mapping UI")


def _ensure_mappings_file():
    if not os.path.exists(MAPPINGS_PATH):
        os.makedirs(os.path.dirname(MAPPINGS_PATH), exist_ok=True)
        with open(MAPPINGS_PATH, "w", encoding="utf-8") as f:
            json.dump({"settings": {}, "mappings": []}, f, indent=2)


def _locked_read_json(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        if HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            return json.load(f)
        except Exception:
            return {}
        finally:
            if HAS_FCNTL:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _locked_write_json(path: str, data: Dict[str, Any]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        if HAS_FCNTL:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _normalize_mapping(payload: Dict[str, Any]) -> Dict[str, Any]:
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

    range_min = float(payload.get("range_min", 0.0))
    range_max = float(payload.get("range_max", 1.0))
    smoothing = float(payload.get("smoothing", 0.0))
    enabled = bool(payload.get("enabled", True))

    return {
        "motion_stream": motion_stream,
        "target": {
            "track_index": int(target["track_index"]),
            "device_index": int(target["device_index"]),
            "parameter_index": int(target["parameter_index"])
        },
        "range": [range_min, range_max],
        "smoothing": smoothing,
        "enabled": enabled,
        "updated_at": time.time()
    }


@app.get("/api/mappings")
def get_mappings():
    _ensure_mappings_file()
    return _locked_read_json(MAPPINGS_PATH)


@app.post("/api/mappings")
def create_mapping(payload: Dict[str, Any]):
    _ensure_mappings_file()
    try:
        mapping = _normalize_mapping(payload)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    config = _locked_read_json(MAPPINGS_PATH)
    mappings = config.get("mappings", [])
    existing = [m for m in mappings if m.get("motion_stream") == mapping["motion_stream"]]
    if existing:
        raise HTTPException(status_code=409, detail="Mapping for motion_stream already exists")
    mappings.append(mapping)
    config["mappings"] = mappings
    _locked_write_json(MAPPINGS_PATH, config)
    return {"status": "ok", "mapping": mapping}


@app.put("/api/mappings/{motion_stream}")
def update_mapping(motion_stream: str, payload: Dict[str, Any]):
    _ensure_mappings_file()
    config = _locked_read_json(MAPPINGS_PATH)
    mappings = config.get("mappings", [])
    updated = None
    for i, mapping in enumerate(mappings):
        if mapping.get("motion_stream") == motion_stream:
            payload["motion_stream"] = motion_stream
            updated = _normalize_mapping({**mapping, **payload})
            mappings[i] = updated
            break
    if updated is None:
        raise HTTPException(status_code=404, detail="Mapping not found")
    config["mappings"] = mappings
    _locked_write_json(MAPPINGS_PATH, config)
    return {"status": "ok", "mapping": updated}


@app.delete("/api/mappings/{motion_stream}")
def delete_mapping(motion_stream: str):
    _ensure_mappings_file()
    config = _locked_read_json(MAPPINGS_PATH)
    mappings = config.get("mappings", [])
    new_mappings = [m for m in mappings if m.get("motion_stream") != motion_stream]
    if len(new_mappings) == len(mappings):
        raise HTTPException(status_code=404, detail="Mapping not found")
    config["mappings"] = new_mappings
    _locked_write_json(MAPPINGS_PATH, config)
    return {"status": "ok"}


@app.get("/api/streams")
def list_streams():
    data = _locked_read_json(STREAMS_PATH)
    return data if data else {"streams": []}


@app.get("/api/ableton/last-selected")
def last_selected():
    data = _locked_read_json(LAST_SELECTED_PATH)
    return data if data else {"type": None, "data": None, "timestamp": None}


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")
