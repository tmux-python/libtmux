import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  DIFFERENTIAL_PROTOCOL,
  decodeDifferentialResponse,
  type DifferentialResponse,
} from "./raw_tmux.js";

const baselineCommit = "38e368c11117fb4aeb2f082d552cd4f210eae06a";
const tsRoot = fileURLToPath(new URL("../..", import.meta.url));
const repositoryRoot = resolve(tsRoot, "..");
const oraclePath = fileURLToPath(new URL("./python_oracle.py", import.meta.url));

export interface ClosedOracleProcess {
  readonly code: number | null;
  readonly stderr: string;
  readonly stdout: string;
}

async function close(child: ReturnType<typeof spawn>): Promise<ClosedOracleProcess> {
  const stdout: Buffer[] = [];
  const stderr: Buffer[] = [];
  child.stdout?.on("data", (chunk: Buffer) => stdout.push(chunk));
  child.stderr?.on("data", (chunk: Buffer) => stderr.push(chunk));
  return new Promise((resolveResult, reject) => {
    let settled = false;
    const finishError = (error: unknown): void => {
      if (settled) return;
      settled = true;
      clearTimeout(term);
      clearTimeout(kill);
      clearTimeout(hard);
      reject(error);
    };
    const term = setTimeout(() => child.kill("SIGTERM"), 5_000);
    const kill = setTimeout(() => child.kill("SIGKILL"), 5_500);
    const hard = setTimeout(() => {
      child.stdin?.destroy();
      child.stdout?.destroy();
      child.stderr?.destroy();
      child.unref();
      finishError(new Error("differential subprocess close exceeded hard deadline"));
    }, 6_000);
    child.once("error", finishError);
    child.once("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(term);
      clearTimeout(kill);
      clearTimeout(hard);
      resolveResult({
        code,
        stderr: Buffer.concat(stderr).toString("utf8"),
        stdout: Buffer.concat(stdout).toString("utf8"),
      });
    });
  });
}

export async function materializePythonBaseline(parent: string): Promise<string> {
  const archive = join(parent, "python-0.62.0.tar");
  const archived = await close(
    spawn("git", ["archive", `--output=${archive}`, baselineCommit, "src/libtmux"], {
      cwd: repositoryRoot,
      stdio: ["ignore", "pipe", "pipe"],
    }),
  );
  if (archived.code !== 0) throw new Error(archived.stderr);
  const extracted = await close(
    spawn("tar", ["-xf", archive, "-C", parent], {
      cwd: repositoryRoot,
      stdio: ["ignore", "pipe", "pipe"],
    }),
  );
  if (extracted.code !== 0) throw new Error(extracted.stderr);
  const listing = await close(
    spawn("git", ["ls-tree", "-r", baselineCommit, "src/libtmux"], {
      cwd: repositoryRoot,
      stdio: ["ignore", "pipe", "pipe"],
    }),
  );
  if (listing.code !== 0) throw new Error(listing.stderr);
  await writeFile(
    join(parent, ".libtmux-oracle.json"),
    `${JSON.stringify({
      commit: baselineCommit,
      listingBase64: Buffer.from(listing.stdout).toString("base64"),
      listingDigest: createHash("sha256").update(listing.stdout).digest("hex"),
      protocol: "libtmux-python-oracle-root-v1",
    })}\n`,
  );
  return parent;
}

export async function queryPythonOracle(
  sourceRoot: string | undefined,
  socketPath: string,
  requestId: string,
  environment: NodeJS.ProcessEnv = process.env,
): Promise<{ result: Promise<ClosedOracleProcess>; response?: DifferentialResponse }> {
  const child = spawn(
    "uv",
    ["run", "--project", repositoryRoot, "python", "-I", "-B", oraclePath],
    {
      cwd: repositoryRoot,
      env: {
        ...environment,
        ...(sourceRoot === undefined ? {} : { LIBTMUX_ORACLE_ROOT: sourceRoot }),
      },
      stdio: ["pipe", "pipe", "pipe"],
    },
  );
  child.stdin!.end(
    `${JSON.stringify({
      operation: "list-sessions",
      protocol: DIFFERENTIAL_PROTOCOL,
      requestId,
      socketPath,
    })}\n`,
  );
  const result = await close(child);
  return result.code === 0
    ? {
        result: Promise.resolve(result),
        response: decodeDifferentialResponse(result.stdout, requestId, "python-0.62.0"),
      }
    : { result: Promise.resolve(result) };
}
