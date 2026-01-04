import { z } from 'zod'
import { ProtocolVersionSchema } from './common.ts'

export const PyIntrospectModuleSchema = z.object({}).passthrough()

export const PyIntrospectPayloadSchema = z.object({
  protocolVersion: ProtocolVersionSchema,
  modules: z.array(PyIntrospectModuleSchema),
})

export type PyIntrospectModule = z.infer<typeof PyIntrospectModuleSchema>
export type PyIntrospectPayload = z.infer<typeof PyIntrospectPayloadSchema>
