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
  const parent = await mkdtemp(join(tmpdir(), "ltx-options-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "opts" });
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

describe("option reads", () => {
  test("reads a server option that was just set", async () => {
    await withServer(async (fixture) => {
      await fixture.executeText(["set-option", "-s", "history-file", "/tmp/ltx history"]);

      const options = await serverFor(fixture).showOptions();

      expect(options.get("history-file")).toBe("/tmp/ltx history");
    });
  }, 30_000);

  test("reads session, window, and pane scopes independently", async () => {
    await withServer(async (fixture) => {
      await fixture.executeText(["set-option", "-t", fixture.sessionId, "status-left", "SESS"]);
      const snapshot = await serverFor(fixture).snapshot();
      const session = snapshot.sessions.one();
      const window = snapshot.windows.one();
      const pane = snapshot.panes.one();

      await fixture.executeText([
        "set-option",
        "-w",
        "-t",
        window.window_id ?? "",
        "main-pane-width",
        "81",
      ]);
      await fixture.executeText([
        "set-option",
        "-p",
        "-t",
        pane.pane_id ?? "",
        "remain-on-exit",
        "on",
      ]);

      const [sessionOptions, windowOptions, paneOptions] = await Promise.all([
        session.showOptions(),
        window.showOptions(),
        pane.showOptions(),
      ]);

      expect(sessionOptions.get("status-left")).toBe("SESS");
      expect(windowOptions.get("main-pane-width")).toBe("81");
      // Window scope does not leak session options.
      expect(windowOptions.has("status-left")).toBe(false);
      // Pane scope lists only what was set on the pane, never inherited values.
      expect(paneOptions.get("remain-on-exit")).toBe("on");
      expect(paneOptions.has("main-pane-width")).toBe(false);
    });
  }, 30_000);

  test("preserves the index on array-valued options", async () => {
    await withServer(async (fixture) => {
      const options = await serverFor(fixture).showOptions();
      const indexed = [...options.keys()].filter((name) => name.includes("["));

      expect(indexed.length).toBeGreaterThan(0);
      expect(indexed.every((name) => /\[\d+\]$/.test(name))).toBe(true);
    });
  }, 30_000);

  test("sets, appends, and unsets options through the handle", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = (await server.snapshot()).sessions.one();

      await session.setOption("status-left", "A");
      expect((await session.showOptions()).get("status-left")).toBe("A");

      await session.setOption("status-left", "B", { append: true });
      expect((await session.showOptions()).get("status-left")).toBe("AB");

      await session.unsetOption("status-left");
      // Unset falls back to what the session inherits, not to the set value.
      expect((await session.showOptions()).get("status-left")).not.toBe("AB");
    });
  }, 30_000);

  test("sets and unsets hooks at session and server scope", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = (await server.snapshot()).sessions.one();

      await session.setHook("after-new-window", "display-message hooked");
      const sessionHooks = await session.showHooks();
      expect([...sessionHooks.keys()].some((name) => name.startsWith("after-new-window"))).toBe(
        true,
      );

      await server.setHook("after-kill-pane", "display-message global");
      const globalHooks = await server.showHooks();
      expect([...globalHooks.keys()].some((name) => name.startsWith("after-kill-pane"))).toBe(true);

      await session.unsetHook("after-new-window");
      const afterUnset = await session.showHooks();
      expect([...afterUnset.keys()].some((name) => name.startsWith("after-new-window"))).toBe(
        false,
      );
    });
  }, 30_000);

  test("rejects an unknown option with a tmux-sourced error", async () => {
    await withServer(async (fixture) => {
      await expect(serverFor(fixture).setOption("definitely-not-an-option", "1")).rejects.toThrow(
        /set-option failed/,
      );
    });
  }, 30_000);
});
