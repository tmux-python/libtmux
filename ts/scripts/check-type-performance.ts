import { createHash, randomUUID } from "node:crypto";
import { lstat, open, readFile, readlink, realpath, rename, unlink } from "node:fs/promises";
import { isAbsolute, join, relative, resolve, sep } from "node:path";
import { spawnSync } from "node:child_process";

type Mode = "check" | "update";

interface CompilerIdentity {
  readonly package: "typescript";
  readonly packageJsonSha256: string;
  readonly version: string;
}

interface InputDigest {
  readonly path: string;
  readonly sha256: string;
}

interface PerformanceBaseline {
  readonly compiler: CompilerIdentity;
  readonly inputs: readonly InputDigest[];
  readonly maxInstantiations: number;
  readonly schemaVersion: 1;
}

const baselineRelativePath = "tests/types/performance-baseline.json";
const compilerArguments = [
  "-p",
  "tests/types/tsconfig.performance.json",
  "--noEmit",
  "--incremental",
  "false",
  "--extendedDiagnostics",
  "--pretty",
  "false",
] as const;
const compilerPackageRelativePath = "node_modules/typescript/package.json";
const directCompilerRelativePath = "node_modules/typescript/bin/tsc";
const localCompilerRelativePath = "node_modules/.bin/tsc";
const performanceConfigRelativePath = "tests/types/tsconfig.performance.json";
const sha256Pattern = /^[0-9a-f]{64}$/;
const exactTypeScriptVersionPattern = /^7\.\d+\.\d+$/;

function fail(message: string): never {
  throw new Error(message);
}

function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function objectAt(value: unknown, path: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    fail(`${path} must be an object`);
  }
  return value as Record<string, unknown>;
}

function exactKeys(object: Record<string, unknown>, keys: readonly string[], path: string): void {
  const actual = Object.keys(object).sort((left, right) => left.localeCompare(right));
  const expected = [...keys].sort((left, right) => left.localeCompare(right));
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    fail(`${path} must contain exactly: ${expected.join(", ")}`);
  }
}

function parseJson(contents: string, path: string): unknown {
  try {
    return JSON.parse(contents) as unknown;
  } catch {
    fail(`${path} must contain valid JSON`);
  }
}

function contained(root: string, candidate: string): boolean {
  const fromRoot = relative(root, candidate);
  return fromRoot !== ".." && !fromRoot.startsWith(`..${sep}`) && !isAbsolute(fromRoot);
}

function projectRelativePath(root: string, path: string): string {
  const fromRoot = relative(root, path);
  if (fromRoot === "" || !contained(root, path)) fail("performance input escapes project root");
  return fromRoot.split(sep).join("/");
}

async function compilerIdentity(root: string): Promise<CompilerIdentity> {
  const packagePath = join(root, compilerPackageRelativePath);
  const packageContents = await readFile(packagePath);
  const packageManifest = objectAt(
    parseJson(packageContents.toString("utf8"), compilerPackageRelativePath),
    "compiler package",
  );
  const compilerName = packageManifest.name;
  const compilerVersion = packageManifest.version;
  const compilerBin = objectAt(packageManifest.bin, "compiler package bin");
  if (compilerName !== "typescript") fail("compiler package name must be typescript");
  if (typeof compilerVersion !== "string" || !exactTypeScriptVersionPattern.test(compilerVersion)) {
    fail("compiler package version must be an exact TypeScript 7 version");
  }
  exactKeys(compilerBin, ["tsc"], "compiler package bin");
  if (compilerBin.tsc !== "./bin/tsc") {
    fail("compiler package bin.tsc must be ./bin/tsc");
  }

  const packageManifestPath = join(root, "package.json");
  const rootManifest = objectAt(
    parseJson(await readFile(packageManifestPath, "utf8"), "package.json"),
    "package.json",
  );
  const developmentDependencies = objectAt(
    rootManifest.devDependencies,
    "package.json devDependencies",
  );
  if (developmentDependencies.typescript !== compilerVersion) {
    fail(
      `package.json devDependencies.typescript must exactly equal compiler version ${compilerVersion}`,
    );
  }

  const localCompiler = join(root, localCompilerRelativePath);
  const directCompiler = join(root, directCompilerRelativePath);
  if (!(await lstat(localCompiler)).isSymbolicLink()) {
    fail(`${localCompilerRelativePath} must be a symlink`);
  }
  if ((await readlink(localCompiler)) !== "../typescript/bin/tsc") {
    fail(`${localCompilerRelativePath} must target ../typescript/bin/tsc`);
  }
  if ((await realpath(localCompiler)) !== (await realpath(directCompiler))) {
    fail(`${localCompilerRelativePath} must resolve to ${directCompilerRelativePath}`);
  }

  return {
    package: "typescript",
    version: compilerVersion,
    packageJsonSha256: sha256(packageContents),
  };
}

