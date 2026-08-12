import { NodeSpawnTransport } from "../../src/_internal/transport/node_spawn_transport.js";

export const DIFFERENTIAL_PROTOCOL = "libtmux-differential-v1" as const;

export interface DifferentialRequest {
  readonly operation: "list-sessions";
  readonly protocol: typeof DIFFERENTIAL_PROTOCOL;
  readonly requestId: string;
  readonly socketPath: string;
}

export interface DifferentialResponse {
  readonly diagnostics: readonly string[];
  readonly implementation: "python-0.62.0" | "raw-tmux";
  readonly protocol: typeof DIFFERENTIAL_PROTOCOL;
  readonly requestId: string;
  readonly returncode: number;
  readonly semantics: { readonly sessions: readonly string[] };
  readonly stderrBase64: string;
  readonly stdoutBase64: string;
}

const responseKeys = [
  "diagnostics",
  "implementation",
  "protocol",
  "requestId",
  "returncode",
  "semantics",
  "stderrBase64",
  "stdoutBase64",
] as const;

function isCanonicalBase64(value: string): boolean {
  return Buffer.from(value, "base64").toString("base64") === value;
}

function validateResponse(
  value: unknown,
  expectedRequestId: string,
  expectedImplementation: DifferentialResponse["implementation"],
): DifferentialResponse {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("differential response must be an object");
  }
  const candidate = value as Record<string, unknown>;
  if (JSON.stringify(Object.keys(candidate).sort()) !== JSON.stringify([...responseKeys].sort())) {
    throw new Error("differential response has invalid fields");
  }
  if (candidate.protocol !== DIFFERENTIAL_PROTOCOL) {
    throw new Error("differential response has the wrong protocol");
  }
  if (candidate.implementation !== expectedImplementation) {
    throw new Error("differential response has the wrong implementation");
  }
  if (typeof candidate.requestId !== "string" || candidate.requestId !== expectedRequestId) {
    throw new Error("differential response requestId is not correlated");
  }
  if (!Number.isSafeInteger(candidate.returncode)) {
    throw new Error("differential response returncode is invalid");
  }
  if (
    !Array.isArray(candidate.diagnostics) ||
    !candidate.diagnostics.every((item) => typeof item === "string")
  ) {
    throw new Error("differential response diagnostics are invalid");
  }
  const semantics = candidate.semantics;
  if (
    typeof semantics !== "object" ||
    semantics === null ||
    Array.isArray(semantics) ||
    JSON.stringify(Object.keys(semantics).sort()) !== JSON.stringify(["sessions"]) ||
    !Array.isArray((semantics as Record<string, unknown>).sessions) ||
    !((semantics as Record<string, unknown>).sessions as unknown[]).every(
      (item) => typeof item === "string",
    )
  ) {
    throw new Error("differential response semantics are invalid");
  }
  if (
    typeof candidate.stdoutBase64 !== "string" ||
    !isCanonicalBase64(candidate.stdoutBase64) ||
    typeof candidate.stderrBase64 !== "string" ||
    !isCanonicalBase64(candidate.stderrBase64)
  ) {
    throw new Error("differential response byte fields are not canonical base64");
  }
  return candidate as unknown as DifferentialResponse;
}

export function decodeDifferentialResponse(
  frame: string,
  expectedRequestId: string,
  expectedImplementation: DifferentialResponse["implementation"],
): DifferentialResponse {
  if (!frame.endsWith("\n") || frame.indexOf("\n") !== frame.length - 1) {
    throw new Error("differential response must be exactly one newline-terminated frame");
  }
  let value: unknown;
  try {
    value = JSON.parse(frame.slice(0, -1));
  } catch (error) {
    throw new Error("differential response is invalid JSON", { cause: error });
  }
  return validateResponse(value, expectedRequestId, expectedImplementation);
}

export function encodeDifferentialResponse(response: DifferentialResponse): string {
  const validated = validateResponse(response, response.requestId, response.implementation);
  return `${JSON.stringify(validated)}\n`;
}

function validateRequest(request: unknown): asserts request is DifferentialRequest {
  if (typeof request !== "object" || request === null || Array.isArray(request)) {
    throw new Error("differential request must be an object");
  }
  const candidate = request as Record<string, unknown>;
  const keys = Object.keys(candidate).sort();
  if (
    JSON.stringify(keys) !== JSON.stringify(["operation", "protocol", "requestId", "socketPath"])
  ) {
    throw new Error("differential request has invalid fields");
  }
  if (typeof candidate.requestId !== "string")
    throw new Error("differential requestId must be a string");
  if (typeof candidate.socketPath !== "string")
    throw new Error("differential socketPath must be a string");
  if (candidate.protocol !== DIFFERENTIAL_PROTOCOL)
    throw new Error("unsupported differential protocol");
  if (candidate.operation !== "list-sessions")
    throw new Error("unsupported differential operation");
  if (candidate.requestId === "") throw new Error("differential requestId must not be empty");
  if (candidate.socketPath === "") throw new Error("differential socketPath must not be empty");
}

export async function queryRawTmux(request: DifferentialRequest): Promise<DifferentialResponse> {
  validateRequest(request);
  const submitted = Object.freeze({
    operation: request.operation,
    protocol: request.protocol,
    requestId: request.requestId,
    socketPath: request.socketPath,
  });
  const result = await new NodeSpawnTransport().execute({
    args: ["-S", submitted.socketPath, "list-sessions", "-F", "#{session_name}"],
    executable: "tmux",
    timeoutMs: 3_000,
  });
  const stdout = new TextDecoder().decode(result.stdout);
  const sessions = stdout
    .split("\n")
    .filter((line) => line !== "")
    .sort();
  const response = Object.freeze({
    diagnostics: Object.freeze(
      result.returncode === 0 ? [] : [new TextDecoder().decode(result.stderr).trim()],
    ),
    implementation: "raw-tmux" as const,
    protocol: DIFFERENTIAL_PROTOCOL,
    requestId: submitted.requestId,
    returncode: result.returncode,
    semantics: Object.freeze({ sessions: Object.freeze(sessions) }),
    stderrBase64: Buffer.from(result.stderr).toString("base64"),
    stdoutBase64: Buffer.from(result.stdout).toString("base64"),
  });
  return decodeDifferentialResponse(
    encodeDifferentialResponse(response),
    submitted.requestId,
    "raw-tmux",
  );
}
