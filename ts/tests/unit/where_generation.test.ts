import { createHash } from "node:crypto";
import { lstat, mkdtemp, readFile, readdir, readlink, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { describe, expect, test } from "bun:test";

import { generateFormats } from "../../scripts/generate-formats.js";

const markerStart = "// <libtmux-generated-where-types>";
const markerEnd = "// </libtmux-generated-where-types>";
const expectedScalarKeys = {
  session: [
    "activeWindowIndex",
    "configFiles",
    "lastWindowIndex",
    "line",
    "name",
    "nextSessionId",
    "pid",
    "sessionActivity",
    "sessionAlerts",
    "sessionAttached",
    "sessionAttachedList",
    "sessionCreated",
    "sessionFormat",
    "sessionGroup",
    "sessionGroupAttached",
    "sessionGroupAttachedList",
    "sessionGroupList",
    "sessionGroupManyAttached",
    "sessionGroupSize",
    "sessionGrouped",
    "sessionId",
    "sessionLastAttached",
    "sessionManyAttached",
    "sessionMarked",
    "sessionPath",
    "sessionStack",
    "sessionWindows",
    "socketPath",
    "startTime",
    "uid",
    "user",
    "version",
  ],
  window: [
    "configFiles",
    "line",
    "name",
    "nextSessionId",
    "pid",
    "socketPath",
    "startTime",
    "uid",
    "user",
    "version",
    "windowActive",
    "windowActiveClients",
    "windowActiveClientsList",
    "windowActiveSessions",
    "windowActiveSessionsList",
    "windowActivity",
    "windowActivityFlag",
    "windowBellFlag",
    "windowBigger",
    "windowCellHeight",
    "windowCellWidth",
    "windowEndFlag",
    "windowFlags",
    "windowFormat",
    "windowHeight",
    "windowId",
    "windowIndex",
    "windowLastFlag",
    "windowLayout",
    "windowLinked",
    "windowLinkedSessions",
    "windowLinkedSessionsList",
    "windowMarkedFlag",
    "windowOffsetX",
    "windowOffsetY",
    "windowPanes",
    "windowRawFlags",
    "windowSilenceFlag",
    "windowStackIndex",
    "windowStartFlag",
    "windowVisibleLayout",
    "windowWidth",
    "windowZoomedFlag",
  ],
  pane: [
    "alternateSavedX",
    "alternateSavedY",
    "bracketPasteFlag",
    "configFiles",
    "cursorCharacter",
    "cursorFlag",
    "cursorX",
    "cursorY",
    "historyBytes",
    "historyLimit",
    "historySize",
    "insertFlag",
    "keypadCursorFlag",
    "keypadFlag",
    "line",
    "mouseAllFlag",
    "mouseAnyFlag",
    "mouseButtonFlag",
    "mouseSgrFlag",
    "mouseStandardFlag",
    "nextSessionId",
    "originFlag",
    "paneActive",
    "paneAtBottom",
    "paneAtLeft",
    "paneAtRight",
    "paneAtTop",
    "paneBg",
    "paneBottom",
    "paneCurrentCommand",
    "paneCurrentPath",
    "paneDead",
    "paneDeadSignal",
    "paneDeadStatus",
    "paneDeadTime",
    "paneFg",
    "paneFlags",
    "paneFloatingFlag",
    "paneFormat",
    "paneHeight",
    "paneId",
    "paneInMode",
    "paneIndex",
    "paneInputOff",
    "paneLast",
    "paneLeft",
    "paneMarked",
    "paneMarkedSet",
    "paneMode",
    "panePath",
    "panePbProgress",
    "panePbState",
    "panePid",
    "panePipe",
    "panePipePid",
    "paneRight",
    "paneSearchString",
    "paneStartCommand",
    "paneStartPath",
    "paneSynchronized",
    "paneTabs",
    "paneTitle",
    "paneTop",
    "paneTty",
    "paneWidth",
    "paneX",
    "paneY",
    "paneZ",
    "paneZoomedFlag",
    "pid",
    "scrollRegionLower",
    "scrollRegionUpper",
    "socketPath",
    "startTime",
    "synchronizedOutputFlag",
    "uid",
    "user",
    "version",
    "wrapFlag",
  ],
} as const;
const expectedRelationKeys = {
  session: ["activePane", "activeWindow", "panes", "windows"],
  window: ["activePane", "linkedSessions", "panes", "session"],
  pane: ["session", "window"],
} as const;
const expectedRelations = {
  pane: [
    { cardinality: "one", name: "window", targetModel: "window" },
    { cardinality: "one", name: "session", targetModel: "session" },
  ],
  session: [
    { cardinality: "many", name: "windows", targetModel: "window" },
    { cardinality: "many", name: "panes", targetModel: "pane" },
    { cardinality: "one", name: "activeWindow", targetModel: "window" },
    { cardinality: "one", name: "activePane", targetModel: "pane" },
  ],
  window: [
    { cardinality: "one", name: "session", targetModel: "session" },
    { cardinality: "many", name: "linkedSessions", targetModel: "session" },
    { cardinality: "many", name: "panes", targetModel: "pane" },
    { cardinality: "one", name: "activePane", targetModel: "pane" },
  ],
} as const;

interface GeneratedRegionSummary {
  readonly forbiddenKinds: readonly string[];
  readonly interfaces: readonly {
    readonly exported: boolean;
    readonly heritageCount: number;
    readonly members: readonly {
      readonly kind: string;
      readonly name: string;
      readonly optional: boolean;
      readonly readonly: boolean;
    }[];
    readonly name: string;
  }[];
  readonly statements: readonly { readonly kind: string; readonly name: string }[];
}

const generatedRegionAstScript = String.raw`
import { API } from "typescript/unstable/sync";
import { SyntaxKind } from "typescript/unstable/ast";

const file = process.argv.at(-1);
const api = new API({ cwd: process.cwd() });
try {
  const snapshot = api.updateSnapshot({ openFiles: [file] });
  const project = snapshot.getDefaultProjectForFile(file);
  const sourceFile = project?.program.getSourceFile(file);
  if (sourceFile === undefined) throw new Error("generated selection source was not parsed");
  const markerStart = "// <libtmux-generated-where-types>";
  const markerEnd = "// </libtmux-generated-where-types>";
  const start = sourceFile.text.indexOf(markerStart);
  const end = sourceFile.text.indexOf(markerEnd, start) + markerEnd.length;
  if (start < 0 || end < markerEnd.length) throw new Error("generated markers were not found");
  const hasModifier = (node, kind) => node.modifiers?.some((modifier) => modifier.kind === kind) ?? false;
  const forbiddenKinds = [];
  const forbidden = new Set([
    SyntaxKind.ConditionalType,
    SyntaxKind.MappedType,
    SyntaxKind.TemplateLiteralType,
  ]);
  const visit = (node) => {
    const insideRegion = node.getStart(sourceFile) >= start && node.getEnd() <= end;
    if (insideRegion && forbidden.has(node.kind)) forbiddenKinds.push(SyntaxKind[node.kind]);
    if (
      insideRegion &&
      node.kind === SyntaxKind.TypeOperator &&
      node.operator === SyntaxKind.KeyOfKeyword
    ) {
      forbiddenKinds.push("KeyOfTypeOperator");
    }
    node.forEachChild((child) => {
      visit(child);
      return undefined;
    });
  };
  visit(sourceFile);
  const interfaces = sourceFile.statements
    .filter((statement) =>
      statement.kind === SyntaxKind.InterfaceDeclaration &&
      statement.getStart(sourceFile) >= start &&
      statement.getEnd() <= end &&
      ["SessionWhere", "WindowWhere", "PaneWhere"].includes(statement.name?.text))
    .map((statement) => ({
      exported: hasModifier(statement, SyntaxKind.ExportKeyword),
      heritageCount: statement.heritageClauses?.length ?? 0,
      members: statement.members.map((member) => ({
        kind: SyntaxKind[member.kind],
        name: member.name?.getText(sourceFile) ?? "",
        optional:
          (member.postfixToken ?? member.questionToken)?.kind === SyntaxKind.QuestionToken,
        readonly: hasModifier(member, SyntaxKind.ReadonlyKeyword),
      })),
      name: statement.name.text,
    }));
  const statements = sourceFile.statements
    .filter(
      (statement) =>
        statement.getStart(sourceFile) >= start && statement.getEnd() <= end,
    )
    .map((statement) => ({
      kind: SyntaxKind[statement.kind],
      name: statement.name?.text ?? statement.getText(sourceFile),
    }));
  process.stdout.write(JSON.stringify({ forbiddenKinds, interfaces, statements }));
} finally {
  api.close();
}
`;

function sha256(value: Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

async function snapshotTree(root: string, relativeDirectory = ""): Promise<readonly object[]> {
  const absoluteDirectory = join(root, relativeDirectory);
  const entries = await readdir(absoluteDirectory, { withFileTypes: true });
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

async function runGeneratorReadOnly(root: string, action: () => Promise<void>): Promise<unknown> {
  const before = await snapshotTree(root);
  const error = await captureFailure(action);
  expect(await snapshotTree(root)).toEqual(before);
  return error;
}

async function summarizeGeneratedRegion(path: string): Promise<GeneratedRegionSummary> {
  const packageRoot = fileURLToPath(new URL("../..", import.meta.url));
  const child = Bun.spawn(
    ["node", "--input-type=module", "--eval", generatedRegionAstScript, path],
    { cwd: packageRoot, stderr: "pipe", stdout: "pipe" },
  );
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  expect(exitCode, stderr).toBe(0);
  expect(stderr).toBe("");
  return JSON.parse(stdout) as GeneratedRegionSummary;
}

async function captureFailure(action: () => Promise<void>): Promise<unknown> {
  try {
    await action();
  } catch (error) {
    return error;
  }
  return undefined;
}

function occurrences(source: string, value: string): number {
  return source.split(value).length - 1;
}

describe("generated Where contract", () => {
  test("writes exact relation metadata and only the delimited cyclic interfaces", async () => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-where-generation-"));
    const outputDirectory = join(temporary, "_generated");
    const neoSourcePath = join(temporary, "neo.ts");
    const parityManifestPath = join(temporary, "python-0.62.0.json");
    const selectionSourcePath = join(temporary, "selection.ts");
    const prefix = Buffer.from('\ufeffexport type SentinelBefore = "before";\r\n\r\n');
    const suffix = Buffer.from('\r\n\r\nexport type SentinelAfter = "after";\r\n');
    const selectionSkeleton = Buffer.concat([
      prefix,
      Buffer.from(`${markerStart}\nstale generated content\n${markerEnd}`),
      suffix,
    ]);
    const options = {
      mode: "write" as const,
      neoSourcePath,
      outputDirectory,
      parityManifestPath,
      selectionSourcePath,
    };
    try {
      await writeFile(neoSourcePath, await readFile(new URL("../../src/neo.ts", import.meta.url)));
      await writeFile(
        parityManifestPath,
        await readFile(new URL("../../parity/python-0.62.0.json", import.meta.url)),
      );
      await writeFile(selectionSourcePath, selectionSkeleton);

      await generateFormats(options);
      const whereSourcePath = join(outputDirectory, "where_fields.ts");
      const whereModule = (await import(
        `${pathToFileURL(whereSourcePath).href}?generated=${String(Date.now())}`
      )) as { readonly WHERE_RELATIONS_V1?: unknown };
      const selectionSource = await readFile(selectionSourcePath, "utf8");
      const selectionBytes = await readFile(selectionSourcePath);
      const generatedAst = await summarizeGeneratedRegion(selectionSourcePath);

      expect(whereModule.WHERE_RELATIONS_V1).toEqual(expectedRelations);
      expect(Object.isFrozen(whereModule.WHERE_RELATIONS_V1)).toBe(true);
      const startOffset = selectionBytes.indexOf(markerStart);
      const endOffset =
        selectionBytes.indexOf(markerEnd, startOffset) + Buffer.byteLength(markerEnd);
      expect(startOffset).toBe(prefix.byteLength);
      expect(selectionBytes.subarray(0, startOffset)).toEqual(prefix);
      expect(selectionBytes.subarray(endOffset)).toEqual(suffix);
      expect(occurrences(selectionSource, markerStart)).toBe(1);
      expect(occurrences(selectionSource, markerEnd)).toBe(1);
      expect(selectionSource).toContain("export interface SessionWhere");
      expect(selectionSource).toContain("export interface WindowWhere");
      expect(selectionSource).toContain("export interface PaneWhere");
      expect(selectionSource).toContain("readonly activeWindow?:");
      expect(selectionSource).toContain("readonly linkedSessions?:");
      // The emitted criteria never carry the tmux wire spellings; those belong
      // to the serialized document, not the TypeScript surface.
      expect(selectionSource).not.toContain("active_window?");
      expect(selectionSource).not.toContain("linked_sessions?");
      expect(selectionSource).not.toContain("children");
      expect(generatedAst.forbiddenKinds).toEqual([]);
      expect(generatedAst.statements).toHaveLength(3);
      expect(
        generatedAst.statements
          .map(({ kind, name }) => ({ kind, name }))
          .sort((left, right) => left.name.localeCompare(right.name)),
      ).toEqual([
        { kind: "InterfaceDeclaration", name: "PaneWhere" },
        { kind: "InterfaceDeclaration", name: "SessionWhere" },
        { kind: "InterfaceDeclaration", name: "WindowWhere" },
      ]);
      expect(generatedAst.interfaces.map(({ name }) => name).sort()).toEqual([
        "PaneWhere",
        "SessionWhere",
        "WindowWhere",
      ]);
      for (const [model, interfaceName] of [
        ["session", "SessionWhere"],
        ["window", "WindowWhere"],
        ["pane", "PaneWhere"],
      ] as const) {
        const generatedInterface = generatedAst.interfaces.find(
          (candidate) => candidate.name === interfaceName,
        );
        expect(generatedInterface?.exported).toBe(true);
        expect(generatedInterface?.heritageCount).toBe(0);
        expect(generatedInterface?.members.map(({ name }) => name).sort()).toEqual(
          ["AND", "NOT", "OR", ...expectedRelationKeys[model], ...expectedScalarKeys[model]].sort(),
        );
        expect(
          generatedInterface?.members.every(
            ({ kind, optional, readonly }) => kind === "PropertySignature" && optional && readonly,
          ),
        ).toBe(true);
      }

      const successfulCheckError = await runGeneratorReadOnly(temporary, () =>
        generateFormats({ ...options, mode: "check" }),
      );
      expect(successfulCheckError).toBeUndefined();

      const relationDrift = (await readFile(whereSourcePath, "utf8")).replace(
        'name: "activePane"',
        'name: "active_pane"',
      );
      await writeFile(whereSourcePath, relationDrift);
      const relationError = await runGeneratorReadOnly(temporary, () =>
        generateFormats({ ...options, mode: "check" }),
      );
      expect(relationError).toBeInstanceOf(Error);
      expect((relationError as Error).message).toContain(
        "generated format outputs are out of date",
      );
      expect(await readFile(whereSourcePath, "utf8")).toBe(relationDrift);

      await generateFormats(options);
      const scalarMetadataSource = await readFile(whereSourcePath, "utf8");
      const scalarMetadataDrift = scalarMetadataSource.replace(
        'wireName: "active_window_index"',
        'wireName: "activeWindowIndex"',
      );
      expect(scalarMetadataDrift).not.toBe(scalarMetadataSource);
      await writeFile(whereSourcePath, scalarMetadataDrift);
      const scalarMetadataError = await runGeneratorReadOnly(temporary, () =>
        generateFormats({ ...options, mode: "check" }),
      );
      expect(scalarMetadataError).toBeInstanceOf(Error);
      expect((scalarMetadataError as Error).message).toContain(
        "generated format outputs are out of date",
      );
      expect(await readFile(whereSourcePath, "utf8")).toBe(scalarMetadataDrift);

      await generateFormats(options);
      const interfaceDrift = (await readFile(selectionSourcePath, "utf8")).replace(
        "readonly activePane?:",
        "readonly active_pane?:",
      );
      await writeFile(selectionSourcePath, interfaceDrift);
      const interfaceError = await runGeneratorReadOnly(temporary, () =>
        generateFormats({ ...options, mode: "check" }),
      );
      expect(interfaceError).toBeInstanceOf(Error);
      expect((interfaceError as Error).message).toContain(
        "generated format outputs are out of date",
      );
      expect(await readFile(selectionSourcePath, "utf8")).toBe(interfaceDrift);
    } finally {
      await rm(temporary, { force: true, recursive: true });
    }
  });

  test.each([
    {
      name: "missing start",
      selectionSource: [markerEnd, ""].join("\n"),
    },
    {
      name: "missing end",
      selectionSource: [markerStart, ""].join("\n"),
    },
    {
      name: "repeated start with one valid end",
      selectionSource: [markerStart, markerStart, "stale", markerEnd, ""].join("\n"),
    },
    {
      name: "repeated end with one valid start",
      selectionSource: [markerStart, "stale", markerEnd, markerEnd, ""].join("\n"),
    },
    {
      name: "one end before one start",
      selectionSource: [markerEnd, "stale", markerStart, ""].join("\n"),
    },
  ])("rejects $name markers without changing any controlled file", async ({ selectionSource }) => {
    const temporary = await mkdtemp(join(tmpdir(), "libtmux-where-markers-"));
    const outputDirectory = join(temporary, "_generated");
    const neoSourcePath = join(temporary, "neo.ts");
    const parityManifestPath = join(temporary, "python-0.62.0.json");
    const selectionSourcePath = join(temporary, "selection.ts");
    const options = {
      neoSourcePath,
      outputDirectory,
      parityManifestPath,
      selectionSourcePath,
    };

    try {
      await writeFile(neoSourcePath, await readFile(new URL("../../src/neo.ts", import.meta.url)));
      await writeFile(
        parityManifestPath,
        await readFile(new URL("../../parity/python-0.62.0.json", import.meta.url)),
      );
      await writeFile(selectionSourcePath, [markerStart, "stale", markerEnd, ""].join("\n"));
      await generateFormats({ ...options, mode: "write" });
      await writeFile(selectionSourcePath, selectionSource);

      const checkError = await runGeneratorReadOnly(temporary, () =>
        generateFormats({ ...options, mode: "check" }),
      );
      const writeError = await runGeneratorReadOnly(temporary, () =>
        generateFormats({ ...options, mode: "write" }),
      );
      const observations = [checkError, writeError] as const;

      expect(observations).toHaveLength(2);
      for (const error of observations) {
        expect(error).toBeInstanceOf(Error);
        expect((error as Error).message).toContain("marker");
      }
    } finally {
      await rm(temporary, { force: true, recursive: true });
    }
  });
});
