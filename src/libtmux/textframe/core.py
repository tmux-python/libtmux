"""TextFrame - ASCII terminal frame simulator.

This module provides a fixed-size ASCII frame for visualizing terminal content
with overflow detection and diagnostic rendering.
"""

from __future__ import annotations

import typing as t
from dataclasses import dataclass, field

if t.TYPE_CHECKING:
    from collections.abc import Sequence

OverflowBehavior = t.Literal["error", "truncate"]


class ContentOverflowError(ValueError):
    """Raised when content does not fit into the configured frame dimensions.

    Attributes
    ----------
    overflow_visual : str
        A diagnostic ASCII visualization showing the content and a mask
        of the valid/invalid areas.
    """

    def __init__(self, message: str, overflow_visual: str) -> None:
        super().__init__(message)
        self.overflow_visual = overflow_visual


@dataclass(slots=True)
class TextFrame:
    """A fixed-size ASCII terminal frame simulator.

    Attributes
    ----------
    content_width : int
        Width of the inner content area.
    content_height : int
        Height of the inner content area.
    overflow_behavior : OverflowBehavior
        How to handle content that exceeds frame dimensions.
        - "error": Raise ContentOverflowError with visual diagnostic.
        - "truncate": Silently clip content to fit.
    fill_char : str
        Character to pad empty space. Defaults to space.
    content : list[str]
        The current content lines.

    Examples
    --------
    >>> frame = TextFrame(content_width=10, content_height=2)
    >>> frame.set_content(["hello", "world"])
    >>> print(frame.render())
    +----------+
    |hello     |
    |world     |
    +----------+
    """

    content_width: int
    content_height: int
    overflow_behavior: OverflowBehavior = "error"
    fill_char: str = " "
    content: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate frame dimensions and fill character.

        Raises
        ------
        ValueError
            If dimensions are not positive or fill_char is not a single character.
        """
        if self.content_width <= 0:
            msg = "content_width must be positive"
            raise ValueError(msg)
        if self.content_height <= 0:
            msg = "content_height must be positive"
            raise ValueError(msg)
        if len(self.fill_char) != 1:
            msg = "fill_char must be a single character"
            raise ValueError(msg)

    def set_content(self, lines: Sequence[str]) -> None:
        """Set content, applying validation or truncation based on overflow_behavior.

        Parameters
        ----------
        lines : Sequence[str]
            Lines of content to set.

        Raises
        ------
        ContentOverflowError
            If content exceeds frame dimensions and overflow_behavior is "error".
        """
        input_lines = list(lines)

        # Calculate dimensions
        max_w = max((len(line) for line in input_lines), default=0)
        max_h = len(input_lines)

        is_overflow = max_w > self.content_width or max_h > self.content_height

        if is_overflow:
            if self.overflow_behavior == "error":
                visual = self._render_overflow(input_lines, max_w, max_h)
                msg = (
                    f"Content ({max_w}x{max_h}) exceeds frame "
                    f"({self.content_width}x{self.content_height})"
                )
                raise ContentOverflowError(msg, overflow_visual=visual)
            # Truncate mode: clip to frame dimensions
            input_lines = [
                line[: self.content_width]
                for line in input_lines[: self.content_height]
            ]

        self.content = input_lines

    def render(self) -> str:
        """Render the frame as ASCII art.

        Returns
        -------
        str
            The rendered frame with borders.
        """
        return self._draw_frame(self.content, self.content_width, self.content_height)

    def _render_overflow(self, lines: list[str], max_w: int, max_h: int) -> str:
        """Render the diagnostic overflow view (Reality vs Mask).

        Parameters
        ----------
        lines : list[str]
            The overflow content lines.
        max_w : int
            Maximum width of content.
        max_h : int
            Maximum height of content.

        Returns
        -------
        str
            A visualization showing content frame and valid/invalid mask.
        """
        display_w = max(self.content_width, max_w)
        display_h = max(self.content_height, max_h)

        # 1. Reality Frame - shows actual content
        reality = self._draw_frame(lines, display_w, display_h)

        # 2. Mask Frame - shows valid vs invalid areas
        mask_lines = []
        for r in range(display_h):
            row = []
            for c in range(display_w):
                is_valid = r < self.content_height and c < self.content_width
                row.append(" " if is_valid else ".")
            mask_lines.append("".join(row))

        mask = self._draw_frame(mask_lines, display_w, display_h)
        return f"{reality}\n{mask}"

    def _draw_frame(self, lines: list[str], w: int, h: int) -> str:
        """Draw a bordered frame around content.

        Parameters
        ----------
        lines : list[str]
            Content lines to frame.
        w : int
            Frame width (excluding borders).
        h : int
            Frame height (excluding borders).

        Returns
        -------
        str
            Bordered ASCII frame.
        """
        border = f"+{'-' * w}+"
        body = []
        for r in range(h):
            line = lines[r] if r < len(lines) else ""
            body.append(f"|{line.ljust(w, self.fill_char)}|")
        return "\n".join([border, *body, border])
