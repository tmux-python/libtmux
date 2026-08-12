export { Client } from "./client.js";
export { Pane } from "./pane.js";
export { Server, type ServerOptions } from "./server.js";
export { Session } from "./session.js";
export { Window } from "./window.js";

export {
  parseLegacyWhere,
  type PaneWhere,
  type RegexCriteriaData,
  type Selection,
  type SessionWhere,
  type WhereDocumentV1,
  type WhereOf,
  type WindowWhere,
} from "./selection.js";

export type {
  CaptureOptions,
  ChooseTreeOptions,
  HookScope,
  IfShellOptions,
  MenuEntry,
  MenuItem,
  MoveWindowOptions,
  NewSessionOptions,
  NewWindowOptions,
  OptionScope,
  PopupOptions,
  RespawnOptions,
  ResizeOptions,
  RunShellOptions,
  SendKeysOptions,
  ServerSnapshot,
  SplitOptions,
  WindowTarget,
} from "./types.js";

export {
  DeprecatedError,
  LibTmuxException,
  MultipleMatchesError,
  MultipleObjectsReturned,
  NoMatchError,
  ObjectDoesNotExist,
  QueryValidationError,
  TmuxCommandError,
} from "./exc.js";
