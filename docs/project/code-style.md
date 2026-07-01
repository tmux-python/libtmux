# Code Style

## Formatting

libtmux uses [ruff](https://github.com/astral-sh/ruff) for both linting and formatting.

```console
$ uv run ruff format .
```

```console
$ uv run ruff check . --fix --show-fixes
```

## Type Checking

Strict [mypy](https://mypy-lang.org/) is enforced across `src/` and `tests/`.

```console
$ uv run mypy
```

## Docstrings

All public functions and methods use NumPy-style docstrings. See the
[NumPy docstring guide](https://numpydoc.readthedocs.io/en/latest/format.html).

## Imports

- Standard library: namespace imports such as
  [`pathlib`](https://docs.python.org/3/library/pathlib.html) (`import pathlib`,
  not `from pathlib import Path`)
  - Exception: [`dataclasses`](https://docs.python.org/3/library/dataclasses.html)
    may use `from dataclasses import dataclass, field`
- [`typing`](https://docs.python.org/3/library/typing.html): `import typing as t`,
  access via
  [`t.Optional`](https://docs.python.org/3/library/typing.html#typing.Optional),
  [`t.NamedTuple`](https://docs.python.org/3/library/typing.html#typing.NamedTuple),
  etc.
- All files: `from __future__ import annotations`
