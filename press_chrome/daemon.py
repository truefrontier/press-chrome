"""Localhost bridge: HTTP for CLI + WebSocket for MV3 extension."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
import uuid
from typing import Any

from aiohttp import WSMsgType, web

from . import __version__
from .config import DEFAULT_HOST, DEFAULT_PORT, read_config, read_token

log = logging.getLogger("press_chrome.daemon")

PENDING_TIMEOUT = 30.0


class BridgeState:
    def __init__(self, token: str) -> None:
        self.token = token
        self.extension_ws: web.WebSocketResponse | None = None
        self.extension_meta: dict[str, Any] = {}
        self.pending: dict[str, asyncio.Future] = {}
        self.started_at = time.time()
        self.paused = False

    def extension_connected(self) -> bool:
        return self.extension_ws is not None and not self.extension_ws.closed

    async def send_to_extension(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.paused:
            return {"ok": False, "error": "agent_access_paused", "code": 4}
        if not self.extension_connected():
            return {"ok": False, "error": "extension_not_connected", "code": 4}
        req_id = payload.get("id") or str(uuid.uuid4())
        payload = {**payload, "id": req_id}
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self.pending[req_id] = fut
        assert self.extension_ws is not None
        try:
            await self.extension_ws.send_json(payload)
            return await asyncio.wait_for(fut, timeout=PENDING_TIMEOUT)
        except asyncio.TimeoutError:
            self.pending.pop(req_id, None)
            return {"ok": False, "error": "extension_timeout", "code": 5}
        except Exception as exc:  # noqa: BLE001
            self.pending.pop(req_id, None)
            return {"ok": False, "error": str(exc), "code": 5}

    def resolve(self, msg: dict[str, Any]) -> None:
        req_id = msg.get("id")
        if not req_id or req_id not in self.pending:
            return
        fut = self.pending.pop(req_id)
        if not fut.done():
            fut.set_result(msg)


def _check_auth(request: web.Request, state: BridgeState) -> web.Response | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return web.json_response({"ok": False, "error": "missing_bearer"}, status=401)
    token = auth[len("Bearer ") :].strip()
    if not token or not secrets.compare_digest(token, state.token):
        return web.json_response({"ok": False, "error": "invalid_token"}, status=401)
    return None


async def handle_status(request: web.Request) -> web.Response:
    state: BridgeState = request.app["state"]
    err = _check_auth(request, state)
    if err:
        return err
    cfg = read_config()
    body = {
        "ok": True,
        "version": __version__,
        "daemon": True,
        "host": cfg.get("host", DEFAULT_HOST),
        "port": int(cfg.get("port", DEFAULT_PORT)),
        "trust": cfg.get("trust", "shared_plus_active"),
        "extension_connected": state.extension_connected(),
        "paused": state.paused,
        "uptime_s": round(time.time() - state.started_at, 1),
        "extension": state.extension_meta,
    }
    return web.json_response(body)


async def handle_rpc(request: web.Request) -> web.Response:
    state: BridgeState = request.app["state"]
    err = _check_auth(request, state)
    if err:
        return err
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)
    if not isinstance(payload, dict) or "type" not in payload:
        return web.json_response({"ok": False, "error": "type_required"}, status=400)
    rpc_type = payload["type"]
    if rpc_type in {"click", "type", "navigate", "write"}:
        return web.json_response(
            {
                "ok": False,
                "error": "write_actions_blocked",
                "hint": "See docs/FUTURE_ACTIONS.md — Jev gate required before any write tools.",
                "code": 2,
            },
            status=400,
        )
    result = await state.send_to_extension(payload)
    status = 200
    if not result.get("ok", True) and result.get("code") == 4:
        status = 503
    elif not result.get("ok", True) and result.get("code") == 3:
        status = 404
    return web.json_response(result, status=status)


async def handle_ws(request: web.Request) -> web.WebSocketResponse:
    state: BridgeState = request.app["state"]
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    authenticated = False

    async for msg in ws:
        if msg.type == WSMsgType.TEXT:
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                await ws.send_json({"ok": False, "error": "invalid_json"})
                continue
            if not isinstance(data, dict):
                continue
            mtype = data.get("type")
            if mtype == "hello":
                tok = (data.get("token") or "").strip()
                if not tok or not secrets.compare_digest(tok, state.token):
                    await ws.send_json({"ok": False, "error": "auth_failed", "type": "hello_ack"})
                    await ws.close(code=4401, message=b"auth_failed")
                    break
                authenticated = True
                if state.extension_ws and state.extension_ws is not ws and not state.extension_ws.closed:
                    try:
                        await state.extension_ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                state.extension_ws = ws
                state.extension_meta = {
                    "version": data.get("version"),
                    "trust": data.get("trust"),
                    "paused": bool(data.get("paused")),
                    "connected_at": time.time(),
                }
                state.paused = bool(data.get("paused"))
                await ws.send_json(
                    {
                        "ok": True,
                        "type": "hello_ack",
                        "version": __version__,
                        "trust": read_config().get("trust", "shared_plus_active"),
                    }
                )
                continue
            if not authenticated:
                await ws.send_json({"ok": False, "error": "auth_required"})
                continue
            if mtype == "status_push":
                state.extension_meta.update(
                    {
                        "trust": data.get("trust", state.extension_meta.get("trust")),
                        "paused": bool(data.get("paused", state.paused)),
                        "shared_count": data.get("shared_count"),
                    }
                )
                state.paused = bool(data.get("paused", state.paused))
                continue
            # Response to a pending RPC
            if "id" in data:
                state.resolve(data)
        elif msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED):
            break

    if state.extension_ws is ws:
        state.extension_ws = None
    return ws


async def handle_health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True, "service": "press-chrome", "version": __version__})


def create_app(token: str | None = None) -> web.Application:
    tok = token or read_token()
    if not tok:
        raise RuntimeError("No token. Run: chtabs init")
    app = web.Application()
    app["state"] = BridgeState(tok)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/status", handle_status)
    app.router.add_post("/rpc", handle_rpc)
    app.router.add_get("/ws", handle_ws)
    return app


async def run_daemon(
    host: str | None = None,
    port: int | None = None,
    token: str | None = None,
) -> None:
    cfg = read_config()
    host = host or str(cfg.get("host", DEFAULT_HOST))
    port = int(port or cfg.get("port", DEFAULT_PORT))
    app = create_app(token=token)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    log.info("press-chrome daemon listening on http://%s:%s (ws /ws)", host, port)
    print(f"press-chrome daemon listening on http://{host}:{port}", flush=True)
    print(f"extension WebSocket: ws://{host}:{port}/ws", flush=True)
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await runner.cleanup()


def main_serve(host: str | None = None, port: int | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run_daemon(host=host, port=port))
