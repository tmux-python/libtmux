"""Retrying screen assertions for tests that drive a terminal app."""

from __future__ import annotations

import difflib
import typing as t

from libtmux.test.constants import RETRY_INTERVAL_SECONDS, RETRY_TIMEOUT_SECONDS
from libtmux.test.retry import retry_until

if t.TYPE_CHECKING:
    from libtmux.pane import Pane


def _lines(text: str | t.Sequence[str]) -> list[str]:
    """Split ``text`` into lines, dropping trailing blank lines."""
    lines = text.split("\n") if isinstance(text, str) else list(text)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def screen_diff(expected: str | t.Sequence[str], actual: str | t.Sequence[str]) -> str:
    r"""Return a line diff of two screens, with every line shown.

    Lines only in ``expected`` start with ``-``, lines only in ``actual`` with
    ``+``, and shared lines with two spaces.

    Examples
    --------
    >>> print(screen_diff("a\nb", "a\nc"))
    --- expected
    +++ actual
      a
    - b
    + c
    """
    want, got = _lines(expected), _lines(actual)
    diff = difflib.unified_diff(
        want,
        got,
        "expected",
        "actual",
        n=max(len(want), len(got)),
        lineterm="",
    )
    return "\n".join(
        line if line.startswith(("---", "+++")) else f"{line[:1]} {line[1:]}"
        for line in diff
        if not line.startswith("@@")
    )


class ScreenMatcher:
    r"""A pane's screen whose ``==``, ``!=``, and ``in`` retry until they hold.

    Each comparison captures the pane again and repeats until it holds or
    ``timeout`` seconds pass, so a test states the screen it expects without a
    ``sleep``. A comparison that never holds returns ``False``; under pytest
    the assertion failure shows a line diff of the last capture.

    Build one with :func:`eventually`.

    Examples
    --------
    >>> pane = session.new_window(
    ...     window_shell="printf 'hello\nworld\n'; cat",
    ... ).active_pane
    >>> assert "world" in eventually(pane)
    >>> assert eventually(pane, row=0) == "hello"
    >>> assert eventually(pane, row=0) != "no such line"
    """

    def __init__(
        self,
        pane: Pane,
        *,
        row: int | None = None,
        timeout: float | None = None,
        interval: float | None = None,
    ) -> None:
        self.pane = pane
        self.row = row
        self.timeout = RETRY_TIMEOUT_SECONDS if timeout is None else timeout
        self.interval = RETRY_INTERVAL_SECONDS if interval is None else interval
        self._value: str | None = None

    @property
    def value(self) -> str:
        """The last captured screen, captured now if there is none yet."""
        return self.capture() if self._value is None else self._value

    def capture(self) -> str:
        """Capture the screen, or the one row, and remember it as ``value``."""
        lines = _lines(self.pane.capture_pane())
        if self.row is None:
            text = "\n".join(lines)
        else:
            text = lines[self.row] if -len(lines) <= self.row < len(lines) else ""
        self._value = text
        return text

    def _eventually(self, check: t.Callable[[str], bool]) -> bool:
        return retry_until(
            lambda: check(self.capture()),
            self.timeout,
            interval=self.interval,
            raises=False,
        )

    def __eq__(self, other: object) -> bool:
        """Return whether the screen eventually equals ``other``."""
        if not isinstance(other, str):
            return NotImplemented
        want = "\n".join(_lines(other))
        return self._eventually(lambda text: text == want)

    def __ne__(self, other: object) -> bool:
        """Return whether the screen eventually differs from ``other``."""
        if not isinstance(other, str):
            return NotImplemented
        want = "\n".join(_lines(other))
        return self._eventually(lambda text: text != want)

    def __contains__(self, item: object) -> bool:
        """Return whether ``item`` eventually appears on the screen."""
        if not isinstance(item, str):
            return False
        return self._eventually(lambda text: item in text)

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        """Return the last captured screen."""
        return self.value


def eventually(
    pane: Pane,
    *,
    row: int | None = None,
    timeout: float | None = None,
    interval: float | None = None,
) -> ScreenMatcher:
    r"""Return a :class:`ScreenMatcher` for ``pane``.

    Parameters
    ----------
    pane : Pane
        Pane to capture.
    row : int, optional
        Compare one captured line, counted from 0, instead of the whole
        screen. An absent row is ``""``.
    timeout : float, optional
        Seconds to keep retrying each comparison. ``0`` compares once.
        Defaults to ``RETRY_TIMEOUT_SECONDS``.
    interval : float, optional
        Seconds between captures. Defaults to ``RETRY_INTERVAL_SECONDS``.

    Examples
    --------
    >>> pane = session.new_window(
    ...     window_shell="printf 'hello\nworld\n'; cat",
    ... ).active_pane
    >>> assert "hello" in eventually(pane)
    """
    return ScreenMatcher(pane, row=row, timeout=timeout, interval=interval)


def assert_screen(
    pane: Pane,
    expected: str | t.Sequence[str],
    *,
    row: int | None = None,
    contains: bool = False,
    timeout: float | None = None,
    interval: float | None = None,
) -> None:
    r"""Assert that ``pane``'s screen comes to match ``expected``.

    Captures the pane, compares, and repeats until the screen matches or
    ``timeout`` seconds pass. Raises :exc:`AssertionError` carrying a line
    diff of the last capture, so the caller sees what the screen held instead
    of a bare timeout. Trailing blank lines are ignored on both sides. Works
    outside pytest.

    Parameters
    ----------
    pane : Pane
        Pane to capture.
    expected : str or sequence of str
        Expected screen, or one line when ``row`` is given. With
        ``contains=True`` it is a substring, which may span lines.
    row : int, optional
        Compare one captured line, counted from 0, instead of the whole
        screen. An absent row is ``""``.
    contains : bool
        Match when ``expected`` appears anywhere in the screen (or row)
        instead of equalling it.
    timeout : float, optional
        Seconds to keep retrying. ``0`` captures once. Defaults to
        ``RETRY_TIMEOUT_SECONDS``.
    interval : float, optional
        Seconds between captures. Defaults to ``RETRY_INTERVAL_SECONDS``.

    Examples
    --------
    >>> pane = session.new_window(
    ...     window_shell="printf 'hello\nworld\n'; cat",
    ... ).active_pane
    >>> assert_screen(pane, "hello\nworld")
    >>> assert_screen(pane, "wor", row=1, contains=True)

    A screen that never matches raises with the diff:

    >>> assert_screen(pane, "hello\nthere", timeout=0)
    Traceback (most recent call last):
    ...
    AssertionError: the screen did not equal expected within 0s
    --- expected
    +++ actual
      hello
    - there
    + world
    """
    matcher = ScreenMatcher(pane, row=row, timeout=timeout, interval=interval)
    want = "\n".join(_lines(expected))
    if contains:
        ok = matcher._eventually(lambda text: want in text)
    else:
        ok = matcher._eventually(lambda text: text == want)
    if ok:
        return
    what = "the screen" if row is None else f"row {row}"
    verb = "contain" if contains else "equal"
    if contains:
        body = f"expected text:\n{want}\n\nactual:\n{matcher.value}"
    else:
        body = screen_diff(want, matcher.value)
    msg = f"{what} did not {verb} expected within {matcher.timeout:g}s\n{body}"
    raise AssertionError(msg)
