# AGENTS.md

## Project Context

Astro-based documentation monorepo for libtmux. It replaces the existing Sphinx site with a static-first Astro site that renders API docs by scanning Python source with a TypeScript toolchain and a small Python AST helper.

## Tech Stack

- **Framework**: Astro v5 (islands) + optional React for hydration
- **Styling**: Tailwind CSS v4
- **Language**: TypeScript (strict)
- **Testing**: Vitest
- **Quality**: Biome (lint/format)
- **Package Manager**: pnpm 10.x workspaces
- **Python tooling**: uv/uvx + Python AST for API scanning

## Architecture Map

```
packages/
├── schema/                # Zod contracts (schema firewall)
├── py-bridge/             # uv/uvx subprocess boundary
├── py-parse/              # Static AST parsing
├── py-introspect/         # Runtime introspection
├── api-model/             # High-level API model + snapshots
├── core/                  # Orchestration + caching
├── intersphinx/           # Intersphinx inventory parser
├── astro-autodoc/         # Astro components + helpers for API rendering
└── astro-intersphinx/     # Astro helpers for intersphinx resolution

apps/
└── docs/                  # Astro docs site for libtmux

python/
└── pyautodoc_sidecar/     # Python sidecar invoked via uv run
```

## Workflow Commands

```bash
pnpm install
```

```bash
pnpm start
```

```bash
pnpm type-check
```

```bash
pnpm biome-all
```

```bash
pnpm test
```

```bash
pnpm update:all
```

```bash
pnpm ncu
```

## Hard Constraints

1. **Monorepo layering**: core packages must not depend on astro packages.
2. **Autodoc data**: use Zod schemas for validated data flow between packages.
3. **Python scanning**: default to `uv run` with a sidecar project; allow an override for local Python executables and optional `uvx` tool mode.
4. **Astro hydration**: any React components must include an explicit client directive.
