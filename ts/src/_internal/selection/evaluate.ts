import { types as nodeTypes } from "node:util";

import { Client } from "../../client.js";
import { MultipleMatchesError, NoMatchError, QueryValidationError } from "../../exc.js";
import { Pane } from "../../pane.js";
import type { Selection, WhereOf } from "../../selection.js";
import { Session } from "../../session.js";
import { Window } from "../../window.js";
import { WHERE_FIELDS_V1, WHERE_RELATIONS_V1 } from "../../_generated/where_fields.js";
import { graphRecordRefsEqual, type GraphRecordRef, type NormalizedGraph } from "../graph/model.js";
import { logicalRefsEqual, winlinkRefsEqual } from "../graph/refs.js";
import {
  isSelectionProjection,
  originGraphForSelectionProjection,
  selectionProjectionOwnsRecord,
  type ProjectionRecord,
  type SelectionProjection,
} from "../graph/selection_projection.js";
import type { ModelForKind } from "../runtime/model_kind.js";
import {
  entityRefForHandle,
  graphRecordRefForHandle,
  originGraphForHandle,
  snapshotForHandle,
  winlinkRefForHandle,
} from "../runtime/live_handle.js";
import { compileWhere, type CompiledWhere } from "./compile.js";

type ProjectedKind = "pane" | "session" | "window";
type ProjectedModel = Pane | Session | Window;

interface SelectionEntry<Model> {
  readonly record: ProjectionRecord | null;
  readonly value: Model;
}

interface ProjectedSelectionState {
  readonly kind: ProjectedKind;
  readonly projection: SelectionProjection;
  readonly resolve: (reference: GraphRecordRef) => ProjectionRecord | undefined;
}

interface ClientSelectionState {
  readonly kind: "client";
  readonly projection: null;
  readonly resolve: null;
}

type SelectionState = ClientSelectionState | ProjectedSelectionState;

const emptyQuery: Readonly<Record<string, unknown>> = Object.freeze({});
const selectionConstructionToken: object = Object.freeze({});

function invalidSelection(cause?: unknown): never {
  throw new QueryValidationError({
    ...(cause === undefined ? {} : { cause }),
    code: "invalid-query",
    message: "Invalid selection construction",
  });
}

function snapshotValues<Model>(input: readonly Model[]): readonly Model[] {
  try {
    if (nodeTypes.isProxy(input) || !Array.isArray(input)) return invalidSelection();
    if (Object.getPrototypeOf(input) !== Array.prototype) return invalidSelection();
    const lengthDescriptor = Object.getOwnPropertyDescriptor(input, "length");
    if (
      lengthDescriptor === undefined ||
      !("value" in lengthDescriptor) ||
      lengthDescriptor.enumerable ||
      typeof lengthDescriptor.value !== "number" ||
      !Number.isSafeInteger(lengthDescriptor.value) ||
      lengthDescriptor.value < 0
    ) {
      return invalidSelection();
    }
    const length = lengthDescriptor.value;
    const keys = Reflect.ownKeys(input);
    if (keys.length !== length + 1 || !keys.includes("length")) return invalidSelection();
    const result: Model[] = [];
    for (let index = 0; index < length; index += 1) {
      const key = String(index);
      if (!keys.includes(key)) return invalidSelection();
      const descriptor = Object.getOwnPropertyDescriptor(input, key);
      if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
        return invalidSelection();
      }
      result.push(descriptor.value as Model);
    }
    return Object.freeze(result);
  } catch (error) {
    if (error instanceof QueryValidationError) throw error;
    return invalidSelection(error);
  }
}

function referenceKey(reference: GraphRecordRef): string {
  return `${String(reference.source.length)}:${reference.source}:${String(reference.ordinal)}`;
}

function buildRecordResolver(
  projection: SelectionProjection,
): (reference: GraphRecordRef) => ProjectionRecord | undefined {
  const records = new Map<string, ProjectionRecord>();
  for (const record of projection.records) {
    if (!selectionProjectionOwnsRecord(projection, record)) return invalidSelection();
    const key = referenceKey(record.ref);
    if (records.has(key)) return invalidSelection();
    records.set(key, record);
  }
  return (reference): ProjectionRecord | undefined => {
    const record = records.get(referenceKey(reference));
    return record !== undefined && graphRecordRefsEqual(record.ref, reference) ? record : undefined;
  };
}

