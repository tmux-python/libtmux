import { randomUUID } from "node:crypto";
import { open, readFile, rename, unlink } from "node:fs/promises";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";

interface SourceMap {
  sourceRoot?: unknown;
  sources: unknown;
  sourcesContent?: unknown;
}

function contained(root: string, path: string): boolean {
  const pathFromRoot = relative(root, path);
  return pathFromRoot !== ".." && !pathFromRoot.startsWith("../") && !isAbsolute(pathFromRoot);
}

async function atomicWrite(path: string, contents: string): Promise<void> {
  const temporaryPath = join(
    dirname(path),
    `.${basename(path)}.${process.pid}.${randomUUID()}.tmp`,
  );
  try {
    const handle = await open(temporaryPath, "wx");
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

const tsRoot = resolve(import.meta.dir, "..");
const argument = process.argv[2];
if (!argument || process.argv.length !== 3) throw new Error("expected one source-map path");
const mapPath = resolve(tsRoot, argument);
if (!contained(tsRoot, mapPath)) throw new Error("source-map path escapes package root");

const map = JSON.parse(await readFile(mapPath, "utf8")) as SourceMap;
if (map.sourceRoot !== undefined && map.sourceRoot !== "") {
  throw new Error("sourceRoot must be absent or empty before normalization");
}
if (!Array.isArray(map.sources) || map.sources.some((source) => typeof source !== "string")) {
  throw new Error("sources must be a string array");
}
if (!Array.isArray(map.sourcesContent) || map.sourcesContent.length !== map.sources.length) {
  throw new Error("sourcesContent must align with sources");
}

const sources = map.sources as string[];
const sourcesContent = map.sourcesContent;
await Promise.all(
  sources.map(async (source, index) => {
    if (isAbsolute(source)) throw new Error("absolute source path is forbidden");
    const sourcePath = resolve(dirname(mapPath), source);
    if (!contained(tsRoot, sourcePath)) throw new Error("source path escapes package root");
    const embedded = sourcesContent[index];
    if (typeof embedded !== "string") throw new Error("source content is missing");
    if (embedded !== (await readFile(sourcePath, "utf8"))) {
      throw new Error("embedded source content does not match its source");
    }
  }),
);

delete map.sourceRoot;
await atomicWrite(mapPath, `${JSON.stringify(map)}\n`);
console.log(`Normalized source map: ${relative(tsRoot, mapPath)}`);
