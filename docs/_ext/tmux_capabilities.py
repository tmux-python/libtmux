"""Render libtmux's tmux capability manifest as a linked Sphinx matrix.

Reads :func:`libtmux._internal.support.capabilities.manifest` (or an override
in ``tmux_capabilities_manifest``) and emits a docutils table mapping each
gated capability and release workaround against tmux versions, with
Python-domain cross-references for every public API and refusal exception.

Examples
--------
>>> tmux_version_key("next-3.9") < tmux_version_key("3.9-rc1") < tmux_version_key("3.9")
True
>>> tmux_version_key("3.2") < tmux_version_key("3.2a")
True
"""

from __future__ import annotations

import inspect
import pathlib
import re
import typing as t
from dataclasses import dataclass

from docutils import nodes
from docutils.parsers.rst import directives
from sphinx import addnodes
from sphinx.util.docutils import SphinxDirective
from sphinx_ux_badges import SAB, build_badge

from libtmux._internal.support import capabilities as support_capabilities

if t.TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sphinx.application import Sphinx
    from sphinx.util.typing import ExtensionMetadata, OptionSpec

CellState: t.TypeAlias = t.Literal[
    "supported",
    "workaround",
    "repaired",
    "fallback",
    "refused",
]

DEFAULT_TMUX_SERIES: tuple[str, ...] = (
    "3.2a",
    "3.3a",
    "3.4",
    "3.5",
    "3.6",
    "3.7",
    "3.8",
)

CELL_ICON: dict[CellState, str] = {
    "supported": "✓",
    "workaround": "◐",
    "repaired": "◐",
    "fallback": "↺",
    "refused": "✕",
}

CELL_LABEL: dict[CellState, str] = {
    "supported": "Works",
    "workaround": "Works with a workaround",
    "repaired": "Repaired after the command",
    "fallback": "Warns and falls back",
    "refused": "Refused with an error",
}

LEGEND_ORDER: tuple[CellState, ...] = (
    "supported",
    "workaround",
    "repaired",
    "fallback",
    "refused",
)

_VERSION_RE: t.Final[re.Pattern[str]] = re.compile(
    r"^(?:next-(0|[1-9]\d*)\.(0|[1-9]\d*)|(0|[1-9]\d*)\.(0|[1-9]\d*)([a-z]?)(?:-rc(\d*))?)$",
)


@dataclass(frozen=True, slots=True)
class ReleaseColumn:
    """One tmux release column or collapsed release range in the matrix.

    Attributes
    ----------
    key : str
        Representative tmux release evaluated for every row in this column.
    label : str
        Header label rendered in ``<thead>``.
    title : str
        Full release description used in cell tooltips and ARIA labels.
    """

    key: str
    label: str
    title: str


def tmux_version_key(version: str) -> tuple[int, int, int, int, int]:
    """Return a sortable key in tmux's release order.

    Orders ``next-X.Y < X.Y-rc < X.Y-rcN < X.Y < X.Ya`` and rejects strings
    tmux never prints.

    Parameters
    ----------
    version : str
        tmux release identifier such as ``"3.2a"``, ``"3.7"``, ``"3.8-rc1"``,
        or ``"next-3.9"``.

    Returns
    -------
    tuple[int, int, int, int, int]
        Sortable tuple ``(major, minor, stage, rc_number, patch_letter)``.

    Raises
    ------
    ValueError
        If *version* does not match tmux's release grammar.

    Examples
    --------
    >>> versions = ["3.7a", "3.7", "3.7-rc2", "3.7-rc", "next-3.7"]
    >>> sorted(versions, key=tmux_version_key)
    ['next-3.7', '3.7-rc', '3.7-rc2', '3.7', '3.7a']
    """
    match = _VERSION_RE.match(version.strip())
    if match is None:
        msg = f"Not a tmux release string: {version!r}"
        raise ValueError(msg)
    if match.group(1) is not None:
        return (int(match.group(1)), int(match.group(2)), 0, 0, 0)
    major = int(match.group(3))
    minor = int(match.group(4))
    patch = match.group(5)
    rc_digits = match.group(6)
    letter = ord(patch) - ord("a") + 1 if patch else 0
    if rc_digits is not None:
        if letter:
            msg = f"Release candidate cannot carry a patch letter: {version!r}"
            raise ValueError(msg)
        return (major, minor, 1, int(rc_digits) if rc_digits else 0, 0)
    return (major, minor, 2, 0, letter)


