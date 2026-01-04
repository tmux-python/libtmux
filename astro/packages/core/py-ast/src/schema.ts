import { z } from 'zod'

export const PyLocationSchema = z.object({
  lineno: z.number().int().nonnegative(),
  colOffset: z.number().int().nonnegative(),
  endLineno: z.number().int().nonnegative().nullable(),
  endColOffset: z.number().int().nonnegative().nullable(),
})

export const PyParameterKindSchema = z.enum([
  'positional-only',
  'positional-or-keyword',
  'var-positional',
  'keyword-only',
  'var-keyword',
])

export const PyParameterSchema = z.object({
  name: z.string(),
  kind: PyParameterKindSchema,
  annotation: z.string().nullable(),
  default: z.string().nullable(),
})

export const PyVariableSchema = z.object({
  kind: z.literal('variable'),
  name: z.string(),
  qualname: z.string(),
  annotation: z.string().nullable(),
  value: z.string().nullable(),
  docstring: z.string().nullable(),
  isPrivate: z.boolean(),
  location: PyLocationSchema,
})

export const PyFunctionSchema = z.object({
  kind: z.literal('function'),
  name: z.string(),
  qualname: z.string(),
  docstring: z.string().nullable(),
  decorators: z.array(z.string()),
  parameters: z.array(PyParameterSchema),
  returns: z.string().nullable(),
  isAsync: z.boolean(),
  isPrivate: z.boolean(),
  location: PyLocationSchema,
})

export const PyClassSchema = z.object({
  kind: z.literal('class'),
  name: z.string(),
  qualname: z.string(),
  docstring: z.string().nullable(),
  bases: z.array(z.string()),
  decorators: z.array(z.string()),
  methods: z.array(PyFunctionSchema),
  attributes: z.array(PyVariableSchema),
  isPrivate: z.boolean(),
  location: PyLocationSchema,
})

export const PyImportSchema = z.object({
  kind: z.literal('import'),
  module: z.string().nullable(),
  names: z.array(z.string()),
  level: z.number().int().nonnegative().nullable(),
  location: PyLocationSchema,
})

export const PyNodeSchema = z.discriminatedUnion('kind', [
  PyClassSchema,
  PyFunctionSchema,
  PyVariableSchema,
  PyImportSchema,
])

export const PyModuleSchema = z.object({
  kind: z.literal('module'),
  name: z.string(),
  qualname: z.string(),
  path: z.string(),
  docstring: z.string().nullable(),
  items: z.array(PyNodeSchema),
  imports: z.array(PyImportSchema),
  exports: z.array(z.string()),
  isPackage: z.boolean(),
  location: PyLocationSchema,
})

export const PyModuleArraySchema = z.array(PyModuleSchema)

export type PyLocation = z.infer<typeof PyLocationSchema>
export type PyParameter = z.infer<typeof PyParameterSchema>
export type PyVariable = z.infer<typeof PyVariableSchema>
export type PyFunction = z.infer<typeof PyFunctionSchema>
export type PyClass = z.infer<typeof PyClassSchema>
export type PyImport = z.infer<typeof PyImportSchema>
export type PyNode = z.infer<typeof PyNodeSchema>
export type PyModule = z.infer<typeof PyModuleSchema>
