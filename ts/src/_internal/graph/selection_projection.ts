import {
  WHERE_FIELDS_V1,
  type WhereField,
  type WhereModel,
} from "../../_generated/where_fields.js";
import type { LogicalRef } from "../../common.js";
import {
  createGraphRecordRef,
  graphRecordRefsEqual,
  isNormalizedGraph,
  type GraphCapture,
  type GraphEntity,
  type GraphRecord,
  type GraphRecordRef,
  type GraphSource,
  type GraphSourceId,
  type NormalizedGraph,
  type WinlinkEntity,
} from "./model.js";
import { createLogicalRef, createWinlinkRef, type WinlinkRef } from "./refs.js";

export interface ProjectionRelationRequirement {
  readonly cardinality: "many" | "one";
  readonly name: string;
  readonly targetModel: WhereModel;
}

export interface ProjectionDescriptor {
  readonly fields: readonly WhereField[];
  readonly model: WhereModel;
  readonly relations: readonly ProjectionRelationRequirement[];
}

export interface ProjectionOneAdjacency {
  readonly cardinality: "one";
  readonly name: string;
  readonly target: GraphRecordRef | null;
  readonly targetModel: WhereModel;
}

export interface ProjectionManyAdjacency {
  readonly cardinality: "many";
  readonly name: string;
  readonly targetModel: WhereModel;
  readonly targets: readonly GraphRecordRef[];
}

export type ProjectionAdjacency = ProjectionManyAdjacency | ProjectionOneAdjacency;

export type ProjectionScalars = Readonly<Record<string, string | null>>;

export interface ProjectionRecord {
  readonly adjacency: readonly ProjectionAdjacency[];
  readonly entity: LogicalRef;
  readonly model: WhereModel;
  readonly ref: GraphRecordRef;
  readonly scalars: ProjectionScalars;
  readonly winlink: WinlinkRef | null;
}

declare class SelectionProjectionNominal {
  private readonly selectionProjectionBrand: undefined;
}

export interface SelectionProjection extends SelectionProjectionNominal {
  readonly capture: GraphCapture;
  readonly entities: readonly GraphEntity<LogicalRef>[];
  readonly members: readonly GraphRecordRef[];
  readonly records: readonly ProjectionRecord[];
  readonly winlinks: readonly WinlinkEntity[];
}

export type ProjectionBuilderState = "collecting" | "complete" | "failed";

export interface SelectionProjectionBuilderInput {
  readonly descriptors: Readonly<Record<WhereModel, ProjectionDescriptor>>;
  readonly graph: NormalizedGraph;
  readonly source: GraphSourceId;
}

interface RelationSlot {
  manyTargets: readonly GraphRecord[];
  materialized: boolean;
  oneTarget: GraphRecord | null;
  readonly requirement: ProjectionRelationRequirement;
}

type DescriptorSnapshots = Readonly<Record<WhereModel, ProjectionDescriptor>>;
type RecordIndex = ReadonlyMap<string, ReadonlyMap<number, GraphRecord>>;

const authenticatedSelectionProjections = new WeakSet<object>();
const selectionProjectionOrigins = new WeakMap<object, NormalizedGraph>();
const selectionProjectionRecordOwners = new WeakMap<object, SelectionProjection>();

function invalidProjection(message: string, cause?: unknown): never {
  throw cause === undefined ? new Error(message) : new Error(message, { cause });
}

