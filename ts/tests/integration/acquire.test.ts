import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import { acquireServerGraph } from "../../src/_internal/operations/acquire.js";
import { createRuntimeContext } from "../../src/_internal/runtime/context.js";
import type { RuntimeContext } from "../../src/_internal/runtime/context.js";
import { TmuxConnection } from "../../src/_internal/runtime/connection.js";
import {
  prepareRunRoot,
  reapOwnedRunRoot,
  runWithCleanup,
} from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";
import { NodeSpawnTransport } from "../../src/_internal/transport/node_spawn_transport.js";
import type { CommandRequest, CommandTransport } from "../../src/_internal/transport/types.js";
import type { ConnectionAlias, DaemonEpoch } from "../../src/common.js";

function runtimeFor(
  server: TestServer,
  observe: (request: CommandRequest) => void = () => undefined,
): RuntimeContext {
  const raw = new NodeSpawnTransport({ terminationGraceMs: 100 });
  const transport: CommandTransport = {
    execute(request) {
      observe(request);
      return raw.execute(request);
    },
  };
  return createRuntimeContext({
    connection: new TmuxConnection({
      environment: server.controllerEnvironment,
      executable: server.tmuxExecutable,
      socketPath: server.socketPath,
    }),
    connectionAlias: server.logicalSocketName as ConnectionAlias,
    daemonEpoch: 0 as DaemonEpoch,
    transport,
  });
}

async function withServer(body: (server: TestServer) => Promise<void>): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-acquire-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const server = await TestServer.create({ runRoot, sessionName: "acquire" });
        await runWithCleanup(
          () => body(server),
          () => server.dispose(),
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

describe("server graph acquisition", () => {
  test("builds the whole session, window, and pane graph", async () => {
    await withServer(async (server) => {
      await server.executeText(["new-window", "-d", "-t", server.sessionName, "-n", "editor"]);
      await server.executeText(["split-window", "-d", "-t", `${server.sessionName}:editor`]);

      const graph = await acquireServerGraph(runtimeFor(server));

      expect(graph.sessions.map(({ ref }) => String(ref.id))).toEqual([server.sessionId]);
      expect(graph.windows.length).toBe(2);
      expect(graph.panes.length).toBe(3);
    });
  }, 30_000);

  test("gives every model its own records so selections have members", async () => {
    await withServer(async (server) => {
      await server.executeText(["new-window", "-d", "-t", server.sessionName, "-n", "editor"]);

      const graph = await acquireServerGraph(runtimeFor(server));
      const models = graph.records.map(({ model }) => model);

      expect(models.filter((model) => model === "session")).toHaveLength(1);
      expect(models.filter((model) => model === "window")).toHaveLength(2);
      expect(models.filter((model) => model === "pane")).toHaveLength(2);
    });
  }, 30_000);

  test("issues one listing per model regardless of topology", async () => {
    await withServer(async (server) => {
      for (const name of ["editor", "shell", "logs"]) {
        // eslint-disable-next-line no-await-in-loop -- tmux assigns window indexes in creation order, so these cannot race.
        await server.executeText(["new-window", "-d", "-t", server.sessionName, "-n", name]);
      }

      const listed: string[] = [];
      const graph = await acquireServerGraph(
        runtimeFor(server, (request) => {
          const subcommand = request.args.find((arg) => arg.startsWith("list-"));
          if (subcommand !== undefined) listed.push(subcommand);
        }),
      );

      expect(listed.toSorted()).toEqual([
        "list-clients",
        "list-panes",
        "list-sessions",
        "list-windows",
      ]);
      expect(graph.windows.length).toBe(4);
    });
  }, 30_000);

  test("keeps one window entity with two winlinks when a window is linked twice", async () => {
    await withServer(async (server) => {
      await server.executeText(["new-session", "-d", "-s", "other"]);
      const created = await server.executeText([
        "new-window",
        "-d",
        "-P",
        "-F",
        "#{window_id}",
        "-t",
        server.sessionName,
        "-n",
        "shared",
      ]);
      const windowId = created.stdout[0];
      if (windowId === undefined) throw new Error("tmux did not return the created window id");
      await server.executeText(["link-window", "-s", windowId, "-t", "other:9"]);

      const graph = await acquireServerGraph(runtimeFor(server));

      expect(graph.windows.filter(({ ref }) => ref.id === windowId)).toHaveLength(1);
      expect(graph.winlinks.filter(({ ref }) => ref.windowId === windowId)).toHaveLength(2);
    });
  }, 30_000);
});
