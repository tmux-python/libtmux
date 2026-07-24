---
name: testing-mcp-with-cli-agents
description: >-
  Test an MCP server by driving real CLI agents (Claude, Codex, Cursor, Gemini,
  Grok, agy) against it — isolating each CLI's config and the server's own
  backend state instead of trusting unit tests alone. Use this whenever
  verifying MCP-server behavior end-to-end, checking that a local branch or
  checkout works across installed agent CLIs, comparing trunk-vs-branch
  behavior, driving an interactive agent TUI to exercise approval flows or
  cancellation, or reproducing a bug through a live client. Reach for it even
  when the user only says "test the MCP", "does the branch work in the agents",
  "drive the CLI to call the tool", or "check it across Codex/Gemini/Cursor".
---

# Testing an MCP server through real CLI agents

Unit tests prove the server's internals; they don't prove a real agent can
discover a tool, clear its approval gate, call it, and survive cancelling it
mid-flight. This skill exercises that whole path by pointing installed CLI
agents at a checkout and driving them. Here the server is libtmux's
tmux-control MCP (`libtmux-engine-mcp`, registered under the `libtmux` slug),
and its backend-isolation lever is a scratch tmux socket
(`LIBTMUX_SOCKET=<scratch>` → an isolated `tmux -L <scratch>` server) — the
thing that scratches every side effect a tool call would otherwise make.

## The core idea: isolate two things, never zero

Driving an MCP server through a real CLI mutates two things you don't want
touched. Isolate both and the whole exercise is safe and observable:

1. **The CLI's config.** Use a throwaway config-home or project config so the
   real `~/.codex`, `~/.claude.json`, etc. are never written. Each CLI's lever
   is in `references/cli-matrix.md`.
2. **The server's backend / side effects.** Point the server at a *scratch*
   backend via its own env var or flag, so tool calls never touch real state
   and you can assert against that scratch backend as independent ground truth.

What "scratch backend" means depends on the server:

| Server kind | Scratch-backend lever | Ground-truth check |
|---|---|---|
| tmux control (libtmux-mcp) | `LIBTMUX_SOCKET=<scratch>` → an isolated `tmux -L <scratch>` server | `tmux -L <scratch> list-windows` |
| search / index (agentgrep) | a scratch index/store dir via the server's data-dir env/flag | inspect the scratch index, not the real store |
| filesystem | a temp working root | check the temp tree |
| external API | a sandbox/base-URL override or a recording | the sandbox's own state |

The principle is identical everywhere: the server writes only to scratch, and
you verify against scratch — so "the agent said it worked" is separated from
"the tool actually did it," and a destructive tool can't harm anything real.

## Climb only as high as the question needs — three fidelity layers

### Layer 0 — Direct MCP smoke, no CLI at all

Fastest and most deterministic. Drive the server over stdio from a tiny FastMCP
client against a scratch backend and assert the wire contract directly: the tool
list, a couple of representative calls, an error path. Use this to answer "is
the tool surface and result shape correct?" before spending a CLI on it.
Normalize result shapes before asserting — `structuredContent` is often
`{"result": [...]}`, and single-value returns can arrive as a bare string.

### Layer 1 — Headless CLI one-shot

Proves the real client can discover and call the tools, scriptably, with no
send-keys. Every CLI has a non-interactive mode. Run a cheap discovery proof
first (does the client *see* the server?) — but the cheapest proof differs
sharply per CLI: grok's `mcp doctor` does a real handshake, codex's `mcp get`
only parses config, some CLIs have nothing short of a model call.
`references/cli-matrix.md` has the verified per-CLI invocation, isolation lever,
and approval-bypass flag. Two recurring surprises: some `mcp list`/`list-tools`
subcommands read the *ambient* config and ignore your isolated one, and a
mutating tool call needs a per-CLI approval-bypass flag or it hangs on a no-TTY
prompt.

### Layer 2 — Interactive, driven by tmux send-keys

The high-fidelity path, and the only one that exercises approval flows, live
streaming, multi-turn, and cancellation. Run the agent's TUI in a **harness**
tmux socket (`tmux -L cli-harness`, separate from any socket the server itself
uses) and drive it:

