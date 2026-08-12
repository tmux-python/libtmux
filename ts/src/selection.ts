import type { ModelKindOf } from "./_internal/runtime/model_kind.js";
import { parseLegacyWhere as lowerLegacyWhere } from "./_internal/selection/legacy.js";

type StringFilterFields = {
  readonly contains?: string;
  readonly endsWith?: string;
  readonly equals?: string | null;
  readonly in?: readonly string[];
  readonly mode?: "insensitive";
  readonly notIn?: readonly string[];
  readonly regex?: RegexCriteriaData;
  readonly startsWith?: string;
};

type StringFilter = StringFilterFields &
  (
    | { readonly contains: string }
    | { readonly endsWith: string }
    | { readonly equals: string | null }
    | { readonly in: readonly string[] }
    | { readonly notIn: readonly string[] }
    | { readonly regex: RegexCriteriaData }
    | { readonly startsWith: string }
  );

type ScalarCriteria = string | null | StringFilter;

type ManyRelation<Where> =
  | { readonly every?: Where; readonly none?: Where; readonly some: Where }
  | { readonly every: Where; readonly none?: Where; readonly some?: Where }
  | { readonly every?: Where; readonly none: Where; readonly some?: Where };

type OneRelation<Where> =
  | { readonly is: Where | null; readonly isNot?: Where | null }
  | { readonly is?: Where | null; readonly isNot: Where | null };

export interface RegexCriteriaData {
  readonly flags: "" | "m" | "s" | "ms";
  readonly pattern: string;
}

// <libtmux-generated-where-types>
export interface SessionWhere {
  readonly AND?: readonly SessionWhere[];
  readonly OR?: readonly SessionWhere[];
  readonly NOT?: readonly SessionWhere[];
  readonly activeWindowIndex?: ScalarCriteria;
  readonly configFiles?: ScalarCriteria;
  readonly lastWindowIndex?: ScalarCriteria;
  readonly line?: ScalarCriteria;
  readonly name?: ScalarCriteria;
  readonly nextSessionId?: ScalarCriteria;
  readonly pid?: ScalarCriteria;
  readonly sessionActivity?: ScalarCriteria;
  readonly sessionAlerts?: ScalarCriteria;
  readonly sessionAttached?: ScalarCriteria;
  readonly sessionAttachedList?: ScalarCriteria;
  readonly sessionCreated?: ScalarCriteria;
  readonly sessionFormat?: ScalarCriteria;
  readonly sessionGroup?: ScalarCriteria;
  readonly sessionGroupAttached?: ScalarCriteria;
  readonly sessionGroupAttachedList?: ScalarCriteria;
  readonly sessionGroupList?: ScalarCriteria;
  readonly sessionGroupManyAttached?: ScalarCriteria;
  readonly sessionGroupSize?: ScalarCriteria;
  readonly sessionGrouped?: ScalarCriteria;
  readonly sessionId?: ScalarCriteria;
  readonly sessionLastAttached?: ScalarCriteria;
  readonly sessionManyAttached?: ScalarCriteria;
  readonly sessionMarked?: ScalarCriteria;
  readonly sessionPath?: ScalarCriteria;
  readonly sessionStack?: ScalarCriteria;
  readonly sessionWindows?: ScalarCriteria;
  readonly socketPath?: ScalarCriteria;
  readonly startTime?: ScalarCriteria;
  readonly uid?: ScalarCriteria;
  readonly user?: ScalarCriteria;
  readonly version?: ScalarCriteria;
  readonly windows?: ManyRelation<WindowWhere>;
  readonly panes?: ManyRelation<PaneWhere>;
  readonly activeWindow?: OneRelation<WindowWhere>;
  readonly activePane?: OneRelation<PaneWhere>;
}

