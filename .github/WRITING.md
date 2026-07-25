# Writing

How this project writes prose, for humans and agents alike. It governs
`README.md`, `CHANGES`, release notes, commit messages, docstrings,
source comments, and the prose under `docs/` — every surface a reader
reaches.

For environment setup, the gates, and the pull request workflow, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Voice

Three surfaces, one voice. A docstring says what a caller may rely on; a
`CHANGES` entry says what changed; prose says what happens. All three are
present tense, lead with the thing being described, and stop. Why it was
built that way belongs in the commit message, which is timestamped and
attached to the diff.

The most useful editing operation is deleting the introductory sentence.

Lead with verbs and name concrete things. Put identifiers in backticks.
Prefer short declarative sentences, one operational fact each. Do not
explain Python to Python developers; do explain this project's semantics.

Type annotations describe shape. Documentation describes meaning. A
sentence that restates a signature has said nothing.

Use MUST, SHOULD, and MAY only where the normative sense is meant. Say
what actually happens rather than that something is "supported".

| Instead of                       | Prefer                            |
| --------------------------------- | ---------------------------------- |
| "We added…"                      | "`Pane.send_keys` now accepts…"   |
| "New and improved"               | "`Server.sessions` now…"          |
| "powerful", "seamless"           | state the capability              |
| "easily", "simply", "just"       | omit                              |
| "simple", "obvious", "intuitive" | omit                              |
| "robust"                         | name the failure that is handled  |
| "comprehensive"                  | name what is covered              |
| "production-ready"               | state the guarantee               |
| "optimized", "blazingly fast"    | give the magnitude                |
| "various fixes"                  | name the components               |
| "under the hood"                 | omit unless observable            |
| "please note that", "note that"  | state the fact                    |
| "leverage", "utilize"            | "use"                             |
| "delve into"                     | "read", or omit                   |
| "best practices"                 | name the practice                 |
| "in order to"                    | "to"                              |

## Who you are writing for

The default reader writes Python and drives tmux through libtmux's object
API — `Server`, `Session`, `Window`, `Pane`. They are fluent in tmux
itself — servers, sessions, windows, panes, targets, formats — and
comfortable in Python, but you cannot assume they know libtmux's
internals: the format-string query layer, `neo`, the options and hooks
machinery, or when an object goes stale and needs `refresh()`.

