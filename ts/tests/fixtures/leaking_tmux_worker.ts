import { spawn } from "node:child_process";
import { chmod, readFile, stat, unlink, writeFile } from "node:fs/promises";

import { OWNER_RECORD_NAME, RUN_ROOT_ENV } from "../../src/_internal/test/run_root.js";
import { TestServer } from "../../src/_internal/test/test_server.js";

interface Arguments {
  readonly exitCode: number;
  readonly marker: string;
  readonly mode:
    | "corrupt-record-exit"
    | "exit"
    | "hold"
    | "ignore-signals"
    | "inherited-pipe"
    | "launching-hold"
    | "owner-mode-exit"
    | "self-sigterm";
}

function parseArguments(argv: readonly string[]): Arguments {
  let exitCode = 0;
  let marker: string | undefined;
  let mode: Arguments["mode"] | undefined;
  for (let index = 0; index < argv.length; index += 2) {
    const flag = argv[index];
    const value = argv[index + 1];
    if (value === undefined) throw new Error(`${flag ?? "argument"} requires a value`);
    if (flag === "--exit-code") exitCode = Number.parseInt(value, 10);
    else if (flag === "--marker") marker = value;
    else if (
      flag === "--mode" &&
      (value === "corrupt-record-exit" ||
        value === "exit" ||
        value === "hold" ||
        value === "ignore-signals" ||
        value === "inherited-pipe" ||
        value === "launching-hold" ||
        value === "owner-mode-exit" ||
        value === "self-sigterm")
    ) {
      mode = value;
    } else {
      throw new Error(`unknown worker argument: ${flag}`);
    }
  }
  if (mode === undefined || marker === undefined)
    throw new Error("--mode and --marker are required");
  if (!Number.isInteger(exitCode) || exitCode < 0 || exitCode > 255) {
    throw new Error("--exit-code must be between 0 and 255");
  }
  return { exitCode, marker, mode };
}

const args = parseArguments(process.argv.slice(2));
if (args.mode === "exit") {
  process.exitCode = args.exitCode;
} else if (args.mode === "self-sigterm") {
  const fallback = setTimeout(() => process.exit(143), 1_000);
  setImmediate(() => process.kill(process.pid, "SIGTERM"));
  fallback.ref();
} else {
  const runRoot = process.env[RUN_ROOT_ENV];
  if (runRoot === undefined) throw new Error(`${RUN_ROOT_ENV} is required`);
  if (args.mode === "owner-mode-exit") {
    const ownerPath = `${runRoot}/${OWNER_RECORD_NAME}`;
    await chmod(ownerPath, 0o644);
    const observedMode = (await stat(ownerPath)).mode & 0o777;
    if (observedMode !== 0o644) throw new Error("owner mode mutation was not observed");
    await writeFile(args.marker, `${JSON.stringify({ observedMode, ownerPath })}\n`);
    process.exitCode = args.exitCode;
  } else if (args.mode === "launching-hold") {
    const launchExecutable = process.env.LIBTMUX_TEST_LAUNCH_WRAPPER;
    if (launchExecutable === undefined) {
      throw new Error("LIBTMUX_TEST_LAUNCH_WRAPPER is required");
    }
    await TestServer.create({ launchExecutable, runRoot });
    throw new Error("launching-hold wrapper returned unexpectedly");
  } else {
    const server = await TestServer.create({ runRoot });
    if (args.mode === "corrupt-record-exit") {
      const recordText = await readFile(server.recordPath, "utf8");
      await unlink(server.socketPath);
      await writeFile(server.recordPath, "{corrupt\n");
      await writeFile(
        args.marker,
        `${JSON.stringify({ recordPath: server.recordPath, recordText })}\n`,
      );
      process.exitCode = args.exitCode;
    } else {
      let holderPid: number | undefined;
      if (args.mode === "inherited-pipe") {
        const holder = spawn(
          process.execPath,
          [
            "-e",
            "process.on('SIGTERM',()=>{});process.on('SIGINT',()=>{});setInterval(()=>{},1000)",
          ],
          { stdio: "inherit" },
        );
        holderPid = holder.pid;
      }
      await writeFile(
        args.marker,
        `${JSON.stringify({
          daemonPid: server.daemonIdentity.pid,
          holderPid,
          recordPath: server.recordPath,
          reservationPath: server.reservationPath,
          socketPath: server.socketPath,
          workerPid: process.pid,
        })}\n`,
      );
      if (args.mode === "ignore-signals" || args.mode === "inherited-pipe") {
        process.on("SIGINT", () => undefined);
        process.on("SIGTERM", () => undefined);
      }
      setInterval(() => undefined, 1_000);
    }
  }
}
