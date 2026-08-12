import { describe, expect, test } from "bun:test";

import { parseControlLine, unescapeOutput } from "../../src/_internal/control/events.js";
import type { TmuxEvent } from "../../src/types.js";

const encoder = new TextEncoder();

function parse(line: string): ReturnType<typeof parseControlLine> {
  return parseControlLine(encoder.encode(line));
}

function event(line: string): TmuxEvent {
  const parsed = parse(line);
  if (parsed === undefined || parsed.kind === "block-begin" || parsed.kind === "block-end") {
    throw new Error(`expected a notification, parsed ${JSON.stringify(parsed)}`);
  }
  return parsed;
}

describe("control-mode line parsing", () => {
  test("ignores lines that are not notifications", () => {
    expect(parse("")).toBeUndefined();
    expect(parse("plain command output")).toBeUndefined();
    expect(parse("0: [80x24]")).toBeUndefined();
  });

  test("reports the framing tmux wraps around a command response", () => {
    expect(parse("%begin 1700000000 1 1")).toEqual({ kind: "block-begin" });
    expect(parse("%end 1700000000 1 1")).toEqual({ failed: false, kind: "block-end" });
    expect(parse("%error 1700000000 1 1")).toEqual({ failed: true, kind: "block-end" });
  });

  test("parses each notification into its own shape", () => {
    expect(event("%window-add @3")).toEqual({ kind: "window-add", windowId: "@3" });
    expect(event("%window-close @3")).toEqual({ kind: "window-close", windowId: "@3" });
    expect(event("%unlinked-window-add @4")).toEqual({
      kind: "unlinked-window-add",
      windowId: "@4",
    });
    expect(event("%window-renamed @3 my window")).toEqual({
      kind: "window-renamed",
      name: "my window",
      windowId: "@3",
    });
    expect(event("%window-pane-changed @3 %7")).toEqual({
      kind: "window-pane-changed",
      paneId: "%7",
      windowId: "@3",
    });
    expect(event("%session-changed $0 work")).toEqual({
      kind: "session-changed",
      name: "work",
      sessionId: "$0",
    });
    expect(event("%sessions-changed")).toEqual({ kind: "sessions-changed" });
    expect(event("%session-window-changed $0 @2")).toEqual({
      kind: "session-window-changed",
      sessionId: "$0",
      windowId: "@2",
    });
    expect(event("%client-session-changed /dev/pts/3 $1 other")).toEqual({
      client: "/dev/pts/3",
      kind: "client-session-changed",
      name: "other",
      sessionId: "$1",
    });
    expect(event("%client-detached /dev/pts/3")).toEqual({
      client: "/dev/pts/3",
      kind: "client-detached",
    });
    expect(event("%pane-mode-changed %2")).toEqual({ kind: "pane-mode-changed", paneId: "%2" });
    expect(event("%paste-buffer-changed buffer0")).toEqual({
      buffer: "buffer0",
      kind: "paste-buffer-changed",
    });
    expect(event("%pause %1")).toEqual({ kind: "pause", paneId: "%1" });
    expect(event("%continue %1")).toEqual({ kind: "continue", paneId: "%1" });
    expect(event("%config-error /etc/tmux.conf:3: bad")).toEqual({
      kind: "config-error",
      message: "/etc/tmux.conf:3: bad",
    });
  });

  test("keeps a window name that contains spaces intact", () => {
    expect(event("%window-renamed @1 two  spaces and more")).toMatchObject({
      name: "two  spaces and more",
    });
    expect(event("%session-renamed $1 a b c")).toMatchObject({ name: "a b c" });
  });

  test("parses layout-change with its four fields", () => {
    expect(event("%layout-change @1 bb62,80x24,0,0,1 cc63,80x24,0,0,1 *Z")).toEqual({
      flags: "*Z",
      kind: "layout-change",
      layout: "bb62,80x24,0,0,1",
      visibleLayout: "cc63,80x24,0,0,1",
      windowId: "@1",
    });
  });

  test("reports an exit reason only when tmux gives one", () => {
    expect(event("%exit")).toEqual({ kind: "exit", reason: undefined });
    expect(event("%exit server exited")).toEqual({ kind: "exit", reason: "server exited" });
  });

  test("surfaces an unmodelled notification rather than dropping it", () => {
    expect(event("%future-notification @1 alpha beta")).toEqual({
      args: ["@1", "alpha", "beta"],
      kind: "unknown",
      name: "future-notification",
    });
  });

  test("parses output, preserving spaces in the payload", () => {
    expect(event("%output %1 hello world")).toEqual({
      data: "hello world",
      kind: "output",
      paneId: "%1",
    });
  });

  test("parses extended-output past its age and colon marker", () => {
    expect(event("%extended-output %1 512 : late data")).toEqual({
      age: 512,
      data: "late data",
      kind: "extended-output",
      paneId: "%1",
    });
  });
});

describe("control-mode output unescaping", () => {
  test("decodes the octal escapes tmux writes for control bytes", () => {
    expect(new TextDecoder().decode(unescapeOutput(encoder.encode("a\\015\\012b")))).toBe("a\r\nb");
    expect(new TextDecoder().decode(unescapeOutput(encoder.encode("\\033[0m")))).toBe("\u001b[0m");
  });

  test("decodes an escaped backslash without consuming what follows", () => {
    expect(new TextDecoder().decode(unescapeOutput(encoder.encode("a\\134b")))).toBe("a\\b");
  });

  test("leaves a backslash that does not begin an octal escape alone", () => {
    expect(new TextDecoder().decode(unescapeOutput(encoder.encode("a\\b")))).toBe("a\\b");
    expect(new TextDecoder().decode(unescapeOutput(encoder.encode("a\\99")))).toBe("a\\99");
    expect(new TextDecoder().decode(unescapeOutput(encoder.encode("trailing\\")))).toBe(
      "trailing\\",
    );
  });

  test("passes high bytes through so multi-byte characters survive", () => {
    // tmux escapes only bytes below 0x20 and the backslash, so UTF-8 arrives raw
    // and must be unescaped as bytes before it is decoded.
    const payload = encoder.encode("héllo → 🌍\\012");
    expect(new TextDecoder().decode(unescapeOutput(payload))).toBe("héllo → 🌍\n");
  });

  test("returns the input untouched when there is nothing to unescape", () => {
    const payload = encoder.encode("no escapes here");
    expect(unescapeOutput(payload)).toBe(payload);
  });
});

describe("control-mode event narrowing", () => {
  test("discriminates on kind without a cast", () => {
    const parsed = event("%output %2 text");
    if (parsed.kind !== "output") throw new Error("expected output");
    // Reaching .paneId and .data here is the assertion: the union narrowed.
    expect(`${parsed.paneId}:${parsed.data}`).toBe("%2:text");
  });
});
