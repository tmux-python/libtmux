import { z } from "zod";

import { QueryValidationError } from "../../exc.js";
import type { WhereDocumentV1 } from "../../selection.js";
import { canonicalizeWhereDocument, canonicalJson } from "./compile.js";

const whereDocumentSchema = z.discriminatedUnion("model", [
  z.strictObject({
    model: z.literal("session"),
    version: z.literal(1),
    where: z.record(z.string(), z.unknown()),
  }),
  z.strictObject({
    model: z.literal("window"),
    version: z.literal(1),
    where: z.record(z.string(), z.unknown()),
  }),
  z.strictObject({
    model: z.literal("pane"),
    version: z.literal(1),
    where: z.record(z.string(), z.unknown()),
  }),
]);

function invalidDocument(cause?: unknown): never {
  throw new QueryValidationError({
    ...(cause === undefined ? {} : { cause }),
    code: "invalid-query",
    message: "Invalid WHERE document",
  });
}

function validatedDocument(input: unknown): WhereDocumentV1 {
  const document = canonicalizeWhereDocument(input);
  const result = whereDocumentSchema.safeParse(document);
  if (!result.success) return invalidDocument(result.error);
  return document;
}

export function encodeWhereDocument(document: WhereDocumentV1): string {
  return canonicalJson(validatedDocument(document) as Readonly<Record<string, unknown>>);
}

export function decodeWhereDocument(input: unknown): WhereDocumentV1 {
  return validatedDocument(input);
}
