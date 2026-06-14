r"""Immutable argv intermediate representation for tmux command sequences.

This module is the substrate for the chainable-commands API. A
:class:`CommandCall` is one typed tmux command before dispatch; a
:class:`CommandChain` is an ordered group of calls that renders to a single
native ``tmux ... \\; ...`` invocation and dispatches once through a
:class:`CommandRunner` (which a live :class:`libtmux.Server` already satisfies).

Note
----
This is an **experimental** API, not covered by the project's versioning policy.
It may change or be removed between any releases without notice.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass

Arg: t.TypeAlias = "str | int"
"""A single tmux argument token. Integers are rendered with :func:`str`."""

CommandScope: t.TypeAlias = t.Literal["server", "session", "window", "pane"]
"""The tmux object scope a command targets."""


class CommandResultLike(t.Protocol):
    """Result protocol matching the libtmux command-result surface.

    A live :class:`libtmux.common.tmux_cmd` satisfies this protocol, as does
    any object exposing ``stdout``/``stderr`` line lists and a ``returncode``.
    """

    stdout: list[str]
    stderr: list[str]
    returncode: int


class CommandRunner(t.Protocol):
    """Object capable of dispatching one tmux command argv.

    A live :class:`libtmux.Server` already matches this protocol via its
    ``cmd()`` method, so sequences can be dispatched without an adapter for the
    common case. Object-level ``cmd()`` wrappers such as ``Session.cmd()`` add
    their own target context; use ``session.server`` or
    :class:`~libtmux._experimental.chain._connection.SessionPlanExecutor` for
    composed command sequences.
    """

    def cmd(
        self,
        cmd: str,
        *args: Arg,
        target: str | int | None = None,
    ) -> CommandResultLike:
        """Dispatch a single tmux command and return its result."""
        ...


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Static metadata describing a tmux command.

    Parameters
    ----------
    name : str
        The tmux command name, e.g. ``"rename-window"``.
    scope : CommandScope
        The tmux object scope the command targets.
    chainable : bool
        Whether the command may be folded into a one-dispatch sequence. A
        command is chainable only when its output is not consumed mid-chain;
        commands that must return output immediately (e.g. ``show-option``) set
        this to ``False``.

    Examples
    --------
    >>> CommandSpec(name="rename-window", scope="window")
    CommandSpec(name='rename-window', scope='window', chainable=True)
    >>> CommandSpec(name="show-option", scope="server", chainable=False).chainable
    False
    """

    name: str
    scope: CommandScope
    chainable: bool = True


@dataclass(frozen=True, slots=True)
class CommandCall:
    """One typed tmux command call before subprocess dispatch.

    Parameters
    ----------
    name : str
        The tmux command name.
    args : tuple[Arg, ...]
        Positional argument tokens, rendered in order after the target.
    target : str | int | None
        Optional ``-t`` target inserted immediately after the command name.

    Examples
    --------
    >>> CommandCall("new-window", ("-d", "-n", "work")).argv()
    ('new-window', '-d', '-n', 'work')

    A target is rendered as a ``-t`` flag right after the command name:

    >>> CommandCall("split-window", ("-h",), target="%1").argv()
    ('split-window', '-t', '%1', '-h')
    """

    name: str
    args: tuple[Arg, ...] = ()
    target: str | int | None = None

    def argv(self) -> tuple[str, ...]:
        """Render this call as tmux argv tokens.

        Returns
        -------
        tuple[str, ...]
            The command name, optional ``-t <target>``, then each argument.

        Examples
        --------
        >>> CommandCall("kill-window", target="@1").argv()
        ('kill-window', '-t', '@1')
        """
        rendered: list[str] = [self.name]
        if self.target is not None:
            rendered.extend(("-t", str(self.target)))
        rendered.extend(_render_arg(arg) for arg in self.args)
        return tuple(rendered)

    def then(self, other: CommandCall | CommandChain) -> CommandChain:
        """Return a sequence with ``other`` appended after this call.

        Parameters
        ----------
        other : CommandCall | CommandChain
            The call or sequence to append.

        Returns
        -------
        CommandChain

        Examples
        --------
        >>> seq = CommandCall("new-window").then(CommandCall("split-window"))
        >>> seq.argvs()
        (('new-window',), ('split-window',))
        """
        if isinstance(other, CommandCall):
            return CommandChain((self, other))
        return CommandChain((self, *other.calls))

    def __rshift__(self, other: CommandCall | CommandChain) -> CommandChain:
        """Compose command calls with ``>>``.

        Examples
        --------
        >>> (CommandCall("new-window") >> CommandCall("split-window")).argv()
        ('new-window', ';', 'split-window')
        """
        return self.then(other)


