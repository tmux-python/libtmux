import { CLIENT_ALIASES, type ClientAliasMap } from "./_generated/field_aliases.js";
import type { AliasedFields, RowWithIdentities } from "./_internal/codec/schemas.js";
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
  get session(): Session | undefined {
    return sessionOf(originGraphForHandle(this), this.sessionId);
  }

  /** The window placement this client currently shows. */
  get window(): Window | undefined {
    return windowOfPlacement(originGraphForHandle(this), this);
  }

  /** The pane this client currently has active. */
  get pane(): Pane | undefined {
    return paneById(originGraphForHandle(this), this.paneId);
  }

  /** Re-read this client at the current instant, in place. */
  refresh(): Promise<void> {
    return refreshHandle(this, runtimeForServer(this.server));
  }

  /** Detach this client from its server. */
  detach(): Promise<void> {
    return detachClient(runtimeForServer(this.server), this.name);
  }

  /** Point this client at a different session. */
  switchTo(session: Session): Promise<void> {
    return switchClient(runtimeForServer(this.server), this.name, session.id);
  }

  equals(other: unknown): boolean {
    return liveHandlesEqual(this, other);
  }
}

type ClientRow = RowWithIdentities<"client_name">;

export interface Client extends AliasedFields<ClientRow, ClientAliasMap> {
  /** The raw tmux format row, addressed by tmux's own token names. */
  readonly format: ClientRow;
}

installLiveHandlePrototype(Client.prototype, CLIENT_ALIASES);
