import { fileURLToPath } from "node:url";

const fixture = "tests/fixtures/type-aware-lint/no_floating_promise.ts";
const tsconfig = "tests/fixtures/type-aware-lint/tsconfig.json";
const diagnostic = "typescript/no-floating-promises";
const tsRoot = fileURLToPath(new URL("..", import.meta.url));
const typeScriptExecutable = fileURLToPath(new URL("../node_modules/.bin/tsc", import.meta.url));
const oxlintExecutable = fileURLToPath(new URL("../node_modules/.bin/oxlint", import.meta.url));
interface OxlintOutput {
  diagnostics: Array<{ code: string; filename: string; severity: string; url?: string }>;
  number_of_files: number;
}

const typecheck = Bun.spawnSync(
  [typeScriptExecutable, "-p", tsconfig, "--noEmit", "--pretty", "false"],
  {
    cwd: tsRoot,
    stderr: "pipe",
    stdout: "pipe",
  },
);
if (
  typecheck.exitCode !== 0 ||
  typecheck.stdout.byteLength !== 0 ||
  typecheck.stderr.byteLength !== 0
) {
  throw new Error(
    `type-aware lint fixture does not typecheck:\n${typecheck.stdout.toString()}${typecheck.stderr.toString()}`.trim(),
  );
}

const result = Bun.spawnSync(
  [
    oxlintExecutable,
    "--type-aware",
    "--tsconfig",
    tsconfig,
    "--deny",
    diagnostic,
    "--format",
    "json",
    fixture,
  ],
  {
    cwd: tsRoot,
    stderr: "pipe",
    stdout: "pipe",
  },
);
const stdout = result.stdout.toString();
const stderr = result.stderr.toString();

if (result.exitCode === 0) {
  throw new Error("type-aware lint fixture unexpectedly passed");
}
if (stderr !== "") {
  throw new Error(`type-aware lint wrote to stderr:\n${stderr.trim()}`);
}

let output: OxlintOutput;
try {
  output = JSON.parse(stdout) as OxlintOutput;
} catch {
  throw new Error(`type-aware lint did not return JSON:\n${stdout.trim()}`);
}
if (output.number_of_files !== 1) {
  throw new Error(`type-aware lint checked ${output.number_of_files} files instead of 1`);
}
if (output.diagnostics.length !== 1) {
  throw new Error(`type-aware lint produced extra or missing diagnostics:\n${stdout.trim()}`);
}
const entry = output.diagnostics[0]!;
if (
  entry.code !== "typescript(no-floating-promises)" ||
  entry.filename !== fixture ||
  entry.severity !== "error" ||
  !entry.url?.endsWith(`/${diagnostic}.html`)
) {
  throw new Error(`missing exact ${diagnostic} diagnostic for ${fixture}:\n${stdout.trim()}`);
}

console.log("Type-aware lint fixture produced typescript/no-floating-promises with nonzero status");
