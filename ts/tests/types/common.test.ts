import type {
  CommandOptions,
  CommandOutcome,
  CommandResult,
  ConnectionAlias,
  DaemonEpoch,
  LogicalRef,
  DeliveryStatus,
  OperationStatus,
  TmuxLogger,
  TmuxLogContext,
  TmuxWarning,
  TmuxWarningSink,
  PaneId,
  PaneRef,
  SessionId,
  SessionRef,
  WindowId,
  WindowRef,
} from "../../src/common.js";
import type { DefaultOptionScope } from "../../src/constants.js";
import * as exception from "../../src/exc.js";
import {
  AdjustmentDirectionRequiresAdjustment,
  MultipleMatchesError,
  NoMatchError,
  QueryValidationError,
} from "../../src/exc.js";
import {
  OptionScope,
  DEFAULT_OPTION_SCOPE,
  HOOK_SCOPE_FLAG_MAP,
  OPTION_SCOPE_FLAG_MAP,
  PaneDirection,
  PANE_DIRECTION_FLAG_MAP,
  ResizeAdjustmentDirection,
  RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
  WindowDirection,
  WINDOW_DIRECTION_FLAG_MAP,
} from "../../src/constants.js";

import type { Equal, Expect } from "./assert.js";

declare const options: CommandOptions;
declare const result: CommandResult;
declare const logger: TmuxLogger;
declare const outcome: CommandOutcome;
declare const ref: LogicalRef;
declare const sessionRef: SessionRef;
declare const windowRef: WindowRef;
declare const paneRef: PaneRef;
declare const warning: TmuxWarning;
declare const warningSink: TmuxWarningSink;

void options.signal;
void options.stdin;
void result.cmd;
void result.stdout;
void result.stderr;
void result.returncode;
logger.debug("tmux command", { tmux_subcommand: "list-sessions" });
logger.info("tmux command");
logger.warn("tmux command");
logger.error("tmux command");
warningSink.warn(warning);
void outcome.delivery;
void outcome.result;
void outcome.status;
void ref.connection;
void ref.epoch;
void ref.id;
void ref.kind;
void warning.code;
void warning.message;
void sessionRef.id;
void windowRef.id;
void paneRef.id;

// @ts-expect-error Command results are readonly snapshots.
result.returncode = 1;
// @ts-expect-error Outcomes are readonly snapshots.
outcome.status = "failed";
// @ts-expect-error Warning payloads are readonly.
warning.code = "changed";
// @ts-expect-error Logical references are readonly.
sessionRef.kind = "window";
// @ts-expect-error Flag maps are readonly.
RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP[ResizeAdjustmentDirection.Up] = "-D";
// @ts-expect-error The sentinel is nominal rather than a plain object.
const plainDefaultScope: DefaultOptionScope = {};
void plainDefaultScope;

const exceptionCause = new Error("cause");
const noMatch = new NoMatchError({
  cause: exceptionCause,
  message: "No match",
  query: { pane_id: "%3" },
  subcommand: "list-panes",
});
const multipleMatches = new MultipleMatchesError({
  cause: exceptionCause,
  count: 2,
  message: "Multiple matches",
  query: { pane_id: "%3" },
  subcommand: "list-panes",
});
const invalidQuery = new QueryValidationError({
  cause: exceptionCause,
  code: "invalid-query",
  message: "Invalid query",
});

void noMatch.query;
void multipleMatches.count;
void invalidQuery.code;
type _NoPublicAdjustmentInstanceHook = Expect<
  Equal<
    Extract<keyof typeof AdjustmentDirectionRequiresAdjustment, typeof Symbol.hasInstance>,
    never
  >
>;
void OptionScope.Server;
void PaneDirection.Above;
void ResizeAdjustmentDirection.Up;
void WindowDirection.Before;
void DEFAULT_OPTION_SCOPE;
void RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP;
void WINDOW_DIRECTION_FLAG_MAP;
void PANE_DIRECTION_FLAG_MAP;
void OPTION_SCOPE_FLAG_MAP;
void HOOK_SCOPE_FLAG_MAP;

