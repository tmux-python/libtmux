import { LibTmuxException } from "../../exc.js";

export interface TmuxEnvironment {
  readonly socketPath: string;
  readonly paneId: string;
}

/**
 * Read the tmux server and pane a process is running inside.
 *
 * `$TMUX` is `socket-path,pid,session-id`, and a socket path may itself contain
 * commas, so the split is anchored from the right. The exported session id is
 * deliberately ignored: it goes stale when a pane moves between sessions, while
 * `$TMUX_PANE` stays correct, so the session is resolved through the pane.
 */
export function readTmuxEnvironment(
  environment: Readonly<Record<string, string | undefined>>,
): TmuxEnvironment {
  const tmux = environment.TMUX;
  if (tmux === undefined || tmux === "") {
    throw new LibTmuxException("$TMUX is not set; this process is not inside tmux");
  }
  const separator = tmux.lastIndexOf(",", tmux.lastIndexOf(",") - 1);
  if (separator <= 0) {
    throw new LibTmuxException(`$TMUX is malformed: ${tmux}`);
  }
  const socketPath = tmux.slice(0, separator);

  const paneId = environment.TMUX_PANE;
  if (paneId === undefined || !/^%\d+$/.test(paneId)) {
    throw new LibTmuxException(`$TMUX_PANE is missing or malformed: ${paneId ?? "<unset>"}`);
  }
  return { paneId, socketPath };
}
