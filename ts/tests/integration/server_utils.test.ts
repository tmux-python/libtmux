import { mkdtemp, rm, writeFile } from "node:fs/promises";
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

async function withServer(
  body: (fixture: TestServer, parent: string) => Promise<void>,
): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-srvutil-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "util" });
        await runWithCleanup(
          () => body(fixture, parent),
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

describe("server utilities", () => {
  test("answers has-session without treating absence as failure", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);

      expect(await server.hasSession(fixture.sessionName)).toBe(true);
      expect(await server.hasSession("definitely-absent")).toBe(false);
    });
  }, 40_000);

  test("round-trips a named paste buffer and deletes it", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);

      await server.setBuffer("greeting", "hello buffer");
      expect(await server.showBuffer("greeting")).toEqual(["hello buffer"]);
      expect(await server.listBuffers()).toContain("greeting");

      await server.deleteBuffer("greeting");
      expect(await server.listBuffers()).not.toContain("greeting");
    });
  }, 40_000);

  test("lists tmux commands", async () => {
    await withServer(async (fixture) => {
      const commands = await serverFor(fixture).listCommands();

      expect(commands).toContain("new-session");
      expect(commands).toContain("list-panes");
    });
  }, 40_000);

  test("sources a config file that changes a server option", async () => {
    await withServer(async (fixture, parent) => {
      const server = serverFor(fixture);
      const config = join(parent, "extra.conf");
      await writeFile(config, "set-option -s history-file /tmp/ltx-sourced\n");

      await server.sourceFile(config);

      expect((await server.showOptions()).get("history-file")).toBe("/tmp/ltx-sourced");
    });
  }, 40_000);

  test("renames a session and selects windows relatively", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = (await server.snapshot()).sessions.one();
      await session.newWindow({ name: "second" });

      await session.rename("renamed");
      expect((await server.snapshot()).sessions.count({ name: "renamed" })).toBe(1);

      await session.selectWindow("next");
      await session.selectWindow("previous");
      await session.selectWindow("last");

      // Relative selection is accepted and leaves exactly one active window.
      const active = (await server.snapshot()).windows.filter(
        (window) => window.window_active === "1",
      );
      expect(active.length).toBe(1);
    });
  }, 40_000);
});
