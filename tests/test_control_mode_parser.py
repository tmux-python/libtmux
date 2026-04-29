"""Unit tests for the ``tmux -CC`` control-mode wire parser.

These tests are pure: no live tmux server required. Inputs are
crafted to mirror real wire output captured against tmux 3.6.
"""

from __future__ import annotations

import pytest

from libtmux.engines.control_mode.parser import (
    Block,
    ClientDetachedNotification,
    ClientSessionChangedNotification,
    ContinueNotification,
    ControlParser,
    ExitNotification,
    ExtendedOutputNotification,
    Notification,
    OutputNotification,
    PaneModeChangedNotification,
    PasteBufferChangedNotification,
    PasteBufferDeletedNotification,
    PauseNotification,
    SessionChangedNotification,
    SessionRenamedNotification,
    SessionsChangedNotification,
    SessionWindowChangedNotification,
    SubscriptionChangedNotification,
    UnknownNotification,
    UnlinkedWindowAddNotification,
    UnlinkedWindowCloseNotification,
    UnlinkedWindowRenamedNotification,
    WindowAddNotification,
    WindowCloseNotification,
    WindowPaneChangedNotification,
    WindowRenamedNotification,
    unescape_octal,
)

# ---------------------------------------------------------------- octal --


def test_unescape_octal_passthrough_when_no_backslash() -> None:
    """Lines without escapes return the same bytes object semantics."""
    assert unescape_octal(b"hello world") == b"hello world"


def test_unescape_octal_decodes_newline_and_backslash() -> None:
    r"""``\012`` decodes to LF; ``\134`` decodes to a backslash."""
    assert unescape_octal(rb"line one\012line two") == b"line one\nline two"
    assert unescape_octal(rb"a\134b") == b"a\\b"


def test_unescape_octal_decodes_full_control_range() -> None:
    """Every byte 0x00-0x1F is encoded by tmux and round-trips through us."""
    encoded = b"".join(rb"\%03o" % i for i in range(0x20))
    encoded = encoded.replace(b"%03o", b"")  # raw concatenation marker
    encoded = b"".join(b"\\%03o" % i for i in range(0x20))
    decoded = unescape_octal(encoded)
    assert decoded == bytes(range(0x20))


def test_unescape_octal_keeps_high_bytes_verbatim() -> None:
    """Bytes >= 0x20 except backslash are passed through unmodified."""
    raw = b"caf\xc3\xa9 \x7f \xff"
    assert unescape_octal(raw) == raw


def test_unescape_octal_partial_escape_at_eof() -> None:
    r"""A trailing ``\`` without three octal digits is kept literal."""
    assert unescape_octal(rb"abc\1") == rb"abc\1"
    assert unescape_octal(rb"abc\\") == rb"abc\\"
    assert unescape_octal(rb"abc\189") == rb"abc\189"


# ------------------------------------------------------------- block --


def test_block_open_close_emits_one_event() -> None:
    """A ``%begin``/``%end`` pair yields one Block with the body lines."""
    parser = ControlParser()
    parser.feed(
        b"%begin 1700000000 7 1\nhello\nworld\n%end 1700000000 7 1\n",
    )
    events = parser.events()
    assert len(events) == 1
    block = events[0]
    assert isinstance(block, Block)
    assert block.number == 7
    assert block.timestamp == 1700000000
    assert block.flags == 1
    assert block.is_error is False
    assert block.body == (b"hello", b"world")
    assert block.end_timestamp == 1700000000
    assert block.end_flags == 1
    assert parser.unknown_count == 0


def test_block_error_close_marks_is_error() -> None:
    """Closing with ``%error`` sets ``is_error`` and keeps body bytes."""
    parser = ControlParser()
    parser.feed(
        b"%begin 1700000000 12 1\nunknown command: foobar\n%error 1700000000 12 1\n",
    )
    [block] = parser.events()
    assert isinstance(block, Block)
    assert block.is_error is True
    assert block.body == (b"unknown command: foobar",)


def test_block_empty_body() -> None:
    """A command with no output yields a Block with an empty body tuple."""
    parser = ControlParser()
    parser.feed(b"%begin 1 1 1\n%end 1 1 1\n")
    [block] = parser.events()
    assert isinstance(block, Block)
    assert block.body == ()


def test_block_body_can_start_with_percent() -> None:
    """Output that starts with ``%`` but is not a recognised guard stays as body."""
    parser = ControlParser()
    parser.feed(
        b"%begin 1 1 1\n%not-a-real-notification\n%end 1 1 1\n",
    )
    [block] = parser.events()
    assert isinstance(block, Block)
    assert block.body == (b"%not-a-real-notification",)
    assert parser.unknown_count == 0


