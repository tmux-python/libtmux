import type { CompleteFormatRow } from "./_internal/codec/schemas.js";
import { paneById, sessionOf, windowOfPlacement } from "./_internal/operations/relations.js";
import { refreshHandle } from "./_internal/operations/refresh.js";
import { detachClient, switchClient } from "./_internal/operations/shell.js";
import { runtimeForServer } from "./_internal/runtime/context.js";
import { originGraphForHandle } from "./_internal/runtime/live_handle.js";
import type { Pane } from "./pane.js";
import type { Session } from "./session.js";
import type { Window } from "./window.js";
import { installLiveHandlePrototype, liveHandlesEqual } from "./_internal/runtime/live_handle.js";
import type { Server } from "./server.js";

// eslint-disable-next-line typescript/no-unsafe-declaration-merging -- CompleteFormatRow declaration merging exposes the frozen scalar snapshot on the nominal handle.
export class Client {
  declare private readonly clientBrand: undefined;
  declare readonly server: Server;

  private constructor() {
    throw new Error("Client cannot be constructed directly");
  }

  /** The session this client is attached to, if it is still attached. */
  session(): Promise<Session | undefined> {
    return sessionOf(this.server, originGraphForHandle(this), this.session_id);
  }

  /** The window placement this client currently shows. */
  window(): Promise<Window | undefined> {
    return windowOfPlacement(this.server, originGraphForHandle(this), this);
  }

  /** The pane this client currently has active. */
  pane(): Promise<Pane | undefined> {
    return paneById(this.server, originGraphForHandle(this), this.pane_id);
  }

  /** Re-read this client at the current instant, in place. */
  refresh(): Promise<void> {
    return refreshHandle(this, runtimeForServer(this.server));
  }

  /** Detach this client from its server. */
  detach(): Promise<void> {
    return detachClient(runtimeForServer(this.server), this.client_name);
  }

  /** Point this client at a different session. */
  switchTo(session: Session): Promise<void> {
    return switchClient(runtimeForServer(this.server), this.client_name, session.session_id ?? "");
  }

  equals(other: unknown): boolean {
    return liveHandlesEqual(this, other);
  }
}

export interface Client extends CompleteFormatRow {}

installLiveHandlePrototype(Client.prototype);
