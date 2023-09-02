(pytest_plugin)=

# tmux `pytest` plugin

libtmux provides pytest fixtures for tmux. The plugin automatically manages setup and teardown of an
independent tmux server.

```{seealso} Using the pytest plugin?

Do you want more flexbility? Correctness? Power? Defaults changed? [Connect with us] on the tracker, we want to know
your case, we won't stabilize APIs until we're sure everything is by the book.

[connect with us]: https://github.com/tmux-python/libtmux/discussions

```

```{module} libtmux.pytest_plugin

```

## Usage

Install `libtmux` via the python package manager of your choosing, e.g.

```console
$ pip install libtmux
```

The pytest plugin will be automatically detected via pytest, and the fixtures will be added.

### Real world usage

View libtmux's own [tests/](https://github.com/tmux-python/libtmux/tree/master/tests) as well as
tmuxp's [tests/](https://github.com/tmux-python/tmuxp/tree/master/tests).

libtmux's tests `autouse` the {ref}`recommended-fixtures` above to ensure stable, assertions and
object lookups in the test grid.

## pytest-tmux

`pytest-tmux` works through providing {ref}`pytest fixtures <pytest:fixtures-api>` - so read up on
those!

The plugin's fixtures guarantee a fresh, headless `tmux(1)` server, session, window, or pane is
passed into your test.

(recommended-fixtures)=

## Recommended fixtures

These are fixtures are automatically used when the plugin is enabled and `pytest` is ran.

- Creating temporary, test directories for:
  - `/home/` ({func}`home_path`)
  - `/home/${user}` ({func}`user_path`)
- Default `.tmux.conf` configuration with these settings ({func}`config_file`):

  - `base-index -g 1`

  These are set to ensure panes and windows can be reliably referenced and asserted.

## Setting a tmux configuration

If you would like {func}`session fixture <libtmux.pytest_plugin.session>` to automatically use a configuration, you have a few
options:

- Pass a `config_file` into {class}`~libtmux.Server`
- Set the `HOME` directory to a local or temporary pytest path with a configurat configuration file

You could also read the code and override {func}`server fixtures <libtmux.pytest_plugin.server>`'s in your own doctest. doctest.

(custom_session_params)=

### Custom session parameters

You can override `session_params` to custom the `session` fixture. The
dictionary will directly pass into :meth:`Server.new_session` keyword arguments.

```python
import pytest

@pytest.fixture
def session_params():
    return {
        'x': 800,
        'y': 600
    }


def test_something(session):
    assert session
```

The above will assure the libtmux session launches with `-x 800 -y 600`.

(set_home)=

### Setting a temporary home directory

```python
import pathlib
import pytest

@pytest.fixture(autouse=True, scope="function")
def set_home(
    monkeypatch: pytest.MonkeyPatch,
    user_path: pathlib.Path,
):
    monkeypatch.setenv("HOME", str(user_path))
```

## Fixtures

```{eval-rst}
.. automodule:: libtmux.pytest_plugin
    :members:
    :inherited-members:
    :private-members:
    :show-inheritance:
    :member-order: bysource
```

## Test utilities

```{toctree}
:maxdepth: 1

test
```
