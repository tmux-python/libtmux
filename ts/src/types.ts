import type { Client } from "./client.js";
import type { Pane } from "./pane.js";
import type { Selection } from "./selection.js";
import type { Session } from "./session.js";
import type { Window } from "./window.js";

/**
 * Option shapes for the public operations.
 *
 * These live beside the classes rather than beside the internal operations that
 * consume them, so emitted public declarations never name an internal module.
 * The dependency points inward: internals import these, not the reverse.
 */

/** An immutable view of the server at one instant. */
export interface ServerSnapshot {
  readonly clients: Selection<Client>;
  readonly panes: Selection<Pane>;
  readonly sessions: Selection<Session>;
  readonly windows: Selection<Window>;
}

export interface NewSessionOptions {
  readonly name?: string;
  readonly startDirectory?: string;
  readonly windowName?: string;
}

export interface NewWindowOptions {
  readonly name?: string;
  readonly startDirectory?: string;
}

export interface SplitOptions {
  readonly startDirectory?: string;
  readonly vertical?: boolean;
}

export interface SendKeysOptions {
  /** Append Enter after the keys. Defaults to true. */
  readonly enter?: boolean;
  /** Send the string literally instead of letting tmux resolve key names. */
  readonly literal?: boolean;
}

export interface CaptureOptions {
  /** Last line to capture; negative counts back from the visible bottom. */
  readonly end?: number;
  /** Join wrapped lines, matching tmux's `-J`. */
  readonly joinWrapped?: boolean;
  /** First line to capture; negative reaches into scrollback history. */
  readonly start?: number;
}

export interface MoveWindowOptions {
  /** Destination index; tmux picks the next free one when omitted. */
  readonly index?: number;
  /** Destination session; the window stays in its own session when omitted. */
  readonly session?: string;
}

export interface ResizeOptions {
  readonly height?: number;
  readonly width?: number;
}

export interface RunShellOptions {
  /** Pane the command's `#{pane_*}` formats resolve against. */
  readonly target?: string | null;
}

export interface IfShellOptions {
  /** Command to run when the condition fails. */
  readonly otherwise?: string;
  /** Treat the condition as a tmux format rather than a shell command. */
  readonly format?: boolean;
  readonly target?: string | null;
}

export interface RespawnOptions {
  /** Replace a pane that is still running rather than only a dead one. */
  readonly kill?: boolean;
  readonly startDirectory?: string;
}

export interface PopupOptions {
  readonly directory?: string;
  /** Close the popup when its command exits. */
  readonly closeOnExit?: boolean;
  readonly height?: string;
  readonly width?: string;
}

export interface MenuEntry {
  /** Single-character shortcut tmux binds to this entry. */
  readonly key: string;
  readonly command: string;
  readonly name: string;
}

/**
 * A menu entry, or a horizontal rule.
 *
 * tmux spells a separator as one empty argument rather than a name/key/command
 * triple, so modelling it as a distinct value keeps callers from fabricating
 * empty fields that tmux would reject.
 */
export type MenuItem = MenuEntry | "separator";

export interface ChooseTreeOptions {
  readonly sessionsOnly?: boolean;
  readonly windowsOnly?: boolean;
}

/** The tmux option scope a lookup is addressed to. */
export type OptionScope = "pane" | "server" | "session" | "window";

/** Hooks live at server or session scope. */
export type HookScope = "server" | "session";

/**
 * A relative direction, or any window target tmux accepts.
 *
 * The intersection keeps the three literals in autocomplete instead of letting
 * the bare `string` swallow them.
 */
export type WindowTarget = "last" | "next" | "previous" | (string & Record<never, never>);

/**
 * tmux control-mode notifications, parsed into a discriminated union.
 *
 * Event names are tmux's own, verbatim and without the leading `%`, so they
 * grep against tmux(1) and the control-mode protocol. Field names are this
 * package's, so they read like the rest of the API. That is the same line
 * `format` draws: tmux's vocabulary for tmux's data, ours for our shape.
 */

/** A pane produced output. */
export interface TmuxOutputEvent {
  readonly data: string;
  readonly kind: "output";
  readonly paneId: string;
}

/**
 * A pane produced output on a connection that asked for age reporting.
 *
 * `age` is milliseconds between tmux buffering the data and writing it, which
 * is how a consumer notices it is falling behind.
 */
export interface TmuxExtendedOutputEvent {
  readonly age: number;
  readonly data: string;
  readonly kind: "extended-output";
  readonly paneId: string;
}

/** A window was added, closed, or linked into or out of a session. */
export interface TmuxWindowLifecycleEvent {
  readonly kind: "window-add" | "window-close" | "unlinked-window-add" | "unlinked-window-close";
  readonly windowId: string;
}

/** A window was renamed. */
export interface TmuxWindowRenamedEvent {
  readonly kind: "window-renamed" | "unlinked-window-renamed";
  readonly name: string;
  readonly windowId: string;
}

