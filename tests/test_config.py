"""Config / token unit tests."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import press_chrome.config as config


def test_init_creates_token_and_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path / ".press-chrome")
    token, cfg = config.init_config(force=True)
    assert token
    assert (tmp_path / ".press-chrome" / "token").exists()
    assert (tmp_path / ".press-chrome" / "config.json").exists()
    mode = (tmp_path / ".press-chrome" / "token").stat().st_mode & 0o777
    assert mode == 0o600
    assert cfg["port"] == 18793
    assert cfg["trust"] == "shared_plus_active"
    assert config.read_token() == token


def test_init_keeps_token_without_force(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path / ".press-chrome")
    t1, _ = config.init_config(force=True)
    t2, _ = config.init_config(force=False)
    assert t1 == t2
