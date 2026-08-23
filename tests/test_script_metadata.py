"""Tests for the inline metadata that makes a repository script runnable.

Every script under ``scripts/`` carries a PEP 723 block and a ``uv run
--script`` shebang, so its dependencies resolve without a prepared
environment. That block is invisible to the rest of the suite: the tests for a
given script import it by path into the already-installed development
environment, which satisfies ``import libtmux`` no matter what the block says.
These tests exercise the block itself.
"""

from __future__ import annotations

import pathlib
import typing as t

import pytest

# ``tomllib`` is stdlib from 3.11 onward. The package still supports 3.10, and
# mypy type-checks against that floor, so this module skips there rather than
# growing a dependency to parse a handful of comment lines.
tomllib = pytest.importorskip("tomllib")

_REPO_ROOT = pathlib.Path(__file__).parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"

_BLOCK_OPEN = "# /// script"
_BLOCK_CLOSE = "# ///"


def _inline_metadata(script: pathlib.Path) -> dict[str, t.Any] | None:
    """Return *script*'s PEP 723 table, or ``None`` when it carries no block."""
    lines = script.read_text(encoding="utf-8").splitlines()
    if _BLOCK_OPEN not in lines:
        return None
    body: list[str] = []
    for line in lines[lines.index(_BLOCK_OPEN) + 1 :]:
        if line == _BLOCK_CLOSE:
            parsed: dict[str, t.Any] = tomllib.loads("\n".join(body))
            return parsed
        body.append(line.removeprefix("#").removeprefix(" "))
    msg = f"{script} opens a PEP 723 block it never closes"
    raise AssertionError(msg)


def _scripts_with_inline_metadata() -> list[pathlib.Path]:
    """Every script carrying a PEP 723 block, in a stable order."""
    if not _SCRIPTS.is_dir():
        return []
    return sorted(p for p in _SCRIPTS.rglob("*.py") if _inline_metadata(p) is not None)


_PEP723 = _scripts_with_inline_metadata()
_IDS = [str(p.relative_to(_REPO_ROOT)) for p in _PEP723]


def test_the_scan_finds_scripts_to_check() -> None:
    """Guard the parametrized tests below against passing on an empty set.

    They are parametrized over a filesystem scan, so a rename that moved every
    script out of ``scripts/`` would leave them collecting nothing and reporting
    green.
    """
    assert _PEP723, f"no PEP 723 scripts found under {_SCRIPTS}"


@pytest.mark.parametrize("script", _PEP723, ids=_IDS)
def test_a_script_depending_on_libtmux_pins_this_checkout(
    script: pathlib.Path,
) -> None:
    """Resolving libtmux from the index measures the wrong library.

    Without a ``tool.uv.sources`` entry, ``uv`` installs the released libtmux
    into the script's ephemeral environment. A benchmark then reports numbers
    for whatever is on the index rather than for the working tree, and any
    script reaching for an unreleased module fails outright at import.

    The path is compared by resolution rather than by spelling, so moving a
    script between directories fails here unless its ``..`` count follows.
    """
    metadata = _inline_metadata(script)
    assert metadata is not None

    dependencies = metadata.get("dependencies", [])
    if not any(d == "libtmux" or d.startswith("libtmux") for d in dependencies):
        pytest.skip("does not depend on libtmux")

    sources = metadata.get("tool", {}).get("uv", {}).get("sources", {})
    assert "libtmux" in sources, (
        f"{script.name} depends on libtmux without a [tool.uv.sources] entry, "
        "so uv resolves it from the index instead of this checkout"
    )

    pinned = (script.parent / sources["libtmux"]["path"]).resolve()
    assert pinned == _REPO_ROOT.resolve(), (
        f"{script.name} pins libtmux at {pinned}, not the repository root"
    )
    assert sources["libtmux"].get("editable") is True
