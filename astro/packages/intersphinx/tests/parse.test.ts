import { deflateSync } from 'node:zlib'
import { describe, expect, it } from 'vitest'
import { parseInventory } from '../src/parse'

const buildInventory = (body: string): Buffer => {
  const header = [
    '# Sphinx inventory version 2',
    '# Project: libtmux',
    '# Version: 0.36.0',
    '# The remainder of this file is compressed using zlib.',
  ].join('\n')

  const compressed = deflateSync(Buffer.from(body, 'utf-8'))
  return Buffer.concat([Buffer.from(`${header}\n`, 'utf-8'), compressed])
}

describe('parseInventory', () => {
  it('parses a minimal intersphinx inventory', () => {
    const body = [
      'libtmux py:module 1 api.html#module-libtmux libtmux',
      'libtmux.Server py:class 1 api.html#libtmux.Server -',
    ].join('\n')

    const buffer = buildInventory(body)
    const inventory = parseInventory(buffer, 'https://libtmux.git-pull.com/')

    expect(inventory.project).toBe('libtmux')
    expect(inventory.items).toHaveLength(2)
    expect(inventory.items[1].url).toContain('https://libtmux.git-pull.com/api.html')
    expect(inventory).toMatchSnapshot()
  })
})
