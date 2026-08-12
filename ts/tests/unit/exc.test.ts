import { describe, expect, test } from "bun:test";

import * as exception from "../../src/exc.js";

import {
  AdjustmentDirectionRequiresAdjustment,
  LibTmuxException,
  MultipleMatchesError,
  MultipleObjectsReturned,
  NoMatchError,
  ObjectDoesNotExist,
  PaneAdjustmentDirectionRequiresAdjustment,
  QueryValidationError,
  WindowAdjustmentDirectionRequiresAdjustment,
  WindowError,
} from "../../src/exc.js";

function nestedQuery(edges: number): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  let current = root;
  for (let index = 0; index < edges; index += 1) {
    const child: Record<string, unknown> = {};
    current.AND = [child];
    current = child;
  }
  current.name = { regex: { flags: "", pattern: "^alpha$" } };
  return root;
}

function prefixedQueryCycle(edges: number): Record<string, unknown> {
  const root: Record<string, unknown> = {};
  let current = root;
  for (let index = 0; index < edges; index += 1) {
    const child: Record<string, unknown> = {};
    current.AND = [child];
    current = child;
  }
  current.AND = [root];
  return root;
}

function arrayQueryDepth(depth: number): Record<string, unknown> {
  let value: unknown = "leaf";
  for (let index = 0; index < depth; index += 1) value = [value];
  return { value };
}

describe("query exceptions", () => {
  test("preserve query, count, subcommand, message, and cause", () => {
    const cause = new Error("transport detail");
    const error = new MultipleObjectsReturned({
      cause,
      count: 2,
      query: { pane_id: "%3" },
      subcommand: "list-panes",
    });

    expect(error).toBeInstanceOf(LibTmuxException);
    expect(error.name).toBe("MultipleObjectsReturned");
    expect(error.count).toBe(2);
    expect(error.query).toEqual({ pane_id: "%3" });
    expect(error.cause).toBe(cause);
    expect(error.message).toBe("Multiple objects returned (2): pane_id='%3'");
    expect(String(error)).toBe("list-panes: Multiple objects returned (2): pane_id='%3'");
  });

  test("keeps canonical query errors in the compatibility hierarchy", () => {
    expect(new NoMatchError({ query: { window_id: "@2" } })).toBeInstanceOf(ObjectDoesNotExist);
    expect(new MultipleMatchesError({ count: 2 })).toBeInstanceOf(MultipleObjectsReturned);
  });

  test("formats every valid depth-64 criterion without a depth sentinel", () => {
    const query = nestedQuery(64);
    const error = new NoMatchError({ query });

    expect(error.message).toBe(`No objects found: AND=${JSON.stringify(query.AND)}`);
    expect(error.message).not.toContain("[query value exceeds maximum depth]");
  });

  test("formats exactly 256 nested containers before using the depth sentinel", () => {
    const atLimit = new NoMatchError({ query: arrayQueryDepth(256) });
    const beyondLimit = new NoMatchError({ query: arrayQueryDepth(257) });

    expect(atLimit.message).not.toContain("[query value exceeds maximum depth]");
    expect(beyondLimit.message).toContain('"[query value exceeds maximum depth]"');
  });

  test("bounds deeply nested acyclic public query formatting", () => {
    const query = nestedQuery(20_000);
    const noMatch = new NoMatchError({ query });
    const multiple = new MultipleMatchesError({ count: 2, query });
    const formatted = noMatch.message.slice("No objects found: ".length);

    expect(noMatch.message).toContain('"[query value exceeds maximum depth]"');
    expect(noMatch.message.length).toBeLessThan(10_000);
    expect(multiple.message).toBe(`Multiple objects returned (2): ${formatted}`);
  });

  test("bounds deep prefixed cycles while retaining shallow cycle evidence", () => {
    const deep = new NoMatchError({ query: prefixedQueryCycle(20_000) });
    const shallow = new NoMatchError({ query: prefixedQueryCycle(32) });

    expect(deep.message).toContain('"[query value exceeds maximum depth]"');
    expect(deep.message.length).toBeLessThan(10_000);
    expect(shallow.message).toContain('"[circular query value]"');
    expect(shallow.message).not.toContain("[query value exceeds maximum depth]");
  });

  test("wraps validation failures behind a stable package error", () => {
    const cause = new Error("regex implementation detail");
    const error = new QueryValidationError({
      cause,
      code: "invalid-id",
      message: "Invalid pane ID",
    });

    expect(error.name).toBe("QueryValidationError");
    expect(error.code).toBe("invalid-id");
    expect(error.cause).toBe(cause);
    expect(error.message).toBe("Invalid pane ID");
    expect(error.message).not.toContain("regex");
    expect(error.message).not.toContain("Zod");
  });
});

