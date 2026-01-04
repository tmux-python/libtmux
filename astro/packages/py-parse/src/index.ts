import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mergePythonPath, type PythonCommand, runPythonJson } from '@libtmux/py-bridge'
import {
  type PyImport,
  type PyModule,
  PyModuleSchema,
  type PyNode,
  PyNodeSchema,
  PyParsePayloadSchema,
} from '@libtmux/schema'

export type ScanOptions = {
  root: string
  paths: string[]
  includePrivate?: boolean
  pythonCommand?: PythonCommand
  env?: NodeJS.ProcessEnv
  cwd?: string
  timeoutMs?: number
}

const resolveSidecarRoot = (): string => {
  const here = path.dirname(fileURLToPath(import.meta.url))
  return path.resolve(here, '../../../python/pyautodoc_sidecar')
}

const buildEnv = (env: NodeJS.ProcessEnv | undefined, sidecarRoot: string): NodeJS.ProcessEnv => {
  const pythonPath = path.join(sidecarRoot, 'src')
  return mergePythonPath(env, pythonPath)
}

export const scanPythonPaths = async (options: ScanOptions): Promise<PyModule[]> => {
  const sidecarRoot = resolveSidecarRoot()
  const args = ['-m', 'pyautodoc_sidecar', 'parse-files', '--root', options.root, '--paths', ...options.paths]

  if (options.includePrivate) {
    args.push('--include-private')
  }

  const payload = await runPythonJson(args, {
    pythonCommand: options.pythonCommand,
    cwd: options.cwd ?? sidecarRoot,
    env: buildEnv(options.env, sidecarRoot),
    timeoutMs: options.timeoutMs,
  })

  return PyParsePayloadSchema.parse(payload).modules
}

export const scanPythonModule = async (
  root: string,
  modulePath: string,
  options: Omit<ScanOptions, 'root' | 'paths'> = {},
): Promise<PyModule> => {
  const modules = await scanPythonPaths({
    root,
    paths: [modulePath],
    ...options,
  })

  if (modules.length === 0) {
    throw new Error(`No modules found for ${modulePath}`)
  }

  return PyModuleSchema.parse(modules[0])
}

export const collectImports = (modules: PyModule[]): PyImport[] => modules.flatMap((module) => module.imports)

export type PyQualifiedNode = Exclude<PyNode, PyImport>

export function* walkPyNodes(modules: PyModule[]): Generator<PyQualifiedNode> {
  for (const module of modules) {
    for (const item of module.items) {
      if (item.kind === 'import') {
        continue
      }
      yield item
      if (item.kind === 'class') {
        for (const method of item.methods) {
          yield method
        }
        for (const attribute of item.attributes) {
          yield attribute
        }
      }
    }
  }
}

export const parsePyNode = (input: unknown): PyNode => PyNodeSchema.parse(input)

export type { PyImport, PyModule, PyNode }
export { PyModuleSchema, PyNodeSchema, PyParsePayloadSchema }
