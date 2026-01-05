import type { ApiPackage } from '@libtmux/api-model'
import { describe, expect, it } from 'vitest'
import { renderDocstrings } from '../src/docstrings.ts'

const location = {
  lineno: 1,
  colOffset: 0,
  endLineno: null,
  endColOffset: null,
}

const sampleApi: ApiPackage = {
  name: 'demo',
  root: '/demo',
  generatedAt: '2026-01-05T00:00:00.000Z',
  modules: [
    {
      kind: 'module',
      name: 'demo',
      qualname: 'demo',
      docstring: 'Hello *world*',
      docstringFormat: 'rst',
      docstringHtml: null,
      summary: null,
      isPrivate: false,
      location,
      path: '/demo/__init__.py',
      exports: [],
      imports: [],
      classes: [],
      functions: [],
      variables: [],
    },
  ],
}

describe('renderDocstrings', () => {
  it('renders rst-lite HTML for module docstrings', () => {
    const rendered = renderDocstrings(sampleApi, { mode: 'rst-lite' })
    expect(rendered.modules[0]?.docstringHtml).toMatchInlineSnapshot('"<p>Hello <em>world</em></p>"')
  })
})
