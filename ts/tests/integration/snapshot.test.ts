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
import { ControlMode } from "../../src/_internal/test/control_mode.js";
import { Server } from "../../src/server.js";

function serverFor(fixture: TestServer): Server {
  return new Server({
    environment: fixture.controllerEnvironment,
    socketPath: fixture.socketPath,
    tmuxBin: fixture.tmuxExecutable,
  });
}

async function withServer(body: (fixture: TestServer) => Promise<void>): Promise<void> {
  const parent = await mkdtemp(join(tmpdir(), "ltx-snapshot-"));
  const published = process.env.LIBTMUX_TEST_RUN_ROOT;
  const runRoot = published ?? join(parent, "run, root");
  if (published === undefined) await prepareRunRoot(runRoot);
  let done = false;
  try {
    await runWithCleanup(
      async () => {
        const fixture = await TestServer.create({ runRoot, sessionName: "snap" });
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

describe("Server.snapshot", () => {
  test("resolves every session as an ordered Selection", async () => {
    await withServer(async (fixture) => {
      await fixture.executeText(["new-session", "-d", "-s", "other"]);
      const snapshot = await serverFor(fixture).snapshot();

      expect(snapshot.sessions.length).toBe(2);
      expect(new Set(snapshot.sessions.toArray().map((session) => session.session_name))).toEqual(
        new Set(["other", fixture.sessionName]),
      );
    });
  }, 30_000);

  test("filters declaratively and by predicate without further tmux calls", async () => {
    await withServer(async (fixture) => {
      await fixture.executeText(["new-session", "-d", "-s", "other"]);
      const snapshot = await serverFor(fixture).snapshot();

      expect(snapshot.sessions.where({ name: "other" }).one().session_name).toBe("other");
      expect(snapshot.sessions.exists({ name: "absent" })).toBe(false);
      expect(snapshot.sessions.count({ name: "other" })).toBe(1);
      expect(snapshot.sessions.oneOrUndefined({ name: "absent" })).toBeUndefined();
      expect(snapshot.sessions.filter((session) => session.session_name === "other").length).toBe(
        1,
      );
    });
  }, 30_000);

  test("returns an immutable value, so an earlier snapshot never changes", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      const before = await server.snapshot();
      await fixture.executeText(["new-session", "-d", "-s", "later"]);
      const after = await server.snapshot();

      expect(before.sessions.length).toBe(1);
      expect(after.sessions.length).toBe(2);
      expect(before.sessions.length).toBe(1);
    });
  }, 30_000);

  test("iterates fresh and is not an Array", async () => {
    await withServer(async (fixture) => {
      const snapshot = await serverFor(fixture).snapshot();

      expect(Array.isArray(snapshot.sessions)).toBe(false);
      expect([...snapshot.sessions]).toHaveLength(1);
      expect([...snapshot.sessions]).toHaveLength(1);
      expect(snapshot.sessions.at(0)?.session_name).toBe(fixture.sessionName);
    });
  }, 30_000);

  test("resolves windows, panes, and clients from the same acquisition", async () => {
    await withServer(async (fixture) => {
      await fixture.executeText(["new-window", "-d", "-t", fixture.sessionName, "-n", "editor"]);
      await fixture.executeText(["split-window", "-d", "-t", `${fixture.sessionName}:editor`]);

      const snapshot = await serverFor(fixture).snapshot();

      expect(snapshot.windows.length).toBe(2);
      expect(snapshot.panes.length).toBe(3);
      expect(snapshot.windows.count({ name: "editor" })).toBe(1);
      expect(snapshot.windows.where({ name: "editor" }).one().window_name).toBe("editor");
      expect(snapshot.panes.count({ window: { is: { name: "editor" } } })).toBe(2);
      // No client is attached to a detached fixture server.
      expect(snapshot.clients.length).toBe(0);
    });
  }, 30_000);

  test("exposes collection accessors that each acquire their own instant", async () => {
    await withServer(async (fixture) => {
      const server = serverFor(fixture);
      await fixture.executeText(["new-window", "-d", "-t", fixture.sessionName, "-n", "editor"]);

      const sessions = await server.sessions();
      expect(sessions.length).toBe(1);
      expect(sessions.one().session_name).toBe(fixture.sessionName);

      expect((await server.windows()).count({ name: "editor" })).toBe(1);
      expect((await server.panes()).length).toBe(2);
      expect((await server.clients()).length).toBe(0);

      await fixture.executeText(["new-session", "-d", "-s", "fresh"]);
      expect((await server.sessions()).length).toBe(2);
      // The earlier Selection was captured at its own instant.
      expect(sessions.length).toBe(1);
    });
  }, 30_000);

  test("resolves session relations locally from the handle's own graph", async () => {
    await withServer(async (fixture) => {
      await fixture.executeText(["new-session", "-d", "-s", "other"]);
      await fixture.executeText(["new-window", "-d", "-t", fixture.sessionName, "-n", "editor"]);
      await fixture.executeText(["split-window", "-d", "-t", `${fixture.sessionName}:editor`]);

      const snapshot = await serverFor(fixture).snapshot();
      const session = snapshot.sessions.where({ name: fixture.sessionName }).one();
      const other = snapshot.sessions.where({ name: "other" }).one();

      expect(session.windows.length).toBe(2);
      expect(session.panes.length).toBe(3);
      expect(session.windows.count({ name: "editor" })).toBe(1);

      // A sibling session sees only its own topology.
      expect(other.windows.length).toBe(1);
      expect(other.panes.length).toBe(1);
    });
  }, 30_000);

  test("resolves window and pane relations, keeping linked placements apart", async () => {
    await withServer(async (fixture) => {
      await fixture.executeText(["new-session", "-d", "-s", "other"]);
      const created = await fixture.executeText([
        "new-window",
        "-d",
        "-P",
        "-F",
        "#{window_id}",
        "-t",
        fixture.sessionName,
        "-n",
        "shared",
      ]);
      const windowId = created.stdout[0];
      if (windowId === undefined) throw new Error("tmux did not return the created window id");
      await fixture.executeText(["split-window", "-d", "-t", windowId]);
      await fixture.executeText(["link-window", "-s", windowId, "-t", "other:9"]);

      const snapshot = await serverFor(fixture).snapshot();
      const placements = snapshot.windows.where({ name: "shared" }).toArray();
      expect(placements).toHaveLength(2);

      // Both placements show the same two panes, each via its own winlink.
      await Promise.all(
        placements.map(async (placement) => {
          expect(placement.panes.length).toBe(2);
          expect(placement.session?.session_id).toBe(placement.session_id);
          expect(placement.linkedSessions.length).toBe(2);
        }),
      );

      const pane = placements[0]!.panes.first();
      expect(pane).toBeDefined();
      expect(pane!.window?.window_id).toBe(windowId);
      expect(pane!.session?.session_id).toBe(pane!.session_id);
    });
  }, 30_000);

  test("resolves an attached client back to its session, window, and pane", async () => {
    await withServer(async (fixture) => {
      const control = await ControlMode.open({
        server: fixture,
        targetSession: fixture.sessionId,
      });
      try {
        const snapshot = await serverFor(fixture).snapshot();
        expect(snapshot.clients.length).toBe(1);

        const client = snapshot.clients.one();
        expect(client.session?.session_id).toBe(fixture.sessionId);

        const window = client.window;
        expect(window?.session_id).toBe(fixture.sessionId);

        // A client's own ids are nullable because a client need not be
        // attached; a resolved pane's are not.
        const clientPaneId = client.pane_id;
        expect(clientPaneId).not.toBeNull();
        const pane = client.pane;
        expect(pane?.pane_id).toBe(clientPaneId ?? undefined);
        expect(pane?.window_id).toBe(window?.window_id);
      } finally {
        await control.dispose();
      }
    });
  }, 30_000);

  test("keeps relation criteria resolvable for a window linked into two sessions", async () => {
    await withServer(async (fixture) => {
      await fixture.executeText(["new-session", "-d", "-s", "other"]);
      const created = await fixture.executeText([
        "new-window",
        "-d",
        "-P",
        "-F",
        "#{window_id}",
        "-t",
        fixture.sessionName,
        "-n",
        "shared",
      ]);
      const windowId = created.stdout[0];
      if (windowId === undefined) throw new Error("tmux did not return the created window id");
      await fixture.executeText(["link-window", "-s", windowId, "-t", "other:9"]);

      const snapshot = await serverFor(fixture).snapshot();

      expect(snapshot.sessions.length).toBe(2);
      expect(snapshot.sessions.count({ windows: { some: { name: "shared" } } })).toBe(2);
      expect(snapshot.windows.count({ name: "shared" })).toBe(2);
      expect(snapshot.windows.where({ name: "shared" }).first()?.window_id).toBe(windowId);
    });
  }, 30_000);
});
