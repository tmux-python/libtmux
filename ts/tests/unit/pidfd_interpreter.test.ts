import { describe, expect, test } from "bun:test";

import { resolvePidfdInterpreter } from "../../src/_internal/test/run_root.js";

function proberFor(capable: ReadonlySet<string>, seen: string[]) {
  return async (executable: string): Promise<boolean> => {
    seen.push(executable);
    return capable.has(executable);
  };
}

describe("pidfd interpreter resolution", () => {
  test("selects the first candidate exposing pidfd_open", async () => {
    const seen: string[] = [];
    const resolved = await resolvePidfdInterpreter(
      ["free-threading-python", "/usr/bin/python3", "/opt/python3"],
      proberFor(new Set(["/usr/bin/python3", "/opt/python3"]), seen),
    );

    expect(resolved).toBe("/usr/bin/python3");
    expect(seen).toEqual(["free-threading-python", "/usr/bin/python3"]);
  });

  test("reports no interpreter when every candidate lacks pidfd_open", async () => {
    const seen: string[] = [];
    const resolved = await resolvePidfdInterpreter(
      ["python3", "/usr/bin/python3"],
      proberFor(new Set(), seen),
    );

    expect(resolved).toBeUndefined();
    expect(seen).toEqual(["python3", "/usr/bin/python3"]);
  });

  test("treats a probe failure as an unusable candidate rather than an error", async () => {
    const resolved = await resolvePidfdInterpreter(
      ["missing-python", "/usr/bin/python3"],
      (executable) => {
        if (executable === "missing-python") throw new Error("ENOENT");
        return Promise.resolve(true);
      },
    );

    expect(resolved).toBe("/usr/bin/python3");
  });

  test("resolves nothing when offered no candidates", async () => {
    expect(await resolvePidfdInterpreter([], () => Promise.resolve(true))).toBeUndefined();
  });
});
