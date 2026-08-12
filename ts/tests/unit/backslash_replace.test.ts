import { describe, expect, test } from "bun:test";

import {
  BackslashReplaceDecoder,
  decodeBackslashReplace,
} from "../../src/_internal/codec/backslash_replace.js";
import { adaptRawResult } from "../../src/_internal/operations/request.js";

describe("UTF-8 backslash replacement", () => {
  test("buffers valid sequences and replaces malformed input per byte across chunks", () => {
    const decoder = new BackslashReplaceDecoder();

    expect(decoder.write(Uint8Array.of(0xe2))).toBe("");
    expect(decoder.write(Uint8Array.of(0x82))).toBe("");
    expect(decoder.write(Uint8Array.of(0xac, 0xff, 0xc3))).toBe("€\\xff");
    expect(decoder.write(Uint8Array.of(0x28))).toBe("\\xc3(");
    expect(decoder.end()).toBe("");
  });

  test("escapes every byte of an incomplete final sequence", () => {
    expect(decodeBackslashReplace(Uint8Array.of(0x61, 0xe2, 0x82))).toBe("a\\xe2\\x82");
  });

  test("preserves Python stdout trimming and stderr filtering", () => {
    const result = adaptRawResult({
      cmd: ["tmux", "display-message"],
      returncode: 1,
      signal: null,
      stderr: new TextEncoder().encode("first error\n\nsecond error\n"),
      stdout: new TextEncoder().encode("first\n\nsecond\n\n"),
    });

    expect(result).toEqual({
      cmd: ["tmux", "display-message"],
      returncode: 1,
      stderr: ["first error", "second error"],
      stdout: ["first", "", "second"],
    });
  });

  test("copies the first has-session error line to empty stdout", () => {
    const result = adaptRawResult({
      cmd: ["tmux", "-Lnamed", "has-session", "-t", "missing"],
      returncode: 1,
      signal: null,
      stderr: new TextEncoder().encode("can't find session: missing\n"),
      stdout: new Uint8Array(),
    });

    expect(result.stdout).toEqual(["can't find session: missing"]);
    expect(result.stderr).toEqual(["can't find session: missing"]);
  });
});
