import type { FormatFieldName } from "../neo.js";

export type WhereModel = "pane" | "session" | "window";

export interface WhereField {
  /** The camelCase key a caller writes in criteria. */
  readonly criteriaName: string;
  readonly domain: "string";
  readonly token: FormatFieldName;
  /** The stable serialized name, unchanged across releases. */
  readonly wireName: string;
}

const sessionFields: readonly WhereField[] = Object.freeze([
  Object.freeze({
    criteriaName: "activeWindowIndex",
    domain: "string",
    token: "active_window_index",
    wireName: "active_window_index",
  }),
  Object.freeze({
    criteriaName: "configFiles",
    domain: "string",
    token: "config_files",
    wireName: "config_files",
  }),
  Object.freeze({
    criteriaName: "lastWindowIndex",
    domain: "string",
    token: "last_window_index",
    wireName: "last_window_index",
  }),
  Object.freeze({ criteriaName: "line", domain: "string", token: "line", wireName: "line" }),
  Object.freeze({
    criteriaName: "name",
    domain: "string",
    token: "session_name",
    wireName: "name",
  }),
  Object.freeze({
    criteriaName: "nextSessionId",
    domain: "string",
    token: "next_session_id",
    wireName: "next_session_id",
  }),
  Object.freeze({ criteriaName: "pid", domain: "string", token: "pid", wireName: "pid" }),
  Object.freeze({
    criteriaName: "sessionActivity",
    domain: "string",
    token: "session_activity",
    wireName: "session_activity",
  }),
  Object.freeze({
    criteriaName: "sessionAlerts",
    domain: "string",
    token: "session_alerts",
    wireName: "session_alerts",
  }),
  Object.freeze({
    criteriaName: "sessionAttached",
    domain: "string",
    token: "session_attached",
    wireName: "session_attached",
  }),
  Object.freeze({
    criteriaName: "sessionAttachedList",
    domain: "string",
    token: "session_attached_list",
    wireName: "session_attached_list",
  }),
  Object.freeze({
    criteriaName: "sessionCreated",
    domain: "string",
    token: "session_created",
    wireName: "session_created",
  }),
  Object.freeze({
    criteriaName: "sessionFormat",
    domain: "string",
    token: "session_format",
    wireName: "session_format",
  }),
  Object.freeze({
    criteriaName: "sessionGroup",
    domain: "string",
    token: "session_group",
    wireName: "session_group",
  }),
  Object.freeze({
    criteriaName: "sessionGroupAttached",
    domain: "string",
    token: "session_group_attached",
    wireName: "session_group_attached",
  }),
  Object.freeze({
    criteriaName: "sessionGroupAttachedList",
    domain: "string",
    token: "session_group_attached_list",
    wireName: "session_group_attached_list",
  }),
  Object.freeze({
    criteriaName: "sessionGroupList",
    domain: "string",
    token: "session_group_list",
    wireName: "session_group_list",
  }),
  Object.freeze({
    criteriaName: "sessionGroupManyAttached",
    domain: "string",
    token: "session_group_many_attached",
    wireName: "session_group_many_attached",
  }),
  Object.freeze({
    criteriaName: "sessionGroupSize",
    domain: "string",
    token: "session_group_size",
    wireName: "session_group_size",
  }),
  Object.freeze({
    criteriaName: "sessionGrouped",
    domain: "string",
    token: "session_grouped",
    wireName: "session_grouped",
  }),
  Object.freeze({
    criteriaName: "sessionId",
    domain: "string",
    token: "session_id",
    wireName: "session_id",
  }),
  Object.freeze({
    criteriaName: "sessionLastAttached",
    domain: "string",
    token: "session_last_attached",
    wireName: "session_last_attached",
  }),
  Object.freeze({
    criteriaName: "sessionManyAttached",
    domain: "string",
    token: "session_many_attached",
    wireName: "session_many_attached",
  }),
  Object.freeze({
    criteriaName: "sessionMarked",
    domain: "string",
    token: "session_marked",
    wireName: "session_marked",
  }),
  Object.freeze({
    criteriaName: "sessionPath",
    domain: "string",
    token: "session_path",
    wireName: "session_path",
  }),
  Object.freeze({
    criteriaName: "sessionStack",
    domain: "string",
    token: "session_stack",
    wireName: "session_stack",
  }),
  Object.freeze({
    criteriaName: "sessionWindows",
    domain: "string",
    token: "session_windows",
    wireName: "session_windows",
  }),
  Object.freeze({
    criteriaName: "socketPath",
    domain: "string",
    token: "socket_path",
    wireName: "socket_path",
  }),
  Object.freeze({
    criteriaName: "startTime",
    domain: "string",
    token: "start_time",
    wireName: "start_time",
  }),
  Object.freeze({ criteriaName: "uid", domain: "string", token: "uid", wireName: "uid" }),
  Object.freeze({ criteriaName: "user", domain: "string", token: "user", wireName: "user" }),
  Object.freeze({
    criteriaName: "version",
    domain: "string",
    token: "version",
    wireName: "version",
  }),
]);

