import * as clientModule from "../../src/client.js";
import type { CompleteFormatRow, RowWithIdentities } from "../../src/_internal/codec/schemas.js";
import type {
  GraphEntityRef,
  GraphRecordRef,
  NormalizedGraph,
} from "../../src/_internal/graph/model.js";
import {
  materializeClientRecord,
  materializeProjectionMembers,
  materializeProjectionRecord,
  replaceHandleSnapshotFromGraph,
} from "../../src/_internal/graph/materialize.js";
import type {
  ProjectionRecord,
  SelectionProjection,
} from "../../src/_internal/graph/selection_projection.js";
import {
  bindLogicalRef,
  createRuntimeContext,
  createServerWithRuntime,
  invalidateRuntimeEpoch,
  runtimeForServer,
  type RuntimeContext,
  type RuntimeContextOptions,
} from "../../src/_internal/runtime/context.js";
import type { LazyCapabilityBinding } from "../../src/_internal/runtime/capabilities.js";
import type { TmuxConnection } from "../../src/_internal/runtime/connection.js";
import {
  entityRefForHandle,
  logicalRefForHandle,
  snapshotForHandle,
  winlinkRefForHandle,
} from "../../src/_internal/runtime/live_handle.js";
import type {
  ModelForKind,
  ModelKind,
  ModelKindOf,
  NominalModel,
} from "../../src/_internal/runtime/model_kind.js";
import * as paneModule from "../../src/pane.js";
import * as serverModule from "../../src/server.js";
import * as sessionModule from "../../src/session.js";
import * as windowModule from "../../src/window.js";
import type {
  ConnectionAlias,
  DaemonEpoch,
  LogicalRef,
  TmuxLogger,
  TmuxWarningSink,
} from "../../src/common.js";
import { Client } from "../../src/client.js";
import type { FormatFieldName } from "../../src/neo.js";
import { Pane } from "../../src/pane.js";
import { Server, type ServerOptions } from "../../src/server.js";
import { Session } from "../../src/session.js";
import { Window } from "../../src/window.js";
import type { CommandTransport } from "../../src/_internal/transport/types.js";
import type { Selection } from "../../src/selection.js";
import type { Equal, Expect } from "./assert.js";

type ExpectedServerOptions = {
  readonly colors?: 88 | 256;
  readonly configFile?: string;
  readonly environment?: Readonly<Record<string, string | undefined>>;
  readonly socketName?: string;
  readonly socketPath?: string;
  readonly tmuxBin?: string;
};

type ExpectedRuntimeContextOptions = {
  readonly connection: TmuxConnection;
  readonly connectionAlias: ConnectionAlias;
  readonly daemonEpoch: DaemonEpoch;
  readonly logger?: TmuxLogger;
  readonly transport: CommandTransport;
  readonly warnings?: TmuxWarningSink;
};

type ExpectedRuntimeContext = {
  readonly capabilities: LazyCapabilityBinding;
  readonly connection: TmuxConnection;
  readonly connectionAlias: ConnectionAlias;
  readonly daemonEpoch: DaemonEpoch;
  readonly logger: TmuxLogger;
  readonly transport: CommandTransport;
  readonly warnings: TmuxWarningSink;
};

type Child = Client | Pane | Session | Window;
type ProjectedChild = Pane | Session | Window;

type _ServerOptions = Expect<Equal<ServerOptions, ExpectedServerOptions>>;
type _ServerConstructor = Expect<
  Equal<ConstructorParameters<typeof Server>, [options?: ServerOptions]>
>;
type _ServerFields = Expect<
  Equal<
    Pick<Server, "colors" | "configFile" | "socketName" | "socketPath" | "tmuxBin">,
    {
      readonly colors: 88 | 256 | undefined;
      readonly configFile: string | undefined;
      readonly socketName: string | undefined;
      readonly socketPath: string | undefined;
      readonly tmuxBin: string;
    }
  >
>;

type _ClientModule = Expect<Equal<keyof typeof clientModule, "Client">>;
type _PaneModule = Expect<Equal<keyof typeof paneModule, "Pane">>;
type _SessionModule = Expect<Equal<keyof typeof sessionModule, "Session">>;
type _WindowModule = Expect<Equal<keyof typeof windowModule, "Window">>;
type _ServerModule = Expect<Equal<keyof typeof serverModule, "Server">>;

type _ClientSnapshot = Expect<
  Equal<Pick<Client, FormatFieldName>, RowWithIdentities<"client_name">>
>;
type _PaneSnapshot = Expect<
  Equal<
    Pick<Pane, FormatFieldName>,
    RowWithIdentities<"pane_id" | "session_id" | "window_id" | "window_index">
  >
>;
type _SessionSnapshot = Expect<
  Equal<Pick<Session, FormatFieldName>, RowWithIdentities<"session_id">>
>;
type _WindowSnapshot = Expect<
  Equal<
    Pick<Window, FormatFieldName>,
    RowWithIdentities<"session_id" | "window_id" | "window_index">
  >
>;

type _SessionAliases = Expect<
  Equal<Pick<Session, "id" | "name">, { readonly id: string; readonly name: string | null }>