def resolve_versions(
    floor_minimum: str,
    entries: Sequence[Mapping[str, t.Any]],
    explicit: str | None = None,
) -> tuple[str, ...]:
    """Return the ordered tmux release identifiers to render as columns.

    Parameters
    ----------
    floor_minimum : str
        Minimum supported tmux release from the manifest ``floor``.
    entries : Sequence[Mapping[str, Any]]
        Capability and workaround mappings displayed in the matrix.
    explicit : str or None, optional
        Comma- or whitespace-separated release list supplied via ``:versions:``.

    Returns
    -------
    tuple[str, ...]
        Validated tmux release strings in column order.

    Raises
    ------
    ValueError
        If *explicit* is empty or contains an invalid tmux release string.

    Examples
    --------
    >>> resolve_versions("3.2a", ())
    ('3.2a', '3.3a', '3.4', '3.5', '3.6', '3.7', '3.8')
    >>> resolve_versions("3.3a", ())
    ('3.3a', '3.4', '3.5', '3.6', '3.7', '3.8')
    >>> resolve_versions("3.2a", ({"since": "3.9"},))[-1]
    '3.9'
    """
    if explicit is not None:
        tokens = [
            token for chunk in explicit.split(",") for token in chunk.split() if token
        ]
        if not tokens:
            msg = ":versions: requires at least one tmux release"
            raise ValueError(msg)
        deduped: list[str] = []
        for token in tokens:
            tmux_version_key(token)
            if token not in deduped:
                deduped.append(token)
        return tuple(deduped)

    floor_key = tmux_version_key(floor_minimum)
    selected = [
        release
        for release in DEFAULT_TMUX_SERIES
        if tmux_version_key(release) >= floor_key
    ]
    if floor_minimum not in selected and (
        not selected or floor_key < tmux_version_key(selected[0])
    ):
        selected.insert(0, floor_minimum)

    highest_key = tmux_version_key(selected[-1]) if selected else floor_key
    extra: set[str] = set()
    for entry in entries:
        since = entry.get("since")
        if isinstance(since, str) and tmux_version_key(since) > highest_key:
            extra.add(since)
        for key_name in ("except", "releases"):
            for rel in entry.get(key_name, ()):
                if isinstance(rel, str) and tmux_version_key(rel) > highest_key:
                    extra.add(rel)

    selected.extend(sorted(extra, key=tmux_version_key))
    return tuple(selected)


def capability_state(entry: Mapping[str, t.Any], release: str) -> CellState:
    """Return what libtmux does for *entry* on tmux *release*.

    Parameters
    ----------
    entry : Mapping[str, Any]
        Manifest capability dictionary.
    release : str
        Target tmux release identifier.

    Returns
    -------
    CellState
        Evaluated behaviour for the matrix cell.

    Examples
    --------
    >>> cap = {"since": "3.6", "handling": "fallback"}
    >>> capability_state(cap, "3.5"), capability_state(cap, "3.6")
    ('fallback', 'supported')
    """
    rel_key = tmux_version_key(release)
    since_key = tmux_version_key(str(entry["since"]))
    excepted = {str(v) for v in entry.get("except", ())}
    in_until = True
    until_raw = entry.get("until")
    if isinstance(until_raw, str):
        until_key = tmux_version_key(until_raw)
        bound = (
            (until_key[0], until_key[1], 0, 0, 0)
            if until_key[2] == 2 and until_key[4] == 0
            else until_key
        )
        in_until = rel_key < bound

    if rel_key >= since_key and in_until and release not in excepted:
        return "supported"

    handling = str(entry["handling"])
    if handling == "fallback":
        return "fallback"
    if handling == "repair":
        return "repaired"
    return "refused"


def workaround_state(entry: Mapping[str, t.Any], release: str) -> CellState:
    """Return what libtmux does for workaround *entry* on tmux *release*.

    Parameters
    ----------
    entry : Mapping[str, Any]
        Manifest workaround dictionary.
    release : str
        Target tmux release identifier.

    Returns
    -------
    CellState
        Evaluated behaviour for the matrix cell.

    Examples
    --------
    >>> wa = {"releases": ["3.7"], "handling": "repair"}
    >>> workaround_state(wa, "3.6"), workaround_state(wa, "3.7")
    ('supported', 'workaround')
    """
    affected = {str(v) for v in entry.get("releases", ())}
    if release not in affected:
        return "supported"
    return "workaround" if entry.get("handling") == "repair" else "refused"


