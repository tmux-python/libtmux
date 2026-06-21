"""Execute an operation through an engine and get back its typed result.

These two helpers are the whole bridge between the inert operation substrate and
the engines. They share the operation's pure :meth:`~.operation.Operation.render`
and :meth:`~.operation.Operation.build_result`; the *only* difference between the
sync and async paths is ``engine.run(...)`` versus ``await engine.run(...)`` --
the same sans-I/O split the lazy plan resolver uses.
"""

from __future__ import annotations

import typing as t

from libtmux.experimental.engines.base import CommandRequest

if t.TYPE_CHECKING:
    import pathlib

    from libtmux.experimental.engines.base import AsyncTmuxEngine, TmuxEngine
    from libtmux.experimental.ops.operation import Operation
    from libtmux.experimental.ops.results import Result

ResultT = t.TypeVar("ResultT", bound="Result")


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
    ('send-keys', '-t', '%1', 'echo hi')
    """
    rendered = operation.render(version=version)
    raw = engine.run(CommandRequest.from_args(*rendered, tmux_bin=tmux_bin))
    return operation.build_result(
        argv=rendered,
        returncode=raw.returncode,
        stdout=raw.stdout,
        stderr=raw.stderr,
    )


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
    rendered = operation.render(version=version)
    raw = await engine.run(CommandRequest.from_args(*rendered, tmux_bin=tmux_bin))
    return operation.build_result(
        argv=rendered,
        returncode=raw.returncode,
        stdout=raw.stdout,
        stderr=raw.stderr,
    )