>;
type _WindowAliases = Expect<
  Equal<
    Pick<Window, "id" | "index" | "name">,
    { readonly id: string; readonly index: string; readonly name: string | null }
  >
>;
type _PaneAliases = Expect<
  Equal<
    Pick<Pane, "id" | "currentCommand">,
    { readonly id: string; readonly currentCommand: string | null }
  >
>;
// A de-stuttered scalar never shadows a relation or an operation.
type _ClientSessionIsRelation = Expect<Equal<Client["session"], Session | undefined>>;
type _ClientSessionScalar = Expect<Equal<Client["clientSession"], string | null>>;
// tmux exposes both `pid` and `pane_pid`, so the pane keeps the longer name.
type _PanePid = Expect<Equal<Pane["panePid"], string | null>>;

type _ServerEquals = Expect<Equal<Server["equals"], (other: unknown) => boolean>>;
type _ClientEquals = Expect<Equal<Client["equals"], (other: unknown) => boolean>>;
type _PaneEquals = Expect<Equal<Pane["equals"], (other: unknown) => boolean>>;
type _SessionEquals = Expect<Equal<Session["equals"], (other: unknown) => boolean>>;
type _WindowEquals = Expect<Equal<Window["equals"], (other: unknown) => boolean>>;

type _SessionWindows = Expect<Equal<Session["windows"], Selection<Window>>>;
type _SessionPanes = Expect<Equal<Session["panes"], Selection<Pane>>>;
type _WindowSession = Expect<Equal<Window["session"], Session | undefined>>;
type _PaneWindow = Expect<Equal<Pane["window"], Window | undefined>>;

type _ClientRefresh = Expect<Equal<Client["refresh"], () => Promise<void>>>;
type _PaneRefresh = Expect<Equal<Pane["refresh"], () => Promise<void>>>;
type _SessionRefresh = Expect<Equal<Session["refresh"], () => Promise<void>>>;
type _WindowRefresh = Expect<Equal<Window["refresh"], () => Promise<void>>>;

type _ModelKind = Expect<Equal<ModelKind, "client" | "pane" | "server" | "session" | "window">>;
type _ClientForKind = Expect<Equal<ModelForKind<"client">, Client>>;
type _PaneForKind = Expect<Equal<ModelForKind<"pane">, Pane>>;
type _ServerForKind = Expect<Equal<ModelForKind<"server">, Server>>;
type _SessionForKind = Expect<Equal<ModelForKind<"session">, Session>>;
type _WindowForKind = Expect<Equal<ModelForKind<"window">, Window>>;
type _AllNominalModels = Expect<Equal<NominalModel<ModelKind>, Child | Server>>;
type _ClientKind = Expect<Equal<ModelKindOf<Client>, "client">>;
type _PaneKind = Expect<Equal<ModelKindOf<Pane>, "pane">>;
type _ServerKind = Expect<Equal<ModelKindOf<Server>, "server">>;
type _SessionKind = Expect<Equal<ModelKindOf<Session>, "session">>;
type _WindowKind = Expect<Equal<ModelKindOf<Window>, "window">>;

type StructuralSession = RowWithIdentities<"session_id"> & {
  readonly equals: (other: unknown) => boolean;
  readonly server: Server;
};
type StructuralServer = {
  readonly colors: 88 | 256 | undefined;
  readonly configFile: string | undefined;
  readonly equals: (other: unknown) => boolean;
  readonly socketName: string | undefined;
  readonly socketPath: string | undefined;
  readonly tmuxBin: string;
};
type _StructuralSessionKind = Expect<Equal<ModelKindOf<StructuralSession>, never>>;
type _StructuralServerKind = Expect<Equal<ModelKindOf<StructuralServer>, never>>;

type _BindLogicalRef = Expect<
  Equal<typeof bindLogicalRef, (runtime: RuntimeContext, value: unknown) => Promise<LogicalRef>>
>;
type _RuntimeContext = Expect<Equal<RuntimeContext, ExpectedRuntimeContext>>;
type _RuntimeContextOptions = Expect<Equal<RuntimeContextOptions, ExpectedRuntimeContextOptions>>;
type _CreateRuntimeContext = Expect<
  Equal<typeof createRuntimeContext, (options: RuntimeContextOptions) => RuntimeContext>
>;
type _CreateServerWithRuntime = Expect<
  Equal<typeof createServerWithRuntime, (runtime: RuntimeContext) => Server>
>;
type _InvalidateRuntimeEpoch = Expect<
  Equal<typeof invalidateRuntimeEpoch, (runtime: RuntimeContext) => DaemonEpoch>
>;
type _RuntimeForServer = Expect<Equal<typeof runtimeForServer, (server: Server) => RuntimeContext>>;

type _MaterializeProjectionRecord = Expect<
  Equal<
    typeof materializeProjectionRecord,
    (
      server: Server,
      projection: SelectionProjection,
      graph: NormalizedGraph,
      record: ProjectionRecord,
    ) => Promise<ProjectedChild>
  >
