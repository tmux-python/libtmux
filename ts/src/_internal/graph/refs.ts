import type {
  ConnectionAlias,
  DaemonEpoch,
  LogicalRef,
  PaneId,
  SessionId,
  SessionIdInput,
  TmuxIdInput,
  TmuxIdKind,
  WindowId,
  WindowIdInput,
} from "../../common.js";
import { QueryValidationError } from "../../exc.js";

type LogicalRefForKind<Kind extends TmuxIdKind> = Extract<LogicalRef, { readonly kind: Kind }>;

interface LogicalRefInput<Kind extends TmuxIdKind> {
  readonly connection: ConnectionAlias;
  readonly epoch: DaemonEpoch;
  readonly id: NoInfer<TmuxIdInput<Kind>>;
  readonly kind: Kind;
}

export type SerializedLogicalRef =
  | {
      readonly connection: string;
      readonly epoch: number;
      readonly id: string;
      readonly kind: "session";
    }
  | {
      readonly connection: string;
      readonly epoch: number;
      readonly id: string;
      readonly kind: "window";
    }
  | {
      readonly connection: string;
      readonly epoch: number;
      readonly id: string;
      readonly kind: "pane";
    };

export interface WinlinkRef {
  readonly connection: ConnectionAlias;
  readonly epoch: DaemonEpoch;
  readonly kind: "winlink";
  readonly sessionId: SessionId;
  readonly windowId: WindowId;
  readonly windowIndex: string;
}

interface WinlinkRefInput {
  readonly connection: ConnectionAlias;
  readonly epoch: DaemonEpoch;
  readonly sessionId: SessionIdInput;
  readonly windowId: WindowIdInput;
  readonly windowIndex: string;
}

function invalidReference(message: string, cause?: unknown): never {
  throw new QueryValidationError(
    cause === undefined
      ? { code: "invalid-query", message }
      : { cause, code: "invalid-query", message },
  );
}

function readStrictDataRecord(
  value: unknown,
  expectedKeys: readonly string[],
  label: string,
): Readonly<Record<string, unknown>> {
  if (typeof value !== "object" || value === null) {
    return invalidReference(`${label} must be an object`);
  }

  let isArray: boolean;
  let prototype: object | null;
  let ownKeys: readonly PropertyKey[];
  let descriptors: readonly (PropertyDescriptor | undefined)[];
  let finalPrototype: object | null;
  let finalOwnKeys: readonly PropertyKey[];
  try {
    isArray = Array.isArray(value);
    prototype = Object.getPrototypeOf(value);
    ownKeys = Reflect.ownKeys(value);
    descriptors = expectedKeys.map((key) => Object.getOwnPropertyDescriptor(value, key));
    finalPrototype = Object.getPrototypeOf(value);
    finalOwnKeys = Reflect.ownKeys(value);
  } catch (error) {
    return invalidReference(`${label} could not be inspected`, error);
  }

  if (isArray) return invalidReference(`${label} must be an object`);
  if (
    prototype !== finalPrototype ||
    (prototype !== Object.prototype && prototype !== null) ||
    (finalPrototype !== Object.prototype && finalPrototype !== null)
  ) {
    return invalidReference(`${label} has an invalid prototype`);
  }
  if (
    ownKeys.length !== expectedKeys.length ||
    ownKeys.some((key) => typeof key !== "string" || !expectedKeys.includes(key)) ||
    ownKeys.length !== finalOwnKeys.length ||
    ownKeys.some((key) => !finalOwnKeys.includes(key))
  ) {
    return invalidReference(`${label} has invalid keys`);
  }

  const record: Record<string, unknown> = {};
  for (const [index, key] of expectedKeys.entries()) {
    const descriptor = descriptors[index];
    if (descriptor === undefined || !("value" in descriptor) || !descriptor.enumerable) {
      return invalidReference(`${label} must contain enumerable data properties`);
    }
    record[key] = descriptor.value;
  }
  return record;
}

function parseConnection(value: unknown): ConnectionAlias {
  if (typeof value !== "string" || value.length === 0) {
    return invalidReference("connection alias must be a nonempty string");
  }
  return value as ConnectionAlias;
}

function parseEpoch(value: unknown): DaemonEpoch {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    return invalidReference("daemon epoch must be a nonnegative safe integer");
  }
  return value as DaemonEpoch;
}

function parseSessionId(value: unknown): SessionId {
  if (typeof value !== "string" || !/^\$\d+$/u.test(value)) {
    return invalidReference("session ID must use the session sigil");
  }
  return value as SessionId;
}

