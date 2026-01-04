import { readFile } from 'node:fs/promises'
import {
  parseInventory,
  type IntersphinxInventory,
  type IntersphinxItem,
} from '@libtmux/intersphinx'

export type IntersphinxRef = {
  name: string
  domain?: string
  role?: string
}

export const buildIntersphinxIndex = (inventory: IntersphinxInventory): Map<string, IntersphinxItem> => {
  const index = new Map<string, IntersphinxItem>()
  for (const item of inventory.items) {
    index.set(`${item.domain}:${item.role}:${item.name}`, item)
  }
  return index
}

export const resolveIntersphinx = (
  inventory: IntersphinxInventory,
  ref: IntersphinxRef,
): IntersphinxItem | undefined => {
  const domain = ref.domain ?? 'py'
  const role = ref.role ?? 'module'
  const index = buildIntersphinxIndex(inventory)
  return index.get(`${domain}:${role}:${ref.name}`)
}

export const loadInventoryFromFile = async (
  filePath: string,
  baseUrl: string,
): Promise<IntersphinxInventory> => {
  const buffer = await readFile(filePath)
  return parseInventory(buffer, baseUrl)
}
