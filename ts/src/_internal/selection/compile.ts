import { types as nodeTypes } from "node:util";

import {
  WHERE_FIELDS_V1,
  WHERE_RELATIONS_V1,
  type WhereModel,
  type WhereRelation,
} from "../../_generated/where_fields.js";
import { QueryValidationError } from "../../exc.js";
import type { WhereDocumentV1 } from "../../selection.js";
import type { GraphRecordRef } from "../graph/model.js";
import type { ProjectionRecord } from "../graph/selection_projection.js";

type RecordResolver = (reference: GraphRecordRef) => ProjectionRecord | undefined;
type RecordPredicate = (record: ProjectionRecord, resolve: RecordResolver) => boolean;

interface ParsedCriteria {
  readonly query: Readonly<Record<string, unknown>>;
  readonly test: RecordPredicate;
}

interface ParsedScalar {
  readonly query: string | null | Readonly<Record<string, unknown>>;
  readonly test: (value: string | null) => boolean;
}

interface ParseState {
  readonly active: WeakSet<object>;
}

export interface CompiledWhere {
  readonly model: WhereModel;
  readonly query: Readonly<Record<string, unknown>>;
  matches(record: ProjectionRecord, resolve: RecordResolver): boolean;
}

const logicalNames = Object.freeze(["AND", "NOT", "OR"] as const);
const scalarOperatorNames = Object.freeze([
  "contains",
  "endsWith",
  "equals",
  "in",
  "mode",
  "notIn",
  "regex",
  "startsWith",
] as const);
const regexFlags = new Set(["", "m", "s", "ms"]);
const escapedRegexLiterals = new Set("^$\\.*+?()[]{}|/-".split(""));
const maximumWhereDepth = 64;
const maximumCanonicalJsonDepth = maximumWhereDepth * 2 + 4;

function invalidQuery(cause?: unknown): never {
  throw new QueryValidationError({
    ...(cause === undefined ? {} : { cause }),
    code: "invalid-query",
    message: "Invalid selection query",
  });
}

function isObject(value: unknown): value is object {
  return (typeof value === "object" || typeof value === "function") && value !== null;
}

function withActive<Value>(value: object, state: ParseState, read: () => Value): Value {
  if (state.active.has(value)) return invalidQuery();
  state.active.add(value);
  try {
    return read();
  } finally {
    state.active.delete(value);
  }
}

function snapshotObject(value: unknown): ReadonlyMap<string, unknown> {
  if (!isObject(value) || typeof value === "function") return invalidQuery();
  try {
    if (nodeTypes.isProxy(value) || Array.isArray(value)) return invalidQuery();
    const prototype = Object.getPrototypeOf(value) as object | null;
    if (prototype !== Object.prototype && prototype !== null) return invalidQuery();
    const keys = Reflect.ownKeys(value);
    if (keys.some((key) => typeof key !== "string")) return invalidQuery();
    const entries: Array<readonly [string, unknown]> = [];
    for (const key of keys) {
      if (typeof key !== "string") return invalidQuery();
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
        return invalidQuery();
      }
      entries.push([key, descriptor.value]);
    }
    return new Map(entries);
  } catch (error) {
    if (error instanceof QueryValidationError) throw error;
    return invalidQuery(error);
  }
}

