import type { Server, TmuxEvent, TmuxEventStream } from "../../src/index.js";

/**
 * The disposal and narrowing guarantees `watch()` advertises, checked by tsc.
 *
 * The integration suite calls `Symbol.asyncDispose` directly because the lint
 * rule for `await using` does not resolve the protocol through an interface.
 * These declarations are where the syntax a consumer actually writes is pinned.
 */
declare const server: Server;

export async function disposesOnScopeExit(): Promise<void> {
  await using events = server.watch();
  for await (const event of events) void event;
}

export async function disposesWithOptions(): Promise<void> {
  await using events = server.watch({ bufferSize: 8, target: "work" });
  void events.dropped;
  await events.close();
}

export async function narrowsOnKind(): Promise<string> {
  for await (const event of server.watch()) {
    switch (event.kind) {
      case "output":
        return `${event.paneId}${event.data}`;
      case "extended-output":
        return `${event.paneId}${String(event.age)}`;
      case "window-add":
      case "window-close":
      case "unlinked-window-add":
      case "unlinked-window-close":
        return event.windowId;
      case "window-renamed":
      case "unlinked-window-renamed":
        return `${event.windowId}${event.name}`;
      case "window-pane-changed":
        return `${event.windowId}${event.paneId}`;
      case "layout-change":
        return `${event.layout}${event.visibleLayout}${event.flags}`;
      case "session-changed":
      case "session-renamed":
        return `${event.sessionId}${event.name}`;
      case "sessions-changed":
        return "";
      case "session-window-changed":
        return `${event.sessionId}${event.windowId}`;
      case "client-session-changed":
        return `${event.client}${event.sessionId}${event.name}`;
      case "client-detached":
        return event.client;
      case "pane-mode-changed":
      case "continue":
      case "pause":
        return event.paneId;
      case "paste-buffer-changed":
      case "paste-buffer-deleted":
        return event.buffer;
      case "config-error":
      case "message":
        return event.message;
      case "exit":
        return event.reason ?? "";
      case "unknown":
        return `${event.name}${event.args.join("")}`;
    }
  }
  return "";
}

/** Every member of the union is handled above, so the switch is exhaustive. */
export function exhaustive(event: TmuxEvent): never | void {
  if (event.kind === "output") return;
}

declare const stream: TmuxEventStream;
export const isIterable: AsyncIterable<TmuxEvent> = stream;

/**
 * `signal` is typed structurally so the declarations need no DOM library; a
 * real AbortSignal has to keep satisfying it.
 */
export function acceptsRealAbortSignal(controller: AbortController): TmuxEventStream {
  return server.watch({ signal: controller.signal });
}
