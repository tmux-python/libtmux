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