function snapshotArray(value: unknown): readonly unknown[] {
  if (!isObject(value) || typeof value === "function") return invalidQuery();
  try {
    if (nodeTypes.isProxy(value) || !Array.isArray(value)) return invalidQuery();
    if (Object.getPrototypeOf(value) !== Array.prototype) return invalidQuery();
    const lengthDescriptor = Object.getOwnPropertyDescriptor(value, "length");
    if (
      lengthDescriptor === undefined ||
      !("value" in lengthDescriptor) ||
      lengthDescriptor.enumerable ||
      typeof lengthDescriptor.value !== "number" ||
      !Number.isSafeInteger(lengthDescriptor.value) ||
      lengthDescriptor.value < 0
    ) {
      return invalidQuery();
    }
    const length = lengthDescriptor.value;
    const keys = Reflect.ownKeys(value);
    if (keys.length !== length + 1 || !keys.includes("length")) return invalidQuery();
    const result: unknown[] = [];
    for (let index = 0; index < length; index += 1) {
      const key = String(index);
      if (!keys.includes(key)) return invalidQuery();
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (descriptor === undefined || !descriptor.enumerable || !("value" in descriptor)) {
        return invalidQuery();
      }
      result.push(descriptor.value);
    }
    return result;
  } catch (error) {
    if (error instanceof QueryValidationError) throw error;
    return invalidQuery(error);
  }
}

function frozenRecord(
  entries: readonly (readonly [string, unknown])[],
): Readonly<Record<string, unknown>> {
  return Object.freeze(
    Object.fromEntries(
      [...entries].sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)),
    ),
  );
}

function frozenArray(values: readonly unknown[]): readonly unknown[] {
  return Object.freeze([...values]);
}

function relationFor(model: WhereModel, name: string): WhereRelation | undefined {
  return WHERE_RELATIONS_V1[model].find((relation) => relation.name === name);
}

function scalarNamesFor(model: WhereModel): ReadonlySet<string> {
  return new Set(WHERE_FIELDS_V1[model].map(({ wireName }) => wireName));
}

function validateRegexPattern(pattern: string): void {
  let groupDepth = 0;
  let inClass = false;
  let classContent = 0;
  let canQuantify = false;

  for (let index = 0; index < pattern.length; index += 1) {
    const character = pattern[index];
    if (character === undefined) return invalidQuery();

    if (character === "\\") {
      const escaped = pattern[index + 1];
      if (escaped === undefined || !escapedRegexLiterals.has(escaped)) return invalidQuery();
      index += 1;
      if (inClass) classContent += 1;
      canQuantify = true;
      continue;
    }

    if (inClass) {
      const code = character.codePointAt(0);
      if (code === undefined || code < 0x20 || code > 0x7e || character === "[") {
        return invalidQuery();
      }
      if (classContent === 0 && character === "^") return invalidQuery();
      if (character === "]") {
        if (classContent === 0) return invalidQuery();
        inClass = false;
        canQuantify = true;
        continue;
      }
      if (
        (character === "&" && pattern[index + 1] === "&") ||
        (character === "-" && pattern[index + 1] === "-")
      ) {
        return invalidQuery();
      }
      classContent += 1;
      continue;
    }

    if (character === "[") {
      inClass = true;
      classContent = 0;
      canQuantify = false;
      continue;
    }
    if (character === "]" || character === "}") return invalidQuery();
    if (character === "(") {
      if (pattern[index + 1] === "?") {
        if (pattern[index + 2] !== ":") return invalidQuery();
        index += 2;
      }
      groupDepth += 1;
      canQuantify = false;
      continue;
    }
    if (character === ")") {
      if (groupDepth === 0) return invalidQuery();
      groupDepth -= 1;
      canQuantify = true;
      continue;
    }
    if (character === "{") {
      if (!canQuantify) return invalidQuery();
      const remainder = pattern.slice(index);
      const match = /^\{\d+(?:,\d*)?\}/u.exec(remainder);
      if (match === null) return invalidQuery();
      const next = pattern[index + match[0].length];
      if (next === "?" || next === "+") return invalidQuery();
      index += match[0].length - 1;
      canQuantify = false;
      continue;
    }
    if (character === "*" || character === "+" || character === "?") {
      if (!canQuantify || pattern[index + 1] === "?" || pattern[index + 1] === "+") {
        return invalidQuery();
      }
      canQuantify = false;
      continue;
    }
    if (character === "|") {
      canQuantify = false;
      continue;
    }
    if (character === "^" || character === "$") {
      canQuantify = false;
      continue;
    }
    if (character.codePointAt(0) !== undefined && character.codePointAt(0)! < 0x20) {
      return invalidQuery();
    }
    canQuantify = true;
  }

  if (inClass || groupDepth !== 0) return invalidQuery();
}

