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

## Which Fixture Do I Need?

- Use {fixture}`session` when you want a ready-to-use tmux session.
- Use {fixture}`server` when you want a bare server and will create sessions yourself.
- Use {fixture}`TestServer` when you need multiple isolated servers in one test.
- Override {fixture}`session_params` when you need custom session creation.
- Override {fixture}`home_user_name` when you need a custom test user.
- Request {fixture}`clear_env` when testing tmux behavior with a minimal environment.

## Fixture Index

| Fixture | Scope | Kind | Returns | Description |
|---|---|---|---|---|
| {fixture}`home_path` | session | resource | `Path` | Temporary `/home/` path |
| {fixture}`home_user_name` | session | override\_hook | `str` | Default username for `user_path` |
| {fixture}`user_path` | session | resource | `Path` | Temporary user home directory |
| {fixture}`config_file` | session | resource | `Path` | Default `.tmux.conf` with `base-index 1` |
| {fixture}`zshrc` | session | resource | `Path` | Empty `.zshrc` to suppress ZSH message |
| {fixture}`server` | function | resource | {class}`~libtmux.Server` | Fresh tmux server per test |
| {fixture}`session` | function | resource | {class}`~libtmux.Session` | Temporary tmux session |
| {fixture}`session_params` | function | override\_hook | `dict` | Override to customize session creation |
| {fixture}`TestServer` | function | factory | `type[Server]` | Factory for independent tmux servers |
| {fixture}`clear_env` | function | resource | `None` | Strips non-essential env vars |

---

## Core Fixtures

The primary injection points for libtmux tests.

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.server

   .. rubric:: Example

   .. code-block:: python

      def test_server_sessions(server: Server) -> None:
          session = server.new_session(session_name="work")
          assert session.session_name == "work"

.. autofixture:: libtmux.pytest_plugin.session

   .. rubric:: Example

   .. code-block:: python

      def test_session_windows(session: Session) -> None:
          window = session.new_window(window_name="editor")
          assert window.window_name == "editor"
```

## Environment Fixtures

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
   :kind: override_hook

.. autofixture:: libtmux.pytest_plugin.session_params
   :kind: override_hook

   .. rubric:: Example

   .. code-block:: python

      # conftest.py
      @pytest.fixture
      def session_params() -> dict:
          return {"x": 800, "y": 600}
```

## Factories

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.TestServer
```

## Low-Level / Rarely Needed

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.clear_env
```

---

## Configuration

These `conf.py` values control how fixture documentation is rendered:

```{eval-rst}
.. confval:: pytest_fixture_hidden_dependencies

   Fixture names to suppress from "Depends on" lists. Default: common pytest
   builtins (:external+pytest:std:fixture:`pytestconfig`,
   :external+pytest:std:fixture:`capfd`,
   :external+pytest:std:fixture:`capsysbinary`,
   :external+pytest:std:fixture:`capfdbinary`,
   :external+pytest:std:fixture:`recwarn`,
   :external+pytest:std:fixture:`tmpdir`,
   :external+pytest:std:fixture:`pytester`,
   :external+pytest:std:fixture:`testdir`,
   :external+pytest:std:fixture:`record_property`,
   ``record_xml_attribute``,
   :external+pytest:std:fixture:`record_testsuite_property`,
   :external+pytest:std:fixture:`cache`).

.. confval:: pytest_fixture_builtin_links

   URL mapping for builtin fixture external links in "Depends on" blocks.
   Default: links to pytest docs for
   :external+pytest:std:fixture:`tmp_path_factory`,
   :external+pytest:std:fixture:`tmp_path`,
   :external+pytest:std:fixture:`monkeypatch`,
   :external+pytest:std:fixture:`request`,
   :external+pytest:std:fixture:`capsys`,
   :external+pytest:std:fixture:`caplog`.

.. confval:: pytest_external_fixture_links

   URL mapping for external fixture cross-references. Default: ``{}``.
```

---

```{note}
All fixtures above are also auto-discoverable via:

    .. autofixtures:: libtmux.pytest_plugin
       :order: source

Use ``autofixtures::`` in your own plugin docs to document all fixtures from a
module without listing each one manually.
```
