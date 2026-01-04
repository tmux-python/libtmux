"""Python AST scanner for libtmux docs."""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import typing as t


def node_to_source(node: ast.AST | None) -> str | None:
    """Return source-like text for an AST node.

    Parameters
    ----------
    node : ast.AST | None
        Node to render as source.

    Returns
    -------
    str | None
        Source string for the node when available.

    Examples
    --------
    >>> import ast
    >>> tree = ast.parse('x = 1')
    >>> node_to_source(tree.body[0].value)
    '1'
    """
    if node is None:
        return None

    try:
        return ast.unparse(node)
    except Exception:
        return None


def node_location(node: ast.AST) -> dict[str, int | None]:
    """Return a location dictionary for a node.

    Parameters
    ----------
    node : ast.AST
        Node with location metadata.

    Returns
    -------
    dict[str, int | None]
        Location metadata for the node.

    Examples
    --------
    >>> import ast
    >>> tree = ast.parse('x = 1')
    >>> node_location(tree.body[0])['lineno']
    1
    """
    lineno = int(getattr(node, "lineno", 1) or 1)
    col_offset = int(getattr(node, "col_offset", 0) or 0)
    end_lineno = getattr(node, "end_lineno", None)
    end_col_offset = getattr(node, "end_col_offset", None)

    return {
        "lineno": lineno,
        "colOffset": col_offset,
        "endLineno": int(end_lineno) if end_lineno is not None else None,
        "endColOffset": int(end_col_offset) if end_col_offset is not None else None,
    }


def is_private(name: str) -> bool:
    """Return True when a name should be considered private.

    Parameters
    ----------
    name : str
        Name to test.

    Returns
    -------
    bool
        True when the name is private.

    Examples
    --------
    >>> is_private('_hidden')
    True
    >>> is_private('visible')
    False
    """
    return name.startswith("_")


def parse_parameters(args: ast.arguments) -> list[dict[str, str | None]]:
    """Parse function parameters into serializable dictionaries.

    Parameters
    ----------
    args : ast.arguments
        Arguments structure from a function definition.

    Returns
    -------
    list[dict[str, str | None]]
        Parsed parameter records.

    Examples
    --------
    >>> import ast
    >>> tree = ast.parse('def f(a, b=1, *args, c=2, **kwargs): pass')
    >>> params = parse_parameters(tree.body[0].args)
    >>> params[0]['name']
    'a'
    """
    params: list[dict[str, str | None]] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)

    for param, default in zip(positional, defaults, strict=True):
        kind = (
            "positional-only" if param in args.posonlyargs else "positional-or-keyword"
        )
        params.append(
            {
                "name": param.arg,
                "kind": kind,
                "annotation": node_to_source(param.annotation),
                "default": node_to_source(default),
            }
        )

    if args.vararg is not None:
        params.append(
            {
                "name": args.vararg.arg,
                "kind": "var-positional",
                "annotation": node_to_source(args.vararg.annotation),
                "default": None,
            }
        )

    for kwonly, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        params.append(
            {
                "name": kwonly.arg,
                "kind": "keyword-only",
                "annotation": node_to_source(kwonly.annotation),
                "default": node_to_source(default),
            }
        )

    if args.kwarg is not None:
        params.append(
            {
                "name": args.kwarg.arg,
                "kind": "var-keyword",
                "annotation": node_to_source(args.kwarg.annotation),
                "default": None,
            }
        )

    return params


def parse_function(
    node: ast.FunctionDef | ast.AsyncFunctionDef, qualname: str
) -> dict[str, t.Any]:
    r"""Parse a function or method definition.

    Parameters
    ----------
    node : ast.FunctionDef | ast.AsyncFunctionDef
        Function node to parse.
    qualname : str
        Fully qualified name for the function.

    Returns
    -------
    dict[str, typing.Any]
        Parsed function record.

    Examples
    --------
    >>> import ast
    >>> tree = ast.parse('def f(a: int) -> str:\n    return "x"')
    >>> parsed = parse_function(tree.body[0], 'mod.f')
    >>> parsed['name']
    'f'
    """
    decorators = [
        value
        for value in (node_to_source(item) for item in node.decorator_list)
        if value
    ]

    return {
        "kind": "function",
        "name": node.name,
        "qualname": qualname,
        "docstring": ast.get_docstring(node),
        "decorators": decorators,
        "parameters": parse_parameters(node.args),
        "returns": node_to_source(node.returns),
        "isAsync": isinstance(node, ast.AsyncFunctionDef),
        "isPrivate": is_private(node.name),
        "location": node_location(node),
    }