async function discoverInputs(root: string): Promise<readonly InputDigest[]> {
  const configPaths = new Set<string>();
  const inputPaths = new Set<string>();

  async function visitConfig(configPath: string): Promise<void> {
    const absoluteConfigPath = resolve(configPath);
    if (!contained(root, absoluteConfigPath)) fail("performance tsconfig escapes project root");
    if (configPaths.has(absoluteConfigPath)) fail("performance tsconfig extends cycle detected");
    configPaths.add(absoluteConfigPath);
    inputPaths.add(absoluteConfigPath);

    const relativeConfigPath = projectRelativePath(root, absoluteConfigPath);
    const config = objectAt(
      parseJson(await readFile(absoluteConfigPath, "utf8"), relativeConfigPath),
      relativeConfigPath,
    );
    if (config.extends !== undefined) {
      if (typeof config.extends !== "string" || !config.extends.startsWith(".")) {
        fail(`${relativeConfigPath}.extends must be a local relative path`);
      }
      const extendedPath = config.extends.endsWith(".json")
        ? config.extends
        : `${config.extends}.json`;
      await visitConfig(resolve(absoluteConfigPath, "..", extendedPath));
    }
    if (config.files !== undefined) {
      if (
        !Array.isArray(config.files) ||
        config.files.some((file) => typeof file !== "string" || file.length === 0)
      ) {
        fail(`${relativeConfigPath}.files must be a string array`);
      }
      for (const file of config.files as string[]) {
        const absoluteInputPath = resolve(absoluteConfigPath, "..", file);
        if (!contained(root, absoluteInputPath)) {
          fail(`${relativeConfigPath}.files contains a path outside the project root`);
        }
        inputPaths.add(absoluteInputPath);
      }
    }
  }

  await visitConfig(join(root, performanceConfigRelativePath));
  return await Promise.all(
    [...inputPaths]
      .map((path) => projectRelativePath(root, path))
      .sort((left, right) => left.localeCompare(right))
      .map(async (path) => ({ path, sha256: sha256(await readFile(join(root, path))) })),
  );
}

function parseBaseline(contents: string): PerformanceBaseline {
  const baseline = objectAt(parseJson(contents, "baseline"), "baseline");
  exactKeys(baseline, ["schemaVersion", "compiler", "inputs", "maxInstantiations"], "baseline");
  if (baseline.schemaVersion !== 1) fail("baseline.schemaVersion must be 1");
  if (!Number.isSafeInteger(baseline.maxInstantiations) || Number(baseline.maxInstantiations) < 0) {
    fail("baseline.maxInstantiations must be a non-negative safe integer");
  }

  const compiler = objectAt(baseline.compiler, "baseline.compiler");
  exactKeys(compiler, ["package", "version", "packageJsonSha256"], "baseline.compiler");
  if (compiler.package !== "typescript") fail("baseline.compiler.package must be typescript");
  if (
    typeof compiler.version !== "string" ||
    !exactTypeScriptVersionPattern.test(compiler.version)
  ) {
    fail("baseline.compiler.version must be an exact TypeScript 7 version");
  }
  if (
    typeof compiler.packageJsonSha256 !== "string" ||
    !sha256Pattern.test(compiler.packageJsonSha256)
  ) {
    fail("baseline.compiler.packageJsonSha256 must be a lowercase SHA-256 digest");
  }

  if (!Array.isArray(baseline.inputs) || baseline.inputs.length === 0) {
    fail("baseline.inputs must be a non-empty array");
  }
  const inputs = baseline.inputs.map((value, index): InputDigest => {
    const input = objectAt(value, `baseline.inputs[${index}]`);
    exactKeys(input, ["path", "sha256"], `baseline.inputs[${index}]`);
    if (typeof input.path !== "string" || input.path.length === 0) {
      fail(`baseline.inputs[${index}].path must be a non-empty string`);
    }
    if (typeof input.sha256 !== "string" || !sha256Pattern.test(input.sha256)) {
      fail(`baseline.inputs[${index}].sha256 must be a lowercase SHA-256 digest`);
    }
    return { path: input.path, sha256: input.sha256 };
  });
  const sortedInputPaths = inputs
    .map((input) => input.path)
    .sort((left, right) => left.localeCompare(right));
  if (JSON.stringify(inputs.map((input) => input.path)) !== JSON.stringify(sortedInputPaths)) {
    fail("baseline.inputs must be path-sorted");
  }

  return {
    schemaVersion: 1,
    compiler: {
      package: "typescript",
      version: compiler.version,
      packageJsonSha256: compiler.packageJsonSha256,
    },
    inputs,
    maxInstantiations: Number(baseline.maxInstantiations),
  };
}