def test_notifications_interleaved_inside_block() -> None:
    """``%output`` inside a block emits a notification, not body bytes."""
    parser = ControlParser()
    parser.feed(
        b"%begin 1 8 1\n%output %1 hi\\012\nline one\n%end 1 8 1\n",
    )
    events = parser.events()
    assert len(events) == 2
    notification, block = events
    assert isinstance(notification, OutputNotification)
    assert notification.pane_id == "%1"
    assert notification.data == b"hi\n"
    assert isinstance(block, Block)
    assert block.body == (b"line one",)


def test_partial_feed_buffers_until_newline() -> None:
    """Bytes split across feed() calls reassemble correctly."""
    parser = ControlParser()
    parser.feed(b"%begi")
    parser.feed(b"n 1 1 1\nhe")
    parser.feed(b"llo\n%end ")
    assert parser.events() == []
    parser.feed(b"1 1 1\n")
    [block] = parser.events()
    assert isinstance(block, Block)
    assert block.body == (b"hello",)


def test_events_drain_after_call() -> None:
    """Calling events() twice does not return the same events again."""
    parser = ControlParser()
    parser.feed(b"%begin 1 1 1\n%end 1 1 1\n")
    first = parser.events()
    second = parser.events()
    assert len(first) == 1
    assert second == []


def test_close_guard_with_no_open_block_is_unknown() -> None:
    """A stray ``%end`` without a matching ``%begin`` increments unknown count."""
    parser = ControlParser()
    parser.feed(b"%end 1 1 1\n")
    assert parser.events() == []
    assert parser.unknown_count == 1


def test_malformed_begin_is_unknown() -> None:
    """A ``%begin`` without the three required fields is rejected."""
    parser = ControlParser()
    parser.feed(b"%begin oops\n%end 1 1 1\n")
    events = parser.events()
    assert events == []
    assert parser.unknown_count == 2  # malformed %begin + orphan %end


def test_feed_eof_drops_partial_line() -> None:
    """Truncated trailing bytes are discarded and counted as unknown."""
    parser = ControlParser()
    parser.feed(b"%begin 1 1 1\nhello")
    parser.feed_eof()
    assert parser.events() == []
    assert parser.unknown_count == 1
    assert parser.in_block is True


# --------------------------------------------------------- notifications --


@pytest.mark.parametrize(
    ("wire", "expected_type", "field_checks"),
    [
        (
            b"%output %2 abc\n",
            OutputNotification,
            {"pane_id": "%2", "data": b"abc"},
        ),
        (
            b"%output %1 caf\xc3\xa9\\012\n",
            OutputNotification,
            {"pane_id": "%1", "data": b"caf\xc3\xa9\n"},
        ),
        (
            b"%extended-output %1 1234567 : hi\n",
            ExtendedOutputNotification,
            {"pane_id": "%1", "age_us": 1234567, "data": b"hi"},
        ),
        (
            b"%pause %3\n",
            PauseNotification,
            {"pane_id": "%3"},
        ),
        (
            b"%continue %3\n",
            ContinueNotification,
            {"pane_id": "%3"},
        ),
        (
            b"%session-changed $1 work\n",
            SessionChangedNotification,
            {"session_id": "$1", "name": "work"},
        ),
        (
            b"%client-session-changed alice $2 dev\n",
            ClientSessionChangedNotification,
            {"client": "alice", "session_id": "$2", "name": "dev"},
        ),
        (
            b"%session-renamed $1 newname\n",
            SessionRenamedNotification,
            {"session_id": "$1", "name": "newname"},
        ),
        (
            b"%sessions-changed\n",
            SessionsChangedNotification,
            {},
        ),
        (
            b"%session-window-changed $1 @5\n",
            SessionWindowChangedNotification,
            {"session_id": "$1", "window_id": "@5"},
        ),
        (
            b"%window-add @9\n",
            WindowAddNotification,
            {"window_id": "@9"},
        ),
        (
            b"%window-close @9\n",
            WindowCloseNotification,
            {"window_id": "@9"},
        ),
        (
            b"%window-renamed @9 build\n",
            WindowRenamedNotification,
            {"window_id": "@9", "name": "build"},
        ),
        (
            b"%window-pane-changed @9 %12\n",
            WindowPaneChangedNotification,
            {"window_id": "@9", "pane_id": "%12"},
        ),
        (
            b"%pane-mode-changed %12\n",
            PaneModeChangedNotification,
            {"pane_id": "%12"},
        ),
        (
            b"%unlinked-window-add @20\n",
            UnlinkedWindowAddNotification,
            {"window_id": "@20"},
        ),
        (
            b"%unlinked-window-close @20\n",
            UnlinkedWindowCloseNotification,
            {"window_id": "@20"},
        ),
        (
            b"%unlinked-window-renamed @20 misc\n",
            UnlinkedWindowRenamedNotification,
            {"window_id": "@20", "name": "misc"},
        ),
        (
            b"%paste-buffer-changed buffer0\n",
            PasteBufferChangedNotification,
            {"name": "buffer0"},
        ),
        (
            b"%paste-buffer-deleted buffer0\n",
            PasteBufferDeletedNotification,
            {"name": "buffer0"},
        ),
        (
            b"%client-detached alice\n",
            ClientDetachedNotification,
            {"client": "alice"},
        ),
        (
            b"%exit\n",
            ExitNotification,
            {"reason": None},
        ),
        (
            b"%exit server exited\n",
            ExitNotification,
            {"reason": "server exited"},
        ),
    ],
)
def test_notification_parsing(
    wire: bytes,
    expected_type: type[Notification],
    field_checks: dict[str, object],
) -> None:
    """Each notification line decodes into its specific dataclass."""
    parser = ControlParser()
    parser.feed(wire)
    [event] = parser.events()
    assert isinstance(event, expected_type)
    assert event.raw == wire.rstrip(b"\n")
    for field, expected in field_checks.items():
        assert getattr(event, field) == expected
    assert parser.unknown_count == 0


