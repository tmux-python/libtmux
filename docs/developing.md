# Development

[poetry] is a required package to develop.

`git clone https://github.com/tmux-python/libtmux.git`

`cd libtmux`

`poetry install -E "docs test coverage lint format"`

Makefile commands prefixed with `watch_` will watch files and rerun.

## Tests

`poetry run py.test`

Helpers: `make test`
Rerun tests on file change: `make watch_test` (requires [entr(1)])

## Documentation

Default preview server: http://localhost:8023

`cd docs/` and `make html` to build. `make serve` to start http server.

Helpers:
`make build_docs`, `make serve_docs`

Rebuild docs on file change: `make watch_docs` (requires [entr(1)])

Rebuild docs and run server via one terminal: `make dev_docs` (requires above, and a
`make(1)` with `-J` support, e.g. GNU Make)

## Formatting / Linting

The project uses [black] and [isort] (one after the other) and runs [flake8] via
CI. See the configuration in `pyproject.toml` and `setup.cfg`:

`make black isort`: Run `black` first, then `isort` to handle import nuances
`make flake8`, to watch (requires `entr(1)`): `make watch_flake8`

## Releasing

As of 0.10, [poetry] handles virtualenv creation, package requirements, versioning,
building, and publishing. Therefore there is no setup.py or requirements files.

Update `__version__` in `__about__.py` and `pyproject.toml`::

    git commit -m 'build(libtmux): Tag v0.1.1'
    git tag v0.1.1
    git push
    git push --tags
    poetry build
    poetry deploy

[poetry]: https://python-poetry.org/
[entr(1)]: http://eradman.com/entrproject/
[black]: https://github.com/psf/black
[isort]: https://pypi.org/project/isort/
[flake8]: https://flake8.pycqa.org/
