"""Command parsing and blacklist/whitelist validation."""

from __future__ import annotations

import os
import re
import shlex


def extract_command_names(command_string: str) -> list[str]:
    """Extract all command names from a shell command string.

    Handles pipes, &&, ||, ;, $() subshells, backtick subshells,
    and bash/sh -c "..." patterns.
    """
    if not command_string or not command_string.strip():
        return []

    commands: list[str] = []

    # Extract commands from $() subshells before splitting
    for match in re.finditer(r"\$\(([^)]+)\)", command_string):
        commands.extend(extract_command_names(match.group(1)))

    # Extract commands from backtick subshells
    for match in re.finditer(r"`([^`]+)`", command_string):
        commands.extend(extract_command_names(match.group(1)))

    # Split into segments by shell operators (quote-aware)
    segments = _split_by_operators(command_string)

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        cmd_name = _extract_first_command(segment)
        if cmd_name:
            commands.append(cmd_name)
            # Check for bash/sh -c "..." pattern
            _extract_shell_c_commands(segment, cmd_name, commands)

    return commands


def validate_command(
    command_string: str,
    blacklist: list[str] | frozenset[str],
    whitelist: list[str] | frozenset[str],
) -> tuple[bool, str]:
    """Validate a command against blacklist/whitelist.

    Returns (is_allowed, reason).
    If whitelist is non-empty, every command must be in it.
    Otherwise, no command may be in the blacklist.
    """
    blacklist_set = set(blacklist)
    whitelist_set = set(whitelist)

    if not blacklist_set and not whitelist_set:
        return (True, "")

    names = extract_command_names(command_string)
    if not names:
        return (True, "")

    if whitelist_set:
        for name in names:
            base = os.path.basename(name)
            if base not in whitelist_set and name not in whitelist_set:
                return (False, f"Command '{base}' is not in the whitelist")
        return (True, "")

    for name in names:
        base = os.path.basename(name)
        if base in blacklist_set or name in blacklist_set:
            return (False, f"Command '{base}' is blacklisted")

    return (True, "")


def _split_by_operators(command_string: str) -> list[str]:
    """Split a command string by |, &&, ||, ; while respecting quotes."""
    segments: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    i = 0
    chars = command_string

    while i < len(chars):
        c = chars[i]

        if c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(c)
            i += 1
        elif c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(c)
            i += 1
        elif c == "\\" and not in_single_quote and i + 1 < len(chars):
            current.append(c)
            current.append(chars[i + 1])
            i += 2
        elif not in_single_quote and not in_double_quote:
            # Check for two-char operators first
            two = chars[i : i + 2]
            if two in ("&&", "||"):
                segments.append("".join(current))
                current = []
                i += 2
            elif c in ("|", ";"):
                segments.append("".join(current))
                current = []
                i += 1
            else:
                current.append(c)
                i += 1
        else:
            current.append(c)
            i += 1

    if current:
        segments.append("".join(current))

    return segments


def _extract_first_command(segment: str) -> str | None:
    """Extract the command name from a segment, skipping env var assignments."""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        # Malformed quoting - try a simple split
        tokens = segment.split()

    for token in tokens:
        # Skip environment variable assignments (FOO=bar)
        if "=" in token and not token.startswith("="):
            key_part = token.split("=", 1)[0]
            if key_part.isidentifier():
                continue
        return os.path.basename(token)

    return None


def _extract_shell_c_commands(
    segment: str, cmd_name: str, commands: list[str]
) -> None:
    """If segment is bash/sh -c '...', recursively extract commands from the inner string."""
    base = os.path.basename(cmd_name)
    if base not in ("bash", "sh", "zsh", "dash", "ksh"):
        return

    try:
        tokens = shlex.split(segment)
    except ValueError:
        return

    for i, token in enumerate(tokens):
        if token == "-c" and i + 1 < len(tokens):
            inner_cmd = tokens[i + 1]
            commands.extend(extract_command_names(inner_cmd))
            break