export interface WindowWhere {
  readonly AND?: readonly WindowWhere[];
  readonly OR?: readonly WindowWhere[];
  readonly NOT?: readonly WindowWhere[];
  readonly configFiles?: ScalarCriteria;
  readonly line?: ScalarCriteria;
  readonly name?: ScalarCriteria;
  readonly nextSessionId?: ScalarCriteria;
  readonly pid?: ScalarCriteria;
  readonly socketPath?: ScalarCriteria;
  readonly startTime?: ScalarCriteria;
  readonly uid?: ScalarCriteria;
  readonly user?: ScalarCriteria;
  readonly version?: ScalarCriteria;
  readonly windowActive?: ScalarCriteria;
  readonly windowActiveClients?: ScalarCriteria;
  readonly windowActiveClientsList?: ScalarCriteria;
  readonly windowActiveSessions?: ScalarCriteria;
  readonly windowActiveSessionsList?: ScalarCriteria;
  readonly windowActivity?: ScalarCriteria;
  readonly windowActivityFlag?: ScalarCriteria;
  readonly windowBellFlag?: ScalarCriteria;
  readonly windowBigger?: ScalarCriteria;
  readonly windowCellHeight?: ScalarCriteria;
  readonly windowCellWidth?: ScalarCriteria;
  readonly windowEndFlag?: ScalarCriteria;
  readonly windowFlags?: ScalarCriteria;
  readonly windowFormat?: ScalarCriteria;
  readonly windowHeight?: ScalarCriteria;
  readonly windowId?: ScalarCriteria;
  readonly windowIndex?: ScalarCriteria;
  readonly windowLastFlag?: ScalarCriteria;
  readonly windowLayout?: ScalarCriteria;
  readonly windowLinked?: ScalarCriteria;
  readonly windowLinkedSessions?: ScalarCriteria;
  readonly windowLinkedSessionsList?: ScalarCriteria;
  readonly windowMarkedFlag?: ScalarCriteria;
  readonly windowOffsetX?: ScalarCriteria;
  readonly windowOffsetY?: ScalarCriteria;
  readonly windowPanes?: ScalarCriteria;
  readonly windowRawFlags?: ScalarCriteria;
  readonly windowSilenceFlag?: ScalarCriteria;
  readonly windowStackIndex?: ScalarCriteria;
  readonly windowStartFlag?: ScalarCriteria;
  readonly windowVisibleLayout?: ScalarCriteria;
  readonly windowWidth?: ScalarCriteria;
  readonly windowZoomedFlag?: ScalarCriteria;
  readonly session?: OneRelation<SessionWhere>;
  readonly linkedSessions?: ManyRelation<SessionWhere>;
  readonly panes?: ManyRelation<PaneWhere>;
  readonly activePane?: OneRelation<PaneWhere>;
}

