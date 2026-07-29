# How-to guides

Documentation follows [WRITING.md](../.github/WRITING.md).
The conventions below apply to executable pages under `docs/howto/`.

## How-to guides run differently

`docs/howto/` differs from the doctested prose pages: those
pages carry code a reader copies into a file of their own, so they use
plain ```` ```python ```` fences with no `>>>`, and **the page carries no
test scaffolding at all** — no assertions, no markers, no hidden blocks.
The visible block is the whole page.

- **Blocks share one namespace, in document order.** Block 2 sees what
  block 1 bound, because that is what a reader pasting in sequence gets.
  This is the opposite of the rule above; write the page as one
  continuous script broken into steps, not as independent snippets.
- **Hidden checks live in a sidecar**, `tests/docs/howto/<slug>.py`,
  where `<slug>` is the page's filename with hyphens as underscores. It
  defines `check_N(ctx)` for each of the page's N blocks, and may define
  `setup(ctx)` and `teardown(ctx)`. A missing sidecar, a missing
  `check_N`, or a `check_N` with no block is a hard failure.
- **Isolation is the runner's job.** Each page gets a private
  `TMUX_TMPDIR` and `HOME` before its sidecar is called, and every socket
  under that directory is killed afterwards. A sidecar never asks for it.
- The page's `ctx` carries `namespace` (what the blocks bound), `output`
  (what each block printed), `monkeypatch`, and `tmp_path`.
  `ctx.run_block(n, namespace={})` re-runs a block in isolation, which is
  how a check exercises the branch the reader's example only shows once.

What the visible code must do, because a reader will run it verbatim:

- **Name the socket** on any page that creates or destroys anything —
  `Server(socket_name="libtmux-howto")` — so the example cannot reach the
  tmux the reader already has open. Read-only pages use a plain `Server()`
  on purpose: the question is about the reader's real server.
- **Pass `kill_session=True`** to `new_session`, so pasting twice works.
- **Poll against a deadline, never sleep a fixed amount**, and **compare
  whole captured lines** — `capture_pane` returns the command tmux echoed
  onto the pane, so a substring test is true before the shell has run.
- **Never start a line with `# `** at column zero. sphinx-copybutton
  reads it as a prompt and copies only such lines. Put the remark in the
  prose, where it belongs.
- Colon fences are for directives only. `:::python` renders a
  copy-pasteable block that nothing executes, and is rejected.

Adding a page: write `docs/howto/<slug>.md` opening with `(howto-<slug>)=`,
add it to the grid and toctree in `docs/howto/index.md`, and write
`tests/docs/howto/<slug>.py`. Every one of those four is enforced by a
test, so getting it wrong is loud rather than silent.

