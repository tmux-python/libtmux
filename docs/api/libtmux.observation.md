# Retained pane observations

{meth}`PaneObservation.capture() <libtmux.PaneObservation.capture>` keeps
decoded pane text and its capture command in a frozen value. Read it after
redraw or pane removal without querying tmux again. The pane and server remain
borrowed.

```python
>>> from libtmux import PaneObservation
>>> observed = PaneObservation.capture(pane)
>>> observed.pane_id == pane.pane_id
True
>>> isinstance(observed.lines, tuple)
True
>>> observed.text == "\n".join(observed.lines)
True
>>> observed.target_lifetime_verified is None
True
```

Use `start`, `end`, and `join_wrapped` to select text with tmux's ordinary
capture semantics. The result retains the selection, actual command argv, and
the controller's monotonic capture interval in nanoseconds. Text uses the
existing command decoder and trailing-empty-line policy. It contains no raw
byte or terminal-column positions.

`max_text_codepoints` bounds admitted decoded text, including LF between lines.
It counts Python Unicode code points. Oversized text raises `ValueError`;
tmux failures raise instead of becoming successful empty observations. The
limit applies after the existing transport returns, so it does not bound
transport memory. The call keeps the selected backend's blocking behavior.

The legacy pane ID cannot prove which daemon or pane lifetime supplied a
capture after replacement; `target_lifetime_verified` remains unknown. The
interval describes one sampled command, without an atomic metadata/content
checkpoint. Retained text remains readable after observer or server loss while
you retain the value. Process exit loses the in-memory value. No serializer or
persistent record is supplied.

A later capture can recover then-visible text, not omitted output, erased
history, or hidden terminal state. Visible text and echoed commands do not
prove application completion. A cooperating producer can signal an
application-defined milestone; the signal proves only that milestone.

```{eval-rst}
.. autoclass:: libtmux.PaneObservation
    :members:
    :member-order: bysource
```
