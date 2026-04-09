"""CLI entry point for shell-mcp server."""

from __future__ import annotations

import argparse

from . import server
from .config import ShellMCPConfig, load_config
from .task_manager import TaskManager


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shell MCP Server")
    parser.add_argument(
        "--config", default=None, help="Path to YAML config file"
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="Transport type (default: stdio)",
    )
    parser.add_argument("--host", default=None, help="Host for HTTP transport")
    parser.add_argument(
        "--port", type=int, default=None, help="Port for HTTP transport"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        dest="default_timeout",
        help="Default command timeout in seconds",
    )
    parser.add_argument(
        "--max-output-length",
        type=int,
        default=None,
        dest="max_output_length",
        help="Max output length in chars",
    )
    parser.add_argument(
        "--completed-task-ttl",
        type=float,
        default=None,
        dest="completed_task_ttl",
        help=(
            "Seconds to retain completed background tasks in memory "
            "(0 disables expiry)"
        ),
    )
    parser.add_argument(
        "--shell", default=None, help="Shell to use (auto-detect if empty)"
    )
    parser.add_argument(
        "--blacklist",
        default=None,
        help="Comma-separated list of blocked commands",
    )
    parser.add_argument(
        "--whitelist",
        default=None,
        help="Comma-separated list of allowed commands (overrides blacklist)",
    )
    return parser.parse_args()


def _build_cli_overrides(args: argparse.Namespace) -> dict:
    """Convert argparse namespace to dict of non-None overrides."""
    overrides: dict = {}
    for key in (
        "transport",
        "host",
        "port",
        "default_timeout",
        "max_output_length",
        "completed_task_ttl",
        "shell",
    ):
        val = getattr(args, key, None)
        if val is not None:
            overrides[key] = val

    if args.blacklist is not None:
        overrides["blacklist"] = [
            s.strip() for s in args.blacklist.split(",") if s.strip()
        ]
    if args.whitelist is not None:
        overrides["whitelist"] = [
            s.strip() for s in args.whitelist.split(",") if s.strip()
        ]
    return overrides


def main() -> None:
    """Main entry point."""
    args = _parse_args()
    cli_overrides = _build_cli_overrides(args)
    cfg = load_config(config_path=args.config, cli_overrides=cli_overrides)

    # Set module-level globals in server
    server.config = cfg
    server.task_manager = TaskManager(cfg)
    server.configure_mcp_runtime(cfg)

    server.mcp.run(transport=cfg.transport)


if __name__ == "__main__":
    main()
