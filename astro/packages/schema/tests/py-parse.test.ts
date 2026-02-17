import { describe, expect, it } from 'vitest'
import { PyParsePayloadSchema } from '../src/index.ts'

describe('PyParsePayloadSchema', () => {
  it('accepts a minimal parse payload', () => {
    const payload = {
      protocolVersion: 1,
      modules: [
        {
          kind: 'module',
          name: 'demo',
          qualname: 'demo',
          path: '/tmp/demo.py',
          docstring: null,
          items: [],
          imports: [],
          exports: [],
          isPackage: false,
          location: {
            lineno: 1,
            colOffset: 0,
            endLineno: null,
            endColOffset: null,
          },
        },
      ],
    }

    expect(() => PyParsePayloadSchema.parse(payload)).not.toThrow()
  })
})
