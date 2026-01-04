import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { resolveSidecarRoot } from '../src/index.ts'

describe('resolveSidecarRoot', () => {
  it('points at the sidecar project', () => {
    const root = resolveSidecarRoot()
    expect(fs.existsSync(path.join(root, 'pyproject.toml'))).toBe(true)
  })
})
