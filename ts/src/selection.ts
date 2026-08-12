import type { ModelKindOf } from "./_internal/runtime/model_kind.js";
import { parseLegacyWhere as lowerLegacyWhere } from "./_internal/selection/legacy.js";

type StringFilterFields = {
  readonly contains?: string;
  readonly endsWith?: string;
  readonly equals?: string | null;
  readonly in?: readonly string[];
  readonly mode?: "insensitive";
  readonly notIn?: readonly string[];
  readonly regex?: RegexCriteriaData;
  readonly startsWith?: string;
};

type StringFilter = StringFilterFields &
  (
    | { readonly contains: string }
    | { readonly endsWith: string }
    | { readonly equals: string | null }
    | { readonly in: readonly string[] }
    | { readonly notIn: readonly string[] }
    | { readonly regex: RegexCriteriaData }
    | { readonly startsWith: string }
  );

type ScalarCriteria = string | null | StringFilter;

type ManyRelation<Where> =
  | { readonly every?: Where; readonly none?: Where; readonly some: Where }
  | { readonly every: Where; readonly none?: Where; readonly some?: Where }
  | { readonly every?: Where; readonly none: Where; readonly some?: Where };

type OneRelation<Where> =
  | { readonly is: Where | null; readonly isNot?: Where | null }
  | { readonly is?: Where | null; readonly isNot: Where | null };

export interface RegexCriteriaData {
  readonly flags: "" | "m" | "s" | "ms";
  readonly pattern: string;
}

// <libtmux-generated-where-types>
export interface SessionWhere {
  readonly AND?: readonly SessionWhere[];
  readonly OR?: readonly SessionWhere[];
  readonly NOT?: readonly SessionWhere[];
  readonly active_window_index?: ScalarCriteria;
  readonly config_files?: ScalarCriteria;
  readonly last_window_index?: ScalarCriteria;
  readonly line?: ScalarCriteria;
  readonly name?: ScalarCriteria;
  readonly next_session_id?: ScalarCriteria;
  readonly pid?: ScalarCriteria;
  readonly session_activity?: ScalarCriteria;
  readonly session_alerts?: ScalarCriteria;
  readonly session_attached?: ScalarCriteria;
  readonly session_attached_list?: ScalarCriteria;
  readonly session_created?: ScalarCriteria;
  readonly session_format?: ScalarCriteria;
  readonly session_group?: ScalarCriteria;
  readonly session_group_attached?: ScalarCriteria;
  readonly session_group_attached_list?: ScalarCriteria;
  readonly session_group_list?: ScalarCriteria;
  readonly session_group_many_attached?: ScalarCriteria;
  readonly session_group_size?: ScalarCriteria;
  readonly session_grouped?: ScalarCriteria;
  readonly session_id?: ScalarCriteria;
  readonly session_last_attached?: ScalarCriteria;
  readonly session_many_attached?: ScalarCriteria;
  readonly session_marked?: ScalarCriteria;
  readonly session_path?: ScalarCriteria;
  readonly session_stack?: ScalarCriteria;
  readonly session_windows?: ScalarCriteria;
  readonly socket_path?: ScalarCriteria;
  readonly start_time?: ScalarCriteria;
  readonly uid?: ScalarCriteria;
  readonly user?: ScalarCriteria;
  readonly version?: ScalarCriteria;
  readonly windows?: ManyRelation<WindowWhere>;
  readonly panes?: ManyRelation<PaneWhere>;
  readonly active_window?: OneRelation<WindowWhere>;
  readonly active_pane?: OneRelation<PaneWhere>;
}

