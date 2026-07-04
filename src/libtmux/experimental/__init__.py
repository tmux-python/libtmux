"""Experimental libtmux APIs.

This package hosts work that is **not** covered by the project's versioning
policy. Anything under :mod:`libtmux.experimental` may change shape or be
removed between any two releases without notice.

Current contents:

- :mod:`libtmux.experimental.ops` -- inert, typed tmux *operation* values: the
  pure source of truth that renders tmux commands, carries result types, and
  serializes without a live tmux server.
- :mod:`libtmux.experimental.engines` -- *engine* protocols and
  implementations that execute operations and return typed results.
- :mod:`libtmux.experimental.objects` -- engine-bound tmux domain objects
  (eager, lazy, and async) over the shared operation spine.

See the operationalization plan (``tmux-python/libtmux`` issue 689) and the
architecture proposal (issue 688) for background.
"""

from __future__ import annotations