@dataclass(frozen=True, slots=True)
class CommandChain:
    r"""An ordered tmux command sequence dispatched as one invocation.

    A sequence renders to a single argv list using standalone ``;`` separator
    tokens, mirroring tmux's native command-sequence syntax
    (``tmux cmd-a \\; cmd-b``). Later commands do not run if an earlier command
    in the sequence errors -- the same semantics tmux applies to ``;`` chains.

    Parameters
    ----------
    calls : tuple[CommandCall, ...]
        The ordered, non-empty calls in the sequence.

    Examples
    --------
    >>> seq = CommandCall("new-window", ("-d",)) >> CommandCall("split-window", ("-h",))
    >>> seq.argv()
    ('new-window', '-d', ';', 'split-window', '-h')
    """

    calls: tuple[CommandCall, ...]

    def __post_init__(self) -> None:
        """Reject empty sequences.

        Examples
        --------
        >>> CommandChain(())
        Traceback (most recent call last):
        ...
        ValueError: CommandChain requires at least one call
        """
        if not self.calls:
            msg = "CommandChain requires at least one call"
            raise ValueError(msg)

    def argv(self) -> tuple[str, ...]:
        """Render the full sequence with tmux ``;`` separators.

        Returns
        -------
        tuple[str, ...]
            One flat argv list, with a standalone ``";"`` token between calls.

        Examples
        --------
        >>> seq = CommandCall("rename-window", ("work",)) >> CommandCall("split-window")
        >>> seq.argv()
        ('rename-window', 'work', ';', 'split-window')
        """
        rendered: list[str] = []
        for index, call in enumerate(self.calls):
            if index:
                rendered.append(";")
            rendered.extend(call.argv())
        return tuple(rendered)

    def argvs(self) -> tuple[tuple[str, ...], ...]:
        """Render each call independently, without separators.

        Returns
        -------
        tuple[tuple[str, ...], ...]
            One argv tuple per call. Useful for asserting the compiled commands
            in tests without reasoning about ``;`` placement.

        Examples
        --------
        >>> seq = CommandCall("rename-window", ("work",)) >> CommandCall("split-window")
        >>> seq.argvs()
        (('rename-window', 'work'), ('split-window',))
        """
        return tuple(call.argv() for call in self.calls)

    def then(self, other: CommandCall | CommandChain) -> CommandChain:
        """Return a sequence with ``other`` appended.

        Parameters
        ----------
        other : CommandCall | CommandChain

        Returns
        -------
        CommandChain

        Examples
        --------
        >>> base = CommandChain((CommandCall("new-window"),))
        >>> base.then(CommandCall("split-window")).argvs()
        (('new-window',), ('split-window',))
        """
        if isinstance(other, CommandCall):
            return CommandChain((*self.calls, other))
        return CommandChain((*self.calls, *other.calls))

    def __rshift__(self, other: CommandCall | CommandChain) -> CommandChain:
        """Compose sequences with ``>>``.

        Examples
        --------
        >>> seq = CommandChain((CommandCall("new-window"),))
        >>> (seq >> CommandCall("kill-window")).argvs()
        (('new-window',), ('kill-window',))
        """
        return self.then(other)

    def run(self, runner: CommandRunner) -> CommandResultLike:
        """Dispatch the whole sequence through one runner call.

        Parameters
        ----------
        runner : CommandRunner
            Any object with a ``Server.cmd``-shaped ``cmd()`` method. A live
            :class:`libtmux.Server` works directly.

        Returns
        -------
        CommandResultLike
            The single result of the one-shot dispatch.

        Examples
        --------
        Two server options set in a single tmux invocation:

        >>> seq = (
        ...     CommandCall("set-option", ("-g", "@cc_demo_a", "1"))
        ...     >> CommandCall("set-option", ("-g", "@cc_demo_b", "2"))
        ... )
        >>> result = seq.run(session.server)
        >>> result.returncode
        0
        >>> session.server.cmd("show-option", "-gv", "@cc_demo_b").stdout
        ['2']
        """
        argv = self.argv()
        return runner.cmd(argv[0], *argv[1:])


def _render_arg(arg: Arg) -> str:
    r"""Render one argument token, escaping a trailing tmux separator.

    A literal argument that ends in ``;`` is escaped to ``\;`` so tmux does not
    mistake it for a command separator inside a sequence.

    Examples
    --------
    >>> _render_arg(50)
    '50'
    >>> _render_arg("echo hi;")
    'echo hi\\;'
    """
    text = str(arg)
    if text.endswith(";"):
        return f"{text[:-1]}\\;"
    return text
