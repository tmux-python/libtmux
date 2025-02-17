# Development

Install [git] and [uv]

Clone:

```console
$ git clone https://github.com/tmux-python/libtmux.git
```

```console
$ cd libtmux
```

Install packages:

```console
$ uv sync --all-extras --dev
```

[installation documentation]: https://docs.astral.sh/uv/getting-started/installation/
[git]: https://git-scm.com/
[uv]: https://github.com/astral-sh/uv

Makefile commands prefixed with `watch_` will watch files and rerun.

## Tests

```console
$ uv run py.test
```

### Helpers

```console
$ make test
```

Rerun tests on file change:

```console
$ make watch_test
```

(requires [entr(1)])

### Pytest plugin

:::{seealso}

See {ref}`pytest_plugin`.

:::

## Documentation

Default preview server: http://localhost:8023

[sphinx-autobuild] will automatically build the docs, watch for file changes and launch a server.

From home directory:
```console
$ make start_docs
```

From inside `docs/`:
```console
$ make start
```

[sphinx-autobuild]: https://github.com/executablebooks/sphinx-autobuild

### Manual documentation (the hard way)

```console
$ cd docs/
$ make html
```

to build.

```console
$ make serve
```

to start http server.

Helpers:
```console
$ make build_docs
$ make serve_docs
```

Rebuild docs on file change:
```console
$ make watch_docs
```
(requires [entr(1)])

Rebuild docs and run server via one terminal:
```console
$ make dev_docs
```
(requires above, and {command}`make(1)` with
`-J` support, e.g. GNU Make)

## Linting

### ruff

The project uses [ruff] to handle formatting, sorting imports and linting.

````{tab} Command

uv:

```console
$ uv run ruff
```

If you setup manually:

```console
$ ruff check .
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

requires [entr(1)].

````

````{tab} Fix files

uv:

```console
$ uv run ruff check . --fix
```

If you setup manually:

```console
$ ruff check . --fix
```

````

#### ruff format

[ruff format] is used for formatting.

````{tab} Command

uv:

```console
$ uv run ruff format .
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

uv:

```console
$ uv run mypy .
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

requires [entr(1)].
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
the top:

```
current
-------
- *Insert changes/features/fixes for next release here*

libtmux 0.9.1 (2020-10-12)
--------------------------
- :issue:`1`: Fix bug
```

`libtmux/__init__.py` and `__about__.py` - Set version

```console
$ git commit -m 'Tag v0.9.1'
```

```console
$ git tag v0.9.1
```

After `git push` and `git push --tags`, CI will automatically build and deploy
to PyPI.

### Releasing via GitHub Actions (manual)

This isn't used yet since package maintainers may want setup.py in the source.
See https://github.com/tmux-python/tmuxp/issues/625.

As of v0.10, [uv] handles virtualenv creation, package requirements, versioning,
building, and publishing. Therefore there is no setup.py or requirements files.

Update `__version__` in `__about__.py` and `pyproject.toml`:

```console
git commit -m 'build(libtmux): Tag v0.1.1'
git tag v0.1.1
git push
git push --tags
```

[twine]: https://twine.readthedocs.io/
[uv]: https://github.com/astral-sh/uv
[entr(1)]: http://eradman.com/entrproject/
[ruff format]: https://docs.astral.sh/ruff/formatter/
[ruff]: https://ruff.rs
[mypy]: http://mypy-lang.org/
