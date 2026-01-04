# libtmux docs (Astro)

Astro-based documentation monorepo for libtmux. It replaces the Sphinx site with a static-first site and a TypeScript-driven API doc pipeline that scans Python source via uv/uvx.

## Packages

- `packages/core/py-ast`: Python AST scanner with Zod schemas
- `packages/core/api-model`: High-level API model built from scan results
- `packages/core/intersphinx`: Sphinx intersphinx inventory parser
- `packages/astro/autodoc`: Astro components for API docs
- `packages/astro/intersphinx`: Astro helpers for intersphinx links
- `packages/site/docs`: The docs website

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

The AST scanner defaults to `uvx python` and can be overridden with `LIBTMUX_PYTHON_COMMAND`.
