#!/usr/bin/env python
"""Demonstration of BOTH async patterns in libtmux.

This example shows:
1. Pattern A: .acmd() methods (simple async on existing classes)
2. Pattern B: tmux_cmd_async (psycopg-style async-first)

Both patterns preserve 100% of the synchronous API.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Try importing from installed package, fallback to development mode
try:
    from libtmux.common import AsyncTmuxCmd
    from libtmux.common_async import tmux_cmd_async, get_version
    from libtmux.server import Server
except ImportError:
    # Development mode: add parent to path
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
    from libtmux.common import AsyncTmuxCmd
    from libtmux.common_async import tmux_cmd_async, get_version
    from libtmux.server import Server


async def demo_pattern_a_acmd_methods() -> None:
    """Pattern A: Use .acmd() methods on existing sync classes.

    This pattern is perfect for:
    - Migrating existing sync code to async gradually
    - Simple async command execution
    - When you need both sync and async in the same codebase
    """
    print("=" * 70)
    print("PATTERN A: .acmd() Methods (Early Asyncio Branch)")
    print("=" * 70)
    print()
    print("Use .acmd() on existing Server/Session/Window/Pane classes")
    print("Perfect for gradual migration from sync to async")
    print()

    # Create a server using the synchronous API (existing code)
    server = Server()

    # Use async command execution via .acmd()
    print("1. Creating new session asynchronously...")
    result = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_id = result.stdout[0]
    print(f"   Created session: {session_id}")
    print(f"   Result type: {type(result).__name__}")
    print(f"   Return code: {result.returncode}")

    # Get session details
    print("\n2. Getting session details...")
    result = await server.acmd("display-message", "-p", "-t", session_id, "-F#{session_name}")
    session_name = result.stdout[0] if result.stdout else "unknown"
    print(f"   Session name: {session_name}")

    # List windows
    print("\n3. Listing windows in session...")
    result = await server.acmd("list-windows", "-t", session_id, "-F#{window_index}:#{window_name}")
    print(f"   Found {len(result.stdout)} windows")
    for window in result.stdout:
        print(f"   - {window}")

    # Cleanup
    print("\n4. Cleaning up (killing session)...")
    await server.acmd("kill-session", "-t", session_id)
    print(f"   Session {session_id} killed")

    print("\n✓ Pattern A Benefits:")
    print("  - Works with existing Server/Session/Window/Pane classes")
    print("  - Minimal code changes (just add await)")
    print("  - 100% backward compatible")
    print("  - Great for gradual async migration")


async def demo_pattern_b_async_classes() -> None:
    """Pattern B: Use async-first classes and functions.

    This pattern is perfect for:
    - New async-only code
    - Maximum performance with concurrent operations
    - Following psycopg-style async-first architecture
    """
    print("\n" + "=" * 70)
    print("PATTERN B: Async-First Classes (Psycopg-Inspired)")
    print("=" * 70)
    print()
    print("Use tmux_cmd_async and async functions directly")
    print("Perfect for new async-only code and maximum performance")
    print()

    # Get version asynchronously
    print("1. Getting tmux version asynchronously...")
    version = await get_version()
    print(f"   tmux version: {version}")

    # Execute command with tmux_cmd_async
    print("\n2. Creating session with tmux_cmd_async...")
    cmd = await tmux_cmd_async("new-session", "-d", "-P", "-F#{session_id}")
    session_id = cmd.stdout[0]
    print(f"   Created session: {session_id}")
    print(f"   Result type: {type(cmd).__name__}")
    print(f"   Return code: {cmd.returncode}")

    # Concurrent operations - THIS IS WHERE ASYNC SHINES
    print("\n3. Running multiple operations concurrently...")
    print("   (This is much faster than sequential execution)")

    results = await asyncio.gather(
        tmux_cmd_async("list-sessions"),
        tmux_cmd_async("list-windows", "-t", session_id),
        tmux_cmd_async("list-panes", "-t", session_id),
        tmux_cmd_async("show-options", "-g"),
    )

    sessions, windows, panes, options = results
    print(f"   - Sessions: {len(sessions.stdout)}")
    print(f"   - Windows: {len(windows.stdout)}")
    print(f"   - Panes: {len(panes.stdout)}")
    print(f"   - Global options: {len(options.stdout)}")

    # Cleanup
    print("\n4. Cleaning up...")
    await tmux_cmd_async("kill-session", "-t", session_id)
    print(f"   Session {session_id} killed")

    print("\n✓ Pattern B Benefits:")
    print("  - Native async/await throughout")
    print("  - Excellent for concurrent operations (asyncio.gather)")
    print("  - Follows psycopg's proven architecture")
    print("  - Best performance for parallel tmux commands")


async def demo_both_patterns_together() -> None:
    """Show that both patterns can coexist in the same codebase."""
    print("\n" + "=" * 70)
    print("BOTH PATTERNS TOGETHER: Hybrid Approach")
    print("=" * 70)
    print()
    print("You can use BOTH patterns in the same application!")
    print()

    # Pattern A: Use .acmd() on Server
    server = Server()
    result_a = await server.acmd("new-session", "-d", "-P", "-F#{session_id}")
    session_a = result_a.stdout[0]
    print(f"Pattern A created session: {session_a}")

    # Pattern B: Use tmux_cmd_async directly
    result_b = await tmux_cmd_async("new-session", "-d", "-P", "-F#{session_id}")
    session_b = result_b.stdout[0]
    print(f"Pattern B created session: {session_b}")

    # Both return compatible result types
    print(f"\nPattern A result type: {type(result_a).__name__}")
    print(f"Pattern B result type: {type(result_b).__name__}")

    # Use asyncio.gather to run operations from both patterns concurrently
    print("\nRunning operations from BOTH patterns concurrently...")
    cleanup_results = await asyncio.gather(
        server.acmd("kill-session", "-t", session_a),  # Pattern A
        tmux_cmd_async("kill-session", "-t", session_b),  # Pattern B
    )
    print(f"Cleaned up {len(cleanup_results)} sessions")

    print("\n✓ Hybrid Benefits:")
    print("  - Choose the right pattern for each use case")
    print("  - Mix and match as needed")
    print("  - Both patterns are fully compatible")


async def demo_performance_comparison() -> None:
    """Compare sequential vs parallel execution."""
    print("\n" + "=" * 70)
    print("PERFORMANCE: Sequential vs Parallel")
    print("=" * 70)
    print()

    import time

    # Create test sessions
    print("Setting up test sessions...")
    sessions = []
    for i in range(4):
        cmd = await tmux_cmd_async("new-session", "-d", "-P", "-F#{session_id}")
        sessions.append(cmd.stdout[0])
    print(f"Created {len(sessions)} test sessions")

    # Sequential execution
    print("\n1. Sequential execution (one after another)...")
    start = time.time()
    for session_id in sessions:
        await tmux_cmd_async("list-windows", "-t", session_id)
    sequential_time = time.time() - start
    print(f"   Time: {sequential_time:.4f} seconds")

    # Parallel execution
    print("\n2. Parallel execution (all at once)...")
    start = time.time()
    await asyncio.gather(*[
        tmux_cmd_async("list-windows", "-t", session_id)
        for session_id in sessions
    ])
    parallel_time = time.time() - start
    print(f"   Time: {parallel_time:.4f} seconds")

    # Show speedup
    speedup = sequential_time / parallel_time if parallel_time > 0 else 0
    print(f"\n✓ Speedup: {speedup:.2f}x faster with async!")

    # Cleanup
    print("\nCleaning up test sessions...")
    await asyncio.gather(*[
        tmux_cmd_async("kill-session", "-t", session_id)
        for session_id in sessions
    ])


async def main() -> None:
    """Run all demonstrations."""
    print()
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  libtmux Hybrid Async Architecture Demo".center(68) + "║")
    print("║" + "  Two Async Patterns, 100% Backward Compatible".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "=" * 68 + "╝")

    try:
        # Demo both patterns
        await demo_pattern_a_acmd_methods()
        await demo_pattern_b_async_classes()
        await demo_both_patterns_together()
        await demo_performance_comparison()

        # Summary
        print("\n" + "=" * 70)
        print("SUMMARY: When to Use Each Pattern")
        print("=" * 70)
        print()
        print("Use Pattern A (.acmd methods) when:")
        print("  • You have existing synchronous libtmux code")
        print("  • You want to gradually migrate to async")
        print("  • You need both sync and async in the same codebase")
        print("  • You're working with Server/Session/Window/Pane objects")
        print()
        print("Use Pattern B (async-first) when:")
        print("  • You're writing new async-only code")
        print("  • You need maximum performance with concurrent operations")
        print("  • You want to follow psycopg-style async architecture")
        print("  • You're primarily using raw tmux commands")
        print()
        print("The Good News:")
        print("  ✓ Both patterns preserve 100% of the synchronous API")
        print("  ✓ Both patterns can be used together in the same code")
        print("  ✓ Both patterns are fully type-safe with mypy")
        print("  ✓ Choose the pattern that fits your use case best!")

    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
