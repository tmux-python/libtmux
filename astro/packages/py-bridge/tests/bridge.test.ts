import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { mergePythonPath, parsePythonCommand } from '../src/index.ts'

describe('parsePythonCommand', () => {
  it('parses commands from strings', () => {
    expect(parsePythonCommand('uv run python')).toEqual(['uv', 'run', 'python'])
    expect(parsePythonCommand('')).toBeUndefined()
    expect(parsePythonCommand(undefined)).toBeUndefined()
  })
})

describe('mergePythonPath', () => {
  it('prepends paths to PYTHONPATH', () => {
    const env = mergePythonPath({ PYTHONPATH: `/tmp${path.delimiter}./local` }, '/sidecar')
    expect(env.PYTHONPATH?.startsWith('/sidecar')).toBe(true)
  })
})
