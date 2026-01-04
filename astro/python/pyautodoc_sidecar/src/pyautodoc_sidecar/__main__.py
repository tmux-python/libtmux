"""Entrypoint for running the sidecar as a module."""

from __future__ import annotations

from pyautodoc_sidecar.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
