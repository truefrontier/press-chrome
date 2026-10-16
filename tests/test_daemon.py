"""Daemon auth + RPC self-test (no Chrome)."""

from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer

from press_chrome.daemon import create_app


@pytest.fixture
async def client_and_token():
    token = "test-token-abc"
    app = create_app(token=token)
    server = TestServer(app)
    client = TestClient(server)
    await client.start_server()
    try:
        yield client, token
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_health(client_and_token):
    client, _token = client_and_token
    resp = await client.get("/health")
    assert resp.status == 200
    data = await resp.json()
    assert data["ok"] is True


@pytest.mark.asyncio
async def test_status_requires_bearer(client_and_token):
    client, token = client_and_token
    resp = await client.get("/status")
    assert resp.status == 401
    resp = await client.get("/status", headers={"Authorization": f"Bearer {token}"})
    assert resp.status == 200
    data = await resp.json()
    assert data["daemon"] is True
    assert data["extension_connected"] is False


@pytest.mark.asyncio
async def test_rpc_without_extension(client_and_token):
    client, token = client_and_token
    resp = await client.post(
        "/rpc",
        json={"type": "list"},
        headers={"Authorization": f"Bearer {token}"},
    )
    data = await resp.json()
    assert data["ok"] is False
    assert data["error"] == "extension_not_connected"


@pytest.mark.asyncio
async def test_write_actions_blocked(client_and_token):
    client, token = client_and_token
    resp = await client.post(
        "/rpc",
        json={"type": "click"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status == 400
    data = await resp.json()
    assert data["error"] == "write_actions_blocked"


@pytest.mark.asyncio
async def test_ws_hello_and_list(client_and_token):
    client, token = client_and_token
    ws = await client.ws_connect("/ws")
    await ws.send_json(
        {"type": "hello", "token": token, "version": "1.0.0", "trust": "shared_plus_active"}
    )
    ack = await ws.receive_json()
    assert ack["ok"] is True
    assert ack["type"] == "hello_ack"

    async def extension_loop():
        async for msg in ws:
            if msg.type != WSMsgType.TEXT:
                break
            data = json.loads(msg.data)
            if data.get("type") == "list":
                await ws.send_json(
                    {
                        "id": data["id"],
                        "ok": True,
                        "tabs": [
                            {
                                "id": 1,
                                "title": "Example",
                                "url": "https://example.com",
                                "shared": True,
                                "active": True,
                            }
                        ],
                    }
                )

    task = asyncio.create_task(extension_loop())
    await asyncio.sleep(0.05)
    resp = await client.post(
        "/rpc",
        json={"type": "list"},
        headers={"Authorization": f"Bearer {token}"},
    )
    data = await resp.json()
    assert data["ok"] is True
    assert data["tabs"][0]["title"] == "Example"
    task.cancel()
    await ws.close()


@pytest.mark.asyncio
async def test_screenshot_rpc_forwarded(client_and_token):
    client, token = client_and_token
    ws = await client.ws_connect('/ws')
    await ws.send_json({'type': 'hello', 'token': token, 'version': '1.1.0'})
    await ws.receive_json()

    async def extension_capture():
        request = await ws.receive_json()
        assert request['type'] == 'screenshot' and request['tabId'] == 17
        # Screenshots can exceed aiohttp's default 4 MiB WS message limit.
        await ws.send_json({'id': request['id'], 'ok': True, 'dataUrl': 'x' * (5*1024*1024),
                            'devicePixelRatio': 2, 'scrollX': 0, 'scrollY': 100})

    task = asyncio.create_task(extension_capture())
    result = await client.post('/rpc', json={'type': 'screenshot', 'tabId': 17},
                               headers={'Authorization': f'Bearer {token}'})
    data = await result.json()
    assert data['ok'] and len(data['dataUrl']) == 5*1024*1024
    assert data['devicePixelRatio'] == 2
    await task
    await ws.close()