export interface PaneWhere {
  readonly AND?: readonly PaneWhere[];
  readonly OR?: readonly PaneWhere[];
  readonly NOT?: readonly PaneWhere[];
  readonly alternateSavedX?: ScalarCriteria;
  readonly alternateSavedY?: ScalarCriteria;
  readonly bracketPasteFlag?: ScalarCriteria;
  readonly configFiles?: ScalarCriteria;
  readonly cursorCharacter?: ScalarCriteria;
  readonly cursorFlag?: ScalarCriteria;
  readonly cursorX?: ScalarCriteria;
  readonly cursorY?: ScalarCriteria;
  readonly historyBytes?: ScalarCriteria;
  readonly historyLimit?: ScalarCriteria;
  readonly historySize?: ScalarCriteria;
  readonly insertFlag?: ScalarCriteria;
  readonly keypadCursorFlag?: ScalarCriteria;
  readonly keypadFlag?: ScalarCriteria;
  readonly line?: ScalarCriteria;
  readonly mouseAllFlag?: ScalarCriteria;
  readonly mouseAnyFlag?: ScalarCriteria;
  readonly mouseButtonFlag?: ScalarCriteria;
  readonly mouseSgrFlag?: ScalarCriteria;
  readonly mouseStandardFlag?: ScalarCriteria;
  readonly nextSessionId?: ScalarCriteria;
  readonly originFlag?: ScalarCriteria;
  readonly paneActive?: ScalarCriteria;
  readonly paneAtBottom?: ScalarCriteria;
  readonly paneAtLeft?: ScalarCriteria;
  readonly paneAtRight?: ScalarCriteria;
  readonly paneAtTop?: ScalarCriteria;
  readonly paneBg?: ScalarCriteria;
  readonly paneBottom?: ScalarCriteria;
  readonly paneCurrentCommand?: ScalarCriteria;
  readonly paneCurrentPath?: ScalarCriteria;
  readonly paneDead?: ScalarCriteria;
  readonly paneDeadSignal?: ScalarCriteria;
  readonly paneDeadStatus?: ScalarCriteria;
  readonly paneDeadTime?: ScalarCriteria;
  readonly paneFg?: ScalarCriteria;
  readonly paneFlags?: ScalarCriteria;
  readonly paneFloatingFlag?: ScalarCriteria;
  readonly paneFormat?: ScalarCriteria;
  readonly paneHeight?: ScalarCriteria;
  readonly paneId?: ScalarCriteria;
  readonly paneInMode?: ScalarCriteria;
  readonly paneIndex?: ScalarCriteria;
  readonly paneInputOff?: ScalarCriteria;
  readonly paneLast?: ScalarCriteria;
  readonly paneLeft?: ScalarCriteria;
  readonly paneMarked?: ScalarCriteria;
  readonly paneMarkedSet?: ScalarCriteria;
  readonly paneMode?: ScalarCriteria;
  readonly panePath?: ScalarCriteria;
  readonly panePbProgress?: ScalarCriteria;
  readonly panePbState?: ScalarCriteria;
  readonly panePid?: ScalarCriteria;
  readonly panePipe?: ScalarCriteria;
  readonly panePipePid?: ScalarCriteria;
  readonly paneRight?: ScalarCriteria;
  readonly paneSearchString?: ScalarCriteria;
  readonly paneStartCommand?: ScalarCriteria;
  readonly paneStartPath?: ScalarCriteria;
  readonly paneSynchronized?: ScalarCriteria;
  readonly paneTabs?: ScalarCriteria;
  readonly paneTitle?: ScalarCriteria;
  readonly paneTop?: ScalarCriteria;
  readonly paneTty?: ScalarCriteria;
  readonly paneWidth?: ScalarCriteria;
  readonly paneX?: ScalarCriteria;
  readonly paneY?: ScalarCriteria;
  readonly paneZ?: ScalarCriteria;
  readonly paneZoomedFlag?: ScalarCriteria;
  readonly pid?: ScalarCriteria;
  readonly scrollRegionLower?: ScalarCriteria;
  readonly scrollRegionUpper?: ScalarCriteria;
  readonly socketPath?: ScalarCriteria;
  readonly startTime?: ScalarCriteria;
  readonly synchronizedOutputFlag?: ScalarCriteria;
  readonly uid?: ScalarCriteria;
  readonly user?: ScalarCriteria;
  readonly version?: ScalarCriteria;
  readonly wrapFlag?: ScalarCriteria;
  readonly window?: OneRelation<WindowWhere>;
  readonly session?: OneRelation<SessionWhere>;
}

// </libtmux-generated-where-types>

type WhereForKind<Kind> = Kind extends "session"
  ? SessionWhere
  : Kind extends "window"
    ? WindowWhere
    : Kind extends "pane"
      ? PaneWhere
      : never;

export type WhereOf<Model> = WhereForKind<ModelKindOf<Model>>;

export interface Selection<Model> extends Iterable<Model> {
  readonly length: number;
  [Symbol.iterator](): IterableIterator<Model>;
  at(index: number): Model | undefined;
  toArray(): Model[];
  filter(
    predicate: (value: Model, index: number, values: readonly Model[]) => unknown,
    thisArg?: unknown,
  ): Selection<Model>;
  where(criteria: WhereOf<Model>): Selection<Model>;
  first(criteria?: WhereOf<Model>): Model | undefined;
  one(criteria?: WhereOf<Model>): Model;
  oneOrUndefined(criteria?: WhereOf<Model>): Model | undefined;
  exists(criteria?: WhereOf<Model>): boolean;
  count(criteria?: WhereOf<Model>): number;
}

export type WhereDocumentV1 =
  | { readonly model: "session"; readonly version: 1; readonly where: SessionWhere }
  | { readonly model: "window"; readonly version: 1; readonly where: WindowWhere }
  | { readonly model: "pane"; readonly version: 1; readonly where: PaneWhere };

export function parseLegacyWhere<Model extends "session" | "window">(
  model: Model,
  input: unknown,
): Extract<WhereDocumentV1, { readonly model: Model }> {
  return lowerLegacyWhere(model, input);
}
