"""Structural contracts for the experimental engine documentation."""

from __future__ import annotations

import doctest
import pathlib
import re

from libtmux.experimental import engines

_ROOT = pathlib.Path(__file__).parents[2]
_ENGINE_LANDING = _ROOT / "docs" / "experimental" / "engines.md"
_ENGINE_ROOT = _ROOT / "docs" / "experimental" / "engines"
_TUTORIAL_ROOT = _ROOT / "docs" / "experimental" / "tutorials"
_PYTHON_BLOCK = re.compile(
    r"^```python\n(?P<body>.*?)^```$",
    re.MULTILINE | re.DOTALL,
)

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

_CANONICAL_TUTORIALS = {
    "AsyncControlModeEngine": "async-control-plans.md",
    "AsyncMockEngine": "offline-testing.md",
    "AsyncSubprocessEngine": "async-subprocess.md",
    "ControlModeEngine": "control-mode.md",
    "ImsgEngine": "imsg-parity.md",
    "MockEngine": "offline-testing.md",
    "SubprocessEngine": "live-operation.md",
}

_REFERENCE_HEADINGS = (
    "## Use it when",
    "## Avoid it when",
    "## Construction and cleanup",
    "## Lifecycle and failure boundary",
    "## API",
    "## Related tutorial",
)


def _first_python_block(engine: str) -> str:
    """Return one engine page's first visible Python block."""
    filename, _target = _ENGINE_PAGES[engine]
    text = (_ENGINE_ROOT / filename).read_text(encoding="utf-8")
    match = _PYTHON_BLOCK.search(text)
    assert match is not None, engine
    return match.group("body")


def test_engine_reference_inventory_is_exact() -> None:
    """The reference has one page per concrete engine."""
    exported_engines = {
        name
        for name in engines.__all__
        if name.endswith("Engine") and name not in {"AsyncTmuxEngine", "TmuxEngine"}
    }

    assert set(_ENGINE_PAGES) == exported_engines
    assert set(_CANONICAL_TUTORIALS) == exported_engines
    assert {path.name for path in _ENGINE_ROOT.glob("*.md")} == {
        filename for filename, _target in _ENGINE_PAGES.values()
    }


def test_engine_landing_owns_reference_and_tutorial_navigation() -> None:
    """Each landing entry maps an engine reference to its canonical tutorial."""
    text = _ENGINE_LANDING.read_text(encoding="utf-8")
    lines = text.splitlines()

    for engine, (filename, _target) in _ENGINE_PAGES.items():
        assert f"engines/{filename.removesuffix('.md')}" in text
        tutorial = _CANONICAL_TUTORIALS[engine].removesuffix(".md")
        assert any(
            engine in line and f"tutorials/{tutorial}" in line for line in lines
        ), engine
    assert "tutorials/index" in text
    assert "Async engines are constructed directly" in text
    assert "('control_mode', 'imsg', 'mock', 'subprocess')" in text
    assert "HasSession" not in text
    assert 'type(create_engine("mock")).__name__' in text


def test_engine_pages_have_visible_first_success_and_api_target() -> None:
    """Each reference opens with executable success and owns one API target."""
    for engine, (filename, target) in _ENGINE_PAGES.items():
        path = _ENGINE_ROOT / filename
        text = path.read_text(encoding="utf-8")
        block = _first_python_block(engine)
        examples = doctest.DocTestParser().get_examples(block)
        tutorial = _CANONICAL_TUTORIALS[engine].removesuffix(".md")

        assert examples, engine
        assert engine in block, engine
        assert any(example.want for example in examples), engine
        assert text.index("```python") < text.index("## API"), engine
        assert f".. autoclass:: {target}" in text, engine
        assert "   :members:" in text, engine
        assert f"{{doc}}`../tutorials/{tutorial}`" in text, engine
        for heading in _REFERENCE_HEADINGS:
            assert heading in text, (engine, heading)


def test_canonical_tutorials_are_present_and_navigable() -> None:
    """Every canonical engine story exists and is assigned in its index."""
    text = (_TUTORIAL_ROOT / "index.md").read_text(encoding="utf-8")
    lines = text.splitlines()
    for engine, filename in _CANONICAL_TUTORIALS.items():
        assert (_TUTORIAL_ROOT / filename).is_file(), filename
        assert filename.removesuffix(".md") in text
        assert any(
            engine in line and filename.removesuffix(".md") in line for line in lines
        ), engine


def test_canonical_tutorials_contain_visible_independent_doctests() -> None:
    """Every canonical engine story ships executable reader-facing Python."""
    for engine, filename in _CANONICAL_TUTORIALS.items():
        text = (_TUTORIAL_ROOT / filename).read_text(encoding="utf-8")
        blocks = _PYTHON_BLOCK.findall(text)
        assert blocks, filename
        assert all(">>>" in block for block in blocks), filename
        assert engine in text, engine
        assert any(engine in block for block in blocks), engine


def test_control_mode_first_successes_use_typed_operations() -> None:
    """Control-mode references teach typed execution instead of raw batching."""
    expected_runners = {
        "ControlModeEngine": "run(",
        "AsyncControlModeEngine": "arun(",
    }
    observed = {}
    for engine, runner in expected_runners.items():
        block = _first_python_block(engine)
        observed[engine] = {
            "typed_runner": runner in block,
            "raw_request": "CommandRequest" in block,
            "raw_batch": ".run_batch(" in block,
        }

    assert observed == {
        engine: {
            "typed_runner": True,
            "raw_request": False,
            "raw_batch": False,
        }
        for engine in expected_runners
    }


def test_imsg_is_the_only_raw_request_first_success() -> None:
    """Only the imsg parity story needs a raw CommandRequest."""
    raw_request_engines = {
        engine
        for engine in _ENGINE_PAGES
        if "CommandRequest" in _first_python_block(engine)
    }

    assert raw_request_engines == {"ImsgEngine"}


def test_engine_examples_keep_known_transport_boundaries() -> None:
    """Examples do not promise APIs or readiness that the engines lack."""
    pages = [
        _ENGINE_LANDING,
        *_ENGINE_ROOT.glob("*.md"),
        *_TUTORIAL_ROOT.glob("*.md"),
    ]
    for path in pages:
        text = path.read_text(encoding="utf-8")
        assert "# doctest: +SKIP" not in text, path
        assert "testsetup" not in text, path
        assert "request.getfixturevalue" not in text, path
        assert "sleep(" not in text, path
        assert "wait_for_output" not in text, path
        assert "ImsgEngine.for_server" not in text, path

    async_control = (_ENGINE_ROOT / "async-control-mode.md").read_text(encoding="utf-8")
    assert "AsyncControlModeEngine.subscribe" in async_control
    assert "readiness" in async_control
