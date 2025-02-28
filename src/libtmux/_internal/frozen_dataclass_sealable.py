"""Custom frozen dataclass implementation.

With field-level mutability control and sealing.

This module provides an enhanced version of the frozen dataclass concept from the
standard dataclasses module, with the following features:

1. Field-level mutability control:

   Use the ``mutable_during_init`` decorator to mark fields that should be mutable
   during the initialization phase but become immutable after sealing.

2. Two-phase initialization:

   - Objects start in an "initializing" state where designated fields can be modified.
   - Objects can be explicitly sealed to prevent further modification of any fields.

3. Circular reference support:

   Create objects, establish circular references between them, then seal
   them together.

4. Backward compatibility:

   Objects are immutable by default, sealing occurs automatically at the end of
   initialization unless explicitly deferred.

Limitations:

By design, to keep the implementation simple, the following are not supported:
- Private attributes
- Deep copying on sealing
- Slots
"""

from __future__ import annotations

import dataclasses
import functools
import typing as t
from typing import (
    Any,
    Callable,
    Protocol,
    TypeVar,
    runtime_checkable,
)

# Type definitions for better type hints
T = TypeVar("T", bound=type)


@runtime_checkable
class SealableProtocol(Protocol):
    """Protocol defining the interface for sealable objects."""

    _sealed: bool

    def seal(self, deep: bool = False) -> None:
        """Seal the object to prevent further modifications.

        Parameters
        ----------
        deep : bool, optional
            If True, recursively seal any nested sealable objects, by default False
        """
        ...

    @classmethod
    def is_sealable(cls) -> bool:
        """Check if this class is sealable.

        Returns
        -------
        bool
            True if the class is sealable, False otherwise
        """
        ...


class Sealable:
    """Base class for sealable objects.

    This class provides the basic implementation of the SealableProtocol,
    which can be used for explicit inheritance to create sealable classes.

    Attributes
    ----------
    _sealed : bool
        Whether the object is sealed or not
    """

    _sealed: bool = False

    def seal(self, deep: bool = False) -> None:
        """Seal the object to prevent further modifications.

        Parameters
        ----------
        deep : bool, optional
            If True, recursively seal any nested sealable objects, by default False
        """
        # Basic implementation that can be overridden by subclasses
        object.__setattr__(self, "_sealed", True)

    @classmethod
    def is_sealable(cls) -> bool:
        """Check if this class is sealable.

        Returns
        -------
        bool
            Always returns True for Sealable and its subclasses
        """
        return True


def mutable_field(
    factory: Callable[[], Any] = list,
) -> dataclasses.Field[Any]:
    """Create a field that is mutable during initialization but immutable after sealing.

    Parameters
    ----------
    factory : callable, optional
        A callable that returns the default value for the field, by default list

    Returns
    -------
    dataclasses.Field
        A dataclass Field with metadata indicating it's mutable during initialization
    """
    return dataclasses.field(
        default_factory=factory, metadata={"mutable_during_init": True}
    )


def mutable_during_init(
    field_method: Callable[[], T] | None = None,
) -> Any:  # mypy doesn't handle complex return types well here
    """Mark a field as mutable during initialization but immutable after sealing.

    This decorator applies to a method that returns the field's default value.

    Parameters
    ----------
    field_method : callable, optional
        A method that returns the default value for the field, by default None

    Returns
    -------
    dataclasses.Field
        A dataclass Field with metadata indicating it's mutable during initialization

    Examples
    --------
    >>> from dataclasses import field
    >>> from libtmux._internal.frozen_dataclass_sealable import (
    ...     frozen_dataclass_sealable, mutable_during_init
    ... )
    >>>
    >>> @frozen_dataclass_sealable
    ... class Example:
    ...     name: str
    ...     items: list[str] = field(
    ...         default_factory=list,
    ...         metadata={"mutable_during_init": True}
    ...     )

    Create an instance with deferred sealing:

    >>> example = Example(name="test-example")

    Cannot modify immutable fields even before sealing:

    >>> try:
    ...     example.name = "new-name"
    ... except AttributeError as e:
    ...     print(f"Error: {type(e).__name__}")
    Error: AttributeError

    Can modify mutable field before sealing:

    >>> example.items.append("item1")
    >>> example.items
    ['item1']

    Now seal the object:

    >>> example.seal()

    Verify the object is sealed:

    >>> hasattr(example, "_sealed") and example._sealed
    True

    Cannot modify mutable field after sealing:

    >>> try:
    ...     example.items = ["new-item"]
    ... except AttributeError as e:
    ...     print(f"Error: {type(e).__name__}")
    Error: AttributeError

    But can still modify the contents of mutable containers:

    >>> example.items.append("item2")
    >>> example.items
    ['item1', 'item2']
    """
    if field_method is None:
        # Used with parentheses: @mutable_during_init()
        return t.cast(
            t.Callable[[t.Callable[[], T]], dataclasses.Field[t.Any]],
            functools.partial(mutable_during_init),
        )

    # Used without parentheses: @mutable_during_init
    if not callable(field_method):
        error_msg = "mutable_during_init must decorate a method"
        raise TypeError(error_msg)

    # Get the default value by calling the method
    # Note: This doesn't have access to self, so it must be a standalone function
    default_value = field_method()

    # Create and return a field with custom metadata
    return dataclasses.field(
        default=default_value, metadata={"mutable_during_init": True}
    )