describe("Python exception compatibility", () => {
  test("constructs every public Python exception with its stable name, message, and library ancestry", () => {
    const cases: ReadonlyArray<readonly [string, Error, string]> = [
      [
        "AdjustmentDirectionRequiresAdjustment",
        new exception.AdjustmentDirectionRequiresAdjustment(),
        "adjustment_direction requires adjustment",
      ],
      ["AmbiguousOption", new exception.AmbiguousOption(), ""],
      [
        "BadSessionName",
        new exception.BadSessionName("contains colon", "a:b"),
        "Bad session name: contains colon (session name: a:b)",
      ],
      [
        "DeprecatedError",
        new exception.DeprecatedError({ deprecated: "old", replacement: "new", version: "0.62" }),
        "old was deprecated in 0.62 and has been removed. Use new instead.",
      ],
      ["InvalidOption", new exception.InvalidOption(), ""],
      ["LibTmuxException", new exception.LibTmuxException("base"), "base"],
      [
        "MultipleActiveWindows",
        new exception.MultipleActiveWindows(2),
        "Multiple active windows: 2 found",
      ],
      [
        "MultipleObjectsReturned",
        new exception.MultipleObjectsReturned({ count: 2, query: { pane_id: "%3" } }),
        "Multiple objects returned (2): pane_id='%3'",
      ],
      ["NoActiveWindow", new exception.NoActiveWindow(), "No active windows found"],
      [
        "NotInsideTmux",
        new exception.NotInsideTmux("TMUX_PANE", { reason: "not a pane id" }),
        "Not inside a tmux pane: $TMUX_PANE is not a pane id",
      ],
      ["NoWindowsExist", new exception.NoWindowsExist(), "No windows exist for object"],
      [
        "ObjectDoesNotExist",
        new exception.ObjectDoesNotExist({ query: { pane_id: "%3" } }),
        "No objects found: pane_id='%3'",
      ],
      ["OptionError", new exception.OptionError(), ""],
      [
        "PaneAdjustmentDirectionRequiresAdjustment",
        new exception.PaneAdjustmentDirectionRequiresAdjustment(),
        "adjustment_direction requires adjustment",
      ],
      ["PaneError", new exception.PaneError(), ""],
      ["PaneNotFound", new exception.PaneNotFound("%3"), "Pane not found: %3"],
      [
        "RequiresDigitOrPercentage",
        new exception.RequiresDigitOrPercentage(),
        "Requires digit (int or str digit) or a percentage.",
      ],
      ["TmuxCommandNotFound", new exception.TmuxCommandNotFound(), ""],
      [
        "TmuxObjectDoesNotExist",
        new exception.TmuxObjectDoesNotExist({
          list_cmd: "list-panes",
          list_extra_args: ["-t", "%3"],
          obj_id: "%3",
          obj_key: "pane_id",
        }),
        "Could not find pane_id=%3 for list-panes ('-t', '%3')",
      ],
      ["TmuxSessionExists", new exception.TmuxSessionExists(), ""],
      [
        "UnknownColorOption",
        new exception.UnknownColorOption(),
        "Server.colors must equal 88 or 256",
      ],
      ["UnknownOption", new exception.UnknownOption(), ""],
      [
        "VariableUnpackingError",
        new exception.VariableUnpackingError(),
        "Unexpected variable: None",
      ],
      ["VersionTooLow", new exception.VersionTooLow(), ""],
      ["WaitTimeout", new exception.WaitTimeout(), ""],
      [
        "WindowAdjustmentDirectionRequiresAdjustment",
        new exception.WindowAdjustmentDirectionRequiresAdjustment(),
        "adjustment_direction requires adjustment",
      ],
      ["WindowError", new exception.WindowError(), ""],
    ];

    for (const [name, error, message] of cases) {
      expect(error).toBeInstanceOf(LibTmuxException);
      expect(error.name).toBe(name);
      expect(error.message).toBe(message);
    }

    expect(new exception.UnknownOption()).toBeInstanceOf(exception.OptionError);
    expect(new exception.UnknownColorOption()).toBeInstanceOf(exception.UnknownOption);
    expect(new exception.UnknownColorOption()).toBeInstanceOf(exception.OptionError);
    expect(new exception.InvalidOption()).toBeInstanceOf(exception.OptionError);
    expect(new exception.AmbiguousOption()).toBeInstanceOf(exception.OptionError);
    expect(new exception.PaneNotFound()).toBeInstanceOf(exception.PaneError);
    expect(new exception.TmuxObjectDoesNotExist()).toBeInstanceOf(exception.ObjectDoesNotExist);
    expect(new exception.NoMatchError()).toBeInstanceOf(exception.ObjectDoesNotExist);
    expect(new exception.MultipleMatchesError()).toBeInstanceOf(exception.MultipleObjectsReturned);
    expect(new exception.MultipleActiveWindows(2)).toBeInstanceOf(exception.WindowError);
    expect(new exception.NoActiveWindow()).toBeInstanceOf(exception.WindowError);
    expect(new exception.NoWindowsExist()).toBeInstanceOf(exception.WindowError);
    expect(new exception.WindowAdjustmentDirectionRequiresAdjustment()).toBeInstanceOf(
      exception.WindowError,
    );
    expect(new exception.PaneAdjustmentDirectionRequiresAdjustment()).toBeInstanceOf(
      exception.WindowError,
    );
    expect(new exception.UnknownOption()).not.toBeInstanceOf(exception.PaneError);
    expect(new exception.PaneNotFound()).not.toBeInstanceOf(exception.WindowError);
    expect(new exception.TmuxObjectDoesNotExist()).not.toBeInstanceOf(exception.PaneError);
    expect(new exception.WindowError()).not.toBeInstanceOf(exception.PaneError);
  });
});