def parse_assignment(
    node: ast.Assign | ast.AnnAssign, qualname: str
) -> list[dict[str, t.Any]]:
    """Parse assignment statements into variables.

    Parameters
    ----------
    node : ast.Assign | ast.AnnAssign
        Assignment node to parse.
    qualname : str
        Qualname prefix for the variable.

    Returns
    -------
    list[dict[str, typing.Any]]
        Parsed variable records.

    Examples
    --------
    >>> import ast
    >>> tree = ast.parse('x: int = 3')
    >>> parsed = parse_assignment(tree.body[0], 'mod')
    >>> parsed[0]['name']
    'x'
    """
    variables: list[dict[str, t.Any]] = []

    if isinstance(node, ast.Assign):
        targets = [item for item in node.targets if isinstance(item, ast.Name)]
        annotation = None
        value = node_to_source(node.value)
    else:
        targets = [node.target] if isinstance(node.target, ast.Name) else []
        annotation = node_to_source(node.annotation)
        value = node_to_source(node.value)

    for target in targets:
        if not isinstance(target, ast.Name):
            continue
        name = target.id
        variables.append(
            {
                "kind": "variable",
                "name": name,
                "qualname": f"{qualname}.{name}" if qualname else name,
                "annotation": annotation,
                "value": value,
                "docstring": None,
                "isPrivate": is_private(name),
                "location": node_location(node),
            }
        )

    return variables


def parse_class(node: ast.ClassDef, qualname: str) -> dict[str, t.Any]:
    r"""Parse a class definition with methods and attributes.

    Parameters
    ----------
    node : ast.ClassDef
        Class node to parse.
    qualname : str
        Qualname for the class.

    Returns
    -------
    dict[str, typing.Any]
        Parsed class record.

    Examples
    --------
    >>> import ast
    >>> tree = ast.parse('class Box:\n    value: int = 1')
    >>> parsed = parse_class(tree.body[0], 'mod.Box')
    >>> parsed['name']
    'Box'
    """
    methods: list[dict[str, t.Any]] = []
    attributes: list[dict[str, t.Any]] = []

    for item in node.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(parse_function(item, f"{qualname}.{item.name}"))
        elif isinstance(item, (ast.Assign, ast.AnnAssign)):
            attributes.extend(parse_assignment(item, qualname))

    decorators = [
        value
        for value in (node_to_source(item) for item in node.decorator_list)
        if value
    ]
    bases = [value for value in (node_to_source(item) for item in node.bases) if value]

    return {
        "kind": "class",
        "name": node.name,
        "qualname": qualname,
        "docstring": ast.get_docstring(node),
        "bases": bases,
        "decorators": decorators,
        "methods": methods,
        "attributes": attributes,
        "isPrivate": is_private(node.name),
        "location": node_location(node),
    }


def parse_import(node: ast.Import | ast.ImportFrom) -> dict[str, t.Any]:
    """Parse an import statement.

    Parameters
    ----------
    node : ast.Import | ast.ImportFrom
        Import node to parse.

    Returns
    -------
    dict[str, typing.Any]
        Parsed import record.

    Examples
    --------
    >>> import ast
    >>> tree = ast.parse('from pathlib import Path as P')
    >>> parsed = parse_import(tree.body[0])
    >>> parsed['module']
    'pathlib'
    """
    names = []
    for alias in node.names:
        if alias.asname:
            names.append(f"{alias.name} as {alias.asname}")
        else:
            names.append(alias.name)

    module = getattr(node, "module", None)
    if module is None and isinstance(node, ast.Import) and len(node.names) == 1:
        module = node.names[0].name

    return {
        "kind": "import",
        "module": module,
        "names": names,
        "level": getattr(node, "level", None),
        "location": node_location(node),
    }


