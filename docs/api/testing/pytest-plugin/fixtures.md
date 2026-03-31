(pytest_plugin_fixtures)=

# Fixtures

## Quick Start

Add a fixture name as a test parameter — pytest creates and injects it automatically. You never call fixtures yourself.

```python
def test_basic(server: Server) -> None:
    session = server.new_session(session_name="my-session")
    assert session is not None


def test_with_session(session: Session) -> None:
    window = session.new_window(window_name="test")
    assert window is not None
```

## Fixture Index

| Fixture | Scope | Kind | Returns |
|---|---|---|---|
| {fixture}`libtmux.pytest_plugin.home_path` | session | resource | `Path` |
| {fixture}`libtmux.pytest_plugin.home_user_name` | session | override\_hook | `str` |
| {fixture}`libtmux.pytest_plugin.user_path` | session | resource | `Path` |
| {fixture}`libtmux.pytest_plugin.config_file` | session | resource | `Path` |
| {fixture}`libtmux.pytest_plugin.zshrc` | session | resource | `Path` |
| {fixture}`libtmux.pytest_plugin.server` | function | resource | `Server` |
| {fixture}`libtmux.pytest_plugin.session` | function | resource | `Session` |
| {fixture}`libtmux.pytest_plugin.session_params` | function | override\_hook | `dict` |
| {fixture}`libtmux.pytest_plugin.TestServer` | function | factory | `type[Server]` |
| {fixture}`libtmux.pytest_plugin.clear_env` | function | resource | `None` |

---

## Core tmux Objects

The primary injection points for libtmux tests.

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.server

.. autofixture:: libtmux.pytest_plugin.session
```

## Environment & Paths

Session-scoped fixtures that create an isolated filesystem environment.
Shared across all tests in a session — created once, reused everywhere.

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.home_path

.. autofixture:: libtmux.pytest_plugin.user_path

.. autofixture:: libtmux.pytest_plugin.config_file

.. autofixture:: libtmux.pytest_plugin.zshrc
```

## Override Hooks

Override these in your project's `conftest.py` to customise the test environment.

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.home_user_name

.. autofixture:: libtmux.pytest_plugin.session_params
```

## Factories

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.TestServer
```

## Hygiene

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.clear_env
```
