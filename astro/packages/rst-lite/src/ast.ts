export type InlineNode =
  | { type: 'text'; value: string }
  | { type: 'emphasis'; value: InlineNode[] }
  | { type: 'strong'; value: InlineNode[] }
  | { type: 'literal'; value: string }
  | { type: 'role'; role: string; value: string }

export type ParagraphNode = {
  type: 'paragraph'
  content: InlineNode[]
}

export type HeadingNode = {
  type: 'heading'
  level: number
  content: InlineNode[]
}

export type CodeBlockNode = {
  type: 'code'
  text: string
}

export type ListItemNode = {
  type: 'list_item'
  children: BlockNode[]
}

export type ListNode = {
  type: 'list'
  ordered: boolean
  items: ListItemNode[]
}

export type FieldItemNode = {
  name: string
  typeText?: string
  body: BlockNode[]
}

export type FieldListNode = {
  type: 'field_list'
  items: FieldItemNode[]
}

export type AdmonitionNode = {
  type: 'admonition'
  name: string
  title?: string
  body: BlockNode[]
}

export type BlockQuoteNode = {
  type: 'blockquote'
  children: BlockNode[]
}

export type BlockNode =
  | ParagraphNode
  | HeadingNode
  | CodeBlockNode
  | ListNode
  | FieldListNode
  | AdmonitionNode
  | BlockQuoteNode

export type DocumentNode = {
  type: 'document'
  children: BlockNode[]
}
