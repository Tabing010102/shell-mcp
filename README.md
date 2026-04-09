# shell-mcp

MCP server for shell command execution. Allows LLMs to run shell commands with security controls, background task management, and output handling.

## Features

- **Dual transport**: stdio (local) and streamable-http (remote)
- **Foreground/background execution**: LLM controls execution mode per command
- **Background task management**: query status, stop, list -- all state in memory
- **Security**: blacklist/whitelist with recursive parsing (pipes, `&&`, `||`, `;`, `$()`, backticks, `bash -c`)
- **Non-interactive**: `stdin=DEVNULL` + env vars prevent interactive prompts (git, apt, etc.)
- **Output control**: configurable max length with proportional truncation and truncation flag
- **Timeout**: per-command timeout, auto-kill on expiry
- **Keepalive**: periodic progress notifications for long-running commands over HTTP
- **YAML config**: file-based configuration with CLI override support

## Installation

Requires Python >= 3.11 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Usage

### stdio (local, e.g. Claude Desktop)

```bash
uv run shell-mcp
```

### streamable-http (remote)

```bash
uv run shell-mcp --transport streamable-http --port 8000
```

### With config file

```bash
cp config.yaml.example config.yaml
# Edit config.yaml as needed
uv run shell-mcp --config config.yaml
```

### CLI flags (override config file)

```bash
uv run shell-mcp \
  --transport stdio \
  --shell /bin/bash \
  --timeout 60 \
  --max-output-length 100000 \
  --blacklist "rm,mkfs,dd,format" \
  --whitelist ""
```

Configuration priority: **CLI args > YAML config file > defaults**.

### Claude Desktop integration

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "shell": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/shell-mcp", "shell-mcp"],
      "env": {}
    }
  }
}
```

## MCP Tools

### `execute_shell_command`

Execute a shell command in foreground or background.

| Parameter | Type | Default | Description |
|---|---|---|---|
| `command` | `str` | required | Shell command to execute |
| `background` | `bool` | `false` | Run in background, return task_id immediately |
| `timeout` | `float \| null` | config default (30s) | Timeout in seconds |
| `shell` | `str` | `""` (auto-detect) | Shell to use (e.g. `/bin/bash`) |
| `cwd` | `str \| null` | `null` | Working directory |

**Foreground result:**

```json
{
  "status": "success",
  "exit_code": 0,
  "stdout": "...",
  "stderr": "",
  "execution_time": 1.23,
  "truncated": false,
  "command": "ls -la"
}
```

Status values: `success`, `error`, `timeout`, `rejected` (blocked by blacklist/whitelist).

**Background result:**

```json
{
  "task_id": "a1b2c3d4e5f6",
  "status": "running",
  "message": "Command started in background"
}
```

### `get_task_status`

Query a background task by ID.

| Parameter | Type | Description |
|---|---|---|
| `task_id` | `str` | Task ID from `execute_shell_command` |

### `stop_background_task`

Stop a running background task.

| Parameter | Type | Description |
|---|---|---|
| `task_id` | `str` | Task ID to stop |

### `list_background_tasks`

List all background tasks (running and completed). No parameters.

## Configuration

See [`config.yaml.example`](config.yaml.example) for all options:

| Option | Default | Description |
|---|---|---|
| `shell` | `""` (auto-detect) | Shell executable. Auto-detect: `$SHELL` -> `/bin/sh` |
| `default_timeout` | `30.0` | Default command timeout in seconds |
| `max_output_length` | `50000` | Max total chars for stdout + stderr |
| `keepalive_interval` | `5.0` | Progress ping interval (seconds) for HTTP keepalive |
| `blacklist` | `[]` | Commands to block |
| `whitelist` | `[]` | If non-empty, ONLY these commands are allowed |
| `transport` | `"stdio"` | `"stdio"` or `"streamable-http"` |
| `host` | `"127.0.0.1"` | HTTP transport bind host |
| `port` | `8000` | HTTP transport bind port |
| `non_interactive_env` | see example | Env vars injected to prevent interactive prompts |

## Security

The command parser extracts **all** command names from a shell string, including:

- Piped commands: `cat file | grep pattern` -> `[cat, grep]`
- Chained commands: `cmd1 && cmd2 || cmd3; cmd4` -> `[cmd1, cmd2, cmd3, cmd4]`
- Subshells: `echo $(whoami)` -> `[echo, whoami]`
- Shell wrappers: `bash -c "rm -rf /"` -> `[bash, rm]`

Each extracted command is checked against the whitelist (if set) or blacklist.

Interactive prompts are prevented by:
- Redirecting `stdin` from `/dev/null`
- Setting `GIT_TERMINAL_PROMPT=0`
- Setting `CI=true`
- Setting `DEBIAN_FRONTEND=noninteractive`

## Development

```bash
# Run tests
uv run pytest -v

# Run specific test module
uv run pytest tests/test_command_parser.py -v
```

## License

MIT
