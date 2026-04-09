"""Configuration for shell-mcp server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast

import yaml


_DEFAULT_NON_INTERACTIVE_ENV: dict[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "CI": "true",
    "DEBIAN_FRONTEND": "noninteractive",
}


OutputTruncationMode = Literal["head", "tail"]


@dataclass
class ShellMCPConfig:
    """Shell MCP server configuration."""

    shell: str = ""
    default_timeout: float = 30.0
    max_output_length: int = 50_000
    output_truncation_mode: OutputTruncationMode = "tail"
    keepalive_interval: float = 5.0
    completed_task_ttl: float = 3600.0
    blacklist: list[str] = field(default_factory=list)
    whitelist: list[str] = field(default_factory=list)
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    non_interactive_env: dict[str, str] = field(
        default_factory=lambda: dict(_DEFAULT_NON_INTERACTIVE_ENV)
    )

    def __post_init__(self) -> None:
        """Normalize configuration values that have constrained choices."""
        self.output_truncation_mode = normalize_output_truncation_mode(
            self.output_truncation_mode
        )


def resolve_shell(configured: str) -> str:
    """Resolve the shell to use.

    Priority: configured value > $SHELL env var > /bin/sh
    """
    if configured:
        return configured
    shell = os.environ.get("SHELL", "")
    if shell:
        return shell
    return "/bin/sh"


def normalize_output_truncation_mode(mode: str) -> OutputTruncationMode:
    """Normalize and validate an output truncation mode."""
    normalized = mode.strip().lower()
    if normalized not in {"head", "tail"}:
        raise ValueError(
            "output_truncation_mode must be either 'head' or 'tail'"
        )
    return cast(OutputTruncationMode, normalized)


def load_config(
    config_path: str | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> ShellMCPConfig:
    """Load configuration with priority: CLI > YAML > defaults."""
    config = ShellMCPConfig()

    # Layer 2: YAML config file
    if config_path:
        path = Path(config_path)
        if path.exists():
            with open(path) as f:
                yaml_data = yaml.safe_load(f)
            if isinstance(yaml_data, dict):
                _apply_dict_to_config(config, yaml_data)

    # Layer 3: CLI overrides (highest priority)
    if cli_overrides:
        _apply_dict_to_config(config, cli_overrides)

    return config


def _apply_dict_to_config(config: ShellMCPConfig, data: dict[str, Any]) -> None:
    """Apply a dict of values to a config, skipping None values and unknown keys."""
    valid_fields = {f.name for f in config.__dataclass_fields__.values()}
    for key, value in data.items():
        if value is None:
            continue
        if key not in valid_fields:
            continue
        if key == "output_truncation_mode":
            value = normalize_output_truncation_mode(str(value))
        setattr(config, key, value)
