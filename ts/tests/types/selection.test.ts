import { Client } from "../../src/client.js";
import type { SelectionProjection } from "../../src/_internal/graph/selection_projection.js";
import type { ModelForKind } from "../../src/_internal/runtime/model_kind.js";
import {
  createClientSelection,
  createProjectedSelection,
} from "../../src/_internal/selection/evaluate.js";
import { Pane } from "../../src/pane.js";
import { Server } from "../../src/server.js";
import { Session } from "../../src/session.js";
import { Window } from "../../src/window.js";
import * as selectionModule from "../../src/selection.js";
import {
  parseLegacyWhere,
  type PaneWhere,
  type RegexCriteriaData,
  type Selection,
  type SessionWhere,
  type WhereDocumentV1,
  type WhereOf,
  type WindowWhere,
} from "../../src/selection.js";
import type { CompleteFormatRow } from "../../src/_internal/codec/schemas.js";
import type { Equal, Expect } from "./assert.js";

// The query surface is reachable from the package root, and is the same type
// the dedicated subpath exports.
type _RootSelection = Expect<
  Equal<import("../../src/index.js").Selection<Session>, Selection<Session>>
>;
type _RootWhereOf = Expect<Equal<import("../../src/index.js").WhereOf<Session>, WhereOf<Session>>>;
type _RootSessionWhere = Expect<Equal<import("../../src/index.js").SessionWhere, SessionWhere>>;
type _RootWindowWhere = Expect<Equal<import("../../src/index.js").WindowWhere, WindowWhere>>;
type _RootPaneWhere = Expect<Equal<import("../../src/index.js").PaneWhere, PaneWhere>>;
type _RootRegexCriteriaData = Expect<
  Equal<import("../../src/index.js").RegexCriteriaData, RegexCriteriaData>
>;
type _RootWhereDocumentV1 = Expect<
  Equal<import("../../src/index.js").WhereDocumentV1, WhereDocumentV1>
>;

type ExpectedSelection<Model> = {
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
};

type StructuralSession = CompleteFormatRow & {
  readonly equals: (other: unknown) => boolean;
  readonly server: Server;
};

type ExpectedParseLegacyWhere = <Model extends "session" | "window">(
  model: Model,
  input: unknown,
) => Extract<WhereDocumentV1, { readonly model: Model }>;
type ExpectedCreateProjectedSelection = <Kind extends "pane" | "session" | "window">(
  model: Kind,
  values: readonly ModelForKind<Kind>[],
  projection: SelectionProjection,
) => Selection<ModelForKind<Kind>>;

type _SelectionShape = Expect<Equal<Selection<Session>, ExpectedSelection<Session>>>;
type _SelectionKeys = Expect<
  Equal<
    keyof Selection<Session>,
    | typeof Symbol.iterator
    | "at"
    | "count"
    | "exists"
    | "filter"
    | "first"
    | "length"
    | "one"
    | "oneOrUndefined"
    | "toArray"
    | "where"
  >
>;
type _SessionWhere = Expect<Equal<WhereOf<Session>, SessionWhere>>;
type _WindowWhere = Expect<Equal<WhereOf<Window>, WindowWhere>>;
type _PaneWhere = Expect<Equal<WhereOf<Pane>, PaneWhere>>;
type _ClientWhere = Expect<Equal<WhereOf<Client>, never>>;
type _ServerWhere = Expect<Equal<WhereOf<Server>, never>>;
type _UnknownWhere = Expect<Equal<WhereOf<unknown>, never>>;
type _StructuralWhere = Expect<Equal<WhereOf<StructuralSession>, never>>;
type _ParseLegacyWhere = Expect<Equal<typeof parseLegacyWhere, ExpectedParseLegacyWhere>>;
type _CreateProjectedSelection = Expect<
  Equal<typeof createProjectedSelection, ExpectedCreateProjectedSelection>
>;
type _CreateClientSelection = Expect<
  Equal<typeof createClientSelection, (values: readonly Client[]) => Selection<Client>>
>;
type _RuntimeExports = Expect<Equal<keyof typeof selectionModule, "parseLegacyWhere">>;
type _RegexData = Expect<
  Equal<RegexCriteriaData, { readonly flags: "" | "m" | "s" | "ms"; readonly pattern: string }>
>;

declare const clients: Selection<Client>;
declare const panes: Selection<Pane>;
declare const sessions: Selection<Session>;
declare const windows: Selection<Window>;
declare const mixed: Selection<Session | Window>;
declare const session: Session;

void sessions.length;
void sessions.at(-1);
void sessions.toArray();
void sessions.where({ name: "main" });
void sessions.first();
void sessions.first({ name: "main" });
void sessions.one();
void sessions.one({ name: "main" });
void sessions.oneOrUndefined();
void sessions.exists();
void sessions.count();
void panes.where({ pane_id: "%1" });
void windows.where({ name: "editor" });
void clients.first();
void clients.one();
void clients.oneOrUndefined();
void clients.exists();
void clients.count();

const callbackFiltered = sessions.filter(
  (value: Session, index: number, values: readonly Session[]) => {
    void value.session_id;
    void index;
    void values[0]?.session_name;
    // @ts-expect-error callback values are readonly.
    values[0] = session;
    return true;
  },
);
type _CallbackResult = Expect<Equal<typeof callbackFiltered, Selection<Session>>>;

const narrowed = mixed.filter(
  (value: Session | Window): value is Session => value instanceof Session,
);
type _NoTypeGuardNarrowing = Expect<Equal<typeof narrowed, Selection<Session | Window>>>;

const thisArgument = { prefix: "m" };
sessions.filter(function (this: typeof thisArgument, value: Session) {
  return value.session_name?.startsWith(this.prefix);
}, thisArgument);

// @ts-expect-error Selection is a type-only interface, not a constructor value.
void new Selection<Session>();
// @ts-expect-error Selection accepts exactly one type parameter.
type InvalidSelection = Selection<Session, SessionWhere>;
// @ts-expect-error callback filtering requires a predicate.
sessions.filter();
// @ts-expect-error callback filtering does not accept declarative criteria.
sessions.filter({ name: "main" });
// @ts-expect-error where requires declarative data.
sessions.where((value: Session) => value.session_name === "main");
// @ts-expect-error Session criteria do not accept Window fields.
sessions.where({ window_id: "@1" });
// @ts-expect-error Client has no declarative criteria.
clients.where({});
// @ts-expect-error Client cardinality is criteria-free.
clients.first({});
// @ts-expect-error Selection has no exactly-one get alias.
sessions.get({ name: "main" });
// @ts-expect-error Selection has no Array mutation surface.
sessions.push(session);
// @ts-expect-error Selection has no direct index signature.
void sessions[0];
// @ts-expect-error QueryList is intentionally absent.
type MissingQueryList = import("../../src/selection.js").QueryList<Session>;
// @ts-expect-error ClientWhere is intentionally absent.
type MissingClientWhere = import("../../src/selection.js").ClientWhere;
// @ts-expect-error scalar helper types remain private implementation details.
type MissingStringFilter = import("../../src/selection.js").StringFilter;

void callbackFiltered;
void narrowed;
void (null as unknown as InvalidSelection);
void (null as unknown as MissingQueryList);
void (null as unknown as MissingClientWhere);
void (null as unknown as MissingStringFilter);
