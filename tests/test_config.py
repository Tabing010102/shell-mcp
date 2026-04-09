"""Tests for config module."""

import pytest

from shell_mcp.config import load_config, resolve_shell


def test_resolve_shell_prefers_configured(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert resolve_shell("/bin/bash") == "/bin/bash"


def test_resolve_shell_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert resolve_shell("") == "/bin/zsh"


def test_resolve_shell_falls_back_to_bin_sh(monkeypatch):
    monkeypatch.delenv("SHELL", raising=False)
    assert resolve_shell("") == "/bin/sh"


def test_load_config_merges_yaml_and_cli(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "transport: streamable-http\n"
        "host: 0.0.0.0\n"
        "port: 9000\n"
        "output_truncation_mode: head\n"
        "completed_task_ttl: 120.0\n"
        "blacklist:\n"
        "  - rm\n"
        "unknown_option: ignored\n"
    )

    cfg = load_config(
        config_path=str(config_file),
        cli_overrides={
            "port": 9100,
            "output_truncation_mode": "tail",
            "completed_task_ttl": 15.0,
            "blacklist": ["echo"],
            "shell": "/bin/bash",
        },
    )

    assert cfg.transport == "streamable-http"
    assert cfg.host == "0.0.0.0"
    assert cfg.port == 9100
    assert cfg.output_truncation_mode == "tail"
    assert cfg.completed_task_ttl == 15.0
    assert cfg.blacklist == ["echo"]
    assert cfg.shell == "/bin/bash"


def test_load_config_rejects_invalid_output_truncation_mode(tmp_path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text("output_truncation_mode: backwards\n")

    with pytest.raises(ValueError, match="output_truncation_mode"):
        load_config(config_path=str(config_file))
