import type { Client } from "../../client.js";
import type { LogicalRef } from "../../common.js";
import { LibTmuxException } from "../../exc.js";
import type { Pane } from "../../pane.js";
import type { Server } from "../../server.js";
import type { Session } from "../../session.js";
import type { Window } from "../../window.js";
import { FORMAT_FIELD_TOKENS } from "../../_generated/format_fields.js";
import type { CompleteFormatRow } from "../codec/schemas.js";
import {
  graphRecordRefsEqual,
  isNormalizedGraph,
  type GraphEntityRef,
  type GraphModel,
  type GraphRecordRef,
  type NormalizedGraph,
} from "../graph/model.js";
import type { WinlinkRef } from "../graph/refs.js";

type Child = Client | Pane | Session | Window;
type LogicalHandle = Pane | Session | Window;

export interface LiveHandleInitialization {
  readonly entity: GraphEntityRef;
  readonly graph: NormalizedGraph;
  readonly model: GraphModel;
  readonly record: GraphRecordRef;
  readonly server: Server;
  readonly snapshot: CompleteFormatRow;
  readonly winlink: WinlinkRef | null;
}

type LiveHandleState = LiveHandleInitialization;

const liveHandleStates = new WeakMap<object, LiveHandleState>();
const installedPrototypes = new WeakSet<object>();

function stateForValue(value: unknown): LiveHandleState | undefined {
  if ((typeof value !== "object" && typeof value !== "function") || value === null) {
    return undefined;
  }
  return liveHandleStates.get(value);
}

function requireState(value: unknown): LiveHandleState {
  const state = stateForValue(value);
  if (state === undefined) throw new LibTmuxException("handle is not authentic");
  return state;
}

function requireAuthenticProvenance(graph: NormalizedGraph, record: GraphRecordRef): void {
  if (
    !isNormalizedGraph(graph) ||
    !graphRecordRefsEqual(record, record) ||
    !graph.records.some((candidate) => graphRecordRefsEqual(candidate.ref, record))
  ) {
    throw new LibTmuxException("handle provenance is not authentic");
  }
}

function freezeState(initialization: LiveHandleInitialization): LiveHandleState {
  return Object.freeze({
    entity: initialization.entity,
    graph: initialization.graph,
    model: initialization.model,
    record: initialization.record,
    server: initialization.server,
    snapshot: initialization.snapshot,
    winlink: initialization.winlink,
  });
}

export function installLiveHandlePrototype(prototype: object): void {
  if (installedPrototypes.has(prototype)) return;

  Object.defineProperty(prototype, "server", {
    configurable: false,
    enumerable: false,
    get(this: object): Server {
      return requireState(this).server;
    },
  });
  for (const token of FORMAT_FIELD_TOKENS) {
    Object.defineProperty(prototype, token, {
      configurable: false,
      enumerable: false,
      get(this: object): string | null {
        return requireState(this).snapshot[token];
      },
    });
  }
  installedPrototypes.add(prototype);
}

export function initializeLiveHandle<Handle extends Child>(
  handle: Handle,
  initialization: LiveHandleInitialization,
): Handle {
  if (liveHandleStates.has(handle)) {
    throw new LibTmuxException("handle is already initialized");
  }
  if (initialization.entity.kind !== initialization.model) {
    throw new LibTmuxException("handle model does not match its entity");
  }
  requireAuthenticProvenance(initialization.graph, initialization.record);
  const state = freezeState(initialization);
  liveHandleStates.set(handle, state);
  Object.freeze(handle);
  return handle;
}

export function liveHandleStateForReplacement(handle: Child): LiveHandleInitialization {
  return requireState(handle);
}

export function compareAndSwapLiveHandleState(
  handle: Child,
  expected: LiveHandleInitialization,
  graph: NormalizedGraph,
  record: GraphRecordRef,
  snapshot: CompleteFormatRow,
  winlink: WinlinkRef | null,
): void {
  const current = requireState(handle);
  if (current !== expected) {
    throw new LibTmuxException("handle state changed while replacement was pending");
  }
  requireAuthenticProvenance(graph, record);
  liveHandleStates.set(
    handle,
    freezeState({
      entity: current.entity,
      graph,
      model: current.model,
      record,
      server: current.server,
      snapshot,
      winlink,
    }),
  );
}

export function liveHandlesEqual(left: Child, other: unknown): boolean {
  const leftState = stateForValue(left);
  const rightState = stateForValue(other);
  if (leftState === undefined || rightState === undefined || leftState.model !== rightState.model) {
    return false;
  }
  if (leftState.model !== "client") {
    return leftState.entity.id === rightState.entity.id;
  }
  if (!leftState.server.equals(rightState.server)) return false;
  for (const token of FORMAT_FIELD_TOKENS) {
    if (leftState.snapshot[token] !== rightState.snapshot[token]) return false;
  }
  return true;
}

export function entityRefForHandle(handle: Child): GraphEntityRef {
  return requireState(handle).entity;
}

export function originGraphForHandle(handle: Child): NormalizedGraph {
  return requireState(handle).graph;
}

export function graphRecordRefForHandle(handle: Child): GraphRecordRef {
  return requireState(handle).record;
}

export function logicalRefForHandle(handle: LogicalHandle): LogicalRef {
  const entity = requireState(handle).entity;
  if (entity.kind === "client") throw new LibTmuxException("Client has no logical reference");
  return entity;
}

export function snapshotForHandle(handle: Child): CompleteFormatRow {
  return requireState(handle).snapshot;
}

export function winlinkRefForHandle(handle: Child): WinlinkRef | null {
  return requireState(handle).winlink;
}
