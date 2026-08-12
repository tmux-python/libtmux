import { describe, expect, test } from "bun:test";

import type { ConnectionAlias, DaemonEpoch, LogicalRef } from "../../src/common.js";
import { QueryValidationError } from "../../src/exc.js";
import {
  createLogicalRef,
  createWinlinkRef,
  decodeLogicalRef,
  encodeLogicalRef,
  logicalRefsEqual,
  type WinlinkRef,
  winlinkRefsEqual,
} from "../../src/_internal/graph/refs.js";

function connection(value = "runtime-a"): ConnectionAlias {
  return value as ConnectionAlias;
}

function epoch(value = 4): DaemonEpoch {
  return value as DaemonEpoch;
}

function expectInvalidQuery(action: () => unknown): void {
  let observed: unknown;
  try {
    action();
  } catch (error) {
    observed = error;
  }
  expect(observed).toBeInstanceOf(QueryValidationError);
  expect(observed).toMatchObject({ code: "invalid-query" });
}

function cloneWithPrototype<Value extends object>(prototype: object | null, value: Value): Value {
  return Object.assign(Object.create(prototype) as object, value) as Value;
}

function hostileEntrypointActions(
  logical: LogicalRef,
  winlink: WinlinkRef,
  hostile: object,
): readonly (() => unknown)[] {
  return [
    () => createLogicalRef(hostile as never),
    () => decodeLogicalRef(hostile),
    () => encodeLogicalRef(hostile as LogicalRef),
    () => createWinlinkRef(hostile as never),
    () => logicalRefsEqual(logical, hostile as LogicalRef),
    () => winlinkRefsEqual(winlink, hostile as WinlinkRef),
  ];
}

describe("logical references", () => {
  test("strictly round-trips each durable logical kind", () => {
    const inputs = [
      { connection: connection(), epoch: epoch(), id: "$1", kind: "session" as const },
      { connection: connection(), epoch: epoch(), id: "@2", kind: "window" as const },
      { connection: connection(), epoch: epoch(), id: "%3", kind: "pane" as const },
    ];

    for (const input of inputs) {
      const ref = createLogicalRef(input);
      const encoded = encodeLogicalRef(ref);
      const decoded = decodeLogicalRef(JSON.parse(JSON.stringify(encoded)));

      expect(Object.keys(ref)).toEqual(["connection", "epoch", "kind", "id"]);
      expect(Object.keys(encoded)).toEqual(["connection", "epoch", "kind", "id"]);
      expect(Object.isFrozen(ref)).toBe(true);
      expect(Object.isFrozen(encoded)).toBe(true);
      expect(Object.isFrozen(decoded)).toBe(true);
      expect(decoded).toEqual(ref);
      expect(logicalRefsEqual(decoded, ref)).toBe(true);
      expect(JSON.stringify(encoded)).not.toContain("socket");
      expect(JSON.stringify(encoded)).not.toContain("executable");
      expect(JSON.stringify(encoded)).not.toContain("environment");
    }
  });

  test("rejects malformed, over-specified, and mismatched serialized shapes", () => {
    const invalid: readonly unknown[] = [
      null,
      {},
      { connection: "", epoch: 0, id: "$1", kind: "session" },
      { connection: "a", epoch: -1, id: "$1", kind: "session" },
      { connection: "a", epoch: 1.5, id: "$1", kind: "session" },
      { connection: "a", epoch: Number.MAX_SAFE_INTEGER + 1, id: "$1", kind: "session" },
      { connection: "a", epoch: 0, id: "@1", kind: "session" },
      { connection: "a", epoch: 0, id: "$1", kind: "window" },
      { connection: "a", epoch: 0, id: "%1", kind: "client" },
      {
        connection: "a",
        epoch: 0,
        id: "$1",
        kind: "session",
        socketPath: "/private/socket",
      },
      {
        connection: "a",
        environment: { SECRET: "value" },
        epoch: 0,
        id: "$1",
        kind: "session",
      },
      {
        connection: "a",
        epoch: 0,
        id: "$1",
        kind: "session",
        transport: {},
      },
      {
        connection: "a",
        epoch: 0,
        id: "@1",
        kind: "winlink",
      },
    ];

    for (const value of invalid) {
      expectInvalidQuery(() => decodeLogicalRef(value));
    }
  });

  test("revalidates branded inputs before encoding", () => {
    const ref = createLogicalRef({
      connection: connection(),
      epoch: epoch(),
      id: "$8",
      kind: "session",
    });
    const polluted = {
      ...ref,
      executable: "/private/tmux",
    } as LogicalRef;

    expectInvalidQuery(() => encodeLogicalRef(polluted));
    expectInvalidQuery(() => encodeLogicalRef({ ...ref, id: "@8" } as unknown as LogicalRef));
    expectInvalidQuery(() =>
      encodeLogicalRef({ ...ref, connection: connection("") } as LogicalRef),
    );
    expectInvalidQuery(() => encodeLogicalRef({ ...ref, epoch: epoch(1.5) } as LogicalRef));
    expectInvalidQuery(() =>
      encodeLogicalRef({ ...ref, epoch: epoch(Number.MAX_SAFE_INTEGER + 1) } as LogicalRef),
    );
    expectInvalidQuery(() =>
      createLogicalRef({ connection: connection(""), epoch: epoch(), id: "$8", kind: "session" }),
    );
    expectInvalidQuery(() =>
      createLogicalRef({ connection: connection(), epoch: epoch(-1), id: "$8", kind: "session" }),
    );
    expectInvalidQuery(() =>
      createLogicalRef({
        connection: connection(),
        epoch: epoch(1.5),
        id: "$8",
        kind: "session",
      }),
    );
    expectInvalidQuery(() =>
      createLogicalRef({
        connection: connection(),
        epoch: epoch(Number.MAX_SAFE_INTEGER + 1),
        id: "$8",
        kind: "session",
      }),
    );
    expectInvalidQuery(() =>
      createLogicalRef({
        connection: connection(),
        epoch: epoch(),
        id: "@8",
        kind: "session",
      } as never),
    );
  });

  test("compares every logical-reference dimension", () => {
    const base = createLogicalRef({
      connection: connection("a"),
      epoch: epoch(1),
      id: "$1",
      kind: "session",
    });
    const variants: readonly LogicalRef[] = [
      createLogicalRef({ connection: connection("b"), epoch: epoch(1), id: "$1", kind: "session" }),
      createLogicalRef({ connection: connection("a"), epoch: epoch(2), id: "$1", kind: "session" }),
      createLogicalRef({ connection: connection("a"), epoch: epoch(1), id: "$2", kind: "session" }),
      createLogicalRef({ connection: connection("a"), epoch: epoch(1), id: "@1", kind: "window" }),
    ];

    expect(logicalRefsEqual(base, base)).toBe(true);
    for (const variant of variants) expect(logicalRefsEqual(base, variant)).toBe(false);
  });
});