function readStrictDataRecord(
  value: unknown,
  expectedKeys: readonly string[],
  label: string,
): Readonly<Record<string, unknown>> {
  if (typeof value !== "object" || value === null) {
    return invalidProjection(`${label} must be an object`);
  }

  let isArray: boolean;
  let prototype: object | null;
  let ownKeys: readonly PropertyKey[];
  let descriptors: readonly (PropertyDescriptor | undefined)[];
  let finalPrototype: object | null;
  let finalOwnKeys: readonly PropertyKey[];
  try {
    isArray = Array.isArray(value);
    prototype = Object.getPrototypeOf(value);
    ownKeys = Reflect.ownKeys(value);
    descriptors = expectedKeys.map((key) => Object.getOwnPropertyDescriptor(value, key));
    finalPrototype = Object.getPrototypeOf(value);
    finalOwnKeys = Reflect.ownKeys(value);
  } catch (error) {
    return invalidProjection(`${label} could not be inspected`, error);
  }

  if (
    isArray ||
    prototype !== finalPrototype ||
    (prototype !== Object.prototype && prototype !== null) ||
    (finalPrototype !== Object.prototype && finalPrototype !== null)
  ) {
    return invalidProjection(`${label} must be a plain data object`);
  }
  if (
    ownKeys.length !== expectedKeys.length ||
    ownKeys.some((key) => typeof key !== "string" || !expectedKeys.includes(key)) ||
    ownKeys.length !== finalOwnKeys.length ||
    ownKeys.some((key) => !finalOwnKeys.includes(key))
  ) {
    return invalidProjection(`${label} has invalid keys`);
  }

  const entries: Array<readonly [string, unknown]> = [];
  for (const [index, key] of expectedKeys.entries()) {
    const descriptor = descriptors[index];
    if (descriptor === undefined || !("value" in descriptor) || !descriptor.enumerable) {
      return invalidProjection(`${label} must contain enumerable data properties`);
    }
    entries.push([key, descriptor.value]);
  }
  return Object.fromEntries(entries);
}

function snapshotDataArray(value: unknown, label: string): readonly unknown[] {
  let isArray: boolean;
  let lengthDescriptor: PropertyDescriptor | undefined;
  const elementDescriptors: Array<PropertyDescriptor | undefined> = [];
  try {
    isArray = Array.isArray(value);
    if (isArray) {
      lengthDescriptor = Object.getOwnPropertyDescriptor(value, "length");
      const length = lengthDescriptor?.value;
      if (typeof length === "number" && Number.isSafeInteger(length) && length >= 0) {
        for (let index = 0; index < length; index += 1) {
          elementDescriptors.push(Object.getOwnPropertyDescriptor(value, String(index)));
        }
      }
    }
  } catch (error) {
    return invalidProjection(`${label} could not be inspected`, error);
  }

  if (!isArray) return invalidProjection(`${label} must be an array`);
  if (
    lengthDescriptor === undefined ||
    !("value" in lengthDescriptor) ||
    lengthDescriptor.enumerable ||
    typeof lengthDescriptor.value !== "number" ||
    !Number.isSafeInteger(lengthDescriptor.value) ||
    lengthDescriptor.value < 0 ||
    elementDescriptors.length !== lengthDescriptor.value
  ) {
    return invalidProjection(`${label} must have a valid array length`);
  }

  const values: unknown[] = [];
  for (const descriptor of elementDescriptors) {
    if (descriptor === undefined || !("value" in descriptor) || !descriptor.enumerable) {
      return invalidProjection(`${label} must contain own enumerable data elements`);
    }
    values.push(descriptor.value);
  }
  return values;
}

function isWhereModel(value: unknown): value is WhereModel {
  return value === "session" || value === "window" || value === "pane";
}

function snapshotDescriptor(model: WhereModel, value: unknown): ProjectionDescriptor {
  const descriptor = readStrictDataRecord(
    value,
    ["fields", "model", "relations"],
    `${model} descriptor`,
  );
  if (descriptor.model !== model) {
    return invalidProjection(`${model} descriptor model does not match its key`);
  }

  const fields: WhereField[] = [];
  const seenTokens = new Set<string>();
  const seenWireNames = new Set<string>();
  for (const value of snapshotDataArray(descriptor.fields, `${model} descriptor fields`)) {
    const field = readStrictDataRecord(value, ["domain", "token", "wireName"], `${model} field`);
    if (
      field.domain !== "string" ||
      typeof field.token !== "string" ||
      typeof field.wireName !== "string"
    ) {
      return invalidProjection(`${model} field is invalid`);
    }
    if (seenTokens.has(field.token)) {
      return invalidProjection(`${model} descriptor has a duplicate field token`);
    }
    if (seenWireNames.has(field.wireName)) {
      return invalidProjection(`${model} descriptor has a duplicate field wire name`);
    }
    const canonical = WHERE_FIELDS_V1[model].find(
      ({ domain, token, wireName }) =>
        domain === field.domain && token === field.token && wireName === field.wireName,
    );
    if (canonical === undefined) {
      return invalidProjection(`${model} field does not belong to the generated descriptor`);
    }
    seenTokens.add(canonical.token);
    seenWireNames.add(canonical.wireName);
    fields.push(
      Object.freeze({
        domain: canonical.domain,
        token: canonical.token,
        wireName: canonical.wireName,
      }),
    );
  }

  const relations: ProjectionRelationRequirement[] = [];
  const seenRelationNames = new Set<string>();
  for (const value of snapshotDataArray(descriptor.relations, `${model} descriptor relations`)) {
    const relation = readStrictDataRecord(
      value,
      ["cardinality", "name", "targetModel"],
      `${model} relation`,
    );
    if (typeof relation.name !== "string" || relation.name.length === 0) {
      return invalidProjection(`${model} relation name must be a nonempty string`);
    }
    if (seenRelationNames.has(relation.name)) {
      return invalidProjection(`${model} descriptor has a duplicate relation name`);
    }
    if (relation.cardinality !== "one" && relation.cardinality !== "many") {
      return invalidProjection(`${model} relation cardinality is invalid`);
    }
    if (!isWhereModel(relation.targetModel)) {
      return invalidProjection(`${model} relation target model is invalid`);
    }
    seenRelationNames.add(relation.name);
    relations.push(
      Object.freeze({
        cardinality: relation.cardinality,
        name: relation.name,
        targetModel: relation.targetModel,
      }),
    );
  }

  return Object.freeze({
    fields: Object.freeze(fields),
    model,
    relations: Object.freeze(relations),
  });
}

