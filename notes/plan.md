# Plan

## Target outcome

A tiered PNPM monorepo under `astro/` that powers a rebuilt libtmux docs site in
Astro + Tailwind, and a reusable autodoc engine that matches Sphinx autodoc
where it matters (imports, signatures, docstrings, annotations, members,
inheritance, and intersphinx URL resolution).

## Non-negotiables

- Hybrid pipeline with schema firewall: TypeScript orchestrates, Python owns
  semantics, Zod enforces contracts.
- Deterministic output, stable IDs, and cacheable artifacts.
- Intersphinx inventories supported end-to-end.
- Astro integration must be flexible: the user authors pages; components provide
  the building blocks.

## Phased build plan

1. Scaffold `astro/` workspace and enforce house rules (Biome, Vitest workspace,
   `update:all`, `ncu`, `type-check`, `biome`, `test`, `build`).
2. Define `schema` package:
   - `protocolVersion` on all payloads
   - stable IDs and anchors
   - error shapes and source spans
   - docstring + annotation channels
3. Implement Python sidecar package (`astro/python/pyautodoc_sidecar`):
   - `parse-files` (ast-based static parse)
   - `introspect-module` and `introspect-package` (inspect, annotations)
   - RST docstring rendering via docutils
   - import mocking, timeouts, and structured failures
4. Implement `py-bridge` to spawn Python via `uv run` and validate output with
   Zod; support `uvx` as an optional tool mode.
5. Implement `py-parse` and `py-introspect` TS wrappers, with unit tests.
6. Build `api-model` with stable ordering and snapshot coverage; output a single
   `api-index.json` artifact.
7. Build `core` orchestration (scan, parse, introspect, build index, cache).
8. Build `astro-autodoc` integration and components, including a virtual module
   and API page generation helpers.
9. Build `intersphinx` parser and `astro-intersphinx` integration.
10. Rebuild the docs site layout in Astro and migrate prose content
    incrementally.

## Testing and QA

- Vitest workspace split:
  - unit tests never spawn Python
  - one integration test exercises `uv run` for introspection
  - snapshot normalization (stable ordering, scrub absolute paths)
- Astro integration gets a single build smoke test.
- CI runs `type-check`, `biome`, `test`, and `build`.

## Risks and mitigations

- Import side effects: default to `annotationFormat=STRING`, support mock
  modules, and enforce timeouts.
- Non-determinism: stable ordering, stable IDs, and cache invalidation rules.
- Docstring formats: store raw, format, and rendered HTML; keep rendering in
  Python.
- Type fidelity: preserve `annotationText`, allow optional `annotationValue`.

## v1 vs v2 scope

v1 delivers module/class/function/variable extraction, signatures, docstrings,
member lists, inheritance, stable deep links, and intersphinx resolution.
v2 can add inherited docstrings, source-order member ordering, richer type
rendering, and generating `objects.inv` for Astro outputs.
