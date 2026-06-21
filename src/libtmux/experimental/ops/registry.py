"""The operation registry: one entry per operation ``kind``.

The registry is the single source of truth that runtime dispatch, serialization,
and the (planned) docs catalog all read from. Each entry is an :class:`OpSpec`
derived from an :class:`~.operation.Operation` subclass's class variables, so the
operation class itself remains authoritative -- the registry just indexes it.

Lookups fail closed: an unknown ``kind`` raises
:class:`~.exc.UnknownOperation`, and registering a duplicate raises
:class:`~.exc.DuplicateOperation` unless ``replace=True``.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

from libtmux.experimental.ops.exc import DuplicateOperation, UnknownOperation

if t.TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from libtmux.experimental.ops._types import Effects, Safety, Scope
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result

OpT = t.TypeVar("OpT", bound="type[Operation[t.Any]]")


@dataclass(frozen=True)
class OpSpec:
    """Indexed metadata for one operation, derived from its class variables.

    Attributes mirror the operation class variables documented on
    :class:`~.operation.Operation`.
    """

    kind: str
    command: str
    scope: Scope
    operation_cls: type[Operation[t.Any]]
    result_cls: type[Result]
    chainable: bool
    primitive: bool
    safety: Safety
    effects: Effects
    min_version: str | None
    flag_version_map: Mapping[str, str]

    @classmethod
    def from_operation(cls, operation_cls: type[Operation[t.Any]]) -> OpSpec:
        """Build a spec by reading an operation class's class variables.

        Examples
        --------
        >>> from libtmux.experimental.ops import SplitWindow
        >>> spec = OpSpec.from_operation(SplitWindow)
        >>> spec.kind, spec.command, spec.scope
        ('split_window', 'split-window', 'window')
        """
        return cls(
            kind=operation_cls.kind,
            command=operation_cls.command,
            scope=operation_cls.scope,
            operation_cls=operation_cls,
            result_cls=operation_cls.result_cls,
            chainable=operation_cls.chainable,
            primitive=operation_cls.primitive,
            safety=operation_cls.safety,
            effects=operation_cls.effects,
            min_version=operation_cls.min_version,
            flag_version_map=operation_cls.flag_version_map,
        )


class OperationRegistry:
    """A fail-closed index of operations keyed by ``kind``.

    Examples
    --------
    >>> from libtmux.experimental.ops import registry, SplitWindow
    >>> "split_window" in registry
    True
    >>> registry.get("split_window").scope
    'window'
    >>> registry.operation("split_window") is SplitWindow
    True
    >>> registry.get("does_not_exist")
    Traceback (most recent call last):
    ...
    libtmux.experimental.ops.exc.UnknownOperation: no operation registered for
    kind 'does_not_exist'
    """

    def __init__(self) -> None:
        self._specs: dict[str, OpSpec] = {}

    def register(
        self,
        operation_cls: type[Operation[t.Any]],
        *,
        replace: bool = False,
    ) -> None:
        """Register an operation class.

        Parameters
        ----------
        operation_cls : type[Operation]
            The operation class to index.
        replace : bool
            Allow replacing an existing registration for the same ``kind``.

        Raises
        ------
        ~libtmux.experimental.ops.exc.DuplicateOperation
            When ``kind`` is already registered and ``replace`` is ``False``.
        """
        kind = operation_cls.kind
        if not replace and kind in self._specs:
            raise DuplicateOperation(kind)
        self._specs[kind] = OpSpec.from_operation(operation_cls)

    def unregister(self, kind: str) -> None:
        """Remove an operation registration.

        Raises
        ------
        ~libtmux.experimental.ops.exc.UnknownOperation
            When ``kind`` is not registered.
        """
        if kind not in self._specs:
            raise UnknownOperation(kind)
        del self._specs[kind]

    def get(self, kind: str) -> OpSpec:
        """Return the :class:`OpSpec` for ``kind`` or fail closed.

        Raises
        ------
        ~libtmux.experimental.ops.exc.UnknownOperation
            When ``kind`` is not registered.
        """
        try:
            return self._specs[kind]
        except KeyError as error:
            raise UnknownOperation(kind) from error

    def operation(self, kind: str) -> type[Operation[t.Any]]:
        """Return the operation class registered for ``kind``."""
        return self.get(kind).operation_cls

    def select(
        self,
        predicate: Callable[[OpSpec], bool] | None = None,
    ) -> list[OpSpec]:
        """Return registered specs (optionally filtered), sorted by ``kind``.

        Named ``select`` rather than ``list`` so the ``-> list[OpSpec]`` return
        annotation is not shadowed by the method name.

        Parameters
        ----------
        predicate : callable, optional
            Keep only specs for which ``predicate(spec)`` is true.

        Examples
        --------
        >>> from libtmux.experimental.ops import registry
        >>> [s.kind for s in registry.select(lambda s: s.safety == "readonly")]
        ['capture_pane', 'display_message', 'has_session', 'list_clients',
        'list_panes', 'list_sessions', 'list_windows', 'save_buffer',
        'show_buffer', 'show_options']
        """
        specs = sorted(self._specs.values(), key=lambda spec: spec.kind)
        if predicate is None:
            return specs
        return [spec for spec in specs if predicate(spec)]

    def kinds(self) -> tuple[str, ...]:
        """Return all registered kinds, sorted."""
        return tuple(sorted(self._specs))

    def __contains__(self, kind: object) -> bool:
        """Whether ``kind`` is registered."""
        return kind in self._specs

    def __iter__(self) -> Iterator[OpSpec]:
        """Iterate specs sorted by ``kind``."""
        return iter(self.select())

    def __len__(self) -> int:
        """Return the number of registered operations."""
        return len(self._specs)


registry = OperationRegistry()
"""The default, process-wide operation registry."""


def register(operation_cls: OpT) -> OpT:
    """Class decorator that registers an operation in the default registry.

    Returns the class unchanged, so it can decorate a class definition.

    Examples
    --------
    >>> from libtmux.experimental.ops import registry
    >>> "send_keys" in registry
    True
    """
    registry.register(operation_cls)
    return operation_cls
