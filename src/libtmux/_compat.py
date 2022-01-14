# flake8: NOQA
import sys
import types
import typing as t

console_encoding = sys.__stdout__.encoding


def console_to_str(s: bytes) -> str:
    """From pypa/pip project, pip.backwardwardcompat. License MIT."""
    try:
        return s.decode(console_encoding, "ignore")
    except UnicodeDecodeError:
        return s.decode("utf_8", "ignore")


# TODO Consider removing, reraise does not seem to be called anywhere
def reraise(
    tp: t.Type[BaseException],
    value: BaseException,
    tb: types.TracebackType,
) -> t.NoReturn:

    if value.__traceback__ is not tb:
        raise (value.with_traceback(tb))
    raise value


def str_from_console(s: t.Union[str, bytes]) -> str:
    try:
        return str(s)
    except UnicodeDecodeError:
        return str(s, encoding="utf_8") if isinstance(s, bytes) else s


try:
    import re
    from typing import Iterator, List, Tuple

    from packaging.version import Version, _BaseVersion

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
        for part in _legacy_version_component_re.split(s):
            part = _legacy_version_replacement_map.get(part, part)

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

    class LegacyVersion(_BaseVersion):
        def __init__(self, version: str) -> None:
            self._version = str(version)
            self._key = _legacy_cmpkey(self._version)

        def __str__(self) -> str:
            return self._version

        def __repr__(self) -> str:
            return "<LegacyVersion({0})>".format(repr(str(self)))

        @property
        def public(self) -> str:
            return self._version

        @property
        def base_version(self) -> str:
            return self._version

        @property
        def epoch(self) -> int:
            return -1

    LooseVersion = LegacyVersion
except ImportError:
    from distutils.version import LooseVersion, Version
