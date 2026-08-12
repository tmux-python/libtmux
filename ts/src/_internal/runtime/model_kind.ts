import type { Client } from "../../client.js";
import type { Pane } from "../../pane.js";
import type { Server } from "../../server.js";
import type { Session } from "../../session.js";
import type { Window } from "../../window.js";

export type ModelKind = "client" | "pane" | "server" | "session" | "window";

export type ModelForKind<Kind extends ModelKind> = Kind extends "client"
  ? Client
  : Kind extends "pane"
    ? Pane
    : Kind extends "server"
      ? Server
      : Kind extends "session"
        ? Session
        : Window;

export type NominalModel<Kind extends ModelKind> = ModelForKind<Kind>;

export type ModelKindOf<Model> = Model extends Client
  ? "client"
  : Model extends Pane
    ? "pane"
    : Model extends Server
      ? "server"
      : Model extends Session
        ? "session"
        : Model extends Window
          ? "window"
          : never;
