# AGENTS.md

Guidelines for AI agents working on this codebase.

## Project Overview

`shell-mcp` is a Python MCP (Model Context Protocol) server that exposes shell command execution as tools for LLMs. Built with `uv` and the `mcp` Python SDK (`FastMCP`).

## Architecture

```text
src/shell_mcp/
├── config.py          # ShellMCPConfig dataclass, YAML loading, resolve_shell()
├── command_parser.py  # extract_command_names(), validate_command()
├── executor.py        # CommandResult dataclass, execute_command()
├── task_manager.py    # BackgroundTask dataclass, TaskManager class
├── keepalive.py       # run_with_keepalive(), _keepalive_loop()
├── server.py          # FastMCP instance, 4 tool definitions, module-level globals
└── cli.py             # argparse entry point main(), config loading
```

**Dependency flow** (no circular imports):

```text
cli.py -> server.py -> config.py
                    -> command_parser.py
                    -> executor.py
                    -> task_manager.py -> executor.py
                    -> keepalive.py
```

`server.py` owns the MCP tool registrations, and `keepalive.py` imports the MCP `Context` type/helper used for HTTP keepalive. The remaining modules stay pure Python/asyncio.

## Key Patterns

### Module-level globals in server.py

`config` and `task_manager` are module-level globals set by `cli.py` before `mcp.run()`. Tools read from these at call time.

### Config priority

CLI args > YAML file > dataclass defaults. Handled by `load_config()` in `config.py`.

### Non-interactive execution

All subprocesses use `stdin=subprocess.DEVNULL` and inject env vars (`GIT_TERMINAL_PROMPT=0`, `CI=true`, `DEBIAN_FRONTEND=noninteractive`).

### Command security

`command_parser.py` uses a quote-aware state machine to split by shell operators. It recursively parses `$()`, backticks, `env ... cmd`, and `bash/sh -c "..."`. Both `extract_command_names()` and `validate_command()` are pure functions with no side effects.

### Background tasks

`TaskManager` wraps each background command in an `asyncio.Task`. The `cleanup()` method cancels all running tasks -- call it on shutdown or in test teardown.

### Output truncation

Proportional: stdout gets first claim, stderr gets remainder. Both capped to `max_output_length` total. A `truncated: bool` flag is set on the result.

## Development Commands

```bash
uv sync                          # Install dependencies
uv run pytest -v                 # Run all tests
uv run pytest tests/test_command_parser.py -v  # Run specific module
uv run shell-mcp                 # Run server (stdio)
uv run shell-mcp --transport streamable-http   # Run server (HTTP)
```

## Testing Conventions

- All async tests use `@pytest.mark.asyncio` with `asyncio_mode = "auto"`
- Test fixtures that create a `TaskManager` must call `await mgr.cleanup()` in teardown to prevent dangling asyncio tasks
- `test_server.py` uses an `autouse` async fixture that resets `server.config` and `server.task_manager` before each test
- Tests call tool functions directly (not via MCP client) -- the tool functions are regular async functions that return JSON strings

## Adding a New Tool

1. Define the async function in `server.py` with `@mcp.tool()` decorator
2. Access config via the module-level `config` global
3. Access task manager via the module-level `task_manager` global
4. Return a JSON string (consistent with existing tools)
5. Add tests in `tests/test_server.py`

## Adding a New Config Option

1. Add the field to `ShellMCPConfig` dataclass in `config.py`
2. Add the CLI flag in `cli.py` `_parse_args()` and `_build_cli_overrides()`
3. Add the option to `config.yaml.example`
4. `_apply_dict_to_config()` handles YAML loading automatically via field name matching

## Common Pitfalls

- **Hanging tests**: background tasks (`sleep 60`, etc.) must be cleaned up. Always use `await mgr.cleanup()` in test teardown.
- **Blacklist bypass**: the command parser must handle `bash -c`, subshells, and piped commands. Test new parsing edge cases in `test_command_parser.py`.
- **Stateful HTTP**: the server does NOT use `stateless_http=True` because background tasks require state across requests.
