"""Admission for ordinary commands on a live or newly created tmux endpoint."""

from __future__ import annotations

import getopt
import os
import pathlib
import re
import subprocess
import threading
import uuid

from libtmux import exc

MINIMUM = "3.3a"

_NUMBER = r"(?:0|[1-9][0-9]*)"
_REPORT = re.compile(
    rf"(?P<dev>next-)?(?P<major>{_NUMBER})\.(?P<minor>{_NUMBER})"
    r"(?:(?P<letter>[a-z])|-rc(?P<candidate>[0-9]*))?",
    re.ASCII,
)


def _rank(report: str) -> tuple[int, int, int, int, str] | None:
    """Order the forms tmux reports, or return None for any other string.

    ``next-X.Y`` precedes ``X.Y-rc``, then ``X.Y-rcN``, then ``X.Y`` and its
    patch letters. A bare ``-rc`` ranks as the first candidate.
    """
    parsed = _REPORT.fullmatch(report)
    if parsed is None:
        return None
    dev = parsed["dev"] is not None
    letter = parsed["letter"]
    candidate = parsed["candidate"]
    if dev and (letter or candidate is not None):
        return None
    stage = 0 if dev else 1 if candidate is not None else 2
    return (
        int(parsed["major"]),
        int(parsed["minor"]),
        stage,
        int(candidate or 1) if stage == 1 else 0,
        letter or "",
    )


def require_version(version: str, minimum: str = MINIMUM) -> None:
    """Reject unknown or older reports, preserving numeric and patch order."""
    running = _rank(version)
    required = _rank(minimum)
    if running is not None and required is not None and running >= required:
        return
    msg = f"libtmux requires tmux {minimum} or newer; endpoint reports {version!r}"
    raise exc.VersionTooLow(msg)


def is_at_least(version: str, minimum: str) -> bool:
    """Compare an admitted report with a feature's complete release floor."""
    try:
        require_version(version, minimum=minimum)
    except exc.VersionTooLow:
        return False
    return True


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="backslashreplace",
            timeout=5,
            check=False,
        )
    except FileNotFoundError:
        raise exc.TmuxCommandNotFound from None
    except subprocess.TimeoutExpired as error:
        msg = "tmux version admission timed out before command dispatch"
        raise exc.LibTmuxException(msg) from error


