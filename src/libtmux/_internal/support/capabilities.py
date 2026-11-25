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
import typing as t
from dataclasses import dataclass

from libtmux._internal.support.versions import MINIMUM

SCHEMA = "libtmux-capabilities/1"
PORT = "py"

Handling: t.TypeAlias = t.Literal["refuse", "fallback", "repair"]


@dataclass(frozen=True)
class Command:
    """A tmux command a capability concerns, with the flags it adds."""

    command: str
    flags: tuple[str, ...] = ()


@dataclass(frozen=True)
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
    handling : str
        What libtmux does on an older tmux. ``"fallback"`` warns and sends
        the command without the flag; ``"refuse"`` raises before tmux runs.
    apis : tuple[str, ...]
        Public names that need the capability.
    commands : tuple[Command, ...]
        tmux commands and flags it concerns.
    error : str or None
        Exception a refusal raises. Set when *handling* is ``"refuse"``.
    """

    id: str
    name: str
    summary: str
    since: str
    handling: Handling
    apis: tuple[str, ...]
    commands: tuple[Command, ...]
    error: str | None = None

    def to_manifest(self) -> dict[str, t.Any]:
        """Return this capability as a manifest entry.

        Examples
        --------
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
            "handling": self.handling,
        }
        if self.error is not None:
            entry["error"] = self.error
        entry["apis"] = list(self.apis)
        entry["commands"] = [
            {"command": command.command, "flags": list(command.flags)}
            if command.flags
            else {"command": command.command}
            for command in self.commands
        ]
        return entry


CAPABILITIES: tuple[Capability, ...] = (
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
        apis=("libtmux.Pane.new_pane",),
        commands=(Command("new-pane"),),
        error="libtmux.exc.LibTmuxException",
    ),
)

_BY_ID: dict[str, Capability] = {
    capability.id: capability for capability in CAPABILITIES
}


def get(capability_id: str) -> Capability:
    """Return the capability named *capability_id*.

    Raises
    ------
    KeyError
        The table defines no capability with that id.

    Examples
    --------
    >>> get("floating-pane").since
    '3.7'
    """
    return _BY_ID[capability_id]


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
    >>> capability_since("run-shell-start-directory")
    '3.4'
    """
    return get(capability_id).since


def manifest() -> dict[str, t.Any]:
    """Return the capability manifest as ``capabilities.json`` stores it.

    Examples
    --------
    >>> doc = manifest()
    >>> doc["schema"], doc["port"]
    ('libtmux-capabilities/1', 'py')
    >>> [entry["id"] for entry in doc["capabilities"]][:2]
    ['run-shell-start-directory', 'run-shell-start-directory-format']
    """
    return {
        "schema": SCHEMA,
        "port": PORT,
        "floor": {"minimum": MINIMUM},
        "capabilities": [capability.to_manifest() for capability in CAPABILITIES],
        "workarounds": [],
    }


def render() -> str:
    """Return :func:`manifest` as the JSON text written to ``capabilities.json``.

    Examples
    --------
    >>> render().splitlines()[0]
    '{'
    """
    return json.dumps(manifest(), indent=2) + "\n"