def _release_label(release: str) -> str:
    return (
        release.replace("next-", "next ", 1) if release.startswith("next-") else release
    )


def _release_title(release: str) -> str:
    if release.startswith("next-"):
        return f"tmux {release} (development)"
    return f"tmux {release}"


def build_release_columns(
    versions: Sequence[str],
    capabilities: Sequence[Mapping[str, t.Any]],
    workarounds: Sequence[Mapping[str, t.Any]] = (),
    *,
    group_releases: bool = False,
) -> tuple[ReleaseColumn, ...]:
    """Build column headers for *versions*, merging identical runs when asked.

    Parameters
    ----------
    versions : Sequence[str]
        Ordered tmux release strings.
    capabilities : Sequence[Mapping[str, Any]]
        Capability entries displayed in the matrix.
    workarounds : Sequence[Mapping[str, Any]], optional
        Workaround entries displayed alongside *capabilities*.
    group_releases : bool, optional
        Merge neighbouring releases whose cell states never differ.

    Returns
    -------
    tuple[ReleaseColumn, ...]
        Columns ready for table rendering.

    Examples
    --------
    >>> caps = [{"since": "3.4", "handling": "fallback"}]
    >>> cols = build_release_columns(
    ...     ("3.2a", "3.3a", "3.4", "3.5"), caps, group_releases=True
    ... )
    >>> [c.label for c in cols]
    ['3.2a-3.3a', '3.4-3.5']
    """
    if not group_releases:
        return tuple(
            ReleaseColumn(
                key=version,
                label=_release_label(version),
                title=_release_title(version),
            )
            for version in versions
        )

    def _signature(version: str) -> tuple[CellState, ...]:
        return (
            *(capability_state(cap, version) for cap in capabilities),
            *(workaround_state(wa, version) for wa in workarounds),
        )

    groups: list[list[str]] = []
    for version in versions:
        if groups and _signature(groups[-1][0]) == _signature(version):
            groups[-1].append(version)
        else:
            groups.append([version])

    return tuple(
        ReleaseColumn(
            key=group[0],
            label=(
                _release_label(group[0])
                if len(group) == 1
                else f"{_release_label(group[0])}-{_release_label(group[-1])}"
            ),
            title=(
                _release_title(group[0])
                if len(group) == 1
                else f"tmux {', '.join(group)}"
            ),
        )
        for group in groups
    )


def short_py_name(target: str) -> str:
    """Strip the leading ``libtmux.`` package prefix for compact display.

    Parameters
    ----------
    target : str
        Dotted Python import path.

    Returns
    -------
    str
        Compact display label.

    Examples
    --------
    >>> short_py_name("libtmux.Pane.capture_pane")
    'Pane.capture_pane'
    >>> short_py_name("libtmux.exc.LibTmuxException")
    'exc.LibTmuxException'
    """
    return target.removeprefix("libtmux.")


def build_py_xref(target: str, display: str | None = None) -> addnodes.pending_xref:
    """Create a Python-domain cross-reference chip that warns when unresolved.

    Parameters
    ----------
    target : str
        Fully-qualified dotted symbol path in the ``py`` domain.
    display : str or None, optional
        Visible literal text; defaults to :func:`short_py_name`.

    Returns
    -------
    sphinx.addnodes.pending_xref
        Cross-reference node resolved by Sphinx's Python domain.

    Examples
    --------
    >>> xref = build_py_xref("libtmux.Server.run_shell")
    >>> xref["refdomain"], xref["reftype"], xref["reftarget"], xref["refwarn"]
    ('py', 'obj', 'libtmux.Server.run_shell', True)
    >>> xref.astext()
    'Server.run_shell'
    """
    label = display if display is not None else short_py_name(target)
    literal = nodes.literal(
        "",
        "",
        nodes.Text(label),
        classes=["xref", "py", "py-obj"],
    )
    return addnodes.pending_xref(
        "",
        literal,
        refdomain="py",
        reftype="obj",
        reftarget=target,
        refexplicit=True,
        refwarn=True,
    )


def _matches_api(entry: Mapping[str, t.Any], api_prefix: str) -> bool:
    return any(
        isinstance(api, str) and (api == api_prefix or api.startswith(f"{api_prefix}."))
        for api in entry.get("apis", ())
    )


