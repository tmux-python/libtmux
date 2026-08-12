import { appendFile, mkdir, mkdtemp, rm, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, test } from "bun:test";

import { prepareRunRoot, reapOwnedRunRoot } from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";
import { materializePythonBaseline, queryPythonOracle } from "../differential/python_client.js";
import { DIFFERENTIAL_PROTOCOL, queryRawTmux } from "../differential/raw_tmux.js";

describe("differential substrate", () => {
  test("smokes reusable raw-tmux and pinned Python 0.62.0 protocols", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-diff-"));
    const publishedRoot = process.env.LIBTMUX_TEST_RUN_ROOT;
    const runRoot = publishedRoot ?? join(parent, "run, root");
    if (publishedRoot === undefined) await prepareRunRoot(runRoot);
    const rawServer = await TestServer.create({ runRoot, sessionName: "substrate-smoke" });
    const pythonServer = await TestServer.create({ runRoot, sessionName: "substrate-smoke" });
    try {
      const oracleRoot = await materializePythonBaseline(parent);
      const raw = await queryRawTmux({
        operation: "list-sessions",
        protocol: DIFFERENTIAL_PROTOCOL,
        requestId: "raw-1",
        socketPath: rawServer.socketPath,
      });
      const oracle = await queryPythonOracle(oracleRoot, pythonServer.socketPath, "python-1");
      expect(oracle.response).toBeDefined();
      expect(raw).toMatchObject({
        implementation: "raw-tmux",
        protocol: DIFFERENTIAL_PROTOCOL,
        requestId: "raw-1",
        semantics: { sessions: ["substrate-smoke"] },
      });
      expect(raw.returncode).toBe(0);
      expect(Buffer.from(raw.stdoutBase64, "base64").toString("utf8")).toContain("substrate-smoke");
      expect(oracle.response).toMatchObject({
        implementation: "python-0.62.0",
        protocol: DIFFERENTIAL_PROTOCOL,
        requestId: "python-1",
        semantics: raw.semantics,
      });
      expect(oracle.response!.diagnostics).toEqual([]);
    } finally {
      await Promise.all([rawServer.dispose(), pythonServer.dispose()]);
      if (publishedRoot === undefined) await reapOwnedRunRoot(runRoot);
      await rm(parent, { force: true, recursive: true });
    }
  }, 15_000);

  test("rejects the editable cwd package without pinned source provenance", async () => {
    const result = await queryPythonOracle(undefined, "/does/not/matter", "negative");
    const completed = await result.result;
    expect(completed.code).not.toBe(0);
    expect(completed.stderr).toContain("isolated Python 0.62.0 source root is required");
  });

  test("reuses one authenticated materialized tree across two isolated oracle calls", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-oracle-reuse-"));
    const publishedRoot = process.env.LIBTMUX_TEST_RUN_ROOT;
    const runRoot = publishedRoot ?? join(parent, "run");
    if (publishedRoot === undefined) await prepareRunRoot(runRoot);
    const server = await TestServer.create({ runRoot, sessionName: "oracle-reuse" });
    try {
      const root = await materializePythonBaseline(parent);
      const first = await queryPythonOracle(root, server.socketPath, "reuse-1");
      expect(first.response?.semantics.sessions).toEqual(["oracle-reuse"]);
      const second = await queryPythonOracle(root, server.socketPath, "reuse-2");
      expect(second.response?.requestId).toBe("reuse-2");
      expect(second.response?.semantics).toEqual(first.response?.semantics);
    } finally {
      await server.dispose();
      if (publishedRoot === undefined) await reapOwnedRunRoot(runRoot);
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("correlates raw tmux execution and response to one submitted request snapshot", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-raw-correlation-"));
    const publishedRoot = process.env.LIBTMUX_TEST_RUN_ROOT;
    const runRoot = publishedRoot ?? join(parent, "run");
    if (publishedRoot === undefined) await prepareRunRoot(runRoot);
    const submittedServer = await TestServer.create({
      runRoot,
      sessionName: "submitted-session",
    });
    const mutatedServer = await TestServer.create({ runRoot, sessionName: "mutated-session" });
    try {
      const request = {
        operation: "list-sessions" as const,
        protocol: DIFFERENTIAL_PROTOCOL,
        requestId: "submitted-id",
        socketPath: submittedServer.socketPath,
      };
      const responsePromise = queryRawTmux(request);
      request.requestId = "mutated-id";
      request.socketPath = mutatedServer.socketPath;

      const response = await responsePromise;

      expect(response.requestId).toBe("submitted-id");
      expect(response.semantics.sessions).toEqual(["submitted-session"]);
    } finally {
      await Promise.all([submittedServer.dispose(), mutatedServer.dispose()]);
      if (publishedRoot === undefined) await reapOwnedRunRoot(runRoot);
      await rm(parent, { force: true, recursive: true });
    }
  });

  for (const mutation of ["extra", "changed", "missing"] as const) {
    test(`rejects a ${mutation} file in a forged pinned source tree`, async () => {
      const parent = await mkdtemp(join(tmpdir(), `ltx4-forged-${mutation}-`));
      try {
        const root = await materializePythonBaseline(parent);
        if (mutation === "extra") {
          await writeFile(join(root, "src/libtmux/forged.py"), "FORGED = True\n");
        } else if (mutation === "changed") {
          await appendFile(join(root, "src/libtmux/test/random.py"), "\nFORGED = True\n");
        } else {
          await unlink(join(root, "src/libtmux/test/random.py"));
        }
        const result = await queryPythonOracle(root, "/does/not/matter", `forged-${mutation}`);
        const completed = await result.result;
        expect(completed.code).not.toBe(0);
        expect(completed.stderr).toContain("provenance");
      } finally {
        await rm(parent, { force: true, recursive: true });
      }
    });
  }

  test("strictly validates every Python response frame and correlation field", async () => {
    const parent = await mkdtemp(join(tmpdir(), "ltx4-bad-frame-"));
    const fakeBin = join(parent, "bin");
    await mkdir(fakeBin);
    const fakeUv = join(fakeBin, "uv");
    await writeFile(fakeUv, "#!/bin/sh\nprintf '%s' \"$LIBTMUX_FAKE_FRAME\"\n", {
      mode: 0o700,
    });
    const valid = {
      diagnostics: [],
      implementation: "python-0.62.0",
      protocol: DIFFERENTIAL_PROTOCOL,
      requestId: "expected",
      returncode: 0,
      semantics: { sessions: [] },
      stderrBase64: "",
      stdoutBase64: "",
    };
    const frames = [
      "not-json\n",
      `${JSON.stringify(valid)}\n${JSON.stringify(valid)}\n`,
      `${JSON.stringify({ ...valid, extra: true })}\n`,
      `${JSON.stringify({ ...valid, requestId: "wrong" })}\n`,
      `${JSON.stringify({ ...valid, protocol: "wrong" })}\n`,
      `${JSON.stringify({ ...valid, implementation: "forged" })}\n`,
      `${JSON.stringify({ ...valid, stdoutBase64: "%%%" })}\n`,
      `${JSON.stringify({ ...valid, diagnostics: [1] })}\n`,
      `${JSON.stringify({ ...valid, semantics: { sessions: [1] } })}\n`,
    ];
    try {
      for (const frame of frames) {
        // eslint-disable-next-line no-await-in-loop -- each malformed frame is an independent process protocol case.
        await expect(
          queryPythonOracle(undefined, "/does/not/matter", "expected", {
            ...process.env,
            LIBTMUX_FAKE_FRAME: frame,
            PATH: `${fakeBin}:${process.env.PATH ?? ""}`,
          }),
        ).rejects.toThrow();
      }
    } finally {
      await rm(parent, { force: true, recursive: true });
    }
  });

  test("rejects malformed or uncorrelated protocol requests", async () => {
    await expect(
      queryRawTmux({
        operation: "list-sessions",
        protocol: DIFFERENTIAL_PROTOCOL,
        requestId: "",
        socketPath: "/tmp/not-used",
      }),
    ).rejects.toThrow("requestId");

    const malformed = [
      null,
      [],
      {
        operation: "list-sessions",
        protocol: DIFFERENTIAL_PROTOCOL,
        requestId: 7,
        socketPath: "/tmp/not-used",
      },
      {
        operation: "list-sessions",
        protocol: DIFFERENTIAL_PROTOCOL,
        requestId: "typed",
        socketPath: 7,
      },
      {
        extra: true,
        operation: "list-sessions",
        protocol: DIFFERENTIAL_PROTOCOL,
        requestId: "extra",
        socketPath: "/tmp/not-used",
      },
    ];
    for (const request of malformed) {
      // eslint-disable-next-line no-await-in-loop -- every malformed frame is an independent pre-spawn boundary.
      await expect(Reflect.apply(queryRawTmux, undefined, [request])).rejects.toThrow();
    }
  });
});
