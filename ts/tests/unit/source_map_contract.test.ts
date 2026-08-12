import { isAbsolute, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, test } from "bun:test";

interface SourceMap {
  sourceRoot?: string;
  sources: string[];
  sourcesContent?: Array<string | null>;
}

const tsRoot = fileURLToPath(new URL("../..", import.meta.url));
const mapUrl = new URL("../../dist/index.js.map", import.meta.url);

async function validateSourceMap(map: SourceMap, packageRoot = tsRoot): Promise<void> {
  if (Object.hasOwn(map, "sourceRoot")) throw new Error("sourceRoot is forbidden");
  if (!map.sourcesContent || map.sourcesContent.length !== map.sources.length) {
    throw new Error("sourcesContent must align with sources");
  }

  const mapDirectory = fileURLToPath(new URL(".", mapUrl));
  const sourcesContent = map.sourcesContent;
  await Promise.all(
    map.sources.map(async (source, index) => {
      if (isAbsolute(source)) throw new Error("absolute source path is forbidden");
      const resolvedSource = resolve(mapDirectory, source);
      const packageRelative = relative(packageRoot, resolvedSource);
      if (
        packageRelative === ".." ||
        packageRelative.startsWith("../") ||
        isAbsolute(packageRelative)
      ) {
        throw new Error("source path escapes package root");
      }
      const embedded = sourcesContent[index];
      if (embedded === null || embedded === undefined) {
        throw new Error("source content is missing");
      }
      expect(embedded).toBe(await Bun.file(resolvedSource).text());
    }),
  );
}

async function expectValidationFailure(promise: Promise<void>, message?: string): Promise<void> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(Error);
    if (message) expect((error as Error).message).toContain(message);
    return;
  }
  throw new Error("source-map validation unexpectedly passed");
}

async function builtSourceMap(): Promise<SourceMap> {
  const build = Bun.spawnSync(["bun", "run", "build"], {
    cwd: tsRoot,
    stderr: "pipe",
    stdout: "pipe",
  });
  expect(build.exitCode, build.stderr.toString()).toBe(0);
  return JSON.parse(await Bun.file(mapUrl).text()) as SourceMap;
}

describe("emitted source-map contract", () => {
  test("uses safe relative sources with exact inline content", async () => {
    const map = await builtSourceMap();

    await validateSourceMap(map);
  });

  test("rejects unsafe, incomplete, and mismatched source maps", async () => {
    const valid = await builtSourceMap();
    const source = valid.sources[0]!;
    const content = valid.sourcesContent![0]!;

    await expectValidationFailure(
      validateSourceMap({ ...valid, sources: ["/tmp/index.ts"] }),
      "absolute source path is forbidden",
    );
    await expectValidationFailure(
      validateSourceMap({ ...valid, sources: ["../../outside.ts"] }),
      "source path escapes package root",
    );
    await expectValidationFailure(
      validateSourceMap({ ...valid, sourceRoot: "../src" }),
      "sourceRoot is forbidden",
    );
    await expectValidationFailure(
      validateSourceMap({ ...valid, sourcesContent: [] }),
      "sourcesContent must align with sources",
    );
    await expectValidationFailure(
      validateSourceMap({ ...valid, sources: [source], sourcesContent: [`${content}\nchanged`] }),
    );
  });
});
