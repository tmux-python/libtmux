import { parsePaneId, parseSessionId, parseWindowId } from "../../src/_internal/runtime/ids.js";
import type { PaneIdInput, SessionIdInput, WindowIdInput } from "../../src/common.js";

declare const raw: string;

const rawSession: SessionIdInput = "$1";
const session = parseSessionId(rawSession);
const pane = parsePaneId("%3");
const window = parseWindowId("@2");

const sessionInput: SessionIdInput = session;
const paneInput: PaneIdInput = pane;
const windowInput: WindowIdInput = window;

void sessionInput;
void paneInput;
void windowInput;
parseSessionId("$1");
parseSessionId(raw);
parseSessionId(session);
parseWindowId("@2");
parseWindowId(raw);
parseWindowId(window);
parsePaneId("%3");
parsePaneId(raw);
parsePaneId(pane);

// @ts-expect-error A pane brand cannot be supplied where a session ID is expected.
parseSessionId(pane);
// @ts-expect-error A window brand cannot be supplied where a session ID is expected.
parseSessionId(window);
// @ts-expect-error A session brand cannot be supplied where a window ID is expected.
parseWindowId(session);
// @ts-expect-error A pane brand cannot be supplied where a window ID is expected.
parseWindowId(pane);
// @ts-expect-error A session brand cannot be supplied where a pane ID is expected.
parsePaneId(session);
// @ts-expect-error A window brand cannot be supplied where a pane ID is expected.
parsePaneId(window);

declare const mixed: typeof session | typeof pane;

// @ts-expect-error A union containing a foreign brand cannot be supplied as a session ID.
parseSessionId(mixed);

declare const mixedWindow: typeof window | typeof session;
declare const mixedPane: typeof pane | typeof window;

// @ts-expect-error A union containing a foreign brand cannot be supplied as a window ID.
parseWindowId(mixedWindow);
// @ts-expect-error A union containing a foreign brand cannot be supplied as a pane ID.
parsePaneId(mixedPane);

const erased: string = pane;
parseSessionId(erased);
parseWindowId(erased);
parsePaneId(erased);
