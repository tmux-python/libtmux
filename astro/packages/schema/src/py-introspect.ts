import { z } from 'zod'
import { ProtocolVersionSchema } from './common.ts'
import { PyParameterKindSchema } from './py-parse.ts'

const DocstringFormatSchema = z.enum(['rst', 'markdown', 'plain', 'unknown'])

const DocstringFieldsSchema = z.object({
  docstringRaw: z.string().nullable(),
  docstringFormat: DocstringFormatSchema,
  docstringHtml: z.string().nullable(),
  summary: z.string().nullable(),
})

const AnnotationFieldsSchema = z.object({
  annotationText: z.string().nullable(),
  annotationValue: z.string().nullable(),
})

export const PyIntrospectParameterSchema = z
  .object({
    name: z.string(),
    kind: PyParameterKindSchema,
    default: z.string().nullable(),
  })
  .merge(AnnotationFieldsSchema)

export const PyIntrospectFunctionSchema = z
  .object({
    kind: z.enum(['function', 'method']),
    name: z.string(),
    qualname: z.string(),
    module: z.string(),
    signature: z.string(),
    parameters: z.array(PyIntrospectParameterSchema),
    returns: AnnotationFieldsSchema,
    isAsync: z.boolean(),
    isPrivate: z.boolean(),
  })
  .merge(DocstringFieldsSchema)

export const PyIntrospectVariableSchema = z
  .object({
    kind: z.literal('variable'),
    name: z.string(),
    qualname: z.string(),
    module: z.string(),
    value: z.string().nullable(),
    isPrivate: z.boolean(),
  })
  .merge(AnnotationFieldsSchema)
  .merge(DocstringFieldsSchema)

export const PyIntrospectClassSchema = z
  .object({
    kind: z.literal('class'),
    name: z.string(),
    qualname: z.string(),
    module: z.string(),
    bases: z.array(z.string()),
    methods: z.array(PyIntrospectFunctionSchema),
    attributes: z.array(PyIntrospectVariableSchema),
    isPrivate: z.boolean(),
  })
  .merge(DocstringFieldsSchema)

export const PyIntrospectModuleSchema = z
  .object({
    kind: z.literal('module'),
    name: z.string(),
    qualname: z.string(),
    classes: z.array(PyIntrospectClassSchema),
    functions: z.array(PyIntrospectFunctionSchema),
    variables: z.array(PyIntrospectVariableSchema),
    isPrivate: z.boolean(),
  })
  .merge(DocstringFieldsSchema)

export const PyIntrospectPayloadSchema = z.object({
  protocolVersion: ProtocolVersionSchema,
  modules: z.array(PyIntrospectModuleSchema),
})

export type PyIntrospectParameter = z.infer<typeof PyIntrospectParameterSchema>
export type PyIntrospectFunction = z.infer<typeof PyIntrospectFunctionSchema>
export type PyIntrospectVariable = z.infer<typeof PyIntrospectVariableSchema>
export type PyIntrospectClass = z.infer<typeof PyIntrospectClassSchema>
export type PyIntrospectModule = z.infer<typeof PyIntrospectModuleSchema>
export type PyIntrospectPayload = z.infer<typeof PyIntrospectPayloadSchema>
