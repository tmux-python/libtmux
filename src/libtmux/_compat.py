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
    import collections
    import functools
    import re
    from typing import Iterator, List, Tuple

    from packaging import version as V
    from packaging.version import VERSION_PATTERN, Version, _BaseVersion

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

        def __lt__(self, other):
            if isinstance(other, str):
                other = LegacyVersion(other)
            return super().__lt__(other)

        def __eq__(self, other) -> bool:
            if isinstance(other, str):
                other = LegacyVersion(other)
            if not isinstance(other, LegacyVersion):
                return NotImplemented

            return self._key == other._key

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

    @functools.total_ordering
    class _VersionCmpMixin:
        # Credit: @layday
        # Link: https://github.com/pypa/packaging/issues/465#issuecomment-1013715662
        def __eq__(self, other: object) -> bool:
            if isinstance(other, str):
                other = self.__class__(other)
            return super().__eq__(other)

        def __lt__(self, other: object) -> bool:
            if isinstance(other, str):
                other = self.__class__(other)
            return super().__lt__(other)

    _Version = collections.namedtuple(
        "_Version", ["epoch", "release", "dev", "pre", "post", "local", "platform"]
    )

    def _cmpkey(
        epoch,  # type: int
        release,  # type: Tuple[int, ...]
        pre,  # type: Optional[Tuple[str, int]]
        post,  # type: Optional[Tuple[str, int]]
        dev,  # type: Optional[Tuple[str, int]]
        local,  # type: Optional[Tuple[SubLocalType]]
        platform,  # type: Optional[Tuple[SubLocalType]]
    ):
        return V._cmpkey(epoch, release, pre, post, dev, local) + (
            tuple(
                (i, "") if isinstance(i, int) else (V.NegativeInfinity, i)
                for i in platform
            )
        )

    class LegacyVersion(Version):
        _regex = re.compile
        _regex = re.compile(
            r"^\s*"
            + VERSION_PATTERN
            + r"(?:(?P<platform>(?:[-_\.][a-z0-9]+)*))?       # platform version"
            + r"\s*$",
            re.VERBOSE | re.IGNORECASE,
        )

        def __init__(self, version):
            # type: (str) -> None

            # Validate the version and parse it into pieces
            match = self._regex.search(version)
            if not match:
                raise V.InvalidVersion("Invalid version: '{0}'".format(version))

            # Store the parsed out pieces of the version
            self._version = _Version(
                epoch=int(match.group("epoch")) if match.group("epoch") else 0,
                release=tuple(int(i) for i in match.group("release").split(".")),
                pre=V._parse_letter_version(match.group("pre_l"), match.group("pre_n")),
                post=V._parse_letter_version(
                    match.group("post_l"),
                    match.group("post_n1") or match.group("post_n2"),
                ),
                dev=V._parse_letter_version(match.group("dev_l"), match.group("dev_n")),
                local=V._parse_local_version(match.group("local")),
                platform=str(match.group("platform"))
                if match.group("platform")
                else "",
            )

            # Generate a key which will be used for sorting
            self._key = _cmpkey(
                self._version.epoch,
                self._version.release,
                self._version.pre,
                self._version.post,
                self._version.dev,
                self._version.local,
                self._version.platform,
            )

        @property
        def platform(self):
            # type: () -> Optional[str]
            if self._version.platform:
                return ".".join(str(x) for x in self._version.platform)
            else:
                return None

        def __str__(self):
            # type: () -> str
            parts = []

            # Epoch
            if self.epoch != 0:
                parts.append("{0}!".format(self.epoch))

            # Release segment
            parts.append(".".join(str(x) for x in self.release))

            # Pre-release
            if self.pre is not None:
                parts.append("".join(str(x) for x in self.pre))

            # Post-release
            if self.post is not None:
                parts.append(".post{0}".format(self.post))

            # Development release
            if self.dev is not None:
                parts.append(".dev{0}".format(self.dev))

            # Local version segment
            if self.local is not None:
                parts.append("+{0}".format(self.local))

            # Platform version segment
            if self.platform is not None:
                parts.append("_{0}".format(self.platform))

            return "".join(parts)

    LooseVersion = LegacyVersion
except ImportError:
    from distutils.version import LooseVersion, Version