export interface WindowWhere {
  readonly AND?: readonly WindowWhere[];
  readonly OR?: readonly WindowWhere[];
  readonly NOT?: readonly WindowWhere[];
  readonly config_files?: ScalarCriteria;
  readonly line?: ScalarCriteria;
  readonly name?: ScalarCriteria;
  readonly next_session_id?: ScalarCriteria;
  readonly pid?: ScalarCriteria;
  readonly socket_path?: ScalarCriteria;
  readonly start_time?: ScalarCriteria;
  readonly uid?: ScalarCriteria;
  readonly user?: ScalarCriteria;
  readonly version?: ScalarCriteria;
  readonly window_active?: ScalarCriteria;
  readonly window_active_clients?: ScalarCriteria;
  readonly window_active_clients_list?: ScalarCriteria;
  readonly window_active_sessions?: ScalarCriteria;
  readonly window_active_sessions_list?: ScalarCriteria;
  readonly window_activity?: ScalarCriteria;
  readonly window_activity_flag?: ScalarCriteria;
  readonly window_bell_flag?: ScalarCriteria;
  readonly window_bigger?: ScalarCriteria;
  readonly window_cell_height?: ScalarCriteria;
  readonly window_cell_width?: ScalarCriteria;
  readonly window_end_flag?: ScalarCriteria;
  readonly window_flags?: ScalarCriteria;
  readonly window_format?: ScalarCriteria;
  readonly window_height?: ScalarCriteria;
  readonly window_id?: ScalarCriteria;
  readonly window_index?: ScalarCriteria;
  readonly window_last_flag?: ScalarCriteria;
  readonly window_layout?: ScalarCriteria;
  readonly window_linked?: ScalarCriteria;
  readonly window_linked_sessions?: ScalarCriteria;
  readonly window_linked_sessions_list?: ScalarCriteria;
  readonly window_marked_flag?: ScalarCriteria;
  readonly window_offset_x?: ScalarCriteria;
  readonly window_offset_y?: ScalarCriteria;
  readonly window_panes?: ScalarCriteria;
  readonly window_raw_flags?: ScalarCriteria;
  readonly window_silence_flag?: ScalarCriteria;
  readonly window_stack_index?: ScalarCriteria;
  readonly window_start_flag?: ScalarCriteria;
  readonly window_visible_layout?: ScalarCriteria;
  readonly window_width?: ScalarCriteria;
  readonly window_zoomed_flag?: ScalarCriteria;
  readonly session?: OneRelation<SessionWhere>;
  readonly linked_sessions?: ManyRelation<SessionWhere>;
  readonly panes?: ManyRelation<PaneWhere>;
  readonly active_pane?: OneRelation<PaneWhere>;
}

