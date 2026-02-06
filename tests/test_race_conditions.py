"""Race condition and state conflict tests for libtmux.

Documents every discoverable failure mode where libtmux's Python-side object
state diverges from the tmux server's actual state. Organized into five
categories:

1. **Create-query races** (#1-6): Two-step "create -> query" fails when state
   changes between the tmux command and the follow-up list query.
2. **Object staleness after external mutation** (#7-10): Cached Python objects
   become invalid after the underlying tmux object is killed externally.
3. **DX frustrations** (#11-15): Natural API usage patterns that produce
   confusing or silent failures.
4. **Query/filter edge cases** (#16-17): QueryList and fetch_obj misbehavior
   on typos and renames.
5. **ID recycling after server restart** (#18): Stale refs match wrong objects
   when tmux recycles numeric IDs.

All xfail tests are ``strict=True`` — they document known issues and will flip
to XPASS when the underlying code is fixed, signaling that the xfail marker
can be removed.

Parallel-safe: each test uses the server/session fixture (unique socket)
and function-scoped monkeypatch where needed.
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


# --- Category 2: Object staleness after external mutation (#7-10) ---
#
# After creation, libtmux objects cache their data as dataclass attributes.
# External changes (CLI user, other scripts, tmux hooks) invalidate that cached
# state. Methods on stale objects produce wrong results or cryptic exceptions.


@pytest.mark.xfail(
    reason="active_window on killed session raises LibTmuxException with raw "
    "tmux stderr (or NoActiveWindow) instead of a clear 'session dead' error. "
    "session.py:288-296 → self.windows → fetch_objs('list-windows') fails.",
    strict=True,
)
def test_session_killed_active_window(server: Server) -> None:
    """Accessing active_window on an externally killed session gives unclear error.

    The session object still exists in Python, but the underlying tmux session
    is gone. Accessing ``active_window`` should raise a clear, typed error
    indicating the session no longer exists — not ``LibTmuxException`` with raw
    tmux stderr or ``NoActiveWindow`` (which implies the session is alive but
    has no active window).
    """
    session = server.new_session(session_name="doomed")
    session_id = session.session_id
    assert session_id is not None

    # Kill via server.cmd to simulate external mutation
    server.cmd("kill-session", "-t", session_id)

    # This should raise a clear "session dead" error, not raw stderr
    _window = session.active_window


def test_session_killed_refresh(server: Server) -> None:
    """Refreshing a killed session correctly raises an exception.

    This is a **positive** test -- the current behavior is correct. ``refresh()``
    calls ``fetch_obj(obj_key='session_id', ...)`` which raises either
    ``TmuxObjectDoesNotExist`` (when server is alive but session is gone) or
    ``LibTmuxException`` (when the server died with the last session).

    We keep a second session alive so the server survives the kill, ensuring
    ``TmuxObjectDoesNotExist`` is raised.
    """
    server.new_session(session_name="keeper")
    session = server.new_session(session_name="doomed")
    session_id = session.session_id
    assert session_id is not None

    server.cmd("kill-session", "-t", session_id)

    with pytest.raises(exc.TmuxObjectDoesNotExist):
        session.refresh()


@pytest.mark.xfail(
    reason="Accessing panes on killed window raises LibTmuxException with raw "
    "tmux stderr instead of a typed 'window dead' error. "
    "window.py:179 → fetch_objs('list-panes', ['-t', window_id]) fails.",
    strict=True,
)
def test_window_killed_panes(session: Session) -> None:
    """Accessing panes on an externally killed window gives unclear error.

    After a window is killed externally, accessing ``window.panes`` triggers
    ``fetch_objs`` with ``-t <dead_window_id>``, which causes tmux to emit
    a stderr error. This propagates as a raw ``LibTmuxException`` rather than
    a clear, typed error about the window being dead.
    """
    window = session.new_window(window_name="doomed")
    window_id = window.window_id
    assert window_id is not None

    session.cmd("kill-window", "-t", window_id)

    # This should raise a clear "window dead" error, not raw stderr
    _panes = window.panes


@pytest.mark.xfail(
    reason="send_keys to dead pane silently succeeds — server.cmd() returns "
    "result with stderr but send_keys ignores it. pane.py:469-471",
    strict=True,
)
def test_pane_killed_send_keys(session: Session) -> None:
    """Sending keys to a killed pane silently fails instead of raising.

    ``send_keys`` calls ``self.cmd('send-keys', ...)`` which delegates to
    ``server.cmd()``. The tmux command returns stderr about the invalid target,
    but ``send_keys`` ignores the return value entirely — the error is
    swallowed and the caller has no idea the operation failed.
    """
    pane = session.active_pane
    assert pane is not None
    new_pane = pane.split()

    session.cmd("kill-pane", "-t", new_pane.pane_id)

    with pytest.raises(exc.LibTmuxException):
        new_pane.send_keys("echo hello")


# --- Category 3: DX frustrations (#11-15) ---
#
# Scenarios a shell-user-turned-programmer would naturally attempt, where
# libtmux's behavior is surprising or silently wrong.


@pytest.mark.xfail(
    reason="server.sessions silently returns [] on dead server "
    "due to bare except:pass at server.py:615-616. "
    "Should raise or clearly indicate the server is dead.",
    strict=True,
)
def test_server_sessions_dead_server(server: Server) -> None:
    """Dead server's sessions property should raise, not return empty list.

    The ``sessions`` property has a bare ``except: pass`` (server.py:615) that
    swallows all exceptions from ``fetch_objs``. When the server is dead, this
    silently returns ``[]`` instead of raising an error — making it impossible
    for the caller to distinguish "server has no sessions" from "server is dead".
    """
    server.new_session(session_name="exists")
    server.kill()

    with pytest.raises(exc.LibTmuxException):
        _sessions = server.sessions


def test_session_context_manager_rename(server: Server) -> None:
    """Session context manager correctly kills renamed session on exit.

    ``Session.__exit__`` at session.py:130 checks
    ``self.server.has_session(self.session_name)``. This works because
    ``rename_session()`` calls ``self.refresh()`` which updates the cached
    ``session_name`` in the Python object. So ``has_session('renamed')``
    returns True and ``kill()`` is called correctly.

    This is a **positive** test documenting that the rename + context manager
    interaction works as expected.
    """
    # Keep a session alive so the server survives after context exit
    server.new_session(session_name="keeper")

    with server.new_session(session_name="original") as session:
        session.rename_session("renamed")

    # After exiting context, session should have been killed
    assert not server.has_session("renamed"), (
        "Session leaked: __exit__ did not kill renamed session"
    )


@pytest.mark.xfail(
    raises=exc.LibTmuxException,
    reason="server.windows has no try/except guard unlike server.sessions. "
    "server.py:620-637 lets LibTmuxException propagate from fetch_objs.",
    strict=True,
)
def test_server_windows_dead_server(server: Server) -> None:
    """Accessing windows on dead server raises raw LibTmuxException.

    Unlike ``server.sessions`` (which has a bare except:pass), ``server.windows``
    has no exception handling at all. When the server is dead, the
    ``LibTmuxException`` from ``fetch_objs`` propagates directly — the
    inconsistency between the two properties is the bug.
    """
    server.new_session(session_name="exists")
    server.kill()
    _windows = server.windows


@pytest.mark.xfail(
    raises=exc.LibTmuxException,
    reason="server.panes has no try/except guard unlike server.sessions. "
    "server.py:639-656 lets LibTmuxException propagate from fetch_objs.",
    strict=True,
)
def test_server_panes_dead_server(server: Server) -> None:
    """Accessing panes on dead server raises raw LibTmuxException.

    Same inconsistency as ``server.windows`` -- no try/except guard while
    ``server.sessions`` silently swallows errors.
    """
    server.new_session(session_name="exists")
    server.kill()
    _panes = server.panes


# --- Category 4: Query/filter edge cases (#16-17) ---
#
# QueryList and fetch_obj edge cases where typos or renames cause silent
# wrong results instead of clear errors.


@pytest.mark.xfail(
    reason="QueryList filter with typo field silently returns empty list "
    "instead of raising. keygetter() at query_list.py:108 catches all "
    "exceptions and returns None, causing the filter to find no matches.",
    strict=True,
)
def test_filter_typo_silent_empty(server: Server) -> None:
    """Typo in filter field name silently returns empty result.

    ``keygetter()`` in query_list.py:99-113 uses a bare ``except Exception``
    that catches ``KeyError``/``AttributeError`` for unknown fields and returns
    ``None``. This means a typo like ``sessionn_name`` (double 'n') silently
    produces zero matches instead of raising an ``AttributeError``.
    """
    server.new_session(session_name="findme")
    result = server.sessions.filter(sessionn_name="findme")
    assert len(result) > 0, "Typo in filter field silently returned empty list"


@pytest.mark.xfail(
    raises=exc.TmuxObjectDoesNotExist,
    reason="fetch_obj by session_name fails after rename — linear scan in "
    "neo.py:237-239 can't find old name.",
    strict=True,
)
def test_fetch_obj_renamed_session(server: Server) -> None:
    """fetch_obj by session_name fails after session rename.

    When a session is renamed between creation and a subsequent ``fetch_obj``
    call that uses ``session_name`` as the key, the linear scan at
    neo.py:237-239 fails because the old name no longer exists.

    This documents that ``fetch_obj`` by mutable keys (like ``session_name``)
    is fragile — callers should prefer immutable keys (``session_id``).
    """
    from libtmux.neo import fetch_obj

    session = server.new_session(session_name="before_rename")
    session.rename_session("after_rename")

    # This raises TmuxObjectDoesNotExist because "before_rename" is gone
    fetch_obj(
        server=server,
        obj_key="session_name",
        obj_id="before_rename",
        list_cmd="list-sessions",
    )


# --- Category 5: ID recycling after server restart (#18) ---
#
# After a server restart, tmux recycles numeric IDs ($0, @0, %0). Stale
# Python refs holding old IDs silently match the wrong new objects.


@pytest.mark.xfail(
    reason="After server restart, stale session ref with recycled $0 ID "
    "silently returns data from a different session. neo.py:237-239 "
    "matches by session_id=$0 which now belongs to the imposter session.",
    strict=True,
)
def test_stale_ref_after_server_restart(server: Server) -> None:
    """Stale object ref silently returns wrong data after server restart.

    When the server is killed and restarted, tmux recycles numeric IDs.
    A stale Python ``Session`` object holding ``session_id='$0'`` will match
    the new session that also got ``$0``, silently returning data from a
    completely different session. There is no staleness detection.
    """
    session = server.new_session(session_name="original")
    original_id = session.session_id
    assert original_id is not None

    server.kill()

    # Start a new session on the same server socket — gets recycled ID $0
    server.cmd("new-session", "-d", "-s", "imposter")

    # Refresh the stale ref — should fail but $0 matches the imposter
    session.refresh()

    # The data now belongs to "imposter", not "original"
    assert session.session_name == "original", (
        f"Stale ref returned '{session.session_name}' instead of 'original' — "
        f"ID {original_id} was recycled to a different session"
    )
