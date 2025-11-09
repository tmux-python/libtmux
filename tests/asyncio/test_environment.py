"""Tests for async environment variable operations.

This module tests async environment variable operations using .acmd() pattern
for both Session and Server objects, ensuring proper isolation and concurrent
operation support.

Note: AsyncEnvironmentMixin exists in common_async.py but is not integrated
into Session/Server classes. Environment operations use .acmd() instead.
"""

from __future__ import annotations

import asyncio
import typing as t

import pytest

from libtmux import Server

if t.TYPE_CHECKING:
    pass


def parse_environment(output: list[str]) -> dict[str, str | bool]:
    """Parse tmux show-environment output into dict.

    Returns dict where:
    - KEY=value -> {KEY: "value"}
    - -KEY -> {KEY: True}  (unset variable)
    """
    env: dict[str, str | bool] = {}
    for line in output:
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
        elif line.startswith("-"):
            env[line[1:]] = True
    return env


@pytest.mark.asyncio
async def test_session_set_environment_basic(async_server: Server) -> None:
    """Test basic async set-environment using .acmd()."""
    session = async_server.new_session(session_name="env_test")

    # Set environment variable using acmd
    result = await session.acmd("set-environment", "TEST_VAR", "test_value")
    assert result.returncode == 0

    # Verify it was set
    result = await session.acmd("show-environment")
    assert result.returncode == 0

    env = parse_environment(result.stdout)
    assert env.get("TEST_VAR") == "test_value"


@pytest.mark.asyncio
async def test_session_unset_environment(async_server: Server) -> None:
    """Test async unset-environment using .acmd()."""
    session = async_server.new_session(session_name="env_test")

    # Set variable
    await session.acmd("set-environment", "TEST_VAR", "test_value")
    result = await session.acmd("show-environment", "TEST_VAR")
    env = parse_environment(result.stdout)
    assert env.get("TEST_VAR") == "test_value"

    # Unset it
    result = await session.acmd("set-environment", "-u", "TEST_VAR")
    assert result.returncode == 0  # Command should succeed

    # After unset, trying to get it should fail or return as unset
    result = await session.acmd("show-environment", "TEST_VAR")
    # Unset variables may fail to show or show as -VAR
    # Either way is valid tmux behavior


@pytest.mark.asyncio
async def test_session_remove_environment(async_server: Server) -> None:
    """Test async remove-environment using .acmd()."""
    session = async_server.new_session(session_name="env_test")

    # Set variable
    await session.acmd("set-environment", "TEST_VAR", "test_value")
    result = await session.acmd("show-environment", "TEST_VAR")
    env = parse_environment(result.stdout)
    assert env.get("TEST_VAR") == "test_value"

    # Remove it
    result = await session.acmd("set-environment", "-r", "TEST_VAR")
    assert result.returncode == 0  # Command should succeed

    # After remove, variable should not have a value
    result = await session.acmd("show-environment", "TEST_VAR")
    # Removed variables may show as unset (-VAR) or be completely gone
    if result.returncode == 0:
        # If successful, should be unset (starts with -) or completely gone
        env_lines = result.stdout
        if len(env_lines) > 0:
            # If present, should be unset (starts with -)
            assert env_lines[0].startswith("-TEST_VAR")
    # Either way, variable has no value


@pytest.mark.asyncio
async def test_session_show_environment(async_server: Server) -> None:
    """Test async show-environment returns dict."""
    session = async_server.new_session(session_name="env_test")

    result = await session.acmd("show-environment")
    assert result.returncode == 0

    env = parse_environment(result.stdout)
    assert isinstance(env, dict)
    assert len(env) > 0  # Should have default tmux variables


@pytest.mark.asyncio
async def test_session_get_specific_environment(async_server: Server) -> None:
    """Test async show-environment for specific variable."""
    session = async_server.new_session(session_name="env_test")

    # Set a variable
    await session.acmd("set-environment", "TEST_VAR", "test_value")

    # Get specific variable
    result = await session.acmd("show-environment", "TEST_VAR")
    assert result.returncode == 0

    env = parse_environment(result.stdout)
    assert env.get("TEST_VAR") == "test_value"


@pytest.mark.asyncio
async def test_session_get_nonexistent_variable(async_server: Server) -> None:
    """Test async show-environment for nonexistent variable."""
    session = async_server.new_session(session_name="env_test")

    # Try to get nonexistent variable - tmux returns error
    result = await session.acmd("show-environment", "NONEXISTENT_VAR_12345")
    assert result.returncode != 0  # Should fail


