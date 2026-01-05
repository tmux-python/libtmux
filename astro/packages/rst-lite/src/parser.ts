import type {
  AdmonitionNode,
  BlockNode,
  BlockQuoteNode,
  CodeBlockNode,
  DocumentNode,
  FieldItemNode,
  FieldListNode,
  HeadingNode,
  InlineNode,
  ListItemNode,
  ListNode,
  ParagraphNode,
} from './ast.ts'

const HEADING_LEVELS = new Map<string, number>([
  ['=', 1],
  ['-', 2],
  ['~', 3],
  ['^', 4],
  ['"', 5],
  ['`', 6],
])

type Line = {
  raw: string
  indent: number
  text: string
}

const toLine = (raw: string): Line => {
  const match = raw.match(/^[ \t]*/)
  const prefix = match ? match[0] : ''
  let indent = 0
  for (const ch of prefix) {
    indent += ch === '\t' ? 4 : 1
  }
  return { raw, indent, text: raw.slice(prefix.length) }
}

const isBlank = (line: Line): boolean => line.text.trim().length === 0

const isHeadingUnderline = (line: Line): { level: number } | null => {
  const trimmed = line.text.trim()
  if (trimmed.length < 3) {
    return null
  }
  const char = trimmed[0]
  if (!HEADING_LEVELS.has(char)) {
    return null
  }
  if (!trimmed.split('').every((item) => item === char)) {
    return null
  }
  return { level: HEADING_LEVELS.get(char) ?? 2 }
}

const detectHeading = (lines: Line[], index: number, baseIndent: number): HeadingNode | null => {
  const current = lines[index]
  const next = lines[index + 1]
  if (!current || !next) {
    return null
  }
  if (current.indent !== baseIndent || next.indent !== baseIndent) {
    return null
  }
  if (isBlank(current) || isBlank(next)) {
    return null
  }
  const underline = isHeadingUnderline(next)
  if (!underline) {
    return null
  }
  return {
    type: 'heading',
    level: underline.level,
    content: parseInline(current.text.trim()),
  }
}

type ListMarker = {
  ordered: boolean
  marker: string
  content: string
}

const parseListMarker = (text: string): ListMarker | null => {
  const bulletMatch = text.match(/^([-+*])\s+(.*)$/)
  if (bulletMatch) {
    return { ordered: false, marker: bulletMatch[1], content: bulletMatch[2] }
  }
  const orderedMatch = text.match(/^(\d+)([.)])\s+(.*)$/)
  if (orderedMatch) {
    return {
      ordered: true,
      marker: `${orderedMatch[1]}${orderedMatch[2]}`,
      content: orderedMatch[3],
    }
  }
  return null
}

const parseDirective = (
  lines: Line[],
  index: number,
  baseIndent: number,
): { node: AdmonitionNode; nextIndex: number } | null => {
  const line = lines[index]
  if (line.indent !== baseIndent) {
    return null
  }
  const match = line.text.match(/^\.\.\s+(\w+)(::\s*(.*))?$/)
  if (!match) {
    return null
  }
  const name = match[1]
  const arg = match[3]?.trim()
  let nextIndex = index + 1
  while (nextIndex < lines.length && isBlank(lines[nextIndex])) {
    nextIndex += 1
  }
  const bodyLines: Line[] = []
  let bodyIndent = 0
  if (nextIndex < lines.length && lines[nextIndex].indent > baseIndent) {
    bodyIndent = lines[nextIndex].indent
    for (let i = nextIndex; i < lines.length; i += 1) {
      const candidate = lines[i]
      if (candidate.indent < bodyIndent && !isBlank(candidate)) {
        break
      }
      if (candidate.indent < baseIndent) {
        break
      }
      bodyLines.push(candidate)
      nextIndex = i + 1
    }
  }
  const { nodes } = parseBlocks(bodyLines, 0, bodyIndent || baseIndent + 2)
  return {
    node: {
      type: 'admonition',
      name,
      title: formatAdmonitionTitle(name, arg),
      body: nodes,
    },
    nextIndex,
  }
}

const formatAdmonitionTitle = (name: string, arg: string | undefined): string => {
  const label = name.replace(/[-_]+/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase())
  if (!arg) {
    return label
  }
  return `${label}: ${arg}`
}