A second, smaller reader works *on* libtmux or against its lower layers:
format tokens, the neo query interface, custom traversal, or
contributing. Serve them too, but mark their material opt-in ("for the
rarer cases", "advanced") so the default reader knows they can stop.
Never make the common case pay a comprehension tax for the advanced one.

Rules that follow:

- **Second person, present tense, active.** "You split the window", not
  "A pane is created". Address the reader who is doing the thing.
- **Concept before API surface.** Open by saying what the object or
  method *is* and what it does for the reader. The signature — the
  parameters, the flags — is the last detail they need, not the first. A
  page that opens with a method signature has buried the idea under its
  mechanics.
- **Say when they can stop.** Lead with the default and the reassurance:
  most readers never reach for this, the defaults work, the advanced
  parts are optional. Let a skimmer leave after one paragraph.
- **Grant permission, don't demand attention.** "Reach for this
  when…", "for the rarer cases" — tell readers they're in the right
  place without implying they must read on.
- **Progressive disclosure.** Order by how many readers need it: the
  common call → the one argument a few will tune → the lower-level
  primitive → querying tmux directly. Each step is for a smaller
  audience than the last.
- **Lean on the hierarchy.** The reader thinks Server → Session → Window
  → Pane; reinforce that chain when you explain containment or
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

## README

A README is the shortest path from "what is this?" to competent use, not
the project's autobiography.

The first sentence is a contract. It says what abstraction the reader
has been handed, concretely enough to tell this package apart from the
neighbouring one.

Get to a runnable command or snippet before anything the reader can
skip. A logo, a mission statement, a comparison matrix and three
paragraphs of history in front of the install line all cost the same
thing.

State the minimum Python version and meaningful platform constraints in
prose, not only in badges. `requires-python` in `pyproject.toml` is the
authority; the README must agree with it.

Name the distribution, the import, and the executable separately
wherever they differ. That distinction prevents a Python-specific class
of confusion.

Examples are executable, not illustrative fiction. Never
`your-command <some-options>`. See
[Documented examples that run](#documented-examples-that-run) for which
blocks are executed and how to write one that qualifies.

Document the semantic model, not the parameter list. A signature already
enumerates parameters; what it cannot say is what the call mutates, what
blocks, and what it raises.

State defaults explicitly — defaults are API. State negative guarantees
where they exist: "performs no network I/O", "never mutates a `Session`
you didn't ask it to touch", "never writes outside the tmux socket it
was given". They establish boundaries faster than any amount of
description.

Headings stay conventional and stable, because people deep-link them.
Badges are few and load-bearing.

## Documented examples that run

Examples in this repository are tests. This section is the contract for
writing one the test suite can actually see, and it is this repo's real
mechanism — read from `pyproject.toml`'s `[tool.pytest.ini_options]` and
the root `conftest.py`, not assumed.

**A fence tag is cosmetic. Only a `>>> ` prompt executes.** A block
written as

    ```python
    server = Server()
    ```

is prose that looks like a test. Nothing collects it, nothing runs it,
and it can be wrong for years. The same block written with prompts is a
test:

    ```python
    >>> server = Server()
    ```

This is the single most expensive mistake available when editing
documentation, because removing the prompts leaves a green test suite
and a silently deleted test. When editing a file that contains examples,
count the prompts before and after.

**The fence tag is `python`** for a doctest session and `console` for a
shell command at a `$` prompt.

**Where examples run.** `testpaths` lists `src/libtmux`, `tests`,
`docs`, and `README.md`. `addopts` sets `--doctest-docutils-modules` and
`-p no:doctest`: the stdlib `doctest` pytest plugin is disabled, and
`gp-libs`' docutils-based collector (`pytest_doctest_docutils`, loaded
under the `sphinx` entry-point name) runs in its place. That collector
reads doctests out of `.py` docstrings *and* out of any Markdown or
reStructuredText page docutils parses — which is why a `>>> ` block in
`README.md` or under `docs/` is executed exactly like one in a
docstring. `ELLIPSIS` and `NORMALIZE_WHITESPACE` are enabled globally
(`doctest_optionflags`), so `...` elides variable output and whitespace
differences do not fail a comparison. Reach for an inline
`# doctest: +FLAG` only for the block that needs something more.

**`# doctest: +SKIP` is not permitted.** It is a workaround that tests
nothing. Use the fixtures.

**Do not downgrade a doctest to a non-executed block to make it pass.**
A `.. code-block::` or an unprompted fence does not run. If an example
cannot pass, fix the example or fix the code.

**The `doctest_namespace` fixtures.** The root `conftest.py`'s
`add_doctest_fixtures` fixture seeds `doctest_namespace` before any
doctest in the suite runs, so a block never needs an import or a setup
preamble to reach these names: `server`, `session`, `window`, `pane`,
`Server`, `Session`, `Window`, `Pane`, `Client`, `ControlMode`,
`control_mode`, `monkeypatch`, `tmp_path`, `request`. It only does this inside an
actual doctest item and only when `tmux` is on `PATH` — a doctest that
uses one of these names with no `tmux` binary available fails with a
`NameError`, not a skip.

**The `Server` trap.** `conftest.py` assigns `doctest_namespace["Server"]`
twice: first to the real `libtmux.server.Server` class, then — a few
lines later — to the `TestServer` fixture from
`src/libtmux/pytest_plugin.py`, a `functools.partial` that builds
uniquely-socketed servers and registers their cleanup. The second
assignment wins. A bare `Server(...)` in a doctest is therefore the test
factory, not the real class. Import the class explicitly when an example
needs class-level API:

```python
>>> from libtmux.server import Server
```

**The `socket_path` trap.** Both the `server` fixture and the doctest
`Server()` factory construct servers with a socket *name*, so their
`socket_path` attribute is `None`. When an example needs the real path,
ask tmux for it: `server.cmd("display-message", "-p",
"#{socket_path}").stdout[0]`.

**`# doctest: +HIDE`.** A `gp-libs` extension flag: it is a no-op for
execution and checking — the line still runs and its output, if any, is
still verified — but it tells the Sphinx-rendered docs to drop that line
from the page. Use it to set up state (an env var, a queried socket
path) a docstring's *Examples* section does not need to show:

```python
>>> from libtmux.server import Server as TmuxServer  # doctest: +HIDE
>>> socket_path = server.cmd(  # doctest: +HIDE
...     "display-message", "-p", "-t", pane.pane_id, "#{socket_path}"
... ).stdout[0]
```

**Every code block on a `docs/` page is an independent doctest.** Blocks
do not share a session: each one gets a fresh copy of the namespace
*and* a fresh tmux server. A later block cannot use a `pane` an earlier
block created — the name is simply not defined there. Write every block
self-contained. Order is load-bearing for the reader's narrative, not
for state — reorder, add, or drop a block as the prose demands, and keep
the story coherent.

**Docstring examples** use the NumPy `Examples` section:

    Examples
    --------
    >>> from example import add
    >>> add(2, 2)
    4

**Room to grow.** The docutils collector reads `.md` and `.rst`
wherever it is loaded, which is everywhere in this repository. A
prompted block added to a documentation page is executed from that
moment with no configuration change. The MyST `{doctest}` directive and
the reStructuredText `.. doctest::` directive are also registered and
available for a case that ever needs an explicitly marked block, rather
than a plain prompted fence. This section is where any additional
executed-block format is documented when one is adopted.

### Experimental operation examples

Every operation page under `docs/experimental/operations/` owns one visible
Python doctest before its API card. That block is the user example and the
executable proof; do not duplicate it in hidden setup or a separate generated
scenario.

- Drive the isolated fixture server through `SubprocessEngine.for_server(server)`.
  Mocks do not prove command rendering, target resolution, parsing, or the
  operation's effect on tmux.
- Show the typed result and the smallest observable outcome that distinguishes
  success from an acknowledgement. Use one of these proof shapes: typed read,
  creation, durable mutation, relationship change, destruction, transient
  acknowledgement, or version-gated behavior.
- Prefer a direct before/after query for mutations and destruction. For terminal
  output, synchronize with tmux or `Server.wait_for`; do not add an arbitrary
  sleep.
- Use a live control-mode client for client operations. A server with no
  attached client cannot demonstrate client behavior.
- Exercise a supported version-gated operation directly. A composed plan may
  report a skipped step, but the operation itself must expose its documented
  version error.
- Keep the primary proof compact. Put reusable setup, async forms, batching, and
  transport-specific behavior in an engine tutorial and link to it.

Operation examples must not contain `MockEngine`, `AsyncMockEngine`,
`# doctest: +SKIP`, or hidden `testsetup` directives.

## Documentation pages

Warm the framing, never the facts. Resolution-order lists, value
tables, exact error strings, format tokens, and class or method
cross-references carry meaning in their exact form — leave them alone.
The friendly voice belongs in the sentences *around* a precise block,
introducing it, not inside it paraphrasing it into vagueness.

Link the first prose mention of any symbol that has a useful
destination on that page — a Python object, a libtmux API, a tmux
concept with a glossary entry, a topic or configuration page, an
external tool or project. Use the most specific target available:
`{class}`, `{meth}`, `{func}`, `{mod}`, `{exc}`, or `{attr}` for API
objects; `{ref}`, `{doc}`, or `{term}` for documentation pages, section
anchors, and glossary entries; a Markdown link for an external project.
After the first linked mention on a page, later mentions can stay plain
unless the distance or context makes another link useful. Do not rely
on a later reference section to satisfy the first-mention rule — if the
first occurrence would be a heading, grid-card teaser, or introductory
sentence, link that occurrence or retitle the heading so the first
prose mention can carry the link. Leave command examples, code blocks,
and literal configuration values as code; link the surrounding prose
instead.

A `{ref}` must match its target's anchor exactly. Anchors mix
underscore and hyphen forms across pages (`context_managers`,
`pane-interaction`) — copy the target's own `(label)=` line rather than
guessing the form. `just build-docs` catches a broken cross-reference;
the doctests do not, so build the docs before you commit.

`docs/topics/pane_interaction.md` is the worked example: a
concept-first intro that says what a `Pane` *is* and which two methods
(`send_keys`, `capture_pane`) cover most uses before any signature, an
explicit "you can stop after the first two sections" reassurance,
sections ordered by shrinking audience, honest trade-offs (polling is a
busy wait; a resize is a request, not a guarantee), methods named by
what they do with `{meth}` cross-references, and precise capture-flag
and format tables left exact. Read it before reshaping another page.

## The changelog

`CHANGES` is the changelog. It is rendered as the Sphinx changelog page
(`docs/history.md` includes it) — not `CHANGELOG.md`. Modeled on
Django's release-notes shape: deliverables get titles and prose, not
bullets.

A ledger, not a narrative. It is scanned, and the question a reader is
asking is whether an entry affects them.

**Release entry boilerplate.** Every release header is
`## libtmux X.Y.Z (YYYY-MM-DD)`. The file opens with a
`## libtmux X.Y.Z (Yet to be released)` placeholder block fenced by
`<!-- KEEP THIS PLACEHOLDER ... -->` and `<!-- END PLACEHOLDER ... -->`
HTML comments — new release entries land immediately below the END
marker, never above it.

**Open with a multi-sentence lead paragraph.** Plain prose, no italic.
Open with the version as sentence subject ("libtmux X.Y.Z ships …") so
the lead is self-contained when excerpted. Two to four sentences telling
the reader what shipped and who cares — user-visible takeaways, not
internal mechanism. Cross-reference detail docs with `{ref}` to keep the
lead compact.

**Lead paragraphs are release-time material — off-limits to branches
and PRs.** The unreleased entry carries no lead paragraph and no version
summary: sections only (`### Breaking changes`, `### What's new`
deliverables, `### Fixes`, …). Speaking for the release — what the
version "is", "ships", or "focuses on" — is presumptuous before its
scope is final; only the person cutting the release writes that, and
only when the user explicitly asks to release. Never write or edit a
lead from a feature branch, and never ask or imply that a release should
happen.

**Each deliverable is a section, not a bullet.** Inside `### What's
new`, every distinct deliverable gets a `#### Deliverable title (#NN)`
heading naming it in user vocabulary, followed by 1-3 prose paragraphs
explaining what shipped. Don't wrap a paragraph in `- ` — bullets are
for enumerable lists, not paragraph containers. Cross-link detail docs
("See `{ref}`foo`` for details.") so prose stays focused.

**The deliverable test.** Before writing an entry, ask: "What's the
deliverable, in user vocabulary?" If you can't answer in one sentence,
the entry isn't ready. Mechanism (helper internals, byte counters,
schema-validation locations) belongs in PR descriptions and code
comments, not the changelog.

