"""Internal payload-aware safety policy for MCP operation projection.

The operation layer describes tmux commands in isolation. The MCP boundary adds
agent-facing policy for concrete payloads: ``kill=True`` escalates otherwise
mutating operations, host-shell/config execution requires destructive access,
and open-world payload transfer is disclosed independently.
"""

from __future__ import annotations

import dataclasses
import re
import typing as t

from libtmux.experimental.ops import registry as ops_registry

if t.TYPE_CHECKING:
    from collections.abc import Mapping

    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.registry import OpSpec

_SIMPLE_FORMAT_FIELD = re.compile(r"[A-Za-z0-9_@-]+")
_STATIC_OPTION_NAME = re.compile(r"(?P<name>[A-Za-z0-9_@-]+)(?:\[[0-9]+\])?")

# Fields handed to a shell by tmux. A nonblank value is an executable payload.
_COMMAND_BODY_FIELDS: Mapping[str, str] = {
    "new_pane": "shell_command",
    "new_session": "window_shell",
    "new_window": "window_shell",
    "pipe_pane": "command_line",
    "respawn_pane": "shell",
    "respawn_window": "shell",
    "set_hook": "hook_command",
    "split_window": "shell",
}

# Per-command environment overrides are merged into the child environment
# immediately before tmux execs it. Session environment writes affect future
# panes in the same way.
_ENVIRONMENT_FIELDS: Mapping[str, str] = {
    "new_pane": "environment",
    "new_session": "environment",
    "new_window": "environment",
    "respawn_pane": "environment",
    "respawn_window": "environment",
    "split_window": "environment",
}

# tmux command-list options, strings consumed as commands, and the
# ``update-environment`` process-environment import list. This follows
# options-table.c plus the consumers in cmd.c, environ.c, popup.c, server-fn.c,
# spawn.c, and window-copy.c. Array options may be addressed as ``name[index]``
# or by an unambiguous prefix.
_EXECUTABLE_OPTION_NAMES = frozenset(
    {
        "after-bind-key",
        "after-capture-pane",
        "after-copy-mode",
        "after-display-message",
        "after-display-panes",
        "after-kill-pane",
        "after-list-buffers",
        "after-list-clients",
        "after-list-keys",
        "after-list-panes",
        "after-list-sessions",
        "after-list-windows",
        "after-load-buffer",
        "after-lock-server",
        "after-new-session",
        "after-new-window",
        "after-paste-buffer",
        "after-pipe-pane",
        "after-queue",
        "after-refresh-client",
        "after-rename-session",
        "after-rename-window",
        "after-resize-pane",
        "after-resize-window",
        "after-save-buffer",
        "after-select-layout",
        "after-select-pane",
        "after-select-window",
        "after-send-keys",
        "after-set-buffer",
        "after-set-environment",
        "after-set-hook",
        "after-set-option",
        "after-show-environment",
        "after-show-messages",
        "after-show-options",
        "after-split-window",
        "after-unbind-key",
        "alert-activity",
        "alert-bell",
        "alert-silence",
        "client-active",
        "client-attached",
        "client-dark-theme",
        "client-detached",
        "client-focus-in",
        "client-focus-out",
        "client-light-theme",
        "client-resized",
        "client-session-changed",
        "command-alias",
        "command-error",
        "copy-command",
        "default-client-command",
        "default-command",
        "default-shell",
        "editor",
        "lock-command",
        "pane-died",
        "pane-exited",
        "pane-focus-in",
        "pane-focus-out",
        "pane-mode-changed",
        "pane-set-clipboard",
        "pane-title-changed",
        "session-closed",
        "session-created",
        "session-renamed",
        "session-window-changed",
        "update-environment",
        "window-layout-changed",
        "window-linked",
        "window-pane-changed",
        "window-renamed",
        "window-resized",
        "window-unlinked",
    }
)

# Fields expanded by tmux or stored as a format that tmux may render later.
# A bounded grammar keeps simple queries at their base tier without attempting
# to duplicate tmux's recursively extensible format parser.
_FORMAT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "break_pane": ("name",),
    "display_message": ("message",),
    "load_buffer": ("path",),
    "new_pane": (
        "width",
        "height",
        "x",
        "y",
        "start_directory",
        "style",
        "active_border_style",
        "inactive_border_style",
        "message",
    ),
    "new_session": ("session_name", "start_directory"),
    "new_window": ("name", "start_directory"),
    "rename_session": ("name",),
    "rename_window": ("name",),
    "respawn_pane": ("start_directory",),
    "respawn_window": ("start_directory",),
    "save_buffer": ("path",),
    "select_pane": ("title",),
    "set_hook": ("name",),
    "set_option": ("option", "value"),
    "set_window_option": ("option", "value"),
    "split_window": ("start_directory",),
}

# Open-world is capability disclosure, not a synonym for destructive. Pane
# input and buffer transfer stay mutating while accurately advertising that
# caller-controlled content crosses into a pane, process, file, or tmux format.
OPEN_WORLD_OPERATION_KINDS = frozenset(
    {
        *_COMMAND_BODY_FIELDS,
        *_ENVIRONMENT_FIELDS,
        *_FORMAT_FIELDS,
        "paste_buffer",
        "run_shell",
        "send_keys",
        "set_buffer",
        "set_environment",
        "source_file",
    }
)