def _format_command(cmd_entry: Mapping[str, t.Any]) -> str:
    command = str(cmd_entry["command"])
    flags = [str(flag) for flag in cmd_entry.get("flags", ())]
    return " ".join([command, *flags])


def _build_stub_cell(entry: Mapping[str, t.Any]) -> nodes.entry:
    cell = nodes.entry()
    title = nodes.paragraph(classes=["tmux-cap-title"])
    title += nodes.strong("", str(entry["name"]))
    cell += title

    summary_text = str(entry.get("summary", "")).strip()
    if summary_text:
        cell += nodes.paragraph("", summary_text, classes=["tmux-cap-summary"])

    commands = list(entry.get("commands", ()))
    error_name = entry.get("error")
    if commands or isinstance(error_name, str):
        meta = nodes.paragraph(classes=["tmux-cap-meta"])
        for idx, cmd_entry in enumerate(commands):
            if idx:
                meta += nodes.Text(", ")
            rendered_cmd = _format_command(cmd_entry)
            meta += nodes.literal(rendered_cmd, rendered_cmd)
        if isinstance(error_name, str):
            if commands:
                meta += nodes.Text(" · raises ")
            else:
                meta += nodes.Text("Raises ")
            meta += build_py_xref(error_name)
        cell += meta
    return cell


def _build_api_cell(entry: Mapping[str, t.Any]) -> nodes.entry:
    cell = nodes.entry(classes=["tmux-cap-api-col"])
    paragraph = nodes.paragraph()
    apis = [str(api) for api in entry.get("apis", ())]
    if not apis:
        paragraph += nodes.literal("—", "—")
    else:
        for idx, api in enumerate(apis):
            if idx:
                paragraph += nodes.Text(", ")
            paragraph += build_py_xref(api)
    cell += paragraph
    return cell


def _build_state_badge(
    state: CellState,
    *,
    tooltip: str,
    tabindex: str = "0",
) -> nodes.Node:
    return build_badge(
        CELL_ICON[state],
        tooltip=tooltip,
        classes=[
            SAB.DENSE,
            SAB.NO_UNDERLINE,
            f"gp-sphinx-badge--cap-{state}",
        ],
        size="xs",
        tabindex=tabindex,
    )


def _build_matrix_table(
    entries: Sequence[Mapping[str, t.Any]],
    columns: Sequence[ReleaseColumn],
    *,
    row_header: str,
    state_fn: t.Callable[[Mapping[str, t.Any], str], CellState],
    seen_states: set[CellState],
) -> nodes.table:
    table = nodes.table(classes=["tmux-capabilities-table", "colwidths-auto"])
    tgroup = nodes.tgroup(cols=2 + len(columns))
    table += tgroup

    tgroup += nodes.colspec(colwidth=28, stub=1)
    tgroup += nodes.colspec(colwidth=20)
    for _ in columns:
        tgroup += nodes.colspec(colwidth=7)

    thead = nodes.thead()
    header_row = nodes.row()
    header_row += nodes.entry("", nodes.paragraph("", row_header))
    header_row += nodes.entry("", nodes.paragraph("", "API"))
    for column in columns:
        th = nodes.entry(classes=["tmux-cap-version-col"])
        th += nodes.paragraph("", column.label)
        header_row += th
    thead += header_row
    tgroup += thead

    tbody = nodes.tbody()
    for entry in entries:
        entry_id = nodes.make_id(f"cap-{entry['id']}")
        row = nodes.row(ids=[entry_id] if entry_id else [])
        row += _build_stub_cell(entry)
        row += _build_api_cell(entry)

        error_name = entry.get("error")
        for column in columns:
            state = state_fn(entry, column.key)
            seen_states.add(state)
            detail = CELL_LABEL[state]
            if state == "refused" and isinstance(error_name, str):
                detail = f"{detail} ({short_py_name(error_name)})"
            tooltip = f"{entry['name']}, {column.title}: {detail}"
            td = nodes.entry(classes=["tmux-cap-cell"])
            td += nodes.paragraph("", "", _build_state_badge(state, tooltip=tooltip))
            row += td
        tbody += row
    tgroup += tbody
    return table


def _build_legend(seen_states: set[CellState]) -> nodes.bullet_list:
    legend = nodes.bullet_list(classes=["tmux-capabilities-legend"])
    for state in LEGEND_ORDER:
        if state not in seen_states:
            continue
        item = nodes.list_item()
        paragraph = nodes.paragraph()
        paragraph += _build_state_badge(
            state,
            tooltip=CELL_LABEL[state],
            tabindex="",
        )
        paragraph += nodes.Text(f" {CELL_LABEL[state]}")
        item += paragraph
        legend += item
    return legend