const parseFieldList = (
  lines: Line[],
  startIndex: number,
  baseIndent: number,
): { node: FieldListNode; nextIndex: number } | null => {
  const fieldMatch = matchField(lines[startIndex], baseIndent)
  if (!fieldMatch) {
    return null
  }
  const items: FieldItemNode[] = []
  let index = startIndex
  while (index < lines.length) {
    const current = lines[index]
    const match = matchField(current, baseIndent)
    if (!match) {
      break
    }
    const { name, typeText } = match
    index += 1
    const bodyLines: Line[] = []
    let bodyIndent = 0
    while (index < lines.length) {
      const next = lines[index]
      if (next.indent < baseIndent) {
        break
      }
      if (next.indent === baseIndent && matchField(next, baseIndent)) {
        break
      }
      if (next.indent > baseIndent && bodyIndent === 0 && !isBlank(next)) {
        bodyIndent = next.indent
      }
      bodyLines.push(next)
      index += 1
    }
    const { nodes } = parseBlocks(bodyLines, 0, bodyIndent || baseIndent + 2)
    items.push({ name, typeText, body: nodes })
  }
  return {
    node: {
      type: 'field_list',
      items,
    },
    nextIndex: index,
  }
}

const matchField = (line: Line, baseIndent: number): { name: string; typeText?: string } | null => {
  if (line.indent !== baseIndent) {
    return null
  }
  const match = line.text.match(/^([A-Za-z_][\w.-]*)(\s*:\s*)(.+)$/)
  if (!match) {
    return null
  }
  return { name: match[1], typeText: match[3].trim() }
}

const parseList = (
  lines: Line[],
  startIndex: number,
  baseIndent: number,
): { node: ListNode; nextIndex: number } | null => {
  const first = lines[startIndex]
  if (!first || first.indent !== baseIndent) {
    return null
  }
  const marker = parseListMarker(first.text)
  if (!marker) {
    return null
  }
  const items: ListItemNode[] = []
  const ordered = marker.ordered
  let index = startIndex
  while (index < lines.length) {
    const line = lines[index]
    if (line.indent !== baseIndent) {
      break
    }
    const markerMatch = parseListMarker(line.text)
    if (!markerMatch || markerMatch.ordered !== ordered) {
      break
    }
    const contentIndent = baseIndent + markerMatch.marker.length + 1
    const itemLines: Line[] = []
    itemLines.push({ raw: markerMatch.content, indent: contentIndent, text: markerMatch.content })
    index += 1
    while (index < lines.length) {
      const next = lines[index]
      if (next.indent < baseIndent) {
        break
      }
      if (next.indent === baseIndent && parseListMarker(next.text)) {
        break
      }
      if (next.indent < contentIndent && !isBlank(next)) {
        itemLines.push({ raw: next.raw, indent: contentIndent, text: next.text.trim() })
      } else {
        itemLines.push(next)
      }
      index += 1
    }
    const { nodes } = parseBlocks(itemLines, 0, contentIndent)
    items.push({ type: 'list_item', children: nodes })
  }
  return {
    node: {
      type: 'list',
      ordered,
      items,
    },
    nextIndex: index,
  }
}

const parseBlockQuote = (
  lines: Line[],
  startIndex: number,
  baseIndent: number,
): { node: BlockQuoteNode; nextIndex: number } => {
  const quoteIndent = lines[startIndex].indent
  const subset: Line[] = []
  let index = startIndex
  while (index < lines.length) {
    const line = lines[index]
    if (line.indent < quoteIndent && !isBlank(line)) {
      break
    }
    if (line.indent < baseIndent) {
      break
    }
    subset.push(line)
    index += 1
  }
  const { nodes } = parseBlocks(subset, 0, quoteIndent)
  return {
    node: { type: 'blockquote', children: nodes },
    nextIndex: index,
  }
}

const parseParagraph = (
  lines: Line[],
  startIndex: number,
  baseIndent: number,
): { node: ParagraphNode; nextIndex: number; literalBlock: boolean } => {
  const textLines: string[] = []
  let index = startIndex
  while (index < lines.length) {
    const line = lines[index]
    if (line.indent < baseIndent) {
      break
    }
    if (isBlank(line)) {
      break
    }
    if (line.indent === baseIndent) {
      if (detectHeading(lines, index, baseIndent)) {
        break
      }
      if (parseListMarker(line.text)) {
        break
      }
      if (matchField(line, baseIndent)) {
        break
      }
      if (line.text.startsWith('.. ')) {
        break
      }
    }
    textLines.push(line.text.trim())
    index += 1
  }
  let literalBlock = false
  if (textLines.length > 0) {
    const lastIndex = textLines.length - 1
    if (textLines[lastIndex].endsWith('::')) {
      literalBlock = true
      textLines[lastIndex] = textLines[lastIndex].replace(/::$/, ':')
    }
  }
  const text = textLines.join('\n')
  return {
    node: { type: 'paragraph', content: parseInline(text) },
    nextIndex: index,
    literalBlock,
  }
}