const windowFields: readonly WhereField[] = Object.freeze([
  Object.freeze({
    criteriaName: "configFiles",
    domain: "string",
    token: "config_files",
    wireName: "config_files",
  }),
  Object.freeze({ criteriaName: "line", domain: "string", token: "line", wireName: "line" }),
  Object.freeze({ criteriaName: "name", domain: "string", token: "window_name", wireName: "name" }),
  Object.freeze({
    criteriaName: "nextSessionId",
    domain: "string",
    token: "next_session_id",
    wireName: "next_session_id",
  }),
  Object.freeze({ criteriaName: "pid", domain: "string", token: "pid", wireName: "pid" }),
  Object.freeze({
    criteriaName: "socketPath",
    domain: "string",
    token: "socket_path",
    wireName: "socket_path",
  }),
  Object.freeze({
    criteriaName: "startTime",
    domain: "string",
    token: "start_time",
    wireName: "start_time",
  }),
  Object.freeze({ criteriaName: "uid", domain: "string", token: "uid", wireName: "uid" }),
  Object.freeze({ criteriaName: "user", domain: "string", token: "user", wireName: "user" }),
  Object.freeze({
    criteriaName: "version",
    domain: "string",
    token: "version",
    wireName: "version",
  }),
  Object.freeze({
    criteriaName: "windowActive",
    domain: "string",
    token: "window_active",
    wireName: "window_active",
  }),
  Object.freeze({
    criteriaName: "windowActiveClients",
    domain: "string",
    token: "window_active_clients",
    wireName: "window_active_clients",
  }),
  Object.freeze({
    criteriaName: "windowActiveClientsList",
    domain: "string",
    token: "window_active_clients_list",
    wireName: "window_active_clients_list",
  }),
  Object.freeze({
    criteriaName: "windowActiveSessions",
    domain: "string",
    token: "window_active_sessions",
    wireName: "window_active_sessions",
  }),
  Object.freeze({
    criteriaName: "windowActiveSessionsList",
    domain: "string",
    token: "window_active_sessions_list",
    wireName: "window_active_sessions_list",
  }),
  Object.freeze({
    criteriaName: "windowActivity",
    domain: "string",
    token: "window_activity",
    wireName: "window_activity",
  }),
  Object.freeze({
    criteriaName: "windowActivityFlag",
    domain: "string",
    token: "window_activity_flag",
    wireName: "window_activity_flag",
  }),
  Object.freeze({
    criteriaName: "windowBellFlag",
    domain: "string",
    token: "window_bell_flag",
    wireName: "window_bell_flag",
  }),
  Object.freeze({
    criteriaName: "windowBigger",
    domain: "string",
    token: "window_bigger",
    wireName: "window_bigger",
  }),
  Object.freeze({
    criteriaName: "windowCellHeight",
    domain: "string",
    token: "window_cell_height",
    wireName: "window_cell_height",
  }),
  Object.freeze({
    criteriaName: "windowCellWidth",
    domain: "string",
    token: "window_cell_width",
    wireName: "window_cell_width",
  }),
  Object.freeze({
    criteriaName: "windowEndFlag",
    domain: "string",
    token: "window_end_flag",
    wireName: "window_end_flag",
  }),
  Object.freeze({
    criteriaName: "windowFlags",
    domain: "string",
    token: "window_flags",
    wireName: "window_flags",
  }),
  Object.freeze({
    criteriaName: "windowFormat",
    domain: "string",
    token: "window_format",
    wireName: "window_format",
  }),
  Object.freeze({
    criteriaName: "windowHeight",
    domain: "string",
    token: "window_height",
    wireName: "window_height",
  }),
  Object.freeze({
    criteriaName: "windowId",
    domain: "string",
    token: "window_id",
    wireName: "window_id",
  }),
  Object.freeze({
    criteriaName: "windowIndex",
    domain: "string",
    token: "window_index",
    wireName: "window_index",
  }),
  Object.freeze({
    criteriaName: "windowLastFlag",
    domain: "string",
    token: "window_last_flag",
    wireName: "window_last_flag",
  }),
  Object.freeze({
    criteriaName: "windowLayout",
    domain: "string",
    token: "window_layout",
    wireName: "window_layout",
  }),
  Object.freeze({
    criteriaName: "windowLinked",
    domain: "string",
    token: "window_linked",
    wireName: "window_linked",
  }),
  Object.freeze({
    criteriaName: "windowLinkedSessions",
    domain: "string",
    token: "window_linked_sessions",
    wireName: "window_linked_sessions",
  }),
  Object.freeze({
    criteriaName: "windowLinkedSessionsList",
    domain: "string",
    token: "window_linked_sessions_list",
    wireName: "window_linked_sessions_list",
  }),
  Object.freeze({
    criteriaName: "windowMarkedFlag",
    domain: "string",
    token: "window_marked_flag",
    wireName: "window_marked_flag",
  }),
  Object.freeze({
    criteriaName: "windowOffsetX",
    domain: "string",
    token: "window_offset_x",
    wireName: "window_offset_x",
  }),
  Object.freeze({
    criteriaName: "windowOffsetY",
    domain: "string",
    token: "window_offset_y",
    wireName: "window_offset_y",
  }),
  Object.freeze({
    criteriaName: "windowPanes",
    domain: "string",
    token: "window_panes",
    wireName: "window_panes",
  }),
  Object.freeze({
    criteriaName: "windowRawFlags",
    domain: "string",
    token: "window_raw_flags",
    wireName: "window_raw_flags",
  }),
  Object.freeze({
    criteriaName: "windowSilenceFlag",
    domain: "string",
    token: "window_silence_flag",
    wireName: "window_silence_flag",
  }),
  Object.freeze({
    criteriaName: "windowStackIndex",
    domain: "string",
    token: "window_stack_index",
    wireName: "window_stack_index",
  }),
  Object.freeze({
    criteriaName: "windowStartFlag",
    domain: "string",
    token: "window_start_flag",
    wireName: "window_start_flag",
  }),
  Object.freeze({
    criteriaName: "windowVisibleLayout",
    domain: "string",
    token: "window_visible_layout",
    wireName: "window_visible_layout",
  }),
  Object.freeze({
    criteriaName: "windowWidth",
    domain: "string",
    token: "window_width",
    wireName: "window_width",
  }),
  Object.freeze({
    criteriaName: "windowZoomedFlag",
    domain: "string",
    token: "window_zoomed_flag",
    wireName: "window_zoomed_flag",
  }),
]);