describe("winlink references", () => {
  test("keeps contextual indexes distinct and frozen", () => {
    const first = createWinlinkRef({
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@2",
      windowIndex: "3",
    });
    const second = createWinlinkRef({
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@2",
      windowIndex: "7",
    });

    expect(Object.keys(first)).toEqual([
      "connection",
      "epoch",
      "kind",
      "sessionId",
      "windowId",
      "windowIndex",
    ]);
    expect(Object.isFrozen(first)).toBe(true);
    expect(winlinkRefsEqual(first, first)).toBe(true);
    expect(winlinkRefsEqual(first, second)).toBe(false);
    expectInvalidQuery(() => decodeLogicalRef(first));
  });

  test("validates every edge identity component", () => {
    const base = {
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@2",
      windowIndex: "0",
    } as const;
    const invalid = [
      { ...base, connection: connection("") },
      { ...base, epoch: epoch(-1) },
      { ...base, epoch: epoch(1.5) },
      { ...base, epoch: epoch(Number.MAX_SAFE_INTEGER + 1) },
      { ...base, sessionId: "@1" },
      { ...base, windowId: "$2" },
      { ...base, windowIndex: "-1" },
      { ...base, windowIndex: "01" },
      { ...base, windowIndex: "1.5" },
      { ...base, windowIndex: String(Number.MAX_SAFE_INTEGER + 1) },
    ];

    for (const value of invalid) {
      expectInvalidQuery(() => createWinlinkRef(value));
    }
  });

  test("compares alias, epoch, session, window, and index", () => {
    const make = (
      options: Partial<{
        connection: ConnectionAlias;
        epoch: DaemonEpoch;
        sessionId: string;
        windowId: string;
        windowIndex: string;
      }> = {},
    ) =>
      createWinlinkRef({
        connection: options.connection ?? connection("a"),
        epoch: options.epoch ?? epoch(1),
        sessionId: options.sessionId ?? "$1",
        windowId: options.windowId ?? "@1",
        windowIndex: options.windowIndex ?? "1",
      });
    const base = make();
    const matching = make();
    const variants = [
      make({ connection: connection("b") }),
      make({ epoch: epoch(2) }),
      make({ sessionId: "$2" }),
      make({ windowId: "@2" }),
      make({ windowIndex: "2" }),
    ];

    expect(matching).not.toBe(base);
    expect(winlinkRefsEqual(base, matching)).toBe(true);
    for (const variant of variants) expect(winlinkRefsEqual(base, variant)).toBe(false);
  });
});

