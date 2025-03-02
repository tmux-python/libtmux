# Analysis of Snapshot Architecture

This document provides an analysis of the `snapshot` module architecture, with updates based on the recent refactoring efforts.

## Current Architecture

The module now implements a hierarchical snapshot system for tmux objects with these key components:

1. A modular package structure:
   ```
   src/libtmux/snapshot/
   ├── __init__.py           # Module documentation only, no exports
   ├── base.py               # Base classes with Sealable mixins
   ├── types.py              # Type definitions, exports, and annotations
   ├── models/
   │   ├── __init__.py       # Package documentation only, no exports
   │   ├── pane.py           # PaneSnapshot implementation
   │   ├── window.py         # WindowSnapshot implementation 
   │   ├── session.py        # SessionSnapshot implementation
   │   └── server.py         # ServerSnapshot implementation
   └── utils.py              # Utility functions (filter_snapshot, snapshot_to_dict, etc.)
   ```

2. Four snapshot classes that mirror the tmux object hierarchy:
   - `ServerSnapshot` (in `models/server.py`)
   - `SessionSnapshot` (in `models/session.py`)
   - `WindowSnapshot` (in `models/window.py`)
   - `PaneSnapshot` (in `models/pane.py`)

3. Each class inherits from both:
   - The corresponding tmux class (Server, Session, etc.)
   - A `Sealable` base class to provide immutability (defined in `base.py`)

4. Utility functions for:
   - Filtering snapshots (`filter_snapshot`)
   - Converting to dictionaries (`snapshot_to_dict`) 
   - Creating active-only views (`snapshot_active_only`)

5. Direct imports approach:
   - No re-exports from `__init__.py` files
   - Users import directly from specific modules
   - Clear and explicit dependencies between modules

## Typing Approach

The module makes excellent use of Python's modern typing features:

- Type variables with covariance (`PaneT = t.TypeVar("PaneT", bound=Pane, covariant=True)`)
- Proper return type annotations with Union types
- Type checking guards (`if t.TYPE_CHECKING:`)
- Type casts for better type safety (`t.cast("ServerSnapshot", filtered)`)
- Centralized type definitions in `types.py`

## Core Design Principles

All proposals and enhancements must adhere to these core design principles:

1. **Type Safety**: All interfaces must provide comprehensive static and runtime type safety.
   - Eliminate all `# type: ignore` comments with proper typing solutions
   - Support advanced mypy checking without compromises
   - Maintain precise typing for all return values and parameters

2. **Immutability**: Snapshots must be strictly immutable.
   - Use `frozen_dataclass_sealable` to enforce immutability
   - Return new instances rather than modifying state
   - Ensure deep immutability for nested structures

3. **Inheritance Model**: Snapshot classes must inherit from their base tmux objects.
   - `PaneSnapshot` inherits from `Pane` 
   - `WindowSnapshot` inherits from `Window`
   - `SessionSnapshot` inherits from `Session`
   - `ServerSnapshot` inherits from `Server`

## Strengths of Current Implementation

1. **Modular Structure**: Smaller, focused files with clear responsibilities
2. **Separation of Concerns**: Types, base classes, models, and utilities are now properly separated
3. **Immutability Pattern**: Using `frozen_dataclass_sealable` provides a robust way to create immutable snapshots
4. **Type Safety**: Strong typing throughout the codebase
5. **Direct Imports**: Explicit dependencies encourage better code organization
6. **Maintainability**: Easier to understand, test, and extend each component

## Remaining Areas for Improvement

While the modular structure has been implemented, there are still opportunities for enhancing the API:

1. **Complex Factory Methods**: The `from_X` methods contain complex logic for finding server references, with multiple fallback strategies:
   ```python
   if source_server is None and window_snapshot is not None:
       source_server = window_snapshot.server
   # ...more fallbacks...
   ```

2. **Circular References**: The bi-directional references (window_snapshot -> session_snapshot -> window_snapshot) could create complexity for serialization and garbage collection.

