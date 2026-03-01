import type { ApiClass, ApiFunction, ApiMethod, ApiModule, ApiPackage, ApiVariable } from '@libtmux/api-model'
import { parseRst, type RoleResolver, renderHtml } from '@libtmux/rst-lite'

export type DocstringRenderMode = 'introspect' | 'rst-lite' | 'none'

export type DocstringRenderOptions = {
  mode?: DocstringRenderMode
  roleResolver?: RoleResolver
}

const shouldRender = (docstring: string | null, format: string): boolean => {
  if (!docstring) {
    return false
  }
  if (format === 'markdown') {
    return false
  }
  return true
}

const renderDocstring = (docstring: string | null, format: string, roleResolver?: RoleResolver): string | null => {
  if (!shouldRender(docstring, format)) {
    return null
  }
  const doc = parseRst(docstring ?? '')
  return renderHtml(doc, { roleResolver })
}

const applyToFunction = (fn: ApiFunction, roleResolver?: RoleResolver): ApiFunction => {
  return {
    ...fn,
    docstringHtml: renderDocstring(fn.docstring, fn.docstringFormat, roleResolver),
  }
}

const applyToMethod = (method: ApiMethod, roleResolver?: RoleResolver): ApiMethod => {
  return {
    ...method,
    docstringHtml: renderDocstring(method.docstring, method.docstringFormat, roleResolver),
  }
}

const applyToVariable = (variable: ApiVariable, roleResolver?: RoleResolver): ApiVariable => {
  return {
    ...variable,
    docstringHtml: renderDocstring(variable.docstring, variable.docstringFormat, roleResolver),
  }
}

const applyToClass = (klass: ApiClass, roleResolver?: RoleResolver): ApiClass => {
  return {
    ...klass,
    docstringHtml: renderDocstring(klass.docstring, klass.docstringFormat, roleResolver),
    methods: klass.methods.map((method) => applyToMethod(method, roleResolver)),
    attributes: klass.attributes.map((attribute) => applyToVariable(attribute, roleResolver)),
  }
}

const applyToModule = (module: ApiModule, roleResolver?: RoleResolver): ApiModule => {
  return {
    ...module,
    docstringHtml: renderDocstring(module.docstring, module.docstringFormat, roleResolver),
    classes: module.classes.map((klass) => applyToClass(klass, roleResolver)),
    functions: module.functions.map((fn) => applyToFunction(fn, roleResolver)),
    variables: module.variables.map((variable) => applyToVariable(variable, roleResolver)),
  }
}

export const renderDocstrings = (api: ApiPackage, options: DocstringRenderOptions = {}): ApiPackage => {
  const mode = options.mode ?? 'introspect'
  if (mode !== 'rst-lite') {
    return api
  }

  return {
    ...api,
    modules: api.modules.map((module) => applyToModule(module, options.roleResolver)),
  }
}
