"""Runtime introspection helpers for the autodoc sidecar."""

from __future__ import annotations

import importlib
import inspect
import pathlib
import pkgutil
import sys
import typing as t


def ensure_sys_path(root: pathlib.Path | None) -> None:
    """Ensure the root path is available on sys.path.

    Parameters
    ----------
    root : pathlib.Path | None
        Root path to prepend to sys.path.

    Examples
    --------
    >>> import pathlib
    >>> from pyautodoc_sidecar.introspect import ensure_sys_path
    >>> root = pathlib.Path('.').resolve()
    >>> ensure_sys_path(root)
    """
    if root is None:
        return

    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)


def safe_repr(value: t.Any) -> str | None:
    """Return a safe repr for a value.

    Parameters
    ----------
    value : typing.Any
        Value to represent.

    Returns
    -------
    str | None
        The repr value when available.

    Examples
    --------
    >>> safe_repr(1)
    '1'
    >>> safe_repr(None) is not None
    True
    """
    try:
        return repr(value)
    except Exception:
        return None


def format_annotation_text(annotation: t.Any) -> str | None:
    """Format an annotation for display.

    Parameters
    ----------
    annotation : typing.Any
        Annotation to format.

    Returns
    -------
    str | None
        Text representation of the annotation.

    Examples
    --------
    >>> from pyautodoc_sidecar.introspect import format_annotation_text
    >>> format_annotation_text(int)
    'int'
    """
    if annotation is inspect._empty:
        return None

    try:
        return inspect.formatannotation(annotation)
    except Exception:
        return safe_repr(annotation)


def render_docstring(docstring: str | None) -> dict[str, str | None]:
    """Render a docstring into metadata fields.

    Parameters
    ----------
    docstring : str | None
        Raw docstring text.

    Returns
    -------
    dict[str, str | None]
        Docstring metadata fields.

    Examples
    --------
    >>> result = render_docstring('Hello world')
    >>> result['summary']
    'Hello world'
    """
    if not docstring:
        return {
            "docstringRaw": None,
            "docstringFormat": "unknown",
            "docstringHtml": None,
            "summary": None,
        }

    cleaned = inspect.cleandoc(docstring)
    summary = cleaned.strip().splitlines()[0].strip() if cleaned.strip() else None
    html: str | None = None

    try:
        from docutils.core import publish_parts

        html = publish_parts(cleaned, writer_name="html")["html_body"]
    except Exception:
        html = None

    return {
        "docstringRaw": cleaned,
        "docstringFormat": "rst",
        "docstringHtml": html,
        "summary": summary,
    }


def resolve_annotation_values(
    obj: t.Any, annotation_format: str
) -> dict[str, t.Any]:
    """Resolve evaluated annotation values for an object.

    Parameters
    ----------
    obj : typing.Any
        Object to introspect.
    annotation_format : str
        Annotation format selector.

    Returns
    -------
    dict[str, typing.Any]
        Mapping of annotation names to values.

    Examples
    --------
    >>> def sample(x: int) -> str:
    ...     return str(x)
    >>> mapping = resolve_annotation_values(sample, 'string')
    >>> mapping == {}
    True
    """
    if annotation_format != "value":
        return {}

    try:
        import annotationlib

        return annotationlib.get_annotations(obj, eval_str=True)
    except Exception:
        try:
            return inspect.get_annotations(obj, eval_str=True)
        except Exception:
            return {}


def parameter_kind(kind: inspect._ParameterKind) -> str:
    """Map inspect parameter kinds to schema names.

    Parameters
    ----------
    kind : inspect._ParameterKind
        Parameter kind.

    Returns
    -------
    str
        Normalized kind string.

    Examples
    --------
    >>> import inspect
    >>> parameter_kind(inspect.Parameter.KEYWORD_ONLY)
    'keyword-only'
    """
    mapping = {
        inspect.Parameter.POSITIONAL_ONLY: "positional-only",
        inspect.Parameter.POSITIONAL_OR_KEYWORD: "positional-or-keyword",
        inspect.Parameter.VAR_POSITIONAL: "var-positional",
        inspect.Parameter.KEYWORD_ONLY: "keyword-only",
        inspect.Parameter.VAR_KEYWORD: "var-keyword",
    }
    return mapping.get(kind, "positional-or-keyword")


def introspect_parameters(
    signature: inspect.Signature, annotation_values: dict[str, t.Any]
) -> list[dict[str, str | None]]:
    """Introspect parameters for a callable.

    Parameters
    ----------
    signature : inspect.Signature
        Callable signature.
    annotation_values : dict[str, typing.Any]
        Evaluated annotation values when available.

    Returns
    -------
    list[dict[str, str | None]]
        Parameter records.

    Examples
    --------
    >>> import inspect
    >>> def sample(x: int, *args): return x
    >>> params = introspect_parameters(inspect.signature(sample), {})
    >>> params[0]['name']
    'x'
    """
    params: list[dict[str, str | None]] = []
    for param in signature.parameters.values():
        annotation_value = annotation_values.get(param.name)
        params.append(
            {
                "name": param.name,
                "kind": parameter_kind(param.kind),
                "default": None
                if param.default is inspect._empty
                else safe_repr(param.default),
                "annotationText": format_annotation_text(param.annotation),
                "annotationValue": safe_repr(annotation_value)
                if annotation_value is not None
                else None,
            }
        )
    return params


