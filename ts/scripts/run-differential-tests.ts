import { runSupervisor } from "../src/_internal/test/run_root.js";

process.exitCode = await runSupervisor({
  command: [
    "bun",
    "test",
    "--no-orphans",
    "--preload",
    "./tests/support/bun_hooks.ts",
    "tests/integration/differential_substrate.test.ts",
  ],
  ...(process.env.LIBTMUX_TEST_RUN_ROOT === undefined
    ? {}
    : { runRoot: process.env.LIBTMUX_TEST_RUN_ROOT }),
});