@pytest.mark.parametrize(
    ("wire", "expected"),
    [
        (
            b"%subscription-changed status-left $1 - - - : my session\n",
            {
                "name": "status-left",
                "session_id": "$1",
                "window_id": None,
                "window_index": None,
                "pane_id": None,
                "value": "my session",
            },
        ),
        (
            b"%subscription-changed pane-size $1 @5 0 %1 : 80x24\n",
            {
                "name": "pane-size",
                "session_id": "$1",
                "window_id": "@5",
                "window_index": 0,
                "pane_id": "%1",
                "value": "80x24",
            },
        ),
        (
            b"%subscription-changed value-with-spaces $1 - - - : a : b : c\n",
            {
                "name": "value-with-spaces",
                "session_id": "$1",
                "window_id": None,
                "window_index": None,
                "pane_id": None,
                "value": "a : b : c",
            },
        ),
    ],
)
def test_subscription_changed_targets(
    wire: bytes,
    expected: dict[str, object],
) -> None:
    """``%subscription-changed`` parses every target shape and preserves values."""
    parser = ControlParser()
    parser.feed(wire)
    [event] = parser.events()
    assert isinstance(event, SubscriptionChangedNotification)
    for field, expected_value in expected.items():
        assert getattr(event, field) == expected_value


def test_unknown_notification_emits_dataclass_and_increments_counter() -> None:
    """Unrecognised ``%``-prefixed lines surface as :class:`UnknownNotification`."""
    parser = ControlParser()
    parser.feed(b"%future-event some payload\n")
    [event] = parser.events()
    assert isinstance(event, UnknownNotification)
    assert event.raw == b"%future-event some payload"
    assert parser.unknown_count == 1


# --------------------------------------------------------------- replay --


def test_replay_realistic_session() -> None:
    """A captured session replays through the parser without any unknowns."""
    wire = (
        b"%begin 1700000000 1 1\n"
        b"%end 1700000000 1 1\n"
        b"%output %1 \\033[31mred\\033[0m\n"
        b"%session-changed $1 work\n"
        b"%begin 1700000001 2 1\n"
        b"line a\n"
        b"line b\n"
        b"%end 1700000001 2 1\n"
        b"%subscription-changed pane-pwd $1 @1 0 %1 : /home/user\n"
        b"%pause %1\n"
        b"%continue %1\n"
        b"%begin 1700000002 3 1\n"
        b"unknown option\n"
        b"%error 1700000002 3 1\n"
    )
    parser = ControlParser()
    parser.feed(wire)
    events = parser.events()

    assert parser.unknown_count == 0
    assert sum(isinstance(e, Block) for e in events) == 3
    assert sum(isinstance(e, Notification) for e in events) == 5
    blocks = [e for e in events if isinstance(e, Block)]
    assert blocks[0].body == ()
    assert blocks[1].body == (b"line a", b"line b")
    assert blocks[2].is_error is True
    assert blocks[2].body == (b"unknown option",)
