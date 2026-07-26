import { z } from 'zod'

export const ProtocolVersionSchema = z.literal(1)

export const PyLocationSchema = z.object({
  lineno: z.number().int().nonnegative(),
  colOffset: z.number().int().nonnegative(),
  endLineno: z.number().int().nonnegative().nullable(),
  endColOffset: z.number().int().nonnegative().nullable(),
})

export type ProtocolVersion = z.infer<typeof ProtocolVersionSchema>
export type PyLocation = z.infer<typeof PyLocationSchema>
