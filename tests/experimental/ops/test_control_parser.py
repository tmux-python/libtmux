"""Pure (no-tmux) tests for the control-mode block parser."""

from __future__ import annotations

from libtmux.experimental.engines import ControlModeParser


def test_parses_success_block() -> None:
    """A ``%begin``/``%end`` pair yields one non-error block with its body."""
    parser = ControlModeParser()
    parser.feed(b"%begin 1 1 1\nhello\nworld\n%end 1 1 1\n")
    blocks = parser.blocks()
    assert len(blocks) == 1
    assert not blocks[0].is_error
    assert blocks[0].body == (b"hello", b"world")


def test_parses_error_block() -> None:
    """A ``%error`` close marks the block as an error."""
    parser = ControlModeParser()
    parser.feed(b"%begin 2 5 1\ncan't find pane\n%error 2 5 1\n")
    block = parser.blocks()[0]
    assert block.is_error
    assert block.body == (b"can't find pane",)


def test_handles_split_chunks() -> None:
    """Bytes split mid-line across feeds still parse into one block."""
    parser = ControlModeParser()
    parser.feed(b"%begin 1 1 1\nhel")
    parser.feed(b"lo\n%end 1 1 1\n")
    assert parser.blocks()[0].body == (b"hello",)


def test_blocks_drains() -> None:
    """``blocks`` returns parsed blocks once, then is empty."""
    parser = ControlModeParser()
    parser.feed(b"%begin 1 1 1\nx\n%end 1 1 1\n")
    assert len(parser.blocks()) == 1
    assert parser.blocks() == []


def test_ignores_noise_outside_blocks() -> None:
    """Notification lines outside a block are not command blocks."""
    parser = ControlModeParser()
    parser.feed(b"%output %1 hi\n%begin 1 1 1\nok\n%end 1 1 1\n")
    blocks = parser.blocks()
    assert len(blocks) == 1
    assert blocks[0].body == (b"ok",)


def test_surfaces_notifications() -> None:
    """Bare ``%`` lines outside blocks are surfaced as notifications."""
    parser = ControlModeParser()
    parser.feed(b"%window-add @3\n%begin 1 1 1\nok\n%end 1 1 1\n%output %1 hi\n")
    assert parser.notifications() == [b"%window-add @3", b"%output %1 hi"]
    # block lines are not double-counted as notifications
    assert parser.blocks()[0].body == (b"ok",)


def test_notifications_drain() -> None:
    """``notifications`` returns each notification once, then is empty."""
    parser = ControlModeParser()
    parser.feed(b"%window-close @3\n")
    assert parser.notifications() == [b"%window-close @3"]
    assert parser.notifications() == []