function compileRegex(pattern: string, flags: string, insensitive: boolean): RegExp {
  validateRegexPattern(pattern);
  try {
    return new RegExp(pattern, `${flags}${insensitive ? "iu" : "u"}`);
  } catch (error) {
    return invalidQuery(error);
  }
}

function parseStringArray(value: unknown, state: ParseState): readonly string[] {
  if (!isObject(value)) return invalidQuery();
  return withActive(value, state, () => {
    const values = snapshotArray(value);
    if (!values.every((entry) => typeof entry === "string")) return invalidQuery();
    return Object.freeze([...values]) as readonly string[];
  });
}

function parseRegex(
  value: unknown,
  insensitive: boolean,
  state: ParseState,
): { readonly query: Readonly<Record<string, unknown>>; readonly regex: RegExp } {
  if (!isObject(value)) return invalidQuery();
  return withActive(value, state, () => {
    const record = snapshotObject(value);
    if (record.size !== 2 || !record.has("flags") || !record.has("pattern")) {
      return invalidQuery();
    }
    const flags = record.get("flags");
    const pattern = record.get("pattern");
    if (typeof flags !== "string" || !regexFlags.has(flags) || typeof pattern !== "string") {
      return invalidQuery();
    }
    return {
      query: frozenRecord([
        ["flags", flags],
        ["pattern", pattern],
      ]),
      regex: compileRegex(pattern, flags, insensitive),
    };
  });
}

function parseScalar(value: unknown, state: ParseState): ParsedScalar {
  if (typeof value === "string" || value === null) {
    return { query: value, test: (candidate) => candidate === value };
  }
  if (!isObject(value)) return invalidQuery();

  return withActive(value, state, () => {
    const record = snapshotObject(value);
    if (
      record.size === 0 ||
      [...record.keys()].some((key) => !scalarOperatorNames.includes(key as never))
    ) {
      return invalidQuery();
    }
    const mode = record.get("mode");
    if (record.has("mode") && mode !== "insensitive") return invalidQuery();
    if ([...record.keys()].every((key) => key === "mode")) return invalidQuery();
    const insensitive = mode === "insensitive";
    const queryEntries: Array<readonly [string, unknown]> = [];
    const operations: Array<(candidate: string | null) => boolean> = [];

    for (const [name, operand] of record) {
      if (name === "mode") {
        queryEntries.push([name, mode]);
        continue;
      }
      if (name === "equals") {
        if (typeof operand !== "string" && operand !== null) return invalidQuery();
        queryEntries.push([name, operand]);
        operations.push((candidate) => {
          if (candidate === null || operand === null) return candidate === operand;
          return insensitive
            ? candidate.toLowerCase() === operand.toLowerCase()
            : candidate === operand;
        });
        continue;
      }
      if (name === "contains" || name === "startsWith" || name === "endsWith") {
        if (typeof operand !== "string") return invalidQuery();
        queryEntries.push([name, operand]);
        operations.push((candidate) => {
          if (candidate === null) return false;
          const left = insensitive ? candidate.toLowerCase() : candidate;
          const right = insensitive ? operand.toLowerCase() : operand;
          if (name === "contains") return left.includes(right);
          if (name === "startsWith") return left.startsWith(right);
          return left.endsWith(right);
        });
        continue;
      }
      if (name === "in" || name === "notIn") {
        const values = parseStringArray(operand, state);
        queryEntries.push([name, values]);
        const comparable = insensitive ? values.map((entry) => entry.toLowerCase()) : values;
        operations.push((candidate) => {
          if (candidate === null) return false;
          const present = comparable.includes(insensitive ? candidate.toLowerCase() : candidate);
          return name === "in" ? present : !present;
        });
        continue;
      }
      if (name === "regex") {
        const parsed = parseRegex(operand, insensitive, state);
        queryEntries.push([name, parsed.query]);
        operations.push((candidate) => candidate !== null && parsed.regex.test(candidate));
        continue;
      }
      return invalidQuery();
    }

    return {
      query: frozenRecord(queryEntries),
      test: (candidate) => operations.every((operation) => operation(candidate)),
    };
  });
}

