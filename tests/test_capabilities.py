"""Tests for the tmux capability table and its published manifest."""

from __future__ import annotations

import dataclasses
import importlib
import json
import pathlib
import re
import typing as t

import pytest

from libtmux import Format, exc
from libtmux._internal.support import capabilities

if t.TYPE_CHECKING:
    from libtmux.pane import Pane
    from libtmux.session import Session

MANIFEST_PATH = pathlib.Path(__file__).parent.parent / "capabilities.json"


def _resolve(dotted: str) -> object:
    """Import the longest module prefix of *dotted*, then walk the attributes."""
    parts = dotted.split(".")
    for split in range(len(parts), 0, -1):
        try:
            found: object = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        for attribute in parts[split:]:
            found = getattr(found, attribute)
        return found
    raise ImportError(dotted)


def test_manifest_matches_table() -> None:
    """The committed manifest text and data match what the table generates."""
    raw = MANIFEST_PATH.read_text(encoding="utf-8")

    assert json.loads(raw) == capabilities.manifest()
    assert raw == capabilities.render()


def test_manifest_floor_is_the_minimum_tmux() -> None:
    """The manifest's floor is the release libtmux declares as its minimum."""
    from libtmux._internal.support import MINIMUM as TMUX_MIN_VERSION

    assert capabilities.manifest()["floor"] == {"minimum": TMUX_MIN_VERSION}


def test_ids_are_unique_kebab_case() -> None:
    """An id names one capability and is lowercase kebab-case."""
    ids = [capability.id for capability in capabilities.CAPABILITIES]

    assert ids
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", id_) for id_ in ids)


def test_refusals_name_their_error() -> None:
    """A capability libtmux refuses names the exception a caller catches."""
    refused = [c for c in capabilities.CAPABILITIES if c.handling == "refuse"]

    assert refused
    assert all(c.error is not None for c in refused)


@pytest.mark.parametrize(
    "name",
    sorted(
        {api for c in capabilities.CAPABILITIES for api in c.apis}
        | {c.error for c in capabilities.CAPABILITIES if c.error is not None},
    ),
)
def test_published_names_resolve(name: str) -> None:
    """Every API and error name the manifest publishes exists."""
    assert _resolve(name) is not None


def test_since_rejects_an_unknown_id() -> None:
    """Asking for a capability the table does not define is a KeyError."""
    with pytest.raises(KeyError, match="no-such-capability"):
        capabilities.capability_since("no-such-capability")


class GateCase(t.NamedTuple):
    """One gated call, and what an old tmux gets from it."""

    test_id: str
    capability: str
    call: t.Callable[[Session], object]
    warning: str | None


def _pane(session: Session) -> Pane:
    pane = session.active_pane
    assert pane is not None
    return pane


def _paste_without_vis(session: Session) -> None:
    session.server.set_buffer("capability-gate")
    _pane(session).paste_buffer(no_vis=True)


GATE_CASES: list[GateCase] = [
    GateCase(
        "run_shell_cwd",
        "run-shell-start-directory",
        lambda session: session.server.run_shell("true", cwd="/", background=True),
        "cwd requires tmux",
    ),
    GateCase(
        "run_shell_cwd_format",
        "run-shell-start-directory-format",
        lambda session: session.server.run_shell(
            "true", cwd=Format("/"), background=True
        ),
        None,
    ),
    GateCase(
        "run_shell_show_stderr",
        "run-shell-show-stderr",
        lambda session: session.server.run_shell(
            "true", show_stderr=True, background=True
        ),
        "show_stderr requires tmux",
    ),
    GateCase(
        "run_shell_args",
        "run-shell-args",
        lambda session: session.server.run_shell("true", args=["x"], background=True),
        "args requires tmux",
    ),
    GateCase(
        "run_shell_output",
        "run-shell-output-in-copy-mode",
        lambda session: session.server.run_shell("true"),
        None,
    ),
    GateCase(
        "list_keys_format",
        "list-keys-format",
        lambda session: session.server.list_keys(format_="#{key_string}"),
        "format requires tmux",
    ),
    GateCase(
        "capture_trim_trailing",
        "capture-trim-blank-cells",
        lambda session: _pane(session).capture_pane(trim_trailing=True),
        "trim_trailing requires tmux",
    ),
    GateCase(
        "capture_mode_screen",
        "capture-mode-screen",
        lambda session: _pane(session).capture_pane(mode_screen=True),
        "mode_screen requires tmux",
    ),
    GateCase(
        "capture_hyperlinks",
        "capture-line-flags",
        lambda session: _pane(session).capture_pane(hyperlinks=True),
        "hyperlinks requires tmux",
    ),
    GateCase(
        "capture_line_numbers",
        "capture-line-flags",
        lambda session: _pane(session).capture_pane(line_numbers=True),
        "line_numbers requires tmux",
    ),
    GateCase(
        "capture_line_flags",
        "capture-line-flags",
        lambda session: _pane(session).capture_pane(line_flags=True),
        "line_flags requires tmux",
    ),
    GateCase(
        "paste_buffer_no_vis",
        "paste-buffer-no-vis",
        _paste_without_vis,
        "no_vis requires tmux",
    ),
    GateCase(
        "new_pane",
        "floating-pane",
        lambda session: _pane(session).new_pane(),
        None,
    ),
]


@pytest.mark.parametrize(
    list(GateCase._fields),
    GATE_CASES,
    ids=[case.test_id for case in GATE_CASES],
)
def test_gate_reads_its_release_from_the_table(
    test_id: str,
    capability: str,
    call: t.Callable[[Session], object],
    warning: str | None,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each gated call takes its release from the capability table.

    The table entry's release is raised above any tmux with ``monkeypatch``,
    which stands in for an old tmux: the suite runs one tmux build, and the
    gate's own fallback or refusal is the behaviour under test.
    """
    entry = capabilities.get(capability)
    monkeypatch.setitem(
        capabilities._BY_ID,
        capability,
        dataclasses.replace(entry, since="99.0"),
    )

    if warning is None:
        with pytest.raises(exc.LibTmuxException, match="requires tmux"):
            call(session)
    else:
        with pytest.warns(UserWarning, match=warning):
            call(session)
