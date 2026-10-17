"""Admission for ordinary commands on a live or newly created tmux endpoint."""

from __future__ import annotations

import getopt
import re
import subprocess
import uuid

from libtmux import exc

MINIMUM = "3.3a"
_RELEASE = re.compile(r"(\d+)\.(\d+)([a-z]?)(?:-(master|dev|rc\d+))?")


def require_version(version: str, minimum: str = MINIMUM) -> None:
    """Reject unknown or older releases, preserving numeric and patch order."""
    # Development lanes are explicit candidates, not stable feature guarantees.
    candidate = version.removeprefix("next-")
    parsed = _RELEASE.fullmatch(candidate)
    floor = _RELEASE.fullmatch(minimum)
    if parsed is not None and floor is not None:
        running = (int(parsed[1]), int(parsed[2]), parsed[3])
        required = (int(floor[1]), int(floor[2]), floor[3])
        if running > required or (
            running == required
            and not version.startswith("next-")
            and not (parsed[4] or "").startswith("rc")
        ):
            return
    msg = f"libtmux requires tmux {minimum} or newer; endpoint reports {version!r}"
    raise exc.VersionTooLow(msg)


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


def prepare(argv: list[str]) -> tuple[list[str], str | None]:
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
    version = endpoint_version(argv[0], selectors)
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


def check_result(stderr: str, marker: str | None) -> None:
    """Reject a replaced daemon before returning an ordinary result."""
    if marker is not None and f"unknown command: {marker}" in stderr.splitlines():
        msg = "tmux daemon changed before dispatch; retry the command"
        raise exc.VersionTooLow(msg)


def live_version(binary: str, selectors: list[str]) -> str | None:
    """Admit an existing daemon, returning None for an absent endpoint."""
    probe = _run([binary, *selectors, "-N", "display-message", "-p", "#{version}"])
    if probe.returncode == 0:
        version = probe.stdout.strip()
        require_version(version)
        return version
    if "no server running" in probe.stderr or (
        "error connecting to" in probe.stderr
        and any(
            reason in probe.stderr
            for reason in (
                "No such file or directory",
                "Connection refused",
            )
        )
    ):
        return None
    msg = probe.stderr.strip() or "tmux did not report a daemon version"
    raise exc.LibTmuxException(msg)


def endpoint_version(binary: str, selectors: list[str]) -> str:
    """Read a fresh daemon version, or the executable for an absent endpoint."""
    version = live_version(binary, selectors)
    if version is not None:
        return version
    result = _run([binary, "-V"])
    if result.returncode or not result.stdout.startswith("tmux "):
        detail = result.stderr.strip() or result.stdout.strip()
        msg = f"cannot establish tmux version before command dispatch: {detail}"
        raise exc.VersionTooLow(msg)
    version = result.stdout.removeprefix("tmux ").strip()
    require_version(version)
    return version
