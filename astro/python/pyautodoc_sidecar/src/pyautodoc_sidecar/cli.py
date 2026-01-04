"""Command-line interface for the autodoc sidecar."""

from __future__ import annotations

import argparse
import json
import pathlib
import typing as t

from pyautodoc_sidecar.introspect import introspect_module, introspect_package
from pyautodoc_sidecar.parse import scan_paths

PROTOCOL_VERSION = 1


def main(argv: list[str] | None = None) -> int:
    """Run the sidecar CLI.

    Parameters
    ----------
    argv : list[str] | None
        CLI arguments (excluding the program name).

    Returns
    -------
    int
        Exit status code.

    Examples
    --------
    >>> import contextlib
    >>> import io
    >>> import json
    >>> import pathlib
    >>> import tempfile
    >>> from pyautodoc_sidecar.cli import main
    >>> root = pathlib.Path(tempfile.mkdtemp())
    >>> module_path = root / 'demo.py'
    >>> _ = module_path.write_text('value = 1')
    >>> buffer = io.StringIO()
    >>> with contextlib.redirect_stdout(buffer):
    ...     main(['parse-files', '--root', str(root), '--paths', str(module_path)])
    0
    >>> payload = json.loads(buffer.getvalue())
    >>> payload['protocolVersion']
    1
    """
    parser = argparse.ArgumentParser(
        description="pyautodoc sidecar utilities for libtmux docs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_parser = subparsers.add_parser("parse-files", help="Parse Python files.")
    parse_parser.add_argument("--root", required=True)
    parse_parser.add_argument("--paths", nargs="+", required=True)
    parse_parser.add_argument("--include-private", action="store_true")

    intro_module = subparsers.add_parser(
        "introspect-module", help="Introspect a module."
    )
    intro_module.add_argument("--module", required=True)
    intro_module.add_argument("--root")
    intro_module.add_argument("--include-private", action="store_true")
    intro_module.add_argument(
        "--annotation-format",
        choices=["string", "value"],
        default="string",
    )

    intro_package = subparsers.add_parser(
        "introspect-package", help="Introspect a package."
    )
    intro_package.add_argument("--package", required=True)
    intro_package.add_argument("--root")
    intro_package.add_argument("--include-private", action="store_true")
    intro_package.add_argument(
        "--annotation-format",
        choices=["string", "value"],
        default="string",
    )

    args = parser.parse_args(argv)
    payload: dict[str, t.Any]

    if args.command == "parse-files":
        root = pathlib.Path(args.root)
        paths = [pathlib.Path(item) for item in args.paths]
        modules = scan_paths(root, paths, args.include_private)
        payload = {"protocolVersion": PROTOCOL_VERSION, "modules": modules}
    elif args.command == "introspect-module":
        root = pathlib.Path(args.root) if args.root else None
        modules = [
            introspect_module(
                args.module,
                root=root,
                include_private=args.include_private,
                annotation_format=args.annotation_format,
            )
        ]
        payload = {"protocolVersion": PROTOCOL_VERSION, "modules": modules}
    elif args.command == "introspect-package":
        root = pathlib.Path(args.root) if args.root else None
        modules = introspect_package(
            args.package,
            root=root,
            include_private=args.include_private,
            annotation_format=args.annotation_format,
        )
        payload = {"protocolVersion": PROTOCOL_VERSION, "modules": modules}
    else:
        raise ValueError(f"Unsupported command: {args.command}")

    print(json.dumps(payload))
    return 0