describe("adjustment-direction exceptions", () => {
  test("preserve both Python library lineages without admitting impostors", () => {
    const cause = new Error("resize cause");
    const window = new WindowAdjustmentDirectionRequiresAdjustment({ cause });
    const pane = new PaneAdjustmentDirectionRequiresAdjustment();
    const impostor = { name: "WindowAdjustmentDirectionRequiresAdjustment" };

    expect(window).toBeInstanceOf(WindowAdjustmentDirectionRequiresAdjustment);
    expect(window).toBeInstanceOf(WindowError);
    expect(window).toBeInstanceOf(AdjustmentDirectionRequiresAdjustment);
    expect(window).toBeInstanceOf(LibTmuxException);
    expect(window).toBeInstanceOf(Error);
    expect(window).not.toBeInstanceOf(PaneAdjustmentDirectionRequiresAdjustment);
    expect(window.name).toBe("WindowAdjustmentDirectionRequiresAdjustment");
    expect(window.message).toBe("adjustment_direction requires adjustment");
    expect(window.cause).toBe(cause);
    expect(window.stack).toContain("WindowAdjustmentDirectionRequiresAdjustment");
    expect(pane).toBeInstanceOf(PaneAdjustmentDirectionRequiresAdjustment);
    expect(pane).toBeInstanceOf(AdjustmentDirectionRequiresAdjustment);
    expect(new WindowError()).not.toBeInstanceOf(AdjustmentDirectionRequiresAdjustment);
    expect(impostor).not.toBeInstanceOf(AdjustmentDirectionRequiresAdjustment);
  });

  test("keeps native subclass behavior for base and concrete classes", () => {
    class AdjustmentSubclass extends AdjustmentDirectionRequiresAdjustment {}
    class WindowAdjustmentSubclass extends WindowAdjustmentDirectionRequiresAdjustment {}

    expect(new AdjustmentSubclass()).toBeInstanceOf(AdjustmentDirectionRequiresAdjustment);
    expect(new AdjustmentSubclass()).toBeInstanceOf(AdjustmentSubclass);
    expect(new WindowAdjustmentSubclass()).toBeInstanceOf(
      WindowAdjustmentDirectionRequiresAdjustment,
    );
    expect(new WindowAdjustmentSubclass()).toBeInstanceOf(AdjustmentDirectionRequiresAdjustment);
    expect(new WindowAdjustmentSubclass()).toBeInstanceOf(WindowAdjustmentSubclass);
  });
});
