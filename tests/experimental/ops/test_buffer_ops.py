"""Tests for the paste-buffer operations (bucket A)."""

from __future__ import annotations

import typing as t

import pytest

from libtmux.experimental.ops import (
    DeleteBuffer,
    LoadBuffer,
    PasteBuffer,
    SaveBuffer,
    SetBuffer,
    ShowBuffer,
    operation_from_dict,
    operation_to_dict,
    result_from_dict,
    result_to_dict,
    run,
)
from libtmux.experimental.ops._types import PaneId

if t.TYPE_CHECKING:
    import pathlib

    from libtmux.experimental.ops.operation import Operation
    from libtmux.session import Session


class RenderCase(t.NamedTuple):
    """An op and the exact argv it renders."""

    test_id: str
    op: Operation[t.Any]
    expected: tuple[str, ...]


RENDER_CASES = (
    RenderCase(
        test_id="set_buffer",
        op=SetBuffer(data="hello"),
        expected=("set-buffer", "hello"),
    ),
    RenderCase(
        test_id="set_buffer_named",
        op=SetBuffer(buffer_name="b0", data="hi"),
        expected=("set-buffer", "-b", "b0", "hi"),
    ),
    RenderCase(
        test_id="delete_buffer_named",
        op=DeleteBuffer(buffer_name="b0"),
        expected=("delete-buffer", "-b", "b0"),
    ),
    RenderCase(
        test_id="delete_buffer_default",
        op=DeleteBuffer(),
        expected=("delete-buffer",),
    ),
    RenderCase(
        test_id="load_buffer",
        op=LoadBuffer(path="/tmp/x"),
        expected=("load-buffer", "/tmp/x"),
    ),
    RenderCase(
        test_id="save_buffer",
        op=SaveBuffer(path="/tmp/x"),
        expected=("save-buffer", "/tmp/x"),
    ),
    RenderCase(
        test_id="save_buffer_append_named",
        op=SaveBuffer(buffer_name="b0", path="/tmp/x", append=True),
        expected=("save-buffer", "-a", "-b", "b0", "/tmp/x"),
    ),
    RenderCase(
        test_id="paste_buffer",
        op=PasteBuffer(target=PaneId("%1")),
        expected=("paste-buffer", "-t", "%1"),
    ),
    RenderCase(
        test_id="paste_buffer_delete",
        op=PasteBuffer(target=PaneId("%1"), delete=True),
        expected=("paste-buffer", "-t", "%1", "-d"),
    ),
    RenderCase(
        test_id="show_buffer",
        op=ShowBuffer(buffer_name="b0"),
        expected=("show-buffer", "-b", "b0"),
    ),
)


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_buffer_op_render(
    test_id: str,
    op: Operation[t.Any],
    expected: tuple[str, ...],
) -> None:
    """Each buffer op renders the exact tmux argv."""
    assert op.render() == expected


@pytest.mark.parametrize(
    list(RenderCase._fields),
    RENDER_CASES,
    ids=[c.test_id for c in RENDER_CASES],
)
def test_buffer_op_round_trips(
    test_id: str,
    op: Operation[t.Any],
    expected: tuple[str, ...],
) -> None:
    """Each op and its result round-trip via dicts."""
    assert operation_from_dict(operation_to_dict(op)) == op
    result = op.build_result(returncode=0)
    assert result_from_dict(result_to_dict(result)) == result


def test_show_buffer_joins_lines() -> None:
    """show-buffer joins captured lines into the buffer text."""
    result = ShowBuffer().build_result(returncode=0, stdout=("line1", "line2"))
    assert result.text == "line1\nline2"


def test_set_show_save_delete_buffer_live(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """set-buffer/show-buffer/save-buffer/delete-buffer round-trip a buffer."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)

    run(SetBuffer(buffer_name="ops_b", data="hello world"), engine).raise_for_status()
    shown = run(ShowBuffer(buffer_name="ops_b"), engine)
    assert shown.ok
    assert shown.text == "hello world"

    out = tmp_path / "buf.txt"
    run(SaveBuffer(buffer_name="ops_b", path=str(out)), engine).raise_for_status()
    assert out.read_text() == "hello world"

    assert run(DeleteBuffer(buffer_name="ops_b"), engine).ok


def test_load_and_paste_buffer_live(
    session: Session,
    tmp_path: pathlib.Path,
) -> None:
    """load-buffer reads a file into a buffer; paste-buffer targets a pane."""
    from libtmux.experimental.engines import SubprocessEngine

    engine = SubprocessEngine.for_server(session.server)
    pane = session.active_pane
    assert pane is not None and pane.pane_id is not None

    src = tmp_path / "in.txt"
    src.write_text("pasted-content")
    run(LoadBuffer(buffer_name="ops_lb", path=str(src)), engine).raise_for_status()
    assert run(ShowBuffer(buffer_name="ops_lb"), engine).text == "pasted-content"

    assert run(
        PasteBuffer(target=PaneId(pane.pane_id), buffer_name="ops_lb"),
        engine,
    ).ok