const parseLiteralBlock = (
  lines: Line[],
  startIndex: number,
  baseIndent: number,
): { node: CodeBlockNode | null; nextIndex: number } => {
  let index = startIndex
  while (index < lines.length && isBlank(lines[index])) {
    index += 1
  }
  if (index >= lines.length || lines[index].indent <= baseIndent) {
    return { node: null, nextIndex: startIndex }
  }
  const blockLines: Line[] = []
  while (index < lines.length) {
    const line = lines[index]
    if (line.indent <= baseIndent && !isBlank(line)) {
      break
    }
    blockLines.push(line)
    index += 1
  }
  const contentLines = blockLines.filter((line) => !isBlank(line))
  const minIndent = contentLines.reduce(
    (min, line) => Math.min(min, line.indent),
    contentLines.length > 0 ? contentLines[0].indent : baseIndent + 2,
  )
  const text = blockLines
    .map((line) => {
      if (isBlank(line)) {
        return ''
      }
      return line.raw.slice(minIndent)
    })
    .join('\n')
  return { node: { type: 'code', text }, nextIndex: index }
}

const parseBlocks = (
  lines: Line[],
  startIndex: number,
  baseIndent: number,
): { nodes: BlockNode[]; nextIndex: number } => {
  const nodes: BlockNode[] = []
  let index = startIndex
  while (index < lines.length) {
    const line = lines[index]
    if (!line) {
      break
    }
    if (line.indent < baseIndent) {
      break
    }
    if (isBlank(line)) {
      index += 1
      continue
    }

    const heading = detectHeading(lines, index, baseIndent)
    if (heading) {
      nodes.push(heading)
      index += 2
      continue
    }

    const directive = parseDirective(lines, index, baseIndent)
    if (directive) {
      nodes.push(directive.node)
      index = directive.nextIndex
      continue
    }

    const list = parseList(lines, index, baseIndent)
    if (list) {
      nodes.push(list.node)
      index = list.nextIndex
      continue
    }

    const fieldList = parseFieldList(lines, index, baseIndent)
    if (fieldList) {
      nodes.push(fieldList.node)
      index = fieldList.nextIndex
      continue
    }

    if (line.indent > baseIndent) {
      const quote = parseBlockQuote(lines, index, baseIndent)
      nodes.push(quote.node)
      index = quote.nextIndex
      continue
    }

    const paragraph = parseParagraph(lines, index, baseIndent)
    nodes.push(paragraph.node)
    index = paragraph.nextIndex
    if (paragraph.literalBlock) {
      const literal = parseLiteralBlock(lines, index, baseIndent)
      if (literal.node) {
        nodes.push(literal.node)
        index = literal.nextIndex
      }
    }
  }
  return { nodes, nextIndex: index }
}

export const parseRst = (input: string): DocumentNode => {
  const normalized = input.replace(/\r\n/g, '\n')
  const lines = normalized.split('\n').map((line) => toLine(line))
  const { nodes } = parseBlocks(lines, 0, 0)
  return { type: 'document', children: nodes }
}

const parseInline = (text: string): InlineNode[] => {
  const normalized = text.replace(/\n+/g, ' ')
  const nodes: InlineNode[] = []
  let index = 0
  while (index < normalized.length) {
    const rest = normalized.slice(index)
    const roleMatch = rest.match(/^:([\w:]+):`([^`]+)`/)
    if (roleMatch) {
      nodes.push({ type: 'role', role: roleMatch[1], value: roleMatch[2] })
      index += roleMatch[0].length
      continue
    }
    if (rest.startsWith('``')) {
      const end = rest.indexOf('``', 2)
      if (end !== -1) {
        const value = rest.slice(2, end)
        nodes.push({ type: 'literal', value })
        index += end + 2
        continue
      }
    }
    if (rest.startsWith('**')) {
      const end = rest.indexOf('**', 2)
      if (end !== -1) {
        const content = rest.slice(2, end)
        nodes.push({ type: 'strong', value: parseInline(content) })
        index += end + 2
        continue
      }
    }
    if (rest.startsWith('*')) {
      const end = rest.indexOf('*', 1)
      if (end !== -1) {
        const content = rest.slice(1, end)
        nodes.push({ type: 'emphasis', value: parseInline(content) })
        index += end + 1
        continue
      }
    }
    const nextSpecial = rest.search(/[:*`]/)
    if (nextSpecial === -1) {
      nodes.push({ type: 'text', value: rest })
      break
    }
    if (nextSpecial > 0) {
      nodes.push({ type: 'text', value: rest.slice(0, nextSpecial) })
      index += nextSpecial
    } else {
      nodes.push({ type: 'text', value: rest[0] })
      index += 1
    }
  }
  return mergeTextNodes(nodes)
}

const mergeTextNodes = (nodes: InlineNode[]): InlineNode[] => {
  const merged: InlineNode[] = []
  for (const node of nodes) {
    const last = merged.at(-1)
    if (node.type === 'text' && last?.type === 'text') {
      last.value += node.value
    } else {
      merged.push(node)
    }
  }
  return merged
}
