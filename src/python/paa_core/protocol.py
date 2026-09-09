"""Bounded UTF-8 JSON Lines control protocol; stdout contains only responses."""

from __future__ import annotations

import json
import os
import platform
from typing import BinaryIO

MAX_LINE_BYTES = 65_536


def error(request_id: str | None, code: str, message: str) -> dict:
    return {"id": request_id, "error": {"code": code, "message": message}}


def handle(request: object) -> tuple[dict, bool]:
    if not isinstance(request, dict):
        return error(None, "invalid_request", "Request must be an object"), False
    request_id = request.get("id")
    if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
        return error(None, "invalid_request", "A short string id is required"), False
    if set(request) - {"id", "method", "params"} or not isinstance(request.get("method"), str):
        return error(request_id, "invalid_request", "Invalid request structure"), False
    if request.get("params", {}) != {}:
        return error(request_id, "invalid_params", "This method accepts no parameters"), False
    method = request["method"]
    if method == "health":
        result = {
            "pythonVersion": platform.python_version(),
            "processId": os.getpid(),
            "capabilities": [
                {"id": "recording", "available": False},
                {"id": "transcription", "available": False},
                {"id": "summary", "available": False},
            ],
        }
    elif method == "meetings.list":
        result = {"meetings": []}
    elif method == "shutdown":
        return {"id": request_id, "result": {"stopping": True}}, True
    else:
        return error(request_id, "method_not_found", "Unknown method"), False
    return {"id": request_id, "result": result}, False


def serve(source: BinaryIO, destination: BinaryIO) -> None:
    while True:
        line = source.readline(MAX_LINE_BYTES + 1)
        if not line:
            return
        if len(line) > MAX_LINE_BYTES:
            while not line.endswith(b"\n"):
                line = source.readline(MAX_LINE_BYTES + 1)
                if not line:
                    break
            response, stopping = error(None, "invalid_request", "Request is too large"), False
        else:
            try:
                request = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
                response, stopping = error(None, "invalid_json", "Expected UTF-8 JSON"), False
            else:
                response, stopping = handle(request)
        destination.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))
        destination.flush()
        if stopping:
            return
