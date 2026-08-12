import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

import {
  generateFormats,
  renderGeneratedNeoTypeRegion,
  renderNeoWithGeneratedTypes,
  renderTask5ParityManifest,
} from "../../scripts/generate-formats.js";
import {
  CLIENT_FORMATS,
  FORMAT_SEPARATOR,
  PANE_FORMATS,
  SESSION_FORMATS,
  WINDOW_FORMATS,
} from "../../src/formats.js";
import type { FormatFieldName } from "../../src/neo.js";
import { FORMAT_FIELD_TOKENS } from "../../src/_generated/format_fields.js";
import { WHERE_ALIASES_V1, WHERE_FIELDS_V1 } from "../../src/_generated/where_fields.js";
import {
  FORMAT_REGISTRY,
  formatFieldsForListCommand,
  lookupFormatField,
  renderGeneratedFormatSources,
  validateWhereSchemaHistory,
} from "../../src/_internal/codec/format_registry.js";

type FormatScope =
  | "buffer"
  | "client"
  | "context"
  | "event"
  | "pane"
  | "session"
  | "universal"
  | "window";

interface PythonFormatFixture {
  baseline: {
    commit: string;
    neoSourceSha256: string;
    objFieldTokensSha256: string;
    pythonVersion: string;
    tag: string;
    tree: string;
  };
  fields: Array<{ scope: FormatScope; since: string; token: FormatFieldName }>;
}

const fixtureUrl = new URL("../fixtures/python-0.62.0-format-fields.json", import.meta.url);
const parityManifestUrl = new URL("../../parity/python-0.62.0.json", import.meta.url);
const tsRootPath = fileURLToPath(new URL("../..", import.meta.url));

async function readFixture(): Promise<PythonFormatFixture> {
  return JSON.parse(await readFile(fixtureUrl, "utf8")) as PythonFormatFixture;
}

