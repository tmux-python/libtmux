import { runSupervisor } from "../src/_internal/test/run_root.js";

interface Arguments {
  readonly command: readonly [string, ...string[]];
  readonly graceMs: number;
  readonly runRoot?: string;
}

function parseArguments(argv: readonly string[]): Arguments {
  const delimiter = argv.indexOf("--");
  if (delimiter < 0 || argv[delimiter + 1] === undefined) {
    throw new Error("supervisor requires -- followed by a command");
  }
  let graceMs = 500;
  let runRoot: string | undefined;
  for (let index = 0; index < delimiter; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (value === undefined) throw new Error(`${flag ?? "argument"} requires a value`);
    if (flag === "--grace-ms") graceMs = Number.parseInt(value, 10);
    else if (flag === "--run-root") runRoot = value;
    else throw new Error(`unknown supervisor argument: ${flag}`);
  }
  const command = argv.slice(delimiter + 1) as [string, ...string[]];
  return runRoot === undefined ? { command, graceMs } : { command, graceMs, runRoot };
}

const args = parseArguments(process.argv.slice(2));
process.exitCode = await runSupervisor(args);
