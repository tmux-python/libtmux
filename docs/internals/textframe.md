# TextFrame - ASCII Frame Simulator

:::{warning}
This is a testing utility in `tests/textframe/`. It is **not** part of the public API.
:::

TextFrame provides a fixed-size ASCII frame simulator for visualizing terminal content with overflow detection and diagnostic rendering. It integrates with [syrupy](https://github.com/tophat/syrupy) for snapshot testing and pytest for rich assertion output.

## Overview

TextFrame is designed for testing terminal UI components. It provides:

- Fixed-dimension ASCII frames with borders
- Configurable overflow behavior (error or truncate)
- Syrupy snapshot testing with `.frame` files
- Rich pytest assertion output for frame comparisons

## Core Components

### TextFrame Dataclass

```python
from tests.textframe.core import TextFrame, ContentOverflowError

# Create a frame with fixed dimensions
frame = TextFrame(content_width=10, content_height=2)
frame.set_content(["hello", "world"])
print(frame.render())
```

Output:
```
+----------+
|hello     |
|world     |
+----------+
```

### Overflow Behavior

TextFrame supports two overflow behaviors:

**Error mode (default):** Raises `ContentOverflowError` with a visual diagnostic showing the content and a mask of valid/invalid areas.

```python
frame = TextFrame(content_width=5, content_height=2, overflow_behavior="error")
frame.set_content(["this line is too long"])  # Raises ContentOverflowError
```

The exception includes an `overflow_visual` attribute showing:
1. A "Reality" frame with the actual content
2. A "Mask" frame showing valid (space) vs invalid (dot) areas

**Truncate mode:** Silently clips content to fit the frame dimensions.

```python
frame = TextFrame(content_width=5, content_height=1, overflow_behavior="truncate")
frame.set_content(["hello world", "extra row"])
print(frame.render())
```

Output:
```
+-----+
|hello|
+-----+
```

## Syrupy Integration

### SingleFileSnapshotExtension

TextFrame uses syrupy's `SingleFileSnapshotExtension` to store each snapshot in its own `.frame` file. This provides:

- Cleaner git diffs (one file per test vs all-in-one `.ambr`)
- Easier code review of snapshot changes
- Human-readable ASCII art in snapshot files

### Extension Implementation

```python
# tests/textframe/plugin.py
from syrupy.extensions.single_file import SingleFileSnapshotExtension, WriteMode

class TextFrameExtension(SingleFileSnapshotExtension):
    _write_mode = WriteMode.TEXT
    file_extension = "frame"

    def serialize(self, data, **kwargs):
        if isinstance(data, TextFrame):
            return data.render()
        if isinstance(data, ContentOverflowError):
            return data.overflow_visual
        return str(data)
```

Key design decisions:

1. **`file_extension = "frame"`**: Uses `.frame` suffix for snapshot files instead of the default `.raw`
2. **`_write_mode = WriteMode.TEXT`**: Stores snapshots as text (not binary)
3. **Custom serialization**: Renders TextFrame objects and ContentOverflowError exceptions as ASCII art

### Fixture Override Pattern

The snapshot fixture is overridden in `conftest.py` using syrupy's `use_extension()` pattern:

```python
# tests/textframe/conftest.py
@pytest.fixture
def snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    return snapshot.use_extension(TextFrameExtension)
```

This pattern works because pytest fixtures that request themselves receive the parent scope's version.

### Snapshot Directory Structure

```
tests/textframe/__snapshots__/
  test_core/
    test_frame_rendering[basic_success].frame
    test_frame_rendering[overflow_width].frame
    test_frame_rendering[empty_frame].frame
    ...
```

## Pure pytest Assertion Hook

For TextFrame-to-TextFrame comparisons (without syrupy), a `pytest_assertrepr_compare` hook provides rich diff output:

```python
# tests/textframe/conftest.py
def pytest_assertrepr_compare(config, op, left, right):
    if not isinstance(left, TextFrame) or not isinstance(right, TextFrame):
        return None
    if op != "==":
        return None

    lines = ["TextFrame comparison failed:"]

    # Dimension mismatch
    if left.content_width != right.content_width:
        lines.append(f"  width: {left.content_width} != {right.content_width}")
    if left.content_height != right.content_height:
        lines.append(f"  height: {left.content_height} != {right.content_height}")

    # Content diff using difflib.ndiff
    left_render = left.render().splitlines()
    right_render = right.render().splitlines()
    if left_render != right_render:
        lines.append("")
        lines.append("Content diff:")
        lines.extend(ndiff(right_render, left_render))

    return lines
```

This hook intercepts `assert frame1 == frame2` comparisons and shows:
- Dimension mismatches (width/height)
- Line-by-line diff using `difflib.ndiff`

## Architecture Patterns

### From syrupy

- **Extension hierarchy**: `SingleFileSnapshotExtension` extends `AbstractSyrupyExtension`
- **Serialization**: Override `serialize()` for custom data types
- **File naming**: `file_extension` class attribute controls snapshot file suffix

### From pytest

- **`pytest_assertrepr_compare` hook**: Return `list[str]` for custom assertion output
- **Fixture override pattern**: Request same-named fixture to get parent scope's version
- **`ndiff` for diffs**: Character-level diff with `+`/`-` prefixes

### From CPython dataclasses

- **`@dataclass(slots=True)`**: Memory-efficient, prevents accidental attribute assignment
- **`__post_init__`**: Validation after dataclass initialization
- **Type aliases**: `OverflowBehavior = Literal["error", "truncate"]`

## Files

| File | Purpose |
|------|---------|
| `tests/textframe/core.py` | `TextFrame` dataclass and `ContentOverflowError` |
| `tests/textframe/plugin.py` | Syrupy `TextFrameExtension` |
| `tests/textframe/conftest.py` | Fixture override and `pytest_assertrepr_compare` hook |
| `tests/textframe/test_core.py` | Parametrized tests with snapshot assertions |
| `tests/textframe/__snapshots__/test_core/*.frame` | Snapshot baselines |
