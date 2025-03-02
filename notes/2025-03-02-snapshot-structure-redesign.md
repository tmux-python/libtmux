# Snapshot Module Redesign Proposal

**Date**: March 2, 2025  
**Author**: Development Team  
**Status**: Draft Proposal

## Executive Summary

This document proposes refactoring the current monolithic `snapshot.py` module (approximately 650 lines) into a structured package to improve maintainability, testability, and extensibility. The primary goal is to separate concerns, reduce file size, and establish a clear API boundary while maintaining backward compatibility.

## Current State Analysis

### Structure

The current `snapshot.py` module contains:

- 4 base classes with sealable mixin functionality
- 4 concrete snapshot classes (Server, Session, Window, Pane)
- Several utility functions for filtering and transformations
- Type definitions and aliases
- Complex inter-dependencies between classes

### Pain Points

1. **Size**: The file is large (~650 lines) and challenging to navigate
2. **Tight coupling**: Classes reference each other directly, creating complex dependencies
3. **Mixed concerns**: Type definitions, base classes, implementations, and utilities are intermingled
4. **Testing complexity**: Testing specific components requires loading the entire module
5. **Future maintenance**: Adding new features or making changes affects the entire module

## Proposed Structure

We propose refactoring into a dedicated package with this structure:

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

### Key Components

1. **`__init__.py`**: Document the module purpose and structure, but without exporting classes
   ```python
   """Hierarchical snapshots of tmux objects.
   
   libtmux.snapshot
   ~~~~~~~~~~~~~~
   
   This module provides hierarchical snapshots of tmux objects (Server, Session,
   Window, Pane) that are immutable and maintain the relationships between objects.
   """
   ```

2. **`types.py`**: Centralizes all type definitions
   ```python
   from __future__ import annotations

   import typing as t

   from libtmux.pane import Pane
   from libtmux.server import Server
   from libtmux.session import Session
   from libtmux.window import Window

   # Type variables for generic typing
   PaneT = t.TypeVar("PaneT", bound=Pane, covariant=True)
   WindowT = t.TypeVar("WindowT", bound=Window, covariant=True)
   SessionT = t.TypeVar("SessionT", bound=Session, covariant=True)
   ServerT = t.TypeVar("ServerT", bound=Server, covariant=True)

   # Forward references for snapshot classes
   if t.TYPE_CHECKING:
       from libtmux.snapshot.models.pane import PaneSnapshot
       from libtmux.snapshot.models.window import WindowSnapshot
       from libtmux.snapshot.models.session import SessionSnapshot
       from libtmux.snapshot.models.server import ServerSnapshot
   
       # Union type for snapshot classes
       SnapshotType = t.Union[ServerSnapshot, SessionSnapshot, WindowSnapshot, PaneSnapshot]
   else:
       # Runtime placeholder - will be properly defined after imports
       SnapshotType = t.Any
   ```

3. **`base.py`**: Base classes that implement sealable behavior
   ```python
   from __future__ import annotations
   
   import typing as t
   
   from libtmux._internal.frozen_dataclass_sealable import Sealable
   from libtmux._internal.query_list import QueryList
   from libtmux.pane import Pane
   from libtmux.server import Server
   from libtmux.session import Session
   from libtmux.window import Window
   
   from libtmux.snapshot.types import PaneT, WindowT, SessionT, PaneT
   
   class SealablePaneBase(Pane, Sealable):
       """Base class for sealable pane classes."""
   
   class SealableWindowBase(Window, Sealable, t.Generic[PaneT]):
       """Base class for sealable window classes with generic pane type."""
       
       # Implementation of properties with proper typing
       
   class SealableSessionBase(Session, Sealable, t.Generic[WindowT, PaneT]):
       """Base class for sealable session classes with generic window and pane types."""
       
       # Implementation of properties with proper typing
   
   class SealableServerBase(Server, Sealable, t.Generic[SessionT, WindowT, PaneT]):
       """Generic base for sealable server with typed session, window, and pane."""
       
       # Implementation of properties with proper typing
   ```

