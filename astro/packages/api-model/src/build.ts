import type {
  PyClass,
  PyFunction,
  PyImport,
  PyIntrospectClass,
  PyIntrospectFunction,
  PyIntrospectModule,
  PyIntrospectParameter,
  PyIntrospectVariable,
  PyModule,
  PyParameter,
  PyVariable,
} from '@libtmux/schema'
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
} from './schema.ts'

export type BuildOptions = {
  name: string
  root: string
  includePrivate?: boolean
  generatedAt?: string
  introspection?: PyIntrospectModule[]
}

const summarizeDocstring = (docstring: string | null): string | null => {
  if (!docstring) {
    return null
  }

  const [firstLine] = docstring.trim().split('\n')
  return firstLine?.trim() || null
}

const formatParameterSignature = (param: {
  name: string
  kind: string
  annotation?: string | null
  annotationText?: string | null
  default?: string | null
}): string => {
  let name = param.name

  if (param.kind === 'var-positional') {
    name = `*${name}`
  }

  if (param.kind === 'var-keyword') {
    name = `**${name}`
  }

  const annotation = param.annotationText ?? param.annotation
  if (annotation) {
    name = `${name}: ${annotation}`
  }

  if (param.default) {
    name = `${name} = ${param.default}`
  }

  return name
}

const buildParameter = (param: PyParameter, introspected?: PyIntrospectParameter): ApiParameter =>
  ApiParameterSchema.parse({
    name: param.name,
    kind: introspected?.kind ?? param.kind,
    annotation: introspected?.annotationText ?? param.annotation,
    annotationValue: introspected?.annotationValue ?? null,
    default: introspected?.default ?? param.default,
    signature: formatParameterSignature({
      name: param.name,
      kind: introspected?.kind ?? param.kind,
      annotationText: introspected?.annotationText ?? null,
      annotation: param.annotation,
      default: introspected?.default ?? param.default,
    }),
  })

const buildSignature = (
  parameters: Array<
    { kind: string } & {
      name: string
      annotation?: string | null
      annotationText?: string | null
      default?: string | null
    }
  >,
): string => {
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

const stripSignatureReturn = (signature: string): string => {
  const arrowIndex = signature.lastIndexOf(' -> ')
  if (arrowIndex === -1) {
    return signature
  }

  return signature.slice(0, arrowIndex)
}

const buildDocFields = (
  docstring: string | null,
  introspected?: {
    docstringRaw: string | null
    docstringFormat: 'rst' | 'markdown' | 'plain' | 'unknown'
    docstringHtml: string | null
    summary: string | null
  },
) => {
  const raw = introspected?.docstringRaw ?? docstring
  return {
    docstring: raw,
    docstringFormat: introspected?.docstringFormat ?? 'unknown',
    docstringHtml: introspected?.docstringHtml ?? null,
    summary: introspected?.summary ?? summarizeDocstring(raw),
  }
}

const buildFunction = (fn: PyFunction, introspected?: PyIntrospectFunction): ApiFunction => {
  const parameters = fn.parameters.map((param) =>
    buildParameter(
      param,
      introspected?.parameters.find((item) => item.name === param.name),
    ),
  )

  return ApiFunctionSchema.parse({
    ...fn,
    kind: 'function',
    signature: introspected ? stripSignatureReturn(introspected.signature) : buildSignature(parameters),
    parameters,
    returns: introspected?.returns.annotationText ?? fn.returns,
    returnsValue: introspected?.returns.annotationValue ?? null,
    isAsync: introspected?.isAsync ?? fn.isAsync,
    ...buildDocFields(fn.docstring, introspected),
  })
}

const buildMethod = (fn: PyFunction, className: string, introspected?: PyIntrospectFunction): ApiMethod => {
  const parameters = fn.parameters.map((param) =>
    buildParameter(
      param,
      introspected?.parameters.find((item) => item.name === param.name),
    ),
  )

  return ApiMethodSchema.parse({
    ...fn,
    kind: 'method',
    signature: introspected ? stripSignatureReturn(introspected.signature) : buildSignature(parameters),
    parameters,
    returns: introspected?.returns.annotationText ?? fn.returns,
    returnsValue: introspected?.returns.annotationValue ?? null,
    isAsync: introspected?.isAsync ?? fn.isAsync,
    ...buildDocFields(fn.docstring, introspected),
    className,
  })
}

const buildVariable = (variable: PyVariable, introspected?: PyIntrospectVariable): ApiVariable =>
  ApiVariableSchema.parse({
    ...variable,
    annotation: introspected?.annotationText ?? variable.annotation,
    annotationValue: introspected?.annotationValue ?? null,
    value: introspected?.value ?? variable.value,
    ...buildDocFields(variable.docstring, introspected),
  })

const indexByQualname = <T extends { qualname: string }>(items: T[] | undefined): Map<string, T> => {
  if (!items) {
    return new Map()
  }

  return new Map(items.map((item) => [item.qualname, item]))
}

const buildClass = (klass: PyClass, includePrivate: boolean, introspected?: PyIntrospectClass): ApiClass => {
  const methodIndex = indexByQualname(introspected?.methods)
  const attributeIndex = indexByQualname(introspected?.attributes)

  const methods = klass.methods
    .filter((method) => includePrivate || !method.isPrivate)
    .map((method) => buildMethod(method, klass.name, methodIndex.get(method.qualname)))

  const attributes = klass.attributes
    .filter((attribute) => includePrivate || !attribute.isPrivate)
    .map((attribute) => buildVariable(attribute, attributeIndex.get(attribute.qualname)))

  return ApiClassSchema.parse({
    ...klass,
    kind: 'class',
    bases: introspected?.bases ?? klass.bases,
    ...buildDocFields(klass.docstring, introspected),
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

const buildModule = (module: PyModule, includePrivate: boolean, introspected?: PyIntrospectModule): ApiModule => {
  const classIndex = indexByQualname(introspected?.classes)
  const functionIndex = indexByQualname(introspected?.functions)
  const variableIndex = indexByQualname(introspected?.variables)

  const classes = module.items
    .filter((item): item is PyClass => item.kind === 'class')
    .filter((item) => includePrivate || !item.isPrivate)
    .map((item) => buildClass(item, includePrivate, classIndex.get(item.qualname)))

  const functions = module.items
    .filter((item): item is PyFunction => item.kind === 'function')
    .filter((item) => includePrivate || !item.isPrivate)
    .map((item) => buildFunction(item, functionIndex.get(item.qualname)))

  const variables = module.items
    .filter((item): item is PyVariable => item.kind === 'variable')
    .filter((item) => includePrivate || !item.isPrivate)
    .map((item) => buildVariable(item, variableIndex.get(item.qualname)))

  return ApiModuleSchema.parse({
    kind: 'module',
    name: module.name,
    qualname: module.qualname,
    ...buildDocFields(module.docstring, introspected),
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
  const introspectionIndex = indexByQualname(options.introspection)

  const apiModules = modules.map((module) =>
    buildModule(module, includePrivate, introspectionIndex.get(module.qualname)),
  )

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
