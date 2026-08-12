import { describe, expect, test } from "bun:test";

import type { ConnectionAlias, DaemonEpoch } from "../../src/common.js";
import { LibTmuxException } from "../../src/exc.js";
import { TmuxConnection } from "../../src/_internal/runtime/connection.js";
import {
  deriveTmuxCapabilities,
  LazyCapabilityBinding,
} from "../../src/_internal/runtime/capabilities.js";
import type {
  CommandRequest,
  CommandTransport,
  RawCommandResult,
} from "../../src/_internal/transport/types.js";

const encoder = new TextEncoder();

function alias(value: string): ConnectionAlias {
  return value as ConnectionAlias;
}

function epoch(value: number): DaemonEpoch {
  return value as DaemonEpoch;
}

function resultFor(request: CommandRequest, version: string): RawCommandResult {
  return {
    cmd: Object.freeze([request.executable, ...request.args]),
    returncode: 0,
    signal: null,
    stderr: new Uint8Array(),
    stdout: encoder.encode(`${version}\n`),
  };
}

function deferred(): { promise: Promise<void>; resolve: () => void } {
  let resolve: (() => void) | undefined;
  const promise = new Promise<void>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return {
    promise,
    resolve() {
      resolve?.();
    },
  };
}

describe("tmux capabilities", () => {
  test("derives carrying format floors and an exact 3.7 break-pane quirk", () => {
    const base = { connectionAlias: alias("daemon-a"), daemonEpoch: epoch(1) };
    const v32a = deriveTmuxCapabilities({ ...base, rawVersion: "3.2a" });
    const v33 = deriveTmuxCapabilities({ ...base, rawVersion: "3.3" });
    const v37 = deriveTmuxCapabilities({ ...base, rawVersion: "3.7" });
    const v37a = deriveTmuxCapabilities({ ...base, rawVersion: "3.7a" });
    const v37b = deriveTmuxCapabilities({ ...base, rawVersion: "3.7b" });

    expect(v32a.formatFloor.paneDeadExit).toBe(false);
    expect(v33.formatFloor.paneDeadExit).toBe(true);
    expect(v37.formatFloor.pane37).toBe(true);
    expect(v37a.formatFloor.pane37).toBe(true);
    expect(v37b.formatFloor.pane37).toBe(true);
    expect(v37.quirks.breakPane37).toBe(true);
    expect(v37a.quirks.breakPane37).toBe(false);
    expect(v37b.quirks.breakPane37).toBe(false);
    expect(Object.isFrozen(v37)).toBe(true);
    expect(Object.isFrozen(v37.formatFloor)).toBe(true);
    expect(Object.isFrozen(v37.quirks)).toBe(true);
  });

  test("fingerprints version, connection alias, and daemon epoch", () => {
    const original = deriveTmuxCapabilities({
      connectionAlias: alias("daemon-a"),
      daemonEpoch: epoch(1),
      rawVersion: "3.7b",
    });
    const changedVersion = deriveTmuxCapabilities({
      connectionAlias: alias("daemon-a"),
      daemonEpoch: epoch(1),
      rawVersion: "3.7a",
    });
    const changedAlias = deriveTmuxCapabilities({
      connectionAlias: alias("daemon-b"),
      daemonEpoch: epoch(1),
      rawVersion: "3.7b",
    });
    const changedEpoch = deriveTmuxCapabilities({
      connectionAlias: alias("daemon-a"),
      daemonEpoch: epoch(2),
      rawVersion: "3.7b",
    });

    expect(
      new Set([
        original.fingerprint,
        changedVersion.fingerprint,
        changedAlias.fingerprint,
        changedEpoch.fingerprint,
      ]).size,
    ).toBe(4);
    expect(
      deriveTmuxCapabilities({
        connectionAlias: alias("daemon-a"),
        daemonEpoch: epoch(1),
        rawVersion: "3.7b",
      }).fingerprint,
    ).toBe(original.fingerprint);
  });

  test("binds lazily against the connected daemon and caches one epoch", async () => {
    const requests: CommandRequest[] = [];
    const transport: CommandTransport = {
      async execute(request) {
        requests.push(request);
        return resultFor(request, "3.6a");
      },
    };
    const connection = new TmuxConnection({
      executable: "/usr/bin/tmux",
      socketPath: "/tmp/capability.sock",
    });
    let currentEpoch = epoch(9);
    const binding = new LazyCapabilityBinding({
      connection,
      connectionAlias: alias("connected-daemon"),
      getDaemonEpoch: () => currentEpoch,
      transport,
    });

    expect(requests).toHaveLength(0);
    const first = await binding.bind();
    const second = await binding.bind();

    expect(first).toBe(second);
    expect(first.rawVersion).toBe("3.6a");
    expect(requests).toHaveLength(1);
    expect(requests[0]?.args).toEqual([
      "-N",
      "-S/tmp/capability.sock",
      "display-message",
      "-p",
      "#{version}",
    ]);

    currentEpoch = epoch(10);
    const rebound = await binding.bind();
    expect(requests).toHaveLength(2);
    expect(rebound.daemonEpoch).toBe(currentEpoch);
    expect(rebound.fingerprint).not.toBe(first.fingerprint);
  });

  test("single-flights concurrent probes once per daemon epoch", async () => {
    let entered = deferred();
    let release = deferred();
    let requests = 0;
    const transport: CommandTransport = {
      async execute(request) {
        requests += 1;
        entered.resolve();
        await release.promise;
        return resultFor(request, "3.7b");
      },
    };
    let currentEpoch = epoch(20);
    const binding = new LazyCapabilityBinding({
      connection: new TmuxConnection({ executable: "/usr/bin/tmux", socketName: "single-flight" }),
      connectionAlias: alias("single-flight"),
      getDaemonEpoch: () => currentEpoch,
      transport,
    });

    const first = binding.bind();
    const second = binding.bind();
    await entered.promise;
    await Promise.resolve();
    const firstWaveRequests = requests;
    release.resolve();
    const [firstSnapshot, secondSnapshot] = await Promise.all([first, second]);
    expect(firstWaveRequests).toBe(1);
    expect(firstSnapshot).toBe(secondSnapshot);

    currentEpoch = epoch(21);
    entered = deferred();
    release = deferred();
    const third = binding.bind();
    const fourth = binding.bind();
    await entered.promise;
    await Promise.resolve();
    const secondWaveRequests = requests;
    release.resolve();
    const [thirdSnapshot, fourthSnapshot] = await Promise.all([third, fourth]);
    expect(secondWaveRequests).toBe(2);
    expect(thirdSnapshot).toBe(fourthSnapshot);
    expect(thirdSnapshot).not.toBe(firstSnapshot);
  });

  test("rejects an epoch change during the daemon probe without caching it", async () => {
    let currentEpoch = epoch(4);
    let calls = 0;
    const transport: CommandTransport = {
      async execute(request) {
        calls += 1;
        currentEpoch = epoch(5);
        return resultFor(request, "3.7b");
      },
    };
    const binding = new LazyCapabilityBinding({
      connection: new TmuxConnection({ executable: "/usr/bin/tmux", socketName: "named" }),
      connectionAlias: alias("connected-daemon"),
      getDaemonEpoch: () => currentEpoch,
      transport,
    });

    await expect(binding.bind()).rejects.toThrow("daemon epoch changed while binding capabilities");
    expect(calls).toBe(1);
    await expect(binding.bind()).resolves.toMatchObject({ daemonEpoch: epoch(5) });
    expect(calls).toBe(2);
  });

  test("maps malformed, ambiguous, and failed connected-daemon version replies", async () => {
    const replies = [
      {
        diagnostic: "tmux version probe returned no version",
        returncode: 0,
        stderr: "",
        stdout: "",
      },
      {
        diagnostic: "tmux version probe returned multiple versions",
        returncode: 0,
        stderr: "",
        stdout: "3.7b\n3.7a\n",
      },
      {
        diagnostic: "invalid tmux version",
        returncode: 0,
        stderr: "",
        stdout: "#{version}\n",
      },
      {
        diagnostic: "tmux version probe failed: no server running",
        returncode: 1,
        stderr: "no server running\n",
        stdout: "",
      },
    ];

    for (const reply of replies) {
      const requests: CommandRequest[] = [];
      const transport: CommandTransport = {
        async execute(request) {
          requests.push(request);
          return {
            cmd: Object.freeze([request.executable, ...request.args]),
            returncode: reply.returncode,
            signal: null,
            stderr: encoder.encode(reply.stderr),
            stdout: encoder.encode(reply.stdout),
          };
        },
      };
      const binding = new LazyCapabilityBinding({
        connection: new TmuxConnection({ executable: "/usr/bin/tmux" }),
        connectionAlias: alias("connected-daemon"),
        getDaemonEpoch: () => epoch(1),
        transport,
      });

      let probeError: unknown;
      try {
        // eslint-disable-next-line no-await-in-loop -- each complete reply exercises a distinct protocol failure.
        await binding.bind();
      } catch (error) {
        probeError = error;
      }
      expect(requests).toHaveLength(1);
      expect(requests[0]?.args).toEqual(["-N", "display-message", "-p", "#{version}"]);
      expect(probeError).toBeInstanceOf(LibTmuxException);
      expect((probeError as Error).message).toContain(reply.diagnostic);
    }
  });
});
