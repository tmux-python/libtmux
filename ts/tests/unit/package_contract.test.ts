import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import type { BunConnectionOptions } from "node:tls";

import { describe, expect, test } from "bun:test";

interface PackageManifest {
  author: string;
  bugs: Record<string, string>;
  dependencies: Record<string, string>;
  description: string;
  keywords: string[];
  license: string;
  repository: Record<string, string>;
  devDependencies: Record<string, string>;
  engines: Record<string, string>;
  exports: Record<string, string | Record<string, string>>;
  files: string[];
  main: string;
  name: string;
  overrides: Record<string, string>;
  packageManager: string;
  private: boolean;
  scripts: Record<string, string>;
  sideEffects: boolean;
  trustedDependencies: string[];
  type: string;
  types: string;
  version: string;
}

interface TypeScriptConfig {
  compilerOptions?: Record<string, unknown>;
  exclude?: string[];
  files?: string[];
  include?: string[];
}

const expectedScripts = {
  build:
    "bun run generate:check && rm -rf dist && tsc -p tsconfig.build.json && bun scripts/normalize-source-map.ts dist/index.js.map",
  format: "oxfmt --write .",
  "format:check": "oxfmt --check .",
  generate: "bun scripts/generate-formats.ts --write",
  "generate:check": "bun scripts/generate-formats.ts --check",
  lint: "oxlint . --ignore-pattern tests/fixtures/type-aware-lint/** --deny-warnings --report-unused-disable-directives && bun scripts/check-type-aware-lint.ts",
  parity: "bun scripts/check-parity.ts",
  "test:differential": "bun scripts/run-differential-tests.ts",
  "test:integration": "bun scripts/run-integration-tests.ts",
  "test:node": "bun run build && bun scripts/test-node.ts --expect-major 22",
  "test:package": "bun run build && bun scripts/check-package.ts",
  "test:type-performance": "bun scripts/check-type-performance.ts --check",
  "test:types": "tsc -p tests/types/tsconfig.json --noEmit && bun run test:type-performance",
  typecheck: "tsc -p tsconfig.json --noEmit",
  "typecheck:consumers": "tsc -p tsconfig.consumers.json --noEmit",
  "typecheck:tooling": "tsc -p tsconfig.tooling.json --noEmit",
  "test:unit": "bun test --parallel=4 --no-orphans tests/unit",
};

const expectedDependencies = {
  zod: "4.4.3",
};

const expectedDevDependencies = {
  "@arethetypeswrong/cli": "0.18.5",
  // The MCP consumer lives under consumers/ and never enters the published
  // package, so the runtime dependency boundary stays at Zod alone.
  "@modelcontextprotocol/sdk": "1.30.0",
  "@types/bun": "1.3.14",
  "@types/node": "22.20.1",
  knip: "6.32.0",
  oxfmt: "0.62.0",
  oxlint: "1.77.0",
  "oxlint-tsgolint": "7.0.2001",
  publint: "0.3.23",
  typescript: "7.0.2",
};

const tsRoot = new URL("../..", import.meta.url);
const tsRootPath = fileURLToPath(tsRoot);
const bunTlsCompatibility: BunConnectionOptions = { key: [{ pem: "test key" }] };
void bunTlsCompatibility;

async function readJson<T>(relativePath: string): Promise<T> {
  return JSON.parse(await readFile(new URL(relativePath, tsRoot), "utf8")) as T;
}

