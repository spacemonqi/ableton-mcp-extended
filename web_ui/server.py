import os
from typing import Any, Dict, Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles


ROUTER_API_BASE = os.environ.get("ROUTER_API_BASE", "http://localhost:9090")

app = FastAPI(title="Signal Router UI")


def _proxy_request(method: str, path: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{ROUTER_API_BASE}{path}"
    try:
        response = requests.request(method, url, json=payload, timeout=5)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Router not reachable: {e}")
    if not response.ok:
        try:
            detail = response.json()
        except Exception:
            detail = {"detail": response.text}
        raise HTTPException(status_code=response.status_code, detail=detail.get("detail", response.text))
    try:
        return response.json()
    except Exception:
        return {"status": "ok"}


@app.get("/api/mappings")
def get_mappings():
    return _proxy_request("GET", "/api/mappings")


@app.post("/api/mappings")
def create_mapping(payload: Dict[str, Any]):
    return _proxy_request("POST", "/api/mappings", payload)


@app.put("/api/mappings/{motion_stream}")
def update_mapping(motion_stream: str, payload: Dict[str, Any]):
    return _proxy_request("PUT", f"/api/mappings/{motion_stream}", payload)


@app.delete("/api/mappings/{motion_stream}")
def delete_mapping(motion_stream: str):
    return _proxy_request("DELETE", f"/api/mappings/{motion_stream}")


@app.post("/api/mappings/create-from-last")
def create_from_last(payload: Dict[str, Any]):
    return _proxy_request("POST", "/api/mappings/create-from-last", payload)


@app.get("/api/streams")
def list_streams():
    return _proxy_request("GET", "/api/streams")


@app.get("/api/ableton/last-selected")
def last_selected():
    return _proxy_request("GET", "/api/ableton/last-selected")


@app.get("/api/stream-values")
def stream_values():
    return _proxy_request("GET", "/api/stream-values")


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"), html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    host = os.environ.get("WEB_UI_HOST", "0.0.0.0")
    port = int(os.environ.get("WEB_UI_PORT", "8080"))
    uvicorn.run(app, host=host, port=port, log_level="info")
