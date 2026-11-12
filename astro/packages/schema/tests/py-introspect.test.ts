import { describe, expect, it } from 'vitest'
import { PyIntrospectPayloadSchema } from '../src/index.ts'

describe('PyIntrospectPayloadSchema', () => {
  it('accepts an empty introspection payload', () => {
    const payload = {
      protocolVersion: 1,
      modules: [],
    }

    expect(() => PyIntrospectPayloadSchema.parse(payload)).not.toThrow()
  })

  it('accepts a minimal module payload', () => {
    const payload = {
      protocolVersion: 1,
      modules: [
        {
          kind: 'module',
          name: 'demo',
          qualname: 'demo',
          isPrivate: false,
          classes: [],
          functions: [],
          variables: [],
          docstringRaw: null,
          docstringFormat: 'unknown',
          docstringHtml: null,
          summary: null,
        },
      ],
    }

    expect(() => PyIntrospectPayloadSchema.parse(payload)).not.toThrow()
  })
})
