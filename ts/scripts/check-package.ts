/**
 * Gate the artifact a consumer actually installs.
 *
 * The other gates read the source tree. This one packs the tarball and asks
 * three questions about it: does it resolve for the runtimes we claim, is the
 * manifest well formed, and does it carry anything a consumer has no use for.
 */
import { rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const tsRoot = fileURLToPath(new URL("..", import.meta.url));

/** Paths that must never reach a consumer, with the reason each is excluded. */
const forbiddenEntries: readonly (readonly [prefix: string, reason: string])[] = [
  ["dist/_internal/test/", "the tmux test harness is for this repository's own suites"],
  ["dist/tests/", "tests are not part of the published surface"],
  ["dist/scripts/", "build tooling is not part of the published surface"],
  ["dist/consumers/", "the example consumers are not part of the published surface"],
];

function fail(message: string): never {
  process.stderr.write(`${message}\n`);
  process.exit(1);
}

async function run(command: readonly string[]): Promise<string> {
  const child = Bun.spawn([...command], { cwd: tsRoot, stderr: "pipe", stdout: "pipe" });
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  if (exitCode !== 0) fail(`${command.join(" ")} exited ${exitCode}\n${stdout}${stderr}`);
  return stdout;
}

// `bun pm pack --dry-run` reports one "packed <size> <path>" line per entry.
const packed = await run(["bun", "pm", "pack", "--dry-run"]);
const entries = packed
  .split("\n")
  .map((line) => /^packed\s+\S+\s+(\S.*)$/.exec(line.trim())?.[1])
  .filter((entry) => entry !== undefined)
  .filter((entry) => entry.startsWith("dist/"));
if (entries.length === 0) fail("packing produced no dist entries; run `bun run build` first");

for (const [prefix, reason] of forbiddenEntries) {
  const found = entries.filter((entry) => entry.startsWith(prefix));
  if (found.length > 0) {
    fail(
      `${found.length} packed ${prefix}* entries: ${reason}\n  ${found.slice(0, 5).join("\n  ")}`,
    );
  }
}

// A root import must not pull the whole package in; entry points are separate
// files precisely so a consumer pays for what it names.
if (!entries.includes("dist/index.js")) fail("the packed tarball has no root entrypoint");
if (!entries.includes("dist/index.d.ts")) fail("the packed tarball has no root declaration");

await run(["./node_modules/.bin/publint"]);
await run(["./node_modules/.bin/attw", "--pack", ".", "--profile", "esm-only"]);
await rm(new URL("../libtmux-0.1.0.tgz", import.meta.url), { force: true });

process.stdout.write(
  `${JSON.stringify({
    entries: entries.length,
    protocol: "libtmux-package-artifact-v1",
    status: "passed",
  })}\n`,
);
