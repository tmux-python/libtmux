---
myst:
  html_meta:
    description: "Getting started with libtmux pytest plugin for tmux testing"
    keywords: "tmux, pytest, plugin, getting started, installation"
---

(getting_started)=

# Getting Started

## Installation

The libtmux pytest plugin is included when you install the libtmux package:

```{code-block} console
$ pip install libtmux
```

No additional configuration is needed as pytest will automatically detect and register the plugin.

## Prerequisites

The plugin requires:

- Python 3.7+
- pytest 6.0+
- tmux 2.8+

## Basic usage

Here's a simple example of using the plugin in your tests:

```python
def test_basic_tmux_functionality(session):
    """Test basic tmux functionality using the session fixture."""
    # The session fixture provides a fresh tmux session
    assert session.is_alive()
    
    # Create a new window in the session
    window = session.new_window(window_name="test-window")
    assert window.window_name == "test-window"
    
    # Send commands to the active pane
    pane = window.active_pane
    pane.send_keys("echo 'Hello from tmux!'", enter=True)
    
    # Give the command time to execute
    import time
    time.sleep(0.5)
    
    # Capture and verify the output
    output = pane.capture_pane()
    assert any("Hello from tmux!" in line for line in output)
```

## How it works

The libtmux pytest plugin provides several fixtures that automatically manage the tmux environment for your tests:

1. **Core fixtures** - `server`, `session`, `window`, and `pane` create isolated tmux instances
2. **Helper fixtures** - Utilities for temporary directories, configurations, and environment management
3. **Custom fixtures** - Fixtures you can override to customize the test environment

Each test gets its own isolated tmux environment, and all resources are automatically cleaned up after the test completes.

(recommended-fixtures)=

## Recommended fixtures

These fixtures are automatically used when the plugin is enabled and `pytest` is run:

- Creating temporary test directories:
  - `/home/` ({func}`home_path`)
  - `/home/${user}` ({func}`user_path`)
  
- Default `.tmux.conf` configuration with these settings ({func}`config_file`):
  - `base-index -g 1`

These settings ensure panes and windows can be reliably referenced and asserted across different test environments.

## Next steps

- Explore the available {ref}`fixtures` for more advanced testing scenarios
- See {ref}`usage-examples` for detailed code examples
- Learn about {ref}`advanced-techniques` for complex testing requirements
