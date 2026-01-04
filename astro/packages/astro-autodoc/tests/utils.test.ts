import { describe, expect, it } from 'vitest'
import { formatSignature, slugify, splitDocstring } from '../src/utils'

describe('autodoc utils', () => {
  it('slugifies qualnames', () => {
    expect(slugify('libtmux.Server.new_window')).toBe('libtmux-server-new-window')
  })

  it('formats signatures with return types', () => {
    expect(formatSignature('(name: str)', 'Window')).toBe('(name: str) -> Window')
  })

  it('splits docstrings into blocks', () => {
    const blocks = splitDocstring('Line one.\n\nLine two.')
    expect(blocks).toEqual(['Line one.', 'Line two.'])
  })
})
