"""Structural contracts for the experimental engine documentation."""

from __future__ import annotations

import pathlib

import libtmux.experimental.engines as engines

_ROOT = pathlib.Path(__file__).parents[2]
_ENGINE_LANDING = _ROOT / "docs" / "experimental" / "engines.md"
_ENGINE_ROOT = _ROOT / "docs" / "experimental" / "engines"
_TUTORIAL_ROOT = _ROOT / "docs" / "experimental" / "tutorials"

_ENGINE_PAGES = {
    "AsyncControlModeEngine": (
        "async-control-mode.md",
        "libtmux.experimental.engines.async_control_mode.AsyncControlModeEngine",
    ),
    "AsyncMockEngine": (
        "async-mock.md",
        "libtmux.experimental.engines.mock.AsyncMockEngine",
    ),
    "AsyncSubprocessEngine": (
        "async-subprocess.md",
        "libtmux.experimental.engines.asyncio.AsyncSubprocessEngine",
    ),
    "ControlModeEngine": (
        "control-mode.md",
        "libtmux.experimental.engines.control_mode.ControlModeEngine",
    ),
    "ImsgEngine": (
        "imsg.md",
        "libtmux.experimental.engines.imsg.base.ImsgEngine",
    ),
    "MockEngine": (
        "mock.md",
        "libtmux.experimental.engines.mock.MockEngine",
    ),
    "SubprocessEngine": (
        "subprocess.md",
        "libtmux.experimental.engines.subprocess.SubprocessEngine",
    ),
}

_TUTORIAL_PAGES = {
    "async-control-plans.md",
    "async-subprocess.md",
    "control-mode.md",
    "imsg-parity.md",
    "live-operation.md",
    "offline-testing.md",
    "results-and-failures.md",
}

_REFERENCE_HEADINGS = (
    "## Use it when",
    "## Avoid it when",
    "## Construction and cleanup",
    "## Lifecycle and failure boundary",
    "## API",
    "## Related tutorial",
)


def test_engine_reference_inventory_is_exact() -> None:
    """The reference has one page per concrete engine."""
    exported_engines = {
        name
        for name in engines.__all__
        if name.endswith("Engine") and name not in {"AsyncTmuxEngine", "TmuxEngine"}
    }

    assert set(_ENGINE_PAGES) == exported_engines
    assert {path.name for path in _ENGINE_ROOT.glob("*.md")} == {
        filename for filename, _target in _ENGINE_PAGES.values()
    }


def test_engine_landing_owns_reference_and_tutorial_navigation() -> None:
    """The landing reaches every engine reference and tutorial."""
    text = _ENGINE_LANDING.read_text(encoding="utf-8")

    for filename, _target in _ENGINE_PAGES.values():
        assert f"engines/{filename.removesuffix('.md')}" in text
    assert "tutorials/index" in text
    assert "Async engines are constructed directly" in text
    assert "('control_mode', 'imsg', 'mock', 'subprocess')" in text


def test_engine_pages_have_one_executable_story_and_api_target() -> None:
    """Each reference owns one visible proof and one concrete autodoc target."""
    for engine, (filename, target) in _ENGINE_PAGES.items():
        path = _ENGINE_ROOT / filename
        text = path.read_text(encoding="utf-8")

        assert text.count("```python") == 1, engine
        assert ">>>" in text, engine
        assert f".. autoclass:: {target}" in text, engine
        assert "   :members:" in text, engine
        assert "{doc}`" in text, engine
        for heading in _REFERENCE_HEADINGS:
            assert heading in text, (engine, heading)


def test_tutorial_inventory_and_navigation_are_exact() -> None:
    """The tutorial index owns the seven shared task tutorials."""
    assert {path.name for path in _TUTORIAL_ROOT.glob("*.md")} == {
        "index.md",
        *_TUTORIAL_PAGES,
    }

    text = (_TUTORIAL_ROOT / "index.md").read_text(encoding="utf-8")
    for filename in _TUTORIAL_PAGES:
        assert filename.removesuffix(".md") in text


def test_tutorials_contain_visible_independent_doctests() -> None:
    """Every tutorial ships executable reader-facing Python."""
    for filename in _TUTORIAL_PAGES:
        text = (_TUTORIAL_ROOT / filename).read_text(encoding="utf-8")
        assert "```python" in text, filename
        assert ">>>" in text, filename


def test_engine_examples_keep_known_transport_boundaries() -> None:
    """Examples do not promise APIs or readiness that the engines lack."""
    pages = [
        _ENGINE_LANDING,
        *_ENGINE_ROOT.glob("*.md"),
        *_TUTORIAL_ROOT.glob("*.md"),
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in pages)

    assert "# doctest: +SKIP" not in text
    assert "testsetup" not in text
    assert "ImsgEngine.for_server" not in text
    assert "await asyncio.sleep(0)" not in text

    async_control = (_ENGINE_ROOT / "async-control-mode.md").read_text(encoding="utf-8")
    assert "AsyncControlModeEngine.subscribe" in async_control
    assert "readiness" in async_control
