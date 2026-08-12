import { describe, expect, test } from "bun:test";

import type { ConnectionAlias, DaemonEpoch } from "../../src/common.js";
import { LibTmuxException, TmuxObjectDoesNotExist } from "../../src/exc.js";
import {
  FIELD_VERSION,
  Obj,
  SCOPES_BY_LIST_CMD,
  getOutputFormat,
  parseOutput,
} from "../../src/neo.js";
import {
  executeGuardedFetch,
  executeGuardedList,
  FormatProtocolError,
  isTargetNotFoundError,
  selectBestWinlink,
} from "../../src/_internal/codec/guard_codec.js";
import { deriveTmuxCapabilities } from "../../src/_internal/runtime/capabilities.js";
import { TmuxConnection } from "../../src/_internal/runtime/connection.js";
import { TransportError, type CommandTransport } from "../../src/_internal/transport/types.js";
import { FORMAT_FIELD_TOKENS } from "../../src/_generated/format_fields.js";

const encoder = new TextEncoder();

function valueFor(token: string, overrides: Readonly<Record<string, string>>): string {
  if (Object.hasOwn(overrides, token)) return overrides[token]!;
  if (token === "session_id") return "$1";
  if (token === "window_id") return "@2";
  if (token === "pane_id") return "%3";
  if (token === "client_name") return "/dev/pts/4";
  return `raw:${token}`;
}

function frame(
  request: ReturnType<typeof getOutputFormat>,
  overrides: Readonly<Record<string, string>> = {},
): Uint8Array {
  const values = request.fields.map(({ token }) => valueFor(token, overrides));
  return encoder.encode(
    `${request.guards.recordStart}${values.join(request.guards.field)}${request.guards.recordEnd}\n`,
  );
}

describe("neo format metadata", () => {
  test("exports only the accepted pure runtime surface", async () => {
    expect(Object.keys(await import("../../src/neo.js")).sort()).toEqual([
      "FIELD_VERSION",
      "Obj",
      "SCOPES_BY_LIST_CMD",
      "getOutputFormat",
      "parseOutput",
    ]);
  });

  test("publishes the exact list-scope cascade as frozen data", () => {
    expect(SCOPES_BY_LIST_CMD).toEqual({
      "list-clients": ["universal", "session", "window", "pane", "client"],
      "list-panes": ["universal", "session", "window", "pane"],
      "list-sessions": ["universal", "session", "window", "pane"],
      "list-windows": ["universal", "session", "window", "pane"],
    });
    expect(Object.isFrozen(SCOPES_BY_LIST_CMD)).toBe(true);
    for (const [command, scopes] of Object.entries(SCOPES_BY_LIST_CMD)) {
      expect(Object.isFrozen(scopes)).toBe(true);
      if (command === "list-clients") expect(scopes).toContain("client");
      else expect(scopes).not.toContain("client");
      expect(scopes).not.toContain("context");
      expect(scopes).not.toContain("event");
    }
  });

  test("publishes only nonbaseline field floors", () => {
    expect(FIELD_VERSION).toEqual({
      bracket_paste_flag: "3.7",
      pane_dead_signal: "3.3",
      pane_dead_time: "3.3",
      pane_flags: "3.7",
      pane_floating_flag: "3.7",
      pane_pb_progress: "3.7",
      pane_pb_state: "3.7",
      pane_pipe_pid: "3.7",
      pane_x: "3.7",
      pane_y: "3.7",
      pane_z: "3.7",
      pane_zoomed_flag: "3.7",
      synchronized_output_flag: "3.7",
    });
    expect(Object.isFrozen(FIELD_VERSION)).toBe(true);
  });
});

