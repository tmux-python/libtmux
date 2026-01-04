import { buildApiPackage } from '@libtmux/api-model'
import { describe, expect, it } from 'vitest'

describe('docs site', () => {
  it('references core api model helpers', () => {
    expect(typeof buildApiPackage).toBe('function')
  })
})
