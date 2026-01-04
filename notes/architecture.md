# Architecture

## Monorepo layout

```text
libtmux/
├- libtmux/
├- docs/
├- pyproject.toml
└- astro/
   ├- AGENTS.md
   ├- pnpm-workspace.yaml
   ├- package.json
   ├- tsconfig.base.json
   ├- vitest.workspace.ts
   ├- biome.json
   ├- packages/
   │  ├- schema/
   │  ├- py-bridge/
   │  ├- py-parse/
   │  ├- py-introspect/
   │  ├- api-model/
   │  ├- core/
   │  ├- intersphinx/
   │  ├- astro-autodoc/
   │  └- astro-intersphinx/
   ├- python/
   │  └- pyautodoc_sidecar/
   └- apps/
      └- docs/
```

## Dependency tiers

- Tier 0: `schema` (leaf, shared Zod contracts)
- Tier 1: `py-bridge`, `py-parse`, `py-introspect`, `intersphinx`
- Tier 2: `api-model`, `core`
- Tier 3: `astro-autodoc`, `astro-intersphinx`, `apps/docs`

Dependencies flow strictly downward. `core` orchestrates; Astro packages are UI
consumers.

## Data flow

```text
python files -> py-parse (ast) -> py-introspect (inspect)
          \                         /
           -> api-model (merge, normalize) -> api-index.json -> astro UI
```

## Schema firewall

All cross-boundary payloads live in `schema` and are validated by Zod:

- `protocolVersion: 1`
- structured errors (no thrown strings)
- source spans for deep links
- stable IDs and anchors
- docstring channels and annotation channels

## Stable IDs and anchors

Use Sphinx-shaped identifiers so local links and intersphinx share a key space:

- `xrefKey = "{domain}:{role}:{fullName}"`
- examples:
  - `py:module:libtmux.server`
  - `py:class:libtmux.server.Server`
  - `py:function:libtmux.server.Server.attach`

Also store `module`, `qualname`, `name`, `kind`, `anchor`, and `source`.

## Docstrings and annotations

- Store `docstringRaw`, `docstringFormat`, `docstringHtml`, `summary`.
- Store `annotationText` always when available.
- Optionally store `annotationValue` when explicitly enabled.
- Default `annotationFormat=STRING` for deterministic output.

## Python sidecar

Package: `astro/python/pyautodoc_sidecar`

CLI subcommands:

1. `parse-files`
   - parse with `ast`
   - emit imports, defs, spans, module docstrings, `__all__` hints
2. `introspect-module`
   - import module
   - `inspect.signature`, member discovery, annotations
3. `introspect-package`
   - package walk with allow/deny and includePrivate options

Docstring rendering:

- Convert RST to HTML via docutils
- Keep raw docstring always
- Allow TS to pre-rewrite xref roles into plain links when inventories exist

Import safety:

- `mockImports` and autodoc-style mocks
- timeouts and bounded output at the subprocess boundary

## TS packages

- `py-bridge`: runs `uv run` or `uvx`, handles timeouts and JSON parsing, enforces
  Zod validation
- `py-parse`: wraps `parse-files`
- `py-introspect`: wraps `introspect-module` and `introspect-package`
- `api-model`: merges parse + introspect data, computes public surface and
  stable ordering
- `core`: orchestration, cache invalidation, file watching
- `intersphinx`: parse `objects.inv` v2, provide resolver
- `astro-autodoc`: virtual module and components
- `astro-intersphinx`: inventory loader and URL resolver

## Cache strategy

- Cache `api-index.json` in `.cache/pyautodoc/`
- In dev, watch `libtmux/**/*.py` and inventories for invalidation
- Normalize output for snapshots (stable order, scrub absolute paths)

## Astro integration

Virtual modules:

- `virtual:pyautodoc/api`
- `virtual:pyautodoc/intersphinx`

Components:

- `<ApiModule/>`, `<ApiObject/>`, `<ApiSignature/>`, `<ApiDocstring/>`,
  `<ApiMemberList/>`

Routing:

- `src/pages/api/[...slug].astro` can render all modules using
  `getStaticPaths()` from the API index while keeping user-authored pages.