```console
$ tmux -L cli-harness new-session -d -s agent -x 220 -y 50   # wide, so TUI isn't wrapped
$ tmux -L cli-harness send-keys -t agent 'cd /repo && <cli launch with backend isolation>' Enter
$ tmux -L cli-harness capture-pane -p -t agent | tail -5      # poll until the prompt renders
$ tmux -L cli-harness send-keys -t agent 'Use the libtmux MCP to <do a thing>'
$ tmux -L cli-harness send-keys -t agent Enter                # separate event — see below
$ tmux -L cli-harness send-keys -t agent 'y' Enter            # answer the approval gate
$ tmux -L cli-harness capture-pane -p -t agent | tail -30     # what the agent rendered
# then assert GROUND TRUTH against the scratch backend (not the transcript)
```

The final ground-truth step is the whole point: Layers 0 and 1 can be fooled by
a hallucinated success line; the scratch backend cannot.

## Two failure modes that waste the most time

**Approval gates hang naive harnesses.** The first tool use pops an approval
dialog. A driver that types the prompt and immediately waits for output waits
forever. Pre-approve with the CLI's trust/approval flags (see the matrix), or
detect the prompt via `capture-pane` and answer its keystroke before waiting.

**Sleeping instead of waiting is flaky, and blind typing doesn't submit.** Poll
`capture-pane` for a stable completion marker rather than `sleep N`. Send the
prompt text and `Enter` as **separate** `send-keys` events — then one Enter
submits; batching text+Enter in one call is what leaves the prompt unsent. And a
CLI launched inside a `-L` harness pane runs in a non-login shell that lacks your
mise/node/uv shims, so `export` the needed bin dirs before launching it.

## High-value test: cancellation / teardown

Cancellation is invisible to the tool list and only reachable through Layer 2.
With a long-running tool (a wait, a big scan): start it, then while the TUI shows
"working / esc to interrupt" send `Escape` to that pane. `Esc` during the working
phase cancels the in-flight tool call while keeping the MCP server subprocess
alive — the exact client-cancellation a server's teardown path must survive;
`Esc` after a turn finishes just enters edit-previous mode. Then assert the
scratch backend is clean and no child process leaked.

## Comparing two versions (trunk vs a branch)

Two worktrees, two scratch backends, same prompt. Diff three things: the **tool
surface** (a Layer-0 `tools/list` dump or `mcp list-tools`, diffed), the
**rendered agent behavior** for the same prompt (capture-pane transcripts), and
the **scratch-backend state** afterward.

## Wiring a checkout into the CLIs: mcp_swap

`scripts/mcp_swap.py` rewrites each CLI's config to run a local checkout, with
backup/revert:

```console
$ uv run scripts/mcp_swap.py detect                          # which CLIs are present
$ uv run scripts/mcp_swap.py doctor --server libtmux-engine         # effective environment + footguns
$ uv run scripts/mcp_swap.py status --server libtmux-engine
$ uv run scripts/mcp_swap.py use-local --server libtmux-engine --env KEY=VALUE --dry-run
$ uv run scripts/mcp_swap.py use-local --server libtmux-engine --env KEY=VALUE
$ uv run scripts/mcp_swap.py revert
```

Run `doctor` first — it reports which server name each CLI points at (and warns
when the repo is registered under a name other than the derived default),
un-reverted swaps and orphaned backups, missing backups (revert would fail), and
auth-overriding env vars like `OPENAI_API_KEY`. Use `--env` to inject the
backend-isolation var (e.g. an isolated socket or data dir) at swap time.

**Prefer zero-mutation isolation for a test.** mcp_swap is for a swap you *want*
to persist. To just exercise a checkout, use each CLI's throwaway
config-home / project-config lever (`references/cli-matrix.md`) — all were
verified to drive the server with the real config confirmed byte-identical
afterward, and no swap state touched. `use-local` mutates real configs, so
dry-run first and always `revert` at the end; and the machine may already carry
an un-reverted swap, so `revert` returns you to *that* state, not a pristine one
(check `doctor` first).

## When NOT to reach for the full harness

If the question is purely "is the tool surface correct?" stay at Layer 0 —
booting six CLIs to answer a wire-contract question is wasted effort. Escalate to
Layers 1 and 2 only when the client's discovery, approval, streaming, or
cancellation behavior is what's actually in doubt.