async function runBoundedCommand(command: readonly string[], cwd: string) {
  const child = Bun.spawn([...command], { cwd, stderr: "pipe", stdout: "pipe" });
  let deadlineReached = false;
  const terminate = setTimeout(() => {
    deadlineReached = true;
    child.kill("SIGTERM");
  }, 10_000);
  const kill = setTimeout(() => child.kill("SIGKILL"), 10_500);
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

describe("package contract", () => {
  test("publishes only ESM root and package metadata entrypoints", async () => {
    const packageManifest = await readJson<PackageManifest>("package.json");

    // The root entrypoint is the surface a consumer actually imports.
    expect(Object.keys(await import("../../src/index.js")).toSorted()).toEqual([
      "Client",
      "DeprecatedError",
      "LibTmuxException",
      "MultipleMatchesError",
      "MultipleObjectsReturned",
      "NoMatchError",
      "ObjectDoesNotExist",
      "Pane",
      "QueryValidationError",
      "Server",
      "Session",
      "TmuxCommandError",
      "Window",
      "parseLegacyWhere",
    ]);
    expect(packageManifest.name).toBe("libtmux");
    expect(packageManifest.version).toBe("0.1.0");
    // Publication metadata is required for the package to be evaluated at all;
    // flipping `private` is the maintainer's release decision, not this gate's.
    expect(packageManifest.private).toBe(true);
    expect(packageManifest.license).toBe("MIT");
    expect(packageManifest.description).toContain("tmux");
    expect(packageManifest.repository).toEqual({
      type: "git",
      url: "git+https://github.com/tmux-python/libtmux.git",
      directory: "ts",
    });
    expect(packageManifest.bugs).toEqual({
      url: "https://github.com/tmux-python/libtmux/issues",
    });
    expect(packageManifest.author).toBe("libtmux contributors");
    expect(packageManifest.keywords).toContain("tmux");
    expect(packageManifest.type).toBe("module");
    expect(packageManifest.main).toBe("./dist/index.js");
    expect(packageManifest.types).toBe("./dist/index.d.ts");
    expect(packageManifest.files).toEqual(["dist", "!dist/_internal/test"]);
    expect(packageManifest.sideEffects).toBe(false);
    expect(packageManifest.trustedDependencies).toEqual([]);
    expect(Object.keys(packageManifest.exports)).toEqual([
      ".",
      "./package.json",
      "./common",
      "./exc",
      "./constants",
      "./formats",
      "./server",
      "./session",
      "./window",
      "./pane",
      "./client",
      "./selection",
    ]);
    expect(packageManifest.exports["."]).toEqual({
      types: "./dist/index.d.ts",
      import: "./dist/index.js",
      default: "./dist/index.js",
    });
    expect(Object.keys(packageManifest.exports["."]!)).toEqual(["types", "import", "default"]);
    expect(packageManifest.exports["./package.json"]).toBe("./package.json");
    expect(packageManifest.exports["./common"]).toEqual({
      types: "./dist/common.d.ts",
      import: "./dist/common.js",
      default: "./dist/common.js",
    });
    expect(packageManifest.exports["./exc"]).toEqual({
      types: "./dist/exc.d.ts",
      import: "./dist/exc.js",
      default: "./dist/exc.js",
    });
    expect(packageManifest.exports["./constants"]).toEqual({
      types: "./dist/constants.d.ts",
      import: "./dist/constants.js",
      default: "./dist/constants.js",
    });
    expect(packageManifest.exports["./formats"]).toEqual({
      types: "./dist/formats.d.ts",
      import: "./dist/formats.js",
      default: "./dist/formats.js",
    });
    for (const model of ["server", "session", "window", "pane", "client", "selection"]) {
      expect(packageManifest.exports[`./${model}`]).toEqual({
        types: `./dist/${model}.d.ts`,
        import: `./dist/${model}.js`,
        default: `./dist/${model}.js`,
      });
    }

    const serializedExports = JSON.stringify(packageManifest.exports);
    expect(serializedExports).not.toContain("require");
    expect(serializedExports).not.toContain("bun");
    expect(serializedExports).not.toContain("src/");
    expect(Object.keys(packageManifest.exports)).not.toContain("./*");
    expect(Object.keys(packageManifest.exports)).not.toContain("./dist/*");
  });

  test("pins the complete dependency boundary to the accepted runtime floors", async () => {
    const packageManifest = await readJson<PackageManifest>("package.json");

    expect(packageManifest.packageManager).toBe("bun@1.3.14");
    expect(packageManifest.engines).toEqual({ node: ">=22", bun: ">=1.3.14" });
    expect(packageManifest.dependencies).toEqual(expectedDependencies);
    expect(packageManifest.devDependencies).toEqual(expectedDevDependencies);
    expect(packageManifest.overrides).toEqual({ "@types/node": "22.20.1" });

    const lockfile = await readFile(new URL("bun.lock", tsRoot), "utf8");
    expect(lockfile).not.toContain('"bun-types/@types/node"');
  });

  test("exposes only runnable Task 5 scripts", async () => {
    const packageManifest = await readJson<PackageManifest>("package.json");

    expect(packageManifest.scripts).toEqual(expectedScripts);
  });

  test("isolates Node source types from Bun tooling types and invalid fixtures", async () => {
    const source = await readJson<TypeScriptConfig>("tsconfig.json");
    const build = await readJson<TypeScriptConfig>("tsconfig.build.json");
    const tooling = await readJson<TypeScriptConfig>("tsconfig.tooling.json");
    const lintFixture = await readJson<TypeScriptConfig>(
      "tests/fixtures/type-aware-lint/tsconfig.json",
    );

    expect(source.include).toEqual(["src/**/*.ts"]);
    expect(source.compilerOptions).toMatchObject({
      declaration: true,
      erasableSyntaxOnly: true,
      exactOptionalPropertyTypes: true,
      isolatedDeclarations: true,
      isolatedModules: true,
      lib: ["ES2024", "ESNext.Disposable"],
      module: "NodeNext",
      moduleResolution: "NodeNext",
      noUncheckedIndexedAccess: true,
      rootDir: "src",
      strict: true,
      target: "ES2024",
      types: ["node"],
      verbatimModuleSyntax: true,
    });
    expect(source.compilerOptions?.skipLibCheck).not.toBe(true);
    expect(build.compilerOptions).toMatchObject({
      declaration: true,
      declarationMap: false,
      inlineSources: true,
      noEmit: false,
      outDir: "dist",
      sourceMap: true,
    });
    expect(build.compilerOptions).not.toHaveProperty("sourceRoot");
    expect(tooling.compilerOptions?.types).toEqual(["bun", "node"]);
    expect(tooling.compilerOptions).not.toHaveProperty("paths");
    expect(tooling.files).toBeUndefined();
    expect(tooling.include).toEqual([
      "scripts/**/*.ts",
      "tests/differential/**/*.ts",
      "tests/integration/**/*.ts",
      "tests/unit/**/*.ts",
      "tests/fixtures/**/*.ts",
      "tests/support/**/*.ts",
    ]);
    expect(tooling.exclude).toContain("tests/types/**");
    expect(tooling.exclude).toContain("tests/fixtures/negative-declarations/**");
    expect(tooling.exclude).toContain("tests/fixtures/type-aware-lint/no_floating_promise.ts");
    expect(lintFixture.files).toEqual(["../../support/bun-tooling.d.ts"]);
  });

  test("proves the exact type-aware no-floating-promises diagnostic", async () => {
    const process = Bun.spawn(["bun", "scripts/check-type-aware-lint.ts"], {
      cwd: tsRootPath,
      stderr: "pipe",
      stdout: "pipe",
    });
    const [exitCode, stdout, stderr] = await Promise.all([
      process.exited,
      new Response(process.stdout).text(),
      new Response(process.stderr).text(),
    ]);

    expect(exitCode).toBe(0);
    expect(stderr).toBe("");
    expect(stdout.trim()).toBe(
      "Type-aware lint fixture produced typescript/no-floating-promises with nonzero status",
    );

    const harness = await readFile(new URL("scripts/check-type-aware-lint.ts", tsRoot), "utf8");
    expect(harness).toContain('"../node_modules/.bin/tsc"');
    expect(harness).toContain("output.diagnostics.length !== 1");
    expect(harness).toContain('entry.severity !== "error"');
    expect(harness).toContain("fileURLToPath");
    expect(tsRootPath).not.toContain("%20");
  });

  test("emits self-contained public declarations", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "ltx5-declarations-"));
    const outputDirectory = join(temporary, "types");
    const configPath = join(temporary, "tsconfig.json");
    await writeFile(
      configPath,
      `${JSON.stringify(
        {
          extends: join(tsRootPath, "tsconfig.build.json"),
          compilerOptions: {
            emitDeclarationOnly: true,
            inlineSources: false,
            outDir: outputDirectory,
            sourceMap: false,
            typeRoots: [join(tsRootPath, "node_modules/@types")],
          },
        },
        null,
        2,
      )}\n`,
    );
    try {
      const { exitCode, stderr, stdout } = await runBoundedCommand(
        [join(tsRootPath, "node_modules/.bin/tsc"), "-p", configPath],
        tsRootPath,
      );
      expect(exitCode, `${stdout}${stderr}`).toBe(0);

      const declarations = await Promise.all([
        readFile(join(outputDirectory, "index.d.ts"), "utf8"),
        readFile(join(outputDirectory, "formats.d.ts"), "utf8"),
      ]);
      // The root entrypoint now carries the public surface, so assert it names
      // the classes rather than that it is empty.
      for (const symbol of ["Server", "Session", "Window", "Pane", "Client", "Selection"]) {
        expect(declarations[0]).toContain(symbol);
      }
      // No public declaration may name an internal module or the runtime
      // plumbing behind it.
      const forbiddenEverywhere = [
        "_generated",
        "_internal",
        "Bun",
        "CommandTransport",
        "FormatProtocolError",
        "GuardCodec",
        "GuardFactory",
        "TmuxCapabilities",
        "Zod",
        "transport",
        "zod",
      ];
      for (const declaration of declarations) {
        for (const forbidden of forbiddenEverywhere) {
          expect(declaration).not.toContain(forbidden);
        }
      }
      // The format entrypoint additionally must not drag the model classes in;
      // the root entrypoint is where those legitimately live.
      expect(declarations[1]).not.toContain("Server");

      await writeFile(
        join(temporary, "package.json"),
        `${JSON.stringify(
          {
            exports: {
              ".": { types: "./types/index.d.ts" },
              "./formats": { types: "./types/formats.d.ts" },
              "./server": { types: "./types/server.d.ts" },
            },
            name: "libtmux",
            type: "module",
          },
          null,
          2,
        )}\n`,
      );
      await writeFile(
        join(temporary, "consumer.ts"),
        `import {
  CLIENT_FORMATS,
  FORMAT_SEPARATOR,
  PANE_FORMATS,
  SESSION_FORMATS,
  WINDOW_FORMATS,
} from "libtmux/formats";
import {
  Client,
  LibTmuxException,
  NoMatchError,
  Pane,
  Server,
  Session,
  Window,
  type CaptureOptions,
  type NewSessionOptions,
  type Selection,
  type ServerSnapshot,
  type SessionWhere,
} from "libtmux";
import { Server as ServerFromSubpath } from "libtmux/server";

// The root entrypoint must be usable exactly as a published consumer sees it.
declare const rootServer: Server;
declare const rootSnapshot: ServerSnapshot;
declare const rootSessions: Selection<Session>;
declare const rootWindow: Window;
declare const rootPane: Pane;
declare const rootClient: Client;
declare const rootCriteria: SessionWhere;
declare const rootCapture: CaptureOptions;
declare const rootNewSession: NewSessionOptions;
void [
  rootServer.snapshot,
  rootSnapshot.sessions,
  rootSessions.where(rootCriteria),
  rootWindow.panes,
  rootPane.capture(rootCapture),
  rootClient.session,
  rootServer.newSession(rootNewSession),
  LibTmuxException,
  NoMatchError,
  ServerFromSubpath,
];

void [CLIENT_FORMATS, FORMAT_SEPARATOR, PANE_FORMATS, SESSION_FORMATS, WINDOW_FORMATS];

// @ts-expect-error The format vocabulary is internal; there is no neo subpath.
void import("libtmux/neo");
// @ts-expect-error Internal package paths are not exported.
void import("libtmux/_internal/codec/guard_codec.js");
`,
      );
      const consumerConfigPath = join(temporary, "consumer-tsconfig.json");
      await writeFile(
        consumerConfigPath,
        `${JSON.stringify(
          {
            compilerOptions: {
              // Server.watch returns an async disposable, so a consumer needs
              // the lib that declares Symbol.asyncDispose. Requiring it is the
              // cost of shipping `await using`; the README states it.
              lib: ["ES2024", "ESNext.Disposable"],
              module: "NodeNext",
              moduleResolution: "NodeNext",
              noEmit: true,
              skipLibCheck: false,
              strict: true,
              target: "ES2024",
              types: [],
              verbatimModuleSyntax: true,
            },
            files: ["consumer.ts"],
          },
          null,
          2,
        )}\n`,
      );
      const consumer = await runBoundedCommand(
        [join(tsRootPath, "node_modules/.bin/tsc"), "-p", consumerConfigPath],
        temporary,
      );
      expect(consumer.exitCode, `${consumer.stdout}${consumer.stderr}`).toBe(0);
    } finally {
      await rm(temporary, { force: true, recursive: true });
    }
  }, 25_000);
});
