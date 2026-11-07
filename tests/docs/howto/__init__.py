"""Sidecar harnesses for the how-to guides under ``docs/howto/``.

Each page ``docs/howto/<slug>.md`` is paired with a module in this package
whose name is the slug with hyphens replaced by underscores. The pairing is
enforced by :mod:`tests.docs.howto_harness`: a page without a sidecar, or a
sidecar whose check count does not match the page's code-block count, fails
the suite.
"""

from __future__ import annotations
