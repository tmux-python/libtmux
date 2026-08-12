import { constants } from "node:fs";
import { access } from "node:fs/promises";
import { isAbsolute, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

interface RuntimeReport {
  readonly cases: readonly { readonly id: string; readonly matched: boolean }[];
  readonly implementation: string;
  readonly protocol: string;
  readonly runtime: string;
  readonly status: "passed";
}

const tsRoot = new URL("../..", import.meta.url);
const tsRootPath = fileURLToPath(tsRoot);

async function runBounded(command: readonly string[], milliseconds = 30_000) {
  const child = Bun.spawn([...command], {
    cwd: tsRootPath,
    stderr: "pipe",
    stdout: "pipe",
  });
  let deadlineReached = false;
  const terminate = setTimeout(() => {
    deadlineReached = true;
    child.kill("SIGTERM");
  }, milliseconds);
  const kill = setTimeout(() => child.kill("SIGKILL"), milliseconds + 500);
  try {
    const [exitCode, stdout, stderr] = await Promise.all([
      child.exited,
      new Response(child.stdout).text(),
      new Response(child.stderr).text(),
    ]);
    if (deadlineReached) throw new Error(`subprocess exceeded deadline: ${command.join(" ")}`);
    return { exitCode, stderr, stdout };
  } finally {
    clearTimeout(terminate);
    clearTimeout(kill);
  }
}

async function resolveNode22(): Promise<string> {
  const configured = process.env.LIBTMUX_NODE22;
  if (configured !== undefined) {
    const candidate = resolve(configured);
    return authenticateNode22(candidate, "LIBTMUX_NODE22");
  }
  const mise = Bun.which("mise");
  if (mise === null) throw new Error("Node 22 requires LIBTMUX_NODE22 or mise");
  const result = await runBounded(
    [mise, "exec", "--quiet", "node@22", "--", "node", "-p", "process.execPath"],
    10_000,
  );
  expect(result.exitCode, result.stderr).toBe(0);
  expect(result.stderr).toBe("");
  const lines = result.stdout.trim().split(/\r?\n/u);
  expect(lines).toHaveLength(1);
  return authenticateNode22(lines[0]!, "mise");
}

async function authenticateNode22(candidate: string, source: string): Promise<string> {
  if (!isAbsolute(candidate)) throw new Error(`${source} returned a non-absolute Node path`);
  await access(candidate, constants.X_OK);
  const version = await runBounded([candidate, "--version"], 10_000);
  expect(version.exitCode, version.stderr).toBe(0);
  expect(version.stderr).toBe("");
  // The corpus fixture pins the major version only. Pinning a patch here
  // breaks the build every time Node ships one, which it did twice while this
  // branch was in CI.
  const match = /^v(?<major>\d+)\.(?<minor>\d+)\.(?<patch>\d+)$/u.exec(version.stdout.trim());
  expect(match?.groups?.major).toBe("22");
  return candidate;
}

function decodeReport(stdout: string): RuntimeReport {
  const report = JSON.parse(stdout) as RuntimeReport;
  expect(report.protocol).toBe("libtmux-where-regex-v1");
  expect(report.status).toBe("passed");
  expect(report.cases.length).toBe(19);
  expect(new Set(report.cases.map(({ id }) => id)).size).toBe(19);
  return report;
}

describe("three-runtime regex corpus", () => {
  test("resolves one executable Node 22 runtime", async () => {
    expect(isAbsolute(await resolveNode22())).toBe(true);
  });

  test("runs the Python oracle and emitted library under Bun and Node 22", async () => {
    const python = await runBounded([
      "python3",
      "-I",
      "-B",
      "tests/differential/where_regex_oracle.py",
    ]);
    expect(python.exitCode, python.stderr).toBe(0);
    expect(python.stderr).toBe("");
    expect(decodeReport(python.stdout).implementation).toBe("python-native-re");

    const build = await runBounded(["bun", "run", "build"]);
    expect(build.exitCode, build.stderr).toBe(0);

    const bun = await runBounded(["bun", "tests/fixtures/where_regex_runtime.mjs", "bun"]);
    expect(bun.exitCode, bun.stderr).toBe(0);
    expect(bun.stderr).toBe("");
    expect(decodeReport(bun.stdout).implementation).toBe("bun-native-regexp");

    const nodeExecutable = await resolveNode22();
    const node = await runBounded([
      nodeExecutable,
      "tests/fixtures/where_regex_runtime.mjs",
      "node",
    ]);
    expect(node.exitCode, node.stderr).toBe(0);
    expect(node.stderr).toBe("");
    expect(decodeReport(node.stdout).implementation).toBe("node-native-regexp");
  }, 90_000);
});