def is_sealable(cls_or_obj: Any) -> bool:
    """Check if a class or object is sealable.

    Parameters
    ----------
    cls_or_obj : Any
        The class or object to check

    Returns
    -------
    bool
        True if the class or object is sealable, False otherwise

    Examples
    --------
    >>> from dataclasses import dataclass
    >>> from libtmux._internal.frozen_dataclass_sealable import (
    ...     frozen_dataclass_sealable, is_sealable, Sealable, SealableProtocol
    ... )

    >>> # Regular class is not sealable
    >>> @dataclass
    ... class Regular:
    ...     value: int

    >>> is_sealable(Regular)
    False
    >>> regular = Regular(value=42)
    >>> is_sealable(regular)
    False

    >>> # Non-class objects are not sealable
    >>> is_sealable("string")
    False
    >>> is_sealable(42)
    False
    >>> is_sealable(None)
    False

    >>> # Classes explicitly inheriting from Sealable are sealable
    >>> @dataclass
    ... class ExplicitSealable(Sealable):
    ...     value: int

    >>> is_sealable(ExplicitSealable)
    True
    >>> explicit = ExplicitSealable(value=42)
    >>> is_sealable(explicit)
    True

    >>> # Classes decorated with frozen_dataclass_sealable are sealable
    >>> @frozen_dataclass_sealable
    ... class DecoratedSealable:
    ...     value: int

    >>> is_sealable(DecoratedSealable)
    True
    >>> decorated = DecoratedSealable(value=42)
    >>> is_sealable(decorated)
    True

    >>> # Classes that implement SealableProtocol are sealable
    >>> class CustomSealable:
    ...     _sealed = False
    ...     def seal(self, deep=False):
    ...         self._sealed = True
    ...     @classmethod
    ...     def is_sealable(cls):
    ...         return True

    >>> is_sealable(CustomSealable)
    True
    >>> custom = CustomSealable()
    >>> is_sealable(custom)
    True
    """
    # Check if the object is an instance of SealableProtocol
    if isinstance(cls_or_obj, SealableProtocol):
        return True

    # If it's a class, check if it's a subclass of Sealable or has a seal method
    if isinstance(cls_or_obj, type):
        # Check if it's a subclass of Sealable
        if issubclass(cls_or_obj, Sealable):
            return True
        # For backward compatibility, check if it has a seal method
        return hasattr(cls_or_obj, "seal") and callable(cls_or_obj.seal)

    # If it's an instance, check if it has a seal method
    return hasattr(cls_or_obj, "seal") and callable(cls_or_obj.seal)


