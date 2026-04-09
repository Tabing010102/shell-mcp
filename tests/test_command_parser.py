"""Tests for command_parser module."""

import pytest

from shell_mcp.command_parser import extract_command_names, validate_command


class TestExtractCommandNames:
    def test_simple_command(self):
        assert extract_command_names("ls -la") == ["ls"]

    def test_newline_separated_commands(self):
        assert extract_command_names("echo ok\nrm -rf /tmp/x") == ["echo", "rm"]

    def test_pipe(self):
        assert extract_command_names("cat file | grep pattern") == ["cat", "grep"]

    def test_and_operator(self):
        assert extract_command_names("cd /tmp && ls") == ["cd", "ls"]

    def test_or_operator(self):
        assert extract_command_names("cmd1 || cmd2") == ["cmd1", "cmd2"]

    def test_semicolons(self):
        assert extract_command_names("echo foo; echo bar; whoami") == [
            "echo",
            "echo",
            "whoami",
        ]

    def test_mixed_operators(self):
        assert extract_command_names("a | b && c || d; e") == [
            "a",
            "b",
            "c",
            "d",
            "e",
        ]

    def test_quoted_operators_double(self):
        result = extract_command_names('echo "hello && world"')
        assert result == ["echo"]

    def test_quoted_operators_single(self):
        result = extract_command_names("echo 'a|b;c'")
        assert result == ["echo"]

    def test_env_var_prefix(self):
        result = extract_command_names("VAR=1 python script.py")
        assert result == ["python"]

    def test_multiple_env_var_prefix(self):
        result = extract_command_names("FOO=1 BAR=2 node app.js")
        assert result == ["node"]

    def test_env_wrapper_command(self):
        result = extract_command_names("env FOO=1 rm -rf /tmp/x")
        assert result == ["env", "rm"]

    def test_subshell_dollar_paren(self):
        result = extract_command_names("echo $(whoami)")
        assert "echo" in result
        assert "whoami" in result

    def test_nested_subshell_dollar_paren(self):
        result = extract_command_names("echo $(printf '%s' \"$(whoami)\")")
        assert result == ["echo", "printf", "whoami"]

    def test_backtick_subshell(self):
        result = extract_command_names("echo `date`")
        assert "echo" in result
        assert "date" in result

    def test_bash_c(self):
        result = extract_command_names('bash -c "rm -rf /tmp"')
        assert "bash" in result
        assert "rm" in result

    def test_sh_c_with_operators(self):
        result = extract_command_names('sh -c "ls && pwd"')
        assert "sh" in result
        assert "ls" in result
        assert "pwd" in result

    def test_empty_string(self):
        assert extract_command_names("") == []

    def test_whitespace_only(self):
        assert extract_command_names("   ") == []

    def test_full_path_command(self):
        result = extract_command_names("/usr/bin/ls -la")
        assert result == ["ls"]

    def test_pipe_chain(self):
        result = extract_command_names("ps aux | grep python | awk '{print $2}'")
        assert "ps" in result
        assert "grep" in result
        assert "awk" in result


class TestValidateCommand:
    def test_blacklist_blocks(self):
        allowed, reason = validate_command("rm -rf /", blacklist=["rm"], whitelist=[])
        assert not allowed
        assert "rm" in reason

    def test_blacklist_blocks_piped(self):
        allowed, reason = validate_command(
            "ls | rm foo", blacklist=["rm"], whitelist=[]
        )
        assert not allowed

    def test_blacklist_allows(self):
        allowed, reason = validate_command("ls -la", blacklist=["rm"], whitelist=[])
        assert allowed
        assert reason == ""

    def test_whitelist_allows(self):
        allowed, reason = validate_command(
            "ls", blacklist=[], whitelist=["ls", "cat"]
        )
        assert allowed

    def test_whitelist_blocks(self):
        allowed, reason = validate_command(
            "ls | rm foo", blacklist=[], whitelist=["ls"]
        )
        assert not allowed
        assert "rm" in reason

    def test_empty_lists_allow_all(self):
        allowed, reason = validate_command("anything", blacklist=[], whitelist=[])
        assert allowed
        assert reason == ""

    def test_blacklist_blocks_chained(self):
        allowed, _ = validate_command(
            "echo hello && rm -rf /", blacklist=["rm"], whitelist=[]
        )
        assert not allowed

    def test_blacklist_blocks_bash_c(self):
        allowed, _ = validate_command(
            'bash -c "rm -rf /"', blacklist=["rm"], whitelist=[]
        )
        assert not allowed

    def test_blacklist_blocks_newline_command(self):
        allowed, _ = validate_command(
            "echo ok\nrm -rf /tmp/x", blacklist=["rm"], whitelist=[]
        )
        assert not allowed

    def test_blacklist_blocks_env_wrapper_command(self):
        allowed, _ = validate_command(
            "env FOO=1 rm -rf /tmp/x", blacklist=["rm"], whitelist=[]
        )
        assert not allowed

    def test_blacklist_blocks_full_path_command(self):
        allowed, reason = validate_command(
            "/usr/bin/rm -rf /tmp/x", blacklist=["/usr/bin/rm"], whitelist=[]
        )
        assert not allowed
        assert "rm" in reason

    def test_whitelist_with_pipe(self):
        allowed, _ = validate_command(
            "cat file | grep pattern", blacklist=[], whitelist=["cat", "grep"]
        )
        assert allowed