function snapshotDescriptors(value: unknown): DescriptorSnapshots {
  const descriptors = readStrictDataRecord(
    value,
    ["pane", "session", "window"],
    "projection descriptors",
  );
  return Object.freeze({
    pane: snapshotDescriptor("pane", descriptors.pane),
    session: snapshotDescriptor("session", descriptors.session),
    window: snapshotDescriptor("window", descriptors.window),
  });
}

function rootModel(source: GraphSource): WhereModel {
  switch (source.listCommand) {
    case "list-clients":
      return invalidProjection("client sources cannot create a selection projection");
    case "list-panes":
      return "pane";
    case "list-sessions":
      return "session";
    case "list-windows":
      return "window";
  }
}

function createRecordIndex(graph: NormalizedGraph): RecordIndex {
  const bySource = new Map<string, Map<number, GraphRecord>>();
  for (const record of graph.records) {
    let byOrdinal = bySource.get(record.ref.source);
    if (byOrdinal === undefined) {
      byOrdinal = new Map<number, GraphRecord>();
      bySource.set(record.ref.source, byOrdinal);
    }
    if (byOrdinal.has(record.ref.ordinal)) {
      return invalidProjection("normalized graph has a duplicate record reference");
    }
    byOrdinal.set(record.ref.ordinal, record);
  }
  return bySource;
}

function logicalEntityForRecord(record: GraphRecord): LogicalRef {
  if (!isWhereModel(record.model) || record.entity.kind !== record.model) {
    return invalidProjection("reachable graph record has an invalid projection model");
  }
  return record.entity;
}

function cloneLogicalRef(ref: LogicalRef): LogicalRef {
  switch (ref.kind) {
    case "session":
      return createLogicalRef({
        connection: ref.connection,
        epoch: ref.epoch,
        id: ref.id,
        kind: "session",
      });
    case "window":
      return createLogicalRef({
        connection: ref.connection,
        epoch: ref.epoch,
        id: ref.id,
        kind: "window",
      });
    case "pane":
      return createLogicalRef({
        connection: ref.connection,
        epoch: ref.epoch,
        id: ref.id,
        kind: "pane",
      });
  }
}

function cloneWinlinkRef(ref: WinlinkRef): WinlinkRef {
  return createWinlinkRef({
    connection: ref.connection,
    epoch: ref.epoch,
    sessionId: ref.sessionId,
    windowId: ref.windowId,
    windowIndex: ref.windowIndex,
  });
}

function logicalRefKey(ref: LogicalRef): string {
  return JSON.stringify([ref.connection, ref.epoch, ref.kind, ref.id]);
}

function winlinkRefKey(ref: WinlinkRef): string {
  return JSON.stringify([ref.connection, ref.epoch, ref.sessionId, ref.windowIndex, ref.windowId]);
}

function projectScalars(record: GraphRecord, descriptor: ProjectionDescriptor): ProjectionScalars {
  return Object.freeze(
    Object.fromEntries(
      descriptor.fields.map(({ token, wireName }) => [wireName, record.scalars[token]]),
    ),
  );
}

