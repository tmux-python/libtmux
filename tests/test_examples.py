"""Execute every script under examples/ end to end, as a reader would.

Each script is a standalone program (not a doctest, not a fixture): it owns
its own :class:`~libtmux.Server` and spawns real tmux sessions, so it is run
here as a subprocess with ``sys.executable``, exactly as
``python examples/quickstart.py`` reads on the page. This is what proves an
example is runnable as shown rather than merely present in the tree.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

EXAMPLES_DIR = pathlib.Path(__file__).parent.parent / "examples"
EXAMPLE_SCRIPTS = sorted(EXAMPLES_DIR.glob("*.py"))


@pytest.mark.examples
@pytest.mark.parametrize(
    "script",
    EXAMPLE_SCRIPTS,
    ids=[script.stem for script in EXAMPLE_SCRIPTS],
)
def test_example_runs_cleanly(script: pathlib.Path) -> None:
    """Run one examples/*.py script and require a clean exit.

    Spawns real tmux servers via the script's own ``Server.owned()`` calls,
    so this belongs with the rest of the suite -- every other test here
    already requires a live tmux binary on ``PATH``.
    """
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, (
        f"{script.name} exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


def test_examples_directory_is_not_empty() -> None:
    """Guard against a silently emptied examples/ directory.

    A future cleanup that deletes every script would leave the parametrized
    test above collecting zero cases -- a green run reporting nothing wrong.
    """
    assert len(EXAMPLE_SCRIPTS) > 0


def test_command_results_example_never_probes_the_default_socket() -> None:
    """command_results.py's probe never reaches a reader's default socket.

    The probe names an isolated socket (``-L``) that cannot already
    exist, so "no server running" is deterministic regardless of
    whether the reader has their own interactive tmux running on the
    ambient default socket. It is read-only and ``has-session`` never
    starts a server. Assert the probe's own isolated socket name
    appears in stdout and the ambient default socket path does not.
    """
    script = EXAMPLES_DIR / "command_results.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    assert "libtmux-examples-command-results-no-such-server" in result.stdout
    # The ambient default socket name tmux falls back to with no selector
    # (`$TMUX_TMPDIR/tmux-<uid>/default`) must never appear.
    assert "/default" not in result.stdout
