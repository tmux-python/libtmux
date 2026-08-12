import { types as nodeTypes } from "node:util";

import { QueryValidationError } from "../../exc.js";
import type { WhereDocumentV1 } from "../../selection.js";

type LegacyModel = "session" | "window";

function invalidLegacyWhere(cause?: unknown): QueryValidationError {
  return new QueryValidationError({
    ...(cause === undefined ? {} : { cause }),
    code: "invalid-query",
    message: "Invalid legacy where query",
  });
}

function readLegacyValue(input: unknown): string {
  try {
    if (
      typeof input !== "object" ||
      input === null ||
      Array.isArray(input) ||
      nodeTypes.isProxy(input)
    ) {
      throw invalidLegacyWhere();
    }
    const prototype = Object.getPrototypeOf(input) as object | null;
    if (prototype !== Object.prototype && prototype !== null) throw invalidLegacyWhere();
    const keys = Reflect.ownKeys(input);
    if (keys.length !== 1 || keys[0] !== "name__contains") throw invalidLegacyWhere();
    const descriptor = Object.getOwnPropertyDescriptor(input, "name__contains");
    if (
      descriptor === undefined ||
      !descriptor.enumerable ||
      !("value" in descriptor) ||
      typeof descriptor.value !== "string"
    ) {
      throw invalidLegacyWhere();
    }
    return descriptor.value;
  } catch (error) {
    if (error instanceof QueryValidationError) throw error;
    throw invalidLegacyWhere(error);
  }
}

export function parseLegacyWhere<Model extends LegacyModel>(
  model: Model,
  input: unknown,
): Extract<WhereDocumentV1, { readonly model: Model }> {
  if (model !== "session" && model !== "window") throw invalidLegacyWhere();
  const value = readLegacyValue(input);
  const contains = Object.freeze({ contains: value });
  const where = Object.freeze({ name: contains });
  return Object.freeze({ model, version: 1, where }) as Extract<
    WhereDocumentV1,
    { readonly model: Model }
  >;
}
