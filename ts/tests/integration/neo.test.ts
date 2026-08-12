import { access, mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import type { ConnectionAlias, DaemonEpoch } from "../../src/common.js";
import { LibTmuxException, TmuxObjectDoesNotExist } from "../../src/exc.js";
import { executeGuardedFetch, executeGuardedList } from "../../src/_internal/codec/guard_codec.js";
import { LazyCapabilityBinding } from "../../src/_internal/runtime/capabilities.js";
import { TmuxConnection } from "../../src/_internal/runtime/connection.js";
import { ControlMode } from "../../src/_internal/test/control_mode.js";
import {
  prepareRunRoot,
  reapOwnedRunRoot,
  runWithCleanup,
} from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";
import { NodeSpawnTransport } from "../../src/_internal/transport/node_spawn_transport.js";
import type { CommandRequest, CommandTransport } from "../../src/_internal/transport/types.js";

interface QueryHarness {
  capabilities: LazyCapabilityBinding;
  connection: TmuxConnection;
  transport: CommandTransport;
}

function queryHarness(
  server: TestServer,
  socketPath = server.socketPath,
  observeRequest: (request: CommandRequest) => void = () => undefined,
): QueryHarness {
  const rawTransport = new NodeSpawnTransport({ terminationGraceMs: 100 });
  const transport: CommandTransport = {
    async execute(request) {
      observeRequest(request);
      await server.assertControllerCurrent();
      return rawTransport.execute(request);
    },
  };
  const connection = new TmuxConnection({
    environment: server.controllerEnvironment,
    executable: server.tmuxExecutable,
    socketPath,
  });
  const capabilities = new LazyCapabilityBinding({
    connection,
    connectionAlias: server.logicalSocketName as ConnectionAlias,
    getDaemonEpoch: () => 1 as DaemonEpoch,
    transport,
  });
  return { capabilities, connection, transport };
}

async function withTestServer(
  prefix: string,
  body: (server: TestServer, parent: string) => Promise<void>,
): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), prefix));
  const publishedRoot = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = publishedRoot ?? join(parent, "run, root");
  if (publishedRoot === undefined) await prepareRunRoot(runRoot);
  let cleanupComplete = false;
  try {
    await runWithCleanup(
      async () => {
        const server = await TestServer.create({ runRoot, sessionName: `${prefix}session` });
        await runWithCleanup(
          () => body(server, parent),
          () => server.dispose(),
        );
      },
      async () => {
        if (publishedRoot === undefined) await reapOwnedRunRoot(runRoot);
        cleanupComplete = true;
      },
    );
  } finally {
    if (cleanupComplete) await rm(parent, { force: true, recursive: true });
  }
}