**Fixed subheadings**, in this order when present: `### Breaking
changes`, `### Dependencies`, `### What's new`, `### Fixes`,
`### Documentation`, `### Development`. Dev tooling (helper scripts,
internal automation) lives under `### Development`. For breaking
changes, show the migration path with concrete inline code (a `# Before`
/ `# After` fenced code block). Dependency floor bumps use the form
``Minimum `pkg>=X.Y.Z` (was `>=X.Y.W`)``.

**PR refs `(#NN)`** sit in each deliverable's `####` heading.

**When bullets are appropriate.** Catch-all sections (`### Fixes`,
occasionally `### Documentation`) with 3+ genuinely small items use
bullets — one line each, never paragraphs. If a bullet swells past two
lines, promote it to a `#### Title (#NN)` heading with prose body.

**Anti-patterns.**

- Fragile metrics: token ceilings, third-party version pins, percent
  benchmarks, exact byte counts. Describe the *capability*, not the
  math.
- Internal jargon: private symbols (leading-underscore identifiers),
  algorithm names exposed for the first time, backend scaffolding.
- Walls of text dressed up as bullets.
- Buried breaking changes — they get their own subheading at the top of
  the entry.

**Always link autodoc'd APIs.** Any class, method, function, exception,
or attribute that has its own rendered page must be cited via the
appropriate role (`{class}`, `{meth}`, `{func}`, `{exc}`, `{attr}`) —
never with plain backticks. Doc pages without explicit ref labels use
`{doc}`. Plain backticks are correct for code syntax, env vars,
parameter names, and file paths that aren't doc pages — anything without
an autodoc destination.

