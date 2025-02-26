---
myst:
  html_meta:
    description: "Usage examples for the libtmux pytest plugin"
    keywords: "tmux, pytest, examples, testing, patterns"
---

(usage-examples)=

# Usage Examples

This page provides practical code examples for testing with the libtmux pytest plugin. All examples shown here are included as real test files in the `tests/examples/pytest_plugin` directory.

## Basic Examples

### Server Testing

```{literalinclude} ../../tests/examples/pytest_plugin/test_basic_usage.py
:language: python
:pyobject: test_basic_server
```

### Session Testing

```{literalinclude} ../../tests/examples/pytest_plugin/test_basic_usage.py
:language: python
:pyobject: test_basic_session
```

### Window Testing

```{literalinclude} ../../tests/examples/pytest_plugin/test_basic_usage.py
:language: python
:pyobject: test_basic_window
```

### Pane Testing

```{literalinclude} ../../tests/examples/pytest_plugin/test_basic_usage.py
:language: python
:pyobject: test_basic_pane
```

## Environment Configuration

### Setting Environment Variables

```{literalinclude} ../../tests/examples/pytest_plugin/test_custom_environment.py
:language: python
:pyobject: test_environment_variables
```

### Directory Navigation

```{literalinclude} ../../tests/examples/pytest_plugin/test_custom_environment.py
:language: python
:pyobject: test_directory_navigation
```

### Custom Session Parameters

```{literalinclude} ../../tests/examples/pytest_plugin/test_session_params.py
:language: python
:pyobject: session_params
```

```{literalinclude} ../../tests/examples/pytest_plugin/test_session_params.py
:language: python
:pyobject: test_custom_session_dimensions
```

## Testing with Multiple Servers

### Basic Test Server Usage

```{literalinclude} ../../tests/examples/pytest_plugin/test_multiple_servers.py
:language: python
:pyobject: test_basic_test_server
```

### Multiple Servers with Custom Configuration

```{literalinclude} ../../tests/examples/pytest_plugin/test_multiple_servers.py
:language: python
:pyobject: test_with_config
```

### Multiple Independent Servers

```{literalinclude} ../../tests/examples/pytest_plugin/test_multiple_servers.py
:language: python
:pyobject: test_multiple_independent_servers
```

## Testing with Multiple Panes

### Multi-Pane Interaction

```{literalinclude} ../../tests/examples/pytest_plugin/test_multi_pane.py
:language: python
:pyobject: test_multi_pane_interaction
```

### Pane Layout Testing

```{literalinclude} ../../tests/examples/pytest_plugin/test_multi_pane.py
:language: python
:pyobject: test_pane_layout
```

## Window Management

Window management is a common task when working with tmux. Here are some examples:

### Window Renaming

```{literalinclude} ../../tests/examples/pytest_plugin/test_window_management.py
:language: python
:pyobject: test_window_renaming
```

### Moving Windows

```{literalinclude} ../../tests/examples/pytest_plugin/test_window_management.py
:language: python
:pyobject: test_window_moving
```

### Switching Between Windows

```{literalinclude} ../../tests/examples/pytest_plugin/test_window_management.py
:language: python
:pyobject: test_window_switching
```

### Killing Windows

```{literalinclude} ../../tests/examples/pytest_plugin/test_window_management.py
:language: python
:pyobject: test_window_killing
```

## Pane Operations

Panes are the subdivisions within windows where commands are executed:

### Advanced Pane Functions

```{literalinclude} ../../tests/examples/pytest_plugin/test_pane_operations.py
:language: python
:pyobject: test_pane_functions
```

### Resizing Panes

```{literalinclude} ../../tests/examples/pytest_plugin/test_pane_operations.py
:language: python
:pyobject: test_pane_resizing
```

### Capturing Pane Content

```{literalinclude} ../../tests/examples/pytest_plugin/test_pane_operations.py
:language: python
:pyobject: test_pane_capturing
```

## Process Control

Working with processes in tmux panes:

### Process Detection

```{literalinclude} ../../tests/examples/pytest_plugin/test_process_control.py
:language: python
:pyobject: test_process_detection
```

### Handling Command Output

```{literalinclude} ../../tests/examples/pytest_plugin/test_process_control.py
:language: python
:pyobject: test_command_output_scrollback
```

### Background Processes

```{literalinclude} ../../tests/examples/pytest_plugin/test_process_control.py
:language: python
:pyobject: test_running_background_process
```

## Custom Configuration Testing

### Creating a Custom Configuration

```{literalinclude} ../../tests/examples/pytest_plugin/test_custom_config.py
:language: python
:pyobject: custom_config
```

### Using a Custom Server Configuration

```{literalinclude} ../../tests/examples/pytest_plugin/test_custom_config.py
:language: python
:pyobject: custom_server
```

### Testing with Custom Configuration

```{literalinclude} ../../tests/examples/pytest_plugin/test_custom_config.py
:language: python
:pyobject: test_with_custom_config
```

## Parametrized Testing

### Testing Multiple Window Names

```{literalinclude} ../../tests/examples/pytest_plugin/test_parametrized.py
:language: python
:pyobject: test_multiple_windows
```

### Testing Various Commands

```{literalinclude} ../../tests/examples/pytest_plugin/test_parametrized.py
:language: python
:pyobject: test_various_commands
```

### Testing Window Layouts

```{literalinclude} ../../tests/examples/pytest_plugin/test_parametrized.py
:language: python
:pyobject: test_window_layouts
```
