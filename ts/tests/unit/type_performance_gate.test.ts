import { createHash } from "node:crypto";
import {
  chmod,
  cp,
  lstat,
  mkdir,
  mkdtemp,
  open,
  readFile,
  readlink,
  readdir,
  realpath,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

interface Baseline {
  readonly compiler: {
    readonly package: "typescript";
    readonly packageJsonSha256: string;
    readonly version: string;
  };
  readonly inputs: readonly { readonly path: string; readonly sha256: string }[];
  readonly maxInstantiations: number;
  readonly schemaVersion: 1;
}

interface CheckerReport {
  readonly compilerVersion: string;
  readonly instantiations: number;
  readonly maxInstantiations: number;
  readonly mode: "check" | "update";
  readonly protocol: "libtmux-type-performance-v1";
  readonly status: "passed";
}

const scriptRelativePath = "scripts/check-type-performance.ts";
const baselineRelativePath = "tests/types/performance-baseline.json";
const repositoryRoot = fileURLToPath(new URL("../..", import.meta.url));
const repositoryCompiler = join(repositoryRoot, "node_modules/.bin/tsc");
const inputPaths = [
  "tests/tsconfig.performance.shared.json",
  "tests/types/stress.test.ts",
  "tests/types/tsconfig.performance.json",
  "tsconfig.json",
] as const;
const exactCompilerArguments = [
  "-p",
  "tests/types/tsconfig.performance.json",
  "--noEmit",
  "--incremental",
  "false",
  "--extendedDiagnostics",
  "--pretty",
  "false",
] as const;

interface CompilerInvocation {
  readonly argv: readonly string[];
  readonly cwd: string;
}

function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function compilerInvocationPath(root: string): string {
  return `${root}.tsc-invocations.jsonl`;
}

function fakeCompilerSource(root: string, diagnostics: string, compileExitCode = 0): string {
  return [
    "#!/usr/bin/env node",
    'import fs from "node:fs";',
    "const argv = process.argv.slice(2);",
    `const expectedCwd = ${JSON.stringify(root)};`,
    `const expectedCompile = ${JSON.stringify(exactCompilerArguments)};`,
    `fs.appendFileSync(${JSON.stringify(compilerInvocationPath(root))}, JSON.stringify({ argv, cwd: process.cwd() }) + "\\n");`,
    'if (process.cwd() !== expectedCwd) { console.error("unexpected tsc cwd"); process.exit(86); }',
    'if (JSON.stringify(argv) === JSON.stringify(["--version"])) { console.log("Version 7.0.2"); process.exit(0); }',
    `if (JSON.stringify(argv) === JSON.stringify(expectedCompile)) { console.log(${JSON.stringify(diagnostics)}); process.exit(${String(compileExitCode)}); }`,
    'console.error("unexpected tsc argv: " + JSON.stringify(argv));',
    "process.exit(86);",
    "",
  ].join("\n");
}

async function resetCompilerInvocations(root: string): Promise<void> {
  await writeFile(compilerInvocationPath(root), "");
}

async function readCompilerInvocations(root: string): Promise<readonly CompilerInvocation[]> {
  const contents = await readFile(compilerInvocationPath(root), "utf8");
  return contents
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as CompilerInvocation);
}

async function removeCheckerFixture(root: string): Promise<void> {
  await Promise.all([
    rm(root, { force: true, recursive: true }),
    rm(compilerInvocationPath(root), { force: true }),
  ]);
}

