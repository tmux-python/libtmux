"""How adopter code reads :meth:`QueryList.get` under ``mypy --strict``."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type

from libtmux import Pane, Server, Session
from libtmux._internal.query_list import QueryList


def get_raises_instead_of_returning_none(panes: QueryList[Pane]) -> None:
    """Without ``default``, ``get`` returns the object or raises."""
    pane = panes.get(pane_id="%1")
    assert_type(pane, Pane)
    assert_type(panes.get(lambda p: p.pane_id == "%1"), Pane)
    # Narrowing is not needed: this is the pane, not ``Pane | None``.
    pane.send_keys("echo ok")


def get_with_default_widens_to_the_default(panes: QueryList[Pane]) -> None:
    """With ``default``, the result is the object or the default."""
    assert_type(panes.get(pane_id="%1", default=None), Pane | None)
    assert_type(panes.get(None, None, pane_id="%1"), Pane | None)
    assert_type(panes.get(pane_id="%1", default=0), Pane | int)
    missing = panes.get(pane_id="%9", default=None)
    if missing is not None:
        assert_type(missing, Pane)


def server_listings_use_the_same_contract(server: Server) -> None:
    """Type ``Server`` listings as ``QueryList`` s."""
    session = server.sessions.get(session_name="a")
    assert_type(session, Session)
    assert_type(server.sessions.get(session_name="a", default=None), Session | None)


def a_default_of_none_is_not_a_pane(panes: QueryList[Pane]) -> None:
    """Reject use of a ``default=None`` result before narrowing."""
    maybe = panes.get(pane_id="%1", default=None)
    maybe.send_keys("x")  # type: ignore[union-attr]
