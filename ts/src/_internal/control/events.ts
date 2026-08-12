import type { TmuxEvent } from "../../types.js";

/** Framing tmux writes around the response to a command it was sent. */
export type ControlBlockBoundary =
  | { readonly kind: "block-begin" }
  | { readonly kind: "block-end"; readonly failed: boolean };

const BACKSLASH = 0x5c;
const ZERO = 0x30;
const SEVEN = 0x37;

/**
 * Reverse the escaping tmux applies to `%output` payloads.
 *
 * tmux writes a byte below 0x20, and the backslash itself, as `\ooo` in octal
 * and passes every other byte through untouched. High bytes are therefore raw,
 * so unescaping has to happen before decoding or a multi-byte character split
 * across the escape boundary is corrupted.
 */
export function unescapeOutput(payload: Uint8Array): Uint8Array {
  if (!payload.includes(BACKSLASH)) return payload;
  const decoded = new Uint8Array(payload.length);
  let written = 0;
  for (let index = 0; index < payload.length; index += 1) {
    const byte = payload[index]!;
    const digits = payload.subarray(index + 1, index + 4);
    if (
      byte === BACKSLASH &&
      digits.length === 3 &&
      digits.every((digit) => digit >= ZERO && digit <= SEVEN)
    ) {
      decoded[written++] = (digits[0]! - ZERO) * 64 + (digits[1]! - ZERO) * 8 + (digits[2]! - ZERO);
      index += 3;
      continue;
    }
    decoded[written++] = byte;
  }
  return decoded.subarray(0, written);
}

const decoder = new TextDecoder();

function splitArguments(rest: string, limit: number): readonly string[] {
  const parts: string[] = [];
  let remainder = rest;
  while (parts.length < limit - 1) {
    const space = remainder.indexOf(" ");
    if (space === -1) break;
    parts.push(remainder.slice(0, space));
    remainder = remainder.slice(space + 1);
  }
  if (remainder.length > 0 || parts.length > 0) parts.push(remainder);
  return parts;
}

/**
 * Parse one control-mode line.
 *
 * Returns undefined for a line that is not a notification, which is the body of
 * a command's response block.
 */
export function parseControlLine(line: Uint8Array): ControlBlockBoundary | TmuxEvent | undefined {
  if (line.length === 0 || line[0] !== 0x25) return undefined;
  const space = line.indexOf(0x20);
  const name = decoder.decode(line.subarray(1, space === -1 ? line.length : space));
  const rest = space === -1 ? "" : decoder.decode(line.subarray(space + 1));

  switch (name) {
    case "begin":
      return { kind: "block-begin" };
    case "end":
      return { failed: false, kind: "block-end" };
    case "error":
      return { failed: true, kind: "block-end" };
    case "output": {
      // The payload is raw bytes, so it is sliced before decoding.
      const payloadStart = line.indexOf(0x20, space + 1);
      if (space === -1 || payloadStart === -1) break;
      return {
        data: decoder.decode(unescapeOutput(line.subarray(payloadStart + 1))),
        kind: "output",
        paneId: decoder.decode(line.subarray(space + 1, payloadStart)),
      };
    }
    case "extended-output": {
      const [paneId, age, marker] = splitArguments(rest, 4);
      const offset = line.indexOf(0x20, space + 1);
      const ageEnd = offset === -1 ? -1 : line.indexOf(0x20, offset + 1);
      const markerEnd = ageEnd === -1 ? -1 : line.indexOf(0x20, ageEnd + 1);
      if (paneId === undefined || age === undefined || marker !== ":" || markerEnd === -1) break;
      return {
        age: Number(age),
        data: decoder.decode(unescapeOutput(line.subarray(markerEnd + 1))),
        kind: "extended-output",
        paneId,
      };
    }
    case "window-add":
    case "window-close":
    case "unlinked-window-add":
    case "unlinked-window-close":
      return { kind: name, windowId: rest };
    case "window-renamed":
    case "unlinked-window-renamed": {
      const [windowId, windowName] = splitArguments(rest, 2);
      if (windowId === undefined || windowName === undefined) break;
      return { kind: name, name: windowName, windowId };
    }
    case "window-pane-changed": {
      const [windowId, paneId] = splitArguments(rest, 2);
      if (windowId === undefined || paneId === undefined) break;
      return { kind: name, paneId, windowId };
    }
    case "layout-change": {
      const [windowId, layout, visibleLayout, flags] = splitArguments(rest, 4);
      if (windowId === undefined || layout === undefined) break;
      return {
        flags: flags ?? "",
        kind: name,
        layout,
        visibleLayout: visibleLayout ?? layout,
        windowId,
      };
    }
    case "session-changed":
    case "session-renamed": {
      const [sessionId, sessionName] = splitArguments(rest, 2);
      if (sessionId === undefined || sessionName === undefined) break;
      return { kind: name, name: sessionName, sessionId };
    }
    case "sessions-changed":
      return { kind: name };
    case "session-window-changed": {
      const [sessionId, windowId] = splitArguments(rest, 2);
      if (sessionId === undefined || windowId === undefined) break;
      return { kind: name, sessionId, windowId };
    }
    case "client-session-changed": {
      const [client, sessionId, sessionName] = splitArguments(rest, 3);
      if (client === undefined || sessionId === undefined || sessionName === undefined) break;
      return { client, kind: name, name: sessionName, sessionId };
    }
    case "client-detached":
      return { client: rest, kind: name };
    case "pane-mode-changed":
      return { kind: name, paneId: rest };
    case "paste-buffer-changed":
    case "paste-buffer-deleted":
      return { buffer: rest, kind: name };
    case "continue":
    case "pause":
      return { kind: name, paneId: rest };
    case "config-error":
    case "message":
      return { kind: name, message: rest };
    case "exit":
      return { kind: "exit", reason: rest.length === 0 ? undefined : rest };
    default:
      break;
  }
  return { args: splitArguments(rest, Number.MAX_SAFE_INTEGER), kind: "unknown", name };
}
