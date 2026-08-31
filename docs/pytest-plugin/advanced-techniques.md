---
myst:
  html_meta:
    description: "Advanced techniques for testing with the libtmux pytest plugin"
    keywords: "tmux, pytest, advanced testing, polling, temporary files"
---

(advanced-techniques)=

# Advanced Techniques

This page covers advanced testing techniques using the libtmux pytest plugin for more sophisticated testing scenarios.

## Testing with Temporary Files

### Creating Temporary Project Directories

```{literalinclude} ../../tests/examples/pytest_plugin/test_temp_files.py
:language: python
:pyobject: temp_project_dir
```

### Working with Files in Temporary Directories

```{literalinclude} ../../tests/examples/pytest_plugin/test_temp_files.py
:language: python
:pyobject: test_project_file_manipulation
```

## Command Polling

### Implementing Robust Wait Functions

```{literalinclude} ../../tests/examples/pytest_plugin/test_command_polling.py
:language: python
:pyobject: wait_for_output
```

### Testing with Command Polling

```{literalinclude} ../../tests/examples/pytest_plugin/test_command_polling.py
:language: python
:pyobject: test_command_with_polling
```

### Error Handling with Polling

```{literalinclude} ../../tests/examples/pytest_plugin/test_command_polling.py
:language: python
:pyobject: test_error_handling
```

## Setting Custom Home Directory

### Temporary Home Directory Setup

```{literalinclude} ../../tests/examples/pytest_plugin/test_home_directory.py
:language: python
:pyobject: set_home
```

## Testing with Complex Layouts

Creating and testing more complex window layouts:

```{literalinclude} ../../tests/examples/pytest_plugin/test_complex_layouts.py
:language: python
:pyobject: test_complex_layouts
```

For an even more advanced layout, you can create a tiled configuration:

```{literalinclude} ../../tests/examples/pytest_plugin/test_complex_layouts.py
:language: python
:pyobject: test_tiled_layout
```

## Testing Across Server Restarts

When you need to test functionality that persists across server restarts:

```{literalinclude} ../../tests/examples/pytest_plugin/test_server_restart.py
:language: python
:pyobject: test_persist_across_restart
```

## Best Practices

### Test Structure

1. **Arrange** - Set up your tmux environment and test data
2. **Act** - Perform the actions you want to test
3. **Assert** - Verify the expected outcome
4. **Clean up** - Reset any state changes (usually handled by fixtures)

### Tips for Reliable Tests

1. **Use appropriate waits**: Terminal operations aren't instantaneous. Add sufficient wait times or use polling techniques.

2. **Capture full pane contents**: Use `pane.capture_pane()` to get all output content for verification.

3. **Isolate tests**: Don't rely on state from other tests. Each test should set up its own environment.

4. **Use descriptive assertions**: When tests fail, the assertion message should clarify what went wrong.

5. **Test error conditions**: Include tests for error handling to ensure your code behaves correctly in failure scenarios.

6. **Keep tests fast**: Minimize wait times while keeping tests reliable.

7. **Use parametrized tests**: For similar tests with different inputs, use pytest's parametrize feature.

8. **Document test requirements**: If tests require specific tmux features, document this in comments.

9. **Mind CI environments**: Tests should work consistently in both local and CI environments, which may have different tmux versions and capabilities.
