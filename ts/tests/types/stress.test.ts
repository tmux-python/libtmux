import type { Pane } from "../../src/pane.js";
import type { Session } from "../../src/session.js";
import type { Window } from "../../src/window.js";
import type {
  PaneWhere,
  Selection,
  SessionWhere,
  WhereOf,
  WindowWhere,
} from "../../src/selection.js";

declare const panes: Selection<Pane>;
declare const sessions: Selection<Session>;
declare const windows: Selection<Window>;

function applyWhere<Model>(
  selection: Selection<Model>,
  criteria: WhereOf<Model>,
): Selection<Model> {
  return selection.where(criteria);
}

const deeplyCyclicSession = {
  windows: {
    some: {
      session: {
        is: {
          panes: {
            some: {
              window: {
                is: {
                  linkedSessions: {
                    some: {
                      activeWindow: {
                        is: {
                          activePane: {
                            is: {
                              session: {
                                is: {
                                  windows: {
                                    some: {
                                      panes: {
                                        some: {
                                          session: { is: { name: "terminal" } },
                                        },
                                      },
                                    },
                                  },
                                },
                              },
                            },
                          },
                        },
                      },
                    },
                  },
                },
              },
            },
          },
        },
      },
    },
  },
} satisfies SessionWhere;

const sessionCases = [
  {},
  { name: "main" },
  { name: null },
  { name: { equals: null } },
  { name: { contains: "a", mode: "insensitive" } },
  { name: { endsWith: "n", startsWith: "m" } },
  { name: { in: ["main", "work"] } },
  { name: { notIn: [] } },
  { name: { regex: { flags: "", pattern: "^(main|work)$" } } },
  { AND: [] },
  { OR: [{ name: "main" }, { name: "work" }] },
  { NOT: [{ name: "other" }] },
  { windows: { some: { name: "editor" } } },
  { windows: { every: {}, none: { name: "logs" }, some: {} } },
  { panes: { some: { title: "shell" } } },
  { panes: { every: {}, none: { title: "tail" }, some: {} } },
  { activeWindow: { is: null } },
  { activeWindow: { is: { name: "editor" }, isNot: { name: "logs" } } },
  { activePane: { is: null } },
  { activePane: { is: { title: "shell" }, isNot: null } },
  deeplyCyclicSession,
] as const satisfies readonly SessionWhere[];

const windowCases = [
  {},
  { name: "editor" },
  { session: { is: { name: "main" } } },
  { session: { is: { windows: { some: { name: "editor" } } }, isNot: null } },
  { linkedSessions: { some: { name: "main" } } },
  { linkedSessions: { every: {}, none: { name: "other" }, some: {} } },
  { panes: { some: { title: "shell" } } },
  { panes: { every: {}, none: { title: "tail" }, some: {} } },
  { activePane: { is: null } },
  {
    activePane: {
      is: { session: { is: { activeWindow: { is: { name: "editor" } } } } },
      isNot: { title: "tail" },
    },
  },
] as const satisfies readonly WindowWhere[];

const paneCases = [
  {},
  { id: "%1" },
  { title: { contains: "shell", mode: "insensitive" } },
  { window: { is: { name: "editor" } } },
  { window: { is: { session: { is: { name: "main" } } }, isNot: null } },
  { session: { is: { name: "main" } } },
  {
    session: {
      is: { activePane: { is: { title: "shell" } } },
      isNot: { name: "other" },
    },
  },
] as const satisfies readonly PaneWhere[];

for (const criteria of sessionCases) void applyWhere(sessions, criteria);
for (const criteria of windowCases) void applyWhere(windows, criteria);
for (const criteria of paneCases) void applyWhere(panes, criteria);

type SessionDepthOne = NonNullable<SessionWhere["windows"]>;
type SessionDepthTwo = NonNullable<WindowWhere["session"]>;
type SessionDepthThree = NonNullable<SessionWhere["panes"]>;
type SessionDepthFour = NonNullable<PaneWhere["window"]>;
type SessionDepthFive = NonNullable<WindowWhere["linkedSessions"]>;

void (null as unknown as SessionDepthOne);
void (null as unknown as SessionDepthTwo);
void (null as unknown as SessionDepthThree);
void (null as unknown as SessionDepthFour);
void (null as unknown as SessionDepthFive);
