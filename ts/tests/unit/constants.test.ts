import { describe, expect, test } from "bun:test";

import {
  DEFAULT_OPTION_SCOPE,
  HOOK_SCOPE_FLAG_MAP,
  OptionScope,
  OPTION_SCOPE_FLAG_MAP,
  PaneDirection,
  PANE_DIRECTION_FLAG_MAP,
  ResizeAdjustmentDirection,
  RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
  WindowDirection,
  WINDOW_DIRECTION_FLAG_MAP,
} from "../../src/constants.js";

describe("constants", () => {
  test("preserve Python direction member names and values", () => {
    expect(ResizeAdjustmentDirection).toEqual({
      Down: "DOWN",
      Left: "LEFT",
      Right: "RIGHT",
      Up: "UP",
    });
    expect(WindowDirection).toEqual({ After: "AFTER", Before: "BEFORE" });
    expect(PaneDirection).toEqual({ Above: "ABOVE", Below: "BELOW", Left: "LEFT", Right: "RIGHT" });
  });

  test("preserves Python option-scope member names and values", () => {
    expect(OptionScope).toEqual({
      Pane: "PANE",
      Server: "SERVER",
      Session: "SESSION",
      Window: "WINDOW",
    });
  });

  test("preserves Python flag maps and default option sentinel", () => {
    expect(RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP).toEqual({
      DOWN: "-D",
      LEFT: "-L",
      RIGHT: "-R",
      UP: "-U",
    });
    expect(WINDOW_DIRECTION_FLAG_MAP).toEqual({ AFTER: "-a", BEFORE: "-b" });
    expect(PANE_DIRECTION_FLAG_MAP).toEqual({
      ABOVE: ["-v", "-b"],
      BELOW: ["-v"],
      LEFT: ["-h", "-b"],
      RIGHT: ["-h"],
    });
    expect(OPTION_SCOPE_FLAG_MAP).toEqual({ PANE: "-p", SERVER: "-s", SESSION: "", WINDOW: "-w" });
    expect(HOOK_SCOPE_FLAG_MAP).toEqual({ PANE: "-p", SERVER: "-g", SESSION: "", WINDOW: "-w" });
    expect(DEFAULT_OPTION_SCOPE).toBe(DEFAULT_OPTION_SCOPE);
  });
});
