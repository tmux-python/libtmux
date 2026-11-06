# Create or reuse a session

Use {meth}`~libtmux.Server.find_or_create_session` when either an existing session
or a new one is acceptable. The result tells you which happened and holds
cleanup responsibility only for a session it created.

```python
>>> acquired = server.find_or_create_session("build", window_command="cat")
>>> acquired.created
True
>>> reused = server.reuse_session("build")
>>> reused.created, reused.value.session_id == acquired.value.session_id
(False, True)
>>> reused.close()
>>> server.has_session("build")
True
>>> acquired.close()
>>> server.has_session("build")
False
```

{meth}`~libtmux.Server.create_session` requires a new session and raises
{exc}`~libtmux.exc.TmuxSessionExists` if the name already exists.
{meth}`~libtmux.Server.reuse_session` requires an existing session and raises
{exc}`~libtmux.exc.ObjectDoesNotExist` when it is absent. Names match literally;
prefixes, format expansion, and tmux target expressions are not accepted.
Periods, colons, and control characters are invalid in these names.

The optional directory, window name, command, and environment settings apply
only during creation. Reuse leaves the existing session and programs untouched.
These methods require tmux 3.2a or later and the stock native dispatcher; custom
command dispatchers and injected engines are refused before any effects.

## Clean up a creation

The result's context returns an ordinary {class}`~libtmux.Session`. Leaving the
context closes only a session created by that acquisition, including when the
body raises an exception.

```python
>>> with server.create_session("temporary", window_command="cat") as temporary:
...     temporary.session_name
'temporary'
>>> server.has_session("temporary")
False
```

Call {meth}`~libtmux.FoundOrCreated.preserve` to keep a created session after
releasing this result's cleanup responsibility. Its {attr}`~libtmux.FoundOrCreated.created`
flag still records what happened during acquisition.

```python
>>> result = server.create_session("keep", window_command="cat")
>>> kept = result.preserve()
>>> result.close()
>>> server.has_session("keep")
True
>>> kept.kill()
```

{meth}`~libtmux.FoundOrCreated.close` is idempotent after successful cleanup and
does nothing for reused or preserved results. Cleanup preserves other sessions
and their programs. If the removed session was the daemon's last session,
tmux's normal `exit-empty` behavior may stop that daemon.

## Identity and failures

{attr}`~libtmux.FoundOrCreated.identity` is a frozen record of the selected socket,
connected daemon version, PID, start time, and session ID. A created result also
retains the random nonce installed in that session's `LIBTMUX_SESSION_OWNER`
environment entry by the creation command. That entry is reserved; altering it
causes cleanup to refuse the session. It is not a security boundary against
clients with access to the daemon.

Reused sessions have `creation_token=None` and `incarnation_verified=None`.
Their PID and start time are observations, not a globally unique daemon identity.
Reuse does not install metadata or acquire cleanup authority. A result's
{attr}`~libtmux.FoundOrCreated.value` remains an ordinary live session handle,
with the usual possibility of becoming stale after external changes.

Cleanup uses the acquisition's captured executable, endpoint, environment, and
working directory. One native command queue checks the daemon observations,
exact session ID, and creation nonce before destroying that session. A deleted
session on the observed daemon closes successfully. An unreachable daemon,
replacement, or changed nonce raises an error instead of authorizing destruction.

After an exact duplicate-session creation conflict,
{meth}`~libtmux.Server.find_or_create_session` makes one reconciliation lookup.
Other native errors retain their raw subprocess cause. Transport errors propagate
without retry. A submitted operation without a trustworthy creation receipt has
an unknown outcome; the library neither retries creation nor destroys by name.
These calls use blocking native subprocesses and do not provide a deadline.

A failure after a trustworthy creation receipt triggers cleanup of only that
creation. If cleanup also fails, {exc}`~libtmux.exc.CreationCleanupError` retains
`operation_error`, `cleanup_error`, and `owner` for inspection or explicit retry.
The same rule applies when both a context body and its cleanup fail.

Window and pane builders, globally strong borrowed-resource identities, leases,
and finalizer or signal cleanup remain outside this session API.

## Result types

```{eval-rst}
.. autoclass:: libtmux.FoundOrCreated
   :members:

.. autoclass:: libtmux.SessionIdentity
   :members:
```