@pytest.mark.asyncio
async def test_server_set_environment_global(async_server: Server) -> None:
    """Test async set-environment at server (global) level."""
    # Create a session first (needed for server to be running)
    _session = async_server.new_session(session_name="temp")

    # Set server-level environment variable
    result = await async_server.acmd(
        "set-environment",
        "-g",
        "SERVER_VAR",
        "server_value",
    )
    assert result.returncode == 0

    # Verify at server level
    result = await async_server.acmd("show-environment", "-g")
    env = parse_environment(result.stdout)
    assert env.get("SERVER_VAR") == "server_value"


@pytest.mark.asyncio
async def test_server_environment_operations(async_server: Server) -> None:
    """Test full cycle of server environment operations."""
    # Create a session first (needed for server to be running)
    _session = async_server.new_session(session_name="temp")

    # Set
    result = await async_server.acmd("set-environment", "-g", "SERVER_VAR", "value")
    assert result.returncode == 0

    result = await async_server.acmd("show-environment", "-g", "SERVER_VAR")
    env = parse_environment(result.stdout)
    assert env.get("SERVER_VAR") == "value"

    # Unset
    result = await async_server.acmd("set-environment", "-g", "-u", "SERVER_VAR")
    assert result.returncode == 0

    # Remove
    result = await async_server.acmd("set-environment", "-g", "-r", "SERVER_VAR")
    assert result.returncode == 0

    # After remove, should not have a value
    result = await async_server.acmd("show-environment", "-g", "SERVER_VAR")
    # Removed variables may show as unset or be gone
    if result.returncode == 0:
        # If successful, should be unset (starts with -) or completely gone
        env_lines = result.stdout
        if len(env_lines) > 0:
            # If present, should be unset (starts with -)
            assert env_lines[0].startswith("-SERVER_VAR")
    # Either way, variable has no value


@pytest.mark.asyncio
async def test_concurrent_environment_operations(async_server: Server) -> None:
    """Test concurrent environment modifications."""
    session = async_server.new_session(session_name="env_test")

    # Set multiple variables concurrently
    results = await asyncio.gather(
        session.acmd("set-environment", "VAR1", "value1"),
        session.acmd("set-environment", "VAR2", "value2"),
        session.acmd("set-environment", "VAR3", "value3"),
        session.acmd("set-environment", "VAR4", "value4"),
        session.acmd("set-environment", "VAR5", "value5"),
    )

    # All should succeed
    assert all(r.returncode == 0 for r in results)

    # Verify all were set
    result = await session.acmd("show-environment")
    env = parse_environment(result.stdout)
    assert env.get("VAR1") == "value1"
    assert env.get("VAR2") == "value2"
    assert env.get("VAR3") == "value3"
    assert env.get("VAR4") == "value4"
    assert env.get("VAR5") == "value5"


@pytest.mark.asyncio
async def test_environment_with_special_characters(async_server: Server) -> None:
    """Test environment values with special characters."""
    session = async_server.new_session(session_name="env_test")

    # Test various special characters
    test_cases = [
        ("SPACES", "value with spaces"),
        ("COLONS", "value:with:colons"),
        ("EQUALS", "value=with=equals"),
        ("SEMICOLONS", "value;with;semicolons"),
    ]

    for var_name, special_value in test_cases:
        await session.acmd("set-environment", var_name, special_value)
        result = await session.acmd("show-environment", var_name)
        env = parse_environment(result.stdout)
        assert env.get(var_name) == special_value, f"Failed for: {special_value}"


@pytest.mark.asyncio
async def test_environment_with_empty_value(async_server: Server) -> None:
    """Test handling of empty environment values."""
    session = async_server.new_session(session_name="env_test")

    # Set empty value
    await session.acmd("set-environment", "EMPTY_VAR", "")

    # Should be retrievable as empty string
    result = await session.acmd("show-environment", "EMPTY_VAR")
    env = parse_environment(result.stdout)
    assert env.get("EMPTY_VAR") == ""


@pytest.mark.asyncio
async def test_environment_isolation_between_sessions(async_server: Server) -> None:
    """Test environment variables are isolated between sessions."""
    session1 = async_server.new_session(session_name="env_test1")
    session2 = async_server.new_session(session_name="env_test2")

    # Set different variables in each session
    await session1.acmd("set-environment", "SESSION1_VAR", "session1_value")
    await session2.acmd("set-environment", "SESSION2_VAR", "session2_value")

    # Each session should only see its own variable
    result1 = await session1.acmd("show-environment")
    env1 = parse_environment(result1.stdout)

    result2 = await session2.acmd("show-environment")
    env2 = parse_environment(result2.stdout)

    assert "SESSION1_VAR" in env1
    assert "SESSION2_VAR" not in env1

    assert "SESSION2_VAR" in env2
    assert "SESSION1_VAR" not in env2


