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
import { TmuxCommandError } from "../../src/exc.js";
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

      expect(expanded[0]).toBe(pane.id);
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
      const pane = source.panes.one();

      await pane.joinTo(target.id);

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
        TMUX_PANE: pane.id,
      });

      expect(session.id).toBe(pane.sessionId);
      expect(session.name).toBe(fixture.sessionName);
    });
  }, 40_000);

  test("enters and leaves copy mode", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const pane = (await server.snapshot()).panes.one();

      await pane.enterCopyMode();
      await pane.refresh();
      expect(pane.inMode).toBe("1");

      await pane.exitCopyMode();
      await pane.refresh();
      expect(pane.inMode).toBe("0");
    });
  }, 40_000);

  test("reports a tmux failure as structured fields, not a formatted string", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const pane = (await server.snapshot()).panes.one();

      const error = await pane
        .sendKeys("x", { enter: false })
        .then(() => undefined)
        .catch((thrown: unknown) => thrown);
      expect(error).toBeUndefined();

      const failure = await server
        .setOption("definitely-not-an-option", "1")
        .then(() => undefined)
        .catch((thrown: unknown) => thrown);

      expect(failure).toBeInstanceOf(TmuxCommandError);
      const typed = failure as TmuxCommandError;
      expect(typed.args[0]).toBe("set-option");
      expect(typed.exitCode).not.toBe(0);
      expect(typed.stderr.length).toBeGreaterThan(0);
      expect(typed.stderrIncludes("definitely-not-an-option")).toBe(true);
      // The parts stay addressable instead of being baked into the message.
      expect(Object.isFrozen(typed.stderr)).toBe(true);
    });
  }, 40_000);

  test("carries the addressed target on a failing command", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);

      const pane = (await server.snapshot()).panes.one();
      await pane.kill();

      const failure = await pane
        .capture()
        .then(() => undefined)
        .catch((thrown: unknown) => thrown);

      expect(failure).toBeInstanceOf(TmuxCommandError);
      expect((failure as TmuxCommandError).target).toBe(pane.id);
    });
  }, 40_000);
});
