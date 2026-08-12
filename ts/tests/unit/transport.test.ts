import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

import { decodeBackslashReplace } from "../../src/_internal/codec/backslash_replace.js";
import {
  adaptRawResult,
  executeBatch,
  prepareCommandRequest,
} from "../../src/_internal/operations/request.js";
import { TmuxConnection } from "../../src/_internal/runtime/connection.js";
import { NodeSpawnTransport } from "../../src/_internal/transport/node_spawn_transport.js";

const echoFixture = fileURLToPath(new URL("../fixtures/echo_argv.mjs", import.meta.url));
const malformedFixture = fileURLToPath(new URL("../fixtures/malformed_utf8.mjs", import.meta.url));

describe("NodeSpawnTransport", () => {
  test("passes hostile-looking values as distinct literal arguments", async () => {
    const values = ["with space", "-leading", 'a"quote', "a\\backslash", "雪", ";"];
    const transport = new NodeSpawnTransport();
    const raw = await transport.execute({
      args: [echoFixture, ...values],
      executable: process.execPath,
    });

    expect(JSON.parse(decodeBackslashReplace(raw.stdout))).toEqual(values);
    expect(raw.cmd).toEqual([process.execPath, echoFixture, ...values]);
    expect(raw.returncode).toBe(0);
  });

  test("returns raw bytes for nonzero exits instead of throwing", async () => {
    const transport = new NodeSpawnTransport();
    const raw = await transport.execute({
      args: [echoFixture, "--exit-code=7", "kept"],
      executable: process.execPath,
    });

    expect(raw.returncode).toBe(7);
    expect(raw.stdout).toBeInstanceOf(Uint8Array);
    expect(raw.stderr).toBeInstanceOf(Uint8Array);
    expect(JSON.parse(decodeBackslashReplace(raw.stdout))).toEqual(["kept"]);
  });

  test("drains stdout and stderr concurrently", async () => {
    const transport = new NodeSpawnTransport();
    const raw = await transport.execute({
      args: [echoFixture, "--dual-streams", "1048576"],
      executable: process.execPath,
    });

    expect(raw.stdout.byteLength).toBe(1_048_576);
    expect(raw.stderr.byteLength).toBe(1_048_576);
  });

  test("captures stdin bytes when execution begins", async () => {
    const stdin = Uint8Array.of(0x61, 0x62);
    const transport = new NodeSpawnTransport();

    const execution = transport.execute({
      args: [echoFixture, "--echo-stdin"],
      executable: process.execPath,
      stdin,
    });
    stdin[0] = 0x7a;

    const raw = await execution;
    expect([...raw.stdout]).toEqual([0x61, 0x62]);
  });

  test("keeps submitted argv correlated with the raw result", async () => {
    const args = [echoFixture, "submitted"];
    const transport = new NodeSpawnTransport();

    const execution = transport.execute({ args, executable: process.execPath });
    args[1] = "mutated-after-spawn";

    const raw = await execution;
    expect(JSON.parse(decodeBackslashReplace(raw.stdout))).toEqual(["submitted"]);
    expect(raw.cmd).toEqual([process.execPath, echoFixture, "submitted"]);
  });

  test("adapts malformed bytes produced by a child", async () => {
    const transport = new NodeSpawnTransport();
    const raw = await transport.execute({
      args: [malformedFixture],
      executable: process.execPath,
    });

    expect(adaptRawResult(raw).stdout).toEqual(["valid:€", "bad:\\xff\\xc3("]);
  });
});

