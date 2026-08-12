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
import { Session } from "../../src/session.js";

function serverFor(fixture: TestServer): Server {
  return new Server({
    environment: fixture.controllerEnvironment,
    socketPath: fixture.socketPath,
    tmuxBin: fixture.tmuxExecutable,
  });
}

async function withServer(body: (fixture: TestServer) => Promise<void>): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-shell-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "shell" });
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

describe("shell execution and pane movement", () => {
  test("runs a shell command and returns its output", async () => {
    await withServer(async (fixture) => {
      const output = await serverFor(fixture).runShell("echo libtmux-run");

      expect(output.join("\n")).toContain("libtmux-run");
    });
  }, 40_000);

  test("expands a tmux format through display-message", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const pane = (await server.snapshot()).panes.one();

      const expanded = await pane.displayMessage("#{pane_id}");

      expect(expanded[0]).toBe(pane.pane_id ?? "");
    });
  }, 40_000);

  test("takes the else branch when an if-shell condition fails", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);

      await server.ifShell("false", "set-option -s history-file /tmp/ltx-then", {
        otherwise: "set-option -s history-file /tmp/ltx-else",
      });

      expect((await server.showOptions()).get("history-file")).toBe("/tmp/ltx-else");
    });
  }, 40_000);

  test("breaks a pane out into its own window", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const window = (await server.snapshot()).windows.one();
      const created = await window.split();

      await created.breakOut("broken-out");

      const after = await server.snapshot();
      expect(after.windows.count({ name: "broken-out" })).toBe(1);
      expect(after.panes.count({ window: { is: { name: "broken-out" } } })).toBe(1);
    });
  }, 40_000);

  test("joins a pane back into another window", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = (await server.snapshot()).sessions.one();
      const target = await session.newWindow({ name: "target" });
      const source = await session.newWindow({ name: "source" });
      const pane = (await source.panes()).one();

      await pane.joinTo(target.window_id ?? "");

      const after = await server.snapshot();
      expect(after.panes.count({ window: { is: { name: "target" } } })).toBe(2);
    });
  }, 40_000);

  test("resolves the current session from the tmux environment", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const pane = (await server.snapshot()).panes.one();
      const socketPath = fixture.socketPath;

      const session = await Session.fromEnv({
        ...fixture.controllerEnvironment,
        TMUX: `${socketPath},1,0`,
        TMUX_PANE: pane.pane_id ?? "",
      });

      expect(session.session_id).toBe(pane.session_id);
      expect(session.session_name).toBe(fixture.sessionName);
    });
  }, 40_000);

  test("enters and leaves copy mode", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const pane = (await server.snapshot()).panes.one();

      await pane.enterCopyMode();
      await pane.refresh();
      expect(pane.pane_in_mode).toBe("1");

      await pane.exitCopyMode();
      await pane.refresh();
      expect(pane.pane_in_mode).toBe("0");
    });
  }, 40_000);
});