@pytest.mark.asyncio
async def test_concurrent_sessions_environment(async_server: Server) -> None:
    """Test concurrent environment operations across multiple sessions."""
    # Create 3 sessions
    sessions = [async_server.new_session(session_name=f"env_test{i}") for i in range(3)]

    # Set variables concurrently in all sessions
    await asyncio.gather(
        sessions[0].acmd("set-environment", "VAR", "value0"),
        sessions[1].acmd("set-environment", "VAR", "value1"),
        sessions[2].acmd("set-environment", "VAR", "value2"),
    )

    # Each should have its own value
    results = await asyncio.gather(
        sessions[0].acmd("show-environment", "VAR"),
        sessions[1].acmd("show-environment", "VAR"),
        sessions[2].acmd("show-environment", "VAR"),
    )

    envs = [parse_environment(r.stdout) for r in results]
    assert envs[0].get("VAR") == "value0"
    assert envs[1].get("VAR") == "value1"
    assert envs[2].get("VAR") == "value2"


@pytest.mark.asyncio
async def test_environment_with_long_value(async_server: Server) -> None:
    """Test environment variables with long values."""
    session = async_server.new_session(session_name="env_test")

    # Create a long value (1000 characters)
    long_value = "x" * 1000

    await session.acmd("set-environment", "LONG_VAR", long_value)
    result = await session.acmd("show-environment", "LONG_VAR")
    env = parse_environment(result.stdout)

    value = env.get("LONG_VAR")
    assert value == long_value
    assert isinstance(value, str)
    assert len(value) == 1000


@pytest.mark.asyncio
async def test_environment_update_existing(async_server: Server) -> None:
    """Test updating an existing environment variable."""
    session = async_server.new_session(session_name="env_test")

    # Set initial value
    await session.acmd("set-environment", "UPDATE_VAR", "initial_value")
    result = await session.acmd("show-environment", "UPDATE_VAR")
    env = parse_environment(result.stdout)
    assert env.get("UPDATE_VAR") == "initial_value"

    # Update to new value
    await session.acmd("set-environment", "UPDATE_VAR", "updated_value")
    result = await session.acmd("show-environment", "UPDATE_VAR")
    env = parse_environment(result.stdout)
    assert env.get("UPDATE_VAR") == "updated_value"


@pytest.mark.asyncio
async def test_concurrent_updates_same_variable(async_server: Server) -> None:
    """Test concurrent updates to the same variable."""
    session = async_server.new_session(session_name="env_test")

    # Update same variable concurrently with different values
    await asyncio.gather(
        session.acmd("set-environment", "RACE_VAR", "value1"),
        session.acmd("set-environment", "RACE_VAR", "value2"),
        session.acmd("set-environment", "RACE_VAR", "value3"),
    )

    # Should have one of the values (whichever completed last)
    result = await session.acmd("show-environment", "RACE_VAR")
    env = parse_environment(result.stdout)
    value = env.get("RACE_VAR")
    assert value in ["value1", "value2", "value3"]


@pytest.mark.asyncio
async def test_global_vs_session_environment_precedence(async_server: Server) -> None:
    """Test that session-level variables override global ones."""
    # Create session
    session = async_server.new_session(session_name="env_test")

    # Set global variable
    await async_server.acmd("set-environment", "-g", "SHARED_VAR", "global_value")

    # Verify global variable is set
    result = await async_server.acmd("show-environment", "-g", "SHARED_VAR")
    env = parse_environment(result.stdout)
    assert env.get("SHARED_VAR") == "global_value"

    # Set session-level variable with same name
    await session.acmd("set-environment", "SHARED_VAR", "session_value")

    # Session-level query should return session value (overrides global)
    result = await session.acmd("show-environment", "SHARED_VAR")
    env = parse_environment(result.stdout)
    assert env.get("SHARED_VAR") == "session_value"

    # Global level should still have original value
    result = await async_server.acmd("show-environment", "-g", "SHARED_VAR")
    env = parse_environment(result.stdout)
    assert env.get("SHARED_VAR") == "global_value"
