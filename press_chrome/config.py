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


class ConfigError(Exception):
    """config.json is unusable. The message names the file and how to repair it."""


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


def _bad_config(path: Path, problem: object) -> ConfigError:
    return ConfigError(
        f"Bad config file {path}: {problem}. Fix it by hand, or run `chtabs init --force` "
        "to reset it (this also rotates the token, so restart the daemon and paste "
        "the new token into the extension)."
    )


def _parse_port(value: Any) -> int | None:
    """The port as an int, or None if it isn't one. Numeric strings are accepted."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        port = int(value)
    except ValueError:
        return None
    return port if 1 <= port <= 65535 else None


def read_config() -> dict[str, Any]:
    """Defaults overlaid with config.json. A missing file is fine; a bad one raises ConfigError."""
    p = config_path()
    cfg = default_config()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return cfg
    # ValueError covers bad JSON and bad UTF-8; RecursionError, absurdly nested JSON.
    except (OSError, ValueError, RecursionError) as exc:
        raise _bad_config(p, exc) from exc
    if not isinstance(data, dict):
        raise _bad_config(p, f"expected a JSON object, got {type(data).__name__}")
    cfg.update(data)
    port = _parse_port(cfg["port"])
    if port is None:
        raise _bad_config(p, f"port must be a whole number from 1 to 65535, got {cfg['port']!r}")
    cfg["port"] = port
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
    """Create token + config. Returns (token, config).

    Without force, a bad config.json raises ConfigError before anything is written.
    With force, the old file is never read, which is what makes it the repair path.
    The config is written first so that a failed repair doesn't also rotate the token.
    """
    ensure_dir()
    keep = None if force else read_config()
    try:
        if force:
            config_path().unlink(missing_ok=True)  # An unreadable file can't be overwritten.
        cfg = write_config(keep)
    except OSError as exc:
        raise ConfigError(f"Cannot write config file {config_path()}: {exc}") from exc
    existing = None if force else read_token()
    return existing or write_token(), cfg


def base_url(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or read_config()
    return f"http://{cfg.get('host', DEFAULT_HOST)}:{int(cfg.get('port', DEFAULT_PORT))}"


def ws_url(cfg: dict[str, Any] | None = None) -> str:
    cfg = cfg or read_config()
    return f"ws://{cfg.get('host', DEFAULT_HOST)}:{int(cfg.get('port', DEFAULT_PORT))}/ws"