function validateProjectionRecord(
  projection: SelectionProjection,
  record: ProjectionRecord,
  resolve: (reference: GraphRecordRef) => ProjectionRecord | undefined,
): void {
  const expectedFields = WHERE_FIELDS_V1[record.model];
  const scalarKeys = Reflect.ownKeys(record.scalars);
  if (
    scalarKeys.length !== expectedFields.length ||
    scalarKeys.some(
      (key) => typeof key !== "string" || !expectedFields.some(({ wireName }) => wireName === key),
    )
  ) {
    return invalidSelection();
  }
  for (const { wireName } of expectedFields) {
    const value = record.scalars[wireName];
    if (typeof value !== "string" && value !== null) return invalidSelection();
  }

  const expectedRelations = WHERE_RELATIONS_V1[record.model];
  if (record.adjacency.length !== expectedRelations.length) return invalidSelection();
  for (const relation of expectedRelations) {
    const matches = record.adjacency.filter(
      (adjacency) =>
        adjacency.name === relation.name &&
        adjacency.cardinality === relation.cardinality &&
        adjacency.targetModel === relation.targetModel,
    );
    if (matches.length !== 1) return invalidSelection();
    const adjacency = matches[0];
    if (adjacency === undefined) return invalidSelection();
    const references =
      adjacency.cardinality === "many"
        ? adjacency.targets
        : adjacency.target === null
          ? []
          : [adjacency.target];
    for (const reference of references) {
      const target = resolve(reference);
      if (
        target === undefined ||
        target.model !== relation.targetModel ||
        !selectionProjectionOwnsRecord(projection, target)
      ) {
        return invalidSelection();
      }
    }
  }
}

function hasProjectedClass(model: ProjectedKind, value: unknown): value is ProjectedModel {
  if ((typeof value !== "object" && typeof value !== "function") || value === null) return false;
  if (nodeTypes.isProxy(value)) return false;
  switch (model) {
    case "pane":
      return value instanceof Pane;
    case "session":
      return value instanceof Session;
    case "window":
      return value instanceof Window;
  }
}

function authenticateProjectedValue(
  model: ProjectedKind,
  value: unknown,
  record: ProjectionRecord,
  projectionGraph: NormalizedGraph,
): asserts value is ProjectedModel {
  if (!hasProjectedClass(model, value) || record.model !== model) return invalidSelection();
  try {
    const entity = entityRefForHandle(value);
    const graph = originGraphForHandle(value);
    const graphRecord = graphRecordRefForHandle(value);
    const snapshot = snapshotForHandle(value);
    const winlink = winlinkRefForHandle(value);
    if (
      graph !== projectionGraph ||
      !graphRecordRefsEqual(graphRecord, record.ref) ||
      entity.kind !== model ||
      !logicalRefsEqual(record.entity, entity)
    )
      return invalidSelection();
    for (const field of WHERE_FIELDS_V1[model]) {
      if (snapshot[field.token] !== record.scalars[field.wireName]) return invalidSelection();
    }
    if (
      (record.winlink === null && winlink !== null) ||
      (record.winlink !== null && winlink === null) ||
      (record.winlink !== null && winlink !== null && !winlinkRefsEqual(record.winlink, winlink))
    ) {
      return invalidSelection();
    }
  } catch (error) {
    if (error instanceof QueryValidationError) throw error;
    return invalidSelection(error);
  }
}

function authenticateClient(value: unknown): asserts value is Client {
  if (
    (typeof value !== "object" && typeof value !== "function") ||
    value === null ||
    nodeTypes.isProxy(value) ||
    !(value instanceof Client)
  ) {
    return invalidSelection();
  }
  try {
    const entity = entityRefForHandle(value);
    snapshotForHandle(value);
    if (entity.kind !== "client" || winlinkRefForHandle(value) !== null) return invalidSelection();
  } catch (error) {
    if (error instanceof QueryValidationError) throw error;
    return invalidSelection(error);
  }
}

function projectedEntries<Kind extends ProjectedKind>(
  model: Kind,
  values: readonly ModelForKind<Kind>[],
  projection: SelectionProjection,
): {
  readonly entries: readonly SelectionEntry<ModelForKind<Kind>>[];
  readonly state: ProjectedSelectionState;
} {
  if (!isSelectionProjection(projection)) return invalidSelection();
  const projectionGraph = originGraphForSelectionProjection(projection);
  if (projectionGraph === undefined) return invalidSelection();
  const copiedValues = snapshotValues(values);
  if (copiedValues.length !== projection.members.length) return invalidSelection();
  const resolve = buildRecordResolver(projection);
  for (const record of projection.records) validateProjectionRecord(projection, record, resolve);

  const entries: Array<SelectionEntry<ModelForKind<Kind>>> = [];
  for (const [index, member] of projection.members.entries()) {
    const value = copiedValues[index];
    const record = resolve(member);
    if (value === undefined || record === undefined || record.model !== model) {
      return invalidSelection();
    }
    authenticateProjectedValue(model, value, record, projectionGraph);
    entries.push(Object.freeze({ record, value: value as ModelForKind<Kind> }));
  }
  return {
    entries: Object.freeze(entries),
    state: Object.freeze({ kind: model, projection, resolve }),
  };
}