describe("request preparation and batching", () => {
  test("prepares connection flags and caller arguments without shell syntax", () => {
    const connection = new TmuxConnection({
      colors: 88,
      configFile: "/tmp/tmux.conf",
      environment: { TERM: "screen-256color" },
      executable: "/usr/bin/tmux",
      socketPath: "/tmp/tmux.sock",
    });

    expect(prepareCommandRequest(connection, ["display-message", ";", "hello world"])).toEqual({
      args: ["-8", "-f/tmp/tmux.conf", "-S/tmp/tmux.sock", "display-message", ";", "hello world"],
      environment: { TERM: "screen-256color" },
      executable: "/usr/bin/tmux",
    });
  });

  test("rejects stdin for commands without a native stdin operand", () => {
    const connection = new TmuxConnection({ executable: "/usr/bin/tmux" });

    expect(() =>
      prepareCommandRequest(connection, ["display-message", "hello"], { stdin: "payload" }),
    ).toThrow("display-message does not accept stdin");
  });

  test("copies stdin accepted by load-buffer from its caller", () => {
    const connection = new TmuxConnection({ executable: "/usr/bin/tmux" });
    const input = Uint8Array.of(0x61, 0x62);

    const request = prepareCommandRequest(connection, ["load-buffer", "-"], { stdin: input });
    input[0] = 0x7a;

    expect(request.stdin).toEqual(Uint8Array.of(0x61, 0x62));
    expect(Object.isFrozen(request)).toBe(true);
    expect(Object.isFrozen(request.args)).toBe(true);
  });

  test("does not expose writable prepared stdin", async () => {
    const connection = new TmuxConnection({ executable: "/usr/bin/tmux" });
    const request = prepareCommandRequest(connection, ["load-buffer", "-"], {
      stdin: Uint8Array.of(0x61, 0x62),
    });

    request.stdin![0] = 0x7a;
    await Promise.resolve();

    expect(request.stdin).toEqual(Uint8Array.of(0x61, 0x62));
  });

  test("returns correlated success failure success and continues after failure", async () => {
    const transport = new NodeSpawnTransport();
    const requests = [0, 9, 0].map((exitCode, index) => ({
      args: [echoFixture, `--exit-code=${exitCode}`, `request-${index}`],
      executable: process.execPath,
    }));

    const outcomes = await executeBatch(transport, requests);

    expect(outcomes.map(({ index, status, delivery }) => ({ index, status, delivery }))).toEqual([
      { delivery: "replied", index: 0, status: "complete" },
      { delivery: "replied", index: 1, status: "failed" },
      { delivery: "replied", index: 2, status: "complete" },
    ]);
    expect(outcomes.map((outcome) => outcome.result?.returncode)).toEqual([0, 9, 0]);
    expect(outcomes.map((outcome) => outcome.request)).toEqual(requests);
  });

  test("captures the independent request sequence before awaiting", async () => {
    const transport = new NodeSpawnTransport();
    const secondRequest = {
      args: [echoFixture, "second-original"],
      executable: process.execPath,
    };
    const requests = [
      { args: [echoFixture, "first"], executable: process.execPath },
      secondRequest,
    ];

    const execution = executeBatch(transport, requests);
    requests[1] = { args: [echoFixture, "second-replacement"], executable: process.execPath };
    const outcomes = await execution;

    expect(outcomes[1]?.request).not.toBe(secondRequest);
    expect(outcomes[1]?.request).toEqual(secondRequest);
    expect(Object.isFrozen(outcomes[1]?.request)).toBe(true);
    expect(JSON.parse(decodeBackslashReplace(outcomes[1]!.rawResult!.stdout))).toEqual([
      "second-original",
    ]);
  });

  test("captures every nested batch argv before awaiting", async () => {
    const transport = new NodeSpawnTransport();
    const secondArgs = [echoFixture, "second-original"];
    const requests = [
      { args: [echoFixture, "first"], executable: process.execPath },
      { args: secondArgs, executable: process.execPath },
    ];

    const execution = executeBatch(transport, requests);
    secondArgs[1] = "second-mutated";
    const outcomes = await execution;

    expect(outcomes[1]?.request.args).toEqual([echoFixture, "second-original"]);
    expect(JSON.parse(decodeBackslashReplace(outcomes[1]!.rawResult!.stdout))).toEqual([
      "second-original",
    ]);
    expect(outcomes[1]?.rawResult?.cmd).toEqual([process.execPath, echoFixture, "second-original"]);
  });

  test("captures every nested batch stdin before awaiting", async () => {
    const transport = new NodeSpawnTransport();
    const secondStdin = Uint8Array.of(0x61, 0x62);
    const requests = [
      { args: [echoFixture, "first"], executable: process.execPath },
      {
        args: [echoFixture, "--echo-stdin"],
        executable: process.execPath,
        stdin: secondStdin,
      },
    ];

    const execution = executeBatch(transport, requests);
    secondStdin[0] = 0x7a;
    const outcomes = await execution;

    expect(outcomes[1]?.request.stdin).toEqual(Uint8Array.of(0x61, 0x62));
    expect(outcomes[1]?.rawResult?.stdout).toEqual(Uint8Array.of(0x61, 0x62));
  });
});