>;
type _MaterializeProjectionMembers = Expect<
  Equal<
    typeof materializeProjectionMembers,
    (
      server: Server,
      projection: SelectionProjection,
      graph: NormalizedGraph,
    ) => Promise<readonly ProjectedChild[]>
  >
>;
type _MaterializeClientRecord = Expect<
  Equal<
    typeof materializeClientRecord,
    (server: Server, graph: NormalizedGraph, record: GraphRecordRef) => Promise<Client>
  >
>;
type _ReplaceHandleSnapshot = Expect<
  Equal<
    typeof replaceHandleSnapshotFromGraph,
    (handle: Child, graph: NormalizedGraph, record: GraphRecordRef) => Promise<void>
  >
>;
type _EntityRefForHandle = Expect<
  Equal<typeof entityRefForHandle, (handle: Child) => GraphEntityRef>
>;
type _LogicalRefForHandle = Expect<
  Equal<typeof logicalRefForHandle, (handle: Pane | Session | Window) => LogicalRef>
>;
type _SnapshotForHandle = Expect<
  Equal<typeof snapshotForHandle, (handle: Child) => CompleteFormatRow>
>;
type _WinlinkRefForHandle = Expect<
  Equal<
    typeof winlinkRefForHandle,
    (handle: Child) => import("../../src/_internal/graph/refs.js").WinlinkRef | null
  >
>;

declare const pane: Pane;
declare const graph: NormalizedGraph;
declare const projectionRecord: ProjectionRecord;
declare const server: Server;
declare const serverOptions: ServerOptions;
declare const session: Session;
declare const structuralServer: StructuralServer;
declare const structuralSession: StructuralSession;
declare const window: Window;

void new Server();
void new Server(serverOptions);
void [Client, Pane, Server, Session, Window];

// @ts-expect-error child handles can only be materialized internally.
void new Client();
// @ts-expect-error child handles can only be materialized internally.
void new Pane();
// @ts-expect-error child handles can only be materialized internally.
void new Session();
// @ts-expect-error child handles can only be materialized internally.
void new Window();

// @ts-expect-error child ownership is readonly.
session.server = server;
// @ts-expect-error all complete-row scalar getters are readonly.
session.session_name = "changed";
// @ts-expect-error Server option snapshots are readonly.
server.socketName = "changed";
// @ts-expect-error ServerOptions are readonly.
serverOptions.tmux_bin = "changed";

// @ts-expect-error complete structural rows are not nominal Session handles.
void (structuralSession satisfies Session);
// @ts-expect-error public Server shape is not an authentic Server instance.
void (structuralServer satisfies Server);
// @ts-expect-error model classes remain nominal despite identical scalar surfaces.
void (session satisfies Pane);
// @ts-expect-error model classes remain nominal despite identical scalar surfaces.
void (window satisfies Client);

// @ts-expect-error criteria scalars are not authenticated graph-record evidence.
void materializeClientRecord(server, graph, projectionRecord.scalars);

// @ts-expect-error Task 9 command execution does not land in Task 7.
void server.cmd;
// @ts-expect-error Task 9 read APIs do not land in Task 7.
void server.read;
// @ts-expect-error Task 9 factories do not land in Task 7.
void Server.create;
// @ts-expect-error Task 9 environment factories do not land in Task 7.
void Server.from_env;
// @ts-expect-error Task 8 Selection APIs do not land in Task 7.
void server.select;
// @ts-expect-error Task 8 criteria APIs do not land in Task 7.
void session.where;
void pane;
// @ts-expect-error on_init is not a Task 7 constructor option.
void new Server({ on_init: () => undefined });
// @ts-expect-error internal logger injection is not a public Server option.
void new Server({ logger: {} as TmuxLogger });
// @ts-expect-error internal warning injection is not a public Server option.
void new Server({ warnings: {} as TmuxWarningSink });

export type {
  _AllNominalModels,
  _BindLogicalRef,
  _ClientEquals,
  _ClientForKind,
  _ClientKind,
  _ClientModule,
  _ClientSnapshot,
  _CreateRuntimeContext,
  _CreateServerWithRuntime,
  _EntityRefForHandle,
  _InvalidateRuntimeEpoch,
  _LogicalRefForHandle,
  _MaterializeClientRecord,
  _MaterializeProjectionMembers,
  _MaterializeProjectionRecord,
  _ModelKind,
  _PaneEquals,
  _PaneForKind,
  _PaneKind,
  _PaneModule,
  _PaneSnapshot,
  _ReplaceHandleSnapshot,
  _RuntimeForServer,
  _RuntimeContext,
  _RuntimeContextOptions,
  _ServerConstructor,
  _ServerEquals,
  _ServerFields,
  _ServerForKind,
  _ServerKind,
  _ServerModule,
  _ServerOptions,
  _SessionEquals,
  _SessionForKind,
  _SessionKind,
  _SessionModule,
  _SessionSnapshot,
  _SnapshotForHandle,
  _StructuralServerKind,
  _StructuralSessionKind,
  _WindowEquals,
  _WindowForKind,
  _WindowKind,
  _WindowModule,
  _WindowSnapshot,
  _WinlinkRefForHandle,
};
