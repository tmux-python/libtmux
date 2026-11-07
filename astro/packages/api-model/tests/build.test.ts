import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { scanPythonPaths } from '@libtmux/py-parse'
import type { PyIntrospectModule } from '@libtmux/schema'
import { describe, expect, it } from 'vitest'
import { buildApiPackage } from '../src/build'

const fixturesRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../py-parse/tests/fixtures')

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

  it('prefers introspected docstrings and signatures when provided', async () => {
    const modules = await scanPythonPaths({
      root: fixturesRoot,
      paths: [samplePath],
      pythonCommand: ['python3'],
    })

    const introspection = [
      {
        kind: 'module',
        name: 'sample_module',
        qualname: 'sample_module',
        isPrivate: false,
        classes: [],
        functions: [
          {
            kind: 'function',
            name: 'greet',
            qualname: 'sample_module.greet',
            module: 'sample_module',
            signature: '(name: str) -> str',
            parameters: [
              {
                name: 'name',
                kind: 'positional-or-keyword',
                default: null,
                annotationText: 'str',
                annotationValue: null,
              },
            ],
            returns: {
              annotationText: 'str',
              annotationValue: null,
            },
            isAsync: false,
            isPrivate: false,
            docstringRaw: 'Say hello.',
            docstringFormat: 'rst',
            docstringHtml: '<p>Say hello.</p>',
            summary: 'Say hello.',
          },
        ],
        variables: [],
        docstringRaw: null,
        docstringFormat: 'unknown',
        docstringHtml: null,
        summary: null,
      },
    ] satisfies PyIntrospectModule[]

    const api = buildApiPackage(modules, {
      name: 'libtmux',
      root: fixturesRoot,
      includePrivate: false,
      generatedAt: '2025-01-01T00:00:00.000Z',
      introspection,
    })

    const greet = api.modules[0]?.functions.find((fn) => fn.name === 'greet')
    expect(greet?.signature).toBe('(name: str)')
    expect(greet?.returns).toBe('str')
    expect(greet?.docstringHtml).toBe('<p>Say hello.</p>')
  })
})
