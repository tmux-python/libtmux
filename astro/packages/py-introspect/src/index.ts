import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mergePythonPath, type PythonCommand, runPythonJson } from '@libtmux/py-bridge'
import { type PyIntrospectPayload, PyIntrospectPayloadSchema } from '@libtmux/schema'

export type IntrospectOptions = {
  root?: string
  includePrivate?: boolean
  annotationFormat?: 'string' | 'value'
  pythonCommand?: PythonCommand
  env?: NodeJS.ProcessEnv
  cwd?: string
  timeoutMs?: number
}

export const resolveSidecarRoot = (): string => {
  const here = path.dirname(fileURLToPath(import.meta.url))
  return path.resolve(here, '../../../python/pyautodoc_sidecar')
}

const buildEnv = (env: NodeJS.ProcessEnv | undefined, sidecarRoot: string): NodeJS.ProcessEnv => {
  const pythonPath = path.join(sidecarRoot, 'src')
  return mergePythonPath(env, pythonPath)
}

export const introspectModule = async (
  moduleName: string,
  options: IntrospectOptions = {},
): Promise<PyIntrospectPayload> => {
  const sidecarRoot = resolveSidecarRoot()
  const args = ['-m', 'pyautodoc_sidecar', 'introspect-module', '--module', moduleName]

  if (options.root) {
    args.push('--root', options.root)
  }

  if (options.includePrivate) {
    args.push('--include-private')
  }

  if (options.annotationFormat) {
    args.push('--annotation-format', options.annotationFormat)
  }

  const payload = await runPythonJson(args, {
    pythonCommand: options.pythonCommand,
    cwd: options.cwd ?? sidecarRoot,
    env: buildEnv(options.env, sidecarRoot),
    timeoutMs: options.timeoutMs,
  })

  return PyIntrospectPayloadSchema.parse(payload)
}

export const introspectPackage = async (
  packageName: string,
  options: IntrospectOptions = {},
): Promise<PyIntrospectPayload> => {
  const sidecarRoot = resolveSidecarRoot()
  const args = ['-m', 'pyautodoc_sidecar', 'introspect-package', '--package', packageName]

  if (options.root) {
    args.push('--root', options.root)
  }

  if (options.includePrivate) {
    args.push('--include-private')
  }

  if (options.annotationFormat) {
    args.push('--annotation-format', options.annotationFormat)
  }

  const payload = await runPythonJson(args, {
    pythonCommand: options.pythonCommand,
    cwd: options.cwd ?? sidecarRoot,
    env: buildEnv(options.env, sidecarRoot),
    timeoutMs: options.timeoutMs,
  })

  return PyIntrospectPayloadSchema.parse(payload)
}
