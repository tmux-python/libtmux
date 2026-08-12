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
import type { TmuxEvent, TmuxEventStream } from "../../src/types.js";

function serverFor(fixture: TestServer): Server {
  return new Server({
    environment: fixture.controllerEnvironment,
    socketPath: fixture.socketPath,
    tmuxBin: fixture.tmuxExecutable,
  });
}

async function withServer(body: (fixture: TestServer) => Promise<void>): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-watch-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "watch" });
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

/** Collect events until `want` matches one, or the bound elapses. */
async function until(
  events: TmuxEventStream,
  want: (event: TmuxEvent) => boolean,
  boundMs = 15_000,
): Promise<TmuxEvent> {
  const deadline = setTimeout(() => void events.close(), boundMs);
  try {
    for await (const event of events) {
      if (want(event)) return event;
    }
  } finally {
    clearTimeout(deadline);
  }
  throw new Error("the watched event never arrived");
}

describe("Server.watch", () => {
  test("reports a window opening on the server it is attached to", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const events = server.watch();

      const arrived = until(events, (event) => event.kind === "window-add");
      // The stream has to be listening before the change, which is the whole
      // difference between watching and polling.
      await new Promise((resolve) => setTimeout(resolve, 250));
      await fixture.executeText(["new-window", "-d", "-t", "watch:"]);

      expect((await arrived).kind).toBe("window-add");
    });
  }, 60_000);

  test("reports a window being renamed, with the new name", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const events = server.watch();

      const arrived = until(events, (event) => event.kind === "window-renamed");
      await new Promise((resolve) => setTimeout(resolve, 250));
      await fixture.executeText(["rename-window", "-t", "watch:", "renamed-by-test"]);

      const event = await arrived;
      if (event.kind !== "window-renamed") throw new Error("expected window-renamed");
      expect(event.name).toBe("renamed-by-test");
      expect(event.windowId.startsWith("@")).toBe(true);
    });
  }, 60_000);

  test("ends the stream and the tmux process when disposed", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const events = server.watch();
      const drained = (async () => {
        let seen = 0;
        for await (const _event of events) seen += 1;
        return seen;
      })();

      await new Promise((resolve) => setTimeout(resolve, 250));
      await events.close();

      // The loop terminating is the assertion: disposal ends iteration rather
      // than leaving the consumer awaiting an event that will never arrive.
      expect(await drained).toBeGreaterThanOrEqual(0);
      expect(events.dropped).toBe(0);
    });
  }, 60_000);

  test("refuses a second iteration of the same stream", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const events = server.watch();
      try {
        for await (const _event of events) break;

        await expect(
          (async () => {
            for await (const _event of events) break;
          })(),
        ).rejects.toThrow(/iterated once/u);
      } finally {
        await events.close();
      }
    });
  }, 60_000);

  test("ends the connection through the async disposal protocol", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const events = server.watch();
      const drained = (async () => {
        for await (const _event of events) void _event;
      })();

      // `await using` compiles to exactly this call; tests/types/watch.test.ts
      // pins that the syntax itself type-checks for a consumer.
      await events[Symbol.asyncDispose]();

      await drained;
      expect(events.dropped).toBe(0);
    });
  }, 60_000);

  test("rejects a buffer size that cannot hold an event", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      expect(() => server.watch({ bufferSize: 0 })).toThrow(/positive integer/u);
      expect(() => server.watch({ bufferSize: 1.5 })).toThrow(/positive integer/u);
    });
  }, 60_000);
});