**MyST roles.** Class references use `{class}` (e.g.
`` {class}`~libtmux.Pane` ``), methods use `{meth}`, functions use
`{func}`, exceptions use `{exc}`, attributes use `{attr}`, internal
anchors use `{ref}`, doc-path links use `{doc}`, glossary terms use
`{term}`.

**Summarization style.** When a user asks "what changed in the latest
version?" or similar, lead with the entry's lead paragraph (paraphrased
if needed), followed by each `####` deliverable heading under
`### What's new` with a one-sentence summary. Cite `(#NN)` only if the
user asks for source links. Don't invent versions, dates, or numbers not
present in `CHANGES`. Don't quote line numbers or file offsets — those
shift as the file evolves.

## Release notes

`CHANGES` is the permanent ledger; a release page is editorial. Lead
with one paragraph naming the headline change, then three to five
highlights, then link the full changelog.

Numbers over adjectives. "Cold start 41 ms to 6 ms" is a sentence; "much
faster startup" is a smell.

A list of merged commit subjects is a merge log wearing a release-note
hat. Put the hand-written highlights above it.

Versions are PEP 440 identifiers. Semantic-versioning meaning is applied
to the documented public API — which includes configuration keys and
serialized formats, not only imported Python symbols.

## Docstrings

The prime directive: never restate the type. The annotation is the
source of truth; the docstring carries what the annotation cannot.

