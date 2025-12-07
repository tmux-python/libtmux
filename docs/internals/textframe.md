# TextFrame - ASCII Frame Simulator

TextFrame provides a fixed-size ASCII frame simulator for visualizing terminal content with overflow detection and diagnostic rendering. It integrates with [syrupy](https://github.com/tophat/syrupy) for snapshot testing and pytest for rich assertion output.

## Installation

TextFrame is available as an optional extra:

```bash
pip install libtmux[textframe]
```

This installs syrupy and registers the pytest plugin automatically.

## Quick Start

After installation, the `textframe_snapshot` fixture and `pytest_assertrepr_compare` hook are auto-discovered by pytest:

```python
from libtmux.textframe import TextFrame

def test_my_terminal_ui(textframe_snapshot):
    frame = TextFrame(content_width=20, content_height=5)
    frame.set_content(["Hello", "World"])
    assert frame == textframe_snapshot
```

## Overview

TextFrame is designed for testing terminal UI components. It provides:

- Fixed-dimension ASCII frames with borders
- Configurable overflow behavior (error or truncate)
- Syrupy snapshot testing with `.frame` files
- Rich pytest assertion output for frame comparisons

## Core Components

### TextFrame Dataclass

```python
from libtmux.textframe import TextFrame, ContentOverflowError

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
# src/libtmux/textframe/plugin.py
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

### Auto-Discovered Fixtures

When `libtmux[textframe]` is installed, the following fixture is available:

```python
@pytest.fixture
def textframe_snapshot(snapshot: SnapshotAssertion) -> SnapshotAssertion:
    """Snapshot fixture configured with TextFrameExtension."""
    return snapshot.use_extension(TextFrameExtension)
```

### Snapshot Directory Structure

```
__snapshots__/
  test_module/
    test_frame_rendering[basic_success].frame
    test_frame_rendering[overflow_width].frame
    test_frame_rendering[empty_frame].frame
    ...
```

## pytest Assertion Hook

The `pytest_assertrepr_compare` hook provides rich diff output for TextFrame comparisons:

```python
# Auto-registered via pytest11 entry point
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

## Plugin Discovery

The textframe plugin is registered via pytest's entry point mechanism:

```toml
# pyproject.toml
[project.entry-points.pytest11]
libtmux-textframe = "libtmux.textframe.plugin"

[project.optional-dependencies]
textframe = ["syrupy>=4.0.0"]
```

When installed with `pip install libtmux[textframe]`:
1. syrupy is installed as a dependency
2. The pytest11 entry point is registered
3. pytest auto-discovers the plugin on startup
4. `textframe_snapshot` fixture and assertion hooks are available

## Architecture Patterns

### From syrupy

- **Extension hierarchy**: `SingleFileSnapshotExtension` extends `AbstractSyrupyExtension`
- **Serialization**: Override `serialize()` for custom data types
- **File naming**: `file_extension` class attribute controls snapshot file suffix

### From pytest

- **`pytest_assertrepr_compare` hook**: Return `list[str]` for custom assertion output
- **pytest11 entry points**: Auto-discovery of installed plugins
- **Fixture auto-discovery**: Fixtures defined in plugins are globally available

### From CPython dataclasses

- **`@dataclass(slots=True)`**: Memory-efficient, prevents accidental attribute assignment
- **`__post_init__`**: Validation after dataclass initialization
- **Type aliases**: `OverflowBehavior = Literal["error", "truncate"]`

## Files

| File | Purpose |
|------|---------|
| `src/libtmux/textframe/core.py` | `TextFrame` dataclass and `ContentOverflowError` |
| `src/libtmux/textframe/plugin.py` | Syrupy extension, pytest hooks, and fixtures |
| `src/libtmux/textframe/__init__.py` | Public API exports |

## Public API

```python
from libtmux.textframe import (
    TextFrame,           # Core dataclass
    ContentOverflowError, # Exception with visual diagnostic
    TextFrameExtension,  # Syrupy extension for custom usage
)
```
