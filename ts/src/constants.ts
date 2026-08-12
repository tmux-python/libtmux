export const ResizeAdjustmentDirection = {
  Up: "UP",
  Down: "DOWN",
  Left: "LEFT",
  Right: "RIGHT",
} as const;
export type ResizeAdjustmentDirection =
  (typeof ResizeAdjustmentDirection)[keyof typeof ResizeAdjustmentDirection];

export const RESIZE_ADJUSTMENT_DIRECTION_FLAG_MAP: Readonly<
  Record<ResizeAdjustmentDirection, string>
> = {
  [ResizeAdjustmentDirection.Up]: "-U",
  [ResizeAdjustmentDirection.Down]: "-D",
  [ResizeAdjustmentDirection.Left]: "-L",
  [ResizeAdjustmentDirection.Right]: "-R",
} as const;

export const WindowDirection = {
  Before: "BEFORE",
  After: "AFTER",
} as const;
export type WindowDirection = (typeof WindowDirection)[keyof typeof WindowDirection];

export const WINDOW_DIRECTION_FLAG_MAP: Readonly<Record<WindowDirection, string>> = {
  [WindowDirection.Before]: "-b",
  [WindowDirection.After]: "-a",
} as const;

export const PaneDirection = {
  Above: "ABOVE",
  Below: "BELOW",
  Right: "RIGHT",
  Left: "LEFT",
} as const;
export type PaneDirection = (typeof PaneDirection)[keyof typeof PaneDirection];

export const PANE_DIRECTION_FLAG_MAP: Readonly<Record<PaneDirection, readonly string[]>> = {
  [PaneDirection.Above]: ["-v", "-b"],
  [PaneDirection.Below]: ["-v"],
  [PaneDirection.Right]: ["-h"],
  [PaneDirection.Left]: ["-h", "-b"],
} as const;

declare const defaultOptionScopeBrand: unique symbol;
export type DefaultOptionScope = { readonly [defaultOptionScopeBrand]: "default-option-scope" };
export const DEFAULT_OPTION_SCOPE: DefaultOptionScope = {} as DefaultOptionScope;

export const OptionScope = {
  Server: "SERVER",
  Session: "SESSION",
  Window: "WINDOW",
  Pane: "PANE",
} as const;
export type OptionScope = (typeof OptionScope)[keyof typeof OptionScope];

export const OPTION_SCOPE_FLAG_MAP: Readonly<Record<OptionScope, string>> = {
  [OptionScope.Server]: "-s",
  [OptionScope.Session]: "",
  [OptionScope.Window]: "-w",
  [OptionScope.Pane]: "-p",
} as const;

export const HOOK_SCOPE_FLAG_MAP: Readonly<Record<OptionScope, string>> = {
  [OptionScope.Server]: "-g",
  [OptionScope.Session]: "",
  [OptionScope.Window]: "-w",
  [OptionScope.Pane]: "-p",
} as const;
