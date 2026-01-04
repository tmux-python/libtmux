export const slugify = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/(^-|-$)+/g, '')

export const formatSignature = (signature: string, returns: string | null): string => {
  if (!returns) {
    return signature
  }

  return `${signature} -> ${returns}`
}

export const splitDocstring = (docstring: string | null): string[] => {
  if (!docstring) {
    return []
  }

  return docstring
    .trim()
    .split(/\n\s*\n/)
    .map((block) => block.trim())
    .filter(Boolean)
}