async function runBounded(command: readonly string[], cwd: string) {
  const child = Bun.spawn([...command], { cwd, stderr: "pipe", stdout: "pipe" });
  let deadlineReached = false;
  const terminate = setTimeout(() => {
    deadlineReached = true;
    child.kill("SIGTERM");
  }, 20_000);
  const kill = setTimeout(() => child.kill("SIGKILL"), 20_500);
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

async function directoryInventory(root: string, relativeDirectory = ""): Promise<string[]> {
  const entries = await readdir(join(root, relativeDirectory), { withFileTypes: true });
  const inventory = await Promise.all(
    entries
      .sort((left, right) => left.name.localeCompare(right.name))
      .map(async (entry) => {
        const relativeEntry = join(relativeDirectory, entry.name);
        const kind = entry.isDirectory() ? "directory" : entry.isFile() ? "file" : "symlink";
        return [
          `${kind}:${relativeEntry}`,
          ...(entry.isDirectory() ? await directoryInventory(root, relativeEntry) : []),
        ];
      }),
  );
  return inventory.flat();
}

async function snapshotTree(root: string, relativeDirectory = ""): Promise<readonly object[]> {
  const entries = await readdir(join(root, relativeDirectory), { withFileTypes: true });
  const rows = await Promise.all(
    entries
      .sort((left, right) => left.name.localeCompare(right.name))
      .map(async (entry): Promise<readonly object[]> => {
        const relativePath = join(relativeDirectory, entry.name);
        const absolutePath = join(root, relativePath);
        const stat = await lstat(absolutePath, { bigint: true });
        const metadata = {
          ctimeNs: stat.ctimeNs,
          inode: stat.ino,
          mode: stat.mode & 0o777n,
          mtimeNs: stat.mtimeNs,
          size: stat.size,
        };
        if (entry.isDirectory()) {
          return [
            { ...metadata, path: relativePath, type: "directory" },
            ...(await snapshotTree(root, relativePath)),
          ];
        }
        if (entry.isSymbolicLink()) {
          return [
            {
              ...metadata,
              path: relativePath,
              target: await readlink(absolutePath),
              type: "symlink",
            },
          ];
        }
        return [
          {
            ...metadata,
            path: relativePath,
            sha256: sha256(await readFile(absolutePath)),
            type: "file",
          },
        ];
      }),
  );
  return rows.flat();
}

async function runReadOnly(command: readonly string[], root: string) {
  const before = await snapshotTree(root);
  const result = await runBounded(command, root);
  expect(await snapshotTree(root)).toEqual(before);
  return result;
}

async function writeFixture(path: string, contents: string): Promise<void> {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, contents);
}

async function createCheckerFixture(root: string): Promise<void> {
  await mkdir(join(root, "scripts"), { recursive: true });
  await cp(
    new URL("../../node_modules/typescript", import.meta.url),
    join(root, "node_modules/typescript"),
    {
      recursive: true,
    },
  );
  await mkdir(join(root, "node_modules/.bin"), { recursive: true });
  const localCompiler = join(root, "node_modules/.bin/tsc");
  const directCompiler = join(root, "node_modules/typescript/bin/tsc");
  const compilerManifest = JSON.parse(
    await readFile(join(root, "node_modules/typescript/package.json"), "utf8"),
  ) as { readonly bin?: Readonly<Record<string, string>>; readonly name?: string };
  expect(compilerManifest.name).toBe("typescript");
  expect(compilerManifest.bin).toEqual({ tsc: "./bin/tsc" });
  await writeFile(directCompiler, fakeCompilerSource(root, "Instantiations: 12"));
  await chmod(directCompiler, 0o755);
  await symlink("../typescript/bin/tsc", localCompiler);
  expect((await lstat(localCompiler)).isSymbolicLink()).toBe(true);
  expect(await readlink(localCompiler)).toBe("../typescript/bin/tsc");
  expect(await realpath(localCompiler)).toBe(await realpath(directCompiler));
  await cp(new URL(`../../${scriptRelativePath}`, import.meta.url), join(root, scriptRelativePath));
  await writeFixture(
    join(root, "package.json"),
    `${JSON.stringify({ devDependencies: { typescript: "7.0.2" } }, null, 2)}\n`,
  );
  await writeFixture(
    join(root, "tsconfig.json"),
    `${JSON.stringify(
      {
        compilerOptions: {
          module: "NodeNext",
          moduleResolution: "NodeNext",
          strict: true,
          target: "ES2024",
        },
      },
      null,
      2,
    )}\n`,
  );
  await writeFixture(
    join(root, "tests/tsconfig.performance.shared.json"),
    `${JSON.stringify(
      {
        extends: "../tsconfig.json",
        compilerOptions: {
          noUncheckedIndexedAccess: true,
        },
      },
      null,
      2,
    )}\n`,
  );
  await writeFixture(
    join(root, "tests/types/tsconfig.performance.json"),
    `${JSON.stringify(
      {
        extends: "../tsconfig.performance.shared.json",
        compilerOptions: {
          declaration: false,
          incremental: false,
          isolatedDeclarations: false,
          noEmit: true,
        },
        files: ["stress.test.ts"],
      },
      null,
      2,
    )}\n`,
  );
  await writeFixture(
    join(root, "tests/types/stress.test.ts"),
    "type Pair<Value> = readonly [Value, Value];\n" +
      "type Nested = Pair<Pair<Pair<Pair<string>>>>;\n" +
      "void (null as unknown as Nested);\n",
  );
}

