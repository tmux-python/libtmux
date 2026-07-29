"""Prove the hidden checks would notice if the examples stopped working.

A check can pass for the wrong reason. The classic one on a page that types
into a pane is to look for the answer in :meth:`~libtmux.Pane.capture_pane`
output with a containment test: the captured lines include the command tmux
just echoed onto the pane, so the test is satisfied the moment the keystrokes
land — before any shell has run, and equally in a world where none ever will.
A page verified that way reports green while teaching a technique that does
not work.

So the checks are themselves checked. Each page that types a command and
reads the answer back is re-run against a libtmux whose ``send_keys`` types
the keys and never presses Enter. Nothing the page waits for can arrive, and
the page's own checks are required to say so.
"""

from __future__ import annotations

import typing as t

import pytest

from libtmux import exc
from libtmux.pane import Pane
from tests.docs import howto_harness

if t.TYPE_CHECKING:
    import pathlib


def _types_and_reads_back(page: pathlib.Path) -> bool:
    """Return whether a page both sends keys and reads the pane back.

    Parameters
    ----------
    page : pathlib.Path
        A how-to page.

    Returns
    -------
    bool
        True when the page's examples do both, and are therefore exposed to
        the echoed-command mistake.
    """
    source = "\n".join(
        block.source for block in howto_harness.parse_python_blocks(page)
    )
    return "send_keys" in source and "capture_pane" in source


#: Pages whose examples type a command and then read the answer back. Derived
#: rather than listed, so a page added later is covered without anyone having
#: to remember this file exists.
PAGES = [page for page in howto_harness.iter_pages() if _types_and_reads_back(page)]
PAGE_IDS = [page.name for page in PAGES]


def test_some_page_reads_output_back() -> None:
    """At least one page is covered, so the probe below is not vacuous."""
    assert PAGES


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_page_fails_when_the_shell_never_runs(
    page: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The page's checks fail when its keystrokes never reach a shell.

    Parameters
    ----------
    page : pathlib.Path
        A how-to page that types a command and reads the answer back.
    monkeypatch : pytest.MonkeyPatch
        Used to withhold the Enter key for the duration of the run.
    """
    typed = Pane.send_keys

    def without_enter(self: Pane, cmd: str | None = None, **kwargs: t.Any) -> None:
        """Type the keys and never press Enter.

        Parameters
        ----------
        self : libtmux.Pane
            Pane being typed into.
        cmd : str, optional
            Keys to send.
        **kwargs : object
            Everything else the page passed, minus ``enter``.
        """
        kwargs.pop("enter", None)
        typed(self, cmd, enter=False, **kwargs)

    monkeypatch.setattr(Pane, "send_keys", without_enter)

    with pytest.raises((AssertionError, exc.LibTmuxException)):
        howto_harness.run_page(page)