function parseWindowId(value: unknown): WindowId {
  if (typeof value !== "string" || !/^@\d+$/u.test(value)) {
    return invalidReference("window ID must use the window sigil");
  }
  return value as WindowId;
}

function parsePaneId(value: unknown): PaneId {
  if (typeof value !== "string" || !/^%\d+$/u.test(value)) {
    return invalidReference("pane ID must use the pane sigil");
  }
  return value as PaneId;
}

function parseWindowIndex(value: unknown): string {
  if (typeof value !== "string" || !/^(?:0|[1-9]\d*)$/u.test(value)) {
    return invalidReference("window index must be canonical unsigned decimal text");
  }
  const numeric = Number(value);
  if (!Number.isSafeInteger(numeric)) {
    return invalidReference("window index must fit in a safe integer");
  }
  return value;
}

function parseLogicalRef(value: unknown): LogicalRef {
  const record = readStrictDataRecord(
    value,
    ["connection", "epoch", "kind", "id"],
    "logical reference",
  );
  const connection = parseConnection(record.connection);
  const epoch = parseEpoch(record.epoch);

  switch (record.kind) {
    case "session":
      return Object.freeze({
        connection,
        epoch,
        kind: "session",
        id: parseSessionId(record.id),
      });
    case "window":
      return Object.freeze({
        connection,
        epoch,
        kind: "window",
        id: parseWindowId(record.id),
      });
    case "pane":
      return Object.freeze({
        connection,
        epoch,
        kind: "pane",
        id: parsePaneId(record.id),
      });
    default:
      return invalidReference("logical reference kind is invalid");
  }
}

function parseWinlinkRef(value: unknown): WinlinkRef {
  const record = readStrictDataRecord(
    value,
    ["connection", "epoch", "kind", "sessionId", "windowId", "windowIndex"],
    "winlink reference",
  );
  if (record.kind !== "winlink") {
    return invalidReference("winlink reference kind is invalid");
  }
  return Object.freeze({
    connection: parseConnection(record.connection),
    epoch: parseEpoch(record.epoch),
    kind: "winlink",
    sessionId: parseSessionId(record.sessionId),
    windowId: parseWindowId(record.windowId),
    windowIndex: parseWindowIndex(record.windowIndex),
  });
}

export function createLogicalRef<Kind extends TmuxIdKind>(
  input: LogicalRefInput<Kind>,
): LogicalRefForKind<Kind> {
  return parseLogicalRef(input) as LogicalRefForKind<Kind>;
}

export function encodeLogicalRef(ref: LogicalRef): SerializedLogicalRef {
  const parsed = parseLogicalRef(ref);
  return Object.freeze({
    connection: parsed.connection,
    epoch: parsed.epoch,
    kind: parsed.kind,
    id: parsed.id,
  });
}

export function decodeLogicalRef(value: unknown): LogicalRef {
  return parseLogicalRef(value);
}

export function logicalRefsEqual(left: LogicalRef, right: LogicalRef): boolean {
  const parsedLeft = parseLogicalRef(left);
  const parsedRight = parseLogicalRef(right);
  return (
    parsedLeft.connection === parsedRight.connection &&
    parsedLeft.epoch === parsedRight.epoch &&
    parsedLeft.kind === parsedRight.kind &&
    parsedLeft.id === parsedRight.id
  );
}

export function createWinlinkRef(input: WinlinkRefInput): WinlinkRef {
  const record = readStrictDataRecord(
    input,
    ["connection", "epoch", "sessionId", "windowId", "windowIndex"],
    "winlink reference",
  );
  return Object.freeze({
    connection: parseConnection(record.connection),
    epoch: parseEpoch(record.epoch),
    kind: "winlink",
    sessionId: parseSessionId(record.sessionId),
    windowId: parseWindowId(record.windowId),
    windowIndex: parseWindowIndex(record.windowIndex),
  });
}

export function winlinkRefsEqual(left: WinlinkRef, right: WinlinkRef): boolean {
  const parsedLeft = parseWinlinkRef(left);
  const parsedRight = parseWinlinkRef(right);
  return (
    parsedLeft.connection === parsedRight.connection &&
    parsedLeft.epoch === parsedRight.epoch &&
    parsedLeft.kind === parsedRight.kind &&
    parsedLeft.sessionId === parsedRight.sessionId &&
    parsedLeft.windowId === parsedRight.windowId &&
    parsedLeft.windowIndex === parsedRight.windowIndex
  );
}
