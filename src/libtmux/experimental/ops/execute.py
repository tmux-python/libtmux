"""Execute an operation through an engine and get back its typed result.

These two helpers are the whole bridge between the inert operation substrate and
the engines. They share the operation's pure :meth:`~.operation.Operation.render`
and :meth:`~.operation.Operation.build_result`; the *only* difference between the
sync and async paths is ``engine.run(...)`` versus ``await engine.run(...)`` --
the same sans-I/O split the lazy plan resolver uses.
"""

from __future__ import annotations

import dataclasses
import typing as t

from libtmux.experimental.engines.base import CommandRequest, SupportsTmuxVersion

if t.TYPE_CHECKING:
    import pathlib

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result

ResultT = t.TypeVar("ResultT", bound="Result")


def _merge_follow_up(result: ResultT, follow_up: Result) -> ResultT:
    """Merge a typed follow-up outcome into its primary operation result.

    The primary payload remains available even when the follow-up fails. Its
    status and diagnostics then describe the complete logical operation.

    Examples
    --------
    >>> from libtmux.experimental.ops import BreakPane, RenameWindow
    >>> from libtmux.experimental.ops._types import PaneId, WindowId
    >>> primary = BreakPane(src_target=PaneId("%1")).build_result(
    ...     returncode=0, stdout=("@2",)
    ... )
    >>> follow_up = RenameWindow(
    ...     target=WindowId("@2"), name="logs"
    ... ).build_result(returncode=0)
    >>> merged = _merge_follow_up(primary, follow_up)
    >>> merged.ok, merged.new_id
    (True, '@2')
    >>> merged.argv[-6:]
    (';', 'rename-window', '-t', '@2', '--', 'logs')
    """
    argv = (*result.argv, ";", *follow_up.argv)
    if follow_up.ok:
        return dataclasses.replace(result, argv=argv)
    return dataclasses.replace(
        result,
        argv=argv,
        status=follow_up.status,
        returncode=follow_up.returncode,
        stderr=(*result.stderr, *follow_up.stderr),
    )


def resolve_engine_version(
    engine: TmuxEngine | AsyncTmuxEngine,
    version: str | None,
) -> str | None:
    """Resolve the tmux version to render against.

    Returns *version* unchanged when the caller supplied one. Otherwise asks the
    engine via the optional
    :class:`~libtmux.experimental.engines.base.SupportsTmuxVersion` capability,
    so version-gated rendering (flag drops and whole-command gates) reflects the
    live tmux at runtime instead of silently assuming latest. Engines that cannot
    report a version fall back to ``None`` ("assume latest").

    Examples
    --------
    >>> from libtmux.experimental.engines import CommandResult
    >>> class VersionedEngine:
    ...     def run(self, request):
    ...         return CommandResult(cmd=("tmux", *request.args), returncode=0)
    ...     def run_batch(self, requests):
    ...         return [self.run(r) for r in requests]
    ...     def tmux_version(self):
    ...         return "2.9"
    >>> resolve_engine_version(VersionedEngine(), None)
    '2.9'
    >>> resolve_engine_version(VersionedEngine(), "3.4")
    '3.4'
    """
    if version is not None:
        return version
    if isinstance(engine, SupportsTmuxVersion):
        return engine.tmux_version()
    return None


def run(
    operation: Operation[ResultT],
    engine: TmuxEngine,
    *,
    version: str | None = None,
    tmux_bin: str | pathlib.Path | None = None,
) -> ResultT:
    """Render *operation*, run it through *engine*, return its typed result.

    Parameters
    ----------
    operation : Operation
        The operation to execute.
    engine : TmuxEngine
        Any synchronous engine.
    version : str or None
        tmux version to render against (drops unsupported flags); ``None``
        renders every flag.
    tmux_bin : str or pathlib.Path or None
        Override the tmux binary for this call.

    Returns
    -------
    ResultT
        The operation's specialized result.

    Examples
    --------
    >>> from libtmux.experimental.ops import SendKeys, run
    >>> from libtmux.experimental.ops._types import PaneId
    >>> from libtmux.experimental.engines import CommandResult
    >>> class EchoEngine:
    ...     def run(self, request):
    ...         return CommandResult(cmd=("tmux", *request.args), returncode=0)
    ...     def run_batch(self, requests):
    ...         return [self.run(r) for r in requests]
    >>> result = run(SendKeys(target=PaneId("%1"), keys="echo hi"), EchoEngine())
    >>> result.ok
    True
    >>> result.argv
    ('send-keys', '-t', '%1', '--', 'echo hi')
    """
    version = resolve_engine_version(engine, version)
    rendered = operation.render(version=version)
    raw = engine.run(
        CommandRequest(
            args=rendered,
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
        ),
    )
    result = operation.build_result(
        argv=rendered,
        returncode=raw.returncode,
        stdout=raw.stdout,
        stderr=raw.stderr,
        version=version,
    )
    follow_up = operation._follow_up(result, version=version)
    if follow_up is None:
        return result
    follow_up_result = run(
        follow_up,
        engine,
        version=version,
        tmux_bin=tmux_bin,
    )
    return _merge_follow_up(result, follow_up_result)


async def arun(
    operation: Operation[ResultT],
    engine: AsyncTmuxEngine,
    *,
    version: str | None = None,
    tmux_bin: str | pathlib.Path | None = None,
) -> ResultT:
    """Async sibling of :func:`run`, sharing the same render/build path.

    Examples
    --------
    >>> import asyncio
    >>> from libtmux.experimental.ops import arun, CapturePane
    >>> from libtmux.experimental.ops._types import PaneId
    >>> from libtmux.experimental.engines import CommandResult
    >>> class AsyncEchoEngine:
    ...     async def run(self, request):
    ...         return CommandResult(
    ...             cmd=("tmux", *request.args),
    ...             stdout=("line-1", "line-2"),
    ...             returncode=0,
    ...         )
    ...     async def run_batch(self, requests):
    ...         return [await self.run(r) for r in requests]
    >>> async def main():
    ...     return await arun(CapturePane(target=PaneId("%1")), AsyncEchoEngine())
    >>> result = asyncio.run(main())
    >>> result.lines
    ('line-1', 'line-2')
    """
    version = resolve_engine_version(engine, version)
    rendered = operation.render(version=version)
    raw = await engine.run(
        CommandRequest(
            args=rendered,
            tmux_bin=str(tmux_bin) if tmux_bin is not None else None,
        ),
    )
    result = operation.build_result(
        argv=rendered,
        returncode=raw.returncode,
        stdout=raw.stdout,
        stderr=raw.stderr,
        version=version,
    )
    follow_up = operation._follow_up(result, version=version)
    if follow_up is None:
        return result
    follow_up_result = await arun(
        follow_up,
        engine,
        version=version,
        tmux_bin=tmux_bin,
    )
    return _merge_follow_up(result, follow_up_result)
