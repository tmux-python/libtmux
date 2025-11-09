#!/usr/bin/env python
"""Demonstration of async tmux command execution.

This example shows how the async-first architecture works with libtmux.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
from pathlib import Path

# Try importing from installed package, fallback to development mode
try:
    from libtmux.common_async import get_version, tmux_cmd_async
except ImportError:
    # Development mode: add parent to path
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from libtmux.common_async import get_version, tmux_cmd_async


async def demo_basic_command() -> None:
    """Demo: Execute a basic tmux command asynchronously."""
    print("=" * 60)
    print("Demo 1: Basic Async Command Execution")
    print("=" * 60)

    # Get tmux version asynchronously
    print("\nGetting tmux version...")
    version = await get_version()
    print(f"tmux version: {version}")

    # List all tmux sessions
    print("\nListing all tmux sessions...")
    proc = await tmux_cmd_async("list-sessions")

    if proc.stderr:
        print(f"No sessions found (or error): {proc.stderr}")
    else:
        print(f"Found {len(proc.stdout)} session(s):")
        for line in proc.stdout:
            print(f"  - {line}")


async def demo_concurrent_commands() -> None:
    """Demo: Execute multiple tmux commands concurrently."""
    print("\n" + "=" * 60)
    print("Demo 2: Concurrent Command Execution")
    print("=" * 60)

    print("\nExecuting multiple commands in parallel...")

    # Execute multiple tmux commands concurrently
    results = await asyncio.gather(
        tmux_cmd_async("list-sessions"),
        tmux_cmd_async("list-windows"),
        tmux_cmd_async("list-panes"),
        tmux_cmd_async("show-options", "-g"),
        return_exceptions=True,
    )

    commands = ["list-sessions", "list-windows", "list-panes", "show-options -g"]
    for cmd, result in zip(commands, results, strict=True):
        if isinstance(result, Exception):
            print(f"\n[{cmd}] Error: {result}")
        else:
            print(f"\n[{cmd}] Returned {len(result.stdout)} lines")
            if result.stderr:
                print(f"  stderr: {result.stderr}")


async def demo_comparison_with_sync() -> None:
    """Demo: Compare async vs sync execution time."""
    print("\n" + "=" * 60)
    print("Demo 3: Performance Comparison")
    print("=" * 60)

    from libtmux.common import tmux_cmd

    # Commands to run
    commands = ["list-sessions", "list-windows", "list-panes", "show-options -g"]

    # Async execution
    print("\nAsync execution (parallel)...")
    start = time.time()
    await asyncio.gather(
        *[tmux_cmd_async(*cmd.split()) for cmd in commands],
        return_exceptions=True,
    )
    async_time = time.time() - start
    print(f"  Time: {async_time:.4f} seconds")

    # Sync execution
    print("\nSync execution (sequential)...")
    start = time.time()
    for cmd in commands:
        with contextlib.suppress(Exception):
            tmux_cmd(*cmd.split())
    sync_time = time.time() - start
    print(f"  Time: {sync_time:.4f} seconds")

    print(f"\nSpeedup: {sync_time / async_time:.2f}x")


async def demo_error_handling() -> None:
    """Demo: Error handling in async tmux commands."""
    print("\n" + "=" * 60)
    print("Demo 4: Error Handling")
    print("=" * 60)

    print("\nExecuting invalid command...")
    try:
        proc = await tmux_cmd_async("invalid-command")
        if proc.stderr:
            print(f"Expected error: {proc.stderr[0]}")
    except Exception as e:
        print(f"Exception caught: {e}")

    print("\nExecuting command for non-existent session...")
    try:
        proc = await tmux_cmd_async("has-session", "-t", "non_existent_session_12345")
        if proc.stderr:
            print(f"Expected error: {proc.stderr[0]}")
        print(f"Return code: {proc.returncode}")
    except Exception as e:
        print(f"Exception caught: {e}")


async def main() -> None:
    """Run all demonstrations."""
    print("\n" + "=" * 60)
    print("libtmux Async Architecture Demo")
    print("Demonstrating psycopg-inspired async-first design")
    print("=" * 60)

    try:
        await demo_basic_command()
        await demo_concurrent_commands()
        await demo_comparison_with_sync()
        await demo_error_handling()

        print("\n" + "=" * 60)
        print("Demo Complete!")
        print("=" * 60)
        print("\nKey Takeaways:")
        print("  ✓ Async commands use asyncio.create_subprocess_exec()")
        print("  ✓ Multiple commands can run concurrently with asyncio.gather()")
        print("  ✓ Same API as sync version, just with await")
        print("  ✓ Error handling works identically")
        print("  ✓ Significant performance improvement for parallel operations")

    except Exception as e:
        print(f"\nDemo failed with error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