_CURATED_OPEN_WORLD_TOOLS = frozenset(
    {
        "break_pane",
        "create_session",
        "create_window",
        "display_message",
        "new_pane",
        "paste_buffer",
        "rename_session",
        "rename_window",
        "respawn_pane",
        "run_tmux",
        "send_input",
        "set_buffer",
        "set_option",
        "split_pane",
    }
)

_CURATED_FORMAT_FIELDS: Mapping[str, tuple[str, ...]] = {
    "break_pane": ("name",),
    "create_session": ("name", "start_directory"),
    "create_window": ("name", "start_directory"),
    "display_message": ("message",),
    "new_pane": ("width", "height", "x", "y", "start_directory"),
    "rename_session": ("name",),
    "rename_window": ("name",),
    "respawn_pane": ("start_directory",),
    "set_option": ("option", "value"),
    "split_pane": ("start_directory",),
}

_CURATED_COMMAND_BODY_FIELDS: Mapping[str, str] = {
    "new_pane": "shell_command",
    "respawn_pane": "shell",
}

_CURATED_ENVIRONMENT_FIELDS: Mapping[str, str] = {
    "create_session": "environment",
}


def _is_bounded_safe_format(value: str | None) -> bool:
    """Return whether *value* uses only inert tmux format constructs.

    The safe grammar is plain text, escaped hash pairs, and simple
    ``#{field_name}`` lookups. An active job, modifier, conditional, nested
    expression, legacy alias, or malformed field fails closed. In particular,
    ``E`` and ``T`` modifiers can recursively expand an option containing
    ``#(shell-command)``.

    Examples
    --------
    >>> _is_bounded_safe_format("plain #{pane_id}")
    True
    >>> _is_bounded_safe_format("##(literal)")
    True
    >>> _is_bounded_safe_format("#(uname)")
    False
    >>> _is_bounded_safe_format("#{E:@status}")
    False
    >>> _is_bounded_safe_format("###(uname)")
    False
    """
    if value is None:
        return True
    index = 0
    while index < len(value):
        if value[index] != "#":
            index += 1
            continue
        run_end = index
        while run_end < len(value) and value[run_end] == "#":
            run_end += 1
        if (run_end - index) % 2 == 0:
            index = run_end
            continue
        if run_end >= len(value) or value[run_end] != "{":
            return False
        field_end = value.find("}", run_end + 1)
        if field_end == -1:
            return False
        field = value[run_end + 1 : field_end]
        if _SIMPLE_FORMAT_FIELD.fullmatch(field) is None:
            return False
        index = field_end + 1
    return True


def _has_command_body(kind: str, payload: Mapping[str, t.Any]) -> bool:
    """Return whether *payload* supplies an active shell/config command."""
    field = _COMMAND_BODY_FIELDS.get(kind)
    if field is None:
        return False
    if kind == "set_hook" and bool(payload.get("unset")):
        return False
    return bool(str(payload.get(field) or "").strip())


def _has_environment_injection(kind: str, payload: Mapping[str, t.Any]) -> bool:
    """Return whether *payload* can alter a future child process environment."""
    if kind == "set_environment":
        return (
            payload.get("value") is not None
            and not bool(payload.get("remove"))
            and not bool(payload.get("unset"))
        )
    field = _ENVIRONMENT_FIELDS.get(kind)
    return field is not None and bool(payload.get(field))


def _option_identity_may_execute(value: t.Any) -> bool:
    """Return whether a static or dynamic option name may hold executable code."""
    if not isinstance(value, str) or not value:
        return True
    if "#" in value:
        return True
    match = _STATIC_OPTION_NAME.fullmatch(value)
    if match is None:
        return True
    name = match.group("name")
    if name.startswith("@"):
        return False
    return any(candidate.startswith(name) for candidate in _EXECUTABLE_OPTION_NAMES)


def _has_executable_option_assignment(
    kind: str,
    payload: Mapping[str, t.Any],
) -> bool:
    """Return whether a concrete option assignment may install a command."""
    return (
        kind in {"set_option", "set_window_option"}
        and payload.get("value") is not None
        and not bool(payload.get("unset"))
        and _option_identity_may_execute(payload.get("option"))
    )


def _has_unsafe_format(kind: str, payload: Mapping[str, t.Any]) -> bool:
    """Return whether a format-bearing field exceeds the bounded grammar."""
    fields = _FORMAT_FIELDS.get(kind, ())
    for field in fields:
        if field == "value" and bool(payload.get("unset")):
            continue
        value = payload.get(field)
        if isinstance(value, str) and not _is_bounded_safe_format(value):
            return True
    return False


