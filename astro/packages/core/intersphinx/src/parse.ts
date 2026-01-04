import { inflateSync } from 'node:zlib'
import {
  type IntersphinxInventory,
  IntersphinxInventorySchema,
  type IntersphinxItem,
  IntersphinxItemSchema,
} from './schema'

const HEADER_LINES = 4

const readHeader = (buffer: Buffer): { header: string[]; offset: number } => {
  const header: string[] = []
  let offset = 0

  for (let index = 0; index < HEADER_LINES; index += 1) {
    const end = buffer.indexOf('\n', offset)
    if (end === -1) {
      throw new Error('Invalid intersphinx inventory header')
    }
    const line = buffer.slice(offset, end).toString('utf-8').replace(/\r$/, '')
    header.push(line)
    offset = end + 1
  }

  return { header, offset }
}

const parseHeaderValue = (header: string[], prefix: string): string => {
  const line = header.find((value) => value.startsWith(prefix))
  if (!line) {
    return ''
  }
  return line.slice(prefix.length).trim()
}

const parseItems = (content: string, baseUrl: string): IntersphinxItem[] => {
  const items: IntersphinxItem[] = []

  for (const line of content.split(/\r?\n/)) {
    if (!line.trim()) {
      continue
    }

    const [name, domainRole, priorityRaw, uri, ...displayParts] = line.split(' ')
    const [domain, role] = domainRole.split(':')
    const displayName = displayParts.join(' ') || name
    const resolvedUri = uri.replace('$', name)
    const url = new URL(resolvedUri, baseUrl).toString()

    items.push(
      IntersphinxItemSchema.parse({
        name,
        domain,
        role,
        priority: Number(priorityRaw),
        uri: resolvedUri,
        displayName: displayName === '-' ? name : displayName,
        url,
        baseUrl,
      }),
    )
  }

  return items
}

export const parseInventory = (input: Buffer | string, baseUrl: string): IntersphinxInventory => {
  const buffer = typeof input === 'string' ? Buffer.from(input, 'utf-8') : input
  const { header, offset } = readHeader(buffer)
  const compressed = buffer.slice(offset)
  const decompressed = inflateSync(compressed).toString('utf-8')

  const project = parseHeaderValue(header, '# Project:')
  const version = parseHeaderValue(header, '# Version:')
  const items = parseItems(decompressed, baseUrl)

  return IntersphinxInventorySchema.parse({
    project,
    version,
    baseUrl,
    items,
  })
}
