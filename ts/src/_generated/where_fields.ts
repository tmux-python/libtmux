import type { FormatFieldName } from "./format_field_names.js";

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
    criteriaName: "lastWindowIndex",
    domain: "string",
    token: "last_window_index",
    wireName: "last_window_index",
  }),
  Object.freeze({
    criteriaName: "name",
    domain: "string",
    token: "session_name",
    wireName: "name",
  }),
  Object.freeze({
    criteriaName: "activity",
    domain: "string",
    token: "session_activity",
    wireName: "session_activity",
  }),
  Object.freeze({
    criteriaName: "alerts",
    domain: "string",
    token: "session_alerts",
    wireName: "session_alerts",
  }),
  Object.freeze({
    criteriaName: "attached",
    domain: "string",
    token: "session_attached",
    wireName: "session_attached",
  }),
  Object.freeze({
    criteriaName: "attachedList",
    domain: "string",
    token: "session_attached_list",
    wireName: "session_attached_list",
  }),
  Object.freeze({
    criteriaName: "created",
    domain: "string",
    token: "session_created",
    wireName: "session_created",
  }),
  Object.freeze({
    criteriaName: "format",
    domain: "string",
    token: "session_format",
    wireName: "session_format",
  }),
  Object.freeze({
    criteriaName: "group",
    domain: "string",
    token: "session_group",
    wireName: "session_group",
  }),
  Object.freeze({
    criteriaName: "groupAttached",
    domain: "string",
    token: "session_group_attached",
    wireName: "session_group_attached",
  }),
  Object.freeze({
    criteriaName: "groupAttachedList",
    domain: "string",
    token: "session_group_attached_list",
    wireName: "session_group_attached_list",
  }),
  Object.freeze({
    criteriaName: "groupList",
    domain: "string",
    token: "session_group_list",
    wireName: "session_group_list",
  }),
  Object.freeze({
    criteriaName: "groupManyAttached",
    domain: "string",
    token: "session_group_many_attached",
    wireName: "session_group_many_attached",
  }),
  Object.freeze({
    criteriaName: "groupSize",
    domain: "string",
    token: "session_group_size",
    wireName: "session_group_size",
  }),
  Object.freeze({
    criteriaName: "grouped",
    domain: "string",
    token: "session_grouped",
    wireName: "session_grouped",
  }),
  Object.freeze({
    criteriaName: "id",
    domain: "string",
    token: "session_id",
    wireName: "session_id",
  }),
  Object.freeze({
    criteriaName: "lastAttached",
    domain: "string",
    token: "session_last_attached",
    wireName: "session_last_attached",
  }),
  Object.freeze({
    criteriaName: "manyAttached",
    domain: "string",
    token: "session_many_attached",
    wireName: "session_many_attached",
  }),
  Object.freeze({
    criteriaName: "marked",
    domain: "string",
    token: "session_marked",
    wireName: "session_marked",
  }),
  Object.freeze({
    criteriaName: "path",
    domain: "string",
    token: "session_path",
    wireName: "session_path",
  }),
  Object.freeze({
    criteriaName: "stack",
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
]);