def introspect_function(
    func: t.Any,
    *,
    kind: str,
    annotation_format: str,
) -> dict[str, t.Any]:
    """Introspect a function or method.

    Parameters
    ----------
    func : typing.Any
        Callable to introspect.
    kind : str
        "function" or "method".
    annotation_format : str
        Annotation format selector.

    Returns
    -------
    dict[str, typing.Any]
        Function record.

    Examples
    --------
    >>> def greet(name: str) -> str:
    ...     return f"hi {name}"
    >>> record = introspect_function(greet, kind='function', annotation_format='string')
    >>> record['name']
    'greet'
    """
    doc_fields = render_docstring(getattr(func, "__doc__", None))
    signature = None

    try:
        signature = inspect.signature(func)
    except Exception:
        signature = inspect.Signature()

    annotation_values = resolve_annotation_values(func, annotation_format)
    params = introspect_parameters(signature, annotation_values)

    return_annotation_value = annotation_values.get("return")
    returns = {
        "annotationText": format_annotation_text(signature.return_annotation),
        "annotationValue": safe_repr(return_annotation_value)
        if return_annotation_value is not None
        else None,
    }

    return {
        "kind": kind,
        "name": func.__name__,
        "qualname": f"{func.__module__}.{func.__qualname__}",
        "module": func.__module__,
        "signature": str(signature),
        "parameters": params,
        "returns": returns,
        "isAsync": inspect.iscoroutinefunction(func),
        "isPrivate": func.__name__.startswith("_"),
        **doc_fields,
    }


def introspect_variable(
    name: str,
    value: t.Any,
    *,
    module_name: str,
    qualname_prefix: str,
    annotation_values: dict[str, t.Any],
) -> dict[str, t.Any]:
    """Introspect a variable.

    Parameters
    ----------
    name : str
        Variable name.
    value : typing.Any
        Variable value.
    module_name : str
        Module name for the variable.
    qualname_prefix : str
        Qualname prefix.
    annotation_values : dict[str, typing.Any]
        Annotation values mapping.

    Returns
    -------
    dict[str, typing.Any]
        Variable record.

    Examples
    --------
    >>> record = introspect_variable('value', 1, module_name='demo', qualname_prefix='demo', annotation_values={})
    >>> record['name']
    'value'
    """
    annotation_value = annotation_values.get(name)
    doc_fields = render_docstring(getattr(value, "__doc__", None))
    return {
        "kind": "variable",
        "name": name,
        "qualname": f"{qualname_prefix}.{name}",
        "module": module_name,
        "value": safe_repr(value),
        "annotationText": format_annotation_text(annotation_value),
        "annotationValue": safe_repr(annotation_value)
        if annotation_value is not None
        else None,
        "isPrivate": name.startswith("_"),
        **doc_fields,
    }


def introspect_class(
    cls: type,
    *,
    include_private: bool,
    annotation_format: str,
) -> dict[str, t.Any]:
    """Introspect a class and its direct members.

    Parameters
    ----------
    cls : type
        Class to introspect.
    include_private : bool
        Whether to include private members.
    annotation_format : str
        Annotation format selector.

    Returns
    -------
    dict[str, typing.Any]
        Class record.

    Examples
    --------
    >>> class Box:
    ...     value: int = 1
    >>> record = introspect_class(Box, include_private=False, annotation_format='string')
    >>> record['name']
    'Box'
    """
    doc_fields = render_docstring(getattr(cls, "__doc__", None))
    bases = [f"{base.__module__}.{base.__qualname__}" for base in cls.__bases__]
    annotation_values = resolve_annotation_values(cls, annotation_format)

    methods: list[dict[str, t.Any]] = []
    attributes: list[dict[str, t.Any]] = []

    for name, value in cls.__dict__.items():
        if not include_private and name.startswith("_"):
            continue

        if isinstance(value, staticmethod):
            func = value.__func__
            methods.append(
                introspect_function(func, kind="method", annotation_format=annotation_format)
            )
            continue

        if isinstance(value, classmethod):
            func = value.__func__
            methods.append(
                introspect_function(func, kind="method", annotation_format=annotation_format)
            )
            continue

        if inspect.isfunction(value):
            methods.append(
                introspect_function(value, kind="method", annotation_format=annotation_format)
            )
            continue

        if inspect.isclass(value) or inspect.ismodule(value):
            continue

        attributes.append(
            introspect_variable(
                name,
                value,
                module_name=cls.__module__,
                qualname_prefix=f"{cls.__module__}.{cls.__qualname__}",
                annotation_values=annotation_values,
            )
        )

    return {
        "kind": "class",
        "name": cls.__name__,
        "qualname": f"{cls.__module__}.{cls.__qualname__}",
        "module": cls.__module__,
        "bases": bases,
        "methods": methods,
        "attributes": attributes,
        "isPrivate": cls.__name__.startswith("_"),
        **doc_fields,
    }


