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

Since this software is used by tens of thousands of users daily, we don't want
to release breaking changes. Additionally this is packaged on large Linux/BSD
distros, so we must be mindful of architectural changes.

Choose what the next version is. Assuming it's version 0.9.0, it could be:

- 0.9.0post0: postrelease, if there was a packaging issue
- 0.9.1: bugfix / security / tweak
- 0.10.0: breaking changes, new features

Let's assume we pick 0.9.1

`CHANGES`: Assure any PRs merged since last release are mentioned. Give a
thank you to the contributor. Set the header with the new version and the date.
Leave the "current" header and _Insert changes/features/fixes for next release here_ at
the top::

    current
    -------
    - *Insert changes/features/fixes for next release here*

    libtmux 0.9.1 (2020-10-12)
    --------------------------
    - :issue:`1`: Fix bug

`libtmux/__init__.py` and `__about__.py` - Set version

`git commit -m 'Tag v0.9.1'`

`git tag v0.9.1`

`pip install wheel twine`

`python setup.py sdist bdist_wheel`

`twine upload dist/*`

### Twine

`twine upload dist/*`

You will be asked for PyPI login information.

### Releasing with Poetry (hypothetical)

This isn't used yet since package maintainers may want setup.py in the source.
See https://github.com/tmux-python/tmuxp/issues/625.

As of 0.10, [poetry] handles virtualenv creation, package requirements, versioning,
building, and publishing. Therefore there is no setup.py or requirements files.

Update `__version__` in `__about__.py` and `pyproject.toml`::

    git commit -m 'build(libtmux): Tag v0.1.1'
    git tag v0.1.1
    git push
    git push --tags
    poetry build
    poetry deploy

[twine]: https://twine.readthedocs.io/
[poetry]: https://python-poetry.org/
[entr(1)]: http://eradman.com/entrproject/
[black]: https://github.com/psf/black
[isort]: https://pypi.org/project/isort/
[flake8]: https://flake8.pycqa.org/
