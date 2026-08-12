import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import { ControlMode } from "../../src/_internal/test/control_mode.js";
import {
  prepareRunRoot,
  reapOwnedRunRoot,
  runWithCleanup,
} from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";
import type { Pane } from "../../src/pane.js";
import { Server } from "../../src/server.js";

function serverFor(fixture: TestServer): Server {
  return new Server({
    environment: fixture.controllerEnvironment,
    socketPath: fixture.socketPath,
    tmuxBin: fixture.tmuxExecutable,
  });
}

/** Interactive commands are client-owned, so each runs with a real client attached. */
async function withAttachedPane(
  body: (pane: Pane, server: Server) => Promise<void>,
): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-interactive-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "inter" });
        await runWithCleanup(
          async () => {
            const control = await ControlMode.open({
              server: fixture,
              targetSession: fixture.sessionId,
            });
            try {
              const server = serverFor(fixture);
              await body((await server.snapshot()).panes.one(), server);
            } finally {
              await control.dispose();
            }
          },
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

describe("interactive commands", () => {
  test("opens a popup that runs a command and closes", async () => {
    await withAttachedPane(async (pane) => {
      await expect(pane.displayPopup("true")).resolves.toBeUndefined();
    });
  }, 40_000);

  test("enters the chooser modes and leaves the pane in a mode", async () => {
    await withAttachedPane(async (pane) => {
      await pane.chooseTree({ sessionsOnly: true });
      await pane.refresh();
      expect(pane.inMode).toBe("1");

      await pane.exitCopyMode();
      await pane.chooseBuffer();
      await pane.refresh();
      expect(pane.inMode).toBe("1");
    });
  }, 40_000);

  test("sends the prefix key without erroring", async () => {
    await withAttachedPane(async (pane) => {
      await expect(pane.sendPrefix()).resolves.toBeUndefined();
    });
  }, 40_000);

  test("opens find-window and customize-mode", async () => {
    await withAttachedPane(async (pane) => {
      await pane.findWindow("inter");
      await pane.exitCopyMode();
      await expect(pane.customizeMode()).resolves.toBeUndefined();
    });
  }, 40_000);
});
