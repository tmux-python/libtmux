# flake8: NOQA
import functools
import sys
import types
import typing as t


# TODO Consider removing, reraise does not seem to be called anywhere
def reraise(
    tp: t.Type[BaseException],
    value: BaseException,
    tb: types.TracebackType,
) -> t.NoReturn:
    if value.__traceback__ is not tb:
        raise (value.with_traceback(tb))
    raise value


class _SentinelBackport:
    """Backport of the ``sentinel`` built-in added in Python 3.15 (PEP 661).

    A sentinel is a unique object that marks "no value was passed" where
    ``None`` already has a meaning.

    Examples
    --------
    >>> from libtmux._compat import _SentinelBackport
    >>> UNSET = _SentinelBackport("UNSET")
    >>> UNSET
    UNSET
    >>> UNSET is _SentinelBackport("UNSET")
    False
    """

    __slots__ = ("_name", "_repr")

    def __init__(self, name: str, /, *, repr: t.Optional[str] = None) -> None:
        self._name = name
        self._repr = name if repr is None else repr

    def __repr__(self) -> str:
        return self._repr

    def __copy__(self) -> "_SentinelBackport":
        return self

    def __deepcopy__(self, memo: t.Dict[int, t.Any]) -> "_SentinelBackport":
        return self


if t.TYPE_CHECKING or sys.version_info < (3, 15):
    sentinel = _SentinelBackport
else:
    from builtins import sentinel


import re
from typing import Iterator, List, Tuple

from libtmux._vendor.version import Version

###
### Legacy support for LooseVersion / LegacyVersion, e.g. 2.4-openbsd
### https://github.com/pypa/packaging/blob/21.3/packaging/version.py#L106-L115
### License: BSD, Accessed: Jan 14th, 2022
###

LegacyCmpKey = Tuple[int, Tuple[str, ...]]

_legacy_version_component_re = re.compile(r"(\d+ | [a-z]+ | \.| -)", re.VERBOSE)
_legacy_version_replacement_map = {
    "pre": "c",
    "preview": "c",
    "-": "final-",
    "rc": "c",
    "dev": "@",
}


def _parse_version_parts(s: str) -> Iterator[str]:
    for raw_part in _legacy_version_component_re.split(s):
        if not isinstance(raw_part, str):
            continue
        part = _legacy_version_replacement_map.get(raw_part, raw_part)

        if not part or part == ".":
            continue

        if part[:1] in "0123456789":
            # pad for numeric comparison
            yield part.zfill(8)
        else:
            yield "*" + part

    # ensure that alpha/beta/candidate are before final
    yield "*final"


def _legacy_cmpkey(version: str) -> LegacyCmpKey:
    # We hardcode an epoch of -1 here. A PEP 440 version can only have a epoch
    # greater than or equal to 0. This will effectively put the LegacyVersion,
    # which uses the defacto standard originally implemented by setuptools,
    # as before all PEP 440 versions.
    epoch = -1

    # This scheme is taken from pkg_resources.parse_version setuptools prior to
    # it's adoption of the packaging library.
    parts: List[str] = []
    for part in _parse_version_parts(version.lower()):
        if part.startswith("*"):
            # remove "-" before a prerelease tag
            if part < "*final":
                while parts and parts[-1] == "*final-":
                    parts.pop()

            # remove trailing zeros from each series of numeric parts
            while parts and parts[-1] == "00000000":
                parts.pop()

        parts.append(part)

    return epoch, tuple(parts)


@functools.total_ordering
class LegacyVersion:
    _key: LegacyCmpKey

    def __hash__(self) -> int:
        return hash(self._key)

    def __init__(self, version: object) -> None:
        self._version = str(version)
        self._key = _legacy_cmpkey(self._version)

    def __str__(self) -> str:
        return self._version

    def __lt__(self, other: object) -> bool:
        if isinstance(other, str):
            other = LegacyVersion(other)
        if not isinstance(other, LegacyVersion):
            return NotImplemented

        return self._key < other._key

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            other = LegacyVersion(other)
        if not isinstance(other, LegacyVersion):
            return NotImplemented

        return self._key == other._key

    def __repr__(self) -> str:
        return "<LegacyVersion({0})>".format(repr(str(self)))


LooseVersion = LegacyVersion
