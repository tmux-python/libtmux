import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

import { FORMAT_FIELD_TOKENS } from "../../dist/_generated/format_fields.js";
import { WHERE_FIELDS_V1, WHERE_RELATIONS_V1 } from "../../dist/_generated/where_fields.js";
import { createGraphSourceId } from "../../dist/_internal/graph/model.js";
import { materializeProjectionMembers } from "../../dist/_internal/graph/materialize.js";
import { normalizeGraph } from "../../dist/_internal/graph/normalize.js";
import { SelectionProjectionBuilder } from "../../dist/_internal/graph/selection_projection.js";
import {
  createRuntimeContext,
  createServerWithRuntime,
} from "../../dist/_internal/runtime/context.js";
import { TmuxConnection } from "../../dist/_internal/runtime/connection.js";
import { createProjectedSelection } from "../../dist/_internal/selection/evaluate.js";

const protocol = "libtmux-where-regex-v1";
const implementation = process.argv[2];
assert.ok(implementation === "bun" || implementation === "node");
if (implementation === "bun") {
  assert.equal(process.versions.bun, "1.3.14");
} else {
  assert.equal(process.versions.bun, undefined);
  assert.equal(process.versions.node.split(".")[0], "22");
}

const fixture = JSON.parse(await readFile(new URL("./where_regex.json", import.meta.url), "utf8"));
assert.equal(fixture.protocol, protocol);
assert.deepEqual(fixture.runtimes, { bun: "1.3.14", node: "22", python: "3" });
const requiredSharedAdaptations = {
  "native-multiline-line-feed":
    "All three pinned native engines recognize LF as a multiline anchor boundary.",
  "native-unicode-astral-dot":
    "ECMAScript internal Unicode mode and Python native Unicode matching consume one astral code point for dot.",
};
for (const [name, description] of Object.entries(requiredSharedAdaptations)) {
  assert.equal(fixture.adaptations[name], description);
}
assert.ok(Array.isArray(fixture.cases));
assert.equal(fixture.cases.length, 19);
assert.equal(new Set(fixture.cases.map(({ session_id }) => session_id)).size, fixture.cases.length);
for (const entry of fixture.cases) assert.match(entry.session_id, /^\$\d+$/u);
assert.equal(
  fixture.cases.find(({ id }) => id === "astral-dot-unicode")?.adaptation,
  "native-unicode-astral-dot",
);
assert.equal(
  fixture.cases.find(({ id }) => id === "lf-multiline-parity")?.adaptation,
  "native-multiline-line-feed",
);

function completeRow(overrides) {
  return Object.assign(
    Object.fromEntries(FORMAT_FIELD_TOKENS.map((token) => [token, null])),
    overrides,
  );
}

const requests = [];
const transport = {
  requests,
  async execute(request) {
    requests.push(request);
    return {
      cmd: Object.freeze([request.executable, ...request.args]),
      returncode: 0,
      signal: null,
      stderr: new Uint8Array(),
      stdout: new TextEncoder().encode("3.7b\n"),
    };
  },
};
const runtime = createRuntimeContext({
  connection: new TmuxConnection({ executable: "tmux", socketName: "where-regex-runtime" }),
  connectionAlias: "where-regex-runtime",
  daemonEpoch: 0,
  transport,
});
const capabilities = await runtime.capabilities.bind();
const source = createGraphSourceId("where-regex-sessions");
const graph = normalizeGraph({
  capture: {
    capabilityFingerprint: capabilities.fingerprint,
    connection: runtime.connectionAlias,
    epoch: runtime.daemonEpoch,
  },
  sources: [
    {
      listCommand: "list-sessions",
      rows: fixture.cases.map((entry) =>
        completeRow({
          session_id: entry.session_id,
          session_name: entry.input,
        }),
      ),
      source,
    },
  ],
});
const builder = SelectionProjectionBuilder.create({
  descriptors: {
    pane: {
      fields: WHERE_FIELDS_V1.pane,
      model: "pane",
      relations: WHERE_RELATIONS_V1.pane,
    },
    session: {
      fields: WHERE_FIELDS_V1.session,
      model: "session",
      relations: WHERE_RELATIONS_V1.session,
    },
    window: {
      fields: WHERE_FIELDS_V1.window,
      model: "window",
      relations: WHERE_RELATIONS_V1.window,
    },
  },
  graph,
  source,
});
for (const member of graph.sources[0].records) {
  builder.materializeMany(member, "windows", []);
  builder.materializeMany(member, "panes", []);
  builder.materializeOne(member, "activeWindow", null);
  builder.materializeOne(member, "activePane", null);
}
const projection = builder.seal();
const values = await materializeProjectionMembers(
  createServerWithRuntime(runtime),
  projection,
  graph,
);
const selection = createProjectedSelection("session", values, projection);
const requestCount = requests.length;
const observations = fixture.cases.map((entry) => {
  const name = {
    equals: entry.input,
    regex: { flags: entry.flags, pattern: entry.pattern },
    ...(entry.mode === "insensitive" ? { mode: "insensitive" } : {}),
  };
  const matched = selection.count({ name, id: entry.session_id }) === 1;
  assert.equal(matched, entry.expected[implementation], entry.id);
  return { id: entry.id, matched };
});
const combined = fixture.cases.find(({ id }) => id === "multiline-dotall-open-quantifier");
assert.ok(combined);
const countCombined = (flags, pattern = combined.pattern) =>
  selection.count({
    name: {
      equals: combined.input,
      regex: { flags, pattern },
    },
    id: combined.session_id,
  });
assert.equal(countCombined("ms"), 1);
assert.equal(countCombined("m"), 0);
assert.equal(countCombined("s"), 0);
const unsatisfiedLowerBound = combined.pattern.replace("{2,}", "{4,}");
assert.notEqual(unsatisfiedLowerBound, combined.pattern);
assert.equal(countCombined("ms", unsatisfiedLowerBound), 0);
assert.equal(requests.length, requestCount);

process.stdout.write(
  `${JSON.stringify({
    cases: observations,
    implementation: `${implementation}-native-regexp`,
    protocol,
    runtime: implementation === "bun" ? process.versions.bun : process.versions.node,
    status: "passed",
  })}\n`,
);