const paneFields: readonly WhereField[] = Object.freeze([
  Object.freeze({
    criteriaName: "alternateSavedX",
    domain: "string",
    token: "alternate_saved_x",
    wireName: "alternate_saved_x",
  }),
  Object.freeze({
    criteriaName: "alternateSavedY",
    domain: "string",
    token: "alternate_saved_y",
    wireName: "alternate_saved_y",
  }),
  Object.freeze({
    criteriaName: "bracketPasteFlag",
    domain: "string",
    token: "bracket_paste_flag",
    wireName: "bracket_paste_flag",
  }),
  Object.freeze({
    criteriaName: "configFiles",
    domain: "string",
    token: "config_files",
    wireName: "config_files",
  }),
  Object.freeze({
    criteriaName: "cursorCharacter",
    domain: "string",
    token: "cursor_character",
    wireName: "cursor_character",
  }),
  Object.freeze({
    criteriaName: "cursorFlag",
    domain: "string",
    token: "cursor_flag",
    wireName: "cursor_flag",
  }),
  Object.freeze({
    criteriaName: "cursorX",
    domain: "string",
    token: "cursor_x",
    wireName: "cursor_x",
  }),
  Object.freeze({
    criteriaName: "cursorY",
    domain: "string",
    token: "cursor_y",
    wireName: "cursor_y",
  }),
  Object.freeze({
    criteriaName: "historyBytes",
    domain: "string",
    token: "history_bytes",
    wireName: "history_bytes",
  }),
  Object.freeze({
    criteriaName: "historyLimit",
    domain: "string",
    token: "history_limit",
    wireName: "history_limit",
  }),
  Object.freeze({
    criteriaName: "historySize",
    domain: "string",
    token: "history_size",
    wireName: "history_size",
  }),
  Object.freeze({
    criteriaName: "insertFlag",
    domain: "string",
    token: "insert_flag",
    wireName: "insert_flag",
  }),
  Object.freeze({
    criteriaName: "keypadCursorFlag",
    domain: "string",
    token: "keypad_cursor_flag",
    wireName: "keypad_cursor_flag",
  }),
  Object.freeze({
    criteriaName: "keypadFlag",
    domain: "string",
    token: "keypad_flag",
    wireName: "keypad_flag",
  }),
  Object.freeze({ criteriaName: "line", domain: "string", token: "line", wireName: "line" }),
  Object.freeze({
    criteriaName: "mouseAllFlag",
    domain: "string",
    token: "mouse_all_flag",
    wireName: "mouse_all_flag",
  }),
  Object.freeze({
    criteriaName: "mouseAnyFlag",
    domain: "string",
    token: "mouse_any_flag",
    wireName: "mouse_any_flag",
  }),
  Object.freeze({
    criteriaName: "mouseButtonFlag",
    domain: "string",
    token: "mouse_button_flag",
    wireName: "mouse_button_flag",
  }),
  Object.freeze({
    criteriaName: "mouseSgrFlag",
    domain: "string",
    token: "mouse_sgr_flag",
    wireName: "mouse_sgr_flag",
  }),
  Object.freeze({
    criteriaName: "mouseStandardFlag",
    domain: "string",
    token: "mouse_standard_flag",
    wireName: "mouse_standard_flag",
  }),
  Object.freeze({
    criteriaName: "nextSessionId",
    domain: "string",
    token: "next_session_id",
    wireName: "next_session_id",
  }),
  Object.freeze({
    criteriaName: "originFlag",
    domain: "string",
    token: "origin_flag",
    wireName: "origin_flag",
  }),
  Object.freeze({
    criteriaName: "paneActive",
    domain: "string",
    token: "pane_active",
    wireName: "pane_active",
  }),
  Object.freeze({
    criteriaName: "paneAtBottom",
    domain: "string",
    token: "pane_at_bottom",
    wireName: "pane_at_bottom",
  }),
  Object.freeze({
    criteriaName: "paneAtLeft",
    domain: "string",
    token: "pane_at_left",
    wireName: "pane_at_left",
  }),
  Object.freeze({
    criteriaName: "paneAtRight",
    domain: "string",
    token: "pane_at_right",
    wireName: "pane_at_right",
  }),
  Object.freeze({
    criteriaName: "paneAtTop",
    domain: "string",
    token: "pane_at_top",
    wireName: "pane_at_top",
  }),
  Object.freeze({
    criteriaName: "paneBg",
    domain: "string",
    token: "pane_bg",
    wireName: "pane_bg",
  }),
  Object.freeze({
    criteriaName: "paneBottom",
    domain: "string",
    token: "pane_bottom",
    wireName: "pane_bottom",
  }),
  Object.freeze({
    criteriaName: "paneCurrentCommand",
    domain: "string",
    token: "pane_current_command",
    wireName: "pane_current_command",
  }),
  Object.freeze({
    criteriaName: "paneCurrentPath",
    domain: "string",
    token: "pane_current_path",
    wireName: "pane_current_path",
  }),
  Object.freeze({
    criteriaName: "paneDead",
    domain: "string",
    token: "pane_dead",
    wireName: "pane_dead",
  }),
  Object.freeze({
    criteriaName: "paneDeadSignal",
    domain: "string",
    token: "pane_dead_signal",
    wireName: "pane_dead_signal",
  }),
  Object.freeze({
    criteriaName: "paneDeadStatus",
    domain: "string",
    token: "pane_dead_status",
    wireName: "pane_dead_status",
  }),
  Object.freeze({
    criteriaName: "paneDeadTime",
    domain: "string",
    token: "pane_dead_time",
    wireName: "pane_dead_time",
  }),
  Object.freeze({
    criteriaName: "paneFg",
    domain: "string",
    token: "pane_fg",
    wireName: "pane_fg",
  }),
  Object.freeze({
    criteriaName: "paneFlags",
    domain: "string",
    token: "pane_flags",
    wireName: "pane_flags",
  }),
  Object.freeze({
    criteriaName: "paneFloatingFlag",
    domain: "string",
    token: "pane_floating_flag",
    wireName: "pane_floating_flag",
  }),
  Object.freeze({
    criteriaName: "paneFormat",
    domain: "string",
    token: "pane_format",
    wireName: "pane_format",
  }),
  Object.freeze({
    criteriaName: "paneHeight",
    domain: "string",
    token: "pane_height",
    wireName: "pane_height",
  }),
  Object.freeze({
    criteriaName: "paneId",
    domain: "string",
    token: "pane_id",
    wireName: "pane_id",
  }),
  Object.freeze({
    criteriaName: "paneInMode",
    domain: "string",
    token: "pane_in_mode",
    wireName: "pane_in_mode",
  }),
  Object.freeze({
    criteriaName: "paneIndex",
    domain: "string",
    token: "pane_index",
    wireName: "pane_index",
  }),
  Object.freeze({
    criteriaName: "paneInputOff",
    domain: "string",
    token: "pane_input_off",
    wireName: "pane_input_off",
  }),
  Object.freeze({
    criteriaName: "paneLast",
    domain: "string",
    token: "pane_last",
    wireName: "pane_last",
  }),
  Object.freeze({
    criteriaName: "paneLeft",
    domain: "string",
    token: "pane_left",
    wireName: "pane_left",
  }),
  Object.freeze({
    criteriaName: "paneMarked",
    domain: "string",
    token: "pane_marked",
    wireName: "pane_marked",
  }),
  Object.freeze({
    criteriaName: "paneMarkedSet",
    domain: "string",
    token: "pane_marked_set",
    wireName: "pane_marked_set",
  }),
  Object.freeze({
    criteriaName: "paneMode",
    domain: "string",
    token: "pane_mode",
    wireName: "pane_mode",
  }),
  Object.freeze({
    criteriaName: "panePath",
    domain: "string",
    token: "pane_path",
    wireName: "pane_path",
  }),
  Object.freeze({
    criteriaName: "panePbProgress",
    domain: "string",
    token: "pane_pb_progress",
    wireName: "pane_pb_progress",
  }),
  Object.freeze({
    criteriaName: "panePbState",
    domain: "string",
    token: "pane_pb_state",
    wireName: "pane_pb_state",
  }),
  Object.freeze({
    criteriaName: "panePid",
    domain: "string",
    token: "pane_pid",
    wireName: "pane_pid",
  }),
  Object.freeze({
    criteriaName: "panePipe",
    domain: "string",
    token: "pane_pipe",
    wireName: "pane_pipe",
  }),
  Object.freeze({
    criteriaName: "panePipePid",
    domain: "string",
    token: "pane_pipe_pid",
    wireName: "pane_pipe_pid",
  }),
  Object.freeze({
    criteriaName: "paneRight",
    domain: "string",
    token: "pane_right",
    wireName: "pane_right",
  }),
  Object.freeze({
    criteriaName: "paneSearchString",
    domain: "string",
    token: "pane_search_string",
    wireName: "pane_search_string",
  }),
  Object.freeze({
    criteriaName: "paneStartCommand",
    domain: "string",
    token: "pane_start_command",
    wireName: "pane_start_command",
  }),
  Object.freeze({
    criteriaName: "paneStartPath",
    domain: "string",
    token: "pane_start_path",
    wireName: "pane_start_path",
  }),
  Object.freeze({
    criteriaName: "paneSynchronized",
    domain: "string",
    token: "pane_synchronized",
    wireName: "pane_synchronized",
  }),
  Object.freeze({
    criteriaName: "paneTabs",
    domain: "string",
    token: "pane_tabs",
    wireName: "pane_tabs",
  }),
  Object.freeze({
    criteriaName: "paneTitle",
    domain: "string",
    token: "pane_title",
    wireName: "pane_title",
  }),
  Object.freeze({
    criteriaName: "paneTop",
    domain: "string",
    token: "pane_top",
    wireName: "pane_top",
  }),
  Object.freeze({
    criteriaName: "paneTty",
    domain: "string",
    token: "pane_tty",
    wireName: "pane_tty",
  }),
  Object.freeze({
    criteriaName: "paneWidth",
    domain: "string",
    token: "pane_width",
    wireName: "pane_width",
  }),
  Object.freeze({ criteriaName: "paneX", domain: "string", token: "pane_x", wireName: "pane_x" }),
  Object.freeze({ criteriaName: "paneY", domain: "string", token: "pane_y", wireName: "pane_y" }),
  Object.freeze({ criteriaName: "paneZ", domain: "string", token: "pane_z", wireName: "pane_z" }),
  Object.freeze({
    criteriaName: "paneZoomedFlag",
    domain: "string",
    token: "pane_zoomed_flag",
    wireName: "pane_zoomed_flag",
  }),
  Object.freeze({ criteriaName: "pid", domain: "string", token: "pid", wireName: "pid" }),
  Object.freeze({
    criteriaName: "scrollRegionLower",
    domain: "string",
    token: "scroll_region_lower",
    wireName: "scroll_region_lower",
  }),
  Object.freeze({
    criteriaName: "scrollRegionUpper",
    domain: "string",
    token: "scroll_region_upper",
    wireName: "scroll_region_upper",
  }),
  Object.freeze({
    criteriaName: "socketPath",
    domain: "string",
    token: "socket_path",
    wireName: "socket_path",
  }),
  Object.freeze({
    criteriaName: "startTime",
    domain: "string",
    token: "start_time",
    wireName: "start_time",
  }),
  Object.freeze({
    criteriaName: "synchronizedOutputFlag",
    domain: "string",
    token: "synchronized_output_flag",
    wireName: "synchronized_output_flag",
  }),
  Object.freeze({ criteriaName: "uid", domain: "string", token: "uid", wireName: "uid" }),
  Object.freeze({ criteriaName: "user", domain: "string", token: "user", wireName: "user" }),
  Object.freeze({
    criteriaName: "version",
    domain: "string",
    token: "version",
    wireName: "version",
  }),
  Object.freeze({
    criteriaName: "wrapFlag",
    domain: "string",
    token: "wrap_flag",
    wireName: "wrap_flag",
  }),
]);

