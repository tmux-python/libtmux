(examples)=

# Examples

`examples/` in the repository root holds standalone scripts you run
directly, with tmux on `PATH` and no existing session required:

```console
$ python examples/quickstart.py
```

Each one owns its own {class}`~libtmux.Server` via
{meth}`~libtmux.Server.owned`, so running it never touches a session you
already have open on your default socket. The suite executes every script
under `examples/` as its own subprocess (`tests/test_examples.py`), so an
example that stops running is a test failure, not a stale file.

You can stop after `quickstart.py` for the object hierarchy itself. The rest
cover one topic each, in the order most readers reach for them.

## Quickstart

`quickstart.py` walks {class}`~libtmux.Server` →
{class}`~libtmux.Session` → {class}`~libtmux.Window` →
{class}`~libtmux.Pane`: create a session, send a command, and read back its
output.

```{literalinclude} ../../examples/quickstart.py
:language: python
```

## Command results

`command_results.py` runs tmux directly with
{func}`~libtmux.common.run_command`, for a one-off query or diagnostic where
you don't need an object to hold onto afterward.

```{literalinclude} ../../examples/command_results.py
:language: python
```

## Owned scopes

`owned_scopes.py` contrasts {meth}`~libtmux.Server.owned` (a private daemon
for the block) with {meth}`~libtmux.Server.owned_session` (one session on a
server you already hold). See {doc}`context_managers` for the cleanup rules
behind both.

```{literalinclude} ../../examples/owned_scopes.py
:language: python
```

## Resilient automation

`resilient_automation.py` bounds a call with a timeout and catches
{exc}`~libtmux.exc.TmuxTimeout`, then verifies a pane's decoded
{attr}`~libtmux.Pane.is_dead` instead of assuming a command finished because
nothing raised. See {doc}`automation_patterns` for the fuller pattern
catalog this is drawn from.

```{literalinclude} ../../examples/resilient_automation.py
:language: python
```

## Polling for changes

`polling_for_changes.py` answers a question the other examples sidestep:
how do you notice a change without an event stream? libtmux has none --
{attr}`~libtmux.Session.windows` re-queries tmux on every access, so polling
it is the supported answer. See {doc}`public-vs-internal` for why this is
the answer rather than the internal `ControlMode` test client.

```{literalinclude} ../../examples/polling_for_changes.py
:language: python
```
