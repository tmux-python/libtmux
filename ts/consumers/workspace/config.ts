import { z } from "zod";

/**
 * A tmuxp-shaped workspace description.
 *
 * The field names follow tmuxp's snake_case config vocabulary rather than this
 * package's camelCase API, because the config is data a user already has on
 * disk. Renaming their keys to suit our API would break the very compatibility
 * the format is here to provide.
 */
const paneSchema = z.union([
  z.string(),
  z.object({
    focus: z.boolean().optional(),
    shell_command: z.union([z.string(), z.array(z.string())]).optional(),
    start_directory: z.string().optional(),
  }),
]);

const windowSchema = z.object({
  focus: z.boolean().optional(),
  layout: z.string().optional(),
  options: z.record(z.string(), z.string()).optional(),
  panes: z.array(paneSchema).default([]),
  start_directory: z.string().optional(),
  window_name: z.string().optional(),
});

export const workspaceSchema = z.object({
  options: z.record(z.string(), z.string()).optional(),
  session_name: z.string(),
  start_directory: z.string().optional(),
  windows: z.array(windowSchema).default([]),
});

export type Workspace = z.infer<typeof workspaceSchema>;
export type WorkspaceWindow = z.infer<typeof windowSchema>;
export type WorkspacePane = z.infer<typeof paneSchema>;

/** Parse a YAML or JSON workspace, rejecting anything the schema does not allow. */
export function parseWorkspace(source: string): Workspace {
  return workspaceSchema.parse(Bun.YAML.parse(source));
}

/** Normalize a pane entry to the commands it should run. */
export function paneCommands(pane: WorkspacePane): readonly string[] {
  if (typeof pane === "string") return [pane];
  const command = pane.shell_command;
  if (command === undefined) return [];
  return typeof command === "string" ? [command] : command;
}

/** A pane's start directory, falling back to its window's and then the session's. */
export function paneStartDirectory(
  pane: WorkspacePane,
  window: WorkspaceWindow,
  workspace: Workspace,
): string | undefined {
  if (typeof pane !== "string" && pane.start_directory !== undefined) return pane.start_directory;
  return window.start_directory ?? workspace.start_directory;
}