3. **Error Handling Consistency**: There's a mix of suppressed exceptions and explicit error raising that could be standardized.

4. **Memory Optimization**: Snapshots duplicate a lot of data, especially with `capture_content=True`.

## Detailed Implementation Proposals

The following proposals aim to address the identified areas for improvement while maintaining the core design principles.

### Proposal 1: Enhanced Hierarchy with Better Type-Safe Factories

This proposal maintains the current inheritance model but significantly improves the factory methods and type safety.

#### 1.1 Type-Safe Factory Base Class

```python
# Add to base.py
class SnapshotFactory(Generic[T_co]):
    """Base class for snapshot factories with type-safe methods."""
    
    @classmethod
    def create(
        cls, 
        source: Union[Server, Session, Window, Pane], 
        capture_content: bool = False,
        **options
    ) -> T_co:
        """Type-safe factory method that dispatches to the correct snapshot type.
        
        Args:
            source: The source object to create a snapshot from
            capture_content: Whether to capture pane content
            **options: Additional options passed to the snapshot constructor
            
        Returns:
            A new snapshot instance of the appropriate type
            
        Raises:
            TypeError: If source is not a valid tmux object type
        """
        if isinstance(source, Pane):
            from libtmux.snapshot.models.pane import PaneSnapshot
            return t.cast(T_co, PaneSnapshot.from_pane(source, capture_content, **options))
        elif isinstance(source, Window):
            from libtmux.snapshot.models.window import WindowSnapshot
            return t.cast(T_co, WindowSnapshot.from_window(source, capture_content, **options))
        elif isinstance(source, Session):
            from libtmux.snapshot.models.session import SessionSnapshot
            return t.cast(T_co, SessionSnapshot.from_session(source, capture_content, **options))
        elif isinstance(source, Server):
            from libtmux.snapshot.models.server import ServerSnapshot
            return t.cast(T_co, ServerSnapshot.from_server(source, capture_content, **options))
        else:
            raise TypeError(f"Cannot create snapshot from {type(source).__name__}")
```

#### 1.2 Improved Snapshot Base Class

```python
# Add to base.py
class SnapshotBase(Generic[T_Snap_co]):
    """Base class for all snapshot types with common functionality."""
    
    def filter(
        self, 
        predicate: Callable[[T_Snap_co], bool]
    ) -> Optional[T_Snap_co]:
        """Apply a filter function to this snapshot and its children.
        
        Args:
            predicate: Function that takes a snapshot and returns True to keep it
            
        Returns:
            A new filtered snapshot or None if this snapshot is filtered out
        """
        from libtmux.snapshot.utils import filter_snapshot
        return filter_snapshot(t.cast(T_Snap_co, self), predicate)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert this snapshot to a dictionary representation.
        
        Returns:
            A dictionary representing this snapshot's data
        """
        from libtmux.snapshot.utils import snapshot_to_dict
        return snapshot_to_dict(self)
```

#### 1.3 Unified Centralized Entry Point 