function validateBaseline(
  baseline: PerformanceBaseline,
  compiler: CompilerIdentity,
  inputs: readonly InputDigest[],
): void {
  if (baseline.compiler.version !== compiler.version) {
    fail("baseline compiler version does not match the local compiler");
  }
  if (baseline.compiler.packageJsonSha256 !== compiler.packageJsonSha256) {
    fail("baseline compiler package.json sha256 does not match the local compiler");
  }
  if (baseline.inputs.length !== inputs.length) fail("baseline input inventory does not match");
  for (let index = 0; index < inputs.length; index += 1) {
    const expected = baseline.inputs[index]!;
    const actual = inputs[index]!;
    if (expected.path !== actual.path) fail("baseline input inventory does not match");
    if (expected.sha256 !== actual.sha256) fail(`input sha256 mismatch: ${actual.path}`);
  }
}

function runCompiler(root: string, arguments_: readonly string[]): string {
  const result = spawnSync(join(root, localCompilerRelativePath), [...arguments_], {
    cwd: root,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
  });
  if (result.error) fail(`compiler execution failed: ${result.error.message}`);
  if (result.status !== 0) {
    fail(`compiler exited with status ${String(result.status)}: ${result.stderr.trim()}`);
  }
  if (result.stderr !== "") fail(`compiler wrote to stderr: ${result.stderr.trim()}`);
  return result.stdout;
}

function measureInstantiations(root: string, expectedVersion: string): number {
  const versionOutput = runCompiler(root, ["--version"]);
  const versionMatch = /^Version (\d+\.\d+\.\d+)\r?\n?$/.exec(versionOutput);
  if (!versionMatch || versionMatch[1] !== expectedVersion) {
    fail("compiler version output does not match the installed compiler version");
  }

  const diagnostics = runCompiler(root, compilerArguments);
  const matches = diagnostics
    .split(/\r?\n/u)
    .map((line) => /^Instantiations:\s*(\d+)\s*$/u.exec(line))
    .filter((match): match is RegExpExecArray => match !== null);
  if (matches.length !== 1) fail("compiler output must contain exactly one Instantiations metric");
  const instantiations = Number(matches[0]![1]);
  if (!Number.isSafeInteger(instantiations) || instantiations <= 0) {
    fail("Instantiations must be a positive safe integer");
  }
  return instantiations;
}

async function atomicWrite(path: string, contents: string): Promise<void> {
  const temporaryPath = `${path}.${process.pid}.${randomUUID()}.tmp`;
  try {
    const handle = await open(temporaryPath, "wx", 0o644);
    try {
      await handle.writeFile(contents);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await rename(temporaryPath, path);
  } catch (error) {
    await unlink(temporaryPath).catch(() => undefined);
    throw error;
  }
}

async function run(mode: Mode): Promise<void> {
  const root = resolve(process.cwd());
  const compiler = await compilerIdentity(root);
  const inputs = await discoverInputs(root);
  const baselinePath = join(root, baselineRelativePath);

  let baseline: PerformanceBaseline | undefined;
  if (mode === "check") {
    let baselineContents: string;
    try {
      baselineContents = await readFile(baselinePath, "utf8");
    } catch {
      fail(`baseline is missing: ${baselineRelativePath}`);
    }
    baseline = parseBaseline(baselineContents);
    validateBaseline(baseline, compiler, inputs);
  }

  const instantiations = measureInstantiations(root, compiler.version);
  const maxInstantiations = mode === "update" ? instantiations : baseline!.maxInstantiations;
  if (instantiations > maxInstantiations) {
    fail(`Instantiations ${instantiations} exceed baseline maximum ${maxInstantiations}`);
  }

  if (mode === "update") {
    const updatedBaseline: PerformanceBaseline = {
      schemaVersion: 1,
      compiler,
      inputs,
      maxInstantiations,
    };
    await atomicWrite(baselinePath, `${JSON.stringify(updatedBaseline, null, 2)}\n`);
  }

  process.stdout.write(
    `${JSON.stringify({
      protocol: "libtmux-type-performance-v1",
      mode,
      compilerVersion: compiler.version,
      instantiations,
      maxInstantiations,
      status: "passed",
    })}\n`,
  );
}

const argument = process.argv[2];
if ((argument !== "--check" && argument !== "--update") || process.argv.length !== 3) {
  process.stderr.write("usage: bun scripts/check-type-performance.ts (--check|--update)\n");
  process.exitCode = 2;
} else {
  try {
    await run(argument === "--check" ? "check" : "update");
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`${message}\n`);
    process.exitCode = 1;
  }
}