This is documentation debt wearing a docstring:

    def get_id(pane: Pane) -> str:
        """Get the pane's identifier.

        Parameters
        ----------
        pane : Pane
            The pane.

        Returns
        -------
        str
            The identifier.
        """

Document instead the dimensions the type system cannot encode:

- **Mutation.** What it changes in place.
- **Ownership.** What the caller must close, release, or keep alive.
- **Ordering.** Whether results come back in a guaranteed order.
- **Timing.** What has finished by the time the call returns, or the
  awaitable resolves.
- **Failure.** Which exceptions are raised and what triggers each.
- **Idempotence.** Whether calling twice does anything the second time.
- **Concurrency.** Whether calls are coalesced, queued, or independent,
  and whether the object is thread-safe, process-safe, or fork-safe.
- **Units and ranges.** What a number means and what values are
  accepted.
- **Boundary behaviour.** What zero, empty, and the maximum do.
- **Platform.** Behaviour that differs by operating system or dependency
  version.
- **Security boundary.** What is executed, and what is only read.

The ambiguity worth resolving by example: whether "retry three times"
means three attempts or four. State it.

The first sentence stands alone; tooling truncates there. PEP 257
applies: triple double quotes, an imperative one-line summary ending in
a period, a blank line before any extended description. Do not repeat
an introspectable signature.

All public functions and methods use the
[NumPy docstring convention](https://numpydoc.readthedocs.io/en/latest/format.html) —
enforced by ruff's `pydocstyle` rules (`convention = "numpy"` in
`pyproject.toml`), not relitigated in review:

