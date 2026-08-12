import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import { createTmuxMcpServer } from "./server.js";
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
  const parent = await mkdtemp(join(tmpdir(), "ltx-mcp-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "mcp" });
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

describe("MCP consumer", () => {
  test("registers the tmux tool surface", async () => {
    await withServer(async (fixture) => {
      const mcp = createTmuxMcpServer(serverFor(fixture));

      expect(mcp).toBeDefined();
      expect(typeof mcp.connect).toBe("function");
    });
  }, 40_000);

  test("drives real tmux through the library it consumes", async () => {
    await withServer(async (fixture) => {
      const tmux = serverFor(fixture);
      createTmuxMcpServer(tmux);

      // The same calls the tools make, exercised directly against real tmux.
      const snapshot = await tmux.snapshot();
      const pane = snapshot.panes.one();
      await pane.sendKeys("mcp-marker", { literal: true });

      let captured: readonly string[] = [];
      for (let attempt = 0; attempt < 100; attempt += 1) {
        // eslint-disable-next-line no-await-in-loop -- Polling is sequential.
        captured = await pane.capture();
        if (captured.some((line) => line.includes("mcp-marker"))) break;
        // eslint-disable-next-line no-await-in-loop -- Each wait follows its capture.
        await new Promise((resolve) => setTimeout(resolve, 20));
      }

      expect(captured.some((line) => line.includes("mcp-marker"))).toBe(true);

      const created = await tmux.newSession({ name: "from-mcp" });
      expect(created.session_name).toBe("from-mcp");
      expect((await tmux.snapshot()).sessions.count({ name: "from-mcp" })).toBe(1);
    });
  }, 40_000);
});