function decodeReport(stdout: string): CheckerReport {
  const lines = stdout.trim().split("\n");
  expect(lines).toHaveLength(1);
  const report = JSON.parse(lines[0]!) as CheckerReport;
  expect(report.protocol).toBe("libtmux-type-performance-v1");
  expect(report.status).toBe("passed");
  expect(report.compilerVersion).toBe("7.0.2");
  expect(report.instantiations).toBeGreaterThan(0);
  expect(report.maxInstantiations).toBeGreaterThanOrEqual(report.instantiations);
  return report;
}

async function readBaseline(root: string): Promise<Baseline> {
  return JSON.parse(await readFile(join(root, baselineRelativePath), "utf8")) as Baseline;
}

describe("TypeScript instantiation performance gate", () => {
  test("isolates the repository performance root to the stress declaration", async () => {
    const result = await runBounded(
      [
        repositoryCompiler,
        "-p",
        "tests/types/tsconfig.performance.json",
        "--showConfig",
        "--pretty",
        "false",
      ],
      repositoryRoot,
    );
    expect(result.exitCode, result.stderr).toBe(0);
    expect(result.stderr).toBe("");

    const resolved = JSON.parse(result.stdout) as {
      readonly files?: unknown;
      readonly include?: unknown;
    };
    expect(resolved.files).toEqual(["./stress.test.ts"]);
    expect(resolved.include).toBeUndefined();
  });

  test("rejects a missing baseline without creating one", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-missing-baseline-"));
    try {
      await createCheckerFixture(temporary);
      const baselinePath = join(temporary, baselineRelativePath);
      expect(await Bun.file(baselinePath).exists()).toBe(false);
      const missing = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(missing.exitCode).not.toBe(0);
      expect(missing.stdout).toBe("");
      expect(missing.stderr).toContain("baseline");
      expect(await Bun.file(baselinePath).exists()).toBe(false);
    } finally {
      await removeCheckerFixture(temporary);
    }
  }, 90_000);

  test("updates atomically and checks compiler, complete input chain, and maximum", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-performance-"));
    try {
      await createCheckerFixture(temporary);
      const localCompiler = join(temporary, "node_modules/.bin/tsc");
      const directCompiler = join(temporary, "node_modules/typescript/bin/tsc");
      await resetCompilerInvocations(temporary);
      const update = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
      expect(update.exitCode, update.stderr).toBe(0);
      expect(update.stderr).toBe("");
      expect(await readCompilerInvocations(temporary)).toEqual([
        { argv: ["--version"], cwd: temporary },
        { argv: exactCompilerArguments, cwd: temporary },
      ]);
      const updateReport = decodeReport(update.stdout);
      expect(updateReport.mode).toBe("update");

      const baselinePath = join(temporary, baselineRelativePath);
      const baselineText = await readFile(baselinePath, "utf8");
      const baseline = JSON.parse(baselineText) as Baseline;
      const compilerPackage = await readFile(
        join(temporary, "node_modules/typescript/package.json"),
      );
      expect(Object.keys(baseline).sort()).toEqual([
        "compiler",
        "inputs",
        "maxInstantiations",
        "schemaVersion",
      ]);
      expect(baseline.schemaVersion).toBe(1);
      expect(baseline.compiler).toEqual({
        package: "typescript",
        packageJsonSha256: sha256(compilerPackage),
        version: "7.0.2",
      });
      expect(baseline.inputs).toEqual(
        await Promise.all(
          inputPaths.map(async (path) => ({
            path,
            sha256: sha256(await readFile(join(temporary, path))),
          })),
        ),
      );
      expect([...inputPaths]).toEqual(
        [...inputPaths].sort((left, right) => left.localeCompare(right)),
      );
      expect(baseline.maxInstantiations).toBe(updateReport.instantiations);

      const missingFlags = await runReadOnly(
        [localCompiler, ...exactCompilerArguments.slice(0, -2)],
        temporary,
      );
      expect(missingFlags.exitCode).toBe(86);
      expect(missingFlags.stderr).toContain("unexpected tsc argv");
      const reorderedFlags = await runReadOnly(
        [
          localCompiler,
          "--noEmit",
          "-p",
          "tests/types/tsconfig.performance.json",
          ...exactCompilerArguments.slice(3),
        ],
        temporary,
      );
      expect(reorderedFlags.exitCode).toBe(86);
      expect(reorderedFlags.stderr).toContain("unexpected tsc argv");
      const extraFlags = await runReadOnly(
        [localCompiler, ...exactCompilerArguments, "--listFiles"],
        temporary,
      );
      expect(extraFlags.exitCode).toBe(86);
      expect(extraFlags.stderr).toContain("unexpected tsc argv");
      const directPath = await runReadOnly([directCompiler, ...exactCompilerArguments], temporary);
      expect(directPath.exitCode, directPath.stderr).toBe(0);
      expect(directPath.stdout).toBe("Instantiations: 12\n");

      await resetCompilerInvocations(temporary);
      const check = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(check.exitCode, check.stderr).toBe(0);
      expect(check.stderr).toBe("");
      expect(await readCompilerInvocations(temporary)).toEqual([
        { argv: ["--version"], cwd: temporary },
        { argv: exactCompilerArguments, cwd: temporary },
      ]);
      const checkReport = decodeReport(check.stdout);
      expect(checkReport.mode).toBe("check");
      expect(checkReport.instantiations).toBe(updateReport.instantiations);
      expect(await readFile(baselinePath, "utf8")).toBe(baselineText);

      const underBudgetBaseline = {
        ...baseline,
        maxInstantiations: baseline.maxInstantiations + 10,
      };
      await writeFile(baselinePath, `${JSON.stringify(underBudgetBaseline, null, 2)}\n`);
      const underBudget = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(underBudget.exitCode, underBudget.stderr).toBe(0);
      const underBudgetReport = decodeReport(underBudget.stdout);
      expect(underBudgetReport.instantiations).toBe(updateReport.instantiations);
      expect(underBudgetReport.maxInstantiations).toBe(baseline.maxInstantiations + 10);

      const refreshed = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
      expect(refreshed.exitCode, refreshed.stderr).toBe(0);
      const refreshedBaseline = await readBaseline(temporary);
      await writeFile(
        baselinePath,
        `${JSON.stringify({ ...refreshedBaseline, maxInstantiations: 0 }, null, 2)}\n`,
      );
      const overBudgetText = await readFile(baselinePath, "utf8");
      const overBudget = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(overBudget.exitCode).not.toBe(0);
      expect(overBudget.stderr).toContain("Instantiations");
      expect(await readFile(baselinePath, "utf8")).toBe(overBudgetText);

      await writeFile(
        baselinePath,
        `${JSON.stringify(
          {
            ...refreshedBaseline,
            compiler: { ...refreshedBaseline.compiler, version: "7.0.1" },
          },
          null,
          2,
        )}\n`,
      );
      const compilerMismatch = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(compilerMismatch.exitCode).not.toBe(0);
      expect(compilerMismatch.stderr).toContain("compiler");

      const invalidBaseline = { ...refreshedBaseline, unexpected: true };
      await writeFile(baselinePath, `${JSON.stringify(invalidBaseline, null, 2)}\n`);
      const unknownField = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(unknownField.exitCode).not.toBe(0);
      expect(unknownField.stderr).toContain("baseline");

      await Promise.all(
        [[], ["--write"], ["--check", "extra"]].map(async (arguments_) => {
          const invalidCli = await runReadOnly(
            ["bun", scriptRelativePath, ...arguments_],
            temporary,
          );
          expect(invalidCli.exitCode).toBe(2);
          expect(invalidCli.stderr).toContain("usage:");
        }),
      );

      const typeDirectory = join(temporary, "tests/types");
      expect((await readdir(typeDirectory)).sort()).toEqual([
        "performance-baseline.json",
        "stress.test.ts",
        "tsconfig.performance.json",
      ]);
      expect((await lstat(baselinePath)).isFile()).toBe(true);
    } finally {
      await removeCheckerFixture(temporary);
    }
  }, 90_000);

  test.each([
    {
      mutate: (baseline: Baseline) => ({ ...baseline, schemaVersion: 2 }),
      name: "a changed schemaVersion",
    },
    {
      mutate: (baseline: Baseline) => ({
        ...baseline,
        compiler: { ...baseline.compiler, unexpected: true },
      }),
      name: "an unknown nested compiler key",
    },
    {
      mutate: (baseline: Baseline) => ({
        ...baseline,
        inputs: baseline.inputs.map((input, index) =>
          index === 0 ? { ...input, unexpected: true } : input,
        ),
      }),
      name: "an unknown nested input key",
    },
    {
      mutate: (baseline: Baseline) => ({ ...baseline, inputs: baseline.inputs.slice(0, -1) }),
      name: "a missing input",
    },
    {
      mutate: (baseline: Baseline) => ({
        ...baseline,
        inputs: [
          ...baseline.inputs,
          { path: "tests/types/untracked.test.ts", sha256: "0".repeat(64) },
        ],
      }),
      name: "an extra input",
    },
    {
      mutate: (baseline: Baseline) => ({ ...baseline, inputs: [...baseline.inputs].reverse() }),
      name: "reordered inputs",
    },
  ])(
    "rejects $name without writing",
    async ({ mutate }) => {
      const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-invalid-baseline-"));
      try {
        await createCheckerFixture(temporary);
        const update = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
        expect(update.exitCode, update.stderr).toBe(0);
        const baselinePath = join(temporary, baselineRelativePath);
        const baseline = await readBaseline(temporary);
        await writeFile(baselinePath, `${JSON.stringify(mutate(baseline), null, 2)}\n`);

        const invalid = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
        expect(invalid.exitCode).not.toBe(0);
        expect(invalid.stdout).toBe("");
        expect(invalid.stderr).not.toBe("");
      } finally {
        await removeCheckerFixture(temporary);
      }
    },
    90_000,
  );

  test("atomically replaces an existing baseline without exposing partial bytes", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-atomic-update-"));
    try {
      await createCheckerFixture(temporary);
      const initialUpdate = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
      expect(initialUpdate.exitCode, initialUpdate.stderr).toBe(0);
      expect(decodeReport(initialUpdate.stdout).instantiations).toBe(12);

      const baselinePath = join(temporary, baselineRelativePath);
      const oldBaselineText = await readFile(baselinePath, "utf8");
      const oldBaseline = JSON.parse(oldBaselineText) as Baseline;
      expect(oldBaseline.maxInstantiations).toBe(12);
      const oldBaselineHandle = await open(baselinePath, "r");
      try {
        const localCompiler = join(temporary, "node_modules/.bin/tsc");
        await writeFile(localCompiler, fakeCompilerSource(temporary, "Instantiations: 34"));
        await chmod(localCompiler, 0o755);
        await resetCompilerInvocations(temporary);
        const inventoryBefore = await directoryInventory(temporary);
        const expectedNewBaselineText = `${JSON.stringify(
          {
            schemaVersion: 1,
            compiler: oldBaseline.compiler,
            inputs: oldBaseline.inputs,
            maxInstantiations: 34,
          },
          null,
          2,
        )}\n`;
        expect(expectedNewBaselineText).not.toBe(oldBaselineText);

        const replacement = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
        expect(replacement.exitCode, replacement.stderr).toBe(0);
        expect(replacement.stderr).toBe("");
        const replacementReport = decodeReport(replacement.stdout);
        expect(replacementReport.instantiations).toBe(34);
        expect(replacementReport.maxInstantiations).toBe(34);

        expect(await oldBaselineHandle.readFile({ encoding: "utf8" })).toBe(oldBaselineText);
        expect(await readFile(baselinePath, "utf8")).toBe(expectedNewBaselineText);
        expect(await directoryInventory(temporary)).toEqual(inventoryBefore);
        expect((await readdir(join(temporary, "tests/types"))).sort()).toEqual([
          "performance-baseline.json",
          "stress.test.ts",
          "tsconfig.performance.json",
        ]);
      } finally {
        await oldBaselineHandle.close();
      }
    } finally {
      await removeCheckerFixture(temporary);
    }
  }, 90_000);

  test.each([
    {
      inputPath: "tests/tsconfig.performance.shared.json",
      needle: '"noUncheckedIndexedAccess": true',
      replacement: '"noUncheckedIndexedAccess": false',
    },
    {
      inputPath: "tests/types/stress.test.ts",
      needle: "type Pair<Value>",
      replacement: "type DriftedPair<Value>",
    },
    {
      inputPath: "tests/types/tsconfig.performance.json",
      needle: '"noEmit": true',
      replacement: '"noEmit": false',
    },
    {
      inputPath: "tsconfig.json",
      needle: '"target": "ES2024"',
      replacement: '"target": "ES2023"',
    },
  ])(
    "rejects valid-baseline digest drift in $inputPath without writing",
    async ({ inputPath, needle, replacement }) => {
      const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-input-drift-"));
      try {
        await createCheckerFixture(temporary);
        const update = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
        expect(update.exitCode, update.stderr).toBe(0);

        const absoluteInputPath = join(temporary, inputPath);
        const original = await readFile(absoluteInputPath, "utf8");
        const drifted = original.replace(needle, replacement);
        expect(drifted).not.toBe(original);
        await writeFile(absoluteInputPath, drifted);

        const mismatch = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
        expect(mismatch.exitCode).not.toBe(0);
        expect(mismatch.stdout).toBe("");
        expect(mismatch.stderr).toBe(`input sha256 mismatch: ${inputPath}\n`);
      } finally {
        await removeCheckerFixture(temporary);
      }
    },
    90_000,
  );

  test("rejects a root devDependency that does not pin the running compiler", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-dependency-"));
    try {
      await createCheckerFixture(temporary);
      const update = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
      expect(update.exitCode, update.stderr).toBe(0);

      await writeFile(
        join(temporary, "package.json"),
        `${JSON.stringify({ devDependencies: { typescript: "7.0.1" } }, null, 2)}\n`,
      );
      const mismatch = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(mismatch.exitCode).not.toBe(0);
      expect(mismatch.stderr).toContain("devDependencies.typescript");
    } finally {
      await removeCheckerFixture(temporary);
    }
  }, 90_000);

  test.each(["^7.0.2", "~7.0.2", ">=7.0.2", "7.0.x", "latest"])(
    "rejects non-exact dependency range %s during update",
    async (range) => {
      const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-update-range-"));
      try {
        await createCheckerFixture(temporary);
        await writeFile(
          join(temporary, "package.json"),
          `${JSON.stringify({ devDependencies: { typescript: range } }, null, 2)}\n`,
        );
        const ranged = await runReadOnly(["bun", scriptRelativePath, "--update"], temporary);
        expect(ranged.exitCode, range).not.toBe(0);
        expect(ranged.stdout).toBe("");
        expect(ranged.stderr).toContain("devDependencies.typescript");
      } finally {
        await removeCheckerFixture(temporary);
      }
    },
    90_000,
  );

  test("rejects installed-package version disagreement during update", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-update-version-"));
    try {
      await createCheckerFixture(temporary);
      const compilerPackagePath = join(temporary, "node_modules/typescript/package.json");
      const compilerPackage = JSON.parse(await readFile(compilerPackagePath, "utf8")) as Record<
        string,
        unknown
      >;
      await writeFile(
        compilerPackagePath,
        `${JSON.stringify({ ...compilerPackage, version: "7.0.1" }, null, 2)}\n`,
      );
      const disagreement = await runReadOnly(["bun", scriptRelativePath, "--update"], temporary);
      expect(disagreement.exitCode).not.toBe(0);
      expect(disagreement.stdout).toBe("");
      expect(disagreement.stderr).toContain("compiler");
      expect(disagreement.stderr).toContain("version");
    } finally {
      await removeCheckerFixture(temporary);
    }
  }, 90_000);

  test("rejects compiler executables outside the package-declared bin symlink", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-compiler-provenance-"));
    try {
      await createCheckerFixture(temporary);
      const update = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
      expect(update.exitCode, update.stderr).toBe(0);

      const localCompiler = join(temporary, "node_modules/.bin/tsc");
      const compilerPackagePath = join(temporary, "node_modules/typescript/package.json");
      const spoofCompiler = join(temporary, "node_modules/typescript/bin/spoof-tsc");

      await rm(localCompiler, { force: true });
      await writeFile(localCompiler, fakeCompilerSource(temporary, "Instantiations: 12"));
      await chmod(localCompiler, 0o755);
      const regularExecutable = await runReadOnly(
        ["bun", scriptRelativePath, "--check"],
        temporary,
      );
      expect(regularExecutable.exitCode).not.toBe(0);
      expect(regularExecutable.stderr).not.toBe("");

      await rm(localCompiler, { force: true });
      await writeFile(spoofCompiler, fakeCompilerSource(temporary, "Instantiations: 12"));
      await chmod(spoofCompiler, 0o755);
      await symlink("../typescript/bin/spoof-tsc", localCompiler);
      const wrongSymlink = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(wrongSymlink.exitCode).not.toBe(0);
      expect(wrongSymlink.stderr).not.toBe("");

      const compilerPackage = JSON.parse(await readFile(compilerPackagePath, "utf8")) as Record<
        string,
        unknown
      >;
      await writeFile(
        compilerPackagePath,
        `${JSON.stringify({ ...compilerPackage, bin: { tsc: "./bin/spoof-tsc" } }, null, 2)}\n`,
      );
      const poisonedPackageBin = await runReadOnly(
        ["bun", scriptRelativePath, "--update"],
        temporary,
      );
      expect(poisonedPackageBin.exitCode).not.toBe(0);
      expect(poisonedPackageBin.stderr).not.toBe("");
    } finally {
      await removeCheckerFixture(temporary);
    }
  }, 90_000);

  test("rejects a compiler package digest mismatch even when its version is unchanged", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-compiler-digest-"));
    try {
      await createCheckerFixture(temporary);
      const update = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
      expect(update.exitCode, update.stderr).toBe(0);

      const compilerPackagePath = join(temporary, "node_modules/typescript/package.json");
      const compilerPackage = JSON.parse(await readFile(compilerPackagePath, "utf8")) as Record<
        string,
        unknown
      >;
      await writeFile(
        compilerPackagePath,
        `${JSON.stringify({ ...compilerPackage, digestMutation: true }, null, 2)}\n`,
      );
      const mismatch = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(mismatch.exitCode).not.toBe(0);
      expect(mismatch.stderr).toContain("compiler");
      expect(mismatch.stderr).toContain("sha256");
    } finally {
      await removeCheckerFixture(temporary);
    }
  }, 90_000);

  test("rejects missing and duplicate anchored Instantiations metrics", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-type-metric-"));
    try {
      await createCheckerFixture(temporary);
      const firstUpdate = await runBounded(["bun", scriptRelativePath, "--update"], temporary);
      expect(firstUpdate.exitCode, firstUpdate.stderr).toBe(0);
      const compilerCli = join(temporary, "node_modules/.bin/tsc");
      const realCompiler = await readFile(compilerCli);
      const realMode = (await lstat(compilerCli)).mode;

      await writeFile(compilerCli, fakeCompilerSource(temporary, "prefix Instantiations: 12"));
      await chmod(compilerCli, 0o755);
      const missing = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(missing.exitCode).not.toBe(0);
      expect(missing.stderr).toContain("Instantiations");

      await writeFile(
        compilerCli,
        fakeCompilerSource(temporary, "Instantiations: 12\nInstantiations: 12"),
      );
      await chmod(compilerCli, 0o755);
      const duplicate = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(duplicate.exitCode).not.toBe(0);
      expect(duplicate.stderr).toContain("Instantiations");

      await writeFile(
        compilerCli,
        fakeCompilerSource(
          temporary,
          [
            "Files: 999999999",
            "Memory used: 999999999999999K",
            "Check time: 999999999.99s",
            "Instantiations: 12",
            "Total time: 999999999.99s",
          ].join("\n"),
        ),
      );
      await chmod(compilerCli, 0o755);
      const irrelevantDiagnostics = await runReadOnly(
        ["bun", scriptRelativePath, "--check"],
        temporary,
      );
      expect(irrelevantDiagnostics.exitCode, irrelevantDiagnostics.stderr).toBe(0);
      expect(decodeReport(irrelevantDiagnostics.stdout).instantiations).toBe(12);

      await writeFile(compilerCli, fakeCompilerSource(temporary, "Instantiations: 12", 9));
      await chmod(compilerCli, 0o755);
      const nonzeroCompiler = await runReadOnly(["bun", scriptRelativePath, "--check"], temporary);
      expect(nonzeroCompiler.exitCode).not.toBe(0);
      expect(nonzeroCompiler.stdout).toBe("");
      expect(nonzeroCompiler.stderr).not.toBe("");

      await writeFile(compilerCli, realCompiler);
      await chmod(compilerCli, realMode);
    } finally {
      await removeCheckerFixture(temporary);
    }
  }, 90_000);

  test("is registered cumulatively without weakening package exports", async () => {
    const manifest = JSON.parse(
      await readFile(new URL("../../package.json", import.meta.url), "utf8"),
    ) as {
      readonly exports: Readonly<Record<string, unknown>>;
      readonly scripts: Readonly<Record<string, string>>;
    };

    expect(manifest.scripts["test:type-performance"]).toBe(
      "bun scripts/check-type-performance.ts --check",
    );
    expect(manifest.scripts["test:types"]).toBe(
      "tsc -p tests/types/tsconfig.json --noEmit && bun run test:type-performance",
    );
    expect(Object.keys(manifest.exports)).not.toContain("./selection");
  });
});
