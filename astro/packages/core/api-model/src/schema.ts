import { z } from 'zod'

export const ApiLocationSchema = z.object({
  lineno: z.number().int().nonnegative(),
  colOffset: z.number().int().nonnegative(),
  endLineno: z.number().int().nonnegative().nullable(),
  endColOffset: z.number().int().nonnegative().nullable(),
})

export const ApiParameterSchema = z.object({
  name: z.string(),
  kind: z.enum(['positional-only', 'positional-or-keyword', 'var-positional', 'keyword-only', 'var-keyword']),
  annotation: z.string().nullable(),
  default: z.string().nullable(),
  signature: z.string(),
})

export const ApiBaseSchema = z.object({
  name: z.string(),
  qualname: z.string(),
  docstring: z.string().nullable(),
  summary: z.string().nullable(),
  isPrivate: z.boolean(),
  location: ApiLocationSchema,
})

export const ApiFunctionSchema = ApiBaseSchema.extend({
  kind: z.literal('function'),
  signature: z.string(),
  parameters: z.array(ApiParameterSchema),
  returns: z.string().nullable(),
  decorators: z.array(z.string()),
  isAsync: z.boolean(),
})

export const ApiMethodSchema = ApiFunctionSchema.extend({
  kind: z.literal('method'),
  className: z.string(),
})

export const ApiVariableSchema = ApiBaseSchema.extend({
  kind: z.literal('variable'),
  annotation: z.string().nullable(),
  value: z.string().nullable(),
})

export const ApiClassSchema = ApiBaseSchema.extend({
  kind: z.literal('class'),
  bases: z.array(z.string()),
  decorators: z.array(z.string()),
  methods: z.array(ApiMethodSchema),
  attributes: z.array(ApiVariableSchema),
})

export const ApiModuleSchema = ApiBaseSchema.extend({
  kind: z.literal('module'),
  path: z.string(),
  exports: z.array(z.string()),
  imports: z.array(z.string()),
  classes: z.array(ApiClassSchema),
  functions: z.array(ApiFunctionSchema),
  variables: z.array(ApiVariableSchema),
})

export const ApiPackageSchema = z.object({
  name: z.string(),
  root: z.string(),
  generatedAt: z.string(),
  modules: z.array(ApiModuleSchema),
})

export type ApiLocation = z.infer<typeof ApiLocationSchema>
export type ApiParameter = z.infer<typeof ApiParameterSchema>
export type ApiBase = z.infer<typeof ApiBaseSchema>
export type ApiFunction = z.infer<typeof ApiFunctionSchema>
export type ApiMethod = z.infer<typeof ApiMethodSchema>
export type ApiVariable = z.infer<typeof ApiVariableSchema>
export type ApiClass = z.infer<typeof ApiClassSchema>
export type ApiModule = z.infer<typeof ApiModuleSchema>
export type ApiPackage = z.infer<typeof ApiPackageSchema>
