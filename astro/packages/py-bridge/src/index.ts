import path from 'node:path'
import { execa } from 'execa'

export type PythonCommand = [string, ...string[]]

export type PythonRunOptions = {
  pythonCommand?: PythonCommand
  env?: NodeJS.ProcessEnv
  cwd?: string
  timeoutMs?: number
}

const DEFAULT_COMMAND_ENV = 'LIBTMUX_PYTHON_COMMAND'
const DEFAULT_COMMAND: PythonCommand = ['uv', 'run', 'python']
const FALLBACK_COMMAND: PythonCommand = process.platform === 'win32' ? ['python'] : ['python3']

export const parsePythonCommand = (value: string | undefined): PythonCommand | undefined => {
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

export const resolvePythonCommand = async (override?: PythonCommand): Promise<PythonCommand> => {
  if (override) {
    return override
  }

  const fromEnv = parsePythonCommand(process.env[DEFAULT_COMMAND_ENV])
  if (fromEnv) {
    return fromEnv
  }

  if (await canRun(DEFAULT_COMMAND)) {
    return DEFAULT_COMMAND
  }

  return FALLBACK_COMMAND
}

export const mergePythonPath = (env: NodeJS.ProcessEnv | undefined, extraPath: string): NodeJS.ProcessEnv => {
  const current = env?.PYTHONPATH ?? process.env.PYTHONPATH ?? ''
  const pythonPath = [extraPath, current].filter(Boolean).join(path.delimiter)

  return {
    ...process.env,
    ...env,
    PYTHONPATH: pythonPath,
  }
}

export const runPythonJson = async (args: string[], options: PythonRunOptions = {}): Promise<unknown> => {
  const command = await resolvePythonCommand(options.pythonCommand)
  const result = await execa(command[0], [...command.slice(1), ...args], {
    cwd: options.cwd,
    env: options.env,
    reject: true,
    timeout: options.timeoutMs,
  })

  return JSON.parse(result.stdout) as unknown
}
