import { describe, expect, test } from "bun:test";

import { parsePaneId, parseSessionId, parseWindowId } from "../../src/_internal/runtime/ids.js";
import { QueryValidationError } from "../../src/exc.js";

describe("tmux IDs", () => {
  test("parses each owned tmux ID kind", () => {
    expect(String(parseSessionId("$1"))).toBe("$1");
    expect(String(parseWindowId("@2"))).toBe("@2");
    expect(String(parsePaneId("%3"))).toBe("%3");
  });

  test("rejects malformed and wrong-kind IDs", () => {
    const cases = [
      ["session", parseSessionId, "$1", ["", "$", "$x", "@2", "%3", "$1 "]],
      ["window", parseWindowId, "@2", ["", "@", "@x", "$1", "%3", "@2 "]],
      ["pane", parsePaneId, "%3", ["", "%", "%x", "$1", "@2", "%3 "]],
    ] as const;

    for (const [_kind, parse, valid, invalid] of cases) {
      expect(String(parse(valid))).toBe(valid);
      for (const value of invalid) {
        expect(() => parse(value as never)).toThrow(QueryValidationError);
      }
    }
  });

  test("wraps parser validation errors with stable package data", () => {
    try {
      parsePaneId("@2" as never);
      throw new Error("expected invalid pane ID to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(QueryValidationError);
      const queryError = error as QueryValidationError;
      expect(queryError.code).toBe("invalid-id");
      expect(queryError.message).toBe("Invalid pane ID");
      expect(queryError.cause).toBeInstanceOf(Error);
      expect(queryError.message).not.toContain("Zod");
      expect(queryError.message).not.toContain("regex");
    }
  });

  test("labels a session parser validation error", () => {
    try {
      parseSessionId("@2" as never);
      throw new Error("expected invalid session ID to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(QueryValidationError);
      const queryError = error as QueryValidationError;
      expect(queryError.code).toBe("invalid-id");
      expect(queryError.message).toBe("Invalid session ID");
      expect(queryError.cause).toBeInstanceOf(Error);
    }
  });

  test("labels a window parser validation error", () => {
    try {
      parseWindowId("%3" as never);
      throw new Error("expected invalid window ID to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(QueryValidationError);
      const queryError = error as QueryValidationError;
      expect(queryError.code).toBe("invalid-id");
      expect(queryError.message).toBe("Invalid window ID");
      expect(queryError.cause).toBeInstanceOf(Error);
    }
  });

  test("labels a pane parser validation error", () => {
    try {
      parsePaneId("$1" as never);
      throw new Error("expected invalid pane ID to throw");
    } catch (error) {
      expect(error).toBeInstanceOf(QueryValidationError);
      const queryError = error as QueryValidationError;
      expect(queryError.code).toBe("invalid-id");
      expect(queryError.message).toBe("Invalid pane ID");
      expect(queryError.cause).toBeInstanceOf(Error);
    }
  });
});
