import type { PyClass, PyFunction, PyImport, PyModule, PyParameter, PyVariable } from '@libtmux/py-ast'
import {
  type ApiClass,
  ApiClassSchema,
  type ApiFunction,
  ApiFunctionSchema,
  type ApiMethod,
  ApiMethodSchema,
  type ApiModule,
  ApiModuleSchema,
  type ApiPackage,
  ApiPackageSchema,
  type ApiParameter,
  ApiParameterSchema,
  type ApiVariable,
  ApiVariableSchema,
} from './schema'

export type BuildOptions = {
  name: string
  root: string
  includePrivate?: boolean
  generatedAt?: string
}

const summarizeDocstring = (docstring: string | null): string | null => {
  if (!docstring) {
    return null
  }

  const [firstLine] = docstring.trim().split('\n')
  return firstLine?.trim() || null
}

const formatParameterSignature = (param: PyParameter): string => {
  let name = param.name

  if (param.kind === 'var-positional') {
    name = `*${name}`
  }

  if (param.kind === 'var-keyword') {
    name = `**${name}`
  }

  if (param.annotation) {
    name = `${name}: ${param.annotation}`
  }

  if (param.default) {
    name = `${name} = ${param.default}`
  }

  return name
}

const buildParameter = (param: PyParameter): ApiParameter =>
  ApiParameterSchema.parse({
    ...param,
    signature: formatParameterSignature(param),
  })

const buildSignature = (parameters: PyParameter[]): string => {
  const positionalOnly = parameters.filter((param) => param.kind === 'positional-only')
  const positional = parameters.filter((param) => param.kind === 'positional-or-keyword')
  const varPositional = parameters.find((param) => param.kind === 'var-positional')
  const keywordOnly = parameters.filter((param) => param.kind === 'keyword-only')
  const varKeyword = parameters.find((param) => param.kind === 'var-keyword')

  const parts: string[] = []

  for (const param of positionalOnly) {
    parts.push(formatParameterSignature(param))
  }

  if (positionalOnly.length > 0) {
    parts.push('/')
  }

  for (const param of positional) {
    parts.push(formatParameterSignature(param))
  }

  if (varPositional) {
    parts.push(formatParameterSignature(varPositional))
  }

  if (keywordOnly.length > 0 && !varPositional) {
    parts.push('*')
  }

  for (const param of keywordOnly) {
    parts.push(formatParameterSignature(param))
  }

  if (varKeyword) {
    parts.push(formatParameterSignature(varKeyword))
  }

  return `(${parts.join(', ')})`
}

const buildFunction = (fn: PyFunction): ApiFunction =>
  ApiFunctionSchema.parse({
    ...fn,
    kind: 'function',
    signature: buildSignature(fn.parameters),
    parameters: fn.parameters.map(buildParameter),
    summary: summarizeDocstring(fn.docstring),
  })

const buildMethod = (fn: PyFunction, className: string): ApiMethod =>
  ApiMethodSchema.parse({
    ...fn,
    kind: 'method',
    signature: buildSignature(fn.parameters),
    parameters: fn.parameters.map(buildParameter),
    summary: summarizeDocstring(fn.docstring),
    className,
  })

const buildVariable = (variable: PyVariable): ApiVariable =>
  ApiVariableSchema.parse({
    ...variable,
    summary: summarizeDocstring(variable.docstring),
  })

const buildClass = (klass: PyClass, includePrivate: boolean): ApiClass => {
  const methods = klass.methods
    .filter((method) => includePrivate || !method.isPrivate)
    .map((method) => buildMethod(method, klass.name))

  const attributes = klass.attributes.filter((attribute) => includePrivate || !attribute.isPrivate).map(buildVariable)

  return ApiClassSchema.parse({
    ...klass,
    kind: 'class',
    summary: summarizeDocstring(klass.docstring),
    methods,
    attributes,
  })
}

const buildImportLine = (item: PyImport): string => {
  if (item.module) {
    return `from ${item.module} import ${item.names.join(', ')}`
  }

  return `import ${item.names.join(', ')}`
}

const buildModule = (module: PyModule, includePrivate: boolean): ApiModule => {
  const classes = module.items
    .filter((item): item is PyClass => item.kind === 'class')
    .filter((item) => includePrivate || !item.isPrivate)
    .map((item) => buildClass(item, includePrivate))

  const functions = module.items
    .filter((item): item is PyFunction => item.kind === 'function')
    .filter((item) => includePrivate || !item.isPrivate)
    .map(buildFunction)

  const variables = module.items
    .filter((item): item is PyVariable => item.kind === 'variable')
    .filter((item) => includePrivate || !item.isPrivate)
    .map(buildVariable)

  return ApiModuleSchema.parse({
    kind: 'module',
    name: module.name,
    qualname: module.qualname,
    docstring: module.docstring,
    summary: summarizeDocstring(module.docstring),
    isPrivate: module.name.startsWith('_'),
    location: module.location,
    path: module.path,
    exports: module.exports,
    imports: module.imports.map(buildImportLine),
    classes,
    functions,
    variables,
  })
}

export const buildApiPackage = (modules: PyModule[], options: BuildOptions): ApiPackage => {
  const includePrivate = options.includePrivate ?? false
  const generatedAt = options.generatedAt ?? new Date().toISOString()

  const apiModules = modules.map((module) => buildModule(module, includePrivate))

  return ApiPackageSchema.parse({
    name: options.name,
    root: options.root,
    generatedAt,
    modules: apiModules,
  })
}

export const buildApiIndex = (
  api: ApiPackage,
): Map<string, ApiModule | ApiClass | ApiFunction | ApiMethod | ApiVariable> => {
  const index = new Map<string, ApiModule | ApiClass | ApiFunction | ApiMethod | ApiVariable>()

  for (const module of api.modules) {
    index.set(module.qualname, module)

    for (const klass of module.classes) {
      index.set(klass.qualname, klass)
      for (const method of klass.methods) {
        index.set(method.qualname, method)
      }
      for (const attribute of klass.attributes) {
        index.set(attribute.qualname, attribute)
      }
    }

    for (const fn of module.functions) {
      index.set(fn.qualname, fn)
    }

    for (const variable of module.variables) {
      index.set(variable.qualname, variable)
    }
  }

  return index
}