```python
"""Short description of the function or class.

Detailed description using reStructuredText format.

Parameters
----------
param1 : type
    Description of param1
param2 : type
    Description of param2

Returns
-------
type
    Description of return value
"""
```

**Classes with fields** — `NamedTuple`, dataclasses — document every
field in an `Attributes` section:

```python
@dataclasses.dataclass()
class Pane(Obj, OptionsMixin, HooksMixin):
    """:term:`tmux(1)` :term:`Pane`.

    Attributes
    ----------
    server : Server
        Server the pane belongs to.
    """
```

Autodoc renders every field whether or not you describe it, so an
undocumented `NamedTuple` field ships to the API docs as "Alias for
field number 0" and a dataclass field ships bare. Document all of
them — a class with three fields and two documented still ships a stub
for the third.

## Source comments

A comment ships only if it passes all three gates. Fail any: delete or
rewrite. Borderline: delete — borderline means the information is
reconstructible, which is what makes deletion cheap.

**Loss.** Three years from now, would losing this cost a maintainer real
time rediscovering intent, an invariant, a constraint, or a failure mode
the code and tests do not already make obvious?

**Elite.** Would SQLite, Redis, the Go standard library, or CPython
write this comment, at this length? Those projects state the constraint
and stop. They do not argue with an imagined objector.

**Upkeep.** Will it stay true without maintenance? A comment that
hand-syncs a value the code owns — a count, an offset, a line reference,
a duplicated constant — is false the first time that value moves.

### Ceiling

One or two lines. A comment reaching four is either carrying several
facts, in which case split it, or arguing, in which case cut it to the
fact.

Rationale, alternatives weighed, and the story of how the code got here
belong in the commit message: timestamped, attached to the exact diff,
and free to maintain.

A comment often holds both a constraint and the deliberation that found
it. Keep the constraint, cut the deliberation. "Runs at most once per
second" survives; "this is the right trade for now" does not.

### Keep

- Why over how: upstream quirks, protocol and compatibility constraints,
  performance tradeoffs still part of the contract.
- Invariants, preconditions, ordering, lifetime, and concurrency
  requirements that types and tests cannot express.
- Code that looks wrong but is not, so a later cleanup does not
  reintroduce the bug.
- A high-level sketch of an algorithm whose local operations do not
  reveal the whole.

### Delete

- Narration of the next lines; code translated into English.
- Restated names, types, defaults, or control flow.
- Values duplicated from the code and hand-synced.
- Justification, hedging, or apology for a choice.
- Speculation about future requirements.
- History version control already holds, including commented-out code.
- Ticket and issue numbers. They say nothing to a reader without
  tracker access, and they rot when the tracker moves. Unfinished work
  goes in the tracker, not the source.
- Transient observations — "currently", "for now", "the latest
  release" — that go stale with no nearby edit.

### The upkeep gate in practice

It reaches values that track our own code. It does not reach frozen
external facts.

Bad (Delete):

```python
# There are 321 tests to complete for servers.
```

Good (Keep):

```python
# tmux < 3.2 reports the pane ID only after the command completes,
# so this query must stay separate.
```

### Documentation exception

Doctests, minimal usage examples, and param, return, and raises lines on
public API are exempt from the loss gate — they serve the caller, not
the maintainer. They are exempt from nothing else. Ceiling: a good man
page entry.

NumPy-style `Parameters`, `Returns`, and `Attributes` sections and
executable doctests fall under this exception — autodoc ships every
field whether or not you describe it, and a doctest that runs is also a
test.

## Terminology and capitalization

Pick the domain noun and keep it. If the code calls something a
session, do not call it a workspace in one paragraph and an environment
in the next. If the method is `capture_pane`, write "capture"
everywhere rather than alternating with "read", "grab", and "snapshot".

Stable vocabulary is what makes search, deep links, and an agent's
retrieval work at all.

Python and PyPI keep their own capitalisation. Distribution names are
written as they are published.

Do not write counts into prose — how many symbols exist, how many tests
there are. They go stale silently and no reader needs them. Counts that
pin a fixture or guard an invariant are different, and belong in code.

