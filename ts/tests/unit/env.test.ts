import { describe, expect, test } from "bun:test";

import { readTmuxEnvironment } from "../../src/_internal/operations/env.js";

describe("tmux environment parsing", () => {
  test("reads the socket path and pane from a plain $TMUX", () => {
    expect(readTmuxEnvironment({ TMUX: "/tmp/tmux-1000/default,1234,0", TMUX_PANE: "%3" })).toEqual(
      { paneId: "%3", socketPath: "/tmp/tmux-1000/default" },
    );
  });

  test("keeps commas that belong to the socket path", () => {
    // The split is anchored from the right, so a comma in the path survives.
    expect(
      readTmuxEnvironment({ TMUX: "/tmp/run, root/socket,987,2", TMUX_PANE: "%0" }).socketPath,
    ).toBe("/tmp/run, root/socket");
  });

  test("rejects a process that is not inside tmux", () => {
    expect(() => readTmuxEnvironment({})).toThrow(/not inside tmux/);
    expect(() => readTmuxEnvironment({ TMUX: "" })).toThrow(/not inside tmux/);
  });

  test("rejects a malformed $TMUX", () => {
    expect(() => readTmuxEnvironment({ TMUX: "no-commas", TMUX_PANE: "%1" })).toThrow(/malformed/);
  });

  test("rejects a missing or malformed pane", () => {
    const tmux = "/tmp/socket,1,0";
    expect(() => readTmuxEnvironment({ TMUX: tmux })).toThrow(/TMUX_PANE/);
    expect(() => readTmuxEnvironment({ TMUX: tmux, TMUX_PANE: "3" })).toThrow(/TMUX_PANE/);
    expect(() => readTmuxEnvironment({ TMUX: tmux, TMUX_PANE: "%abc" })).toThrow(/TMUX_PANE/);
  });
});
