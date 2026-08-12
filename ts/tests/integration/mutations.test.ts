import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import {
  prepareRunRoot,
  reapOwnedRunRoot,
  runWithCleanup,
} from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";
import { Server } from "../../src/server.js";

function serverFor(fixture: TestServer): Server {
  return new Server({
    environment: fixture.controllerEnvironment,
    socketPath: fixture.socketPath,
    tmuxBin: fixture.tmuxExecutable,
  });
}

async function withServer(body: (fixture: TestServer) => Promise<void>): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-mutate-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "mutate" });
        await runWithCleanup(
          () => body(fixture),
          () => fixture.dispose(),
        );
      },
      async () => {
        if (published === undefined) await reapOwnedRunRoot(runRoot);
        done = true;
      },
    );
  } finally {
    if (done) await rm(parent, { force: true, recursive: true });
  }
}

describe("lifecycle mutations", () => {
  test("creates a session, window, and pane, resolving each as a handle", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);

      const session = await server.newSession({ name: "created" });
      expect(session.session_name).toBe("created");

      const window = await session.newWindow({ name: "editor" });
      expect(window.window_name).toBe("editor");
      expect(window.session_id).toBe(session.session_id);

      const pane = await window.split();
      expect(pane.window_id).toBe(window.window_id);
      // The returned pane is live; the window handle predates the split and
      // still reports the instant it was created at.
      expect((await window.panes()).length).toBe(1);
      expect((await server.snapshot()).panes.count({ window: { is: { name: "editor" } } })).toBe(2);
    });
  }, 40_000);

  test("a snapshot taken before a mutation keeps reporting its own instant", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const before = await server.snapshot();

      await server.newSession({ name: "later" });

      expect(before.sessions.length).toBe(1);
      expect((await server.snapshot()).sessions.length).toBe(2);
    });
  }, 40_000);

  test("kills a pane, window, and session", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = await server.newSession({ name: "doomed" });
      const window = await session.newWindow({ name: "temp" });
      const pane = await window.split();

      await pane.kill();
      // The window handle predates the split, so it keeps reporting its own
      // instant rather than tracking later mutations.
      expect((await window.panes()).length).toBe(1);
      // A fresh snapshot shows the split pane was really removed.
      expect((await server.snapshot()).panes.count({ window: { is: { name: "temp" } } })).toBe(1);

      await window.kill();
      expect((await server.snapshot()).windows.count({ name: "temp" })).toBe(0);

      await session.kill();
      expect((await server.snapshot()).sessions.count({ name: "doomed" })).toBe(0);
    });
  }, 40_000);

  test("reports a tmux failure rather than inventing a handle", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      await server.newSession({ name: "duplicate" });

      await expect(server.newSession({ name: "duplicate" })).rejects.toThrow(/new-session failed/);
    });
  }, 40_000);

  test("refresh advances one handle without unfreezing selections", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const snapshot = await server.snapshot();
      const window = snapshot.windows.one();
      expect((await window.panes()).length).toBe(1);

      await window.split();

      // The selection stays frozen at its own instant.
      expect(snapshot.windows.length).toBe(1);
      expect((await window.panes()).length).toBe(1);

      await window.refresh();

      // Only the refreshed handle advances.
      expect((await window.panes()).length).toBe(2);
      expect(snapshot.panes.length).toBe(1);
    });
  }, 40_000);

  test("refresh keeps a linked window on its own placement", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      await server.newSession({ name: "other" });
      const window = (await server.snapshot()).windows
        .filter((candidate) => candidate.session_name === fixture.sessionName)
        .one();
      await window.link({ index: 9, session: "other" });

      const originalIndex = window.window_index;
      await window.refresh();

      // Refreshing resolves the placement it was created at, not the new one.
      expect(window.window_index).toBe(originalIndex);
      expect(window.session_name).toBe(fixture.sessionName);
    });
  }, 40_000);

  test("refreshing a killed object reports it rather than going quiet", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = await server.newSession({ name: "transient" });

      await session.kill();

      await expect(session.refresh()).rejects.toThrow(/no longer exists/);
    });
  }, 40_000);
});