function findAdjacency(record: ProjectionRecord, relation: WhereRelation) {
  return record.adjacency.find(
    (candidate) =>
      candidate.name === relation.name &&
      candidate.cardinality === relation.cardinality &&
      candidate.targetModel === relation.targetModel,
  );
}

function parseManyRelation(
  relation: WhereRelation,
  value: unknown,
  state: ParseState,
  depth: number,
): { readonly query: Readonly<Record<string, unknown>>; readonly test: RecordPredicate } {
  if (!isObject(value)) return invalidQuery();
  return withActive(value, state, () => {
    const record = snapshotObject(value);
    if (
      record.size === 0 ||
      [...record.keys()].some((key) => key !== "some" && key !== "every" && key !== "none")
    ) {
      return invalidQuery();
    }
    const entries: Array<readonly [string, unknown]> = [];
    const operations: Array<{
      readonly name: string;
      readonly parsed: ParsedCriteria;
    }> = [];
    for (const [name, child] of record) {
      const parsed = parseCriteria(relation.targetModel, child, state, depth + 1);
      entries.push([name, parsed.query]);
      operations.push({ name, parsed });
    }
    return {
      query: frozenRecord(entries),
      test: (source, resolve) => {
        const adjacency = findAdjacency(source, relation);
        if (adjacency === undefined || adjacency.cardinality !== "many") return false;
        const targets = adjacency.targets.map(resolve);
        if (targets.some((target) => target === undefined)) return false;
        return operations.every(({ name, parsed }) => {
          const matches = (target: ProjectionRecord | undefined): boolean =>
            target !== undefined && parsed.test(target, resolve);
          if (name === "some") return targets.some(matches);
          if (name === "every") return targets.every(matches);
          return targets.every((target) => !matches(target));
        });
      },
    };
  });
}

function parseOneRelation(
  relation: WhereRelation,
  value: unknown,
  state: ParseState,
  depth: number,
): { readonly query: Readonly<Record<string, unknown>>; readonly test: RecordPredicate } {
  if (!isObject(value)) return invalidQuery();
  return withActive(value, state, () => {
    const record = snapshotObject(value);
    if (record.size === 0 || [...record.keys()].some((key) => key !== "is" && key !== "isNot")) {
      return invalidQuery();
    }
    const entries: Array<readonly [string, unknown]> = [];
    const operations: Array<{
      readonly name: string;
      readonly parsed: ParsedCriteria | null;
    }> = [];
    for (const [name, child] of record) {
      const parsed =
        child === null ? null : parseCriteria(relation.targetModel, child, state, depth + 1);
      entries.push([name, parsed?.query ?? null]);
      operations.push({ name, parsed });
    }
    return {
      query: frozenRecord(entries),
      test: (source, resolve) => {
        const adjacency = findAdjacency(source, relation);
        if (adjacency === undefined || adjacency.cardinality !== "one") return false;
        const target = adjacency.target === null ? null : resolve(adjacency.target);
        if (target === undefined) return false;
        return operations.every(({ name, parsed }) => {
          const matches =
            parsed === null ? target === null : target !== null && parsed.test(target, resolve);
          return name === "is" ? matches : !matches;
        });
      },
    };
  });
}