```python
# Create new factory.py
"""Factory functions for creating tmux object snapshots."""

from __future__ import annotations

import typing as t
from typing import Optional, Union, TypeVar, overload

from libtmux.pane import Pane
from libtmux.server import Server
from libtmux.session import Session
from libtmux.window import Window

# Forward references for overloads
if t.TYPE_CHECKING:
    from libtmux.snapshot.models.pane import PaneSnapshot
    from libtmux.snapshot.models.server import ServerSnapshot
    from libtmux.snapshot.models.session import SessionSnapshot
    from libtmux.snapshot.models.window import WindowSnapshot

# Type-safe overloaded factory function
@overload
def create_snapshot(source: Server, capture_content: bool = False, **options) -> "ServerSnapshot": ...

@overload
def create_snapshot(source: Session, capture_content: bool = False, **options) -> "SessionSnapshot": ...

@overload
def create_snapshot(source: Window, capture_content: bool = False, **options) -> "WindowSnapshot": ...

@overload
def create_snapshot(source: Pane, capture_content: bool = False, **options) -> "PaneSnapshot": ...

def create_snapshot(
    source: Union[Server, Session, Window, Pane],
    capture_content: bool = False,
    **options
) -> Union["ServerSnapshot", "SessionSnapshot", "WindowSnapshot", "PaneSnapshot"]:
    """Create a snapshot of any tmux object with precise typing.
    
    Args:
        source: The tmux object to create a snapshot from
        capture_content: Whether to capture pane content
        **options: Additional options for specific snapshot types
        
    Returns:
        An immutable snapshot of the appropriate type
        
    Examples:
        # Create a server snapshot
        server_snapshot = create_snapshot(server)
        
        # Create a session snapshot with pane content captured
        session_snapshot = create_snapshot(session, capture_content=True)
        
        # Use fluent methods on the result
        filtered = create_snapshot(server).filter(lambda s: s.name == "dev")
    """
    # Implementation that dispatches to the correct type
    if isinstance(source, Pane):
        from libtmux.snapshot.models.pane import PaneSnapshot
        return PaneSnapshot.from_pane(source, capture_content, **options)
    elif isinstance(source, Window):
        from libtmux.snapshot.models.window import WindowSnapshot
        return WindowSnapshot.from_window(source, capture_content, **options)
    elif isinstance(source, Session):
        from libtmux.snapshot.models.session import SessionSnapshot
        return SessionSnapshot.from_session(source, capture_content, **options)
    elif isinstance(source, Server):
        from libtmux.snapshot.models.server import ServerSnapshot
        return ServerSnapshot.from_server(source, capture_content, **options)
    else:
        raise TypeError(f"Cannot create snapshot from {type(source).__name__}")
```

### Proposal 2: Fluent API with Method Chaining While Preserving Immutability

This proposal adds fluent interfaces to snapshot classes while maintaining immutability.

#### 2.1 Updated Snapshot Classes with Fluent Methods

```python
# Example for PaneSnapshot in models/pane.py
@frozen_dataclass_sealable
class PaneSnapshot(SealablePaneBase):
    """Immutable snapshot of a tmux pane."""
    
    # Existing fields...
    
    def with_content(self) -> "PaneSnapshot":
        """Return a new snapshot with captured pane content.
        
        Returns:
            A new PaneSnapshot with content captured
            
        Raises:
            ValueError: If the original pane is no longer available
        """
        if not self._original_pane or not self._original_pane.attached:
            raise ValueError("Original pane is no longer available")
            
        content = self._original_pane.capture_pane()
        return replace(self, content=content)
    
    def with_options(self, **options) -> "PaneSnapshot":
        """Return a new snapshot with updated options.
        
        Args:
            **options: New option values to set
            
        Returns:
            A new PaneSnapshot with updated options
        """
        return replace(self, **options)
```

#### 2.2 Enhanced Utility Methods as Class Methods

```python
# Example for ServerSnapshot in models/server.py
@frozen_dataclass_sealable
class ServerSnapshot(SealableServerBase):
    """Immutable snapshot of a tmux server."""
    
    # Existing fields...
    
    def active_only(self) -> "ServerSnapshot":
        """Filter this snapshot to include only active sessions, windows, and panes.
        
        Returns:
            A new ServerSnapshot with only active components
        """
        from libtmux.snapshot.utils import snapshot_active_only
        return snapshot_active_only(self)
    
    def find_session(self, name: str) -> Optional["SessionSnapshot"]:
        """Find a session by name in this snapshot.
        
        Args:
            name: The session name to search for
            
        Returns:
            The matching SessionSnapshot or None if not found
        """
        return next((s for s in self.sessions if s.name == name), None)
    
    def find_window(self, window_id: str) -> Optional["WindowSnapshot"]:
        """Find a window by ID in this snapshot.
        
        Args:
            window_id: The window ID to search for
            
        Returns:
            The matching WindowSnapshot or None if not found
        """
        for session in self.sessions:
            for window in session.windows:
                if window.window_id == window_id:
                    return window
        return None
```