const emptyAliases: Readonly<Record<string, string>> = Object.freeze({});

export const WHERE_FIELDS_V1: Readonly<Record<WhereModel, readonly WhereField[]>> = Object.freeze({
  session: sessionFields,
  window: windowFields,
  pane: paneFields,
});

export const WHERE_ALIASES_V1: Readonly<Record<WhereModel, Readonly<Record<string, string>>>> =
  Object.freeze({
    session: emptyAliases,
    window: emptyAliases,
    pane: emptyAliases,
  });

export interface WhereRelation {
  readonly cardinality: "many" | "one";
  readonly name: string;
  readonly targetModel: WhereModel;
}

export const WHERE_RELATIONS_V1: Readonly<{
  readonly pane: readonly [
    {
      readonly cardinality: "one";
      readonly name: "window";
      readonly targetModel: "window";
    },
    {
      readonly cardinality: "one";
      readonly name: "session";
      readonly targetModel: "session";
    },
  ];
  readonly session: readonly [
    {
      readonly cardinality: "many";
      readonly name: "windows";
      readonly targetModel: "window";
    },
    {
      readonly cardinality: "many";
      readonly name: "panes";
      readonly targetModel: "pane";
    },
    {
      readonly cardinality: "one";
      readonly name: "activeWindow";
      readonly targetModel: "window";
    },
    {
      readonly cardinality: "one";
      readonly name: "activePane";
      readonly targetModel: "pane";
    },
  ];
  readonly window: readonly [
    {
      readonly cardinality: "one";
      readonly name: "session";
      readonly targetModel: "session";
    },
    {
      readonly cardinality: "many";
      readonly name: "linkedSessions";
      readonly targetModel: "session";
    },
    {
      readonly cardinality: "many";
      readonly name: "panes";
      readonly targetModel: "pane";
    },
    {
      readonly cardinality: "one";
      readonly name: "activePane";
      readonly targetModel: "pane";
    },
  ];
}> = Object.freeze({
  pane: Object.freeze([
    Object.freeze({ cardinality: "one", name: "window", targetModel: "window" }),
    Object.freeze({ cardinality: "one", name: "session", targetModel: "session" }),
  ] as const),
  session: Object.freeze([
    Object.freeze({ cardinality: "many", name: "windows", targetModel: "window" }),
    Object.freeze({ cardinality: "many", name: "panes", targetModel: "pane" }),
    Object.freeze({ cardinality: "one", name: "activeWindow", targetModel: "window" }),
    Object.freeze({ cardinality: "one", name: "activePane", targetModel: "pane" }),
  ] as const),
  window: Object.freeze([
    Object.freeze({ cardinality: "one", name: "session", targetModel: "session" }),
    Object.freeze({ cardinality: "many", name: "linkedSessions", targetModel: "session" }),
    Object.freeze({ cardinality: "many", name: "panes", targetModel: "pane" }),
    Object.freeze({ cardinality: "one", name: "activePane", targetModel: "pane" }),
  ] as const),
} as const);
