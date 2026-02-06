"""Race condition tests for object creation methods (#624).

Each test deterministically reproduces a failure mode where the two-step
"create -> query" pattern in new_session(), new_window(), and split() fails.

All tests are strict xfail -- they document known vulnerabilities and will
flip to XPASS when the creation methods are changed to construct objects
directly from -P output.

Parallel-safe: each test uses the server/session fixture (unique socket)
and function-scoped monkeypatch.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux.server import Server

if t.TYPE_CHECKING:
    from libtmux.neo import ListCmd, ListExtraArgs
    from libtmux.session import Session


# --- Failure Mode A: Server crash between create and query ---


@pytest.mark.xfail(
    raises=exc.TmuxObjectDoesNotExist,
    reason="new_session() re-queries via list-sessions after new-session returns. "
    "Server crash between steps loses the session. "
    "See https://github.com/tmux-python/libtmux/issues/624",
    strict=True,
)
def test_new_session_server_crash(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server crash between new-session and list-sessions (#624)."""
    from libtmux import neo

    original_fetch_objs = neo.fetch_objs
    server_crashed = False

    def fetch_objs_with_crash(
        server: Server,
        list_cmd: ListCmd,
        list_extra_args: ListExtraArgs = None,
    ) -> list[dict[str, t.Any]]:
        nonlocal server_crashed
        if list_cmd == "list-sessions" and not server_crashed:
            server_crashed = True
            server.cmd("kill-server")
            server.cmd("new-session", "-d", "-s", "_replacement")
        return original_fetch_objs(
            server=server,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )

    # Bumper session ensures race_test gets $1+, replacement server gets $0
    server.cmd("new-session", "-d", "-s", "_bumper")
    monkeypatch.setattr(neo, "fetch_objs", fetch_objs_with_crash)
    server.new_session(session_name="race_test")


@pytest.mark.xfail(
    raises=exc.TmuxObjectDoesNotExist,
    reason="new_window() re-queries via list-windows after new-window returns. "
    "Server crash between steps loses the window.",
    strict=True,
)
def test_new_window_server_crash(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server crash between new-window and list-windows."""
    from libtmux import neo

    original_fetch_objs = neo.fetch_objs
    server_crashed = False

    def fetch_objs_with_crash(
        server: Server,
        list_cmd: ListCmd,
        list_extra_args: ListExtraArgs = None,
    ) -> list[dict[str, t.Any]]:
        nonlocal server_crashed
        if list_cmd == "list-windows" and not server_crashed:
            server_crashed = True
            server.cmd("kill-server")
            server.cmd("new-session", "-d", "-s", "_replacement")
        return original_fetch_objs(
            server=server,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )

    monkeypatch.setattr(neo, "fetch_objs", fetch_objs_with_crash)
    session.new_window(window_name="race_test")


@pytest.mark.xfail(
    raises=exc.TmuxObjectDoesNotExist,
    reason="split() re-queries via list-panes after split-window returns. "
    "Server crash between steps loses the pane.",
    strict=True,
)
def test_split_server_crash(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Server crash between split-window and list-panes."""
    from libtmux import neo

    original_fetch_objs = neo.fetch_objs
    server_crashed = False

    def fetch_objs_with_crash(
        server: Server,
        list_cmd: ListCmd,
        list_extra_args: ListExtraArgs = None,
    ) -> list[dict[str, t.Any]]:
        nonlocal server_crashed
        if list_cmd == "list-panes" and not server_crashed:
            server_crashed = True
            server.cmd("kill-server")
            server.cmd("new-session", "-d", "-s", "_replacement")
        return original_fetch_objs(
            server=server,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )

    monkeypatch.setattr(neo, "fetch_objs", fetch_objs_with_crash)
    pane = session.active_pane
    assert pane is not None
    pane.split()


# --- Failure Mode B: Stale empty query response ---


@pytest.mark.xfail(
    raises=exc.TmuxObjectDoesNotExist,
    reason="new_session() re-queries via list-sessions. "
    "Stale empty response causes TmuxObjectDoesNotExist.",
    strict=True,
)
def test_new_session_stale_list(
    server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty list-sessions after new-session (#624)."""
    from libtmux import neo

    original_fetch_objs = neo.fetch_objs
    intercepted = False

    def fetch_objs_stale(
        server: Server,
        list_cmd: ListCmd,
        list_extra_args: ListExtraArgs = None,
    ) -> list[dict[str, t.Any]]:
        nonlocal intercepted
        if list_cmd == "list-sessions" and not intercepted:
            intercepted = True
            return []
        return original_fetch_objs(
            server=server,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )

    monkeypatch.setattr(neo, "fetch_objs", fetch_objs_stale)
    server.new_session(session_name="race_test")


@pytest.mark.xfail(
    raises=exc.TmuxObjectDoesNotExist,
    reason="new_window() re-queries via list-windows. "
    "Stale empty response causes TmuxObjectDoesNotExist.",
    strict=True,
)
def test_new_window_stale_list(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty list-windows after new-window."""
    from libtmux import neo

    original_fetch_objs = neo.fetch_objs
    intercepted = False

    def fetch_objs_stale(
        server: Server,
        list_cmd: ListCmd,
        list_extra_args: ListExtraArgs = None,
    ) -> list[dict[str, t.Any]]:
        nonlocal intercepted
        if list_cmd == "list-windows" and not intercepted:
            intercepted = True
            return []
        return original_fetch_objs(
            server=server,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )

    monkeypatch.setattr(neo, "fetch_objs", fetch_objs_stale)
    session.new_window(window_name="race_test")


@pytest.mark.xfail(
    raises=exc.TmuxObjectDoesNotExist,
    reason="split() re-queries via list-panes. "
    "Stale empty response causes TmuxObjectDoesNotExist.",
    strict=True,
)
def test_split_stale_list(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty list-panes after split-window."""
    from libtmux import neo

    original_fetch_objs = neo.fetch_objs
    intercepted = False

    def fetch_objs_stale(
        server: Server,
        list_cmd: ListCmd,
        list_extra_args: ListExtraArgs = None,
    ) -> list[dict[str, t.Any]]:
        nonlocal intercepted
        if list_cmd == "list-panes" and not intercepted:
            intercepted = True
            return []
        return original_fetch_objs(
            server=server,
            list_cmd=list_cmd,
            list_extra_args=list_extra_args,
        )

    monkeypatch.setattr(neo, "fetch_objs", fetch_objs_stale)
    pane = session.active_pane
    assert pane is not None
    pane.split()
