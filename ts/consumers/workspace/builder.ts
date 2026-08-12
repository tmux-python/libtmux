import type { Server } from "../../src/server.js";
import type { Session } from "../../src/session.js";
import {
  paneCommands,
  paneStartDirectory,
  type Workspace,
  type WorkspaceWindow,
} from "./config.js";

/**
 * Build a workspace into a real tmux session.
 *
 * tmux gives every new session a window and every new window a pane, so the
 * first window and first pane of each level are adopted rather than created.
 * Creating them anyway is the classic workspace-builder bug that leaves an
 * empty leading window behind.
 */
export async function buildWorkspace(server: Server, workspace: Workspace): Promise<Session> {
  const session = await server.newSession({
    name: workspace.session_name,
    ...(workspace.start_directory === undefined
      ? {}
      : { startDirectory: workspace.start_directory }),
    ...(workspace.windows[0]?.window_name === undefined
      ? {}
      : { windowName: workspace.windows[0].window_name }),
  });

  for (const [option, value] of Object.entries(workspace.options ?? {})) {
    // eslint-disable-next-line no-await-in-loop -- Later options may depend on earlier ones.
    await session.setOption(option, value);
  }

  for (const [index, window] of workspace.windows.entries()) {
    // eslint-disable-next-line no-await-in-loop -- Window order is observable, so creation is sequential.
    await buildWindow(server, session, window, workspace, index === 0);
  }

  return session;
}

async function buildWindow(
  server: Server,
  session: Session,
  window: WorkspaceWindow,
  workspace: Workspace,
  adoptFirst: boolean,
): Promise<void> {
  const startDirectory = window.start_directory ?? workspace.start_directory;
  const target = adoptFirst
    ? (await session.windows()).at(0)
    : await session.newWindow({
        ...(window.window_name === undefined ? {} : { name: window.window_name }),
        ...(startDirectory === undefined ? {} : { startDirectory }),
      });
  if (target === undefined) throw new Error("session reported no window to build into");

  for (const [option, value] of Object.entries(window.options ?? {})) {
    // eslint-disable-next-line no-await-in-loop -- Later options may depend on earlier ones.
    await target.setOption(option, value);
  }

  const panes = window.panes.length === 0 ? [""] : window.panes;
  for (const [index, pane] of panes.entries()) {
    const directory = paneStartDirectory(pane, window, workspace);
    // The window already owns one pane, so only later entries split.
    const handle =
      index === 0
        ? // eslint-disable-next-line no-await-in-loop -- Pane order is observable.
          (await target.panes()).at(0)
        : // eslint-disable-next-line no-await-in-loop -- Each split follows the previous one.
          await target.split(directory === undefined ? {} : { startDirectory: directory });
    if (handle === undefined) throw new Error("window reported no pane to build into");

    for (const command of paneCommands(pane)) {
      if (command === "") continue;
      // eslint-disable-next-line no-await-in-loop -- Commands run in the order written.
      await handle.sendKeys(command);
    }
  }
}