function parseCriteria(
  model: WhereModel,
  value: unknown,
  state: ParseState,
  depth = 0,
): ParsedCriteria {
  if (depth > maximumWhereDepth || !isObject(value)) return invalidQuery();
  return withActive(value, state, () => {
    const record = snapshotObject(value);
    const scalarNames = scalarNamesFor(model);
    const entries: Array<readonly [string, unknown]> = [];
    const predicates: RecordPredicate[] = [];

    for (const [name, criterion] of record) {
      if (scalarNames.has(name)) {
        const parsed = parseScalar(criterion, state);
        entries.push([name, parsed.query]);
        predicates.push((source) => parsed.test(source.scalars[name] ?? null));
        continue;
      }
      if (logicalNames.includes(name as never)) {
        if (!isObject(criterion)) return invalidQuery();
        const children = withActive(criterion, state, () =>
          snapshotArray(criterion).map((child) => parseCriteria(model, child, state, depth + 1)),
        );
        entries.push([name, frozenArray(children.map(({ query }) => query))]);
        if (name === "AND") {
          predicates.push((source, resolve) => children.every(({ test }) => test(source, resolve)));
        } else if (name === "OR") {
          predicates.push((source, resolve) => children.some(({ test }) => test(source, resolve)));
        } else {
          predicates.push((source, resolve) =>
            children.every(({ test }) => !test(source, resolve)),
          );
        }
        continue;
      }
      const relation = relationFor(model, name);
      if (relation === undefined) return invalidQuery();
      const parsed =
        relation.cardinality === "many"
          ? parseManyRelation(relation, criterion, state, depth)
          : parseOneRelation(relation, criterion, state, depth);
      entries.push([name, parsed.query]);
      predicates.push(parsed.test);
    }

    return {
      query: frozenRecord(entries),
      test: (source, resolve) => predicates.every((predicate) => predicate(source, resolve)),
    };
  });
}

function parseModel(value: unknown): WhereModel {
  if (value !== "session" && value !== "window" && value !== "pane") return invalidQuery();
  return value;
}

export function canonicalizeWhere(
  model: WhereModel,
  criteria: unknown,
): Readonly<Record<string, unknown>> {
  return parseCriteria(parseModel(model), criteria, { active: new WeakSet() }).query;
}

export function compileWhere(model: WhereModel, criteria: unknown): CompiledWhere {
  const parsedModel = parseModel(model);
  const parsed = parseCriteria(parsedModel, criteria, { active: new WeakSet() });
  return Object.freeze({
    model: parsedModel,
    query: parsed.query,
    matches(record: ProjectionRecord, resolve: RecordResolver): boolean {
      return record.model === parsedModel && parsed.test(record, resolve);
    },
  });
}

export function canonicalizeWhereDocument(input: unknown): WhereDocumentV1 {
  const envelope = snapshotObject(input);
  if (
    envelope.size !== 3 ||
    !envelope.has("model") ||
    !envelope.has("version") ||
    !envelope.has("where") ||
    envelope.get("version") !== 1
  ) {
    return invalidQuery();
  }
  const model = parseModel(envelope.get("model"));
  const where = canonicalizeWhere(model, envelope.get("where"));
  return Object.freeze({ model, version: 1, where }) as WhereDocumentV1;
}

function jsonString(value: string): string {
  const encoded = JSON.stringify(value);
  return encoded === undefined ? invalidQuery() : encoded;
}

function canonicalJsonValue(value: unknown, depth: number): string {
  if (value === null) return "null";
  if (typeof value === "string") return jsonString(value);
  if (typeof value === "boolean") return String(value);
  if (typeof value === "number") return Number.isFinite(value) ? String(value) : "null";
  if (depth > maximumCanonicalJsonDepth || !isObject(value) || typeof value === "function") {
    return invalidQuery();
  }
  if (Array.isArray(value)) {
    return `[${snapshotArray(value)
      .map((entry) => canonicalJsonValue(entry, depth + 1))
      .join(",")}]`;
  }
  return `{${[...snapshotObject(value)]
    .sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0))
    .map(([key, entry]) => `${jsonString(key)}:${canonicalJsonValue(entry, depth + 1)}`)
    .join(",")}}`;
}

export function canonicalJson(value: Readonly<Record<string, unknown>>): string {
  return canonicalJsonValue(value, 0);
}
