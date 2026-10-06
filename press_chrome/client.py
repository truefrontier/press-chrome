"""HTTP client from chtabs CLI → local daemon."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import base_url, read_config, read_token


class ClientError(Exception):
    def __init__(self, message: str, code: int = 5, payload: dict | None = None):
        super().__init__(message)
        self.code = code
        self.payload = payload or {}


def _request(
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    timeout: float = 35.0,
) -> dict[str, Any]:
    token = read_token()
    if not token:
        raise ClientError("No token. Run: chtabs init", code=4)
    url = base_url(read_config()) + path
    data = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {"ok": True}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            payload = {"ok": False, "error": exc.reason}
        code = int(payload.get("code") or (4 if exc.code in (401, 403, 503) else 5))
        if exc.code == 404:
            code = 3
        raise ClientError(payload.get("error") or str(exc.reason), code=code, payload=payload) from exc
    except urllib.error.URLError as exc:
        raise ClientError(
            f"daemon_unreachable: {exc.reason}. Start with: chtabs serve",
            code=4,
        ) from exc


def status() -> dict[str, Any]:
    return _request("GET", "/status")


def rpc(payload: dict[str, Any]) -> dict[str, Any]:
    return _request("POST", "/rpc", payload)


def health() -> dict[str, Any]:
    url = base_url(read_config()) + "/health"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ClientError(f"daemon_unreachable: {exc}", code=4) from exc
