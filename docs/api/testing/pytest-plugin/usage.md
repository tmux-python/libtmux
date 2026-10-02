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

(attach_to_failed_test)=

## Attaching to a failed test

When a test that uses {fixture}`server` or {fixture}`session` fails, the
failure report gains a `libtmux` section with the command that attaches to
that test's private tmux server. Passing tests print nothing.

```text
----------------------------------- libtmux ------------------------------------
Attach to the tmux server this test used:
  tmux -S /tmp/tmux-1000/libtmux_test8abtrukf attach -t libtmux_7afb0whg ';' resize-window -x 80 -y 24
```

The command names the socket by path, so it works from any shell. The trailing
`resize-window` restores the window to the size the test saw, which attaching
from a larger terminal would otherwise change.

By default the fixture finalizer kills the server as soon as the test ends, so
the command only works while pytest is still running, for example under a
debugger. Pass `--libtmux-keep-failed` to leave the server of each failed test
running. The report then adds the `kill-server` command that stops it:

```console
$ pytest --libtmux-keep-failed
```

(deterministic_shell)=

## A deterministic shell

By default a test's panes run your login shell, so the prompt, `TERM`, and
environment come from the machine: a themed prompt changes every line the test
captures. Mark a test, class, or module with `deterministic_shell` to start the
{fixture}`session` fixture's shell through
{func}`~libtmux.test.shell.deterministic_shell_command` instead: bash with no
startup files, an empty environment apart from `PATH`, `TERM=xterm-256color`,
and the prompt `$ `. Unmarked tests keep the default shell.

```python
>>> source = """
... import pytest
...
... @pytest.mark.deterministic_shell
... def test_clean_shell(session):
...     pane = session.active_pane
...     command = pane.cmd("display-message", "-p", "#{pane_start_command}")
...     assert "env -i" in "".join(command.stdout)
... """
>>> import subprocess, sys  # doctest: +HIDE
>>> test_dir = request.getfixturevalue("tmp_path")  # doctest: +HIDE
>>> _ = (test_dir / "test_shell.py").write_text(source)  # doctest: +HIDE
>>> run = subprocess.run(  # doctest: +HIDE
...     [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
...     cwd=test_dir,
...     capture_output=True,
...     text=True,
... )
>>> run.returncode, run.stdout.splitlines()[-1].split(" in ")[0]  # doctest: +HIDE
(0, '1 passed')
```

The marker takes the keyword arguments of the function (`ps1`, `term`,
`inherit`). It applies only to the `session` fixture, and an explicit
`window_command` from {fixture}`session_params` wins. Outside pytest, or for
sessions you create yourself, pass the command to `window_command`:

```python
>>> from libtmux.test.shell import deterministic_shell_command
>>> clean = server.new_session(
...     session_name="clean",
...     window_command=deterministic_shell_command(ps1="> "),
... )
```

(screen_assertions)=

## Asserting on the screen

A terminal app draws asynchronously, so a test that captures a pane once
races the app. {func}`~libtmux.test.screen.assert_screen` captures the pane
again until the screen matches or the timeout passes, then raises with a line
diff of what the screen held. It needs no fixture and works outside pytest.

```python
>>> from libtmux.test.screen import assert_screen
>>> pane = session.new_window(
...     window_shell="printf 'hello\\nworld\\n'; cat",
... ).active_pane
>>> assert_screen(pane, "hello\nworld")
>>> assert_screen(pane, "wor", row=1, contains=True)
```

`row` compares one captured line, counted from 0; `contains` matches a
substring instead of the whole text. `timeout` defaults to
`RETRY_TIMEOUT_SECONDS` and `interval` to `RETRY_INTERVAL_SECONDS`; `timeout=0`
captures once. Each retry is a `capture-pane` round trip, so a long timeout
costs time only when the screen never matches.

For the `assert screen == text` style, {func}`~libtmux.test.screen.eventually`
returns an object whose `==`, `!=`, and `in` retry the same way. Under pytest a
failed comparison prints the same diff:

```python
>>> from libtmux.test.screen import eventually
>>> pane = session.new_window(
...     window_shell="printf 'hello\\nworld\\n'; cat",
... ).active_pane
>>> assert eventually(pane, row=0) == "hello"
>>> assert "world" in eventually(pane)
>>> assert eventually(pane, row=1) != "hello"
```

[pytest]: https://docs.pytest.org/en/stable/
[pytest-tmux]: https://pytest-tmux.readthedocs.io/
[tmuxp]: https://tmuxp.git-pull.com/
