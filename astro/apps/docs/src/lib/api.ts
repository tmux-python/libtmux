import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type { ApiPackage } from '@libtmux/api-model'
import { loadApiPackage } from '@libtmux/astro-autodoc'

let cached: ApiPackage | null = null

const resolveRepoRoot = (): string => {
  const fromEnv = process.env.LIBTMUX_REPO_ROOT
  if (fromEnv) {
    return fromEnv
  }

  const here = path.dirname(fileURLToPath(import.meta.url))
  return path.resolve(here, '../../../../../')
}

export const getApiModel = async (): Promise<ApiPackage> => {
  if (cached) {
    return cached
  }

  const repoRoot = resolveRepoRoot()
  const sourceRoot = path.join(repoRoot, 'src')
  const packageRoot = path.join(sourceRoot, 'libtmux')

  cached = await loadApiPackage({
    name: 'libtmux',
    root: sourceRoot,
    paths: [packageRoot],
    introspect: true,
    introspectPackage: 'libtmux',
    annotationFormat: 'string',
    mockImports: ['pytest'],
  })

  return cached
}
