# CLI matrix — per-CLI isolation, proofs, and gotchas

Verified 2026-07-24 by driving all six CLIs against a local MCP server on
throwaway configs. **Every real config was confirmed byte-identical
before/after** — no CLI needs `mcp_swap` or a real-config write to be tested.
Full model-driven tool-call proof was reached on **codex, cursor, grok, agy**;
**claude** and **gemini** were blocked at account tier/credit, not by the
harness. Flags drift — re-verify with `<cli> --help` before trusting any
invocation. Throughout, `libtmux` is the server's registered slug and
`LIBTMUX_SOCKET` is the env var that scratches its backend — pointing the
server at an isolated `tmux -L <scratch>` control server.

## Cross-cutting lessons (the transferable part)

1. **Isolate the config, never mutate it.** Every CLI exposes a config-home or
   project-config lever (table below). None requires `mcp_swap` for a test.
2. **The wall is auth/account tier, not the harness.** claude → `Credit balance
   is too low`; gemini → `IneligibleTierError` (free tier unsupported). Treat
   these as findings and stop spending; they are not harness failures.
3. **Name the throwaway server distinctively.** CLIs commonly already carry an
   entry under a shared slug pointing elsewhere. An identical name silently
   collides — it merges (cursor), shadows (gemini), or gets resolved instead of
   yours (claude `mcp list`). A unique name makes leakage obvious. (This is also
   why `mcp_swap doctor` warns when the repo's derived server name isn't the one
   the CLIs are actually registered under.)
4. **Config leaks across CLIs.** grok merges Claude Code's `~/.claude.json` *and*
   any cwd `.mcp.json`; agy and gemini share the `~/.gemini` tree; codex's daemon
   is keyed to `CODEX_HOME`. Assume ambient servers are present unless you
   override `HOME`/config-home fully.
5. **"Cheapest proof" is not uniform.** grok's `mcp doctor` does a real
   handshake; codex's `mcp get` only parses config; agy has nothing short of a
   model call. Pick per CLI (table).