const windowFields: readonly WhereField[] = Object.freeze([
  Object.freeze({ criteriaName: "name", domain: "string", token: "window_name", wireName: "name" }),
  Object.freeze({
    criteriaName: "active",
    domain: "string",
    token: "window_active",
    wireName: "window_active",
  }),
  Object.freeze({
    criteriaName: "activeClients",
    domain: "string",
    token: "window_active_clients",
    wireName: "window_active_clients",
  }),
  Object.freeze({
    criteriaName: "activeClientsList",
    domain: "string",
    token: "window_active_clients_list",
    wireName: "window_active_clients_list",
  }),
  Object.freeze({
    criteriaName: "activeSessions",
    domain: "string",
    token: "window_active_sessions",
    wireName: "window_active_sessions",
  }),
  Object.freeze({
    criteriaName: "activeSessionsList",
    domain: "string",
    token: "window_active_sessions_list",
    wireName: "window_active_sessions_list",
  }),
  Object.freeze({
    criteriaName: "activity",
    domain: "string",
    token: "window_activity",
    wireName: "window_activity",
  }),
  Object.freeze({
    criteriaName: "activityFlag",
    domain: "string",
    token: "window_activity_flag",
    wireName: "window_activity_flag",
  }),
  Object.freeze({
    criteriaName: "bellFlag",
    domain: "string",
    token: "window_bell_flag",
    wireName: "window_bell_flag",
  }),
  Object.freeze({
    criteriaName: "bigger",
    domain: "string",
    token: "window_bigger",
    wireName: "window_bigger",
  }),
  Object.freeze({
    criteriaName: "cellHeight",
    domain: "string",
    token: "window_cell_height",
    wireName: "window_cell_height",
  }),
  Object.freeze({
    criteriaName: "cellWidth",
    domain: "string",
    token: "window_cell_width",
    wireName: "window_cell_width",
  }),
  Object.freeze({
    criteriaName: "endFlag",
    domain: "string",
    token: "window_end_flag",
    wireName: "window_end_flag",
  }),
  Object.freeze({
    criteriaName: "flags",
    domain: "string",
    token: "window_flags",
    wireName: "window_flags",
  }),
  Object.freeze({
    criteriaName: "format",
    domain: "string",
    token: "window_format",
    wireName: "window_format",
  }),
  Object.freeze({
    criteriaName: "height",
    domain: "string",
    token: "window_height",
    wireName: "window_height",
  }),
  Object.freeze({
    criteriaName: "id",
    domain: "string",
    token: "window_id",
    wireName: "window_id",
  }),
  Object.freeze({
    criteriaName: "index",
    domain: "string",
    token: "window_index",
    wireName: "window_index",
  }),
  Object.freeze({
    criteriaName: "lastFlag",
    domain: "string",
    token: "window_last_flag",
    wireName: "window_last_flag",
  }),
  Object.freeze({
    criteriaName: "layout",
    domain: "string",
    token: "window_layout",
    wireName: "window_layout",
  }),
  Object.freeze({
    criteriaName: "linked",
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
    criteriaName: "linkedSessionsList",
    domain: "string",
    token: "window_linked_sessions_list",
    wireName: "window_linked_sessions_list",
  }),
  Object.freeze({
    criteriaName: "markedFlag",
    domain: "string",
    token: "window_marked_flag",
    wireName: "window_marked_flag",
  }),
  Object.freeze({
    criteriaName: "offsetX",
    domain: "string",
    token: "window_offset_x",
    wireName: "window_offset_x",
  }),
  Object.freeze({
    criteriaName: "offsetY",
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
    criteriaName: "rawFlags",
    domain: "string",
    token: "window_raw_flags",
    wireName: "window_raw_flags",
  }),
  Object.freeze({
    criteriaName: "silenceFlag",
    domain: "string",
    token: "window_silence_flag",
    wireName: "window_silence_flag",
  }),
  Object.freeze({
    criteriaName: "stackIndex",
    domain: "string",
    token: "window_stack_index",
    wireName: "window_stack_index",
  }),
  Object.freeze({
    criteriaName: "startFlag",
    domain: "string",
    token: "window_start_flag",
    wireName: "window_start_flag",
  }),
  Object.freeze({
    criteriaName: "visibleLayout",
    domain: "string",
    token: "window_visible_layout",
    wireName: "window_visible_layout",
  }),
  Object.freeze({
    criteriaName: "width",
    domain: "string",
    token: "window_width",
    wireName: "window_width",
  }),
  Object.freeze({
    criteriaName: "zoomedFlag",
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
    criteriaName: "originFlag",
    domain: "string",
    token: "origin_flag",
    wireName: "origin_flag",
  }),
  Object.freeze({
    criteriaName: "active",
    domain: "string",
    token: "pane_active",
    wireName: "pane_active",
  }),
  Object.freeze({
    criteriaName: "atBottom",
    domain: "string",
    token: "pane_at_bottom",
    wireName: "pane_at_bottom",
  }),
  Object.freeze({
    criteriaName: "atLeft",
    domain: "string",
    token: "pane_at_left",
    wireName: "pane_at_left",
  }),
  Object.freeze({
    criteriaName: "atRight",
    domain: "string",
    token: "pane_at_right",
    wireName: "pane_at_right",
  }),
  Object.freeze({
    criteriaName: "atTop",
    domain: "string",
    token: "pane_at_top",
    wireName: "pane_at_top",
  }),
  Object.freeze({ criteriaName: "bg", domain: "string", token: "pane_bg", wireName: "pane_bg" }),
  Object.freeze({
    criteriaName: "bottom",
    domain: "string",
    token: "pane_bottom",
    wireName: "pane_bottom",
  }),
  Object.freeze({
    criteriaName: "currentCommand",
    domain: "string",
    token: "pane_current_command",
    wireName: "pane_current_command",
  }),
  Object.freeze({
    criteriaName: "currentPath",
    domain: "string",
    token: "pane_current_path",
    wireName: "pane_current_path",
  }),
  Object.freeze({
    criteriaName: "dead",
    domain: "string",
    token: "pane_dead",
    wireName: "pane_dead",
  }),
  Object.freeze({
    criteriaName: "deadSignal",
    domain: "string",
    token: "pane_dead_signal",
    wireName: "pane_dead_signal",
  }),
  Object.freeze({
    criteriaName: "deadStatus",
    domain: "string",
    token: "pane_dead_status",
    wireName: "pane_dead_status",
  }),
  Object.freeze({
    criteriaName: "deadTime",
    domain: "string",
    token: "pane_dead_time",
    wireName: "pane_dead_time",
  }),
  Object.freeze({ criteriaName: "fg", domain: "string", token: "pane_fg", wireName: "pane_fg" }),
  Object.freeze({
    criteriaName: "flags",
    domain: "string",
    token: "pane_flags",
    wireName: "pane_flags",
  }),
  Object.freeze({
    criteriaName: "floatingFlag",
    domain: "string",
    token: "pane_floating_flag",
    wireName: "pane_floating_flag",
  }),
  Object.freeze({
    criteriaName: "format",
    domain: "string",
    token: "pane_format",
    wireName: "pane_format",
  }),
  Object.freeze({
    criteriaName: "height",
    domain: "string",
    token: "pane_height",
    wireName: "pane_height",
  }),
  Object.freeze({ criteriaName: "id", domain: "string", token: "pane_id", wireName: "pane_id" }),
  Object.freeze({
    criteriaName: "inMode",
    domain: "string",
    token: "pane_in_mode",
    wireName: "pane_in_mode",
  }),
  Object.freeze({
    criteriaName: "index",
    domain: "string",
    token: "pane_index",
    wireName: "pane_index",
  }),
  Object.freeze({
    criteriaName: "inputOff",
    domain: "string",
    token: "pane_input_off",
    wireName: "pane_input_off",
  }),
  Object.freeze({
    criteriaName: "last",
    domain: "string",
    token: "pane_last",
    wireName: "pane_last",
  }),
  Object.freeze({
    criteriaName: "left",
    domain: "string",
    token: "pane_left",
    wireName: "pane_left",
  }),
  Object.freeze({
    criteriaName: "marked",
    domain: "string",
    token: "pane_marked",
    wireName: "pane_marked",
  }),
  Object.freeze({
    criteriaName: "markedSet",
    domain: "string",
    token: "pane_marked_set",
    wireName: "pane_marked_set",
  }),
  Object.freeze({
    criteriaName: "mode",
    domain: "string",
    token: "pane_mode",
    wireName: "pane_mode",
  }),
  Object.freeze({
    criteriaName: "path",
    domain: "string",
    token: "pane_path",
    wireName: "pane_path",
  }),
  Object.freeze({
    criteriaName: "pbProgress",
    domain: "string",
    token: "pane_pb_progress",
    wireName: "pane_pb_progress",
  }),
  Object.freeze({
    criteriaName: "pbState",
    domain: "string",
    token: "pane_pb_state",
    wireName: "pane_pb_state",
  }),
  Object.freeze({ criteriaName: "pid", domain: "string", token: "pane_pid", wireName: "pane_pid" }),
  Object.freeze({
    criteriaName: "pipe",
    domain: "string",
    token: "pane_pipe",
    wireName: "pane_pipe",
  }),
  Object.freeze({
    criteriaName: "pipePid",
    domain: "string",
    token: "pane_pipe_pid",
    wireName: "pane_pipe_pid",
  }),
  Object.freeze({
    criteriaName: "right",
    domain: "string",
    token: "pane_right",
    wireName: "pane_right",
  }),
  Object.freeze({
    criteriaName: "searchString",
    domain: "string",
    token: "pane_search_string",
    wireName: "pane_search_string",
  }),
  Object.freeze({
    criteriaName: "startCommand",
    domain: "string",
    token: "pane_start_command",
    wireName: "pane_start_command",
  }),
  Object.freeze({
    criteriaName: "startPath",
    domain: "string",
    token: "pane_start_path",
    wireName: "pane_start_path",
  }),
  Object.freeze({
    criteriaName: "synchronized",
    domain: "string",
    token: "pane_synchronized",
    wireName: "pane_synchronized",
  }),
  Object.freeze({
    criteriaName: "tabs",
    domain: "string",
    token: "pane_tabs",
    wireName: "pane_tabs",
  }),
  Object.freeze({
    criteriaName: "title",
    domain: "string",
    token: "pane_title",
    wireName: "pane_title",
  }),
  Object.freeze({ criteriaName: "top", domain: "string", token: "pane_top", wireName: "pane_top" }),
  Object.freeze({ criteriaName: "tty", domain: "string", token: "pane_tty", wireName: "pane_tty" }),
  Object.freeze({
    criteriaName: "width",
    domain: "string",
    token: "pane_width",
    wireName: "pane_width",
  }),
  Object.freeze({ criteriaName: "x", domain: "string", token: "pane_x", wireName: "pane_x" }),
  Object.freeze({ criteriaName: "y", domain: "string", token: "pane_y", wireName: "pane_y" }),
  Object.freeze({ criteriaName: "z", domain: "string", token: "pane_z", wireName: "pane_z" }),
  Object.freeze({
    criteriaName: "zoomedFlag",
    domain: "string",
    token: "pane_zoomed_flag",
    wireName: "pane_zoomed_flag",
  }),
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
    criteriaName: "synchronizedOutputFlag",
    domain: "string",
    token: "synchronized_output_flag",
    wireName: "synchronized_output_flag",
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
