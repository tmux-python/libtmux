(waiter)=

# Waiters - `libtmux._internal.waiter`

The waiter module provides utilities for waiting on specific content to appear in tmux panes, making it easier to write reliable tests that interact with terminal output.

## Key Features

- **Fluent API**: Playwright-inspired chainable API for expressive, readable test code
- **Multiple Match Types**: Wait for exact matches, substring matches, regex patterns, or custom predicate functions
- **Composable Waiting**: Wait for any of multiple conditions or all conditions to be met
- **Flexible Timeout Handling**: Configure timeout behavior and error handling to suit your needs
- **Shell Prompt Detection**: Easily wait for shell readiness with built-in prompt detection
- **Robust Error Handling**: Improved exception handling and result reporting
- **Clean Code**: Well-formatted, linted code with proper type annotations

## Basic Concepts

When writing tests that interact with tmux sessions and panes, it's often necessary to wait for specific content to appear before proceeding with the next step. The waiter module provides a set of functions to help with this.

There are multiple ways to match content:
- **Exact match**: The content exactly matches the specified string
- **Contains**: The content contains the specified string
- **Regex**: The content matches the specified regular expression
- **Predicate**: A custom function that takes the pane content and returns a boolean

## Quick Start Examples

### Simple Waiting

Wait for specific text to appear in a pane:

```{literalinclude} ../../tests/examples/_internal/waiter/test_wait_for_text.py
:language: python
```

### Advanced Matching

Use regex patterns or custom predicates for more complex matching:

```{literalinclude} ../../tests/examples/_internal/waiter/test_wait_for_regex.py
:language: python
```

```{literalinclude} ../../tests/examples/_internal/waiter/test_custom_predicate.py
:language: python
```

### Timeout Handling

Control how long to wait and what happens when a timeout occurs:

```{literalinclude} ../../tests/examples/_internal/waiter/test_timeout_handling.py
:language: python
```

### Waiting for Shell Readiness

A common use case is waiting for a shell prompt to appear, indicating the command has completed. The example below uses a regular expression to match common shell prompt characters (`$`, `%`, `>`, `#`):

```{literalinclude} ../../tests/examples/_internal/waiter/test_wait_until_ready.py
:language: python
```

> Note: This test is skipped in CI environments due to timing issues but works well for local development.

## Fluent API (Playwright-inspired)

For a more expressive and chainable API, you can use the fluent interface provided by the `PaneContentWaiter` class:

```{literalinclude} ../../tests/examples/_internal/waiter/test_fluent_basic.py
:language: python
```

```{literalinclude} ../../tests/examples/_internal/waiter/test_fluent_chaining.py
:language: python
```

## Multiple Conditions

The waiter module also supports waiting for multiple conditions at once:

```{literalinclude} ../../tests/examples/_internal/waiter/test_wait_for_any_content.py
:language: python
```

```{literalinclude} ../../tests/examples/_internal/waiter/test_wait_for_all_content.py
:language: python
```

```{literalinclude} ../../tests/examples/_internal/waiter/test_mixed_pattern_types.py
:language: python
```

## Implementation Notes

### Error Handling

The waiting functions are designed to be robust and handle timing and error conditions gracefully:

- All wait functions properly calculate elapsed time for performance tracking
- Functions handle exceptions consistently and provide clear error messages
- Proper handling of return values ensures consistent behavior whether or not raises=True

### Type Safety

The waiter module is fully type-annotated to ensure compatibility with static type checkers:

- All functions include proper type hints for parameters and return values
- The ContentMatchType enum ensures that only valid match types are used
- Combined with runtime checks, this prevents type-related errors during testing

### Example Usage in Documentation

All examples in this documentation are actual test files from the libtmux test suite. The examples are included using `literalinclude` directives, ensuring that the documentation remains synchronized with the actual code.

## API Reference

```{eval-rst}
.. automodule:: libtmux._internal.waiter
   :members:
   :undoc-members:
   :show-inheritance:
   :member-order: bysource
```

## Extended Retry Functionality

```{eval-rst}
.. automodule:: libtmux.test.retry_extended
   :members:
   :undoc-members:
   :show-inheritance:
   :member-order: bysource
```
