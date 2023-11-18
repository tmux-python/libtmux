# Development

[poetry] is a required package to develop.

```console
$ git clone https://github.com/tmux-python/libtmux.git
```

```console
$ cd libtmux
```

```console
$ poetry install -E "docs test coverage lint"
```

Makefile commands prefixed with `watch_` will watch files and rerun.

## Tests

`poetry run py.test`

Helpers: `make test`
Rerun tests on file change: `make watch_test` (requires [entr(1)])

### Pytest plugin

:::{seealso}

See {ref}`pytest_plugin`.

:::

## Documentation

Default preview server: http://localhost:8023

[sphinx-autobuild] will automatically build the docs, watch for file changes and launch a server.

From home directory: `make start_docs` From inside `docs/`: `make start`

[sphinx-autobuild]: https://github.com/executablebooks/sphinx-autobuild

### Manual documentation (the hard way)

`cd docs/` and `make html` to build. `make serve` to start http server.

Helpers: `make build_docs`, `make serve_docs`

Rebuild docs on file change: `make watch_docs` (requires [entr(1)])

Rebuild docs and run server via one terminal: `make dev_docs` (requires above, and a `make(1)` with
`-J` support, e.g. GNU Make)

## Linting

### ruff

The project uses [ruff] to handles formatting, sorting imports and linting.

````{tab} Command

poetry:

```console
$ poetry run ruff
```

If you setup manually:

```console
$ ruff .
```

````

````{tab} make

```console
$ make ruff
```

````

````{tab} Watch

```console
$ make watch_ruff
```

requires [`entr(1)`].

````

````{tab} Fix files

poetry:

```console
$ poetry run ruff . --fix
```

If you setup manually:

```console
$ ruff . --fix
```

````

#### ruff format

[ruff format] is used for formatting.

````{tab} Command

poetry:

```console
$ poetry run ruff format .
```

If you setup manually:

```console
$ ruff format .
```

````

````{tab} make

```console
$ make ruff_format
```

````

### mypy

[mypy] is used for static type checking.

````{tab} Command

poetry:

```console
$ poetry run mypy .
```

If you setup manually:

```console
$ mypy .
```

````

````{tab} make

```console
$ make mypy
```

````

````{tab} Watch

```console
$ make watch_mypy
```

requires [`entr(1)`].
````

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

```console
$ git commit -m 'Tag v0.9.1'
```

```console
$ git tag v0.9.1
```

After `git push` and `git push --tags`, CI will automatically build and deploy
to PyPI.

### Releasing with Poetry (manual)

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
[`entr(1)`]: http://eradman.com/entrproject/
[ruff format]: https://docs.astral.sh/ruff/formatter/
[ruff]: https://ruff.rs
[mypy]: http://mypy-lang.org/