#### 2.3 Context Managers for Snapshot Operations

```python
# Add to factory.py
@contextlib.contextmanager
def snapshot_context(
    source: Union[Server, Session, Window, Pane],
    capture_content: bool = False,
    **options
) -> Generator[SnapshotType, None, None]:
    """Create a snapshot as a context manager.
    
    Args:
        source: The tmux object to create a snapshot from
        capture_content: Whether to capture pane content
        **options: Additional options for specific snapshot types
        
    Yields:
        An immutable snapshot of the appropriate type
        
    Examples:
        with snapshot_context(server) as snapshot:
            active_sessions = [s for s in snapshot.sessions if s.active]
    """
    snapshot = create_snapshot(source, capture_content, **options)
    try:
        yield snapshot
    finally:
        # No cleanup needed due to immutability, but the context
        # manager pattern is still useful for scoping
        pass
```

### Proposal 3: Advanced Type Safety with Protocol Classes

This proposal enhances type safety while maintaining the inheritance model.

#### 3.1 Protocol-Based Type Definitions

```python
# Add to types.py
class SnapshotProtocol(Protocol):
    """Protocol defining common snapshot interface."""
    
    # Common properties that all snapshots should have
    @property
    def id(self) -> str: ...
    
    # Common methods all snapshots should implement
    def to_dict(self) -> dict[str, Any]: ...
    
class PaneSnapshotProtocol(SnapshotProtocol, Protocol):
    """Protocol for pane snapshots."""
    
    @property
    def pane_id(self) -> str: ...
    
    @property
    def window(self) -> "WindowSnapshotProtocol": ...
    
    # Other pane-specific properties
    
class WindowSnapshotProtocol(SnapshotProtocol, Protocol):
    """Protocol for window snapshots."""
    
    @property
    def window_id(self) -> str: ...
    
    @property
    def session(self) -> "SessionSnapshotProtocol": ...
    
    @property
    def panes(self) -> list["PaneSnapshotProtocol"]: ...
    
    # Other window-specific properties

# Similar protocols for Session and Server
```

#### 3.2 Updated Type Variables and Constraints

```python
# Update in types.py
# More precise type variables using Protocol classes
PaneT = TypeVar("PaneT", bound=PaneSnapshotProtocol, covariant=True)
WindowT = TypeVar("WindowT", bound=WindowSnapshotProtocol, covariant=True)
SessionT = TypeVar("SessionT", bound=SessionSnapshotProtocol, covariant=True)
ServerT = TypeVar("ServerT", bound=ServerSnapshotProtocol, covariant=True)

# Generic snapshot type
SnapshotT = TypeVar(
    "SnapshotT", 
    bound=Union[
        ServerSnapshotProtocol, 
        SessionSnapshotProtocol,
        WindowSnapshotProtocol,
        PaneSnapshotProtocol
    ],
    covariant=True
)
```

### Proposal 4: Advanced Configuration Options

This proposal adds flexible configuration options while maintaining immutability.

#### 4.1 Snapshot Configuration Class

```python
# Add to models/config.py
@dataclass(frozen=True)
class SnapshotConfig:
    """Configuration options for snapshot creation."""
    
    capture_content: bool = False
    """Whether to capture pane content."""
    
    max_content_lines: Optional[int] = None
    """Maximum number of content lines to capture, or None for all."""
    
    include_active_only: bool = False
    """Whether to include only active sessions, windows, and panes."""
    
    include_session_names: Optional[list[str]] = None
    """Names of sessions to include, or None for all."""
    
    include_window_ids: Optional[list[str]] = None
    """IDs of windows to include, or None for all."""
    
    include_pane_ids: Optional[list[str]] = None
    """IDs of panes to include, or None for all."""
    
    @classmethod
    def default(cls) -> "SnapshotConfig":
        """Get default configuration."""
        return cls()
    
    @classmethod
    def with_content(cls, max_lines: Optional[int] = None) -> "SnapshotConfig":
        """Get configuration with content capture enabled."""
        return cls(capture_content=True, max_content_lines=max_lines)
    
    @classmethod
    def active_only(cls, capture_content: bool = False) -> "SnapshotConfig":
        """Get configuration for active-only snapshots."""
        return cls(capture_content=capture_content, include_active_only=True)
```

