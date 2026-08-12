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
import { buildWorkspace } from "./builder.js";
import { parseWorkspace } from "./config.js";

function serverFor(fixture: TestServer): Server {
  return new Server({
    environment: fixture.controllerEnvironment,
    socketPath: fixture.socketPath,
    tmuxBin: fixture.tmuxExecutable,
  });
}

async function withServer(body: (fixture: TestServer) => Promise<void>): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-workspace-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "ws" });
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

const WORKSPACE = `
session_name: project
windows:
  - window_name: editor
    panes:
      - shell_command: "true"
      - shell_command: "true"
  - window_name: server
    options:
      main-pane-width: "80"
    panes:
      - "true"
`;

describe("workspace builder", () => {
  test("parses a tmuxp-shaped workspace", () => {
    const workspace = parseWorkspace(WORKSPACE);

    expect(workspace.session_name).toBe("project");
    expect(workspace.windows).toHaveLength(2);
    expect(workspace.windows[0]?.window_name).toBe("editor");
    expect(workspace.windows[1]?.panes).toHaveLength(1);
  });

  test("rejects a workspace missing its session name", () => {
    expect(() => parseWorkspace("windows: []")).toThrow();
  });

  test("rejects a YAML-coerced boolean where a shell command belongs", () => {
    // YAML turns bare true/yes/on into booleans, so an unquoted command is
    // rejected rather than silently coerced back into a string.
    expect(() => parseWorkspace("session_name: x\nwindows:\n  - panes:\n      - true\n")).toThrow();
  });

  test("builds the described session without a stray leading window", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = await buildWorkspace(server, parseWorkspace(WORKSPACE));

      expect(session.name).toBe("project");

      const snapshot = await server.snapshot();
      const windows = snapshot.windows.filter((window) => window.sessionId === session.id);

      // Exactly the two described windows: the first was adopted, not created.
      expect(windows.length).toBe(2);
      expect(windows.toArray().map((window) => window.name)).toEqual(["editor", "server"]);

      expect(snapshot.panes.count({ window: { is: { name: "editor" } } })).toBe(2);
      expect(snapshot.panes.count({ window: { is: { name: "server" } } })).toBe(1);
    });
  }, 60_000);

  test("applies window options from the workspace", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const session = await buildWorkspace(server, parseWorkspace(WORKSPACE));
      const snapshot = await server.snapshot();
      const server_window = snapshot.windows
        .filter((window) => window.sessionId === session.id)
        .where({ name: "server" })
        .one();

      expect((await server_window.showOptions()).get("main-pane-width")).toBe("80");
    });
  }, 60_000);
});
