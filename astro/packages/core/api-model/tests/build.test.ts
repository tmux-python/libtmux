import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { scanPythonPaths } from '@libtmux/py-ast'
import { describe, expect, it } from 'vitest'
import { buildApiPackage } from '../src/build'

const fixturesRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../py-ast/tests/fixtures')

const samplePath = path.join(fixturesRoot, 'sample_module.py')

describe('buildApiPackage', () => {
  it('builds a package model suitable for rendering', async () => {
    const modules = await scanPythonPaths({
      root: fixturesRoot,
      paths: [samplePath],
      pythonCommand: ['python3'],
    })

    const api = buildApiPackage(modules, {
      name: 'libtmux',
      root: fixturesRoot,
      includePrivate: false,
      generatedAt: '2025-01-01T00:00:00.000Z',
    })

    expect(api).toMatchSnapshot()
  })
})