describe("request-bound neo parsing", () => {
  test("prepares and parses through one immutable request-bound plan", () => {
    const request = getOutputFormat("list-sessions", "3.2a");
    const rows = parseOutput(
      request,
      frame(request, { session_group: "", session_name: "name␞with\nnewline" }),
    );

    expect(request.fields).toHaveLength(123);
    expect(request.format).toBe(
      `${request.guards.recordStart}${request.fields
        .map(({ token }) => `#{${token}}`)
        .join(request.guards.field)}${request.guards.recordEnd}`,
    );
    expect(Object.keys(request).sort()).toEqual([
      "fields",
      "format",
      "guards",
      "listCommand",
      "tmuxVersion",
    ]);
    for (const field of request.fields) expect(Object.keys(field)).toEqual(["token"]);
    expect(Object.keys(request.guards).sort()).toEqual(["field", "recordEnd", "recordStart"]);
    expect(Object.keys(request.tmuxVersion).sort()).toEqual(["major", "minor", "raw", "suffix"]);
    expect(Object.isFrozen(request)).toBe(true);
    expect(Object.isFrozen(request.fields)).toBe(true);
    expect(request.fields.every((field) => Object.isFrozen(field))).toBe(true);
    expect(Object.isFrozen(request.guards)).toBe(true);
    expect(Object.isFrozen(request.tmuxVersion)).toBe(true);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toBeInstanceOf(Obj);
    expect(rows[0]?.session_id).toBe("$1");
    expect(rows[0]?.session_name).toBe("name␞with\nnewline");
    expect(rows[0]?.session_group).toBe("");
    expect(rows[0]?.pane_x).toBeNull();
    expect(Object.keys(rows[0] ?? {})).toEqual([...FORMAT_FIELD_TOKENS]);
    expect(Object.isFrozen(rows)).toBe(true);
    expect(Object.isFrozen(rows[0])).toBe(true);
  });

  test("carries a 3.7 floor into 3.7a while retaining the selected version", () => {
    const request = getOutputFormat("list-panes", "3.7a");

    expect(request.fields.some(({ token }) => token === "pane_x")).toBe(true);
    expect(request.tmuxVersion).toEqual({ major: 3, minor: 7, raw: "3.7a", suffix: "a" });
  });

  test("creates fresh nonempty printable independent guards for each public plan", () => {
    const plans = [
      getOutputFormat("list-sessions", "3.7b"),
      getOutputFormat("list-sessions", "3.7b"),
    ];
    const triples = plans.map(({ guards: { field, recordEnd, recordStart } }) => [
      field,
      recordEnd,
      recordStart,
    ]);

    for (const triple of triples) {
      expect(new Set(triple).size).toBe(3);
      for (const guard of triple) expect(guard).toMatch(/^[\x20-\x7e]+$/u);
    }
    expect(triples[0]).not.toEqual(triples[1]);
  });

  test("returns an empty frozen collection for an empty successful listing", () => {
    const request = getOutputFormat("list-sessions", "3.7b");
    const rows = parseOutput(request, new Uint8Array());

    expect(rows).toEqual([]);
    expect(Object.isFrozen(rows)).toBe(true);
  });

  test("accepts only the exact plan identity retained in the runtime WeakMap", () => {
    const request = getOutputFormat("list-sessions", "3.7b");
    const copied = Object.freeze({ ...request }) as typeof request;

    expect(() => parseOutput(copied, new Uint8Array())).toThrow(FormatProtocolError);
    expect(() => parseOutput(copied, new Uint8Array())).toThrow("foreign OutputFormatPlan");
    expect(() => parseOutput(request, frame(request))).not.toThrow();
  });
});

describe("neo point-selection policies", () => {
  test("rejects a stale capability fingerprint before list execution", async () => {
    const prepared = deriveTmuxCapabilities({
      connectionAlias: "neo-stale" as ConnectionAlias,
      daemonEpoch: 1 as DaemonEpoch,
      rawVersion: "3.7b",
    });
    const stale = deriveTmuxCapabilities({
      connectionAlias: "neo-stale" as ConnectionAlias,
      daemonEpoch: 2 as DaemonEpoch,
      rawVersion: "3.7b",
    });
    let binds = 0;
    let executions = 0;
    const transport: CommandTransport = {
      async execute() {
        executions += 1;
        throw new Error("transport must not execute a stale request");
      },
    };

    await expect(
      executeGuardedList({
        capabilities: {
          async bind() {
            binds += 1;
            return binds === 1 ? prepared : stale;
          },
        },
        connection: new TmuxConnection({ executable: "/usr/bin/tmux" }),
        listCommand: "list-sessions",
        transport,
      }),
    ).rejects.toThrow("capability fingerprint changed before execution");
    expect(binds).toBe(2);
    expect(executions).toBe(0);
  });

  test("translates only exact target-not-found diagnostics", () => {
    const cases = [
      ["can't find pane: %99", true],
      ["can't find window: @99", true],
      ["can't find session: $99", true],
      ["no server running on /tmp/tmux-1000/default", false],
      ["error connecting to /tmp/nope (No such file or directory)", false],
      ["error connecting to /tmp/other (Permission denied)", false],
    ] as const;

    for (const [message, expected] of cases) {
      expect(isTargetNotFoundError(message)).toBe(expected);
    }
  });

  test("does not translate a transport message without tmux stderr", async () => {
    const capabilities = deriveTmuxCapabilities({
      connectionAlias: "neo-transport-message" as ConnectionAlias,
      daemonEpoch: 1 as DaemonEpoch,
      rawVersion: "3.7b",
    });
    const transport: CommandTransport = {
      async execute() {
        throw new TransportError("can't find pane: %404", {
          delivery: "not_started",
          kind: "spawn",
          stderr: new Uint8Array(),
        });
      },
    };

    try {
      await executeGuardedFetch({
        capabilities: {
          async bind() {
            return capabilities;
          },
        },
        connection: new TmuxConnection({ executable: "/usr/bin/tmux" }),
        identityField: "pane_id",
        identityValue: "%404",
        listCommand: "list-panes",
        transport,
      });
      throw new Error("expected point fetch to reject");
    } catch (error) {
      expect(error).toBeInstanceOf(LibTmuxException);
      expect(error).not.toBeInstanceOf(TmuxObjectDoesNotExist);
      expect(String(error)).toContain("can't find pane: %404");
    }
  });

  test("preserves caller-supplied target arguments for point fetches", async () => {
    const capabilities = deriveTmuxCapabilities({
      connectionAlias: "neo-target" as ConnectionAlias,
      daemonEpoch: 1 as DaemonEpoch,
      rawVersion: "3.7b",
    });
    const requests: string[][] = [];
    const transport: CommandTransport = {
      async execute(request) {
        requests.push([...request.args]);
        return {
          cmd: Object.freeze([request.executable, ...request.args]),
          returncode: 1,
          signal: null,
          stderr: encoder.encode("can't find window: @404\n"),
          stdout: new Uint8Array(),
        };
      },
    };

    await expect(
      executeGuardedFetch({
        capabilities: {
          async bind() {
            return capabilities;
          },
        },
        connection: new TmuxConnection({ executable: "/usr/bin/tmux" }),
        identityField: "window_id",
        identityValue: "@404",
        listCommand: "list-windows",
        listExtraArgs: ["-t", "@404"],
        transport,
      }),
    ).rejects.toBeInstanceOf(TmuxObjectDoesNotExist);
    const listIndex = requests[0]?.indexOf("list-windows") ?? -1;
    expect(requests[0]?.slice(listIndex, listIndex + 3)).toEqual(["list-windows", "-t", "@404"]);
  });

  test("translates a successful empty point listing into object absence", async () => {
    const capabilities = deriveTmuxCapabilities({
      connectionAlias: "neo-empty" as ConnectionAlias,
      daemonEpoch: 1 as DaemonEpoch,
      rawVersion: "3.7b",
    });
    const transport: CommandTransport = {
      async execute(request) {
        return {
          cmd: Object.freeze([request.executable, ...request.args]),
          returncode: 0,
          signal: null,
          stderr: new Uint8Array(),
          stdout: new Uint8Array(),
        };
      },
    };

    await expect(
      executeGuardedFetch({
        capabilities: {
          async bind() {
            return capabilities;
          },
        },
        connection: new TmuxConnection({ executable: "/usr/bin/tmux" }),
        identityField: "session_id",
        identityValue: "$404",
        listCommand: "list-sessions",
        transport,
      }),
    ).rejects.toBeInstanceOf(TmuxObjectDoesNotExist);
  });

  test("selects the active winlink and otherwise the lowest numeric index", () => {
    const low = Object.freeze({ window_active: "0", window_id: "@1", window_index: "1" });
    const high = Object.freeze({ window_active: "0", window_id: "@1", window_index: "5" });
    const activeHigh = Object.freeze({
      window_active: "1",
      window_id: "@1",
      window_index: "5",
    });
    const activeLow = Object.freeze({
      window_active: "1",
      window_id: "@1",
      window_index: "1",
    });

    expect(selectBestWinlink([high, low])).toBe(low);
    expect(selectBestWinlink([low, high])).toBe(low);
    expect(selectBestWinlink([low, activeHigh])).toBe(activeHigh);
    expect(selectBestWinlink([activeHigh, activeLow])).toBe(activeHigh);
    expect(selectBestWinlink([low])).toBe(low);
    expect(high.window_index).toBe("5");
  });
});
