"""Behavioral checks for the rampa load scenario's stale-root reaper.

``scripts/lgtm/load_tmux.py`` cleans up in rampa's ``teardown`` hook, which
covers a normal finish and a Ctrl-C alike. SIGKILL runs no user code, so a
killed run strands a tmux server, its pane, and its scratch root, each holding
a pty. The reaper is the path that survives that, because it runs at the start
of the *next* run.

These run the scenario module in a subprocess under the ``load`` dependency
group: rampa needs a newer Python than libtmux targets, so it is not present in
the plain test environment.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import textwrap

import pytest

_ROOT = pathlib.Path(__file__).parents[1]


_PREAMBLE = (
    "import os, pathlib, sys\nsys.path.insert(0, 'scripts/lgtm')\nimport load_tmux\n"
)


def _run_in_load_env(body: str) -> subprocess.CompletedProcess[str]:
    """Execute *body* with the scenario module already imported.

    *body* is dedented on its own before the preamble is prepended: dedenting
    the joined text instead would find no common prefix and leave the indented
    half indented, which fails as an ``IndentationError`` the caller then reads
    as "rampa is unavailable" and skips.
    """
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    # The scenario refuses to import without a valid lane, by design.
    env["LIBTMUX_LOAD_LANE"] = "control-async"
    return subprocess.run(
        (
            "uv",
            "run",
            "--group",
            "otel",
            "--group",
            "load",
            "python",
            "-c",
            _PREAMBLE + textwrap.dedent(body),
        ),
        cwd=_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.fixture(scope="module")
def load_module_available() -> None:
    """Skip the module when rampa cannot be resolved for this interpreter."""
    probe = _run_in_load_env("print('importable')")
    if probe.returncode != 0:
        pytest.skip(f"load scenario not importable here: {probe.stderr[-400:]}")
    assert "importable" in probe.stdout


def test_reaper_removes_a_root_whose_owner_is_gone(
    load_module_available: None,
    tmp_path: pathlib.Path,
) -> None:
    """A root left by a killed run is reclaimed, server and directory alike."""
    completed = _run_in_load_env(
        f"""
        root = pathlib.Path({str(tmp_path)!r}) / (load_tmux._ROOT_PREFIX + "dead")
        root.mkdir()
        # pid 2**22 is above the default pid_max, so it cannot be running.
        (root / "owner").write_text("4194304 999")

        load_tmux.tempfile.gettempdir = lambda: {str(tmp_path)!r}
        load_tmux._reap_stale_roots()

        print("REAPED" if not root.exists() else "KEPT")
        """
    )

    assert completed.returncode == 0, completed.stderr
    assert "REAPED" in completed.stdout


def test_reaper_leaves_a_root_whose_owner_is_alive(
    load_module_available: None,
    tmp_path: pathlib.Path,
) -> None:
    """A concurrent run's root is untouched.

    This is the property that makes the reaper safe to run unattended: stealing
    another run's tmux server would be a worse failure than leaking this one.
    """
    completed = _run_in_load_env(
        f"""
        root = pathlib.Path({str(tmp_path)!r}) / (load_tmux._ROOT_PREFIX + "live")
        root.mkdir()
        # This very process is the owner, so the identity check must match.
        (root / "owner").write_text(
            f"{{os.getpid()}} {{load_tmux._process_identity(os.getpid())}}"
        )

        load_tmux.tempfile.gettempdir = lambda: {str(tmp_path)!r}
        load_tmux._reap_stale_roots()

        print("KEPT" if root.exists() else "REAPED")
        """
    )

    assert completed.returncode == 0, completed.stderr
    assert "KEPT" in completed.stdout


def test_reaper_rejects_a_reused_pid(
    load_module_available: None,
    tmp_path: pathlib.Path,
) -> None:
    """A live pid with a different start time is a reused number, not the owner.

    Without the start-time half of the identity, the reaper would skip a stale
    root forever once the kernel handed its pid to something else -- or, worse,
    a bare-pid *match* would let it reap a live run.
    """
    completed = _run_in_load_env(
        f"""
        root = pathlib.Path({str(tmp_path)!r}) / (load_tmux._ROOT_PREFIX + "reused")
        root.mkdir()
        # A running pid, but stamped with a start time that is not its own.
        (root / "owner").write_text(f"{{os.getpid()}} 1")

        load_tmux.tempfile.gettempdir = lambda: {str(tmp_path)!r}
        load_tmux._reap_stale_roots()

        print("REAPED" if not root.exists() else "KEPT")
        """
    )

    assert completed.returncode == 0, completed.stderr
    assert "REAPED" in completed.stdout


def test_process_identity_is_absent_for_a_dead_pid(
    load_module_available: None,
) -> None:
    """The identity probe reports absence rather than raising."""
    completed = _run_in_load_env(
        """
        print("SELF", load_tmux._process_identity(os.getpid()) is not None)
        print("DEAD", load_tmux._process_identity(4194304) is None)
        """
    )

    assert completed.returncode == 0, completed.stderr
    assert "SELF True" in completed.stdout
    assert "DEAD True" in completed.stdout


def test_hold_command_outlasts_any_plausible_run(
    load_module_available: None,
) -> None:
    """The pane's holding command bounds how long a run can last.

    When it exits the window closes, the last window closing ends the session,
    and the server goes with it -- ``destroy-unattached off`` only survives
    *detach*. So this value is a run-duration ceiling, and a short one would
    kill a long ``--duration`` mid-flight.
    """
    completed = _run_in_load_env(
        """
        print("HOLD", load_tmux._HOLD_COMMAND)
        """
    )

    assert completed.returncode == 0, completed.stderr
    seconds = int(completed.stdout.split("HOLD sleep ")[1].split()[0])
    assert seconds >= 3600, "a run longer than the hold command loses its server"
