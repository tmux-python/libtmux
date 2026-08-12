import { readFile } from "node:fs/promises";

import { describe, expect, test } from "bun:test";

interface ObservableBehavior {
  readonly adaptation: string;
  readonly id: string;
  readonly typescript: string;
}

interface ParityManifest {
  readonly observableBehaviors: readonly ObservableBehavior[];
}

const expected = {
  "collection.inherited-concatenation": {
    adaptation: "Concatenation uses explicit defensive arrays",
    typescript: "[...selection.toArray(), ...values]",
  },
  "collection.inherited-copy": {
    adaptation: "Copying uses toArray",
    typescript: "selection.toArray()",
  },
  "collection.inherited-repetition": {
    adaptation: "Repetition uses defensive arrays",
    typescript: "Array.from({ length: n }, () => selection.toArray()).flat()",
  },
  "collection.inherited-reverse": {
    adaptation: "Reverse uses a defensive array",
    typescript: "selection.toArray().reverse()",
  },
  "collection.inherited-slicing": {
    adaptation: "Slicing uses toArray slice",
    typescript: "selection.toArray().slice(start, end)",
  },
} as const;

describe("Selection parity adaptations", () => {
  test("use plain defensive arrays because Selection has no constructor", async () => {
    const manifest = JSON.parse(
      await readFile(new URL("../../parity/python-0.62.0.json", import.meta.url), "utf8"),
    ) as ParityManifest;
    const observed = Object.fromEntries(
      manifest.observableBehaviors
        .filter(({ id }) => Object.hasOwn(expected, id))
        .map(({ adaptation, id, typescript }) => [id, { adaptation, typescript }]),
    );

    expect(Object.keys(observed).sort()).toEqual(Object.keys(expected).sort());
    expect(observed).toEqual(expected);
    expect(JSON.stringify(observed)).not.toContain("new Selection");
  });
});