class AdmissionCache:
    """The daemon release last admitted for one endpoint.

    The in-band version fence catches a replaced daemon, so a cached release
    only needs a new probe after the fence fires or the daemon disappears.
    An absent endpoint is never cached.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entry: tuple[tuple[str, tuple[str, ...], str, str], str] | None = None

    @staticmethod
    def _key(
        binary: str, selectors: list[str]
    ) -> tuple[str, tuple[str, ...], str, str]:
        # The socket directory follows the environment when no path is named.
        env = os.environ
        return (
            binary,
            tuple(selectors),
            env.get("TMUX_TMPDIR", ""),
            env.get("TMUX", ""),
        )

    def get(self, binary: str, selectors: list[str]) -> str | None:
        """Return the admitted release for this endpoint, if one is cached."""
        with self._lock:
            entry = self._entry
        if entry is not None and entry[0] == self._key(binary, selectors):
            return entry[1]
        return None

    def put(self, binary: str, selectors: list[str], version: str) -> None:
        """Remember an admitted release."""
        with self._lock:
            self._entry = (self._key(binary, selectors), version)

    def clear(self) -> None:
        """Forget the admitted release."""
        with self._lock:
            self._entry = None

    def __bool__(self) -> bool:
        return self._entry is not None


def _absent_endpoint(stderr: str) -> bool:
    return "no server running" in stderr or (
        "error connecting to" in stderr
        and any(
            reason in stderr
            for reason in ("No such file or directory", "Connection refused")
        )
    )


def daemon_gone(stderr: str) -> bool:
    """Report that a command found no daemon to talk to."""
    return _absent_endpoint(stderr)


def _command_items(arguments: list[str]) -> list[list[str]]:
    """Inspect the native argv command boundaries without rewriting them."""
    commands: list[list[str]] = []
    current: list[str] = []
    for argument in arguments:
        if argument.endswith(";"):
            value = argument[:-1]
            if value.endswith("\\"):
                current.append(value[:-1] + ";")
                continue
            if value:
                current.append(value)
            if current:
                commands.append(current)
                current = []
        else:
            current.append(argument)
    if current:
        commands.append(current)
    return commands


def _require_commands(
    version: str, arguments: list[str], *, repaired_break: bool
) -> None:
    for command in _command_items(arguments):
        name = command[0]
        if not is_at_least(version, "3.4") and (
            name == "selectl" or (len(name) >= 8 and "select-layout".startswith(name))
        ):
            options, operands = getopt.getopt(command[1:], "Enopt:")
            flags = {flag for flag, _ in options}
            if not operands or flags & {"-E", "-n", "-p"}:
                continue
            layout = operands[0]
            # Before 3.4 an invalid header leaves the native error cause unset.
            if re.fullmatch(r"[0-9a-fA-F]{4},[\s\S]+", layout):
                continue
            presets = (
                "even-horizontal",
                "even-vertical",
                "main-horizontal",
                "main-vertical",
                "tiled",
            )
            if (
                "-o" not in flags
                and sum(item.startswith(layout) for item in presets) == 1
            ):
                continue
            msg = (
                "invalid layout refused before dispatch on tmux 3.3a; "
                "use a unique built-in layout name or a serialized layout"
            )
            raise ValueError(msg)
        elif not is_at_least(version, "3.4") and (
            name == "deleteb" or "delete-buffer".startswith(name)
        ):
            options, _ = getopt.getopt(command[1:], "b:")
            if any(flag == "-b" for flag, _ in options):
                msg = "exact named-buffer deletion requires tmux 3.4 or newer"
                raise exc.VersionTooLow(msg)
        elif not is_at_least(version, "3.4") and (
            name == "setb" or (len(name) >= 5 and "set-buffer".startswith(name))
        ):
            options, _ = getopt.getopt(command[1:], "ab:t:n:w")
            flags = {flag for flag, _ in options}
            if {"-b", "-n"} <= flags:
                msg = "exact named-buffer rename requires tmux 3.4 or newer"
                raise exc.VersionTooLow(msg)
        elif version == "3.7" and (name == "breakp" or "break-pane".startswith(name)):
            options, _ = getopt.getopt(command[1:], "abdPF:n:s:t:")
            if not repaired_break or not any(flag == "-n" for flag, _ in options):
                msg = (
                    "raw break-pane is unsafe on tmux 3.7; use Pane.break_pane "
                    "with an explicit window_name or upgrade to 3.7a"
                )
                raise exc.VersionTooLow(msg)
        elif (
            is_at_least(version, "3.4")
            and not is_at_least(version, "3.5")
            and (name == "splitw" or "split-window".startswith(name))
        ):
            options, _ = getopt.getopt(command[1:], "bc:de:fF:hIl:p:Pt:vZ")
            if any(flag == "-p" for flag, _ in options):
                msg = (
                    "split-window -p is broken on tmux 3.4; "
                    "use -l with a percentage or Pane.split"
                )
                raise exc.VersionTooLow(msg)


def prepare(
    argv: list[str],
    *,
    cache: AdmissionCache | None = None,
    minimum: str = MINIMUM,
    expected_version: str | None = None,
    repaired_break: bool = False,
) -> tuple[list[str], str | None]:
    """Admit the daemon, then fence dispatch against its exact version."""
    try:
        options, commands = getopt.getopt(argv[1:], "28c:CDdf:hlL:NqS:T:uUvV")
    except getopt.GetoptError as error:
        raise exc.LibTmuxException(str(error)) from error
    if any(flag in {"-V", "-h"} for flag, _ in options):
        return argv, None
    if any(flag == "-c" for flag, _ in options):
        msg = "tmux -c is outside command dispatch; use Server.run_shell instead"
        raise exc.LibTmuxException(msg)
    if any(flag == "-C" for flag, _ in options):
        msg = "raw control startup cannot retain a daemon endpoint; use ControlMode"
        raise exc.LibTmuxException(msg)
    if not commands:
        commands = ["new-session"]
    globals_: list[str] = []
    selectors: list[str] = []
    for flag, value in options:
        globals_.append(flag)
        if flag in {"-f", "-L", "-S", "-T"}:
            globals_.append(value)
        if flag in {"-L", "-S"}:
            selectors.extend((flag, value))
    version = cache.get(argv[0], selectors) if cache is not None else None
    if version is None:
        version = live_version(argv[0], selectors)
        if cache is not None:
            if version is None:
                cache.clear()
            else:
                cache.put(argv[0], selectors, version)
    if version is None:
        version = _binary_version(argv[0])
    elif not any(flag == "-N" for flag, _ in options):
        # A vanished daemon must not restart an older configured executable.
        globals_.append("-N")
    if not is_at_least(version, minimum):
        msg = (
            f"this operation requires tmux {minimum} or newer; "
            f"daemon reports {version!r}"
        )
        raise exc.VersionTooLow(msg)
    if expected_version is not None and version != expected_version:
        msg = "tmux daemon changed while selecting the operation's capabilities"
        raise exc.VersionTooLow(msg)
    try:
        _require_commands(version, commands, repaired_break=repaired_break)
    except getopt.GetoptError as error:
        raise exc.LibTmuxException(str(error)) from error
    marker = "libtmux-version-" + uuid.uuid4().hex
    condition = "#{==:#{version}," + version + "}"
    return [
        argv[0],
        *globals_,
        "if-shell",
        "-F",
        condition,
        "",
        marker,
        ";",
        *commands,
    ], marker


def check_result(
    stderr: str, marker: str | None, *, cache: AdmissionCache | None = None
) -> None:
    """Reject a replaced daemon before returning an ordinary result."""
    if marker is not None and f"unknown command: {marker}" in stderr.splitlines():
        if cache is not None:
            cache.clear()
        msg = "tmux daemon changed before dispatch; retry the command"
        raise exc.VersionTooLow(msg)


def live_version(binary: str, selectors: list[str]) -> str | None:
    """Admit an existing daemon, returning None for an absent endpoint."""
    # run-shell has no after-hook and, with -C, fails while parsing its own
    # output, so the probe fires neither after-* nor command-error hooks.
    marker = "libtmux-version-" + uuid.uuid4().hex + "-"
    probe = _run([binary, *selectors, "-N", "run-shell", "-C", marker + "#{version}"])
    prefix = f"unknown command: {marker}"
    reports = [
        line[len(prefix) :]
        for line in probe.stderr.splitlines()
        if line.startswith(prefix)
    ]
    if probe.returncode == 1 and len(reports) == 1:
        require_version(reports[0])
        return reports[0]
    if _absent_endpoint(probe.stderr):
        return None
    msg = probe.stderr.strip() or "tmux did not report a daemon version"
    raise exc.LibTmuxException(msg)


def endpoint_version(
    binary: str, selectors: list[str], *, cache: AdmissionCache | None = None
) -> str:
    """Read the daemon version, or the executable's for an absent endpoint.

    With a cache, a release admitted earlier is returned without a probe.
    """
    if cache is not None:
        cached = cache.get(binary, selectors)
        if cached is not None:
            return cached
    version = live_version(binary, selectors)
    if version is not None:
        if cache is not None:
            cache.put(binary, selectors, version)
        return version
    if cache is not None:
        cache.clear()
    return _binary_version(binary)


def _binary_version(binary: str) -> str:
    result = _run([binary, "-V"])
    # tmux 3.3a prints its executable name, including non-UTF-8 bytes.
    name = os.fsencode(pathlib.Path(binary).name).decode(
        "utf-8", errors="backslashreplace"
    )
    prefix = next(
        (item for item in (name + " ", "tmux ") if result.stdout.startswith(item)),
        None,
    )
    if result.returncode or prefix is None:
        detail = result.stderr.strip() or result.stdout.strip()
        msg = f"cannot establish tmux version before command dispatch: {detail}"
        raise exc.VersionTooLow(msg)
    version = result.stdout[len(prefix) :].strip()
    require_version(version)
    return version
