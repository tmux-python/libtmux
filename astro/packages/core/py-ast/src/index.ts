import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { execa } from 'execa'
import {
  type PyImport,
  type PyModule,
  PyModuleArraySchema,
  PyModuleSchema,
  type PyNode,
  PyNodeSchema,
} from './schema.ts'

export type PythonCommand = [string, ...string[]]

export type ScanOptions = {
  root: string
  paths: string[]
  includePrivate?: boolean
  pythonCommand?: PythonCommand
  env?: NodeJS.ProcessEnv
  cwd?: string
}

const DEFAULT_COMMAND_ENV = 'LIBTMUX_PYTHON_COMMAND'

const FALLBACK_COMMAND: PythonCommand = process.platform === 'win32' ? ['python'] : ['python3']

const DEFAULT_COMMAND: PythonCommand = ['uvx', 'python']

const parseCommand = (value: string | undefined): PythonCommand | undefined => {
  if (!value) {
    return undefined
  }

  const parts = value.split(' ').filter(Boolean)
  if (parts.length === 0) {
    return undefined
  }

  return parts as PythonCommand
}

const canRun = async (command: PythonCommand): Promise<boolean> => {
  const result = await execa(command[0], [...command.slice(1), '--version'], {
    reject: false,
    stdin: 'ignore',
  })

  return result.exitCode === 0
}

const resolvePythonCommand = async (override?: PythonCommand): Promise<PythonCommand> => {
  if (override) {
    return override
  }

  const fromEnv = parseCommand(process.env[DEFAULT_COMMAND_ENV])
  if (fromEnv) {
    return fromEnv
  }

  if (await canRun(DEFAULT_COMMAND)) {
    return DEFAULT_COMMAND
  }

  return FALLBACK_COMMAND
}

const resolveScriptPath = (): string => {
  const here = path.dirname(fileURLToPath(import.meta.url))
  return path.resolve(here, '../python/scan.py')
}

export const scanPythonPaths = async (options: ScanOptions): Promise<PyModule[]> => {
  const scriptPath = resolveScriptPath()
  const command = await resolvePythonCommand(options.pythonCommand)
  const args = [scriptPath, '--root', options.root, '--paths', ...options.paths]

  if (options.includePrivate) {
    args.push('--include-private')
  }

  const result = await execa(command[0], [...command.slice(1), ...args], {
    cwd: options.cwd,
    env: options.env,
    reject: true,
  })

  const parsed = JSON.parse(result.stdout) as unknown
  return PyModuleArraySchema.parse(parsed)
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

export * from './schema.ts'
