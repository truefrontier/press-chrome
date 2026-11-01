"""A bad config.json: clear CLI error, running daemon survives, init --force repairs."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer, unused_port
from click.testing import CliRunner

import press_chrome.config as config
from press_chrome.cli import main
from press_chrome.config import ConfigError
from press_chrome.daemon import create_app, run_daemon

TOKEN = "test-token-abc"

BAD_FILES = {
    "corrupt-json": b"{not json",
    "empty-file": b"",
    "not-utf8": b"\xff\xfe\x00",
    "array-not-object": b"[]",
    "null-not-object": b"null",
    "string-not-object": b'"text"',
    "string-port": b'{"port": "abc"}',
    "null-port": b'{"port": null}',
    "bool-port": b'{"port": true}',
    "float-port": b'{"port": 1.5}',
    "port-too-big": b'{"port": 70000}',
    "port-zero": b'{"port": 0}',
    "too-deeply-nested": b"[" * 200_000,
}
bad_files = pytest.mark.parametrize("raw", BAD_FILES.values(), ids=BAD_FILES.keys())


def _mode_000(path):
    path.write_text("{}")
    path.chmod(0)


def _directory(path):
    path.mkdir()


unreadable = pytest.mark.parametrize("make_unreadable", [_mode_000, _directory])


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """config.json path under a temp home, with a token already in place."""
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path / ".press-chrome")
    config.write_token(TOKEN)
    return config.config_path()


@bad_files
def test_read_config_names_the_file_and_the_repair(cfg_file, raw):
    cfg_file.write_bytes(raw)
    with pytest.raises(ConfigError) as err:
        config.read_config()
    assert str(cfg_file) in str(err.value)
    assert "chtabs init --force" in str(err.value)


@unreadable
def test_read_config_reports_an_unreadable_file(cfg_file, make_unreadable):
    make_unreadable(cfg_file)
    with pytest.raises(ConfigError) as err:
        config.read_config()
    assert str(cfg_file) in str(err.value)


@pytest.mark.parametrize("url", [config.base_url, config.ws_url])
def test_urls_report_a_string_port_instead_of_crashing(cfg_file, url):
    cfg_file.write_text('{"port": "abc"}')
    with pytest.raises(ConfigError, match="'abc'"):
        url()


def test_missing_file_is_defaults(cfg_file):
    assert not cfg_file.exists()
    assert config.read_config()["port"] == 18793


def test_numeric_string_port_keeps_working(cfg_file):
    cfg_file.write_text('{"port": "19000"}')
    assert config.read_config()["port"] == 19000
    assert config.base_url() == "http://127.0.0.1:19000"


@pytest.mark.parametrize(
    "argv",
    [["status"], ["list"], ["read", "1"], ["init"], ["serve"], ["vision", "ask", "1", "a cat?"]],
    ids=lambda argv: argv[0],
)
def test_cli_exits_2_with_the_path_and_no_traceback(cfg_file, argv):
    # A string port, not corrupt JSON: if the check regressed, `serve` would start on
    # corrupt JSON and hang this test, but a string port still fails fast at int().
    cfg_file.write_text('{"port": "abc"}')
    result = CliRunner().invoke(main, argv)
    assert result.exit_code == 2, result.output
    assert str(cfg_file) in result.output
    assert "Traceback" not in result.output


@bad_files
def test_plain_init_leaves_a_bad_file_alone(cfg_file, raw):
    config.token_path().unlink()
    cfg_file.write_bytes(raw)
    result = CliRunner().invoke(main, ["init"])
    assert result.exit_code == 2, result.output
    assert str(cfg_file) in result.output
    assert cfg_file.read_bytes() == raw
    assert not config.token_path().exists()


def test_plain_init_keeps_a_good_config_and_token(cfg_file):
    cfg_file.write_text('{"port": 19000, "trust": "shared_only"}')
    token, cfg = config.init_config()
    assert token == TOKEN
    assert (cfg["port"], cfg["trust"]) == (19000, "shared_only")
    assert json.loads(cfg_file.read_text())["port"] == 19000


@bad_files
def test_init_force_repairs_a_bad_file(cfg_file, raw):
    cfg_file.write_bytes(raw)
    result = CliRunner().invoke(main, ["init", "--force"])
    assert result.exit_code == 0, result.output
    assert "ws://127.0.0.1:18793/ws" in result.output
    assert json.loads(cfg_file.read_text()) == config.default_config()
    assert cfg_file.stat().st_mode & 0o777 == 0o600
    assert config.read_config()["port"] == 18793
    assert config.read_token() != TOKEN


def test_init_force_repairs_an_unreadable_file(cfg_file):
    _mode_000(cfg_file)
    result = CliRunner().invoke(main, ["init", "--force"])
    assert result.exit_code == 0, result.output
    assert config.read_config()["port"] == 18793


def test_init_force_repairs_a_config_when_the_token_file_is_bad(cfg_file):
    cfg_file.write_text("{not json")
    config.token_path().write_bytes(b"\xff\xfe")
    result = CliRunner().invoke(main, ["init", "--force"])
    assert result.exit_code == 0, result.output
    assert config.read_config()["port"] == 18793
    assert config.read_token()


def test_init_force_keeps_the_token_when_it_cannot_write_the_config(cfg_file):
    _directory(cfg_file)
    result = CliRunner().invoke(main, ["init", "--force"])
    assert result.exit_code == 2, result.output
    assert str(cfg_file) in result.output
    assert config.read_token() == TOKEN


@unreadable
async def test_running_daemon_survives_the_file_becoming_unreadable(cfg_file, make_unreadable):
    auth = {"Authorization": f"Bearer {TOKEN}"}
    client = TestClient(TestServer(create_app(token=TOKEN)))
    await client.start_server()
    try:
        make_unreadable(cfg_file)
        resp = await client.get("/status", headers=auth)
        assert resp.status == 200
        assert (await resp.json())["port"] == 18793
    finally:
        await client.close()


@bad_files
async def test_running_daemon_survives_the_file_going_bad(cfg_file, raw, caplog):
    auth = {"Authorization": f"Bearer {TOKEN}"}

    async def hello_trust():
        ws = await client.ws_connect("/ws")
        await ws.send_json({"type": "hello", "token": TOKEN})
        ack = await ws.receive_json()
        await ws.close()
        assert ack["ok"] is True
        return ack["trust"]

    cfg_file.write_text('{"port": 19000, "trust": "shared_only"}')
    client = TestClient(TestServer(create_app(token=TOKEN)))
    await client.start_server()
    try:
        assert (await (await client.get("/status", headers=auth)).json())["port"] == 19000

        cfg_file.write_bytes(raw)
        resp = await client.get("/status", headers=auth)
        assert resp.status == 200
        status = await resp.json()
        assert (status["port"], status["trust"]) == (19000, "shared_only")
        assert await hello_trust() == "shared_only"
        assert f"Keeping last good config: Bad config file {cfg_file}" in caplog.text

        # Hello first: it must re-read the repaired file, not reuse what /status cached.
        cfg_file.write_text('{"port": 19000, "trust": "all_tabs_meta"}')
        assert await hello_trust() == "all_tabs_meta"
        assert (await (await client.get("/status", headers=auth)).json())["trust"] == "all_tabs_meta"
    finally:
        await client.close()


async def test_daemon_keeps_its_startup_config_if_the_file_breaks_before_first_read(cfg_file):
    port = unused_port()
    cfg_file.write_text(json.dumps({"port": port, "trust": "shared_only"}))
    daemon = asyncio.create_task(run_daemon(token=TOKEN))
    try:
        async with aiohttp.ClientSession(base_url=f"http://127.0.0.1:{port}") as http:
            for _ in range(100):
                try:
                    await http.get("/health")
                    break
                except aiohttp.ClientConnectionError:
                    await asyncio.sleep(0.02)
            cfg_file.write_text("{not json")
            resp = await http.get("/status", headers={"Authorization": f"Bearer {TOKEN}"})
            status = await resp.json()
        assert (status["port"], status["trust"]) == (port, "shared_only")
    finally:
        daemon.cancel()
        await asyncio.gather(daemon, return_exceptions=True)
