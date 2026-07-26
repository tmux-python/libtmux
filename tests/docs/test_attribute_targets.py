"""Sphinx target hygiene for dataclass ``Attributes`` sections."""

from __future__ import annotations

import dataclasses
import pathlib
import pydoc
import re
import typing as t

from sphinx.ext.napoleon.docstring import NumpyDocstring

DOCS_ROOT = pathlib.Path(__file__).parents[2] / "docs"
AUTOCLASS = re.compile(r"^\.\. autoclass:: (?P<target>\S+)$")


def _declares_attributes(value: type[object]) -> bool:
    """Return whether *value* owns a NumPy ``Attributes`` entry."""
    docstring = t.cast(str | None, value.__dict__.get("__doc__"))
    return any(
        line.startswith(".. attribute:: ")
        for line in NumpyDocstring(docstring or "").lines()
    )


def _autoclass_blocks(path: pathlib.Path) -> t.Iterator[tuple[str, set[str]]]:
    """Yield autoclass targets and their explicit options from *path*."""
    lines = path.read_text().splitlines()
    for index, line in enumerate(lines):
        match = AUTOCLASS.match(line)
        if match is None:
            continue
        options: set[str] = set()
        for candidate in lines[index + 1 :]:
            if candidate and not candidate[0].isspace():
                break
            stripped = candidate.strip()
            if stripped.startswith(":") and stripped.endswith(":"):
                options.add(stripped)
        yield match.group("target"), options


def test_dataclass_attributes_are_not_registered_twice() -> None:
    """Authored attributes replace autodoc's bare member copies."""
    missing_option: list[str] = []
    for path in sorted((*DOCS_ROOT.rglob("*.md"), *DOCS_ROOT.rglob("*.rst"))):
        if "_build" in path.relative_to(DOCS_ROOT).parts:
            continue
        for target, options in _autoclass_blocks(path):
            value = pydoc.locate(target)
            if (
                isinstance(value, type)
                and dataclasses.is_dataclass(value)
                and _declares_attributes(value)
                and ":no-undoc-members:" not in options
            ):
                relative = path.relative_to(DOCS_ROOT)
                missing_option.append(f"{relative}: {target}")

    assert not missing_option, (
        "Dataclasses with Attributes sections need :no-undoc-members: "
        f"to avoid duplicate Sphinx targets: {missing_option}"
    )
