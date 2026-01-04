import type { ApiPackage } from '@libtmux/api-model'
import { buildApiPackage } from '@libtmux/api-model'
import type { PythonCommand } from '@libtmux/py-bridge'
import { introspectPackage } from '@libtmux/py-introspect'
import { scanPythonPaths } from '@libtmux/py-parse'

export type LoadApiOptions = {
  name: string
  root: string
  paths: string[]
  includePrivate?: boolean
  generatedAt?: string
  introspect?: boolean
  introspectPackage?: string
  annotationFormat?: 'string' | 'value'
  pythonCommand?: PythonCommand
}

export const loadApiPackage = async (options: LoadApiOptions): Promise<ApiPackage> => {
  const modules = await scanPythonPaths({
    root: options.root,
    paths: options.paths,
    includePrivate: options.includePrivate,
    pythonCommand: options.pythonCommand,
  })

  const introspection = options.introspect
    ? (
        await introspectPackage(options.introspectPackage ?? options.name, {
          root: options.root,
          includePrivate: options.includePrivate,
          annotationFormat: options.annotationFormat,
          pythonCommand: options.pythonCommand,
        })
      ).modules
    : undefined

  return buildApiPackage(modules, {
    name: options.name,
    root: options.root,
    includePrivate: options.includePrivate,
    generatedAt: options.generatedAt,
    introspection,
  })
}