#### 4.2 Updated Factory Function with Configuration Support

```python
# Update in factory.py
def create_snapshot(
    source: Union[Server, Session, Window, Pane],
    config: Optional[SnapshotConfig] = None,
    **options
) -> SnapshotType:
    """Create a snapshot with advanced configuration options.
    
    Args:
        source: The tmux object to create a snapshot from
        config: Snapshot configuration options, or None for defaults
        **options: Additional options for specific snapshot types
        
    Returns:
        An immutable snapshot of the appropriate type
        
    Examples:
        # Create a snapshot with default configuration
        snapshot = create_snapshot(server)
        
        # Create a snapshot with content capture
        config = SnapshotConfig.with_content(max_lines=1000)
        snapshot = create_snapshot(server, config)
        
        # Create a snapshot with only active components
        snapshot = create_snapshot(server, SnapshotConfig.active_only())
    """
    config = config or SnapshotConfig.default()
    
    # Implementation that applies configuration options
    if isinstance(source, Pane):
        from libtmux.snapshot.models.pane import PaneSnapshot
        return PaneSnapshot.from_pane(
            source, 
            capture_content=config.capture_content,
            max_content_lines=config.max_content_lines,
            **options
        )
    # Similar implementation for other types
```

## Example Usage After Implementation

```python
# Simple usage with centralized factory function
from libtmux.snapshot import create_snapshot

# Create a snapshot of a server
snapshot = create_snapshot(server)

# Create a snapshot with content capture
snapshot_with_content = create_snapshot(server, capture_content=True)

# Use fluent methods for filtering and transformation
active_windows = (
    create_snapshot(server)
    .filter(lambda s: isinstance(s, WindowSnapshot) and s.active)
    .to_dict()
)

# Use advanced configuration
from libtmux.snapshot.models.config import SnapshotConfig

config = SnapshotConfig(
    capture_content=True,
    max_content_lines=100,
    include_active_only=True
)

snapshot = create_snapshot(server, config=config)

# Use context manager
from libtmux.snapshot import snapshot_context

with snapshot_context(server) as snapshot:
    # Work with immutable snapshot
    dev_session = snapshot.find_session("dev")
    if dev_session:
        print(f"Dev session has {len(dev_session.windows)} windows")
```

## Implementation Priority and Timeline

Based on the proposals above, the following implementation timeline is suggested:

1. **Phase 1: Enhanced Factory Functions and Basic Fluent API** (1-2 weeks)
   - Implement the centralized factory in `factory.py`
   - Add basic fluent methods to snapshot classes
   - Update type definitions for better safety

2. **Phase 2: Advanced Type Safety with Protocol Classes** (1-2 weeks)
   - Implement Protocol classes in `types.py`
   - Update snapshot classes to conform to protocols
   - Enhance type checking throughout the codebase

3. **Phase 3: Advanced Configuration and Context Managers** (1-2 weeks)
   - Implement `SnapshotConfig` class
   - Add context manager support
   - Update factory functions to use configuration options

4. **Phase 4: Complete API Refinement and Documentation** (1-2 weeks)
   - Finalize the public API
   - Add comprehensive docstrings with examples
   - Provide usage examples in README

These proposals maintain the core design principles of inheritance, immutability, and type safety while significantly improving the API ergonomics, type checking, and user experience.
