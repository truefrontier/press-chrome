"""Config + token under ~/.press-chrome (mode 0600)."""

from __future__ import annotations

import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18793  # avoid OpenClaw 18792
DEFAULT_TRUST = "shared_plus_active"
CONFIG_DIR_NAME = ".press-chrome"


def config_dir() -> Path:
    return Path.home() / CONFIG_DIR_NAME


def token_path() -> Path:
    return config_dir() / "token"


def config_path() -> Path:
    return config_dir() / "config.json"


def _chmod_600(path: Path) -> None:
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def ensure_dir() -> Path:
    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, stat.S_IRWXU)
    return d


def read_token() -> str | None:
    p = token_path()
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def write_token(token: str | None = None) -> str:
    ensure_dir()
    token = token or secrets.token_urlsafe(32)
    p = token_path()
    p.write_text(token + "\n", encoding="utf-8")
    _chmod_600(p)
    return token


def default_config() -> dict[str, Any]:
    return {
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "trust": DEFAULT_TRUST,
        "version": "1.0.0",
    }


def read_config() -> dict[str, Any]:
    p = config_path()
    cfg = default_config()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                cfg.update(data)
        except json.JSONDecodeError:
            pass
    return cfg


def write_config(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    ensure_dir()
    out = default_config()
    if cfg:
        out.update(cfg)
    p = config_path()
    p.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    _chmod_600(p)
    return out


def init_config(*, force: bool = False) -> tuple[str, dict[str, Any]]:
    """Create token + config. Returns (token, config)."""
    ensure_dir()
    existing = read_token()
    if existing and not force:
        token = existing
    else:
        token = write_token()
    cfg = write_config(read_config() if config_path().exists() and not force else None)
    return token, cfg


def base_url(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or read_config()
    return f"http://{cfg.get('host', DEFAULT_HOST)}:{int(cfg.get('port', DEFAULT_PORT))}"


def ws_url(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or read_config()
    return f"ws://{cfg.get('host', DEFAULT_HOST)}:{int(cfg.get('port', DEFAULT_PORT))}/ws"
