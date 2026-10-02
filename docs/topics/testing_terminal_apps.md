(testing-terminal-apps)=

# Testing terminal apps

A terminal app is tested by what it draws. libtmux's [pytest] plugin gives each
test a private tmux server, so the test types into a pane and asserts on the
screen the app produced. Three pieces keep that reliable: a shell that looks
the same on every machine, an assertion that waits for the screen to settle,
and, when a test fails, the command that attaches to the screen it saw.

If you already use the {fixture}`session` fixture, you need only the middle
piece. The other two are opt-in or only act on failure.

## A shell that looks the same everywhere

A pane runs your login shell, so a themed prompt or an `rc` file changes every
line the test captures. Mark the test `deterministic_shell` and its pane runs
bash with no startup files, an empty environment apart from `PATH`,
`TERM=xterm-256color`, and the prompt `$ `. Unmarked tests keep the default
shell. See {ref}`deterministic_shell` for the arguments and for use outside
pytest.

## Waiting for the screen

An app draws after the keys are sent, so a single
{meth}`~libtmux.Pane.capture_pane` races it.
{func}`~libtmux.test.screen.assert_screen` captures again until the screen
equals what you expect or the timeout passes, then raises with a line diff.
`row` narrows the check to one line and `contains` matches a substring.

This test starts a one-line program, answers its prompt, and checks the whole
screen:

```python
>>> import subprocess, sys, textwrap
>>> test_dir = request.getfixturevalue("tmp_path")
>>> _ = (test_dir / "test_greeter.py").write_text(textwrap.dedent('''
... import pytest
... from libtmux.test.screen import assert_screen
...
... @pytest.mark.deterministic_shell
... def test_greeter(session):
...     pane = session.active_pane
...     pane.send_keys('read -p "name? " n; echo "hello $n"')
...     assert_screen(pane, "name?", contains=True)
...     pane.send_keys("tony")
...     assert_screen(pane, """\\
... $ read -p "name? " n; echo "hello $n"
... name? tony
... hello tony
... $""")
... '''))
>>> run = subprocess.run(
...     [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
...     cwd=test_dir,
...     capture_output=True,
...     text=True,
... )
>>> run.stdout.splitlines()[-1].split(" in ")[0]
'1 passed'
```

Each retry is a `capture-pane` round trip, so a long timeout costs time only
when the screen never matches. `timeout` defaults to `RETRY_TIMEOUT_SECONDS`
and `interval` to `RETRY_INTERVAL_SECONDS`; `timeout=0` captures once.

To write `assert pane_screen == text` instead, wrap the pane with
{func}`~libtmux.test.screen.eventually`. Its `==`, `!=`, and `in` retry the same
way, and under pytest a failed comparison prints the same diff. See
{ref}`screen_assertions`.

## Looking at a failed screen

When a test fails, the report names the command that attaches to its tmux
server:

```text
----------------------------- libtmux -----------------------------
Attach to the tmux server this test used:
  tmux -S /tmp/tmux-1000/libtmux_test8abtrukf attach -t libtmux_7afb0whg ';' resize-window -x 80 -y 24
```

Passing tests print nothing. The fixture finalizer kills the server when the
test ends, so by default the command works only while pytest is still running,
such as under `--pdb`. Run with `--libtmux-keep-failed` to leave a failed
test's server running; the report then adds the `kill-server` command that
stops it. See {ref}`attach_to_failed_test`.

Here a deliberately wrong assertion fails, and the report carries both
commands:

```python
>>> import shlex, subprocess, sys, textwrap
>>> test_dir = request.getfixturevalue("tmp_path")
>>> _ = (test_dir / "test_wrong.py").write_text(textwrap.dedent('''
... from libtmux.test.screen import assert_screen
...
... def test_wrong(session):
...     assert_screen(session.active_pane, "never shown", timeout=0)
... '''))
>>> run = subprocess.run(
...     [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
...      "--libtmux-keep-failed"],
...     cwd=test_dir,
...     capture_output=True,
...     text=True,
... )
>>> report = run.stdout.splitlines()
>>> any(" attach -t libtmux_" in line for line in report)
True
>>> kill = next(line for line in report if line.endswith(" kill-server"))
>>> subprocess.run(shlex.split(kill), check=True).returncode
0
```

[pytest]: https://docs.pytest.org/en/stable/
