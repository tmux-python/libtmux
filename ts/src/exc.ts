import { types as nodeTypes } from "node:util";

export type Query = Readonly<Record<string, unknown>>;

interface ExceptionOptions {
  readonly cause?: unknown;
  readonly subcommand?: string;
}

interface ObjectDoesNotExistOptions extends ExceptionOptions {
  readonly message?: string;
  readonly query?: Query;
}

interface MultipleObjectsReturnedOptions extends ObjectDoesNotExistOptions {
  readonly count?: number;
}

const maximumQueryFormatDepth = 256;
const maximumQueryDepthValue = JSON.stringify("[query value exceeds maximum depth]");

function sortedDataEntries(value: object): readonly (readonly [string, unknown])[] | null {
  try {
    if (nodeTypes.isProxy(value) || Array.isArray(value)) return null;
    const prototype = Object.getPrototypeOf(value) as object | null;
    if (prototype !== Object.prototype && prototype !== null) return null;
    const entries: Array<readonly [string, unknown]> = [];
    for (const key of Reflect.ownKeys(value)) {
      if (typeof key !== "string") return null;
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
        return null;
      }
      entries.push([key, descriptor.value]);
    }
    return entries.sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0));
  } catch {
    return null;
  }
}

function dataArrayValues(value: object): readonly unknown[] | null {
  try {
    if (nodeTypes.isProxy(value) || !Array.isArray(value)) return null;
    const lengthDescriptor = Object.getOwnPropertyDescriptor(value, "length");
    if (
      Object.getPrototypeOf(value) !== Array.prototype ||
      lengthDescriptor === undefined ||
      !("value" in lengthDescriptor) ||
      lengthDescriptor.enumerable ||
      typeof lengthDescriptor.value !== "number" ||
      !Number.isSafeInteger(lengthDescriptor.value) ||
      lengthDescriptor.value < 0 ||
      Reflect.ownKeys(value).length !== lengthDescriptor.value + 1
    ) {
      return null;
    }
    const values: unknown[] = [];
    for (let index = 0; index < lengthDescriptor.value; index += 1) {
      const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
      if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
        return null;
      }
      values.push(descriptor.value);
    }
    return values;
  } catch {
    return null;
  }
}

function formatDataValue(value: unknown, active: Set<object>, depth = 0): string {
  if (value === null) return "null";
  if (typeof value === "string") return JSON.stringify(value);
  if (typeof value === "boolean") return String(value);
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
  if ((typeof value !== "object" && typeof value !== "function") || value === null) {
    return "null";
  }
  if (depth >= maximumQueryFormatDepth) return maximumQueryDepthValue;
  if (active.has(value)) return JSON.stringify("[circular query value]");
  active.add(value);
  try {
    const array = dataArrayValues(value);
    if (array !== null) {
      return `[${array.map((entry) => formatDataValue(entry, active, depth + 1)).join(",")}]`;
    }
    const entries = sortedDataEntries(value);
    if (entries === null) return JSON.stringify("[invalid query value]");
    return `{${entries
      .map(([key, entry]) => `${JSON.stringify(key)}:${formatDataValue(entry, active, depth + 1)}`)
      .join(",")}}`;
  } finally {
    active.delete(value);
  }
}

function formatQuery(query: Query): string {
  const entries = sortedDataEntries(query);
  if (entries === null) return "";
  return entries
    .map(([key, value]) =>
      typeof value === "string"
        ? `${key}='${value}'`
        : `${key}=${formatDataValue(value, new Set())}`,
    )
    .join(", ");
}

export class LibTmuxException extends Error {
  readonly subcommand: string | undefined;

  constructor(message = "", options: ExceptionOptions = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = new.target.name;
    this.subcommand = options.subcommand;
  }

  override toString(): string {
    return this.subcommand === undefined
      ? `${this.name}: ${this.message}`
      : `${this.subcommand}: ${this.message}`;
  }
}

export class DeprecatedError extends LibTmuxException {
  constructor({
    deprecated,
    replacement,
    version,
  }: {
    deprecated: string;
    replacement: string;
    version: string;
  }) {
    super(
      `${deprecated} was deprecated in ${version} and has been removed. Use ${replacement} instead.`,
    );
  }
}

export class TmuxSessionExists extends LibTmuxException {}
export class TmuxCommandNotFound extends LibTmuxException {}

export class NotInsideTmux extends LibTmuxException {
  constructor(variable?: string, options: { readonly reason?: string } = {}) {
    super(
      variable === undefined
        ? "Not inside a tmux pane"
        : `Not inside a tmux pane: $${variable} is ${options.reason ?? "unset or empty"}`,
    );
  }
}

export class ObjectDoesNotExist extends LibTmuxException {
  readonly query: Query | undefined;

  constructor(options: ObjectDoesNotExistOptions = {}) {
    const formattedQuery = options.query === undefined ? "" : formatQuery(options.query);
    const message =
      options.message ??
      (formattedQuery === "" ? "No objects found" : `No objects found: ${formattedQuery}`);
    super(message, options);
    this.query = options.query;
  }
}

