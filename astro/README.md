# libtmux docs (Astro)

Astro-based documentation monorepo for libtmux. It replaces the Sphinx site with a static-first site and a TypeScript-driven API doc pipeline that scans Python source via a Python sidecar.

## Packages

- `packages/schema`: Zod schema firewall
- `packages/py-bridge`: Python subprocess bridge (uv run / uvx)
- `packages/py-parse`: Python AST parser
- `packages/py-introspect`: Runtime introspection wrapper
- `packages/api-model`: High-level API model built from scan results
- `packages/core`: Orchestration + caching
- `packages/intersphinx`: Sphinx intersphinx inventory parser
- `packages/astro-autodoc`: Astro components for API docs
- `packages/astro-intersphinx`: Astro helpers for intersphinx links
- `apps/docs`: The docs website

## Setup

Install dependencies:

```bash
pnpm install
```

## Development

Start the docs site:

```bash
pnpm start
```

## Quality checks

Run the type checker:

```bash
pnpm type-check
```

Run the linter:

```bash
pnpm biome-all
```

Run tests:

```bash
pnpm test
```

## Updating dependencies

Update all dependencies with npm-check-updates:

```bash
pnpm update:all
```

## Python scanning

The sidecar defaults to `uv run python` and can be overridden with `LIBTMUX_PYTHON_COMMAND`.