def operation_safety(operation: Operation[t.Any]) -> str:
    """Return the effective MCP tier for one concrete operation payload.

    Examples
    --------
    >>> from libtmux.experimental.ops import (
    ...     DisplayMessage, PipePane, RespawnPane, RunShell, SourceFile
    ... )
    >>> operation_safety(RespawnPane(kill=False))
    'mutating'
    >>> operation_safety(RespawnPane(kill=True))
    'destructive'
    >>> operation_safety(RunShell(command_line="echo hi"))
    'destructive'
    >>> operation_safety(SourceFile(path="tmux.conf", no_exec=True))
    'mutating'
    >>> operation_safety(PipePane(command_line="cat >log"))
    'destructive'
    >>> operation_safety(PipePane())
    'mutating'
    >>> operation_safety(DisplayMessage(message="#{pane_id}"))
    'readonly'
    >>> operation_safety(DisplayMessage(message="#{E:@status}"))
    'destructive'
    """
    spec = ops_registry.get(operation.kind)
    payload = {
        field.name: getattr(operation, field.name)
        for field in dataclasses.fields(operation)
    }
    if (
        spec.effects.destructive
        or bool(getattr(operation, "kill", False))
        or operation.kind == "run_shell"
        or (
            operation.kind == "source_file"
            and not bool(getattr(operation, "no_exec", False))
        )
        or _has_command_body(operation.kind, payload)
        or _has_environment_injection(operation.kind, payload)
        or _has_executable_option_assignment(operation.kind, payload)
        or _has_unsafe_format(operation.kind, payload)
    ):
        return "destructive"
    return spec.safety


def projected_spec_safety(spec: OpSpec) -> str:
    """Return the static MCP tier for an operation tool descriptor.

    A command with no safe payload, currently ``run_shell``, is hidden below
    destructive. Parameterized commands remain at their base tier and are
    payload-gated at runtime.

    Examples
    --------
    >>> projected_spec_safety(ops_registry.get("run_shell"))
    'destructive'
    >>> projected_spec_safety(ops_registry.get("source_file"))
    'mutating'
    """
    if spec.kind == "run_shell":
        return "destructive"
    return spec.safety


def spec_can_destroy(spec: OpSpec) -> bool:
    """Return whether any payload of *spec* can destroy or execute host code.

    Examples
    --------
    >>> spec_can_destroy(ops_registry.get("capture_pane"))
    False
    >>> spec_can_destroy(ops_registry.get("unlink_window"))
    True
    >>> spec_can_destroy(ops_registry.get("source_file"))
    True
    """
    kill_variant = any(
        field.name == "kill" for field in dataclasses.fields(spec.operation_cls)
    )
    return (
        spec.effects.destructive
        or kill_variant
        or spec.kind == "run_shell"
        or spec.kind == "source_file"
        or spec.kind in _COMMAND_BODY_FIELDS
        or spec.kind in _ENVIRONMENT_FIELDS
        or spec.kind == "set_environment"
        or spec.kind in _FORMAT_FIELDS
    )


def spec_is_open_world(spec: OpSpec) -> bool:
    """Return whether *spec* can execute host code or read an external config.

    Examples
    --------
    >>> spec_is_open_world(ops_registry.get("run_shell"))
    True
    >>> spec_is_open_world(ops_registry.get("send_keys"))
    True
    """
    return spec.kind in OPEN_WORLD_OPERATION_KINDS


def curated_call_safety(
    name: str,
    arguments: Mapping[str, t.Any],
    base_safety: str,
) -> str:
    """Return the effective tier for one curated-tool call.

    Examples
    --------
    >>> curated_call_safety("display_message", {"message": "#{pane_id}"}, "readonly")
    'readonly'
    >>> curated_call_safety("display_message", {"message": "#{T:@status}"}, "readonly")
    'destructive'
    >>> curated_call_safety("send_input", {"keys": "rm -f file"}, "mutating")
    'mutating'
    """
    if name == "respawn_pane" and bool(arguments.get("kill")):
        return "destructive"
    command_field = _CURATED_COMMAND_BODY_FIELDS.get(name)
    if command_field is not None and bool(
        str(arguments.get(command_field) or "").strip()
    ):
        return "destructive"
    environment_field = _CURATED_ENVIRONMENT_FIELDS.get(name)
    if environment_field is not None and bool(arguments.get(environment_field)):
        return "destructive"
    if _has_executable_option_assignment(name, arguments):
        return "destructive"
    for field in _CURATED_FORMAT_FIELDS.get(name, ()):
        if field == "value" and bool(arguments.get("unset")):
            continue
        value = arguments.get(field)
        if isinstance(value, str) and not _is_bounded_safe_format(value):
            return "destructive"
    return base_safety


def curated_can_destroy(name: str, base_safety: str) -> bool:
    """Return whether any curated-tool payload can be destructive."""
    return (
        base_safety == "destructive"
        or name == "respawn_pane"
        or name in _CURATED_COMMAND_BODY_FIELDS
        or name in _CURATED_ENVIRONMENT_FIELDS
        or name in _CURATED_FORMAT_FIELDS
    )


def curated_is_open_world(name: str) -> bool:
    """Return whether a curated tool can cross an open-world boundary."""
    return name in _CURATED_OPEN_WORLD_TOOLS
