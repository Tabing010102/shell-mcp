"""Command parsing and blacklist/whitelist validation."""

from __future__ import annotations

import os
import shlex


_SHELL_WRAPPERS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_ENV_OPTIONS_WITH_VALUE = frozenset({"-u", "--unset"})


def extract_command_names(command_string: str) -> list[str]:
    """Extract all command names from a shell command string.

    Handles pipes, &&, ||, ;, $() subshells, backtick subshells,
    and bash/sh -c "..." patterns.
    """
    return [os.path.basename(token) for token in _extract_command_tokens(command_string)]


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

    tokens = _extract_command_tokens(command_string)
    if not tokens:
        return (True, "")

    if whitelist_set:
        for token in tokens:
            base = os.path.basename(token)
            if base not in whitelist_set and token not in whitelist_set:
                return (False, f"Command '{base}' is not in the whitelist")
        return (True, "")

    for token in tokens:
        base = os.path.basename(token)
        if base in blacklist_set or token in blacklist_set:
            return (False, f"Command '{base}' is blacklisted")

    return (True, "")


def _extract_command_tokens(command_string: str) -> list[str]:
    """Extract command tokens, preserving full paths when present."""
    if not command_string or not command_string.strip():
        return []

    commands: list[str] = []
    for segment in _split_by_operators(command_string):
        segment = segment.strip()
        if not segment:
            continue
        commands.extend(_extract_segment_commands(segment))

    return commands


def _extract_segment_commands(segment: str) -> list[str]:
    """Extract commands from a single top-level command segment."""
    tokens = _tokenize(segment)
    command_index = _find_command_index(tokens)
    inline_source = segment

    if command_index is None:
        return _extract_inline_command_tokens(inline_source)

    command_token = tokens[command_index]
    commands = [command_token]

    wrapper_inner = _extract_wrapper_inner_command(tokens, command_index)
    if wrapper_inner:
        inline_source = _remove_first_occurrence(inline_source, wrapper_inner)

    commands.extend(_extract_inline_command_tokens(inline_source))

    if wrapper_inner:
        commands.extend(_extract_command_tokens(wrapper_inner))

    return commands


def _split_by_operators(command_string: str) -> list[str]:
    """Split a command string by top-level shell operators."""
    segments: list[str] = []
    current: list[str] = []
    in_single_quote = False
    in_double_quote = False
    in_backticks = False
    dollar_paren_depth = 0
    i = 0
    chars = command_string

    while i < len(chars):
        c = chars[i]

        if c == "\\" and not in_single_quote and i + 1 < len(chars):
            current.append(c)
            current.append(chars[i + 1])
            i += 2
        elif not in_backticks and c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            current.append(c)
            i += 1
        elif not in_backticks and c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            current.append(c)
            i += 1
        elif not in_single_quote and c == "`":
            in_backticks = not in_backticks
            current.append(c)
            i += 1
        elif (
            not in_single_quote
            and not in_backticks
            and c == "$"
            and i + 1 < len(chars)
            and chars[i + 1] == "("
        ):
            dollar_paren_depth += 1
            current.append(c)
            current.append(chars[i + 1])
            i += 2
        elif (
            not in_single_quote
            and not in_backticks
            and dollar_paren_depth > 0
            and c == ")"
        ):
            dollar_paren_depth -= 1
            current.append(c)
            i += 1
        elif not in_single_quote and not in_double_quote:
            two = chars[i : i + 2]
            if not in_backticks and dollar_paren_depth == 0 and two in ("&&", "||"):
                segments.append("".join(current))
                current = []
                i += 2
            elif not in_backticks and dollar_paren_depth == 0 and c in ("|", ";", "\n"):
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


def _extract_inline_command_tokens(text: str) -> list[str]:
    """Extract commands from $() and backtick substitutions."""
    commands: list[str] = []
    in_single_quote = False
    in_double_quote = False
    i = 0

    while i < len(text):
        c = text[i]

        if c == "\\" and not in_single_quote and i + 1 < len(text):
            i += 2
        elif c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            i += 1
        elif c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            i += 1
        elif not in_single_quote and c == "`":
            inner, i = _consume_backticks(text, i + 1)
            commands.extend(_extract_command_tokens(inner))
        elif (
            not in_single_quote
            and c == "$"
            and i + 1 < len(text)
            and text[i + 1] == "("
        ):
            inner, i = _consume_dollar_paren(text, i + 2)
            commands.extend(_extract_command_tokens(inner))
        else:
            i += 1

    return commands