export class IncompleteProjectionError extends Error {
  constructor() {
    super("selection projection hydration is incomplete");
    this.name = "IncompleteProjectionError";
  }
}

export class SelectionProjectionBuilder {
  private readonly descriptors: DescriptorSnapshots;
  private readonly graph: NormalizedGraph;
  private readonly reachableRecords: GraphRecord[] = [];
  private readonly reachableSet: Set<GraphRecord> = new Set<GraphRecord>();
  private readonly recordIndex: RecordIndex;
  private readonly rootRecords: readonly GraphRecord[];
  private readonly slots: Map<GraphRecord, Map<string, RelationSlot>> = new Map<
    GraphRecord,
    Map<string, RelationSlot>
  >();
  private builderState: ProjectionBuilderState = "collecting";
  private completedProjection: SelectionProjection | undefined;
  private failureCause: unknown;

  private constructor(
    descriptors: DescriptorSnapshots,
    graph: NormalizedGraph,
    rootSource: GraphSource,
    expectedRootModel: WhereModel,
  ) {
    this.descriptors = descriptors;
    this.graph = graph;
    this.recordIndex = createRecordIndex(graph);
    const roots: GraphRecord[] = [];
    for (const ref of rootSource.records) {
      const record = this.resolveRecord(ref);
      if (record.model !== expectedRootModel) {
        invalidProjection("source contains a record with the wrong root model");
      }
      roots.push(record);
      this.addReachable(record);
    }
    this.rootRecords = Object.freeze(roots);
  }

  static create(input: SelectionProjectionBuilderInput): SelectionProjectionBuilder {
    const values = readStrictDataRecord(
      input,
      ["descriptors", "graph", "source"],
      "projection builder input",
    );
    if (!isNormalizedGraph(values.graph)) {
      return invalidProjection("selection projection requires an authentic normalized graph");
    }
    if (typeof values.source !== "string" || values.source.length === 0) {
      return invalidProjection("selection projection source must be a nonempty graph source ID");
    }
    const source = values.graph.sources.find(({ id }) => id === values.source);
    if (source === undefined) {
      return invalidProjection("selection projection source does not exist in the graph");
    }
    const expectedRootModel = rootModel(source);
    const descriptors = snapshotDescriptors(values.descriptors);
    return new SelectionProjectionBuilder(descriptors, values.graph, source, expectedRootModel);
  }

  get state(): ProjectionBuilderState {
    return this.builderState;
  }

  abort(cause: unknown): never {
    if (this.builderState === "failed") throw this.failureCause;
    if (this.builderState === "complete") {
      return invalidProjection("selection projection is already complete");
    }
    this.builderState = "failed";
    this.failureCause = cause;
    throw cause;
  }

  materializeOne(source: GraphRecordRef, relation: string, target: GraphRecordRef | null): void {
    this.requireCollecting();
    const slot = this.resolveReachableSlot(source, relation);
    if (slot.requirement.cardinality !== "one") {
      return invalidProjection("projection relation cardinality does not accept one target");
    }
    if (slot.materialized) {
      return invalidProjection("projection relation slot is already materialized");
    }

    let targetRecord: GraphRecord | null = null;
    if (target !== null) {
      targetRecord = this.resolveRecord(target);
      if (targetRecord.model !== slot.requirement.targetModel) {
        return invalidProjection("projection relation target model does not match");
      }
    }

    slot.oneTarget = targetRecord;
    slot.materialized = true;
    if (targetRecord !== null) this.addReachable(targetRecord);
  }

  materializeMany(
    source: GraphRecordRef,
    relation: string,
    targets: readonly GraphRecordRef[],
  ): void {
    this.requireCollecting();
    const slot = this.resolveReachableSlot(source, relation);
    if (slot.requirement.cardinality !== "many") {
      return invalidProjection("projection relation cardinality does not accept many targets");
    }
    if (slot.materialized) {
      return invalidProjection("projection relation slot is already materialized");
    }

    let targetValues: readonly unknown[];
    try {
      targetValues = snapshotDataArray(targets, "projection target record array");
    } catch (error) {
      this.requireCollecting();
      throw error;
    }

    const targetRecords: GraphRecord[] = [];
    for (const target of targetValues) {
      const targetRecord = this.resolveRecord(target as GraphRecordRef);
      if (targetRecord.model !== slot.requirement.targetModel) {
        return invalidProjection("projection relation target model does not match");
      }
      targetRecords.push(targetRecord);
    }

    this.requireCollecting();
    if (slot.materialized) {
      return invalidProjection("projection relation slot is already materialized");
    }
    slot.manyTargets = Object.freeze(targetRecords);
    slot.materialized = true;
    for (const targetRecord of targetRecords) this.addReachable(targetRecord);
  }