describe("guarded neo integration", () => {
  test("lists and fetches complete rows with tmux winlink selection", async () => {
    await withTestServer("ltx5-neo-", async (server) => {
      const harness = queryHarness(server);
      const sessions = await executeGuardedList({
        ...harness,
        listCommand: "list-sessions",
      });

      expect(sessions).toHaveLength(1);
      expect(sessions[0]?.session_id).toBe(server.sessionId);
      expect(sessions[0]?.session_name).toBe(server.sessionName);
      expect(sessions[0]?.session_group).toBe("");

      const created = await server.executeText([
        "new-window",
        "-d",
        "-P",
        "-F",
        "#{window_id}\t#{window_index}",
        "-t",
        server.sessionId,
        "-n",
        "linked",
      ]);
      const [windowId, originalIndex] = created.stdout[0]?.split("\t") ?? [];
      if (windowId === undefined || originalIndex === undefined) {
        throw new Error("tmux did not return the created winlink identity");
      }
      const embeddedName = "alpha␞beta";
      await server.executeText(["rename-window", "-t", windowId, embeddedName]);

      const explicitlyTargeted = await executeGuardedFetch({
        ...harness,
        identityField: "window_id",
        identityValue: windowId,
        listCommand: "list-windows",
        listExtraArgs: ["-t", windowId],
      });
      expect(explicitlyTargeted.window_id).toBe(windowId);
      expect(explicitlyTargeted.window_name).toBe(embeddedName);

      await server.executeText(["link-window", "-s", windowId, "-t", `${server.sessionId}:5`]);
      await server.executeText(["select-window", "-t", `${server.sessionId}:5`]);

      const windows = await executeGuardedList({
        ...harness,
        listCommand: "list-windows",
        listExtraArgs: ["-t", server.sessionId],
      });
      expect(
        windows
          .filter(({ window_id }) => window_id === windowId)
          .map(({ window_name }) => window_name),
      ).toEqual([embeddedName, embeddedName]);

      const active = await executeGuardedFetch({
        ...harness,
        identityField: "window_id",
        identityValue: windowId,
        listCommand: "list-windows",
        listExtraArgs: ["-t", server.sessionId],
      });
      expect(active.window_index).toBe("5");

      await server.executeText(["select-window", "-t", `${server.sessionId}:0`]);
      const first = await executeGuardedFetch({
        ...harness,
        identityField: "window_id",
        identityValue: windowId,
        listCommand: "list-windows",
        listExtraArgs: ["-t", server.sessionId],
      });
      expect(first.window_index).toBe(originalIndex);
      expect(first.window_name).toBe(embeddedName);
    });
  }, 15_000);

  test("translates missing targets without swallowing other tmux failures", async () => {
    await withTestServer("ltx5-target-", async (server) => {
      const harness = queryHarness(server);

      await expect(
        executeGuardedFetch({
          ...harness,
          identityField: "pane_id",
          identityValue: "%99999",
          listCommand: "list-panes",
          listExtraArgs: ["-t", "%99999"],
        }),
      ).rejects.toBeInstanceOf(TmuxObjectDoesNotExist);

      try {
        await executeGuardedFetch({
          ...harness,
          identityField: "pane_id",
          identityValue: "%99999",
          listCommand: "list-panes",
          listExtraArgs: ["-Z"],
        });
        throw new Error("expected the invalid list command to fail");
      } catch (error) {
        expect(error).toBeInstanceOf(LibTmuxException);
        expect(error).not.toBeInstanceOf(TmuxObjectDoesNotExist);
      }
    });
  }, 15_000);

  test("validates real client names without requiring a sigil", async () => {
    await withTestServer("ltx5-client-", async (server) => {
      const harness = queryHarness(server);
      const control = await ControlMode.open({ server, targetSession: server.sessionId });
      try {
        const client = await executeGuardedFetch({
          ...harness,
          identityField: "client_name",
          identityValue: control.clientName,
          listCommand: "list-clients",
        });

        expect(client.client_name).toBe(control.clientName);
        expect(client.client_name?.startsWith("$")).toBe(false);
        expect(client.client_name?.startsWith("@")).toBe(false);
        expect(client.client_name?.startsWith("%")).toBe(false);
      } finally {
        await control.dispose();
      }
    });
  }, 15_000);

  test("probes a missing socket with no-autostart and creates no daemon socket", async () => {
    await withTestServer("ltx5-no-start-", async (server, parent) => {
      const missingSocket = join(parent, "missing.sock");
      const requests: CommandRequest[] = [];
      const harness = queryHarness(server, missingSocket, (request) => requests.push(request));

      let probeError: unknown;
      try {
        await harness.capabilities.bind();
      } catch (error) {
        probeError = error;
      }
      expect(requests).toHaveLength(1);
      expect(requests[0]?.args).toEqual([
        "-N",
        `-S${missingSocket}`,
        "display-message",
        "-p",
        "#{version}",
      ]);
      expect(probeError).toBeInstanceOf(LibTmuxException);
      expect((probeError as Error).message).toContain("tmux version probe failed");
      await expect(access(missingSocket)).rejects.toMatchObject({ code: "ENOENT" });
    });
  }, 15_000);
});
