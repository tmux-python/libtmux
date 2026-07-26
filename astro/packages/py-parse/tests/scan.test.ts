import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { scanPythonPaths, walkPyNodes } from '../src/index'

const fixturesRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'fixtures')

const samplePath = path.join(fixturesRoot, 'sample_module.py')

describe('scanPythonPaths', () => {
  it('parses python modules into zod-backed structures', async () => {
    const modules = await scanPythonPaths({
      root: fixturesRoot,
      paths: [samplePath],
      pythonCommand: ['python3'],
    })

    expect(modules).toHaveLength(1)
    expect(modules[0].name).toBe('sample_module')
    expect(modules[0].imports.map((item) => item.module)).toContain('typing')
    expect(modules[0]).toMatchSnapshot()
  })

  it('walks nested nodes', async () => {
    const modules = await scanPythonPaths({
      root: fixturesRoot,
      paths: [samplePath],
      pythonCommand: ['python3'],
    })

    const names = Array.from(walkPyNodes(modules)).map((node) => node.qualname)
    expect(names).toContain('sample_module.Widget.label')
    expect(names).toContain('sample_module.greet')
  })
})
