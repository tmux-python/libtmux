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
  const parent = await mkdtemp(join(tmpdir(), "ltx-topology-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "topo" });
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

describe("window and pane topology", () => {
  test("renames a window", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const window = (await server.snapshot()).windows.one();

      await window.rename("renamed");

      expect((await server.snapshot()).windows.count({ name: "renamed" })).toBe(1);
    });
  }, 40_000);

  test("links a window into a second session and unlinks one placement", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const other = await server.newSession({ name: "other" });
      const window = (await server.snapshot()).windows
        .filter((candidate) => candidate.sessionName === fixture.sessionName)
        .one();

      await window.link({ index: 9, session: "other" });

      const linked = (await server.snapshot()).windows.filter(
        (candidate) => candidate.id === window.id,
      );
      expect(linked.length).toBe(2);

      // Unlinking the second placement leaves the original intact.
      const placement = linked.filter((candidate) => candidate.sessionId === other.id).one();
      await placement.unlink();

      const afterUnlink = (await server.snapshot()).windows.filter(
        (candidate) => candidate.id === window.id,
      );
      expect(afterUnlink.length).toBe(1);
    });
  }, 40_000);

  test("moves a window to an explicit index", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const window = (await server.snapshot()).windows.one();

      await window.move({ index: 7, session: fixture.sessionName });

      const moved = (await server.snapshot()).windows
        .filter((candidate) => candidate.id === window.id)
        .one();
      expect(moved.index).toBe("7");
    });
  }, 40_000);

  test("applies a layout and resizes a pane", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const window = (await server.snapshot()).windows.one();
      await window.split();

      await window.selectLayout("main-vertical");
      const panes = (await server.snapshot()).panes.toArray();
      expect(panes.length).toBe(2);

      const first = panes[0];
      if (first === undefined) throw new Error("expected a pane to resize");
      await first.resize({ width: 40 });

      const resized = (await server.snapshot()).panes
        .filter((candidate) => candidate.id === first.id)
        .one();
      expect(Number(resized.width)).toBeGreaterThan(0);
    });
  }, 40_000);

  test("swaps two windows", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = (await server.snapshot()).sessions.one();
      const second = await session.newWindow({ name: "second" });
      const first = (await server.snapshot()).windows
        .filter((candidate) => candidate.id !== second.id)
        .one();
      const firstIndex = first.index;
      const secondIndex = second.index;

      await first.swapWith(second);

      const after = await server.snapshot();
      expect(after.windows.filter((candidate) => candidate.id === first.id).one().index).toBe(
        secondIndex,
      );
      expect(after.windows.filter((candidate) => candidate.id === second.id).one().index).toBe(
        firstIndex,
      );
    });
  }, 40_000);
});
