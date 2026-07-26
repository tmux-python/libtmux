"""Custom frozen dataclass implementation that works with inheritance.

This module provides a `frozen_dataclass` decorator that allows creating
effectively immutable dataclasses that can inherit from mutable ones,
which is not possible with standard dataclasses.
"""

from __future__ import annotations

import dataclasses
import functools
import typing as t

from typing_extensions import dataclass_transform

_T = t.TypeVar("_T")


@dataclass_transform(frozen_default=True)
def frozen_dataclass(cls: type[_T]) -> type[_T]:
    """Create a dataclass that's effectively immutable but inherits from non-frozen.

    This decorator:
      1) Applies dataclasses.dataclass(frozen=False) to preserve normal dataclass
         generation
      2) Overrides __setattr__ and __delattr__ to block changes post-init
      3) Tells type-checkers that the resulting class should be treated as frozen

    Parameters
    ----------
    cls : Type[_T]
        The class to convert to a frozen-like dataclass

    Returns
    -------
    Type[_T]
        The processed class with immutability enforced at runtime

    Examples
    --------
    Basic usage:

    >>> @frozen_dataclass
    ... class User:
    ...     id: int
    ...     name: str
    >>> user = User(id=1, name="Alice")
    >>> user.name
    'Alice'
    >>> user.name = "Bob"
    Traceback (most recent call last):
        ...
    AttributeError: User is immutable: cannot modify field 'name'

    Mutating internal attributes (_-prefixed):

    >>> user._cache = {"logged_in": True}
    >>> user._cache
    {'logged_in': True}

    Nested mutable fields limitation:

    >>> @frozen_dataclass
    ... class Container:
    ...     items: list[int]
    >>> c = Container(items=[1, 2])
    >>> c.items.append(3)  # allowed; mutable field itself isn't protected
    >>> c.items
    [1, 2, 3]
    >>> # For deep immutability, use immutable collections (tuple, frozenset)
    >>> @frozen_dataclass
    ... class ImmutableContainer:
    ...     items: tuple[int, ...] = (1, 2)
    >>> ic = ImmutableContainer()
    >>> ic.items
    (1, 2)

    Inheritance from mutable base classes:

    >>> import dataclasses
    >>> @dataclasses.dataclass
    ... class MutableBase:
    ...     value: int
    >>> @frozen_dataclass
    ... class ImmutableSub(MutableBase):
    ...     pass
    >>> obj = ImmutableSub(42)
    >>> obj.value
    42
    >>> obj.value = 100
    Traceback (most recent call last):
        ...
    AttributeError: ImmutableSub is immutable: cannot modify field 'value'

    Security consideration - modifying the _frozen flag:

    >>> @frozen_dataclass
    ... class SecureData:
    ...     secret: str
    >>> data = SecureData(secret="password123")
    >>> data.secret = "hacked"
    Traceback (most recent call last):
        ...
    AttributeError: SecureData is immutable: cannot modify field 'secret'
    >>> # CAUTION: The _frozen attribute can be modified to bypass immutability
    >>> # protection. This is a known limitation of this implementation
    >>> data._frozen = False  # intentionally bypassing immutability
    >>> data.secret = "hacked"  # now works because object is no longer frozen
    >>> data.secret
    'hacked'
    """
    # A. Convert to a dataclass with frozen=False
    cls = dataclasses.dataclass(cls)

    # B. Explicitly annotate and initialize the `_frozen` attribute for static analysis
    cls.__annotations__["_frozen"] = bool
    setattr(cls, "_frozen", False)

    # Save the original __init__ to use in our hooks
    original_init = cls.__init__

    # C. Create a new __init__ that will call the original and then set _frozen flag
    @functools.wraps(original_init)
    def __init__(self: t.Any, *args: t.Any, **kwargs: t.Any) -> None:
        # Call the original __init__
        original_init(self, *args, **kwargs)
        # Set the _frozen flag to make object immutable
        object.__setattr__(self, "_frozen", True)

    # D. Custom attribute assignment method
    def __setattr__(self: t.Any, name: str, value: t.Any) -> None:
        # If _frozen is set and we're trying to set a field, block it
        if getattr(self, "_frozen", False) and not name.startswith("_"):
            # Allow mutation of private (_-prefixed) attributes after initialization
            error_msg = f"{cls.__name__} is immutable: cannot modify field '{name}'"
            raise AttributeError(error_msg)

        # Allow the assignment
        object.__setattr__(self, name, value)

    # E. Custom attribute deletion method
    def __delattr__(self: t.Any, name: str) -> None:
        # If we're frozen, block deletion
        if getattr(self, "_frozen", False):
            error_msg = f"{cls.__name__} is immutable: cannot delete field '{name}'"
            raise AttributeError(error_msg)

        # Allow the deletion
        object.__delattr__(self, name)

    # F. Inject methods into the class (using setattr to satisfy mypy)
    setattr(cls, "__init__", __init__)  # Sets _frozen flag post-initialization
    setattr(cls, "__setattr__", __setattr__)  # Blocks attribute modification post-init
    setattr(cls, "__delattr__", __delattr__)  # Blocks attribute deletion post-init

    return cls
