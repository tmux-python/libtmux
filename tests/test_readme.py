"""Prove a README snippet is runnable as published, not only inside pytest.

``README.md``'s ``>>> `` blocks are doctests, collected and run by the same
suite as everything else (see ``.github/WRITING.md``). That proves the
snippet executes *inside* this suite, where ``conftest.py``'s
``add_doctest_fixtures`` injects names like ``Server`` into the doctest
namespace -- it does not prove the snippet a reader copies into a plain
``python`` shell works, since that injection isn't there. This module
extracts a block straight from the file and runs it with a bare
interpreter to check the second claim too.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

README = pathlib.Path(__file__).parent.parent / "README.md"


def _extract_prompted_block(heading: str) -> str:
    """Return the runnable source of the first fenced block after *heading*.

    Reads the block straight from ``README.md`` rather than duplicating it
    here, so this cannot silently drift from what a reader actually sees.
    Only ``>>> ``/``... `` prompted lines are source; any other line inside
    the fence is a doctest's expected output, not code to run.
    """
    text = README.read_text()
    start = text.index(heading)
    fence_start = text.index("```python", start)
    fence_end = text.index("```", fence_start + len("```python"))
    block = text[fence_start:fence_end].splitlines()[1:]  # drop the fence line

    source_lines = []
    for line in block:
        if line.startswith(">>> "):
            source_lines.append(line[len(">>> ") :])
        elif line.startswith("... "):
            source_lines.append(line[len("... ") :])
    return "\n".join(source_lines)


def test_run_any_tmux_command_snippet_runs_without_doctest_fixtures() -> None:
    """The "Run any tmux command" snippet runs standalone.

    The published block called a bare ``Server(...)``, which only
    resolves during this suite's own doctest run, where
    ``conftest.py`` rebinds ``Server`` to a test factory -- copied into
    a fresh interpreter, it raised ``NameError: name 'Server' is not
    defined``. Run here with plain ``python -c``, outside pytest and
    its injected doctest namespace entirely.
    """
    source = _extract_prompted_block("### Run any tmux command")
    assert source, "could not extract the snippet from README.md"

    result = subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, (
        "README's 'Run any tmux command' snippet failed outside the "
        f"doctest suite\nsource:\n{source}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "NameError" not in result.stderr
