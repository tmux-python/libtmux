"""Tests for :class:`libtmux.aio.stream.PaneStream` and the Gap/capture_since pairing.

Every test runs under :func:`tests._aio.run_checked`; see that module for what
it fails on.
"""

from __future__ import annotations

import asyncio
import codecs
import itertools
import typing as t

import pytest

from libtmux import exc
from libtmux.aio.capture import capture_since
from libtmux.aio.stream import Gap, PaneStream
from libtmux.engines import (
    AsyncControlModeEngine,
    AsyncSubprocessEngine,
    CommandRequest,
)
from libtmux.server import Server

from ._aio import run_checked

if t.TYPE_CHECKING:
    from libtmux.pane import Pane


def request(*args: str, **kwargs: t.Any) -> CommandRequest:
    """Build a request."""
    return CommandRequest.from_args(*args, **kwargs)


def shell_pane(server: Server, name: str, *, history_limit: int = 50_000) -> Pane:
    """Return a fresh ``sh`` pane that keeps *history_limit* rows of scrollback.

    ``history-limit`` is read when a pane is created, and a server that is not
    running yet takes it from its configuration, so the server starts first and
    the pane comes after the option is set.
    """
    session = server.new_session(f"{name}_base", window_command="sh")
    server.cmd("set-option", "-g", "history-limit", str(history_limit))
    window = session.new_window(window_name=name, window_shell="sh", attach=False)
    pane = window.active_pane
    assert pane is not None
    return pane


def numbers(text: str) -> list[int]:
    """Return the ``L<n>`` numbers in *text*, in order."""
    return [int(w[1:]) for w in text.split() if w[:1] == "L" and w[1:].isdigit()]


def test_a_stream_delivers_what_the_pane_prints(server: Server) -> None:
    """Bytes arrive in order and decode incrementally, multi-byte text included."""
    pane = shell_pane(server, "text")
    pane_id = str(pane.pane_id)

    async def main() -> str:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            decoder = codecs.getincrementaldecoder("utf-8")()
            seen = ""
            async with PaneStream(engine, pane_id) as out:
                await engine.run(
                    request(
                        "send-keys",
                        "-t",
                        pane_id,
                        "printf 'caf\\303\\251 %s%s' stream _ok",
                        "Enter",
                    ),
                )
                async for item in out:
                    assert not isinstance(item, Gap)
                    seen += decoder.decode(item)
                    if "stream_ok" in seen.split("printf")[-1].replace("\r", ""):
                        return seen
        msg = "stream ended early"
        raise AssertionError(msg)

    assert "café stream_ok" in run_checked(main)


def test_an_engine_that_cannot_stream_is_refused(server: Server) -> None:
    """Only a control client receives pane output; anything else is an error."""
    with pytest.raises(exc.EngineError, match="cannot stream pane output"):
        PaneStream(AsyncSubprocessEngine.for_server(server), "%0")


def test_a_bad_policy_is_refused(server: Server) -> None:
    """``policy`` is ``watermark`` or ``unbounded``, nothing else."""

    async def main() -> None:
        engine = AsyncControlModeEngine.for_server(server)
        try:
            with pytest.raises(ValueError, match="policy"):
                PaneStream(engine, "%0", policy="drop_oldest")  # type: ignore[arg-type]
        finally:
            await engine.aclose()

    run_checked(main)


def test_leaving_the_context_turns_pane_output_off_again(server: Server) -> None:
    """With nobody listening, the client is told to send no pane output."""
    pane = shell_pane(server, "gate")
    pane_id = str(pane.pane_id)

    async def main() -> tuple[bool, bool, bool]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            async with PaneStream(engine, pane_id):
                during = not engine._silenced
            after = engine._silenced
            reuse = False
            async with PaneStream(engine, pane_id):  # the pane can be streamed again
                reuse = True
            return during, after, reuse

    assert run_checked(main) == (True, True, True)


def test_one_stream_per_pane(server: Server) -> None:
    """A second stream on a pane is refused while the first is open."""
    pane = shell_pane(server, "dup")
    pane_id = str(pane.pane_id)

    async def main() -> None:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            async with PaneStream(engine, pane_id):
                with pytest.raises(ValueError, match="already has an output stream"):
                    PaneStream(engine, pane_id)

    run_checked(main)


