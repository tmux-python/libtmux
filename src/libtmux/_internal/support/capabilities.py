"""tmux capabilities libtmux gates by release.

One table decides both what a gate compares against and what
``capabilities.json`` at the repository root publishes. The manifest is
generated from :data:`CAPABILITIES` and never written by hand:

.. code-block:: console

    $ just build-capabilities

Note
----
This is an internal API not covered by versioning policy.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import typing as t
from dataclasses import dataclass

from libtmux import exc

if t.TYPE_CHECKING:
    from libtmux.engine import TmuxEngine

SCHEMA: t.Final[str] = "libtmux-capabilities/1"
PORT: t.Final[str] = "py"
TMUX_MIN_VERSION: t.Final[str] = "3.3a"

Handling: t.TypeAlias = t.Literal["refuse", "fallback", "repair"]

REMOVED_39_POPUP_OPTIONS: t.Final[frozenset[str]] = frozenset(
    {
        "popup-border-lines",
        "popup-border-style",
        "popup-style",
    }
)


@dataclass(frozen=True, slots=True)
class Command:
    """A tmux command a capability concerns, with the flags it adds.

    Attributes
    ----------
    command : str
        Tmux subcommand name.
    flags : tuple[str, ...]
        Gated short flags on *command*.
    """

    command: str
    flags: tuple[str, ...] = ()

    def to_manifest(self) -> dict[str, t.Any]:
        """Return this command entry in ``libtmux-capabilities/1`` form."""
        if self.flags:
            return {"command": self.command, "flags": list(self.flags)}
        return {"command": self.command}


@dataclass(frozen=True, slots=True)
class Capability:
    """A tmux feature that exists from one release on.

    Attributes
    ----------
    id : str
        Stable lowercase kebab-case identifier shared across libtmux's ports.
    name : str
        Short heading.
    summary : str
        One sentence on what a caller can do with it.
    since : str
        First tmux release at which it works, spelled as tmux prints it.
    handling : {"refuse", "fallback", "repair"}
        What libtmux does on an older tmux. ``"fallback"`` warns and sends
        the command without the flag; ``"refuse"`` raises before tmux runs.
    apis : tuple[str, ...]
        Public names that need the capability.
    commands : tuple[Command, ...]
        tmux commands and flags it concerns.
    error : str or None
        Exception a refusal raises. Set when *handling* is ``"refuse"``.
    until : str or None
        First tmux release where the feature was removed, or ``None``.
    except_releases : tuple[str, ...]
        Specific releases within ``[since, until)`` where the feature is refused.
    """

    id: str
    name: str
    summary: str
    since: str
    handling: Handling
    apis: tuple[str, ...]
    commands: tuple[Command, ...]
    error: str | None = None
    until: str | None = None
    except_releases: tuple[str, ...] = ()

    def to_manifest(self) -> dict[str, t.Any]:
        """Return this capability as a manifest entry.

        Examples
        --------
        >>> from libtmux._internal.support.capabilities import get
        >>> get("floating-pane").to_manifest()["error"]
        'libtmux.exc.LibTmuxException'
        >>> "error" in get("run-shell-args").to_manifest()
        False
        """
        entry: dict[str, t.Any] = {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "since": self.since,
        }
        if self.until is not None:
            entry["until"] = self.until
        if self.except_releases:
            entry["except"] = list(self.except_releases)
        entry["handling"] = self.handling
        if self.error is not None:
            entry["error"] = self.error
        entry["apis"] = list(self.apis)
        entry["commands"] = [command.to_manifest() for command in self.commands]
        return entry


@dataclass(frozen=True, slots=True)
class Workaround:
    """Release-specific upstream tmux defect handled by libtmux.

    Attributes
    ----------
    id : str
        Stable lowercase kebab-case identifier shared across libtmux's ports.
    name : str
        Short heading.
    summary : str
        Upstream defect and how libtmux handles it.
    releases : tuple[str, ...]
        Exact tmux releases affected.
    handling : {"refuse", "repair"}
        Whether libtmux refuses or repairs affected invocations.
    apis : tuple[str, ...]
        Public names affected.
    commands : tuple[Command, ...]
        tmux commands and flags concerned.
    """

    id: str
    name: str
    summary: str
    releases: tuple[str, ...]
    handling: t.Literal["refuse", "repair"]
    apis: tuple[str, ...]
    commands: tuple[Command, ...]

    def to_manifest(self) -> dict[str, t.Any]:
        """Return this workaround as a manifest entry."""
        return {
            "id": self.id,
            "name": self.name,
            "summary": self.summary,
            "releases": list(self.releases),
            "handling": self.handling,
            "apis": list(self.apis),
            "commands": [command.to_manifest() for command in self.commands],
        }


@dataclass(frozen=True, slots=True)
class DaemonIdentity:
    """Connected tmux server generation and version tuple.

    Attributes
    ----------
    pid : int
        Observed ``#{pid}`` of the connected daemon.
    start_time : int
        Observed ``#{start_time}`` epoch seconds of the connected daemon.
    version : str
        Observed ``#{version}`` of the connected daemon.
    """

    pid: int
    start_time: int
    version: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        id="control-mode",
        name="Control mode",
        summary="Attach a library-managed control client and pipeline commands.",
        since="3.7",
        handling="refuse",
        error="libtmux.exc.VersionTooLow",
        apis=("libtmux.engine.ControlModeEngine",),
        commands=(Command("attach-session", ("-C",)),),
    ),
    Capability(
        id="run-shell-start-directory",
        name="run-shell working directory",
        summary="Start a run-shell job in a chosen directory.",
        since="3.4",
        handling="fallback",
        apis=("libtmux.Server.run_shell",),
        commands=(Command("run-shell", ("-c",)),),
    ),
    Capability(
        id="run-shell-start-directory-format",
        name="run-shell working directory formats",
        summary="Expand a format in a run-shell job's working directory.",
        since="3.8",
        handling="refuse",
        apis=("libtmux.Server.run_shell",),
        commands=(Command("run-shell", ("-c",)),),
        error="libtmux.exc.LibTmuxException",
    ),
    Capability(
        id="run-shell-show-stderr",
        name="run-shell stderr",
        summary="Show a run-shell job's standard error as well as its output.",
        since="3.6",
        handling="fallback",
        apis=("libtmux.Server.run_shell",),
        commands=(Command("run-shell", ("-E",)),),
    ),
    Capability(
        id="run-shell-args",
        name="run-shell job arguments",
        summary="Pass extra arguments to a run-shell job.",
        since="3.7",
        handling="fallback",
        apis=("libtmux.Server.run_shell",),
        commands=(Command("run-shell"),),
    ),
    Capability(
        id="run-shell-output-in-copy-mode",
        name="run-shell output capture",
        summary="Return a foreground run-shell command's output to the caller.",
        since="3.5",
        handling="refuse",
        apis=("libtmux.Server.run_shell",),
        commands=(Command("run-shell"),),
        error="libtmux.exc.VersionTooLow",
    ),
    Capability(
        id="list-keys-format",
        name="Formatted key listing",
        summary="Format each key binding with a caller-supplied template.",
        since="3.7",
        handling="fallback",
        apis=("libtmux.Server.list_keys",),
        commands=(Command("list-keys", ("-F",)),),
    ),
    Capability(
        id="capture-trim-blank-cells",
        name="Trim blank capture cells",
        summary="Drop trailing positions that hold no character from a capture.",
        since="3.4",
        handling="fallback",
        apis=("libtmux.Pane.capture_pane",),
        commands=(Command("capture-pane", ("-T",)),),
    ),
    Capability(
        id="capture-mode-screen",
        name="Capture the mode screen",
        summary="Capture what a pane's active mode shows instead of the pane.",
        since="3.6",
        handling="fallback",
        apis=("libtmux.Pane.capture_pane",),
        commands=(Command("capture-pane", ("-M",)),),
    ),
    Capability(
        id="capture-line-flags",
        name="Capture line numbers, flags and hyperlinks",
        summary=(
            "Prefix captured lines with their number or metadata flags, "
            "or keep hyperlinks."
        ),
        since="3.7",
        handling="fallback",
        apis=("libtmux.Pane.capture_pane",),
        commands=(Command("capture-pane", ("-F", "-H", "-L")),),
    ),
    Capability(
        id="paste-buffer-no-vis",
        name="Paste raw bytes",
        summary="Paste a buffer without tmux rewriting its control characters.",
        since="3.7",
        handling="fallback",
        apis=("libtmux.Pane.paste_buffer",),
        commands=(Command("paste-buffer", ("-S",)),),
    ),
    Capability(
        id="floating-pane",
        name="Floating panes",
        summary="Create a floating pane with new-pane.",
        since="3.7",
        handling="refuse",
        error="libtmux.exc.LibTmuxException",
        apis=("libtmux.Pane.new_pane",),
        commands=(Command("new-pane"),),
    ),
)

WORKAROUNDS: tuple[Workaround, ...] = (
    Workaround(
        id="break-pane-misnames-windows",
        name="break-pane window naming",
        summary=(
            "tmux 3.7 crashes on break-pane without -n and ignores -n when "
            "given; break_pane supplies a placeholder -n and renames afterwards."
        ),
        releases=("3.7",),
        handling="repair",
        apis=("libtmux.Pane.break_pane",),
        commands=(Command("break-pane", ("-n",)),),
    ),
)

_BY_ID: dict[str, Capability] = {
    capability.id: capability for capability in CAPABILITIES
}
_WORKAROUNDS_BY_ID: dict[str, Workaround] = {
    workaround.id: workaround for workaround in WORKAROUNDS
}

_NEXT_RE: t.Final[re.Pattern[str]] = re.compile(r"^next-(\d+)\.(\d+)$")
_RELEASE_RE: t.Final[re.Pattern[str]] = re.compile(
    r"^(\d+)\.(\d+)(?:([a-z])|-rc(\d*))?$"
)


def get(capability_id: str) -> Capability:
    """Return the capability named *capability_id*.

    Raises
    ------
    KeyError
        The table defines no capability with that id.

    Examples
    --------
    >>> from libtmux._internal.support.capabilities import get
    >>> get("floating-pane").since
    '3.7'
    """
    return _BY_ID[capability_id]


def get_workaround(workaround_id: str) -> Workaround:
    """Return the workaround named *workaround_id*, or raise ``KeyError``."""
    return _WORKAROUNDS_BY_ID[workaround_id]


def capability_since(capability_id: str) -> str:
    """Return the first tmux release that has *capability_id*.

    Gates pass the result to :func:`libtmux.common.has_gte_version`, so the
    release a gate compares against lives in the table and nowhere else.

    Raises
    ------
    KeyError
        The table defines no capability with that id.

    Examples
    --------
    >>> from libtmux._internal.support.capabilities import capability_since
    >>> capability_since("run-shell-start-directory")
    '3.4'
    """
    return get(capability_id).since


def manifest() -> dict[str, t.Any]:
    """Return the capability manifest as ``capabilities.json`` stores it.

    Examples
    --------
    >>> from libtmux._internal.support.capabilities import manifest
    >>> doc = manifest()
    >>> doc["schema"], doc["port"]
    ('libtmux-capabilities/1', 'py')
    >>> [entry["id"] for entry in doc["capabilities"]][:2]
    ['control-mode', 'run-shell-start-directory']
    """
    return {
        "schema": SCHEMA,
        "port": PORT,
        "floor": {"minimum": TMUX_MIN_VERSION},
        "capabilities": [capability.to_manifest() for capability in CAPABILITIES],
        "workarounds": [workaround.to_manifest() for workaround in WORKAROUNDS],
    }


def render() -> str:
    """Return :func:`manifest` as the JSON text written to ``capabilities.json``.

    Examples
    --------
    >>> from libtmux._internal.support.capabilities import render
    >>> render().splitlines()[0]
    '{'
    """
    return json.dumps(manifest(), indent=2) + "\n"


def extract_version_token(raw_output: str) -> str:
    """Extract the version token from ``tmux -V`` output regardless of binary name.

    Examples
    --------
    >>> from libtmux._internal.support.capabilities import extract_version_token
    >>> extract_version_token("tmux 3.8a")
    '3.8a'
    >>> extract_version_token("tmux-3.3a 3.3a")
    '3.3a'
    """
    stripped = raw_output.strip()
    if not stripped:
        return ""
    parts = stripped.split(None, 1)
    return parts[1].strip() if len(parts) == 2 else parts[0]


def parse_tmux_release(raw: str) -> tuple[int, int, int, int] | None:
    """Parse a tmux version token into an ordered ``(major, minor, stage, patch)`` key.

    Orders ``next-X.Y < X.Y-rc < X.Y-rcN < X.Y < X.Ya`` and treats trunk
    ``master`` or OpenBSD ``*-openbsd`` builds as newer than tagged releases.
    """
    token = raw.strip()
    if not token:
        return None
    if token == "master" or token.endswith(("-master", "-openbsd")):
        return (999, 0, 2, 0)
    next_match = _NEXT_RE.match(token)
    if next_match is not None:
        return (int(next_match.group(1)), int(next_match.group(2)), 0, 0)
    rel_match = _RELEASE_RE.match(token)
    if rel_match is None:
        return None
    major_s, minor_s, patch_s, rc_s = rel_match.groups()
    if rc_s is not None:
        return (int(major_s), int(minor_s), 1, int(rc_s or 0))
    patch_num = ord(patch_s) - ord("a") + 1 if patch_s else 0
    return (int(major_s), int(minor_s), 2, patch_num)


def normalize_version_for_loose(raw: str) -> str:
    """Normalize a raw tmux version string for :class:`LooseVersion` callers."""
    parsed = parse_tmux_release(raw)
    if parsed is None:
        cleaned = re.sub(r"[a-z-]", "", raw)
        return cleaned or raw
    if parsed[0] == 999:
        return "99.0"
    return f"{parsed[0]}.{parsed[1]}"


def evaluate_capability(
    version: str,
    spec: Capability,
) -> tuple[t.Literal["supported", "unsupported", "unknown"], str]:
    """Evaluate *spec* against daemon *version*, returning ``(status, reason)``."""
    have = parse_tmux_release(version)
    if have is None:
        return ("unknown", f"unrecognized daemon version {version!r}")
    if version in spec.except_releases:
        return ("unsupported", f"excluded on connected tmux {version}")

    minimum = parse_tmux_release(spec.since)
    assert minimum is not None
    if have < minimum:
        return ("unsupported", f"requires connected tmux {spec.since} or newer")

    if spec.until is not None:
        upper = parse_tmux_release(spec.until)
        assert upper is not None
        upper_bound = (
            (upper[0], upper[1], 0, 0) if upper[2] == 2 and upper[3] == 0 else upper
        )
        if have >= upper_bound:
            return ("unsupported", f"removed in tmux {spec.until}")

    return ("supported", f"available on tmux {version}")


def supports_interval(
    version: str,
    *,
    since: str,
    until: str | None = None,
    except_releases: tuple[str, ...] = (),
) -> bool:
    """Return ``True`` if *version* satisfies ``[since, until)`` minus exclusions."""
    probe = Capability(
        id="_interval",
        name="_interval",
        summary="",
        since=since,
        handling="refuse",
        apis=(),
        commands=(),
        until=until,
        except_releases=except_releases,
    )
    status, _reason = evaluate_capability(version, probe)
    return status == "supported"


def probe_daemon_identity(
    engine: TmuxEngine,
    *,
    timeout: float | None = 5.0,
) -> DaemonIdentity | None:
    """Probe connected daemon ``(pid, start_time, version)`` without firing hooks.

    Executes ``-u -N run-shell -C`` with a random marker so ``run-shell -C``
    expands ``#{version}/#{pid}/#{start_time}`` inside ``cmd_run_shell_exec``
    and fails command lookup before any ``after-*`` hook can fire.
    """
    from libtmux._internal.protocols import dispatch_execute
    from libtmux.engine import TmuxRequest

    marker = f"__libtmux_cap_{secrets.token_hex(6)}_"
    req = TmuxRequest(
        commands=(
            ("run-shell", "-C", f"{marker}#{{version}}/#{{pid}}/#{{start_time}}"),
        ),
        client_args=("-u", "-N"),
        env={k: v for k, v in os.environ.items() if k != "TMUX"},
        timeout=timeout,
    )
    res = dispatch_execute(engine, req)
    stderr_text = res.stderr.decode("utf-8", errors="replace")
    prefix = f"unknown command: {marker}"
    for raw_line in stderr_text.splitlines():
        line = raw_line.strip()
        idx = line.find(prefix)
        if idx != -1:
            payload = line[idx + len(prefix) :].strip()
            parts = payload.split("/")
            if len(parts) == 3:
                ver_s, pid_s, start_s = parts
                try:
                    return DaemonIdentity(
                        pid=int(pid_s),
                        start_time=int(start_s),
                        version=ver_s,
                    )
                except ValueError:
                    return None
    lower = stderr_text.lower()
    if (
        "no server running" in lower
        or "no such file or directory" in lower
        or "connection refused" in lower
        or "error connecting to" in lower
    ):
        return None
    msg = stderr_text.strip() or f"capability probe failed (exit {res.returncode})"
    raise exc.LibTmuxException(msg)