  seal(): SelectionProjection {
    if (this.builderState === "failed") throw this.failureCause;
    if (this.builderState === "complete") {
      if (this.completedProjection === undefined) {
        return invalidProjection("completed selection projection is unavailable");
      }
      return this.completedProjection;
    }

    for (const record of this.reachableRecords) {
      for (const slot of this.slots.get(record)?.values() ?? []) {
        if (!slot.materialized) throw new IncompleteProjectionError();
      }
    }

    const projection = this.buildProjection();
    this.completedProjection = projection;
    this.builderState = "complete";
    return projection;
  }

  private addReachable(record: GraphRecord): void {
    if (this.reachableSet.has(record)) return;
    if (!isWhereModel(record.model)) {
      return invalidProjection("client records cannot be reached by a selection projection");
    }
    this.reachableSet.add(record);
    this.reachableRecords.push(record);
    const relationSlots = new Map<string, RelationSlot>();
    for (const requirement of this.descriptors[record.model].relations) {
      relationSlots.set(requirement.name, {
        requirement,
        materialized: false,
        oneTarget: null,
        manyTargets: [],
      });
    }
    this.slots.set(record, relationSlots);
  }

  private buildProjection(): SelectionProjection {
    const projectedRefs = new Map<GraphRecord, GraphRecordRef>();
    for (const record of this.reachableRecords) {
      projectedRefs.set(record, createGraphRecordRef(record.ref.source, record.ref.ordinal));
    }
    const projectedRef = (record: GraphRecord): GraphRecordRef => {
      const ref = projectedRefs.get(record);
      if (ref === undefined)
        return invalidProjection("reachable projection record is missing a ref");
      return ref;
    };

    const records: ProjectionRecord[] = this.reachableRecords.map((record) => {
      const model = record.model;
      if (!isWhereModel(model)) {
        return invalidProjection("client records cannot be projected");
      }
      const descriptor = this.descriptors[model];
      const recordSlots = this.slots.get(record);
      if (recordSlots === undefined) {
        return invalidProjection("reachable projection record is missing relation slots");
      }
      const adjacency: ProjectionAdjacency[] = descriptor.relations.map((requirement) => {
        const slot = recordSlots.get(requirement.name);
        if (slot === undefined || !slot.materialized) {
          return invalidProjection("reachable projection record has incomplete adjacency");
        }
        if (requirement.cardinality === "one") {
          return Object.freeze({
            cardinality: "one",
            name: requirement.name,
            targetModel: requirement.targetModel,
            target: slot.oneTarget === null ? null : projectedRef(slot.oneTarget),
          });
        }
        return Object.freeze({
          cardinality: "many",
          name: requirement.name,
          targetModel: requirement.targetModel,
          targets: Object.freeze(slot.manyTargets.map(projectedRef)),
        });
      });
      return Object.freeze({
        ref: projectedRef(record),
        model,
        entity: cloneLogicalRef(logicalEntityForRecord(record)),
        winlink: record.winlink === null ? null : cloneWinlinkRef(record.winlink),
        scalars: projectScalars(record, descriptor),
        adjacency: Object.freeze(adjacency),
      });
    });

    const graphEntities = new Map<string, GraphEntity<LogicalRef>>();
    for (const entity of [...this.graph.sessions, ...this.graph.windows, ...this.graph.panes]) {
      graphEntities.set(logicalRefKey(entity.ref), entity);
    }
    const entities: GraphEntity<LogicalRef>[] = [];
    const seenEntities = new Set<string>();
    for (const record of this.reachableRecords) {
      const ref = logicalEntityForRecord(record);
      const key = logicalRefKey(ref);
      if (seenEntities.has(key)) continue;
      seenEntities.add(key);
      const graphEntity = graphEntities.get(key);
      if (graphEntity === undefined) {
        return invalidProjection("reachable projection entity does not exist in the graph");
      }
      const occurrences: GraphRecordRef[] = [];
      for (const occurrence of graphEntity.occurrences) {
        const occurrenceRecord = this.resolveRecord(occurrence);
        if (this.reachableSet.has(occurrenceRecord))
          occurrences.push(projectedRef(occurrenceRecord));
      }
      entities.push(
        Object.freeze({
          ref: cloneLogicalRef(graphEntity.ref),
          occurrences: Object.freeze(occurrences),
        }),
      );
    }

    const graphWinlinks = new Map<string, WinlinkEntity>();
    for (const winlink of this.graph.winlinks) {
      graphWinlinks.set(winlinkRefKey(winlink.ref), winlink);
    }
    const winlinks: WinlinkEntity[] = [];
    const seenWinlinks = new Set<string>();
    for (const record of this.reachableRecords) {
      if (record.winlink === null) continue;
      const key = winlinkRefKey(record.winlink);
      if (seenWinlinks.has(key)) continue;
      seenWinlinks.add(key);
      const graphWinlink = graphWinlinks.get(key);
      if (graphWinlink === undefined) {
        return invalidProjection("reachable projection winlink does not exist in the graph");
      }
      const occurrences: GraphRecordRef[] = [];
      for (const occurrence of graphWinlink.occurrences) {
        const occurrenceRecord = this.resolveRecord(occurrence);
        if (this.reachableSet.has(occurrenceRecord))
          occurrences.push(projectedRef(occurrenceRecord));
      }
      winlinks.push(
        Object.freeze({
          ref: cloneWinlinkRef(graphWinlink.ref),
          occurrences: Object.freeze(occurrences),
        }),
      );
    }

    const capture = Object.freeze({
      connection: this.graph.capture.connection,
      epoch: this.graph.capture.epoch,
      capabilityFingerprint: this.graph.capture.capabilityFingerprint,
    });
    const projection = Object.freeze({
      capture,
      entities: Object.freeze(entities),
      winlinks: Object.freeze(winlinks),
      records: Object.freeze(records),
      members: Object.freeze(this.rootRecords.map(projectedRef)),
    }) as unknown as SelectionProjection;
    authenticatedSelectionProjections.add(projection);
    selectionProjectionOrigins.set(projection, this.graph);
    for (const record of records) selectionProjectionRecordOwners.set(record, projection);
    return projection;
  }