4. **Model classes**: Individual implementations in separate files
   - Each file contains a single snapshot class with focused responsibility
   - Clear imports and dependencies between modules
   - Proper type annotations

5. **`utils.py`**: Utility functions separated from model implementations
   ```python
   from __future__ import annotations
   
   import copy
   import datetime
   import typing as t
   
   from libtmux.snapshot.types import SnapshotType
   from libtmux.snapshot.models.server import ServerSnapshot
   from libtmux.snapshot.models.session import SessionSnapshot
   from libtmux.snapshot.models.window import WindowSnapshot
   from libtmux.snapshot.models.pane import PaneSnapshot
   
   def filter_snapshot(
       snapshot: SnapshotType,
       filter_func: t.Callable[[SnapshotType], bool],
   ) -> SnapshotType | None:
       """Filter a snapshot hierarchy based on a filter function."""
       # Implementation...
   
   def snapshot_to_dict(
       snapshot: SnapshotType | t.Any,
   ) -> dict[str, t.Any]:
       """Convert a snapshot to a dictionary, avoiding circular references."""
       # Implementation...
   
   def snapshot_active_only(
       full_snapshot: ServerSnapshot,
   ) -> ServerSnapshot:
       """Return a filtered snapshot containing only active sessions, windows, and panes."""
       # Implementation...
   ```

## Implementation Plan

We propose a phased approach with the following steps:

### Phase 1: Setup Package Structure (Week 1)

1. Create the package directory structure
2. Set up module files with appropriate documentation
3. Create the types.py module with all type definitions
4. Draft the base.py module with base classes

### Phase 2: Migrate Models (Week 2-3)

1. Move PaneSnapshot to its own module
2. Move WindowSnapshot to its own module
3. Move SessionSnapshot to its own module
4. Move ServerSnapshot to its own module
5. Update imports and references between modules

### Phase 3: Extract Utilities (Week 3)

1. Move utility functions to utils.py
2. Update imports and references

### Phase 4: Testing and Finalization (Week 4)

1. Add/update tests to verify all functionality works correctly
2. Update documentation
3. Final code review
4. Merge to main branch

## Benefits and Tradeoffs

### Benefits

1. **Improved maintainability**: Smaller, focused files with clear responsibilities
2. **Better organization**: Separation of concerns between different components
3. **Simplified testing**: Ability to test components in isolation
4. **Enhanced discoverability**: Easier for new developers to understand the codebase
5. **Clearer API boundary**: Direct imports encourage explicit dependencies
6. **Future extensibility**: Easier to add new snapshot types or modify existing ones

### Tradeoffs

1. **Initial effort**: Significant upfront work to refactor and test
2. **Complexity**: More files to navigate and understand
3. **Risk**: Potential for regressions during refactoring
4. **Import overhead**: Slightly more verbose import statements
5. **Learning curve**: Team needs to adapt to the new structure

## Backward Compatibility

The proposed changes maintain backward compatibility through:

1. **Direct imports**: Users will need to update imports to reference specific modules
2. **Same behavior**: No functional changes to how snapshots work
3. **Same type definitions**: Type hints remain compatible with existing code

## Success Metrics

The success of this refactoring will be measured by:

1. **Code coverage**: Maintain or improve current test coverage
2. **File sizes**: No file should exceed 200 lines
3. **Import clarity**: Clear and direct imports between modules
4. **Maintainability**: Reduction in complexity metrics
5. **Developer feedback**: Team survey on code navigability

## Conclusion

This redesign addresses the current maintainability issues with the snapshot module while preserving all functionality and backward compatibility. The modular approach will make future maintenance easier and allow for more focused testing. We recommend proceeding with this refactoring as outlined in the implementation plan.

## Next Steps

1. Review and finalize this proposal
2. Create implementation tickets in the issue tracker
3. Assign resources for implementation
4. Schedule code reviews at each phase completion 