def _consume_backticks(text: str, start_index: int) -> tuple[str, int]:
    """Consume a backtick command substitution."""
    i = start_index
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            i += 2
        elif text[i] == "`":
            return (text[start_index:i], i + 1)
        else:
            i += 1

    return (text[start_index:], len(text))


def _consume_dollar_paren(text: str, start_index: int) -> tuple[str, int]:
    """Consume a $(...) command substitution, including nested substitutions."""
    depth = 1
    in_single_quote = False
    in_double_quote = False
    in_backticks = False
    i = start_index

    while i < len(text):
        c = text[i]

        if c == "\\" and not in_single_quote and i + 1 < len(text):
            i += 2
        elif not in_backticks and c == "'" and not in_double_quote:
            in_single_quote = not in_single_quote
            i += 1
        elif not in_backticks and c == '"' and not in_single_quote:
            in_double_quote = not in_double_quote
            i += 1
        elif not in_single_quote and c == "`":
            in_backticks = not in_backticks
            i += 1
        elif (
            not in_single_quote
            and not in_backticks
            and c == "$"
            and i + 1 < len(text)
            and text[i + 1] == "("
        ):
            depth += 1
            i += 2
        elif not in_single_quote and not in_backticks and c == ")":
            depth -= 1
            if depth == 0:
                return (text[start_index:i], i + 1)
            i += 1
        else:
            i += 1

    return (text[start_index:], len(text))


def _tokenize(segment: str) -> list[str]:
    """Tokenize a shell segment using shlex, with a safe fallback."""
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _find_command_index(tokens: list[str]) -> int | None:
    """Return the first executable token, skipping environment assignments."""
    for token in tokens:
        if _is_env_assignment(token):
            continue
        return tokens.index(token)

    return None


def _is_env_assignment(token: str) -> bool:
    """Return True when a token is a leading environment variable assignment."""
    if "=" not in token or token.startswith("="):
        return False

    key_part = token.split("=", 1)[0]
    return key_part.isidentifier()


def _extract_wrapper_inner_command(tokens: list[str], command_index: int) -> str | None:
    """Extract an inner command for wrappers such as env and bash -c."""
    command_token = tokens[command_index]
    base = os.path.basename(command_token)

    if base in _SHELL_WRAPPERS:
        return _extract_shell_c_inner_command(tokens, command_index)
    if base == "env":
        return _extract_env_inner_command(tokens, command_index)
    return None


def _extract_shell_c_inner_command(tokens: list[str], command_index: int) -> str | None:
    """Extract the command string passed to bash/sh/zsh -c."""
    for i in range(command_index + 1, len(tokens)):
        token = tokens[i]
        if token == "-c" and i + 1 < len(tokens):
            return tokens[i + 1]
        if token.startswith("-") and not token.startswith("--") and "c" in token[1:]:
            if i + 1 < len(tokens):
                return tokens[i + 1]
    return None


def _extract_env_inner_command(tokens: list[str], command_index: int) -> str | None:
    """Extract the command executed via env after assignments/options."""
    i = command_index + 1
    while i < len(tokens):
        token = tokens[i]

        if token == "--":
            i += 1
            break
        if token in _ENV_OPTIONS_WITH_VALUE:
            i += 2
            continue
        if token in ("-i", "--ignore-environment"):
            i += 1
            continue
        if token.startswith("--unset="):
            i += 1
            continue
        if _is_env_assignment(token):
            i += 1
            continue
        if token.startswith("-"):
            i += 1
            continue
        break

    if i >= len(tokens):
        return None

    return shlex.join(tokens[i:])


def _remove_first_occurrence(text: str, target: str) -> str:
    """Remove the first raw occurrence of target when it exists."""
    index = text.find(target)
    if index == -1:
        return text
    return text[:index] + text[index + len(target) :]
