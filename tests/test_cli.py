"""Tests for cli module."""

import argparse

from shell_mcp import cli, server
from shell_mcp.config import ShellMCPConfig
from shell_mcp.task_manager import TaskManager


def test_build_cli_overrides_parses_values():
    args = argparse.Namespace(
        config=None,
        transport="streamable-http",
        host="0.0.0.0",
        port=9000,
        default_timeout=12.5,
        max_output_length=1234,
        shell="/bin/bash",
        blacklist="rm, mkfs",
        whitelist="echo, ls",
    )

    overrides = cli._build_cli_overrides(args)

    assert overrides == {
        "transport": "streamable-http",
        "host": "0.0.0.0",
        "port": 9000,
        "default_timeout": 12.5,
        "max_output_length": 1234,
        "shell": "/bin/bash",
        "blacklist": ["rm", "mkfs"],
        "whitelist": ["echo", "ls"],
    }


def test_main_loads_config_and_runs_server(monkeypatch):
    fake_args = argparse.Namespace(
        config="config.yaml",
        transport=None,
        host=None,
        port=None,
        default_timeout=None,
        max_output_length=None,
        shell=None,
        blacklist=None,
        whitelist=None,
    )
    cfg = ShellMCPConfig(transport="streamable-http", host="0.0.0.0", port=9001)
    run_call: dict[str, object] = {}

    monkeypatch.setattr(cli, "_parse_args", lambda: fake_args)
    monkeypatch.setattr(cli, "load_config", lambda config_path, cli_overrides: cfg)

    def fake_run(*, transport, host, port):
        run_call.update({"transport": transport, "host": host, "port": port})

    monkeypatch.setattr(server.mcp, "run", fake_run)

    cli.main()

    assert server.config is cfg
    assert isinstance(server.task_manager, TaskManager)
    assert run_call == {
        "transport": "streamable-http",
        "host": "0.0.0.0",
        "port": 9001,
    }