export interface PaneWhere {
  readonly AND?: readonly PaneWhere[];
  readonly OR?: readonly PaneWhere[];
  readonly NOT?: readonly PaneWhere[];
  readonly alternate_saved_x?: ScalarCriteria;
  readonly alternate_saved_y?: ScalarCriteria;
  readonly bracket_paste_flag?: ScalarCriteria;
  readonly config_files?: ScalarCriteria;
  readonly cursor_character?: ScalarCriteria;
  readonly cursor_flag?: ScalarCriteria;
  readonly cursor_x?: ScalarCriteria;
  readonly cursor_y?: ScalarCriteria;
  readonly history_bytes?: ScalarCriteria;
  readonly history_limit?: ScalarCriteria;
  readonly history_size?: ScalarCriteria;
  readonly insert_flag?: ScalarCriteria;
  readonly keypad_cursor_flag?: ScalarCriteria;
  readonly keypad_flag?: ScalarCriteria;
  readonly line?: ScalarCriteria;
  readonly mouse_all_flag?: ScalarCriteria;
  readonly mouse_any_flag?: ScalarCriteria;
  readonly mouse_button_flag?: ScalarCriteria;
  readonly mouse_sgr_flag?: ScalarCriteria;
  readonly mouse_standard_flag?: ScalarCriteria;
  readonly next_session_id?: ScalarCriteria;
  readonly origin_flag?: ScalarCriteria;
  readonly pane_active?: ScalarCriteria;
  readonly pane_at_bottom?: ScalarCriteria;
  readonly pane_at_left?: ScalarCriteria;
  readonly pane_at_right?: ScalarCriteria;
  readonly pane_at_top?: ScalarCriteria;
  readonly pane_bg?: ScalarCriteria;
  readonly pane_bottom?: ScalarCriteria;
  readonly pane_current_command?: ScalarCriteria;
  readonly pane_current_path?: ScalarCriteria;
  readonly pane_dead?: ScalarCriteria;
  readonly pane_dead_signal?: ScalarCriteria;
  readonly pane_dead_status?: ScalarCriteria;
  readonly pane_dead_time?: ScalarCriteria;
  readonly pane_fg?: ScalarCriteria;
  readonly pane_flags?: ScalarCriteria;
  readonly pane_floating_flag?: ScalarCriteria;
  readonly pane_format?: ScalarCriteria;
  readonly pane_height?: ScalarCriteria;
  readonly pane_id?: ScalarCriteria;
  readonly pane_in_mode?: ScalarCriteria;
  readonly pane_index?: ScalarCriteria;
  readonly pane_input_off?: ScalarCriteria;
  readonly pane_last?: ScalarCriteria;
  readonly pane_left?: ScalarCriteria;
  readonly pane_marked?: ScalarCriteria;
  readonly pane_marked_set?: ScalarCriteria;
  readonly pane_mode?: ScalarCriteria;
  readonly pane_path?: ScalarCriteria;
  readonly pane_pb_progress?: ScalarCriteria;
  readonly pane_pb_state?: ScalarCriteria;
  readonly pane_pid?: ScalarCriteria;
  readonly pane_pipe?: ScalarCriteria;
  readonly pane_pipe_pid?: ScalarCriteria;
  readonly pane_right?: ScalarCriteria;
  readonly pane_search_string?: ScalarCriteria;
  readonly pane_start_command?: ScalarCriteria;
  readonly pane_start_path?: ScalarCriteria;
  readonly pane_synchronized?: ScalarCriteria;
  readonly pane_tabs?: ScalarCriteria;
  readonly pane_title?: ScalarCriteria;
  readonly pane_top?: ScalarCriteria;
  readonly pane_tty?: ScalarCriteria;
  readonly pane_width?: ScalarCriteria;
  readonly pane_x?: ScalarCriteria;
  readonly pane_y?: ScalarCriteria;
  readonly pane_z?: ScalarCriteria;
  readonly pane_zoomed_flag?: ScalarCriteria;
  readonly pid?: ScalarCriteria;
  readonly scroll_region_lower?: ScalarCriteria;
  readonly scroll_region_upper?: ScalarCriteria;
  readonly socket_path?: ScalarCriteria;
  readonly start_time?: ScalarCriteria;
  readonly synchronized_output_flag?: ScalarCriteria;
  readonly uid?: ScalarCriteria;
  readonly user?: ScalarCriteria;
  readonly version?: ScalarCriteria;
  readonly wrap_flag?: ScalarCriteria;
  readonly window?: OneRelation<WindowWhere>;
  readonly session?: OneRelation<SessionWhere>;
}

// </libtmux-generated-where-types>

type WhereForKind<Kind> = Kind extends "session"
  ? SessionWhere
  : Kind extends "window"
    ? WindowWhere
    : Kind extends "pane"
      ? PaneWhere
      : never;

export type WhereOf<Model> = WhereForKind<ModelKindOf<Model>>;

export interface Selection<Model> extends Iterable<Model> {
  readonly length: number;
  [Symbol.iterator](): IterableIterator<Model>;
  at(index: number): Model | undefined;
  toArray(): Model[];
  filter(
    predicate: (value: Model, index: number, values: readonly Model[]) => unknown,
    thisArg?: unknown,
  ): Selection<Model>;
  where(criteria: WhereOf<Model>): Selection<Model>;
  first(criteria?: WhereOf<Model>): Model | undefined;
  one(criteria?: WhereOf<Model>): Model;
  oneOrUndefined(criteria?: WhereOf<Model>): Model | undefined;
  exists(criteria?: WhereOf<Model>): boolean;
  count(criteria?: WhereOf<Model>): number;
}

export type WhereDocumentV1 =
  | { readonly model: "session"; readonly version: 1; readonly where: SessionWhere }
  | { readonly model: "window"; readonly version: 1; readonly where: WindowWhere }
  | { readonly model: "pane"; readonly version: 1; readonly where: PaneWhere };

export function parseLegacyWhere<Model extends "session" | "window">(
  model: Model,
  input: unknown,
): Extract<WhereDocumentV1, { readonly model: Model }> {
  return lowerLegacyWhere(model, input);
}
