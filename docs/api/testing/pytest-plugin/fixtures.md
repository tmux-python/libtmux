(pytest_plugin_fixtures)=

# Fixture Reference

## Environment and Path Fixtures

Session-scoped fixtures that create isolated filesystem environments.
Shared across all tests in a session.

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.home_path
.. autofixture:: libtmux.pytest_plugin.home_user_name
.. autofixture:: libtmux.pytest_plugin.user_path
.. autofixture:: libtmux.pytest_plugin.zshrc
.. autofixture:: libtmux.pytest_plugin.config_file
```

## Hygiene Fixtures

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.clear_env
```

## Core tmux Object Fixtures

The primary injection points. Request `server` or `session` in any test function:

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.server
.. autofixture:: libtmux.pytest_plugin.session
```

## Customization and Factories

```{eval-rst}
.. autofixture:: libtmux.pytest_plugin.session_params
.. autofixture:: libtmux.pytest_plugin.TestServer
```
