import { describe, expect, test } from "bun:test";

import { TmuxConnection } from "../../src/_internal/runtime/connection.js";

describe("TmuxConnection", () => {
  test("rejects conflicting socket selectors", () => {
    expect(
      () =>
        new TmuxConnection({
          executable: "/usr/bin/tmux",
          socketName: "named",
          socketPath: "/tmp/tmux.sock",
        }),
    ).toThrow("socketName and socketPath are mutually exclusive");
  });

  test("copies and freezes connection configuration and environment", () => {
    const environment = { LC_ALL: "C.UTF-8", TERM: "tmux-256color" };
    const options = {
      colors: 256 as const,
      configFile: "/tmp/tmux.conf",
      environment,
      executable: "/usr/bin/tmux",
      socketName: "named",
    };

    const connection = new TmuxConnection(options);
    environment.TERM = "changed";
    options.configFile = "/tmp/changed.conf";

    expect(connection).toEqual({
      colors: 256,
      configFile: "/tmp/tmux.conf",
      environment: { LC_ALL: "C.UTF-8", TERM: "tmux-256color" },
      executable: "/usr/bin/tmux",
      socketName: "named",
      socketPath: undefined,
    });
    expect(Object.isFrozen(connection)).toBe(true);
    expect(Object.isFrozen(connection.environment)).toBe(true);
  });
});
