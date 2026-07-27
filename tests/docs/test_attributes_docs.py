"""Field-documentation contract for first-party record classes."""

from __future__ import annotations

import dataclasses
import importlib
import pkgutil
import typing as t

from sphinx.ext.napoleon.docstring import NumpyDocstring

import libtmux


def _is_named_tuple(value: type[object]) -> bool:
    """Return whether *value* is a ``NamedTuple`` class."""
    return issubclass(value, tuple) and isinstance(
        value.__dict__.get("_fields"),
        tuple,
    )


def _is_record(value: type[object]) -> bool:
    """Return whether *value* declares structured fields."""
    return (
        dataclasses.is_dataclass(value)
        or _is_named_tuple(value)
        or t.is_typeddict(value)
    )


def _iter_record_classes() -> t.Iterator[type[object]]:
    """Yield each first-party record class once."""
    modules = [libtmux]
    modules.extend(
        importlib.import_module(module_info.name)
        for module_info in pkgutil.walk_packages(
            libtmux.__path__,
            prefix=f"{libtmux.__name__}.",
        )
        if not module_info.name.endswith(".__main__")
        and not module_info.name.startswith("libtmux._vendor")
    )

    seen: set[type[object]] = set()
    for module in modules:
        for value in vars(module).values():
            if (
                not isinstance(value, type)
                or value.__module__ != module.__name__
                or value in seen
            ):
                continue
            if _is_record(value):
                seen.add(value)
                yield value


def _field_names(value: type[object]) -> tuple[str, ...]:
    """Return effective field names in their runtime order."""
    if dataclasses.is_dataclass(value):
        return tuple(field.name for field in dataclasses.fields(value))
    if _is_named_tuple(value):
        return t.cast(tuple[str, ...], value.__dict__["_fields"])
    annotations = t.cast(
        t.Mapping[str, object],
        value.__annotations__,
    )
    return tuple(annotations)


def _own_attribute_docs(value: type[object]) -> dict[str, str]:
    """Return NumPy ``Attributes`` declared by *value*."""
    docstring = t.cast(str | None, value.__dict__.get("__doc__"))
    lines = NumpyDocstring(docstring or "").lines()
    documented: dict[str, str] = {}
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.startswith(".. attribute:: "):
            index += 1
            continue
        name = line.removeprefix(".. attribute:: ").strip()
        index += 1
        body: list[str] = []
        while index < len(lines) and not lines[index].startswith(".. "):
            candidate = lines[index].strip()
            if candidate and not candidate.startswith(":type:"):
                body.append(candidate)
            index += 1
        documented[name] = " ".join(body)
    return documented


def _attribute_docs(value: type[object]) -> dict[str, str]:
    """Return field documentation inherited by *value*."""
    documented: dict[str, str] = {}
    for base in _documentation_lineage(value):
        documented.update(_own_attribute_docs(base))
    return documented


def _documentation_lineage(
    value: type[object],
) -> t.Iterator[type[object]]:
    """Yield documentation bases before the class that overrides them."""
    if not t.is_typeddict(value):
        yield from reversed(value.__mro__)
        return

    original_bases = t.cast(
        tuple[object, ...],
        vars(value).get("__orig_bases__", ()),
    )
    for base in original_bases:
        if isinstance(base, type) and t.is_typeddict(base):
            yield from _documentation_lineage(base)
    yield value


def test_attribute_parser_stops_at_following_section() -> None:
    """A later section cannot satisfy an empty field description."""

    @dataclasses.dataclass
    class Value:
        """A value with an empty field description.

        Attributes
        ----------
        field : str

        Notes
        -----
        This prose describes the class, not ``field``.
        """

        field: str

    assert _own_attribute_docs(Value) == {"field": ""}


def test_record_field_names_include_supported_declarations() -> None:
    """Field discovery covers each supported declarative record shape."""

    @dataclasses.dataclass
    class DataRecord:
        first: str
        second: int

    class ClassNamedTuple(t.NamedTuple):
        first: str
        second: int

    FunctionalNamedTuple = t.NamedTuple(  # noqa: UP014
        "FunctionalNamedTuple",
        [("first", str), ("second", int)],
    )

    class BaseTypedRecord(t.TypedDict):
        """Base mapping record.

        Attributes
        ----------
        first : str
            First value.
        """

        first: str

    class TypedRecord(BaseTypedRecord):
        """Extended mapping record.

        Attributes
        ----------
        second : int
            Second value.
        """

        second: int

    records = (DataRecord, ClassNamedTuple, FunctionalNamedTuple, TypedRecord)

    assert [_field_names(record) for record in records] == [
        ("first", "second"),
        ("first", "second"),
        ("first", "second"),
        ("first", "second"),
    ]
    assert tuple(_attribute_docs(TypedRecord)) == ("first", "second")


def test_inherited_attribute_docs_follow_record_mro() -> None:
    """The most specific field declaration supplies effective prose."""

    @dataclasses.dataclass
    class BaseRecord:
        """Generic record.

        Attributes
        ----------
        value : str
            Generic value.
        """

        value: str

    @dataclasses.dataclass
    class SpecializedRecord(BaseRecord):
        """Specialized record.

        Attributes
        ----------
        value : str
            Value interpreted by the specialized record.
        """

        value: str

    assert _attribute_docs(SpecializedRecord)["value"] == (
        "Value interpreted by the specialized record."
    )


def test_first_party_record_fields_use_attributes_sections() -> None:
    """Every first-party record field has semantic ``Attributes`` prose."""
    missing: dict[str, list[str]] = {}
    empty: dict[str, list[str]] = {}
    out_of_order: dict[str, list[str]] = {}

    for value in _iter_record_classes():
        fields = _field_names(value)
        documented = _attribute_docs(value)
        absent = [name for name in fields if name not in documented]
        blank = [name for name in fields if name in documented and not documented[name]]
        ordered = tuple(name for name in documented if name in fields)
        if absent:
            missing[f"{value.__module__}.{value.__qualname__}"] = absent
        if blank:
            empty[f"{value.__module__}.{value.__qualname__}"] = blank
        if not absent and ordered != fields:
            out_of_order[f"{value.__module__}.{value.__qualname__}"] = list(ordered)

    assert not missing, f"Fields missing from Attributes sections: {missing}"
    assert not empty, f"Fields with empty Attributes prose: {empty}"
    assert not out_of_order, f"Attributes not in field order: {out_of_order}"
