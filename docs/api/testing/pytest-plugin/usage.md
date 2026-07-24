(pytest_plugin_usage)=

# Usage Guide

libtmux provides [pytest] fixtures for tmux. The plugin automatically manages
setup and teardown of an independent tmux server.

```{seealso} Using the pytest plugin?

If the fixture defaults do not fit your test suite, [start a discussion] with
the use case before depending on undocumented behavior.

[start a discussion]: https://github.com/tmux-python/libtmux/discussions
```

## Usage

Install `libtmux` via the python package manager of your choosing, e.g.

```console
$ pip install libtmux
```

The plugin is automatically detected by [pytest], and the fixtures are added.

### Real world usage

View libtmux's own [tests](https://github.com/tmux-python/libtmux/tree/master/tests)
as well as [tmuxp]'s
[tests](https://github.com/tmux-python/tmuxp/tree/master/tests).

libtmux's tests `autouse` the {ref}`recommended-fixtures` above to ensure stable test execution, assertions and
object lookups in the test grid.

## pytest-driven tmux tests

[pytest-tmux] also works through {ref}`pytest fixtures <pytest:fixtures-api>`,
so the same fixture concepts apply.

The plugin's fixtures guarantee a fresh, headless {command}`tmux(1)` server, session, window, or pane is
passed into your test.

(recommended-fixtures)=

## Recommended fixtures

These fixtures are automatically used when the plugin is enabled and `pytest` is run.

- Creating temporary, test directories for:
  - `/home/` ({fixture}`home_path`)
  - `/home/${user}` ({fixture}`user_path`)
- Default `.tmux.conf` configuration with these settings ({fixture}`config_file`):

  - `base-index -g 1`

  These are set to ensure panes and windows can be reliably referenced and asserted.

(setting_a_tmux_configuration)=

## Setting a tmux configuration

If you would like {fixture}`session <libtmux.pytest_plugin.session>` to automatically use a configuration, you have a few
options:

- Pass a `config_file` into {class}`~libtmux.Server`
- Set the `HOME` directory to a local or temporary pytest path with a configuration file

You could also read the code and override {fixture}`server <libtmux.pytest_plugin.server>` in your own doctest.

(custom_session_params)=

### Custom session parameters

You can override {fixture}`session_params` to customize the `session` fixture. The
dictionary will directly pass into
{meth}`Server.new_session() <libtmux.Server.new_session>` keyword arguments.

```python
>>> import pytest
>>> @pytest.fixture
... def session_params() -> dict[str, int]:
...     return {"x": 800, "y": 600}
```

The above will assure the libtmux session launches with `-x 800 -y 600`.

(temp_server)=

### Creating temporary servers

If you need multiple independent tmux servers in your tests, the {fixture}`TestServer <libtmux.pytest_plugin.TestServer>` provides a factory that creates servers with unique socket names. Each server is automatically cleaned up when the test completes.

```python
>>> temp_server = Server()
>>> temp_session = temp_server.new_session()
>>> temp_server.is_alive()
True
>>> temp_server.kill()
```

You can also use it with custom configurations, similar to the {ref}`server fixture <setting_a_tmux_configuration>`:

```python
>>> config_path = request.getfixturevalue("tmp_path") / "tmux.conf"
>>> _ = config_path.write_text("set -g status off")
>>> configured_server = Server(config_file=str(config_path))
>>> _ = configured_server.new_session()
>>> configured_server.is_alive()
True
>>> configured_server.kill()
```

This is particularly useful when testing interactions between multiple tmux servers or when you need to verify behavior across server restarts.

(set_home)=

### Setting a temporary home directory

```python
>>> import pathlib
>>> import pytest
>>> @pytest.fixture(autouse=True, scope="function")
... def set_home(
...     monkeypatch: pytest.MonkeyPatch,
...     user_path: pathlib.Path,
... ) -> None:
...     monkeypatch.setenv("HOME", str(user_path))
```

## Selecting tmux engines (experimental)

Fixtures can run against different execution engines. By default the
`subprocess` engine is used. You can choose control mode globally:

```console
$ pytest --engine=control
```

Or per-test via the `engines` marker (uses parametrization) and the `engine_name`
fixture:

```python
import pytest

@pytest.mark.engines(["subprocess", "control"])
def test_my_flow(server, engine_name):
    # server uses the selected engine, engine_name reflects the current one
    assert engine_name in {"subprocess", "control"}
    assert server.is_alive()
```

`TestServer` also respects the selected engine. Control mode is experimental and
its APIs may change between releases.

### Control sandbox fixture (experimental)

Use ``control_sandbox`` when you need a hermetic control-mode server for a test:

```python
import typing as t
import pytest
from libtmux.server import Server

@pytest.mark.engines(["control"])
def test_control_sandbox(control_sandbox: t.ContextManager[Server]):
    with control_sandbox as server:
        session = server.new_session(session_name="sandbox", attach=False)
        out = server.cmd("display-message", "-p", "hi")
        assert out.stdout == ["hi"]
```

The fixture:
- Spins up a unique socket name and isolates ``HOME`` / ``TMUX_TMPDIR``
- Clears inherited ``TMUX`` so it never attaches to the user's server
- Uses ``ControlModeEngine`` and cleans up the server on exit

[pytest]: https://docs.pytest.org/en/stable/
[pytest-tmux]: https://pytest-tmux.readthedocs.io/
[tmuxp]: https://tmuxp.git-pull.com/
