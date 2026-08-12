import { describe, expect, test } from "bun:test";

import {
  compareTmuxVersions,
  parseTmuxVersion,
  tmuxVersionAtLeast,
  tmuxVersionIsExact,
} from "../../src/_internal/runtime/tmux_version.js";

describe("tmux versions", () => {
  test("orders final and lettered releases chronologically", () => {
    const versions = ["3.10", "3.7b", "3.7", "3.7a", "3.6a"]
      .map(parseTmuxVersion)
      .sort(compareTmuxVersions)
      .map(({ raw }) => raw);

    expect(versions).toEqual(["3.6a", "3.7", "3.7a", "3.7b", "3.10"]);
  });

  test("retains a frozen normalized representation", () => {
    const version = parseTmuxVersion("3.7b");

    expect(version).toEqual({ major: 3, minor: 7, raw: "3.7b", suffix: "b" });
    expect(Object.isFrozen(version)).toBe(true);
  });

  test("orders raw master builds above every tagged release", () => {
    const latestTagged = parseTmuxVersion("99.9z");

    expect(compareTmuxVersions(parseTmuxVersion("master"), latestTagged)).toBeGreaterThan(0);
    expect(compareTmuxVersions(parseTmuxVersion("3.6a-master"), latestTagged)).toBeGreaterThan(0);
    expect(parseTmuxVersion("3.6a-master").raw).toBe("3.6a-master");
  });

  test("carries ordinary version floors into later patch releases", () => {
    expect(tmuxVersionAtLeast(parseTmuxVersion("3.7"), parseTmuxVersion("3.7"))).toBe(true);
    expect(tmuxVersionAtLeast(parseTmuxVersion("3.7a"), parseTmuxVersion("3.7"))).toBe(true);
    expect(tmuxVersionAtLeast(parseTmuxVersion("3.7b"), parseTmuxVersion("3.7"))).toBe(true);
    expect(tmuxVersionAtLeast(parseTmuxVersion("3.6a"), parseTmuxVersion("3.7"))).toBe(false);
  });

  test("keeps exact-version quirks exact", () => {
    const quirkVersion = parseTmuxVersion("3.7");

    expect(tmuxVersionIsExact(parseTmuxVersion("3.7"), quirkVersion)).toBe(true);
    expect(tmuxVersionIsExact(parseTmuxVersion("3.7a"), quirkVersion)).toBe(false);
    expect(tmuxVersionIsExact(parseTmuxVersion("3.7b"), quirkVersion)).toBe(false);
  });

  test("rejects noncanonical or incomplete versions", () => {
    for (const value of ["3", "3.7aa", "3.7-rc1", "v3.7", "tmux 3.7", "3.7 ", " 3.7"]) {
      expect(() => parseTmuxVersion(value)).toThrow("invalid tmux version");
    }
  });
});
