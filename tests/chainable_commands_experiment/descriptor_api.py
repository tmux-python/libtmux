"""Typed descriptor experiment for command metadata."""

from __future__ import annotations

import typing as t

from .shared import (
    CommandCall,
    CommandSpec,
    new_window_call,
    split_window_call,
)


class NewWindowCommand:
    """Bound command object for ``new-window``."""

    spec = CommandSpec(name="new-window", scope="session")

    def __call__(
        self,
        *,
        window_name: str | None = None,
        detach: bool = True,
    ) -> CommandCall:
        """Build a ``new-window`` call."""
        return new_window_call(window_name=window_name, detach=detach)


class SplitWindowCommand:
    """Bound command object for ``split-window``."""

    spec = CommandSpec(name="split-window", scope="window")

    def __call__(
        self,
        *,
        horizontal: bool = False,
        percentage: int | None = None,
    ) -> CommandCall:
        """Build a ``split-window`` call."""
        return split_window_call(horizontal=horizontal, percentage=percentage)


class NewWindowDescriptor:
    """Descriptor that binds ``new-window`` command objects."""

    @t.overload
    def __get__(
        self,
        instance: None,
        owner: type[object] | None = None,
    ) -> NewWindowDescriptor: ...

    @t.overload
    def __get__(
        self,
        instance: object,
        owner: type[object] | None = None,
    ) -> NewWindowCommand: ...

    def __get__(
        self,
        instance: object | None,
        owner: type[object] | None = None,
    ) -> NewWindowDescriptor | NewWindowCommand:
        """Bind the descriptor to an instance."""
        if instance is None:
            return self
        return NewWindowCommand()


class SplitWindowDescriptor:
    """Descriptor that binds ``split-window`` command objects."""

    @t.overload
    def __get__(
        self,
        instance: None,
        owner: type[object] | None = None,
    ) -> SplitWindowDescriptor: ...

    @t.overload
    def __get__(
        self,
        instance: object,
        owner: type[object] | None = None,
    ) -> SplitWindowCommand: ...

    def __get__(
        self,
        instance: object | None,
        owner: type[object] | None = None,
    ) -> SplitWindowDescriptor | SplitWindowCommand:
        """Bind the descriptor to an instance."""
        if instance is None:
            return self
        return SplitWindowCommand()


class Commands:
    """Container exposing typed command descriptors."""

    new_window = NewWindowDescriptor()
    split_window = SplitWindowDescriptor()