describe("reference input hardening", () => {
  test("accepts null prototypes but rejects custom prototypes at every entrypoint", () => {
    const logicalInput = {
      connection: connection(),
      epoch: epoch(),
      id: "$1",
      kind: "session" as const,
    };
    const logical = createLogicalRef(logicalInput);
    const encoded = encodeLogicalRef(logical);
    const winlinkInput = {
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@1",
      windowIndex: "1",
    };
    const winlink = createWinlinkRef(winlinkInput);

    expect(createLogicalRef(cloneWithPrototype(null, logicalInput))).toEqual(logical);
    expect(decodeLogicalRef(cloneWithPrototype(null, encoded))).toEqual(logical);
    expect(encodeLogicalRef(cloneWithPrototype(null, logical))).toEqual(encoded);
    expect(createWinlinkRef(cloneWithPrototype(null, winlinkInput))).toEqual(winlink);
    expect(logicalRefsEqual(logical, cloneWithPrototype(null, logical))).toBe(true);
    expect(winlinkRefsEqual(winlink, cloneWithPrototype(null, winlink))).toBe(true);

    const customPrototype = { transport: { execute() {} } };
    for (const action of [
      () => createLogicalRef(cloneWithPrototype(customPrototype, logicalInput)),
      () => decodeLogicalRef(cloneWithPrototype(customPrototype, encoded)),
      () => encodeLogicalRef(cloneWithPrototype(customPrototype, logical)),
      () => createWinlinkRef(cloneWithPrototype(customPrototype, winlinkInput)),
      () => logicalRefsEqual(logical, cloneWithPrototype(customPrototype, logical)),
      () => winlinkRefsEqual(winlink, cloneWithPrototype(customPrototype, winlink)),
    ]) {
      expectInvalidQuery(action);
    }
  });

  test("maps hostile reflection failures to invalid-query at every entrypoint", () => {
    const logical = createLogicalRef({
      connection: connection(),
      epoch: epoch(),
      id: "$1",
      kind: "session",
    });
    const winlink = createWinlinkRef({
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@1",
      windowIndex: "1",
    });
    const hostileValues = [
      new Proxy(
        {},
        {
          getPrototypeOf() {
            throw new Error("hostile prototype reflection");
          },
        },
      ),
      new Proxy(
        {},
        {
          ownKeys() {
            throw new Error("hostile own-key reflection");
          },
        },
      ),
    ];

    for (const hostile of hostileValues) {
      for (const action of hostileEntrypointActions(logical, winlink, hostile)) {
        expectInvalidQuery(action);
      }
    }
  });

  test("rejects keyset mutation during descriptor inspection at every entrypoint", () => {
    const logicalInput = {
      connection: connection(),
      epoch: epoch(),
      id: "$1",
      kind: "session" as const,
    };
    const logical = createLogicalRef(logicalInput);
    const encoded = encodeLogicalRef(logical);
    const winlinkInput = {
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@1",
      windowIndex: "1",
    };
    const winlink = createWinlinkRef(winlinkInput);
    const mutateDuringInspection = <Value extends object>(value: Value): Value => {
      const target = { ...value } as Value;
      let mutated = false;
      return new Proxy(target, {
        getOwnPropertyDescriptor(inner, key) {
          const descriptor = Reflect.getOwnPropertyDescriptor(inner, key);
          if (!mutated) {
            mutated = true;
            Reflect.defineProperty(inner, "unexpected", {
              configurable: true,
              enumerable: true,
              value: "injected",
              writable: true,
            });
          }
          return descriptor;
        },
      });
    };

    const observed = [
      () => createLogicalRef(mutateDuringInspection(logicalInput)),
      () => decodeLogicalRef(mutateDuringInspection(encoded)),
      () => encodeLogicalRef(mutateDuringInspection(logical)),
      () => createWinlinkRef(mutateDuringInspection(winlinkInput)),
      () => logicalRefsEqual(logical, mutateDuringInspection(logical)),
      () => winlinkRefsEqual(winlink, mutateDuringInspection(winlink)),
    ].map((action) => {
      try {
        action();
      } catch (error) {
        return error;
      }
      return undefined;
    });

    for (const error of observed) {
      expect(error).toBeInstanceOf(QueryValidationError);
      expect(error).toMatchObject({ code: "invalid-query" });
    }
  });

  test("maps revoked proxies to invalid-query at every entrypoint", () => {
    const logical = createLogicalRef({
      connection: connection(),
      epoch: epoch(),
      id: "$1",
      kind: "session",
    });
    const winlink = createWinlinkRef({
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@1",
      windowIndex: "1",
    });
    const revocable = Proxy.revocable({}, {});
    revocable.revoke();

    for (const action of hostileEntrypointActions(logical, winlink, revocable.proxy)) {
      expectInvalidQuery(action);
    }
  });

  test("rewraps noncanonical validation errors thrown by proxy traps", () => {
    const logical = createLogicalRef({
      connection: connection(),
      epoch: epoch(),
      id: "$1",
      kind: "session",
    });
    const winlink = createWinlinkRef({
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@1",
      windowIndex: "1",
    });
    const hostile = new Proxy(
      {},
      {
        getPrototypeOf() {
          throw new QueryValidationError({ code: "invalid-id", message: "proxy trap" });
        },
      },
    );

    for (const action of hostileEntrypointActions(logical, winlink, hostile)) {
      expectInvalidQuery(action);
    }
  });

  test("wraps hostile thrown proxies without inspecting the cause", () => {
    const logical = createLogicalRef({
      connection: connection(),
      epoch: epoch(),
      id: "$1",
      kind: "session",
    });
    const winlink = createWinlinkRef({
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@1",
      windowIndex: "1",
    });
    const hostileCause = new Proxy(Object.create(null) as object, {
      get() {
        throw new Error("hostile cause accessor");
      },
      getPrototypeOf() {
        throw new Error("hostile cause prototype");
      },
    });
    const hostile = new Proxy(
      {},
      {
        getPrototypeOf() {
          throw hostileCause;
        },
      },
    );

    for (const action of hostileEntrypointActions(logical, winlink, hostile)) {
      expectInvalidQuery(action);
    }
  });

  test("rejects equality forgeries without invoking accessors", () => {
    const logical = createLogicalRef({
      connection: connection(),
      epoch: epoch(),
      id: "$1",
      kind: "session",
    });
    const winlink = createWinlinkRef({
      connection: connection(),
      epoch: epoch(),
      sessionId: "$1",
      windowId: "@1",
      windowIndex: "1",
    });
    let logicalGetterCalls = 0;
    let winlinkGetterCalls = 0;
    const logicalGetterForgery = { ...logical };
    Object.defineProperty(logicalGetterForgery, "id", {
      enumerable: true,
      get() {
        logicalGetterCalls += 1;
        return "$1";
      },
    });
    const logicalExtraForgery = Object.assign({ ...logical }, { executable: "tmux" });
    Object.defineProperty(logicalExtraForgery, "id", {
      enumerable: true,
      get() {
        logicalGetterCalls += 1;
        return "$1";
      },
    });
    const winlinkGetterForgery = { ...winlink };
    Object.defineProperty(winlinkGetterForgery, "windowIndex", {
      enumerable: true,
      get() {
        winlinkGetterCalls += 1;
        return "1";
      },
    });
    const winlinkExtraForgery = Object.assign({ ...winlink }, { logger: {} });
    Object.defineProperty(winlinkExtraForgery, "windowIndex", {
      enumerable: true,
      get() {
        winlinkGetterCalls += 1;
        return "1";
      },
    });

    expectInvalidQuery(() => logicalRefsEqual(logical, logicalGetterForgery as LogicalRef));
    expectInvalidQuery(() => logicalRefsEqual(logical, logicalExtraForgery as LogicalRef));
    expectInvalidQuery(() => winlinkRefsEqual(winlink, winlinkGetterForgery as WinlinkRef));
    expectInvalidQuery(() => winlinkRefsEqual(winlink, winlinkExtraForgery as WinlinkRef));
    expect(logicalGetterCalls).toBe(0);
    expect(winlinkGetterCalls).toBe(0);
  });
});
