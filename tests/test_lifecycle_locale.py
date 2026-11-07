"""Exercise lifecycle receipts with the locale used by the actual tmux client."""

from __future__ import annotations

import json
import os
import pathlib
import select
import subprocess
import typing as t

import pytest

import libtmux.lifecycle as lifecycle_module
from libtmux import Server
from libtmux._compat import BaseExceptionGroup
from libtmux.lifecycle import CreationCleanupError, UnknownCreation
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from collections.abc import Generator

    from libtmux.common import tmux_cmd


@pytest.fixture(
    params=[("C", "C"), ("C.UTF-8", "C"), ("C.UTF-8", "C.UTF-8")],
    ids=["c", "lc-all-c", "utf8"],
)
def locale_server(
    request: pytest.FixtureRequest,
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    clear_env: None,
    record_property: t.Callable[[str, object], None],
) -> Generator[Server, None, None]:
    """Set locale after clear_env and check each selected endpoint's client launch."""
    lang, lc_all = request.param
    monkeypatch.setenv("LANG", lang)
    monkeypatch.setenv("LC_ALL", lc_all)
    server = Server(socket_path=tmp_path / "server.sock", config_file="/dev/null")
    expected = {"LANG": lang, "LC_ALL": lc_all}
    assert {key: os.environ[key] for key in expected} == expected
    assert {key: server.child_environment[key] for key in expected} == expected
    parent_environment = dict(os.environ)
    parent_environment.pop("PYTEST_CURRENT_TEST", None)
    launches: list[dict[str, str]] = []
    launch = subprocess.Popen

    def checked_launch(*args: t.Any, **kwargs: t.Any) -> subprocess.Popen[str]:
        if any(
            argument in (str(server.socket_path), f"-S{server.socket_path}")
            for argument in args[0]
        ):
            actual = {key: kwargs["env"].get(key) for key in expected}
            assert actual == expected
            launches.append(actual)
        return launch(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", checked_launch)
    try:
        yield server
    finally:
        # Only this fixture can create a daemon at this fresh explicit endpoint.
        probe = server.cmd("display-message", "-p", "#{pid}")
        if probe.returncode == 0:
            pid = int(probe.stdout[0])
            descriptor = os.pidfd_open(pid) if hasattr(os, "pidfd_open") else None
            try:
                killed = server.cmd(
                    "if-shell", "-F", f"#{{==:#{{pid}},{pid}}}", "kill-server", ""
                )
                assert killed.returncode == 0, killed.stderr
                if descriptor is not None:
                    poller = select.poll()
                    poller.register(descriptor, select.POLLIN)
                    assert any(
                        events & select.POLLIN for _, events in poller.poll(3000)
                    )
                else:

                    def process_exited() -> bool:
                        try:
                            os.kill(pid, 0)
                        except ProcessLookupError:
                            return True
                        return False

                    retry_until(process_exited, seconds=3)
                    assert process_exited()
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        assert launches
        after = dict(os.environ)
        after.pop("PYTEST_CURRENT_TEST", None)
        assert after == parent_environment
        record_property(
            "effective_locale",
            json.dumps({"after_fixtures": expected, "client_launches": launches}),
        )


def test_discovery_reads_ascii_identity_in_effective_locale(
    locale_server: Server,
) -> None:
    """A raw-created daemon remains discoverable without ownership metadata writes."""
    server = locale_server
    started = server.cmd("new-session", "-d", "-s", "keeper", "/bin/sh")
    assert started.returncode == 0, started.stderr
    before = server.cmd("show-options", "-s").stdout
    result = server.discover(
        [pathlib.Path(server.socket_path).parent], include_configured=False
    )
    assert not result.diagnostics
    assert len(result.servers) == 1
    assert result.servers[0].server_pid == int(
        server.cmd("display-message", "-p", "#{pid}").stdout[0]
    )
    assert result.servers[0].start_time == int(
        server.cmd("display-message", "-p", "#{start_time}").stdout[0]
    )
    assert server.cmd("show-options", "-s").stdout == before


def test_server_created_and_borrowed_receipts_in_effective_locale(
    locale_server: Server,
) -> None:
    """Startup returns its owner while a borrowed scope preserves that daemon."""
    server = locale_server
    created = server.find_or_create(timeout=0.5)
    assert created.created and created.owner is not None
    borrowed = server.find_or_create(timeout=0.5)
    assert not borrowed.created and borrowed.owner is None
    with pytest.raises(ValueError, match="borrowed body"), borrowed:
        message = "borrowed body"
        raise ValueError(message)
    assert server.cmd("display-message", "-p", "#{pid}").stdout == [
        str(created.owner.identity.server_pid)
    ]
    created.close()
    assert created.owner.closed
    assert server.cmd("display-message", "-p", "#{pid}").returncode != 0


@pytest.mark.parametrize("interrupt", [False, True])
def test_server_receipt_retains_both_failures_in_effective_locale(
    locale_server: Server,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: bool,
) -> None:
    """Acceptance and rollback failures retain the exact cause and retry owner."""
    primary = KeyboardInterrupt() if interrupt else ValueError("acceptance failed")
    cleanup = PermissionError("rollback failed")

    def reject(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise primary

    def refuse(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise cleanup

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_module, "_verify_identity", reject)
        patch.setattr(lifecycle_module.Owned, "_destroy", refuse)
        with pytest.raises(BaseExceptionGroup) as caught:
            locale_server.find_or_create(timeout=0.5)
    assert caught.value.exceptions[0] is primary
    retry = caught.value.exceptions[1]
    assert isinstance(retry, CreationCleanupError)
    assert retry.__cause__ is cleanup
    assert retry.owner.cleanup_error is cleanup
    assert retry.owner._timeout == 0.5
    retry.owner.close()
    assert retry.owner.closed
    assert locale_server.cmd("display-message", "-p", "#{pid}").returncode != 0


@pytest.mark.parametrize("kind", ["session", "window", "pane"])
def test_child_receipt_retains_payload_and_rollback_in_effective_locale(
    locale_server: Server,
    monkeypatch: pytest.MonkeyPatch,
    kind: t.Literal["session", "window", "pane"],
) -> None:
    """Receipt recovery preserves delimiter-bearing payload without legacy snapshots."""
    server = locale_server
    started = server.cmd("new-session", "-d", "-s", "keeper", "/bin/sh")
    assert started.returncode == 0, started.stderr
    command = {
        "session": "new-session",
        "window": "new-window",
        "pane": "split-window",
    }[kind]
    payload = "ascii|payload|end"
    arguments = ["-d", "-P", "-F", lifecycle_module._creation_format(kind, payload)]
    if kind != "session":
        arguments += ["-t", "keeper:"]
    arguments.append("/bin/sh")
    listing = (f"list-{kind}s", *(("-a",) if kind != "session" else ()))
    before = server.cmd(*listing, "-F", f"#{{{kind}_id}}").stdout
    primary = ValueError("materialization failed")
    cleanup = PermissionError("rollback failed")
    created_id = None

    def refuse(*args: t.Any, **kwargs: t.Any) -> t.NoReturn:
        raise cleanup

    with monkeypatch.context() as patch:
        patch.setattr(lifecycle_module.Owned, "_destroy", refuse)
        with (
            pytest.raises(BaseExceptionGroup) as caught,
            lifecycle_module._creation(server, kind, command, tuple(arguments)) as (
                result,
                receipt,
            ),
        ):
            assert result.stdout == [payload]
            created_id = receipt.identity.object_id
            assert created_id not in before
            raise primary
    assert caught.value.exceptions[0] is primary
    retry = caught.value.exceptions[1]
    assert isinstance(retry, CreationCleanupError)
    assert retry.__cause__ is cleanup
    assert retry.owner.cleanup_error is cleanup
    assert retry.owner.identity.object_id == created_id
    retry.owner.close()
    assert server.cmd(*listing, "-F", f"#{{{kind}_id}}").stdout == before
    assert server.has_session("keeper")


def test_missing_startup_receipt_stays_unknown_in_effective_locale(
    locale_server: Server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable receipt cannot justify inventing ownership or destroying tmux."""
    original = Server.cmd

    def lose(client: Server, command: str, *args: t.Any, **kwargs: t.Any) -> tmux_cmd:
        result = original(client, command, *args, **kwargs)
        if command == "start-server":
            result.stdout = []
        return result

    with monkeypatch.context() as patch:
        patch.setattr(Server, "cmd", lose)
        with pytest.raises(UnknownCreation):
            locale_server.find_or_create(timeout=0.5)
    assert locale_server.cmd("display-message", "-p", "#{pid}").returncode == 0
