import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

interface PackageManifest {
  readonly exports: Readonly<Record<string, unknown>>;
  readonly files: readonly string[];
}

interface SelectionAstSummary {
  readonly exported: readonly { readonly kind: string; readonly name: string }[];
  readonly rootStatements: readonly { readonly kind: string; readonly text: string }[];
  readonly selection: {
    readonly exported: boolean;
    readonly heritage: readonly string[];
    readonly kind: string;
    readonly members: readonly { readonly kind: string; readonly name: string }[];
    readonly typeParameterCount: number;
  } | null;
}

const astSummaryScript = String.raw`
import { API } from "typescript/unstable/sync";
import { SyntaxKind } from "typescript/unstable/ast";

const [selectionFile, rootFile] = process.argv.slice(1);
const api = new API({ cwd: process.cwd() });
try {
  const snapshot = api.updateSnapshot({ openFiles: [selectionFile, rootFile] });
  const project = snapshot.getDefaultProjectForFile(selectionFile);
  const sourceFile = project?.program.getSourceFile(selectionFile);
  const rootSourceFile = project?.program.getSourceFile(rootFile);
  if (sourceFile === undefined) throw new Error("selection source was not parsed");
  if (rootSourceFile === undefined) throw new Error("root source was not parsed");
  const hasModifier = (node, kind) => node.modifiers?.some((modifier) => modifier.kind === kind) ?? false;
  const exported = [];
  let selection = null;
  for (const statement of sourceFile.statements) {
    if (hasModifier(statement, SyntaxKind.ExportKeyword)) {
      exported.push({ kind: SyntaxKind[statement.kind], name: statement.name?.text ?? statement.getText(sourceFile) });
    } else if (statement.kind === SyntaxKind.ExportDeclaration || statement.kind === SyntaxKind.ExportAssignment) {
      exported.push({ kind: SyntaxKind[statement.kind], name: statement.getText(sourceFile) });
    }
    if (statement.name?.text !== "Selection") continue;
    const typeParameterName = statement.typeParameters?.[0]?.name.text ?? "";
    selection = {
      exported: hasModifier(statement, SyntaxKind.ExportKeyword),
      heritage: (statement.heritageClauses ?? []).map((clause) =>
        clause
          .getText(sourceFile)
          .replace(/\s+/gu, " ")
          .replace(new RegExp("\\b" + typeParameterName + "\\b", "gu"), "Type"),
      ),
      kind: SyntaxKind[statement.kind],
      members: (statement.members ?? []).map((member) => ({
        kind: SyntaxKind[member.kind],
        name: member.name?.getText(sourceFile) ?? "",
      })),
      typeParameterCount: statement.typeParameters?.length ?? 0,
    };
  }
  const rootStatements = rootSourceFile.statements.map((statement) => ({
    kind: SyntaxKind[statement.kind],
    text: statement.getText(rootSourceFile).replace(/\s+/gu, " "),
  }));
  process.stdout.write(JSON.stringify({ exported, rootStatements, selection }));
} finally {
  api.close();
}
`;

async function selectionAstSummary(): Promise<SelectionAstSummary> {
  const selectionPath = fileURLToPath(new URL("../../src/selection.ts", import.meta.url));
  const rootPath = fileURLToPath(new URL("../../src/index.ts", import.meta.url));
  const packageRoot = fileURLToPath(new URL("../..", import.meta.url));
  const child = Bun.spawn(
    ["node", "--input-type=module", "--eval", astSummaryScript, selectionPath, rootPath],
    { cwd: packageRoot, stderr: "pipe", stdout: "pipe" },
  );
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  expect(exitCode, stderr).toBe(0);
  expect(stderr).toBe("");
  return JSON.parse(stdout) as SelectionAstSummary;
}

describe("Task 8 package boundary", () => {
  test("keeps Selection internal until Task 9 real-tmux evidence", async () => {
    const manifest = JSON.parse(
      await readFile(new URL("../../package.json", import.meta.url), "utf8"),
    ) as PackageManifest;
    const rootModule = await import("../../src/index.js");
    const selectionModule = await import("../../src/selection.js");
    const ast = await selectionAstSummary();

    expect(Object.keys(rootModule)).toEqual([]);
    expect(Object.keys(selectionModule)).toEqual(["parseLegacyWhere"]);
    expect(Reflect.get(selectionModule, "Selection")).toBeUndefined();
    expect(Object.keys(manifest.exports)).not.toContain("./selection");
    expect(JSON.stringify(manifest.exports)).not.toContain("selection");
    expect(manifest.files).toEqual(["dist"]);
    expect(ast.exported.map(({ name }) => name).sort()).toEqual([
      "PaneWhere",
      "RegexCriteriaData",
      "Selection",
      "SessionWhere",
      "WhereDocumentV1",
      "WhereOf",
      "WindowWhere",
      "parseLegacyWhere",
    ]);
    expect(ast.rootStatements).toEqual([{ kind: "ExportDeclaration", text: "export {};" }]);
    expect(ast.exported.find(({ name }) => name === "Selection")?.kind).toBe(
      "InterfaceDeclaration",
    );
    expect(ast.selection).toEqual({
      exported: true,
      heritage: ["extends Iterable<Type>"],
      kind: "InterfaceDeclaration",
      members: [
        { kind: "PropertySignature", name: "length" },
        { kind: "MethodSignature", name: "[Symbol.iterator]" },
        { kind: "MethodSignature", name: "at" },
        { kind: "MethodSignature", name: "toArray" },
        { kind: "MethodSignature", name: "filter" },
        { kind: "MethodSignature", name: "where" },
        { kind: "MethodSignature", name: "first" },
        { kind: "MethodSignature", name: "one" },
        { kind: "MethodSignature", name: "oneOrUndefined" },
        { kind: "MethodSignature", name: "exists" },
        { kind: "MethodSignature", name: "count" },
      ],
      typeParameterCount: 1,
    });
  });
});