async function runBoundedCommand(
  command: readonly string[],
  options: { readonly cwd?: string; readonly env?: NodeJS.ProcessEnv } = {},
) {
  const child = Bun.spawn([...command], {
    ...options,
    stderr: "pipe",
    stdout: "pipe",
  });
  let deadlineReached = false;
  const terminate = setTimeout(() => {
    deadlineReached = true;
    child.kill("SIGTERM");
  }, 5_000);
  const kill = setTimeout(() => child.kill("SIGKILL"), 5_500);
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

function runGeneratorCli(arguments_: readonly string[], cwd = tsRootPath) {
  return runBoundedCommand(["bun", "scripts/generate-formats.ts", ...arguments_], {
    cwd,
  });
}

describe("public format constants", () => {
  test("exports only the accepted runtime surface", async () => {
    expect(Object.keys(await import("../../src/formats.js")).sort()).toEqual([
      "CLIENT_FORMATS",
      "FORMAT_SEPARATOR",
      "PANE_FORMATS",
      "SESSION_FORMATS",
      "WINDOW_FORMATS",
    ]);
  });

  test("matches the Python 0.62.0 reference lists", () => {
    expect(FORMAT_SEPARATOR).toBe("␞");
    expect(SESSION_FORMATS).toEqual([
      "session_name",
      "session_windows",
      "session_width",
      "session_height",
      "session_id",
      "session_created",
      "session_created_string",
      "session_attached",
      "session_group",
    ]);
    expect(CLIENT_FORMATS).toEqual([
      "client_cwd",
      "client_height",
      "client_width",
      "client_tty",
      "client_termname",
      "client_created",
      "client_created_string",
      "client_activity",
      "client_activity_string",
      "client_prefix",
      "client_utf8",
      "client_readonly",
      "client_session",
      "client_last_session",
    ]);
    expect(WINDOW_FORMATS).toEqual([
      "window_id",
      "window_name",
      "window_width",
      "window_height",
      "window_layout",
      "window_panes",
      "window_index",
      "window_flags",
      "window_active",
      "window_bell_flag",
      "window_activity_flag",
      "window_silence_flag",
    ]);
    expect(PANE_FORMATS).toEqual([
      "history_size",
      "history_limit",
      "history_bytes",
      "pane_index",
      "pane_width",
      "pane_height",
      "pane_title",
      "pane_id",
      "pane_active",
      "pane_dead",
      "pane_in_mode",
      "pane_synchronized",
      "pane_tty",
      "pane_pid",
      "pane_start_command",
      "pane_start_path",
      "pane_current_path",
      "pane_current_command",
      "cursor_x",
      "cursor_y",
      "scroll_region_upper",
      "scroll_region_lower",
      "saved_cursor_x",
      "saved_cursor_y",
      "alternate_on",
      "alternate_saved_x",
      "alternate_saved_y",
      "cursor_flag",
      "insert_flag",
      "keypad_cursor_flag",
      "keypad_flag",
      "wrap_flag",
      "mouse_standard_flag",
      "mouse_button_flag",
      "mouse_any_flag",
      "mouse_utf8_flag",
      "pane_flags",
      "pane_floating_flag",
      "pane_x",
      "pane_y",
      "pane_z",
      "pane_zoomed_flag",
      "pane_pb_progress",
      "pane_pb_state",
      "pane_pipe_pid",
      "bracket_paste_flag",
      "synchronized_output_flag",
    ]);
    for (const value of [CLIENT_FORMATS, PANE_FORMATS, SESSION_FORMATS, WINDOW_FORMATS]) {
      expect(Object.isFrozen(value)).toBe(true);
    }
  });

  test("reads the separator override at import time without coupling guarded framing", async () => {
    const formatsUrl = new URL("../../src/formats.ts", import.meta.url).href;
    const capabilitiesUrl = new URL("../../src/_internal/runtime/capabilities.ts", import.meta.url)
      .href;
    const codecUrl = new URL("../../src/_internal/codec/guard_codec.ts", import.meta.url).href;
    const source = `
      const [{ FORMAT_SEPARATOR }, { deriveTmuxCapabilities }, { GuardCodec }] = await Promise.all([
        import(${JSON.stringify(formatsUrl)}),
        import(${JSON.stringify(capabilitiesUrl)}),
        import(${JSON.stringify(codecUrl)}),
      ]);
      const capabilities = deriveTmuxCapabilities({
        connectionAlias: "fresh-process",
        daemonEpoch: 1,
        rawVersion: "3.7b",
      });
      const request = new GuardCodec({ capabilities, listCommand: "list-sessions" }).prepare();
      process.stdout.write(JSON.stringify({
        formatContainsOverride: request.format.includes(FORMAT_SEPARATOR),
        separator: FORMAT_SEPARATOR,
      }));
    `;
    const { exitCode, stderr, stdout } = await runBoundedCommand(["bun", "-e", source], {
      env: { ...process.env, LIBTMUX_TMUX_FORMAT_SEPARATOR: "CUSTOM_SEPARATOR" },
    });

    expect(exitCode).toBe(0);
    expect(stderr).toBe("");
    expect(JSON.parse(stdout)).toEqual({
      formatContainsOverride: false,
      separator: "CUSTOM_SEPARATOR",
    });
  }, 7_000);
});

describe("format registry", () => {
  test("matches every pinned Python Obj token, scope, and version floor", async () => {
    const fixture = await readFixture();

    expect(Object.keys(fixture)).toEqual(["baseline", "fields"]);
    expect(Object.keys(fixture.baseline)).toEqual([
      "commit",
      "neoSourceSha256",
      "objFieldTokensSha256",
      "pythonVersion",
      "tag",
      "tree",
    ]);
    for (const field of fixture.fields) {
      expect(Object.keys(field)).toEqual(["scope", "since", "token"]);
    }
    expect(fixture.baseline).toEqual({
      commit: "38e368c11117fb4aeb2f082d552cd4f210eae06a",
      neoSourceSha256: "764264bf42bc305d1d97e9596806f004326c460e771f2a750429c75690afe82f",
      objFieldTokensSha256: "de09e5e1cf4d6749c3a9f77c211c0a1a94c7586559d8d08ed516f7c456f1c693",
      pythonVersion: "0.62.0",
      tag: "v0.62.0",
      tree: "eee900223a11c00a4b9b0cc6944e7d5a4d503bc8",
    });
    expect(
      FORMAT_REGISTRY.map(({ scope, since, token }) => ({ scope, since: since.raw, token })),
    ).toEqual(fixture.fields);
    expect(Object.isFrozen(FORMAT_REGISTRY)).toBe(true);
    expect(Object.isFrozen(FORMAT_FIELD_TOKENS)).toBe(true);
    for (const field of FORMAT_REGISTRY) {
      expect(Object.keys(field).sort(), field.token).toEqual([
        "criteriaWireNames",
        "rawRepresentation",
        "scalarFilterDomain",
        "scope",
        "since",
        "snapshotDestination",
        "token",
      ]);
      expect(Object.isFrozen(field), field.token).toBe(true);
      expect(Object.isFrozen(field.criteriaWireNames), field.token).toBe(true);
      expect(Object.isFrozen(field.since), field.token).toBe(true);
    }
    expect(new Set(FORMAT_REGISTRY.map(({ token }) => token)).size).toBe(178);
    expect(FORMAT_FIELD_TOKENS).toEqual(fixture.fields.map(({ token }) => token));
    expect(
      createHash("sha256")
        .update(JSON.stringify(fixture.fields.map(({ token }) => token)))
        .digest("hex"),
    ).toBe("de09e5e1cf4d6749c3a9f77c211c0a1a94c7586559d8d08ed516f7c456f1c693");
  });

  test("resolves every oracle token while unknown tokens fail closed", async () => {
    const fixture = await readFixture();
    const resolved = fixture.fields.map(({ token }) => lookupFormatField(token));

    expect(fixture.fields).toHaveLength(178);
    expect(FORMAT_REGISTRY).toHaveLength(fixture.fields.length);
    expect(resolved).not.toContain(undefined);
    expect(resolved).toEqual([...FORMAT_REGISTRY]);
    for (const [index, { token }] of fixture.fields.entries()) {
      expect(resolved[index], token).toBeDefined();
      expect(resolved[index]?.token, token).toBe(token);
      expect(resolved[index], token).toBe(FORMAT_REGISTRY[index]);
    }
    expect(lookupFormatField("libtmux_nonexistent_format_token")).toBeUndefined();
  });

  test("keeps raw, snapshot, and criteria destinations explicit", () => {
    expect(FORMAT_REGISTRY.every(({ rawRepresentation }) => rawRepresentation === "string")).toBe(
      true,
    );

    const destinationCases = [
      ["config_files", "server"],
      ["session_name", "session"],
      ["window_name", "window"],
      ["pane_id", "pane"],
      ["client_name", "client"],
      ["line", "raw-row"],
    ] as const;
    for (const [token, destination] of destinationCases) {
      expect(FORMAT_REGISTRY.find((field) => field.token === token)?.snapshotDestination).toBe(
        destination,
      );
    }

    const winlinkFields = [
      "window_active",
      "window_activity_flag",
      "window_bell_flag",
      "window_end_flag",
      "window_flags",
      "window_index",
      "window_last_flag",
      "window_marked_flag",
      "window_raw_flags",
      "window_silence_flag",
      "window_stack_index",
      "window_start_flag",
    ];
    const winlinkFieldSet = new Set(winlinkFields);
    for (const token of winlinkFields) {
      expect(FORMAT_REGISTRY.find((field) => field.token === token)?.snapshotDestination).toBe(
        "winlink",
      );
    }

    const rawRowWindowFields = [
      "window_bigger",
      "window_format",
      "window_offset_x",
      "window_offset_y",
    ];
    const rawRowWindowFieldSet = new Set(rawRowWindowFields);
    for (const token of rawRowWindowFields) {
      expect(FORMAT_REGISTRY.find((field) => field.token === token)?.snapshotDestination).toBe(
        "raw-row",
      );
    }

    for (const field of FORMAT_REGISTRY.filter(({ scope }) =>
      ["buffer", "context", "event"].includes(scope),
    )) {
      expect(field.snapshotDestination, field.token).toBe("raw-row");
    }

    for (const field of FORMAT_REGISTRY) {
      const expectedDestination = winlinkFieldSet.has(field.token)
        ? "winlink"
        : rawRowWindowFieldSet.has(field.token) ||
            field.token === "line" ||
            ["buffer", "context", "event"].includes(field.scope)
          ? "raw-row"
          : field.scope === "universal"
            ? "server"
            : field.scope === "client" ||
                field.scope === "pane" ||
                field.scope === "session" ||
                field.scope === "window"
              ? field.scope
              : "raw-row";
      expect(field.snapshotDestination, field.token).toBe(expectedDestination);
    }

    expect(new Set(FORMAT_REGISTRY.map(({ snapshotDestination }) => snapshotDestination))).toEqual(
      new Set(["server", "session", "window", "winlink", "pane", "client", "raw-row"]),
    );

    expect(FORMAT_REGISTRY.find(({ token }) => token === "session_name")).toMatchObject({
      criteriaWireNames: { session: "name" },
      scalarFilterDomain: "string",
    });
    expect(FORMAT_REGISTRY.find(({ token }) => token === "window_name")).toMatchObject({
      criteriaWireNames: { window: "name" },
      scalarFilterDomain: "string",
    });
    expect(FORMAT_REGISTRY.find(({ token }) => token === "pane_id")).toMatchObject({
      criteriaWireNames: { pane: "pane_id" },
      scalarFilterDomain: "string",
    });
    expect(FORMAT_REGISTRY.find(({ token }) => token === "pid")).toMatchObject({
      criteriaWireNames: { pane: "pid", session: "pid", window: "pid" },
      scalarFilterDomain: "string",
    });
    expect(FORMAT_REGISTRY.find(({ token }) => token === "client_name")).toMatchObject({
      criteriaWireNames: {},
      scalarFilterDomain: null,
    });
  });

  test("selects Python list scopes while carrying version floors", () => {
    const expectedCounts = {
      "3.2a": { clients: 148, panes: 123, sessions: 123, windows: 123 },
      "3.3": { clients: 150, panes: 125, sessions: 125, windows: 125 },
      "3.7": { clients: 161, panes: 136, sessions: 136, windows: 136 },
      "3.7a": { clients: 161, panes: 136, sessions: 136, windows: 136 },
      "3.7b": { clients: 161, panes: 136, sessions: 136, windows: 136 },
    };

    for (const [version, counts] of Object.entries(expectedCounts)) {
      expect(formatFieldsForListCommand("list-sessions", version)).toHaveLength(counts.sessions);
      expect(formatFieldsForListCommand("list-windows", version)).toHaveLength(counts.windows);
      expect(formatFieldsForListCommand("list-panes", version)).toHaveLength(counts.panes);
      expect(formatFieldsForListCommand("list-clients", version)).toHaveLength(counts.clients);
    }

    const clientScopes = new Set(
      formatFieldsForListCommand("list-clients", "3.7b").map(({ scope }) => scope),
    );
    expect(clientScopes).toEqual(new Set(["client", "pane", "session", "universal", "window"]));
    const ordinaryScopes = new Set(
      formatFieldsForListCommand("list-sessions", "3.7b").map(({ scope }) => scope),
    );
    expect(ordinaryScopes).toEqual(new Set(["pane", "session", "universal", "window"]));

    for (const masterVersion of ["master", "3.6a-master"]) {
      expect(
        formatFieldsForListCommand("list-panes", masterVersion).some(
          ({ token }) => token === "pane_x",
        ),
      ).toBe(true);
    }
  });

  test("generates only canonical scalar Where fields for eligible models", () => {
    expect(Object.isFrozen(WHERE_FIELDS_V1)).toBe(true);
    expect(Object.isFrozen(WHERE_ALIASES_V1)).toBe(true);
    for (const fields of Object.values(WHERE_FIELDS_V1)) {
      expect(Object.isFrozen(fields)).toBe(true);
      expect(fields.every((field) => Object.isFrozen(field))).toBe(true);
    }
    for (const aliases of Object.values(WHERE_ALIASES_V1)) {
      expect(Object.isFrozen(aliases)).toBe(true);
    }
    expect(Object.keys(WHERE_FIELDS_V1)).toEqual(["session", "window", "pane"]);
    expect(WHERE_FIELDS_V1.session).toHaveLength(32);
    expect(WHERE_FIELDS_V1.window).toHaveLength(43);
    expect(WHERE_FIELDS_V1.pane).toHaveLength(79);
    expect(createHash("sha256").update(JSON.stringify(WHERE_FIELDS_V1.session)).digest("hex")).toBe(
      "448219eaf05c1ff76d0a20166f4455cb39105eba71343ed7132cf7caec585dea",
    );
    expect(createHash("sha256").update(JSON.stringify(WHERE_FIELDS_V1.window)).digest("hex")).toBe(
      "d83b4161b7c0e6cbc7bc3bc150a02af0ef7076a0c104346f5f7432c0e397336a",
    );
    expect(createHash("sha256").update(JSON.stringify(WHERE_FIELDS_V1.pane)).digest("hex")).toBe(
      "a1ff60c5274d1796da73079e649b5e1f86a9435bcf80496d1f8ebdd286c13b60",
    );
    for (const [model, fields] of Object.entries(WHERE_FIELDS_V1)) {
      for (const field of fields) {
        expect(
          FORMAT_REGISTRY.find(({ token }) => token === field.token)?.criteriaWireNames[
            model as "pane" | "session" | "window"
          ],
        ).toBe(field.wireName);
      }
    }
    expect(WHERE_FIELDS_V1.session.some(({ wireName }) => wireName === "name")).toBe(true);
    expect(WHERE_FIELDS_V1.window.some(({ wireName }) => wireName === "name")).toBe(true);
    expect(WHERE_FIELDS_V1.pane.some(({ wireName }) => wireName === "name")).toBe(false);
    expect(JSON.stringify(WHERE_FIELDS_V1)).not.toContain("client_name");
    expect(JSON.stringify(WHERE_FIELDS_V1)).not.toContain("refresh");
  });

  test("keeps schema version 1 alias-free and validates future alias provenance", () => {
    expect(WHERE_ALIASES_V1).toEqual({ pane: {}, session: {}, window: {} });

    expect(() =>
      validateWhereSchemaHistory([
        {
          aliases: { pane: {}, session: {}, window: {} },
          fields: { pane: ["pane_id"], session: ["name"], window: ["name"] },
          version: 1,
        },
        {
          aliases: { pane: {}, session: { name: "label" }, window: {} },
          fields: { pane: ["pane_id"], session: ["label"], window: ["name"] },
          version: 2,
        },
      ]),
    ).not.toThrow();

    expect(() =>
      validateWhereSchemaHistory([
        {
          aliases: { pane: {}, session: {}, window: {} },
          fields: { pane: ["pane_id"], session: ["name"], window: ["name"] },
          version: 1,
        },
        {
          aliases: { pane: {}, session: { neverShipped: "name" }, window: {} },
          fields: { pane: ["pane_id"], session: ["name"], window: ["name"] },
          version: 2,
        },
      ]),
    ).toThrow("alias must name a field from an earlier schema");

    expect(() =>
      validateWhereSchemaHistory([
        {
          aliases: { pane: {}, session: { oldName: "name" }, window: {} },
          fields: { pane: ["pane_id"], session: ["name"], window: ["name"] },
          version: 1,
        },
      ]),
    ).toThrow("schema version 1 cannot contain aliases");
  });

  test("renders deterministic generated sources", () => {
    const first = renderGeneratedFormatSources();
    const second = renderGeneratedFormatSources();

    expect(first).toEqual(second);
    expect(Object.keys(first)).toEqual(["format_fields.ts", "where_fields.ts"]);
    expect(first["format_fields.ts"]?.endsWith("\n")).toBe(true);
    expect(first["where_fields.ts"]?.endsWith("\n")).toBe(true);
  });

  test("renders only the delimited public neo type region", () => {
    const region = renderGeneratedNeoTypeRegion();
    const canonical = `export class Obj {\n  private constructor() {}\n}\n\n${region}\nconst suffix = "unrelated";\n`;

    expect(region).toContain("// <libtmux-generated-format-types>");
    expect(region).toContain("// </libtmux-generated-format-types>");
    expect(region).toContain("export type FormatFieldName =");
    expect(region).toContain(
      "export interface Obj extends Readonly<Record<FormatFieldName, string | null>> {}",
    );
    expect(renderNeoWithGeneratedTypes(canonical)).toBe(canonical);
    expect(
      renderNeoWithGeneratedTypes(
        canonical.replace("active_window_index", "active_window_index_drift"),
      ),
    ).toBe(canonical);

    const unrelated = canonical
      .replace("export class Obj", "export class Obj /* prefix sentinel */")
      .replace('const suffix = "unrelated";', 'const suffix = "suffix sentinel";');
    expect(renderNeoWithGeneratedTypes(unrelated)).toBe(unrelated);
    expect(
      renderNeoWithGeneratedTypes(
        unrelated.replace("active_window_index", "active_window_index_drift"),
      ),
    ).toBe(unrelated);
    expect(() => renderNeoWithGeneratedTypes("export class Obj {}\n")).toThrow(
      "neo.ts must contain exactly one generated format type region",
    );
  });

  test("renders the activated Task 5 parity rows without normalizing unrelated bytes", async () => {
    const canonical = await readFile(parityManifestUrl, "utf8");
    const drifted = canonical.replace(
      '"./neo#value:FIELD_VERSION"',
      '"./neo#value:FIELD_VERSION_DRIFT"',
    );
    expect(drifted).not.toBe(canonical);
    expect(renderTask5ParityManifest(drifted)).toBe(canonical);
    expect(renderTask5ParityManifest(canonical)).toBe(canonical);

    const unrelatedWhitespace = canonical.replace(
      '"pythonVersion": "0.62.0",',
      '"pythonVersion": "0.62.0",   ',
    );
    expect(renderTask5ParityManifest(unrelatedWhitespace)).toBe(unrelatedWhitespace);
  });

  test("check mode detects exact-byte drift without rewriting it", async () => {
    const outputDirectory = await mkdtemp(join(tmpdir(), "ltx5-generated-"));
    const neoSourcePath = join(outputDirectory, "neo.ts");
    const parityManifestPath = join(outputDirectory, "python-0.62.0.json");
    try {
      const canonicalParity = await readFile(parityManifestUrl, "utf8");
      const canonicalNeo = `export class Obj {\n  private constructor() {}\n}\n\n${renderGeneratedNeoTypeRegion()}\nconst suffix = "preserve me";\n`;
      await writeFile(
        neoSourcePath,
        canonicalNeo.replace("active_window_index", "active_window_index_drift"),
      );
      await writeFile(
        parityManifestPath,
        canonicalParity.replace('"./neo#value:FIELD_VERSION"', '"./neo#value:FIELD_VERSION_DRIFT"'),
      );
      await generateFormats({ mode: "write", neoSourcePath, outputDirectory, parityManifestPath });
      await expect(
        generateFormats({ mode: "check", neoSourcePath, outputDirectory, parityManifestPath }),
      ).resolves.toBeUndefined();
      expect(await readFile(neoSourcePath, "utf8")).toBe(canonicalNeo);
      expect(await readFile(parityManifestPath, "utf8")).toBe(canonicalParity);

      const generatedPath = join(outputDirectory, "format_fields.ts");
      const drifted = `${await readFile(generatedPath, "utf8")}drift\n`;
      await writeFile(generatedPath, drifted);

      await expect(
        generateFormats({ mode: "check", neoSourcePath, outputDirectory, parityManifestPath }),
      ).rejects.toThrow("generated format outputs are out of date");
      expect(await readFile(generatedPath, "utf8")).toBe(drifted);

      await generateFormats({ mode: "write", neoSourcePath, outputDirectory, parityManifestPath });
      const neoDrift = canonicalNeo.replace("active_window_index", "active_window_index_drift");
      await writeFile(neoSourcePath, neoDrift);
      await expect(
        generateFormats({ mode: "check", neoSourcePath, outputDirectory, parityManifestPath }),
      ).rejects.toThrow("generated format outputs are out of date");
      expect(await readFile(neoSourcePath, "utf8")).toBe(neoDrift);

      await generateFormats({ mode: "write", neoSourcePath, outputDirectory, parityManifestPath });
      const parityDrift = canonicalParity.replace(
        '"./neo#value:FIELD_VERSION"',
        '"./neo#value:FIELD_VERSION_DRIFT"',
      );
      await writeFile(parityManifestPath, parityDrift);
      await expect(
        generateFormats({ mode: "check", neoSourcePath, outputDirectory, parityManifestPath }),
      ).rejects.toThrow("generated format outputs are out of date");
      expect(await readFile(parityManifestPath, "utf8")).toBe(parityDrift);
    } finally {
      await rm(outputDirectory, { force: true, recursive: true });
    }
  });

  test("CLI accepts exactly one explicit mode and rejected forms never write", async () => {
    const cliRoot = await mkdtemp(join(tsRootPath, ".task5-generator-cli-"));
    const generatedPaths = [
      join(cliRoot, "src/_generated/format_fields.ts"),
      join(cliRoot, "src/_generated/where_fields.ts"),
      join(cliRoot, "src/neo.ts"),
      join(cliRoot, "parity/python-0.62.0.json"),
    ];
    const readGeneratedOutputs = () =>
      Promise.all(
        generatedPaths.map(async (path) => {
          try {
            return await readFile(path);
          } catch (error) {
            if ((error as NodeJS.ErrnoException).code === "ENOENT") return null;
            throw error;
          }
        }),
      );
    try {
      await mkdir(join(cliRoot, "scripts"), { recursive: true });
      await Promise.all([
        cp(
          join(tsRootPath, "scripts/generate-formats.ts"),
          join(cliRoot, "scripts/generate-formats.ts"),
        ),
        cp(join(tsRootPath, "src"), join(cliRoot, "src"), { recursive: true }),
        cp(join(tsRootPath, "parity"), join(cliRoot, "parity"), { recursive: true }),
        cp(join(tsRootPath, "tests/fixtures"), join(cliRoot, "tests/fixtures"), {
          recursive: true,
        }),
        cp(join(tsRootPath, "package.json"), join(cliRoot, "package.json")),
      ]);
      const before = await readGeneratedOutputs();

      for (const arguments_ of [[], ["--unknown"], ["--check", "--write"]]) {
        // eslint-disable-next-line no-await-in-loop -- each rejected argv must settle before its immediate zero-write audit.
        const result = await runGeneratorCli(arguments_, cliRoot);
        expect(result.exitCode).not.toBe(0);
        expect(result.stderr).toContain("usage: generate-formats.ts (--check|--write)");
        // eslint-disable-next-line no-await-in-loop -- later CLI cases must not repair an earlier rejected-mode write.
        expect(await readGeneratedOutputs()).toEqual(before);
      }

      const driftedFormatFields = Buffer.concat([
        before[0] ?? Buffer.alloc(0),
        Buffer.from("// generator CLI drift\n"),
      ]);
      await writeFile(generatedPaths[0]!, driftedFormatFields);
      const drifted = await readGeneratedOutputs();

      const check = await runGeneratorCli(["--check"], cliRoot);
      expect(check.exitCode).not.toBe(0);
      expect(check.stderr).toContain("generated format outputs are out of date");
      expect(await readGeneratedOutputs()).toEqual(drifted);

      await expect(runGeneratorCli(["--write"], cliRoot)).resolves.toMatchObject({
        exitCode: 0,
        stderr: "",
      });
      const repaired = await readGeneratedOutputs();
      expect(repaired[0]).not.toEqual(drifted[0]);
      expect(repaired[0]).toEqual(before[0]);

      await expect(runGeneratorCli(["--check"], cliRoot)).resolves.toMatchObject({
        exitCode: 0,
        stderr: "",
      });
      expect(await readGeneratedOutputs()).toEqual(repaired);
    } finally {
      await rm(cliRoot, { force: true, recursive: true });
    }
  }, 40_000);
});