export class MultipleObjectsReturned extends LibTmuxException {
  readonly count: number | undefined;
  readonly query: Query | undefined;

  constructor(options: MultipleObjectsReturnedOptions = {}) {
    const parts = ["Multiple objects returned"];
    if (options.count !== undefined) parts.push(`(${options.count})`);
    const formattedQuery = options.query === undefined ? "" : formatQuery(options.query);
    const message =
      options.message ?? `${parts.join(" ")}${formattedQuery === "" ? "" : `: ${formattedQuery}`}`;
    super(message, options);
    this.count = options.count;
    this.query = options.query;
  }
}

export class TmuxObjectDoesNotExist extends ObjectDoesNotExist {
  constructor(
    options: {
      readonly list_cmd?: string;
      readonly list_extra_args?: readonly string[];
      readonly obj_id?: string;
      readonly obj_key?: string;
    } = {},
  ) {
    const { list_cmd, list_extra_args, obj_id, obj_key } = options;
    super({
      message:
        list_cmd === undefined ||
        list_extra_args === undefined ||
        obj_id === undefined ||
        obj_key === undefined
          ? "Could not find object"
          : `Could not find ${obj_key}=${obj_id} for ${list_cmd} (${list_extra_args.map((value) => `'${value}'`).join(", ")})`,
    });
  }
}

export class VersionTooLow extends LibTmuxException {}

export class BadSessionName extends LibTmuxException {
  constructor(reason: string, session_name?: string) {
    super(
      `Bad session name: ${reason}${session_name === undefined ? "" : ` (session name: ${session_name})`}`,
    );
  }
}

export class OptionError extends LibTmuxException {}
export class UnknownOption extends OptionError {}
export class UnknownColorOption extends UnknownOption {
  constructor() {
    super("Server.colors must equal 88 or 256");
  }
}
export class InvalidOption extends OptionError {}
export class AmbiguousOption extends OptionError {}
export class WaitTimeout extends LibTmuxException {}

export class VariableUnpackingError extends LibTmuxException {
  constructor(variable?: unknown) {
    const value =
      variable === undefined
        ? "None"
        : typeof variable === "object"
          ? Object.prototype.toString.call(variable)
          : String(variable as string | number | bigint | boolean | symbol);
    super(`Unexpected variable: ${value}`);
  }
}

export class PaneError extends LibTmuxException {}
export class PaneNotFound extends PaneError {
  constructor(pane_id?: string) {
    super(pane_id === undefined ? "Pane not found" : `Pane not found: ${pane_id}`);
  }
}

export class WindowError extends LibTmuxException {}
export class MultipleActiveWindows extends WindowError {
  constructor(count: number) {
    super(`Multiple active windows: ${count} found`);
  }
}
export class NoActiveWindow extends WindowError {
  constructor() {
    super("No active windows found");
  }
}
export class NoWindowsExist extends WindowError {
  constructor() {
    super("No windows exist for object");
  }
}

const adjustmentDirectionInstances = new WeakSet<object>();

export class AdjustmentDirectionRequiresAdjustment extends LibTmuxException {
  constructor(options: ExceptionOptions = {}) {
    super("adjustment_direction requires adjustment", options);
    adjustmentDirectionInstances.add(this);
  }
}
export class WindowAdjustmentDirectionRequiresAdjustment extends WindowError {
  constructor(options: ExceptionOptions = {}) {
    super("adjustment_direction requires adjustment", options);
    adjustmentDirectionInstances.add(this);
  }
}
export class PaneAdjustmentDirectionRequiresAdjustment extends WindowError {
  constructor(options: ExceptionOptions = {}) {
    super("adjustment_direction requires adjustment", options);
    adjustmentDirectionInstances.add(this);
  }
}

Object.defineProperty(AdjustmentDirectionRequiresAdjustment, Symbol.hasInstance, {
  value(this: Function, value: unknown): boolean {
    if (this === AdjustmentDirectionRequiresAdjustment) {
      return typeof value === "object" && value !== null && adjustmentDirectionInstances.has(value);
    }
    return Function.prototype[Symbol.hasInstance].call(this, value);
  },
});
export class RequiresDigitOrPercentage extends LibTmuxException {
  constructor() {
    super("Requires digit (int or str digit) or a percentage.");
  }
}

export class NoMatchError extends ObjectDoesNotExist {}
export class MultipleMatchesError extends MultipleObjectsReturned {}

export type QueryValidationErrorCode = "invalid-id" | "invalid-query";

export class QueryValidationError extends LibTmuxException {
  readonly code: QueryValidationErrorCode;

  constructor({
    cause,
    code,
    message,
  }: {
    readonly cause?: unknown;
    readonly code: QueryValidationErrorCode;
    readonly message: string;
  }) {
    super(message, { cause });
    this.code = code;
  }
}
