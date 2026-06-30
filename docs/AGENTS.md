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
than after paragraphs of prose; libtmux is code-first.

- Use the `doctest_namespace` fixtures — `server`, `session`, `window`,
  `pane` (and `Server` / `Session` / `Window` / `Pane` / `Client`) —
  instead of building a server by hand.
- Fence a `>>>` session as a ```` ```python ```` block, and reach for
  `# doctest: +ELLIPSIS` when output varies (ids like `@1`, `$2`,
  socket names). Use a ```` ```console ```` block for shell commands at
  a `$` prompt.
- The code blocks on a page share one doctest session, so a later
  block can use a `pane` an earlier block created. That makes their
  **order load-bearing**: never reorder, add, or drop a code block when
  you reshape the prose around it.

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