async def consume_flood(
    out: PaneStream,
    *,
    pause: float,
) -> tuple[list[str], int]:
    """Read *out* until the pane's sentinel; return one text per segment, and bytes."""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    segments = [""]
    total = 0
    async for item in out:
        if isinstance(item, Gap):
            segments.append("")
            continue
        total += len(item)
        text = decoder.decode(item)
        segments[-1] += text
        if pause:
            await asyncio.sleep(pause)
        if "SENTINEL" in text:
            break
    return segments, total


async def quiesce(engine: AsyncControlModeEngine, pane_id: str) -> None:
    """Return once the pane has printed nothing for 100 ms."""
    with engine.watch_output(pane_id) as watch:
        while await watch.changed(0.1):
            pass


def sentinel_line(n: int, server: Server) -> str:
    """Return the shell line that floods, signals, then heartbeats a sentinel."""
    done = f"tmux -L{server.socket_name} wait-for -S flood_done"
    return (
        f"i=1; while [ $i -le {n} ]; do echo L$i; i=$((i+1)); done; {done}; "
        "while :; do echo SEN''TINEL; sleep 0.05; done"
    )


@pytest.mark.parametrize("policy", ["watermark", "unbounded"])
def test_a_slow_consumer_is_bounded_or_lossless_by_policy(
    server: Server,
    policy: t.Literal["watermark", "unbounded"],
) -> None:
    """Watermark bounds the queue and reports loss; unbounded loses nothing."""
    pane = shell_pane(server, f"policy_{policy}")
    pane_id = str(pane.pane_id)
    total = 6000
    high = 2048

    async def main() -> tuple[list[str], int, int]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            async with PaneStream(
                engine, pane_id, high=high, low=512, policy=policy
            ) as out:
                consumer = asyncio.ensure_future(consume_flood(out, pause=0.002))
                await engine.run(
                    request(
                        "send-keys",
                        "-t",
                        pane_id,
                        sentinel_line(total, server),
                        "Enter",
                    ),
                )
                segments, _ = await asyncio.wait_for(consumer, 60)
                return segments, out.peak, out.gaps

    segments, peak, gaps = run_checked(main)

    if policy == "watermark":
        assert gaps >= 1
        assert peak < high * 8
    else:
        assert gaps == 0
        assert peak > high * 8
        assert numbers("".join(segments)) == list(range(1, total + 1))
    # A hole in the numbers can only sit at a Gap, whichever the policy.
    for segment in segments:
        for before, after in itertools.pairwise(numbers(segment)):
            assert after == before + 1


def test_a_gap_is_resynchronised_with_capture_since(server: Server) -> None:
    """On a Gap, ``capture_since(cursor)`` returns the whole flood: nothing is lost."""
    pane = shell_pane(server, "resync", history_limit=50_000)
    pane_id = str(pane.pane_id)
    total = 6000

    async def main() -> tuple[int, list[str], bool]:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            cursor = (await capture_since(engine, pane_id)).cursor
            async with PaneStream(engine, pane_id, high=8192, low=2048) as out:
                consumer = asyncio.ensure_future(consume_flood(out, pause=0.002))
                await engine.run(
                    request(
                        "send-keys",
                        "-t",
                        pane_id,
                        sentinel_line(total, server),
                        "Enter",
                    ),
                )
                await asyncio.wait_for(consumer, 60)
                gaps = out.gaps
            await engine.run(request("send-keys", "-t", pane_id, "C-c"))
            await quiesce(engine, pane_id)
            resync = await capture_since(engine, pane_id, cursor)
            return gaps, resync.lines, resync.lines_missed

    gaps, lines, missed = run_checked(main)

    assert gaps >= 1
    assert not missed
    assert numbers("\n".join(lines))[:total] == list(range(1, total + 1))


def test_a_resync_after_the_history_is_gone_says_so(server: Server) -> None:
    """With a short history the flood scrolls the anchor away: ``lines_missed``."""
    pane = shell_pane(server, "scrolled", history_limit=300)
    pane_id = str(pane.pane_id)
    total = 6000

    async def main() -> bool:
        async with AsyncControlModeEngine.for_server(server) as engine:
            await engine.run(request("display-message", "-p", "attach"))
            cursor = (await capture_since(engine, pane_id)).cursor
            async with PaneStream(engine, pane_id, high=8192, low=2048) as out:
                consumer = asyncio.ensure_future(consume_flood(out, pause=0.0))
                await engine.run(
                    request(
                        "send-keys",
                        "-t",
                        pane_id,
                        sentinel_line(total, server),
                        "Enter",
                    ),
                )
                await asyncio.wait_for(consumer, 60)
            return (await capture_since(engine, pane_id, cursor)).lines_missed

    assert run_checked(main)