def resolve_public_names(
    module: t.Any, include_private: bool
) -> list[str] | None:
    """Resolve the public names for a module.

    Parameters
    ----------
    module : typing.Any
        Module object.
    include_private : bool
        Whether to include private members.

    Returns
    -------
    list[str] | None
        Public names if defined.

    Examples
    --------
    >>> import types
    >>> mod = types.SimpleNamespace(__all__=['a', 'b'])
    >>> resolve_public_names(mod, False)
    ['a', 'b']
    """
    if include_private:
        return None

    exports = getattr(module, "__all__", None)
    if exports is None:
        return None

    if isinstance(exports, (list, tuple, set)):
        return [str(item) for item in exports]

    return None


def introspect_module(
    module_name: str,
    *,
    root: pathlib.Path | None,
    include_private: bool,
    annotation_format: str,
) -> dict[str, t.Any]:
    """Introspect a module.

    Parameters
    ----------
    module_name : str
        Module name to import.
    root : pathlib.Path | None
        Root path to add to sys.path.
    include_private : bool
        Whether to include private members.
    annotation_format : str
        Annotation format selector.

    Returns
    -------
    dict[str, typing.Any]
        Module record.

    Examples
    --------
    >>> result = introspect_module('json', root=None, include_private=False, annotation_format='string')
    >>> result['kind']
    'module'
    """
    ensure_sys_path(root)
    module = importlib.import_module(module_name)
    doc_fields = render_docstring(getattr(module, "__doc__", None))
    exports = resolve_public_names(module, include_private)

    functions: list[dict[str, t.Any]] = []
    classes: list[dict[str, t.Any]] = []
    variables: list[dict[str, t.Any]] = []

    module_annotations = resolve_annotation_values(module, annotation_format)

    for name, value in inspect.getmembers(module):
        if not include_private and name.startswith("_"):
            if exports is None or name not in exports:
                continue

        if exports is not None and name not in exports:
            continue

        if inspect.isclass(value):
            classes.append(
                introspect_class(
                    value,
                    include_private=include_private,
                    annotation_format=annotation_format,
                )
            )
            continue

        if inspect.isfunction(value) or inspect.isbuiltin(value):
            if getattr(value, "__module__", module_name) != module_name and exports is None:
                continue
            functions.append(
                introspect_function(value, kind="function", annotation_format=annotation_format)
            )
            continue

        if inspect.ismodule(value):
            continue

        variables.append(
            introspect_variable(
                name,
                value,
                module_name=module_name,
                qualname_prefix=module_name,
                annotation_values=module_annotations,
            )
        )

    return {
        "kind": "module",
        "name": module_name.split(".")[-1],
        "qualname": module_name,
        "isPrivate": module_name.split(".")[-1].startswith("_"),
        "classes": classes,
        "functions": functions,
        "variables": variables,
        **doc_fields,
    }


def walk_package_modules(
    package_name: str,
    *,
    root: pathlib.Path | None,
) -> list[str]:
    """Walk modules within a package.

    Parameters
    ----------
    package_name : str
        Package to inspect.
    root : pathlib.Path | None
        Root path to add to sys.path.

    Returns
    -------
    list[str]
        Module names including the package itself.

    Examples
    --------
    >>> modules = walk_package_modules('json', root=None)
    >>> modules[0]
    'json'
    """
    ensure_sys_path(root)
    package = importlib.import_module(package_name)
    names = [package.__name__]

    if not hasattr(package, "__path__"):
        return names

    for module in pkgutil.walk_packages(package.__path__, prefix=f"{package.__name__}."):
        names.append(module.name)

    return names


def introspect_package(
    package_name: str,
    *,
    root: pathlib.Path | None,
    include_private: bool,
    annotation_format: str,
) -> list[dict[str, t.Any]]:
    """Introspect every module within a package.

    Parameters
    ----------
    package_name : str
        Package to inspect.
    root : pathlib.Path | None
        Root path to add to sys.path.
    include_private : bool
        Whether to include private members.
    annotation_format : str
        Annotation format selector.

    Returns
    -------
    list[dict[str, typing.Any]]
        Module records.

    Examples
    --------
    >>> modules = introspect_package('json', root=None, include_private=False, annotation_format='string')
    >>> modules[0]['kind']
    'module'
    """
    modules = []
    for module_name in walk_package_modules(package_name, root=root):
        modules.append(
            introspect_module(
                module_name,
                root=root,
                include_private=include_private,
                annotation_format=annotation_format,
            )
        )
    return modules