## Markdown

Prose wraps at 80 columns. Table rows, badge lines, and long links are
exempt, because breaking them harms rendering. A pull request or issue
body does not wrap at all: GitHub renders a single newline as a space in
a file and as a line break in a comment, so a wrapped comment body
arrives as ragged stubs.

GitHub alert blocks — `> [!NOTE]`, `> [!WARNING]` — render as literal
text outside GitHub, so reserve them for at most one load-bearing
warning per document. Write the sentence so it carries the fact on its
own, and a renderer that drops the marker loses nothing.

Do not use a local absolute path or an email address in anything
published.

## Code blocks

Code blocks are paste-and-run units: pasting one block runs exactly one
intended action. Executed examples are exempt — the test suite runs
them, nobody pastes them.

- **One command per block.** Multiple steps may share a block only when
  explicitly chained with `&&`, `;`, or `\` continuations — the chain is
  then one logical command.
- **Explanations go in prose above the block**, never as `#` comments
  inside it.
- **Command menus are per-command blocks with prose lead-ins**, not
  tables.
- **Shell commands use the `console` tag with a `$ ` prefix.** This
  separates interactive commands from scripts and enables prompt-aware
  copy.
- **Split long commands with `\`** — one flag or flag+value pair per
  indented continuation line, positional arguments last.

Good — show the last ten commits as a graph:

```console
$ git log \
    --max-count=10 \
    --graph \
    --oneline
```

Bad:

```console
# Show the last ten commits as a graph
$ git log --max-count=10 --graph --oneline
```

## Commits

```
Scope(type[detail]): concise description

why: Explanation of necessity or impact.