function clientEntries(values: readonly Client[]): readonly SelectionEntry<Client>[] {
  const copiedValues = snapshotValues(values);
  const entries: Array<SelectionEntry<Client>> = [];
  for (const value of copiedValues) {
    authenticateClient(value);
    entries.push(Object.freeze({ record: null, value }));
  }
  return Object.freeze(entries);
}

class SelectionImpl<Model> implements Selection<Model> {
  readonly #entries: readonly SelectionEntry<Model>[];
  readonly #state: SelectionState;
  readonly #values: readonly Model[];

  constructor(token: object, entries: readonly SelectionEntry<Model>[], state: SelectionState) {
    if (token !== selectionConstructionToken) invalidSelection();
    this.#entries = entries;
    this.#state = state;
    this.#values = Object.freeze(entries.map(({ value }) => value));
    Object.freeze(this);
  }

  get length(): number {
    return this.#entries.length;
  }

  [Symbol.iterator](): IterableIterator<Model> {
    return this.#values[Symbol.iterator]();
  }

  at(index: number): Model | undefined {
    return this.#values.at(index);
  }

  toArray(): Model[] {
    return [...this.#values];
  }

  filter(
    predicate: (value: Model, index: number, values: readonly Model[]) => unknown,
    thisArg?: unknown,
  ): Selection<Model> {
    if (typeof predicate !== "function") throw new TypeError("predicate must be a function");
    const entries = this.#entries.filter(({ value }, index) =>
      Boolean(predicate.call(thisArg, value, index, this.#values)),
    );
    return new SelectionImpl(selectionConstructionToken, Object.freeze(entries), this.#state);
  }

  where(criteria: WhereOf<Model>): Selection<Model> {
    if (criteria === undefined || this.#state.kind === "client") return invalidSelection();
    const matched = this.#matchingEntries(criteria);
    return new SelectionImpl(selectionConstructionToken, matched, this.#state);
  }

  first(criteria?: WhereOf<Model>): Model | undefined {
    return this.#matchingEntries(criteria).at(0)?.value;
  }

  one(criteria?: WhereOf<Model>): Model {
    const { entries, query } = this.#matchingWithQuery(criteria);
    if (entries.length === 0) throw new NoMatchError({ query });
    if (entries.length !== 1) throw new MultipleMatchesError({ count: entries.length, query });
    return entries[0]!.value;
  }

  oneOrUndefined(criteria?: WhereOf<Model>): Model | undefined {
    const { entries, query } = this.#matchingWithQuery(criteria);
    if (entries.length > 1) throw new MultipleMatchesError({ count: entries.length, query });
    return entries[0]?.value;
  }

  exists(criteria?: WhereOf<Model>): boolean {
    return this.#matchingEntries(criteria).length > 0;
  }

  count(criteria?: WhereOf<Model>): number {
    return this.#matchingEntries(criteria).length;
  }

  #compile(criteria: unknown): CompiledWhere | null {
    if (criteria === undefined) return null;
    if (this.#state.kind === "client") return invalidSelection();
    return compileWhere(this.#state.kind, criteria);
  }

  #matchingEntries(criteria: unknown): readonly SelectionEntry<Model>[] {
    return this.#matchingWithQuery(criteria).entries;
  }

  #matchingWithQuery(criteria: unknown): {
    readonly entries: readonly SelectionEntry<Model>[];
    readonly query: Readonly<Record<string, unknown>>;
  } {
    const compiled = this.#compile(criteria);
    if (compiled === null) return { entries: this.#entries, query: emptyQuery };
    if (this.#state.kind === "client") return invalidSelection();
    const state = this.#state;
    const entries = this.#entries.filter(({ record }) =>
      record === null ? false : compiled.matches(record, state.resolve),
    );
    return { entries: Object.freeze(entries), query: compiled.query };
  }
}

Object.freeze(SelectionImpl.prototype);
Object.freeze(SelectionImpl);

export function createProjectedSelection<Kind extends ProjectedKind>(
  model: Kind,
  values: readonly ModelForKind<Kind>[],
  projection: SelectionProjection,
): Selection<ModelForKind<Kind>> {
  if (model !== "pane" && model !== "session" && model !== "window") {
    return invalidSelection();
  }
  const { entries, state } = projectedEntries(model, values, projection);
  return new SelectionImpl(selectionConstructionToken, entries, state);
}

export function createClientSelection(values: readonly Client[]): Selection<Client> {
  const state: ClientSelectionState = Object.freeze({
    kind: "client",
    projection: null,
    resolve: null,
  });
  return new SelectionImpl(selectionConstructionToken, clientEntries(values), state);
}
