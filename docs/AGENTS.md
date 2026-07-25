# Experimental documentation

Documentation follows [WRITING.md](../.github/WRITING.md).
The doctest namespace also provides `tmp_path` for these examples.

## Experimental operation examples

Every operation page under `experimental/operations/` owns one visible Python
doctest before its API card. That block is the user example and the executable
proof; do not duplicate it in hidden setup or a separate generated scenario.

- Drive the isolated fixture server through
  `SubprocessEngine.for_server(server)`. Mocks do not prove command rendering,
  target resolution, parsing, or the operation's effect on tmux.
- Show the typed result and the smallest observable outcome that distinguishes
  success from an acknowledgement. Use one of these proof shapes: typed read,
  creation, durable mutation, relationship change, destruction, transient
  acknowledgement, or version-gated behavior.
- Prefer a direct before/after query for mutations and destruction. For
  terminal output, synchronize with tmux or `Server.wait_for`; do not add an
  arbitrary sleep.
- Use a live control-mode client for client operations. A server with no
  attached client cannot demonstrate client behavior.
- Exercise a supported version-gated operation directly. A composed plan may
  report a skipped step, but the operation itself must expose its documented
  version error.
- Keep the primary proof compact. Put reusable setup, async forms, batching,
  and transport-specific behavior in an engine tutorial and link to it.

Operation examples must not contain `MockEngine`, `AsyncMockEngine`,
`# doctest: +SKIP`, or hidden `testsetup` directives.

