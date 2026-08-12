import { runSupervisor } from "../src/_internal/test/run_root.js";

process.exitCode = await runSupervisor({
  command: [
    "bun",
    "test",
    "--parallel=4",
    "--no-orphans",
    "--preload",
    "./tests/support/bun_hooks.ts",
    "tests/integration/test_server.test.ts",
    "tests/integration/supervisor_cleanup.test.ts",
    "tests/integration/neo.test.ts",
    "tests/integration/graph.test.ts",
    "tests/integration/acquire.test.ts",
    "tests/integration/snapshot.test.ts",
    "tests/integration/options.test.ts",
    "tests/integration/mutations.test.ts",
    "tests/integration/pane_io.test.ts",
    "tests/integration/topology.test.ts",
    "tests/integration/server_utils.test.ts",
    "tests/integration/shell.test.ts",
    "tests/integration/interactive.test.ts",
    "consumers/mcp/server.test.ts",
    "consumers/workspace/builder.test.ts",
  ],
  ...(process.env.LIBTMUX_TEST_RUN_ROOT === undefined
    ? {}
    : { runRoot: process.env.LIBTMUX_TEST_RUN_ROOT }),
});