  private requireCollecting(): void {
    if (this.builderState === "failed") throw this.failureCause;
    if (this.builderState === "complete") {
      return invalidProjection("selection projection is already complete");
    }
  }

  private resolveReachableSlot(source: GraphRecordRef, relation: string): RelationSlot {
    const record = this.resolveRecord(source);
    if (!this.reachableSet.has(record)) {
      return invalidProjection("projection source record is not reachable");
    }
    const slot = this.slots.get(record)?.get(relation);
    if (slot === undefined) {
      return invalidProjection("projection relation does not exist for the source record");
    }
    return slot;
  }

  private resolveRecord(ref: GraphRecordRef): GraphRecord {
    if (!graphRecordRefsEqual(ref, ref)) {
      return invalidProjection("projection record reference is not authentic");
    }
    const record = this.recordIndex.get(ref.source)?.get(ref.ordinal);
    if (record === undefined) {
      return invalidProjection("projection record does not exist in the graph");
    }
    return record;
  }
}

export function isSelectionProjection(value: unknown): value is SelectionProjection {
  return (
    typeof value === "object" && value !== null && authenticatedSelectionProjections.has(value)
  );
}

export function originGraphForSelectionProjection(value: unknown): NormalizedGraph | undefined {
  if ((typeof value !== "object" && typeof value !== "function") || value === null) {
    return undefined;
  }
  return selectionProjectionOrigins.get(value);
}

export function selectionProjectionOwnsRecord(
  projection: unknown,
  record: unknown,
): record is ProjectionRecord {
  if (
    (typeof projection !== "object" && typeof projection !== "function") ||
    projection === null ||
    (typeof record !== "object" && typeof record !== "function") ||
    record === null
  ) {
    return false;
  }
  return (
    selectionProjectionOrigins.has(projection) &&
    selectionProjectionRecordOwners.get(record) === projection
  );
}
