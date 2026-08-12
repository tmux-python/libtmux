import { z } from "zod";

import type {
  PaneId,
  PaneIdInput,
  SessionId,
  SessionIdInput,
  WindowId,
  WindowIdInput,
} from "../../common.js";
import { QueryValidationError } from "../../exc.js";

const sessionIdSchema = z.string().regex(/^\$\d+$/);
const windowIdSchema = z.string().regex(/^@\d+$/);
const paneIdSchema = z.string().regex(/^%\d+$/);

function parseId<Id extends string>(schema: z.ZodType<string>, value: string, label: string): Id {
  const result = schema.safeParse(value);
  if (!result.success) {
    throw new QueryValidationError({
      cause: result.error,
      code: "invalid-id",
      message: `Invalid ${label} ID`,
    });
  }
  return result.data as Id;
}

export function parseSessionId(value: SessionIdInput): SessionId {
  return parseId<SessionId>(sessionIdSchema, value, "session");
}

export function parseWindowId(value: WindowIdInput): WindowId {
  return parseId<WindowId>(windowIdSchema, value, "window");
}

export function parsePaneId(value: PaneIdInput): PaneId {
  return parseId<PaneId>(paneIdSchema, value, "pane");
}
