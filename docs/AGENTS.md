# Documentation voice

This file covers the *voice* of prose under `docs/` — how to frame a
page so a reader meets the idea before its API surface. It complements
the repository-root `AGENTS.md`, which already governs code blocks,
shell-command formatting, doctests, changelog conventions, and MyST
roles. When the two overlap, the root file wins; this one only answers
the question it leaves open: how should the prose sound?

## Who you are writing for

The default reader writes Python and drives tmux through libtmux's
object API — `Server`, `Session`, `Window`, `Pane`. They are fluent in
tmux itself — servers, sessions, windows, panes, targets, formats — and
comfortable in Python, but you cannot assume they know libtmux's
internals: the format-string query layer, `neo`, the options and hooks
machinery, or when an object goes stale and needs `refresh()`.

A second, smaller reader works *on* libtmux or against its lower
layers: format tokens, the neo query interface, custom traversal, or
contributing. Serve them too, but mark their material opt-in ("for the
rarer cases", "advanced") so the default reader knows they can stop.
Never make the common case pay a comprehension tax for the advanced one.

## Voice

- **Second person, present tense, active.** "You split the window", not
  "A pane is created". Address the reader who is doing the thing.
- **Concept before API surface.** Open by saying what the object or
  method *is* and what it does for the reader. The signature — the
  parameters, the flags — is the last detail they need, not the first.
  A page that opens with a method signature has buried the idea under
  its mechanics.
- **Say when they can stop.** Lead with the default and the
  reassurance: most readers never reach for this, the defaults work,
  the advanced parts are optional. Let a skimmer leave after one
  paragraph.
- **Grant permission, don't demand attention.** "Reach for this
  when…", "for the rarer cases" — tell readers they're in the right
  place without implying they must read on.
- **Progressive disclosure.** Order by how many readers need it: the
  common call → the one argument a few will tune → the lower-level
  primitive → querying tmux directly. Each step is for a smaller
  audience than the last.
- **Lean on the hierarchy.** The reader thinks Server → Session →
  Window → Pane; reinforce that chain when you explain containment or
  traversal. It is the mental model the whole library hangs on.
- **Name the trade-off.** If a call costs something — an extra tmux
  round-trip, a stale object needing `refresh()`, a polling wait — say
  so, and say what it buys ("a busy wait, not an event, but reliable").
  State it; don't sell it.
- **Frame by concept, not by mechanism.** Don't headline a feature by
  its tmux flag or format token in prose; that names the implementation
  surface, which is the reader's last concern. Name the concept. The
  mechanics vocabulary — a parameter table, a `#{format}` token, the
  `-t` target — belongs in a reference table or the API docs, and only
  there.

## Examples that run

Prose examples under `docs/` are doctests, and the root `AGENTS.md`
requires them to actually execute — `testpaths` includes `docs/`, so
pytest runs every one. Lead with a small, runnable example early rather
than after paragraphs of prose; libtmux is code-first. Pages under
`docs/howto/` are the exception and work the other way round; see
[How-to guides run differently](#how-to-guides-run-differently).

- Use the `doctest_namespace` fixtures instead of building a server by
  hand. `conftest.py` seeds the namespace with `server`, `session`,
  `window`, `pane`, the `Server` / `Session` / `Window` / `Pane` /
  `Client` classes, `ControlMode` and `control_mode`, `monkeypatch`,
  and `request`.
- Fence a `>>>` session as a ```` ```python ```` block, and reach for
  `# doctest: +ELLIPSIS` when output varies (ids like `@1`, `$2`,
  socket names). Use a ```` ```console ```` block for shell commands at
  a `$` prompt.
- **Every code block on a page is an independent doctest.** Blocks do
  not share a session: each one gets a fresh copy of the namespace *and*
  a fresh tmux server. A later block cannot use a `pane` an earlier
  block created — the name is simply not defined there. So **write every
  block self-contained**. The fixtures above are re-seeded for each
  block, which makes that cheap: no block needs an import or a setup
  preamble to get a `server`, a `session`, or a `pane`. Order is
  load-bearing for the reader's narrative, not for state — reorder, add,
  or drop a block as the prose demands, and keep the story coherent.
- Two of those names are not quite what they look like. `Server` is a
  `TestServer` partial, not the real class; write
  `>>> from libtmux.server import Server` when an example needs the
  class itself. And the fixture server is created with a socket *name*,
  so `server.socket_path` is `None` — an example that needs the path
  must ask tmux for it with `display-message -p '#{socket_path}'`.

## How-to guides run differently

Everything above describes prose pages. `docs/howto/` inverts it: those
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

## What stays precise

Warm the framing, never the facts. Resolution-order lists, value
tables, exact error strings, format tokens, and class or method
cross-references carry meaning in their exact form — leave them alone.
The friendly voice belongs in the sentences *around* a precise block,
introducing it, not inside it paraphrasing it into vagueness.

## Cross-references

Point the advanced reader at the deep-dive rather than inlining it, and
put the link where their interest peaks — on the phrase that made them
curious ("query tmux directly", "write your own traversal") — not as a
standalone footnote the eye skips. Use the MyST roles listed in the
root `AGENTS.md` (`{meth}`, `{class}`, `{func}`, `{attr}`, `{exc}`,
`{ref}`, `{doc}`, `{term}`). A `{ref}` must match its target's anchor
exactly — anchors mix underscore and hyphen forms across pages
(`context_managers`, `pane-interaction`). `just build-docs` catches a
broken cross-reference; the doctests do not — so build the docs before
you commit.

Link the first prose mention of any symbol that has a useful destination on
that page. This includes Python objects, libtmux APIs, tmux concepts with
glossary entries, topic/configuration pages, and external tools or projects.
Use the most specific target available: `{class}`, `{meth}`, `{func}`, `{mod}`,
`{exc}`, or `{attr}` for API objects; `{ref}`, `{doc}`, or `{term}` for
documentation pages, section anchors, and glossary entries; and a Markdown link
or reference link for external projects. After the first linked mention on a
page, later mentions can stay plain unless the distance or context makes
another link useful.

Do not rely on a later reference section to satisfy the first-mention rule. If
the first occurrence would be a heading, grid-card teaser, or introductory
sentence, link that occurrence or retitle the heading so the first prose mention
can carry the link. Leave command examples, code blocks, and literal
configuration values as code; link the surrounding prose instead.

## A page that does this

`docs/topics/pane_interaction.md` is the worked example: a concept-first
intro that says what a `Pane` *is* and which two methods (`send_keys`,
`capture_pane`) cover most uses before any signature, an explicit "you
can stop after the first two sections" reassurance, sections ordered by
shrinking audience, honest trade-offs (polling is a busy wait; a resize
is a request, not a guarantee), methods named by what they do with
`{meth}` cross-references, and precise capture-flag and format tables
left exact. Read it before reshaping another page.

## Before you commit

- Does the page open with what the feature *is*, or with how to call it?
- Can a reader who needs only the common case stop after the first
  paragraph?
- Is anything framed by its tmux flag or format token that should be
  named by concept instead?
- Are the advanced and lower-level parts clearly marked opt-in?
- Do the doctests run, and did you leave every code block, table, error
  string, and cross-reference exact?
- Did `just build-docs` stay clean — no new warning, no broken
  cross-reference?