const allExceptions = [
  new exception.AdjustmentDirectionRequiresAdjustment({
    cause: exceptionCause,
    subcommand: "resize-pane",
  }),
  new exception.AmbiguousOption("ambiguous", { cause: exceptionCause, subcommand: "show-options" }),
  new exception.BadSessionName("reason", "session-name"),
  new exception.DeprecatedError({ deprecated: "old", replacement: "new", version: "0" }),
  new exception.InvalidOption("invalid", { cause: exceptionCause }),
  new exception.LibTmuxException("base", { cause: exceptionCause, subcommand: "list-sessions" }),
  new exception.MultipleActiveWindows(2),
  new exception.MultipleObjectsReturned({
    cause: exceptionCause,
    count: 2,
    message: "Multiple objects",
    query: { pane_id: "%3" },
    subcommand: "list-panes",
  }),
  new exception.NoActiveWindow(),
  new exception.NotInsideTmux("TMUX_PANE", { reason: "not a pane id" }),
  new exception.NoWindowsExist(),
  new exception.ObjectDoesNotExist({
    cause: exceptionCause,
    message: "No objects",
    query: { window_id: "@2" },
    subcommand: "list-windows",
  }),
  new exception.OptionError("option", { subcommand: "show-options" }),
  new exception.PaneAdjustmentDirectionRequiresAdjustment({
    cause: exceptionCause,
    subcommand: "resize-pane",
  }),
  new exception.PaneError(),
  new exception.PaneNotFound("%3"),
  new exception.RequiresDigitOrPercentage(),
  new exception.TmuxCommandNotFound("missing", { cause: exceptionCause }),
  new exception.TmuxObjectDoesNotExist({
    list_cmd: "list-panes",
    list_extra_args: ["-t", "%3"],
    obj_id: "%3",
    obj_key: "pane_id",
  }),
  new exception.TmuxSessionExists("exists", { subcommand: "new-session" }),
  new exception.UnknownColorOption(),
  new exception.UnknownOption("unknown", { cause: exceptionCause }),
  new exception.VariableUnpackingError("value"),
  new exception.VersionTooLow(),
  new exception.WaitTimeout(),
  new exception.WindowAdjustmentDirectionRequiresAdjustment({
    cause: exceptionCause,
    subcommand: "resize-window",
  }),
  new exception.WindowError(),
];
void allExceptions;

type _DeliveryStatus = Expect<
  Equal<DeliveryStatus, "not_started" | "written" | "replied" | "indeterminate">
>;
type _OperationStatus = Expect<
  Equal<OperationStatus, "complete" | "failed" | "skipped" | "unknown">
>;
type _CommandOutcomeKeys = Expect<Equal<keyof CommandOutcome, "delivery" | "result" | "status">>;
type _CommandOptions = Expect<
  Equal<CommandOptions, { readonly signal?: AbortSignal; readonly stdin?: string | Uint8Array }>
>;
type _CommandResult = Expect<
  Equal<
    CommandResult,
    {
      readonly cmd: readonly string[];
      readonly returncode: number;
      readonly stderr: readonly string[];
      readonly stdout: readonly string[];
    }
  >
>;
type _CommandOutcome = Expect<
  Equal<
    CommandOutcome,
    {
      readonly delivery: DeliveryStatus;
      readonly result?: CommandResult;
      readonly status: OperationStatus;
    }
  >
>;
type _Warning = Expect<Equal<TmuxWarning, { readonly code: string; readonly message: string }>>;
type _WarningSink = Expect<Equal<TmuxWarningSink["warn"], (warning: TmuxWarning) => void>>;
type _LogContext = Expect<
  Equal<TmuxLogContext, Readonly<Record<string, boolean | number | string | undefined>>>
>;
type _LoggerDebug = Expect<
  Equal<TmuxLogger["debug"], (message: string, context?: TmuxLogContext) => void>
>;
type _LoggerInfo = Expect<
  Equal<TmuxLogger["info"], (message: string, context?: TmuxLogContext) => void>
>;
type _LoggerWarn = Expect<
  Equal<TmuxLogger["warn"], (message: string, context?: TmuxLogContext) => void>
>;
type _LoggerError = Expect<
  Equal<TmuxLogger["error"], (message: string, context?: TmuxLogContext) => void>
>;
type _SessionRef = Expect<
  Equal<
    SessionRef,
    {
      readonly connection: ConnectionAlias;
      readonly epoch: DaemonEpoch;
      readonly id: SessionId;
      readonly kind: "session";
    }
  >
>;
type _WindowRef = Expect<
  Equal<
    WindowRef,
    {
      readonly connection: ConnectionAlias;
      readonly epoch: DaemonEpoch;
      readonly id: WindowId;
      readonly kind: "window";
    }
  >
>;
type _PaneRef = Expect<
  Equal<
    PaneRef,
    {
      readonly connection: ConnectionAlias;
      readonly epoch: DaemonEpoch;
      readonly id: PaneId;
      readonly kind: "pane";
    }
  >
>;
type _ResizeFlags = Expect<
  Equal<
    typeof RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP,
    Readonly<Record<ResizeAdjustmentDirection, string>>
  >
>;
type _WindowFlags = Expect<
  Equal<typeof WINDOW_DIRECTION_FLAG_MAP, Readonly<Record<WindowDirection, string>>>
>;
type _PaneFlags = Expect<
  Equal<typeof PANE_DIRECTION_FLAG_MAP, Readonly<Record<PaneDirection, readonly string[]>>>
>;
type _OptionFlags = Expect<
  Equal<typeof OPTION_SCOPE_FLAG_MAP, Readonly<Record<OptionScope, string>>>
>;
type _HookFlags = Expect<Equal<typeof HOOK_SCOPE_FLAG_MAP, Readonly<Record<OptionScope, string>>>>;

export type {
  _CommandOutcomeKeys,
  _DeliveryStatus,
  _NoPublicAdjustmentInstanceHook,
  _OperationStatus,
  _PaneFlags,
  _PaneRef,
  _ResizeFlags,
  _SessionRef,
  _WindowFlags,
  _WindowRef,
  _OptionFlags,
  _HookFlags,
};
