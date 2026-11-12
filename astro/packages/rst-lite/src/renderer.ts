import type {
  AdmonitionNode,
  BlockNode,
  DocumentNode,
  FieldListNode,
  InlineNode,
  ListItemNode,
  ListNode,
} from './ast.ts'

export type RoleResolution = {
  href: string
  text?: string
}

export type RoleResolver = (role: string, value: string) => RoleResolution | null

export type RenderOptions = {
  roleResolver?: RoleResolver
}

export const renderHtml = (doc: DocumentNode, options: RenderOptions = {}): string => {
  return doc.children.map((node) => renderBlock(node, options)).join('')
}

const renderBlock = (node: BlockNode, options: RenderOptions): string => {
  switch (node.type) {
    case 'paragraph':
      return `<p>${renderInline(node.content, options)}</p>`
    case 'heading':
      return `<h${node.level}>${renderInline(node.content, options)}</h${node.level}>`
    case 'code':
      return `<pre><code>${escapeHtml(node.text)}</code></pre>`
    case 'list':
      return renderList(node, options)
    case 'field_list':
      return renderFieldList(node, options)
    case 'admonition':
      return renderAdmonition(node, options)
    case 'blockquote':
      return `<blockquote>${node.children.map((child) => renderBlock(child, options)).join('')}</blockquote>`
    default:
      return ''
  }
}

const renderList = (node: ListNode, options: RenderOptions): string => {
  const tag = node.ordered ? 'ol' : 'ul'
  const items = node.items.map((item) => renderListItem(item, options)).join('')
  return `<${tag}>${items}</${tag}>`
}

const renderListItem = (node: ListItemNode, options: RenderOptions): string => {
  const body = node.children.map((child) => renderBlock(child, options)).join('')
  return `<li>${body}</li>`
}

const renderFieldList = (node: FieldListNode, options: RenderOptions): string => {
  const items = node.items
    .map((item) => {
      const title = item.typeText ? `${item.name} : ${item.typeText}` : item.name
      const body = item.body.map((child) => renderBlock(child, options)).join('')
      return `<dt>${escapeHtml(title)}</dt><dd>${body}</dd>`
    })
    .join('')
  return `<dl class="field-list">${items}</dl>`
}

const renderAdmonition = (node: AdmonitionNode, options: RenderOptions): string => {
  const title = node.title ?? node.name
  const body = node.body.map((child) => renderBlock(child, options)).join('')
  return `<aside class="admonition admonition-${escapeHtml(node.name)}"><p class="admonition-title">${escapeHtml(
    title,
  )}</p>${body}</aside>`
}

const renderInline = (nodes: InlineNode[], options: RenderOptions): string => {
  return nodes
    .map((node) => {
      switch (node.type) {
        case 'text':
          return escapeHtml(node.value)
        case 'literal':
          return `<code>${escapeHtml(node.value)}</code>`
        case 'emphasis':
          return `<em>${renderInline(node.value, options)}</em>`
        case 'strong':
          return `<strong>${renderInline(node.value, options)}</strong>`
        case 'role':
          return renderRole(node.role, node.value, options)
        default:
          return ''
      }
    })
    .join('')
}

const renderRole = (role: string, value: string, options: RenderOptions): string => {
  const resolver = options.roleResolver
  if (resolver) {
    const resolved = resolver(role, value)
    if (resolved) {
      const label = resolved.text ?? value
      return `<a href="${escapeHtml(resolved.href)}">${escapeHtml(label)}</a>`
    }
  }
  return `<code>${escapeHtml(value)}</code>`
}

const escapeHtml = (value: string): string => {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}