6. **PATH:** for a **headless** run, export the node + uv dirs once before
   invoking — the CLI inherits them. The alternate-socket-pane PATH gap (a `-L`
   pane's non-login shell lacks the mise shims) only bites when you launch a CLI
   **TUI inside a harness pane** (Layer 2).
7. **Non-interactive mutating tool calls need an approval-bypass flag** —
   different per CLI (table). Without it, a mutating call blocks on a no-TTY
   prompt and the harness hangs.
8. **Interactive send-keys submit:** send the prompt text and `Enter` as
   **separate** `send-keys` events — then one Enter submits. `Esc` cancels only
   *during* the working/tool phase; after a turn completes it enters
   edit-previous mode.

## Quick matrix

| CLI | headless one-shot | config-isolation lever | cheapest discovery proof | approval bypass (non-interactive) | full model proof reached |
|---|---|---|---|---|---|
| claude | `claude -p` | `--mcp-config <f> --strict-mcp-config` (session only) | `-p --output-format stream-json` init event | `--permission-mode bypassPermissions` | no — credit blocked |
| codex | `codex exec` | `CODEX_HOME` throwaway **or** `-c` overrides | `codex mcp get libtmux-engine` (parses config, no spawn) | `--dangerously-bypass-approvals-and-sandbox` | yes |
| cursor | `cursor-agent --print` | project `.cursor/mcp.json` (merged, not isolating) | headless `--approve-mcps` run (see trap) | `--force --approve-mcps` (omit `--mode`) | yes |
| gemini | `gemini -p` | project `.gemini/settings.json` from cwd | `gemini mcp list` | `--approval-mode yolo` (`--skip-trust`) | no — free tier |
| grok | `grok -p` / `--single` | `GROK_HOME` **or** `mcp add --scope project` | `grok mcp doctor libtmux --json` (real handshake) | `--permission-mode bypassPermissions` | yes |
| agy | `agy -p` | hidden `--gemini_dir <path>` | none short of a model call | `--dangerously-skip-permissions` | yes |

## Per-CLI detail

### codex — two isolation styles
- **Config-less (leanest):** a home dir with only a symlink to real `auth.json`,
  no `config.toml`, plus `-c` overrides:
  `-c 'mcp_servers.libtmux-engine.command="..."' -c 'mcp_servers.libtmux-engine.args=[...]' -c 'mcp_servers.libtmux-engine.env.LIBTMUX_SOCKET="..."'`.
- **Copy-config:** `cp ~/.codex/config.toml <home>/`; symlink `auth.json`;
  rewrite `[mcp_servers.libtmux-engine]`. Downside: **drags in the user's hooks/output
  style** — prefer the `-c` style.
- Run: `env -u OPENAI_API_KEY CODEX_HOME=<home> codex exec --dangerously-bypass-approvals-and-sandbox --skip-git-repo-check -C <repo> '<prompt>'`.
- Gotchas: **`OPENAI_API_KEY` hijacks auth** to API-key billing even with a
  ChatGPT `auth.json` — always `env -u OPENAI_API_KEY`. **No `codex mcp
  list-tools`**; `mcp list`/`get`/`doctor` only parse config — real enumeration
  needs a model turn. Subcommand flags are position-sensitive (after the
  subcommand; `--skip-git-repo-check` is exec-only). Env values show masked as
  `*****` in `mcp get`. The `/tmp` `CODEX_HOME` helper-binary warning is harmless.

### cursor — and it CORRECTS common prior art
- Project `<ws>/.cursor/mcp.json` with a **distinct** server name; run with
  cwd=`<ws>` or `--workspace <ws>`:
  `cursor-agent --print --output-format stream-json --trust --approve-mcps --force --workspace <ws> '<prompt>'`.
- **`mcp list-tools <unapproved>` FAILS** on build 2026.07.23 (`has not been
  approved`) — the older "list-tools bypasses approval" note is reversed. Prove
  via a headless `--approve-mcps` run + the backend, not `list-tools`.
- **`--mode ask`/`--mode plan` are read-only**, so a mutating call is
  suppressed. Omit `--mode` and add `--force`.
- Project config is **merged** with global (all global servers still load) —
  isolate by unique name + the backend env var, not by expecting override. No
  `mcp add`; config is a JSON file only.

### grok — best cheap proof
- `GROK_HOME=<ws>/.grok grok mcp add libtmux-engine -e LIBTMUX_SOCKET=... -- <server-cmd>`,
  then `cp ~/.grok/auth.json ~/.grok/agent_id <ws>/.grok/` (**auth does not
  follow `GROK_HOME`**), then
  `GROK_HOME=<ws>/.grok grok -p '<prompt>' --permission-mode bypassPermissions --cwd <ws> --output-format plain`.
- `grok mcp doctor libtmux --json` is the **best cheap proof of any CLI** — a
  real handshake reporting tool count, no model turn. Alternative: `mcp add
  --scope project` writes `./.grok/config.toml` (keeps real `$HOME`/auth).
- Gotchas: **grok merges `~/.claude.json` + cwd `.mcp.json`**, so `GROK_HOME`
  alone doesn't fully isolate — override `HOME` for a clean set. `grok models`
  says "not authenticated" even when valid (trust `doctor` and the run).

### agy (Antigravity) — no `mcp` verb
- **Hidden `--gemini_dir <path>`** flag (not in `--help`) relocates the entire
  `~/.gemini` tree. Symlink the real auth/state files into `<gdir>`, but make
  `<gdir>/config/mcp_config.json` your own `{"mcpServers":{"libtmux-engine":{...}}}`.
- Run: `PATH=<uv>:<node>:$PATH agy --gemini_dir <gdir> --log-file <log> --dangerously-skip-permissions --print-timeout 3m -p '<prompt>'`.
- Gotchas: **no `mcp` verb at all** — configure by editing `mcp_config.json`;
  only a model call enumerates. `--gemini_dir` does **not** isolate auth (symlink
  it). `--print-timeout` default is 5m — set it low and wrap in `timeout`.

### claude — isolation proven, model turn often credit-blocked
- `--mcp-config <file> --strict-mcp-config` scopes which MCP servers a
  `-p`/interactive **session** sees — but the server sits at `status:"pending"`
  and connects lazily on the **first model turn**, so you can't enumerate its
  tools without spending one.
- **`claude mcp list`/`get` ignore `--mcp-config`** and inspect the *ambient*
  config. Use a `-p --output-format stream-json` run and read the `init` event's
  `mcp_servers` array.
- `--strict-mcp-config` scopes MCP **only**: a `-p` run still writes
  `~/.claude.json` and creates `~/.claude/projects/<cwd>/`, and ambient
  hooks/skills fire. Add **`--bare`** to strip them. `mcp list` alone leaves
  `~/.claude.json` untouched.
- Auth: `ANTHROPIC_API_KEY` (if set) takes precedence over the claude.ai OAuth
  login; `env -u ANTHROPIC_API_KEY claude …` forces subscription auth.

### gemini — isolation proven, model turn often tier-blocked
- Project `<ws>/.gemini/settings.json` (`{"mcpServers":{"libtmux-engine":{"command","args","env"}}}`)
  read from **cwd**; a project-scoped server **shadows** a same-named user
  server. `gemini mcp add <name> <cmd> [args] -s project -e K=V` defaults to
  project scope.
- Run: `gemini --skip-trust --allowed-mcp-server-names libtmux-engine --approval-mode yolo --output-format json -p '<prompt>'` (verified against gemini 0.52.0).
- Gotchas: **untrusted folders disable ALL MCP** — pass `--skip-trust` (`mcp
  list` shows Disabled without it — expected, not a failure). A failed headless
  run **still mutates `~/.gemini/projects.json`** (appends the cwd); full
  isolation needs a `HOME`/config-dir override (which discards real OAuth).
