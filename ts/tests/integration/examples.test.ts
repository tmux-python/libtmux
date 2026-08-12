import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import { quickstart } from "../../examples/quickstart.js";
import {
  prepareRunRoot,
  reapOwnedRunRoot,
  runWithCleanup,
} from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";
import { Server } from "../../src/server.js";

async function withServer(body: (fixture: TestServer) => Promise<void>): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-examples-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "examples" });
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

describe("documented examples", () => {
  test("the quickstart runs end to end against real tmux", async () => {
    await withServer(async (fixture) => {
      const server = new Server({
        environment: fixture.controllerEnvironment,
        socketPath: fixture.socketPath,
        tmuxBin: fixture.tmuxExecutable,
      });

      const snapshot = await quickstart(server);

      expect(snapshot.sessions.count({ name: "quickstart" })).toBe(1);
      expect(snapshot.windows.count({ name: "editor" })).toBe(1);
      expect(snapshot.panes.count({ window: { is: { name: "editor" } } })).toBe(2);
    });
  }, 60_000);
});
