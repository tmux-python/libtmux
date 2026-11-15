"""Connected-daemon feature decisions and refusal before effects."""

from __future__ import annotations

import dataclasses
import typing as t

import pytest

from libtmux import exc
from libtmux._internal import program
from libtmux.capabilities import ServerCapabilities

if t.TYPE_CHECKING:
    from libtmux.session import Session


@pytest.mark.parametrize(
    ("version", "state"),
    [
        ("3.3a", "unsupported"),
        ("3.7c", "unsupported"),
        ("next-3.8", "unsupported"),
        ("3.8-rc", "unsupported"),
        ("3.8-rc2", "unsupported"),
        ("3.8", "supported"),
        ("3.8a", "supported"),
        ("next-3.9", "supported"),
        ("3.10", "supported"),
        ("master", "unknown"),
        ("3.8-custom", "unknown"),
        ("3.8a-extra", "unknown"),
        ("", "unknown"),
    ],
)
def test_program_release_boundary(version: str, state: str) -> None:
    """Require the released feature boundary, preserving unknown spellings."""
    report = ServerCapabilities(pid=42, start_time=10, version=version)
    feature = report.feature("program-owned")
    assert feature.status == state
    assert feature.since == "3.8"
    assert bool(feature.reason)
    assert report.supports("program-owned") is (state == "supported")
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.version = "changed"  # type: ignore[misc]
    with pytest.raises(KeyError):
        report.feature("unknown-feature")


def test_capabilities_use_connected_daemon(session: Session) -> None:
    """Discovery binds native version and identity without creating a window."""
    before = session.cmd("list-windows", "-F", "#{window_id}").stdout
    report = session.server.capabilities()
    row = session.cmd("display-message", "-p", "#{pid}|#{start_time}|#{version}").stdout
    assert row == [f"{report.pid}|{report.start_time}|{report.version}"]
    assert session.server.capabilities() == report
    assert session.cmd("list-windows", "-F", "#{window_id}").stdout == before


@pytest.mark.parametrize("version", ["3.8-rc2", "next-3.8", "3.8-custom"])
def test_unsupported_version_refuses_before_creation(
    session: Session, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    """A synthetic version exercises refusal while a real daemon proves no effects."""
    original = program._Program._run

    def version_reply(
        owner: program._Program, args: tuple[str, ...], *rest: t.Any
    ) -> bytes:
        result = original(owner, args, *rest)
        if args[-1] == "#{pid}|#{start_time}|#{session_id}|#{version}":
            return result.rsplit(b"|", 1)[0] + b"|" + version.encode() + b"\n"
        return result

    before = session.cmd("list-windows", "-F", "#{window_id}").stdout
    monkeypatch.setattr(program._Program, "_run", version_reply)
    with pytest.raises(exc.LibTmuxException):
        session.run_program(["/bin/echo", "not admitted"])
    assert session.cmd("list-windows", "-F", "#{window_id}").stdout == before
