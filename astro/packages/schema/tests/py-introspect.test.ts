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
})
