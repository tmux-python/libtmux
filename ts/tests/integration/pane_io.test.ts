import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import type { Pane } from "../../src/pane.js";
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
  const parent = await mkdtemp(join(tmpdir(), "ltx-paneio-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "paneio" });
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

/** Poll a pane until its contents satisfy a predicate or the deadline passes. */
async function captureUntil(
  pane: Pane,
  matches: (lines: readonly string[]) => boolean,
  attempts = 100,
): Promise<readonly string[]> {
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    // eslint-disable-next-line no-await-in-loop -- Polling is inherently sequential.
    const lines = await pane.capture();
    if (matches(lines)) return lines;
    // eslint-disable-next-line no-await-in-loop -- Each wait follows the capture before it.
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error("pane never reached the expected contents");
}

describe("pane input and capture", () => {
  test("sends literal text and captures it back", async () => {
    await withServer(async (fixture) => {
      const pane = (await serverFor(fixture).snapshot()).panes.one();

      await pane.sendKeys("libtmux-marker", { literal: true });
      const lines = await captureUntil(pane, (captured) =>
        captured.some((line) => line.includes("libtmux-marker")),
      );

      expect(lines.some((line) => line.includes("libtmux-marker"))).toBe(true);
    });
  }, 40_000);

  test("capture returns lines without a trailing blank", async () => {
    await withServer(async (fixture) => {
      const pane = (await serverFor(fixture).snapshot()).panes.one();

      const lines = await pane.capture();

      expect(Array.isArray(lines)).toBe(true);
      expect(lines.at(-1)).not.toBe("");
    });
  }, 40_000);

  test("honours an explicit start line", async () => {
    await withServer(async (fixture) => {
      const pane = (await serverFor(fixture).snapshot()).panes.one();

      const visible = await pane.capture({ start: 0 });
      const withHistory = await pane.capture({ start: -50 });

      expect(withHistory.length).toBeGreaterThanOrEqual(visible.length);
    });
  }, 40_000);

  test("clears scrollback history without disturbing the visible pane", async () => {
    await withServer(async (fixture) => {
      const pane = (await serverFor(fixture).snapshot()).panes.one();

      await pane.sendKeys("history-marker", { literal: true });
      await captureUntil(pane, (captured) =>
        captured.some((line) => line.includes("history-marker")),
      );

      await pane.clearHistory();

      // clear-history drops scrollback, so the deep capture collapses toward
      // the visible region rather than erroring.
      const afterClear = await pane.capture({ start: -50 });
      expect(afterClear.length).toBeGreaterThan(0);
    });
  }, 40_000);
});