what:
- Specific technical changes made
- Focused on a single topic
```

Keep the subject to 50 characters or fewer, excluding any trailing
`(#NN)` pull request reference, and wrap body lines at 72. Separate the
`why:` and `what:` blocks with a blank line.

The subject has two forms. `Scope(type[detail]): Description`, with a
colon, for anything that changes behaviour. `Scope(type[detail])
Description` — no colon — for routine maintenance: a dependency bump
(`py(deps…)`) or an AI rule update (`ai(rules…)`) that does not change
what the code does.

Common types:

- **feat**: New features or enhancements
- **fix**: Bug fixes
- **refactor**: Code restructuring without functional change
- **docs**: Documentation updates
- **chore**: Maintenance (dependencies, tooling, config)
- **test**: Test-related updates
- **style**: Code style and formatting
- **ci**: Workflow and pipeline changes
- **py(deps)**: Dependencies
- **py(deps[dev])**: Dev dependencies
- **ai(rules[AGENTS])**: AI rule updates
- **ai(claude[rules])**: Claude Code rules (`CLAUDE.md`)
- **ai(claude[command])**: Claude Code command changes

Example:

```
Pane(feat[send_keys]): Add support for a literal flag

why: Send characters without tmux interpreting them.

what:
- Add a literal parameter to send_keys
- Pass -l when it is set
```

For a multi-line message, use a heredoc so the formatting survives:

```console
$ git commit -m "$(cat <<'EOF'
Scope(feat[detail]): Concise description

why: Explanation of the change.

what:
- First change
- Second change
EOF
)"
```

### Release commits

Never create tags. Never push tags. The owner handles tagging and tag
pushes, because a tag triggers the publish workflow.

A release commit subject is plain and short: `Tag v<version>`. The
detailed why and what go in the body. Do not use the
`Scope(type[detail]):` format for a release — it buries the lede.

## Slop prevention

Treat AI slop as review-hostile noise, not as proof that text or code is
wrong. The goal is to maximise information density.

- **AI signatures.** No "Generated by", no conversational filler
  ("Certainly!", "Here is..."), no unexplained emoji, no tool metadata.
- **Brittle references.** No hard-coded line numbers, fragile file or
  test counts, dated "as of" claims, bare SHAs, or local absolute
  paths — unless they are strict evidentiary artefacts such as a
  benchmark log.
- **Diff narration.** Do not restate what moved, was renamed, or was
  removed in anything the reader holds alongside the diff: code,
  docstrings, README, CHANGES, or a pull request description. The diff
  and commit message already carry it.
- **Branch-internal narrative.** Do not mention intermediate states,
  abandoned approaches, or "no longer" behaviour unless users of a
  published release actually experienced the old state — see
  [Shipped vs. branch-internal narrative](#shipped-vs-branch-internal-narrative).
- **Low-value scaffolding.** No ownerless TODOs, unused
  future-proofing, debug artefacts, or defensive wrappers around
  failure modes nothing can reach.
- **Prose inflation.** The diction table under [Voice](#voice) governs;
  replace an inflated word with a concrete description of behaviour,
  constraints, or trade-offs.
- **Coded labels.** Write rules and findings as plain imperatives. No
  `[R1]`, `Option B`, or any index a reader has to decode. Internal
  agent bookkeeping may use ids; shipped text may not.

Preserve the "why". Never delete a comment documenting an invariant, a
protocol constraint, a platform quirk, or an upstream workaround — those
are the facts [Source comments](#source-comments) keeps, and every other
comment is judged by it. Preserve exact counts, dates, and SHAs that
serve as evidence in benchmark results, release notes, stack traces, or
lockfiles — that evidence is immune to the brittle-references rule
above.

### Durable source links

Link to a pinned revision, never to trunk. A pinned permalink is not a
brittle reference; an unlinked SHA dropped into prose is. `blob/master/…`
links rot silently — the file moves, lines shift, and the anchor lands
on unrelated code while still resolving.

- Prefer a release tag (`blob/v1.4.0/…`). Most durable, and it tells the
  reader which released version the claim held for.
- Otherwise use a 7-char commit ref (`blob/9a29b1a/…`) reachable from
  trunk. Use when there is no tag or the claim is about unreleased
  code. Never a PR-head SHA — it can be rebased or garbage-collected.
- Reserve `blob/master/…` for living documents meant to always show the
  latest state, such as this contributing guide.
- Line anchors (`#L120-L145`) are only safe on a pinned ref.

### Shipped vs. branch-internal narrative

Long-running branches accumulate tactical decisions — renames,
refactors, attempts-then-reverts, intermediate states. Commit messages
and the diff hold what changed and why. Do not restate either in
artefacts the downstream reader holds: code, docstrings, README,
CHANGES, pull request descriptions, release notes, migration guides.

When deciding what counts as branch-internal, use trunk or the parent
branch as the baseline — not intermediate states inside the current
branch.

**The published-release test.** Before adding rename history,
"previously" / "formerly" / "no longer X" phrasing, "removed" / "moved"
/ "refactored" / "fixed" diff paraphrases, or a `### Fixes` entry to a
user-facing surface, ask: did users of the most recently published
release ever experience this old name, old behaviour, or bug? If no, it
is branch-internal narrative — move it to the commit message and
describe only the current state in the artefact.

**Keep in shipped artefacts.** Deprecations and migration guides for
symbols that actually shipped. `### Fixes` entries for bugs that
affected users of a published release. Comments explaining why the
current code looks this way — invariants, platform quirks, upstream bug
workarounds — that make sense to a reader who never saw the previous
version. Default: when in doubt, keep the artefact clean and put the
story in the commit.

**Cleanup in hindsight.** Applying this rule retroactively from inside
a feature branch: first diff against the parent branch or trunk to see
which commits this branch actually introduced. For commits this branch
introduced, offer `fixup!` commits with `git rebase --autosquash`, or
one cleanup commit at branch tip — the author chooses. Leave commits
already in trunk or a parent branch alone by default; act on them only
on explicit instruction, and then fold the cleanup into one commit at
branch tip without rewriting trunk or parent-branch history. If
cleaning up in-branch bleed would touch a colleague's in-flight work or
expand the branch beyond its stated goal, stay in lane: protect the
branch's current goal and leave prior bleed alone.
