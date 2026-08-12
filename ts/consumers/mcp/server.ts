import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { Server } from "../../src/server.js";

/**
 * An MCP server exposing a tmux server through libtmux.
 *
 * Every tool acquires its own snapshot. Two concurrent requests therefore
 * observe their own instants rather than sharing mutable state, which is the
 * property the acquisition design was chosen for.
 */
export function createTmuxMcpServer(tmux: Server): McpServer {
  const mcp = new McpServer({ name: "libtmux", version: "0.1.0" });

  mcp.registerTool(
    "list_sessions",
    {
      description: "List every tmux session with its id, name, and window count.",
      inputSchema: {},
      title: "List sessions",
    },
    async () => {
      const snapshot = await tmux.snapshot();
      // Count windows from the snapshot already in hand rather than asking each
      // session, which would resolve the same window set once per session.
      const sessions = snapshot.sessions.toArray().map((session) => ({
        id: session.session_id,
        name: session.session_name,
        windows: snapshot.windows.filter((window) => window.session_id === session.session_id)
          .length,
      }));
      return { content: [{ text: JSON.stringify(sessions, null, 2), type: "text" }] };
    },
  );

  mcp.registerTool(
    "list_panes",
    {
      description: "List panes, optionally restricted to one session by name.",
      inputSchema: { session: z.string().optional() },
      title: "List panes",
    },
    async ({ session }) => {
      const snapshot = await tmux.snapshot();
      const panes = snapshot.panes
        .filter((pane) => session === undefined || pane.session_name === session)
        .toArray()
        .map((pane) => ({
          command: pane.pane_current_command,
          id: pane.pane_id,
          session: pane.session_name,
          window: pane.window_name,
        }));
      return { content: [{ text: JSON.stringify(panes, null, 2), type: "text" }] };
    },
  );

  mcp.registerTool(
    "capture_pane",
    {
      description: "Capture a pane's visible contents, or reach into its scrollback.",
      inputSchema: { paneId: z.string(), start: z.number().int().optional() },
      title: "Capture pane",
    },
    async ({ paneId, start }) => {
      const snapshot = await tmux.snapshot();
      const pane = snapshot.panes.filter((candidate) => candidate.pane_id === paneId).first();
      if (pane === undefined) {
        return { content: [{ text: `No pane ${paneId}`, type: "text" }], isError: true };
      }
      const lines = await pane.capture(start === undefined ? {} : { start });
      return { content: [{ text: lines.join("\n"), type: "text" }] };
    },
  );

  mcp.registerTool(
    "send_keys",
    {
      description: "Send keys to a pane, optionally literally and without Enter.",
      inputSchema: {
        enter: z.boolean().optional(),
        keys: z.string(),
        literal: z.boolean().optional(),
        paneId: z.string(),
      },
      title: "Send keys",
    },
    async ({ enter, keys, literal, paneId }) => {
      const snapshot = await tmux.snapshot();
      const pane = snapshot.panes.filter((candidate) => candidate.pane_id === paneId).first();
      if (pane === undefined) {
        return { content: [{ text: `No pane ${paneId}`, type: "text" }], isError: true };
      }
      await pane.sendKeys(keys, {
        ...(enter === undefined ? {} : { enter }),
        ...(literal === undefined ? {} : { literal }),
      });
      return { content: [{ text: `Sent to ${paneId}`, type: "text" }] };
    },
  );

  mcp.registerTool(
    "new_session",
    {
      description: "Create a detached tmux session.",
      inputSchema: { name: z.string().optional() },
      title: "New session",
    },
    async ({ name }) => {
      const session = await tmux.newSession(name === undefined ? {} : { name });
      return {
        content: [
          {
            text: `Created ${session.session_name ?? ""} (${session.session_id ?? ""})`,
            type: "text",
          },
        ],
      };
    },
  );

  return mcp;
}

/** Serve over stdio when run directly. */
export async function main(): Promise<void> {
  const mcp = createTmuxMcpServer(new Server());
  await mcp.connect(new StdioServerTransport());
}