class TmuxCapabilitiesDirective(SphinxDirective):
    """Render the capability and workaround matrices from the capability table.

    Supported options:

    - ``:versions:`` — comma- or space-separated tmux release columns.
    - ``:api:`` — dotted Python API prefix filter (for example ``libtmux.Pane``).
    - ``:group-releases:`` — merge consecutive releases with identical states.
    - ``:no-legend:`` — omit the badge legend beneath the table.
    """

    has_content: t.ClassVar[bool] = False
    required_arguments: t.ClassVar[int] = 0
    optional_arguments: t.ClassVar[int] = 0
    # Directive declares mutable ClassVar[OptionSpec | None], invariant on subclasses.
    option_spec: t.ClassVar[OptionSpec | None] = {
        "versions": directives.unchanged,
        "api": directives.unchanged,
        "group-releases": directives.flag,
        "no-legend": directives.flag,
    }

    def _load_manifest(self) -> Mapping[str, t.Any]:
        override = self.config.tmux_capabilities_manifest
        if isinstance(override, dict):
            return override
        source_file = inspect.getsourcefile(support_capabilities)
        if source_file is not None:
            self.env.note_dependency(source_file)
        return support_capabilities.manifest()

    def run(self) -> list[nodes.Node]:
        """Build the capability matrix nodes for the current document."""
        doc = self._load_manifest()
        floor_minimum = str(doc.get("floor", {}).get("minimum", "3.2a"))
        capabilities: list[Mapping[str, t.Any]] = list(doc.get("capabilities", ()))
        workarounds: list[Mapping[str, t.Any]] = list(doc.get("workarounds", ()))

        api_filter = self.options.get("api")
        if isinstance(api_filter, str) and api_filter.strip():
            prefix = api_filter.strip()
            capabilities = [c for c in capabilities if _matches_api(c, prefix)]
            workarounds = [w for w in workarounds if _matches_api(w, prefix)]
            if not capabilities and not workarounds:
                msg = (
                    f"tmux-capabilities :api: {prefix!r} matched no capability entries"
                )
                return [self.state_machine.reporter.error(msg, line=self.lineno)]

        all_entries = [*capabilities, *workarounds]
        try:
            versions = resolve_versions(
                floor_minimum,
                all_entries,
                explicit=self.options.get("versions"),
            )
        except ValueError as exc:
            return [self.state_machine.reporter.error(str(exc), line=self.lineno)]

        columns = build_release_columns(
            versions,
            capabilities,
            workarounds,
            group_releases="group-releases" in self.options,
        )

        result: list[nodes.Node] = []
        seen_states: set[CellState] = set()

        if capabilities:
            result.append(
                _build_matrix_table(
                    capabilities,
                    columns,
                    row_header="Capability",
                    state_fn=capability_state,
                    seen_states=seen_states,
                ),
            )

        if workarounds:
            result.append(
                _build_matrix_table(
                    workarounds,
                    columns,
                    row_header="Workaround",
                    state_fn=workaround_state,
                    seen_states=seen_states,
                ),
            )

        if seen_states and "no-legend" not in self.options:
            result.append(_build_legend(seen_states))

        return result


def setup(app: Sphinx) -> ExtensionMetadata:
    """Register the ``tmux-capabilities`` directive and its stylesheet.

    Parameters
    ----------
    app : sphinx.application.Sphinx
        Active Sphinx application.

    Returns
    -------
    sphinx.util.typing.ExtensionMetadata
        Parallel-safe extension metadata.

    Examples
    --------
    >>> callable(setup)
    True
    """
    app.setup_extension("sphinx_ux_badges")
    app.add_config_value(
        "tmux_capabilities_manifest",
        default=None,
        rebuild="env",
        types=(dict,),
    )
    app.add_directive("tmux-capabilities", TmuxCapabilitiesDirective)

    static_dir = str(pathlib.Path(__file__).parent / "_static")

    def _add_static_path(sphinx_app: Sphinx) -> None:
        if static_dir not in sphinx_app.config.html_static_path:
            sphinx_app.config.html_static_path.append(static_dir)

    app.connect("builder-inited", _add_static_path)
    app.add_css_file("css/tmux_capabilities.css")

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
