import { z } from 'zod'

export const IntersphinxItemSchema = z.object({
  name: z.string(),
  domain: z.string(),
  role: z.string(),
  priority: z.number().int(),
  uri: z.string(),
  displayName: z.string(),
  url: z.string(),
  baseUrl: z.string(),
})

export const IntersphinxInventorySchema = z.object({
  project: z.string(),
  version: z.string(),
  baseUrl: z.string(),
  items: z.array(IntersphinxItemSchema),
})

export type IntersphinxItem = z.infer<typeof IntersphinxItemSchema>
export type IntersphinxInventory = z.infer<typeof IntersphinxInventorySchema>
