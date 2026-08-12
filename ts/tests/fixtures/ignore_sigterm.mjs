import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";

process.on("SIGTERM", () => undefined);
const arguments_ = process.argv.slice(2);
const markerPath = arguments_.find((argument) => !argument.startsWith("--"));
const exitArgument = arguments_.find((argument) => argument.startsWith("--exit-after="));
const inheritedPipeArgument = arguments_.find((argument) =>
  argument.startsWith("--inherit-pipes="),
);
if (inheritedPipeArgument !== undefined) {
  const inheritedPipeMarker = inheritedPipeArgument.slice("--inherit-pipes=".length);
  const holder = spawn(
    process.execPath,
    ["--input-type=module", "--eval", "setInterval(() => {}, 1000)"],
    { detached: true, stdio: ["ignore", "inherit", "inherit"] },
  );
  holder.unref();
  await new Promise((resolve, reject) => {
    process.stdout.write("launch-frame\n", (stdoutError) => {
      if (stdoutError !== null && stdoutError !== undefined) {
        reject(stdoutError);
        return;
      }
      process.stderr.write("launch-diagnostic\n", (stderrError) => {
        if (stderrError !== null && stderrError !== undefined) {
          reject(stderrError);
          return;
        }
        writeFileSync(inheritedPipeMarker, String(holder.pid));
        resolve();
      });
    });
  });
} else {
  if (markerPath !== undefined) writeFileSync(markerPath, "ready");
  process.stdout.write("ready\n");
}
if (exitArgument !== undefined) {
  setTimeout(() => process.exit(0), Number.parseInt(exitArgument.slice(13), 10));
}
setInterval(() => undefined, 1_000);
