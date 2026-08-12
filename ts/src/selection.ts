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
  readonly activity?: ScalarCriteria;
  readonly alerts?: ScalarCriteria;
  readonly attached?: ScalarCriteria;
  readonly attachedList?: ScalarCriteria;
  readonly created?: ScalarCriteria;
  readonly format?: ScalarCriteria;
  readonly group?: ScalarCriteria;
  readonly groupAttached?: ScalarCriteria;
  readonly groupAttachedList?: ScalarCriteria;
  readonly groupList?: ScalarCriteria;
  readonly groupManyAttached?: ScalarCriteria;
  readonly groupSize?: ScalarCriteria;
  readonly grouped?: ScalarCriteria;
  readonly id?: ScalarCriteria;
  readonly lastAttached?: ScalarCriteria;
  readonly lastWindowIndex?: ScalarCriteria;
  readonly manyAttached?: ScalarCriteria;
  readonly marked?: ScalarCriteria;
  readonly name?: ScalarCriteria;
  readonly path?: ScalarCriteria;
  readonly sessionWindows?: ScalarCriteria;
  readonly stack?: ScalarCriteria;
  readonly windows?: ManyRelation<WindowWhere>;
  readonly panes?: ManyRelation<PaneWhere>;
  readonly activeWindow?: OneRelation<WindowWhere>;
  readonly activePane?: OneRelation<PaneWhere>;
}

export interface WindowWhere {
  readonly AND?: readonly WindowWhere[];
  readonly OR?: readonly WindowWhere[];
  readonly NOT?: readonly WindowWhere[];
  readonly active?: ScalarCriteria;
  readonly activeClients?: ScalarCriteria;
  readonly activeClientsList?: ScalarCriteria;
  readonly activeSessions?: ScalarCriteria;
  readonly activeSessionsList?: ScalarCriteria;
  readonly activity?: ScalarCriteria;
  readonly activityFlag?: ScalarCriteria;
  readonly bellFlag?: ScalarCriteria;
  readonly bigger?: ScalarCriteria;
  readonly cellHeight?: ScalarCriteria;
  readonly cellWidth?: ScalarCriteria;
  readonly endFlag?: ScalarCriteria;
  readonly flags?: ScalarCriteria;
  readonly format?: ScalarCriteria;
  readonly height?: ScalarCriteria;
  readonly id?: ScalarCriteria;
  readonly index?: ScalarCriteria;
  readonly lastFlag?: ScalarCriteria;
  readonly layout?: ScalarCriteria;
  readonly linked?: ScalarCriteria;
  readonly linkedSessionsList?: ScalarCriteria;
  readonly markedFlag?: ScalarCriteria;
  readonly name?: ScalarCriteria;
  readonly offsetX?: ScalarCriteria;
  readonly offsetY?: ScalarCriteria;
  readonly rawFlags?: ScalarCriteria;
  readonly silenceFlag?: ScalarCriteria;
  readonly stackIndex?: ScalarCriteria;
  readonly startFlag?: ScalarCriteria;
  readonly visibleLayout?: ScalarCriteria;
  readonly width?: ScalarCriteria;
  readonly windowLinkedSessions?: ScalarCriteria;
  readonly windowPanes?: ScalarCriteria;
  readonly zoomedFlag?: ScalarCriteria;
  readonly session?: OneRelation<SessionWhere>;
  readonly linkedSessions?: ManyRelation<SessionWhere>;
  readonly panes?: ManyRelation<PaneWhere>;
  readonly activePane?: OneRelation<PaneWhere>;
}

export interface PaneWhere {
  readonly AND?: readonly PaneWhere[];
  readonly OR?: readonly PaneWhere[];
  readonly NOT?: readonly PaneWhere[];
  readonly active?: ScalarCriteria;
  readonly alternateSavedX?: ScalarCriteria;
  readonly alternateSavedY?: ScalarCriteria;
  readonly atBottom?: ScalarCriteria;
  readonly atLeft?: ScalarCriteria;
  readonly atRight?: ScalarCriteria;
  readonly atTop?: ScalarCriteria;
  readonly bg?: ScalarCriteria;
  readonly bottom?: ScalarCriteria;
  readonly bracketPasteFlag?: ScalarCriteria;
  readonly currentCommand?: ScalarCriteria;
  readonly currentPath?: ScalarCriteria;
  readonly cursorCharacter?: ScalarCriteria;
  readonly cursorFlag?: ScalarCriteria;
  readonly cursorX?: ScalarCriteria;
  readonly cursorY?: ScalarCriteria;
  readonly dead?: ScalarCriteria;
  readonly deadSignal?: ScalarCriteria;
  readonly deadStatus?: ScalarCriteria;
  readonly deadTime?: ScalarCriteria;
  readonly fg?: ScalarCriteria;
  readonly flags?: ScalarCriteria;
  readonly floatingFlag?: ScalarCriteria;
  readonly format?: ScalarCriteria;
  readonly height?: ScalarCriteria;
  readonly historyBytes?: ScalarCriteria;
  readonly historyLimit?: ScalarCriteria;
  readonly historySize?: ScalarCriteria;
  readonly id?: ScalarCriteria;
  readonly inMode?: ScalarCriteria;
  readonly index?: ScalarCriteria;
  readonly inputOff?: ScalarCriteria;
  readonly insertFlag?: ScalarCriteria;
  readonly keypadCursorFlag?: ScalarCriteria;
  readonly keypadFlag?: ScalarCriteria;
  readonly last?: ScalarCriteria;
  readonly left?: ScalarCriteria;
  readonly marked?: ScalarCriteria;
  readonly markedSet?: ScalarCriteria;
  readonly mode?: ScalarCriteria;
  readonly mouseAllFlag?: ScalarCriteria;
  readonly mouseAnyFlag?: ScalarCriteria;
  readonly mouseButtonFlag?: ScalarCriteria;
  readonly mouseSgrFlag?: ScalarCriteria;
  readonly mouseStandardFlag?: ScalarCriteria;
  readonly originFlag?: ScalarCriteria;
  readonly path?: ScalarCriteria;
  readonly pbProgress?: ScalarCriteria;
  readonly pbState?: ScalarCriteria;
  readonly pid?: ScalarCriteria;
  readonly pipe?: ScalarCriteria;
  readonly pipePid?: ScalarCriteria;
  readonly right?: ScalarCriteria;
  readonly scrollRegionLower?: ScalarCriteria;
  readonly scrollRegionUpper?: ScalarCriteria;
  readonly searchString?: ScalarCriteria;
  readonly startCommand?: ScalarCriteria;
  readonly startPath?: ScalarCriteria;
  readonly synchronized?: ScalarCriteria;
  readonly synchronizedOutputFlag?: ScalarCriteria;
  readonly tabs?: ScalarCriteria;
  readonly title?: ScalarCriteria;
  readonly top?: ScalarCriteria;
  readonly tty?: ScalarCriteria;
  readonly width?: ScalarCriteria;
  readonly wrapFlag?: ScalarCriteria;
  readonly x?: ScalarCriteria;
  readonly y?: ScalarCriteria;
  readonly z?: ScalarCriteria;
  readonly zoomedFlag?: ScalarCriteria;
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
