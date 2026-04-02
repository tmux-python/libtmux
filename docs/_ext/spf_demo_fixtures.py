"""Synthetic fixtures for the sphinx_pytest_fixtures badge demo page.

Each fixture exercises one badge-slot combination so the demo page can show
every permutation side-by-side:

  Scope:  session | module | class | function (suppressed — no badge)
  Kind:   resource (suppressed) | factory | override_hook
  State:  autouse | deprecated (set via RST :deprecated: option)
  Combos: session+factory, session+autouse

These fixtures are purely for documentation; they are never collected by
pytest during a real test run (the module is not in the test tree).
"""

from __future__ import annotations

import pytest


@pytest.fixture
def demo_plain() -> str:
    """Plain function-scope resource. Shows FIXTURE badge only."""
    return "plain"


@pytest.fixture(scope="session")
def demo_session() -> str:
    """Session-scoped resource. Shows SESSION + FIXTURE badges."""
    return "session"


@pytest.fixture(scope="module")
def demo_module() -> str:
    """Module-scoped resource. Shows MODULE + FIXTURE badges."""
    return "module"


@pytest.fixture(scope="class")
def demo_class() -> str:
    """Class-scoped resource. Shows CLASS + FIXTURE badges."""
    return "class"


@pytest.fixture
def demo_factory() -> type[str]:
    """Return a callable (factory kind). Shows FACTORY + FIXTURE badges."""
    return str


@pytest.fixture
def demo_override_hook() -> str:
    """Override hook — customise in conftest.py. Shows OVERRIDE + FIXTURE badges."""
    return "override"


@pytest.fixture(autouse=True)
def demo_autouse() -> None:
    """Autouse fixture. Shows AUTO + FIXTURE badges."""


@pytest.fixture
def demo_deprecated() -> str:
    """Return a value (deprecated since 1.0, replaced by :func:`demo_plain`).

    This fixture is documented with the ``deprecated`` RST option so the
    demo page can show the DEPRECATED + FIXTURE badge combination.
    """
    return "deprecated"


@pytest.fixture(scope="session")
def demo_session_factory() -> type[str]:
    """Session-scoped factory. Shows SESSION + FACTORY + FIXTURE badges."""
    return str


@pytest.fixture(scope="session", autouse=True)
def demo_session_autouse() -> None:
    """Session-scoped autouse. Shows SESSION + AUTO + FIXTURE badges."""