def frozen_dataclass_sealable(cls: type) -> type:
    """Create a dataclass that is immutable, with field-level mutability control.

    Enhances the standard dataclass with:

    - Core immutability (like dataclasses.frozen=True)
    - Field-level mutability control during initialization
    - Explicit sealing mechanism
    - Support for inheritance from mutable base classes

    Parameters
    ----------
    cls : type
        The class to decorate

    Returns
    -------
    type
        The decorated class with immutability features

    Examples
    --------
    Basic usage:

    >>> from dataclasses import field
    >>> from typing import Optional
    >>> from libtmux._internal.frozen_dataclass_sealable import (
    ...     frozen_dataclass_sealable, is_sealable
    ... )
    >>>
    >>> @frozen_dataclass_sealable
    ... class Config:
    ...     name: str
    ...     values: dict[str, int] = field(
    ...         default_factory=dict,
    ...         metadata={"mutable_during_init": True}
    ...     )

    Create an instance:

    >>> config = Config(name="test-config")
    >>> config.name
    'test-config'

    Cannot modify frozen field:

    >>> try:
    ...     config.name = "modified"
    ... except AttributeError as e:
    ...     print(f"Error: {type(e).__name__}")
    Error: AttributeError

    Can modify mutable field before sealing:

    >>> config.values["key1"] = 100
    >>> config.values
    {'key1': 100}

    Can also directly assign to mutable field before sealing:

    >>> new_values = {"key2": 200}
    >>> config.values = new_values
    >>> config.values
    {'key2': 200}

    Seal the object:

    >>> config.seal()

    Verify the object is sealed:

    >>> hasattr(config, "_sealed") and config._sealed
    True

    Cannot modify mutable field after sealing:

    >>> try:
    ...     config.values = {"key3": 300}
    ... except AttributeError as e:
    ...     print(f"Error: {type(e).__name__}")
    Error: AttributeError

    But can still modify the contents of mutable containers after sealing:

    >>> config.values["key3"] = 300
    >>> config.values
    {'key2': 200, 'key3': 300}

    With deferred sealing:

    >>> @frozen_dataclass_sealable
    ... class Node:
    ...     value: int
    ...     next_node: Optional['Node'] = field(
    ...         default=None,
    ...         metadata={"mutable_during_init": True}
    ...     )

    Create a linked list:

    >>> node1 = Node(value=1)  # Not sealed automatically
    >>> node2 = Node(value=2)  # Not sealed automatically

    Can modify mutable field before sealing:

    >>> node1.next_node = node2

    Verify structure:

    >>> node1.value
    1
    >>> node2.value
    2
    >>> node1.next_node is node2
    True

    Seal nodes:

    >>> node1.seal()
    >>> node2.seal()

    Verify sealed status:

    >>> hasattr(node1, "_sealed") and node1._sealed
    True
    >>> hasattr(node2, "_sealed") and node2._sealed
    True

    Cannot modify mutable field after sealing:

    >>> try:
    ...     node1.next_node = None
    ... except AttributeError as e:
    ...     print(f"Error: {type(e).__name__}")
    Error: AttributeError
    """
    # Support both @frozen_dataclass_sealable and @frozen_dataclass_sealable() usage
    # This branch is for direct decorator usage: @frozen_dataclass_sealable
    if not isinstance(cls, type):
        err_msg = "Expected a class when calling frozen_dataclass_sealable directly"
        raise TypeError(err_msg)

    # From here, we know cls is not None, so we can safely use cls.__name__
    class_name = cls.__name__

    # Convert the class to a dataclass if it's not already one
    # CRITICAL: Explicitly set frozen=False to preserve inheritance flexibility
    # Our custom __setattr__ and __delattr__ will handle immutability
    if not dataclasses.is_dataclass(cls):
        # Explicitly set frozen=False to preserve inheritance flexibility
        cls = dataclasses.dataclass(frozen=False)(cls)

    # Store the original __post_init__ if it exists
    original_post_init = getattr(cls, "__post_init__", None)

    # Keep track of fields that can be modified during initialization
    mutable_fields = set()

    # Get all fields from the class hierarchy
    all_fields = {}

    # Get all fields from the class hierarchy
    for base_cls in cls.__mro__:
        if hasattr(base_cls, "__dataclass_fields__"):
            for name, field_obj in base_cls.__dataclass_fields__.items():
                # Don't override fields from derived classes
                if name not in all_fields:
                    all_fields[name] = field_obj
                    # Check if this field should be mutable during initialization
                    if (
                        field_obj.metadata.get("mutable_during_init", False)
                        and name not in mutable_fields
                    ):
                        mutable_fields.add(name)

    # Custom attribute setting implementation
    def custom_setattr(self: Any, name: str, value: Any) -> None:
        # Allow setting private attributes always
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return

        # Check if object is in initialization phase
        initializing = getattr(self, "_initializing", False)

        # Check if object has been sealed
        sealed = getattr(self, "_sealed", False)

        # If sealed, block all field modifications
        if sealed:
            error_msg = f"{class_name} is sealed: cannot modify field '{name}'"
            raise AttributeError(error_msg)

        # If initializing or this is a mutable field during init phase
        if initializing or (not sealed and name in mutable_fields):
            object.__setattr__(self, name, value)
            return

        # Otherwise, prevent modifications
        error_msg = f"{class_name} is immutable: cannot modify field '{name}'"
        raise AttributeError(error_msg)

    # Custom attribute deletion implementation
    def custom_delattr(self: Any, name: str) -> None:
        if name.startswith("_"):
            object.__delattr__(self, name)
            return

        sealed = getattr(self, "_sealed", False)
        if sealed:
            error_msg = f"{class_name} is sealed: cannot delete field '{name}'"
            raise AttributeError(error_msg)

        error_msg = f"{class_name} is immutable: cannot delete field '{name}'"
        raise AttributeError(error_msg)

    # Custom initialization to set initial attribute values
    def custom_init(self: Any, *args: Any, **kwargs: Any) -> None:
        # Set the initializing flag
        object.__setattr__(self, "_initializing", True)
        object.__setattr__(self, "_sealed", False)

        # Collect required field names from all classes in the hierarchy
        required_fields = set()
        for name, field_obj in all_fields.items():
            # A field is required if it has no default and no default_factory
            if (
                field_obj.default is dataclasses.MISSING
                and field_obj.default_factory is dataclasses.MISSING
            ):
                required_fields.add(name)

        # Check if all required fields are provided in kwargs
        missing_fields = required_fields - set(kwargs.keys())
        if missing_fields:
            plural = "s" if len(missing_fields) > 1 else ""
            missing_str = ", ".join(missing_fields)
            error_msg = (
                f"{class_name} missing {len(missing_fields)} "
                f"required argument{plural}: {missing_str}"
            )
            raise TypeError(error_msg)

        # Process mutable fields to make sure they have proper default values
        for field_name in mutable_fields:
            if not hasattr(self, field_name):
                field_obj = all_fields.get(field_name)
                if field_obj is not None:
                    # Set default values for mutable fields
                    if field_obj.default is not dataclasses.MISSING:
                        object.__setattr__(self, field_name, field_obj.default)
                    elif field_obj.default_factory is not dataclasses.MISSING:
                        default_value = field_obj.default_factory()
                        object.__setattr__(self, field_name, default_value)

        # Process inheritance by properly handling base class initialization
        # Extract parameters for base classes
        base_init_kwargs = {}
        this_class_kwargs = {}

        # Get all fields from base classes
        base_fields = set()

        # Skip the current class in the MRO (it's the first one)
        for base_cls in cls.__mro__[1:]:
            if hasattr(base_cls, "__dataclass_fields__"):
                for name in base_cls.__dataclass_fields__:
                    base_fields.add(name)

        # Get all valid field names for this class
        valid_field_names = set(all_fields.keys())

        # Split kwargs between base classes, this class, and filter out unknown params
        for key, value in kwargs.items():
            if key in base_fields:
                base_init_kwargs[key] = value
            elif key in valid_field_names:
                this_class_kwargs[key] = value
            # Skip unknown parameters - don't add them as attributes

        # Initialize base classes first
        # Skip the current class in the MRO (it's the first one)
        for base_cls in cls.__mro__[1:]:
            base_init = getattr(base_cls, "__init__", None)
            if (
                base_init is not None
                and base_init is not object.__init__
                and hasattr(base_cls, "__dataclass_fields__")
            ):
                # Filter kwargs to only include fields from this base class
                base_class_kwargs = {
                    k: v
                    for k, v in base_init_kwargs.items()
                    if k in base_cls.__dataclass_fields__
                }
                if base_class_kwargs:
                    # Call the base class __init__ with appropriate kwargs
                    base_init(self, **base_class_kwargs)

        # Execute original init with parameters specific to this class
        # Note: We can't directly call original_init here because it would
        # reinitialize the base classes. We already initialized the base classes
        # above, so we manually set the fields for this class
        for key, value in this_class_kwargs.items():
            object.__setattr__(self, key, value)

        # Turn off initializing flag
        object.__setattr__(self, "_initializing", False)

        # Call original __post_init__ if it exists
        if original_post_init is not None:
            original_post_init(self)

        # Automatically seal if no mutable fields are defined
        # But ONLY for classes that don't have any fields marked mutable_during_init
        if not mutable_fields:
            seal_method = getattr(self, "seal", None)
            if seal_method and callable(seal_method):
                seal_method()

    # Define methods that will be attached to the class
    def seal_method(self: Any, deep: bool = False) -> None:
        """Seal the object to prevent further modifications.

        Parameters
        ----------
        deep : bool, optional
            If True, recursively seal any nested sealable objects, by default False
        """
        # First seal this object
        object.__setattr__(self, "_sealed", True)

        # If deep sealing requested, look for nested sealable objects
        if deep:
            for field_obj in dataclasses.fields(self):
                field_value = getattr(self, field_obj.name, None)
                # Check if the field value is sealable
                if field_value is not None and is_sealable(field_value):
                    # Seal the nested object
                    field_value.seal(deep=True)

    # Define the is_sealable class method
    def is_sealable_class_method(cls_param: type) -> bool:
        """Check if this class is sealable.

        Returns
        -------
        bool
            Always returns True for classes decorated with frozen_dataclass_sealable
        """
        return True

    # Add custom methods to the class
    cls.__setattr__ = custom_setattr  # type: ignore
    cls.__delattr__ = custom_delattr  # type: ignore
    cls.__init__ = custom_init  # type: ignore
    cls.seal = seal_method  # type: ignore
    cls.is_sealable = classmethod(is_sealable_class_method)  # type: ignore

    return cls
