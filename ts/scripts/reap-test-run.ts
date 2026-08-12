import { reapStaleRunRoot } from "../src/_internal/test/run_root.js";

const argv = process.argv.slice(2);
if (argv.length !== 2 || argv[0] !== "--run-root" || argv[1] === undefined) {
  throw new Error("usage: reap-test-run.ts --run-root <absolute-run-root>");
}
const report = await reapStaleRunRoot(argv[1]);
if (report.leaks.length > 0) {
  process.stderr.write(`${report.leaks.join("\n")}\n`);
  process.exitCode = 1;
} else {
  process.stdout.write(`${JSON.stringify(report)}\n`);
}
