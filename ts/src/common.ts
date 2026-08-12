declare const tmuxIdBrand: unique symbol;
declare const connectionAliasBrand: unique symbol;
declare const daemonEpochBrand: unique symbol;

export type TmuxIdKind = "session" | "window" | "pane";

export type TmuxId<Kind extends TmuxIdKind> = string & {
  readonly [tmuxIdBrand]: Kind;
};

export type SessionId = TmuxId<"session">;
export type WindowId = TmuxId<"window">;
export type PaneId = TmuxId<"pane">;
export type TmuxIdInput<Kind extends TmuxIdKind> = string & {
  readonly [tmuxIdBrand]?: Kind;
};
export type SessionIdInput = TmuxIdInput<"session">;
export type WindowIdInput = TmuxIdInput<"window">;
export type PaneIdInput = TmuxIdInput<"pane">;

export type ConnectionAlias = string & { readonly [connectionAliasBrand]: "connection" };
export type DaemonEpoch = number & { readonly [daemonEpochBrand]: "daemon" };

export interface CommandOptions {
  readonly signal?: AbortSignal;
  readonly stdin?: string | Uint8Array;
}

export interface CommandResult {
  readonly cmd: readonly string[];
  readonly returncode: number;
  readonly stderr: readonly string[];
  readonly stdout: readonly string[];
}

export type DeliveryStatus = "not_started" | "written" | "replied" | "indeterminate";
export type OperationStatus = "complete" | "failed" | "skipped" | "unknown";

export interface CommandOutcome {
  readonly delivery: DeliveryStatus;
  readonly result?: CommandResult;
  readonly status: OperationStatus;
}

export type TmuxLogContext = Readonly<Record<string, boolean | number | string | undefined>>;

export interface TmuxLogger {
  debug(message: string, context?: TmuxLogContext): void;
  error(message: string, context?: TmuxLogContext): void;
  info(message: string, context?: TmuxLogContext): void;
  warn(message: string, context?: TmuxLogContext): void;
}

export interface TmuxWarning {
  readonly code: string;
  readonly message: string;
}

export interface TmuxWarningSink {
  warn(warning: TmuxWarning): void;
}

interface LogicalRefBase<Kind extends TmuxIdKind, Id extends TmuxId<Kind>> {
  readonly connection: ConnectionAlias;
  readonly epoch: DaemonEpoch;
  readonly id: Id;
  readonly kind: Kind;
}

export type SessionRef = LogicalRefBase<"session", SessionId>;
export type WindowRef = LogicalRefBase<"window", WindowId>;
export type PaneRef = LogicalRefBase<"pane", PaneId>;
export type LogicalRef = SessionRef | WindowRef | PaneRef;