/** The active pane of a window changed. */
export interface TmuxWindowPaneChangedEvent {
  readonly kind: "window-pane-changed";
  readonly paneId: string;
  readonly windowId: string;
}

/** A window's layout changed. */
export interface TmuxLayoutChangeEvent {
  readonly flags: string;
  readonly kind: "layout-change";
  readonly layout: string;
  readonly visibleLayout: string;
  readonly windowId: string;
}

/** The attached session changed, or a session was renamed. */
export interface TmuxSessionEvent {
  readonly kind: "session-changed" | "session-renamed";
  readonly name: string;
  readonly sessionId: string;
}

/** The set of sessions changed. Carries no payload; re-read the server. */
export interface TmuxSessionsChangedEvent {
  readonly kind: "sessions-changed";
}

/** A session's active window changed. */
export interface TmuxSessionWindowChangedEvent {
  readonly kind: "session-window-changed";
  readonly sessionId: string;
  readonly windowId: string;
}

/** Another client switched sessions. */
export interface TmuxClientSessionChangedEvent {
  readonly client: string;
  readonly kind: "client-session-changed";
  readonly name: string;
  readonly sessionId: string;
}

/** Another client detached. */
export interface TmuxClientDetachedEvent {
  readonly client: string;
  readonly kind: "client-detached";
}

/** A pane entered or left a mode such as copy mode. */
export interface TmuxPaneModeChangedEvent {
  readonly kind: "pane-mode-changed";
  readonly paneId: string;
}

/** A paste buffer was written or deleted. */
export interface TmuxPasteBufferEvent {
  readonly buffer: string;
  readonly kind: "paste-buffer-changed" | "paste-buffer-deleted";
}

/** tmux paused or resumed output for a pane that fell behind. */
export interface TmuxPaneFlowEvent {
  readonly kind: "continue" | "pause";
  readonly paneId: string;
}

/** tmux reported a message, or an error in its configuration. */
export interface TmuxMessageEvent {
  readonly kind: "config-error" | "message";
  readonly message: string;
}

/** The control-mode connection is ending. */
export interface TmuxExitEvent {
  readonly kind: "exit";
  readonly reason: string | undefined;
}

/**
 * A notification this version of the package does not model.
 *
 * tmux adds notifications between releases. Rather than drop them, they arrive
 * with their name and raw arguments so a consumer can handle one this package
 * has not caught up with yet.
 */
export interface TmuxUnknownEvent {
  readonly args: readonly string[];
  readonly kind: "unknown";
  readonly name: string;
}

export type TmuxEvent =
  | TmuxClientDetachedEvent
  | TmuxClientSessionChangedEvent
  | TmuxExitEvent
  | TmuxExtendedOutputEvent
  | TmuxLayoutChangeEvent
  | TmuxMessageEvent
  | TmuxOutputEvent
  | TmuxPaneFlowEvent
  | TmuxPaneModeChangedEvent
  | TmuxPasteBufferEvent
  | TmuxSessionEvent
  | TmuxSessionWindowChangedEvent
  | TmuxSessionsChangedEvent
  | TmuxUnknownEvent
  | TmuxWindowLifecycleEvent
  | TmuxWindowPaneChangedEvent
  | TmuxWindowRenamedEvent;

/**
 * The part of `AbortSignal` this package uses.
 *
 * Typed structurally rather than as the global, because `AbortSignal` comes
 * from the DOM or Node type libraries and naming it would make these public
 * declarations require one. A real `AbortSignal` satisfies it.
 */
export interface AbortLike {
  addEventListener(type: "abort", listener: () => void, options?: { once?: boolean }): void;
  readonly aborted: boolean;
  removeEventListener(type: "abort", listener: () => void): void;
}

/** Options for {@link Server.watch}. */
export interface WatchOptions {
  /**
   * How many events to hold for a consumer that has fallen behind.
   *
   * On overflow the oldest event is dropped and {@link TmuxEventStream.dropped}
   * counts it. Buffering without a bound would let a slow consumer grow the
   * heap until the process dies, which is worse than losing an event.
   */
  readonly bufferSize?: number;
  /** Abort the connection when this signal fires. */
  readonly signal?: AbortLike;
  /** Session to attach to. Defaults to whichever tmux considers most recent. */
  readonly target?: string;
}

/**
 * A live stream of tmux control-mode events.
 *
 * Async iterable and async disposable, so `await using` ends the connection on
 * scope exit even when the loop throws. The events are consumed, not replayed,
 * so a stream is iterated once.
 */
export interface TmuxEventStream extends AsyncIterable<TmuxEvent>, AsyncDisposable {
  /** End the connection. Safe to call more than once. */
  close(): Promise<void>;
  /** Events discarded because the consumer fell behind. */
  readonly dropped: number;
  [Symbol.asyncDispose](): Promise<void>;
}
