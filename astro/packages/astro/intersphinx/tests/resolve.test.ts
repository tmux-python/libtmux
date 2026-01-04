import { describe, expect, it } from 'vitest'
import type { IntersphinxInventory } from '@libtmux/intersphinx'
import { resolveIntersphinx } from '../src/resolve'

describe('resolveIntersphinx', () => {
  it('resolves inventory entries by ref', () => {
    const inventory: IntersphinxInventory = {
      project: 'libtmux',
      version: '0.36.0',
      baseUrl: 'https://libtmux.git-pull.com/',
      items: [
        {
          name: 'libtmux',
          domain: 'py',
          role: 'module',
          priority: 1,
          uri: 'api.html#module-libtmux',
          displayName: 'libtmux',
          url: 'https://libtmux.git-pull.com/api.html#module-libtmux',
          baseUrl: 'https://libtmux.git-pull.com/',
        },
      ],
    }

    const item = resolveIntersphinx(inventory, { name: 'libtmux', domain: 'py', role: 'module' })
    expect(item?.url).toContain('api.html')
  })
})
