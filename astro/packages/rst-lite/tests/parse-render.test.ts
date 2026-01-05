import { describe, expect, it } from 'vitest'
import { parseRst, type RoleResolver, renderHtml } from '../src/index.ts'

const resolver: RoleResolver = (role, value) => {
  if (role === 'class') {
    return { href: `https://example.test/${value}`, text: value }
  }
  if (role === 'meth') {
    return { href: `https://example.test/${value}#meth`, text: value }
  }
  return null
}

describe('rst-lite parser', () => {
  const cases = [
    {
      name: 'paragraph-inline',
      input: 'Hello *world* **bold** ``code`` and :class:`Foo`.',
    },
    {
      name: 'heading-field-list',
      input: 'Parameters\n----------\nfoo : int\n    Foo line.\nbar : str\n    Bar line.\n',
    },
    {
      name: 'nested-lists',
      input: '- Item one\n  - Sub a\n    - Deep item\n  - Sub b\n- Item two\n',
    },
    {
      name: 'literal-block',
      input: `Example::\n\n    print('hi')\n    print('there')\n`,
    },
    {
      name: 'admonition',
      input: '.. deprecated:: 0.17\n\n   Use :meth:`Foo.old` instead.\n',
    },
    {
      name: 'mixed-blocks',
      input:
        'Notes\n-----\nThis is a paragraph.\n\n.. note::\n\n   A note with :class:`Thing`.\n\n1. Ordered\n2. List\n',
    },
  ]

  for (const fixture of cases) {
    it(`parses ${fixture.name}`, () => {
      const doc = parseRst(fixture.input)
      expect(doc).toMatchSnapshot(`${fixture.name}-ast`)
    })

    it(`renders ${fixture.name}`, () => {
      const doc = parseRst(fixture.input)
      const html = renderHtml(doc, { roleResolver: resolver })
      expect(html).toMatchSnapshot(`${fixture.name}-html`)
    })
  }
})
