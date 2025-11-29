"""Async tests for libtmux.

This directory contains asynchronous tests for libtmux's async API. Tests are
organized by object type to mirror the sync test structure:

- test_server.py: Server.acmd() and concurrent server operations
- test_session.py: Session.acmd() and concurrent session operations
- test_window.py: Window.acmd() and concurrent window operations
- test_pane.py: Pane.acmd() and concurrent pane operations
- test_integration.py: Complex multi-object async workflows

All tests use isolated test servers via the `server` fixture with unique socket
names (libtmux_test{8_random_chars}) that never affect developer sessions.

Key patterns demonstrated:
- Concurrent operations (parallel session/window/pane creation)
- Real-world automation (batch operations, multi-pane setup)
- Error handling (timeouts, command failures, race conditions)
- Integration workflows (complex multi-object scenarios)
"""

from __future__ import annotations
