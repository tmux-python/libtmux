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
    return sessionOf(originGraphForHandle(this), this.session_id);
  }

  /** The window placement this client currently shows. */
  get window(): Window | undefined {
    return windowOfPlacement(originGraphForHandle(this), this);
  }

  /** The pane this client currently has active. */
  get pane(): Pane | undefined {
    return paneById(originGraphForHandle(this), this.pane_id);
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

type ClientRow = RowWithIdentities<"client_name">;

export interface Client extends ClientRow, AliasedFields<ClientRow, ClientAliasMap> {}

installLiveHandlePrototype(Client.prototype, CLIENT_ALIASES);