def parse_module(
    path: pathlib.Path, module_name: str, include_private: bool
) -> dict[str, t.Any]:
    """Parse a module into a serializable record.

    Parameters
    ----------
    path : pathlib.Path
        File path to the module.
    module_name : str
        Qualified module name.
    include_private : bool
        Whether to include private members.

    Returns
    -------
    dict[str, typing.Any]
        Parsed module record.

    Examples
    --------
    >>> import pathlib
    >>> import tempfile
    >>> root = pathlib.Path(tempfile.mkdtemp())
    >>> module_path = root / 'sample.py'
    >>> _ = module_path.write_text('value: int = 1')
    >>> parsed = parse_module(module_path, 'sample', True)
    >>> parsed['name']
    'sample'
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    items: list[dict[str, t.Any]] = []
    imports: list[dict[str, t.Any]] = []
    exports: list[str] = []

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports.append(parse_import(node))
            continue

        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            variables = parse_assignment(node, module_name)
            for variable in variables:
                if variable["name"] == "__all__" and variable["value"]:
                    try:
                        exports = list(ast.literal_eval(variable["value"]))
                    except Exception:
                        exports = []
                    continue

                if not include_private and variable["isPrivate"]:
                    continue

                items.append(variable)
            continue

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not include_private and is_private(node.name):
                continue
            items.append(parse_function(node, f"{module_name}.{node.name}"))
            continue

        if isinstance(node, ast.ClassDef):
            if not include_private and is_private(node.name):
                continue
            items.append(parse_class(node, f"{module_name}.{node.name}"))

    module_location = node_location(tree)

    return {
        "kind": "module",
        "name": module_name.split(".")[-1],
        "qualname": module_name,
        "path": str(path),
        "docstring": ast.get_docstring(tree),
        "items": items,
        "imports": imports,
        "exports": exports,
        "isPackage": path.name == "__init__.py",
        "location": module_location,
    }


def walk_python_files(
    root: pathlib.Path, paths: list[pathlib.Path]
) -> list[tuple[pathlib.Path, str]]:
    """Collect Python files from a list of paths.

    Parameters
    ----------
    root : pathlib.Path
        Root path used for module names.
    paths : list[pathlib.Path]
        File or directory paths to scan.

    Returns
    -------
    list[tuple[pathlib.Path, str]]
        Tuples of file paths and module names.

    Examples
    --------
    >>> import pathlib
    >>> import tempfile
    >>> root = pathlib.Path(tempfile.mkdtemp())
    >>> pkg = root / 'pkg'
    >>> pkg.mkdir()
    >>> _ = (pkg / '__init__.py').write_text('')
    >>> files = walk_python_files(root, [pkg])
    >>> files[0][1]
    'pkg'
    """
    ignore_dirs = {
        ".git",
        ".venv",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".mypy_cache",
        ".pytest_cache",
    }
    results: list[tuple[pathlib.Path, str]] = []

    for entry in paths:
        if entry.is_file() and entry.suffix == ".py":
            file_paths = [entry]
        elif entry.is_dir():
            file_paths = [
                item
                for item in entry.rglob("*.py")
                if not any(part in ignore_dirs for part in item.parts)
            ]
        else:
            file_paths = []

        for file_path in file_paths:
            relative = file_path.relative_to(root)
            module_parts = list(relative.with_suffix("").parts)
            if module_parts[-1] == "__init__":
                module_parts = module_parts[:-1]
            module_name = ".".join(module_parts)
            results.append((file_path, module_name))

    return results


def scan_paths(
    root: pathlib.Path, paths: list[pathlib.Path], include_private: bool
) -> list[dict[str, t.Any]]:
    """Scan paths and return parsed modules.

    Parameters
    ----------
    root : pathlib.Path
        Root used for module name resolution.
    paths : list[pathlib.Path]
        File or directory paths to scan.
    include_private : bool
        Whether to include private members.

    Returns
    -------
    list[dict[str, typing.Any]]
        Parsed module records.

    Examples
    --------
    >>> import pathlib
    >>> import tempfile
    >>> root = pathlib.Path(tempfile.mkdtemp())
    >>> module_path = root / 'demo.py'
    >>> _ = module_path.write_text('value = 1')
    >>> modules = scan_paths(root, [module_path], True)
    >>> modules[0]['qualname']
    'demo'
    """
    modules: list[dict[str, t.Any]] = []
    for file_path, module_name in walk_python_files(root, paths):
        modules.append(parse_module(file_path, module_name, include_private))
    return modules


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scan Python modules for libtmux docs."
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--paths", nargs="+", required=True)
    parser.add_argument("--include-private", action="store_true")
    args = parser.parse_args()

    root_path = pathlib.Path(args.root)
    scan_paths_input = [pathlib.Path(item) for item in args.paths]
    data = scan_paths(root_path, scan_paths_input, args.include_private)
    print(json.dumps(data))
