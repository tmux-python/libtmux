(pytest_plugin_fixtures)=

# Fixtures

## Quick Start

Add a fixture name as a test parameter — [pytest] creates and injects it
automatically. You never call fixtures yourself. In doctests, libtmux injects
the same objects through `doctest_namespace`:

```python
>>> created_session = server.new_session(session_name="my-session")
>>> created_session is not None
True
>>> created_session.kill()

>>> created_window = session.new_window(window_name="test")
>>> created_window is not None
True
>>> created_window.kill()
```

## Which Fixture Do I Need?

- Use {fixture}`session` when you want a ready-to-use tmux session.
- Use {fixture}`server` when you want a bare server and will create sessions yourself.
- Use {fixture}`TestServer` when you need multiple isolated servers in one test.
- Override {fixture}`session_params` when you need custom session creation.
- Override {fixture}`home_user_name` when you need a custom test user.
- Request {fixture}`clear_env` when testing tmux behavior with a minimal environment.

## Fixture Summary

| Fixture | Use |
|---------|-----|
| {fixture}`server` | Bare isolated server |
| {fixture}`session` | Ready-to-use isolated session |
| {fixture}`home_path` / {fixture}`user_path` | Temporary home directories |
| {fixture}`config_file` | Test `.tmux.conf` |
| {fixture}`session_params` | Session creation override |
| {fixture}`TestServer` | Factory for extra isolated servers |
| {fixture}`control_mode` | Attached client factory |
| {fixture}`clear_env` | Minimal test environment |

---

## Core Fixtures

The primary injection points for libtmux tests.

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.server

.. autofixture:: libtmux.pytest_plugin.session
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

```

## Factories

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.TestServer

.. autofixture:: libtmux.pytest_plugin.control_mode

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

[pytest]: https://docs.pytest.org/en/stable/
