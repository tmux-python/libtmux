"""Run the copy-pasteable how-to guides under ``docs/howto/`` as tests.

A how-to page holds nothing but reader-facing content: prose and plain
```` ```python ```` fences containing code a reader can paste into a file and
run. There are no ``>>>`` prompts, no ``assert`` statements, and no markers
addressed at the test suite.

Everything that makes such a page testable lives beside it, in a *sidecar*
module under :mod:`tests.docs.howto`. This plugin joins the two:

- it parses the page with MyST's own markdown parser and collects every
  backtick-fenced ``python`` block, in document order;
- it points tmux at a private, throwaway world, so a page's examples never
  reach the sockets of whoever is running the suite;
- it executes those blocks in one shared namespace, so block 2 sees the names
  block 1 bound — exactly what the reader gets pasting in sequence;
- it imports the page's sidecar and calls ``check_N(ctx)`` after block ``N``,
  bracketed by the sidecar's optional ``setup(ctx)`` and ``teardown(ctx)``.

Rot defence is the point of the contract. A page with no ``python`` fence, a
page with no sidecar, and a sidecar whose ``check_N`` functions do not
correspond one-to-one with the page's blocks all *fail*. They do not skip and
they do not silently pass. The companion :mod:`tests.docs.test_howto_harness`
closes the remaining holes by asserting that this plugin actually collected
the pages the run was pointed at, and that each page is reachable from the
section index.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import importlib
import importlib.util
import io
import os
import tempfile
import typing as t
from pathlib import Path

import pytest
from markdown_it.renderer import RendererHTML
from myst_parser.config.main import MdParserConfig
from myst_parser.parsers.mdit import create_md_parser

if t.TYPE_CHECKING:
    import types
    from collections.abc import Callable, Generator, Iterator, Sequence

    from markdown_it import MarkdownIt

# Sidecars use bare ``assert`` for their hidden checks; without this the
# failure output loses pytest's introspection because the modules are imported
# by name rather than collected as test files.
pytest.register_assert_rewrite("tests.docs.howto")

REPO_ROOT = Path(__file__).parents[2]
HOWTO_DIR = REPO_ROOT / "docs" / "howto"
DOCS_CONF = REPO_ROOT / "docs" / "conf.py"
SIDECAR_PACKAGE = "tests.docs.howto"


class HowtoContractError(Exception):
    """A how-to page and its sidecar do not satisfy the harness contract."""


@functools.cache
def _docs_myst_extensions() -> frozenset[str]:
    """Return the MyST extensions the documentation build enables.

    Read from ``docs/conf.py`` rather than restated here. Whether a run of
    backticks or colons becomes a fence is decided by the enabled extension
    set, so a parser configured from a copy of that set would drift the first
    time the site's changed and this file did not — and drift means a block
    that renders on the page but never runs.

    Returns
    -------
    frozenset of str
        Contents of the build's ``myst_enable_extensions``.
    """
    spec = importlib.util.spec_from_file_location("_libtmux_docs_conf", DOCS_CONF)
    if spec is None or spec.loader is None:  # pragma: no cover - unreachable
        msg = f"cannot load {DOCS_CONF}"
        raise HowtoContractError(msg)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return frozenset(getattr(module, "myst_enable_extensions", ()))


@functools.cache
def _md_parser() -> MarkdownIt:
    """Return a parser that tokenizes a page the way the docs build does.

    Returns
    -------
    markdown_it.MarkdownIt
        Parser configured from the build's extension set.
    """
    return create_md_parser(
        MdParserConfig(enable_extensions=set(_docs_myst_extensions())),
        RendererHTML,
    )


@dataclasses.dataclass(frozen=True)
class CodeBlock:
    """One backtick-fenced ``python`` block on a how-to page.

    Attributes
    ----------
    number : int
        1-based position of the block within the page.
    source : str
        Block body, verbatim, without the fence lines.
    first_line : int
        1-based line number of the block's first line of code in the
        markdown file. Used to make tracebacks point at the page.
    """

    number: int
    source: str
    first_line: int


def iter_pages() -> Iterator[Path]:
    """Yield every how-to page, in a stable order.

    Walks subdirectories: a page filed under ``docs/howto/advanced/`` is as
    much a how-to page as one at the top level, and a guard that stopped at
    the first level would leave a whole tree untested without saying so.

    Yields
    ------
    pathlib.Path
        Absolute path to a how-to page other than a section index.
    """
    for path in sorted(HOWTO_DIR.rglob("*.md")):
        if path.name != "index.md":
            yield path


def sidecar_name(page: Path) -> str:
    """Return the dotted module name of a page's sidecar.

    Parameters
    ----------
    page : pathlib.Path
        Path to a how-to markdown page.

    Returns
    -------
    str
        Importable module name, e.g. ``tests.docs.howto.check_if_tmux_is_running``.
    """
    parts = page.relative_to(HOWTO_DIR).with_suffix("").parts
    return ".".join((SIDECAR_PACKAGE, *(part.replace("-", "_") for part in parts)))


def parse_python_blocks(page: Path) -> list[CodeBlock]:
    """Extract the backtick-fenced ``python`` blocks from a page.

    Parameters
    ----------
    page : pathlib.Path
        Path to a how-to markdown page.

    Returns
    -------
    list of CodeBlock
        Blocks in document order.

    Raises
    ------
    HowtoContractError
        If the page carries a colon fence that is not a directive. Colon
        fences are the house style for directives, but ``:::python`` renders
        an ordinary, copy-pasteable code block that this harness would never
        execute — a block that looks tested and is not.
    """
    blocks: list[CodeBlock] = []
    for token in _md_parser().parse(page.read_text(encoding="utf-8")):
        if token.type != "fence":
            continue
        info = token.info.strip()
        if not token.markup.startswith("`"):
            if not info.startswith("{"):
                line = (token.map[0] if token.map is not None else 0) + 1
                msg = (
                    f"{page.name}:{line} opens a colon fence with info "
                    f"{info!r}. On a how-to page colon fences are for "
                    f"directives only — a code example must use a backtick "
                    f"fence so it runs."
                )
                raise HowtoContractError(msg)
            continue
        if info.split()[:1] != ["python"]:
            continue
        opening_line = token.map[0] if token.map is not None else 0
        blocks.append(
            CodeBlock(
                number=len(blocks) + 1,
                source=token.content,
                first_line=opening_line + 2,
            ),
        )
    return blocks


@dataclasses.dataclass
class HowtoContext:
    """What a sidecar is handed for setup, checks, and teardown.

    Attributes
    ----------
    page : pathlib.Path
        The markdown page being executed.
    blocks : Sequence[CodeBlock]
        Every ``python`` block on the page, in order.
    namespace : dict
        The shared namespace the page's blocks execute in. After block 2 has
        run it holds everything blocks 1 and 2 bound.
    output : dict of int to str
        Standard output captured per block number, so a check can assert on
        what the reader would have seen printed.
    monkeypatch : pytest.MonkeyPatch
        Undone when the page finishes.
    tmp_path : pathlib.Path
        Private scratch directory, removed when the page finishes.
    """

    page: Path
    blocks: Sequence[CodeBlock]
    namespace: dict[str, t.Any] = dataclasses.field(default_factory=dict)
    output: dict[int, str] = dataclasses.field(default_factory=dict)
    monkeypatch: pytest.MonkeyPatch = dataclasses.field(
        default_factory=pytest.MonkeyPatch,
    )
    tmp_path: Path = dataclasses.field(default_factory=Path)
    _cleanups: list[Callable[[], None]] = dataclasses.field(default_factory=list)

    def add_cleanup(self, fn: Callable[[], None]) -> None:
        """Register a callable to run when the page finishes.

        Cleanups run in reverse registration order, while the environment
        patches from :meth:`isolate_tmux` are still in effect.

        Parameters
        ----------
        fn : callable
            Zero-argument callable.
        """
        self._cleanups.append(fn)

    def run_block(
        self,
        number: int,
        namespace: dict[str, t.Any] | None = None,
    ) -> str:
        """Execute one of the page's blocks and return what it printed.

        Passing an explicit ``namespace`` runs the block in isolation instead
        of the page's shared namespace — a check uses that to exercise the
        other side of a branch the reader's single example only shows once.

        Parameters
        ----------
        number : int
            1-based block number.
        namespace : dict, optional
            Namespace to execute in. Defaults to the shared one.

        Returns
        -------
        str
            Anything the block wrote to standard output.
        """
        __tracebackhide__ = True
        block = self.blocks[number - 1]
        target = self.namespace if namespace is None else namespace
        # Pad with newlines so the compiled code's line numbers match the
        # markdown file: a traceback then points at the real page and line.
        padded = "\n" * (block.first_line - 1) + block.source
        code = compile(padded, str(self.page), "exec")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exec(code, target)  # noqa: S102
        return stdout.getvalue()

    def run_cleanups(self) -> None:
        """Run every registered cleanup, most recent first."""
        while self._cleanups:
            self._cleanups.pop()()


def _isolate_tmux(ctx: HowtoContext) -> None:
    """Point tmux at a private, throwaway world for one page.

    The runner calls this before the sidecar ever sees the context, which is
    the whole design: isolation a page has to remember to ask for is
    isolation a page will one day forget to ask for, and that failure mode
    reaches into whatever tmux the person running the suite has open.

    Socket isolation is governed by ``TMUX_TMPDIR``, so both a bare
    ``Server()`` and a ``Server(socket_name=...)`` in a visible block resolve
    under this page's scratch directory instead of the reader's real one.
    ``HOME`` moves too, so shell start-up files stay out of the way, and
    ``TMUX`` is cleared so libtmux does not believe it is running in a pane.

    The page's own code contains none of this — which is the residual gap: a
    reader pasting the same block hits their real sockets. Visible examples
    must therefore be non-destructive on their own.

    Parameters
    ----------
    ctx : HowtoContext
        The page's execution context.
    """
    tmux_tmpdir = ctx.tmp_path / "tmux"
    home = ctx.tmp_path / "home"
    tmux_tmpdir.mkdir(exist_ok=True)
    home.mkdir(exist_ok=True)
    # An empty HOME makes zsh open its first-run configuration wizard, which
    # takes over the pane and swallows send-keys input.
    (home / ".zshrc").touch()
    (home / ".bashrc").touch()

    ctx.monkeypatch.setenv("TMUX_TMPDIR", str(tmux_tmpdir))
    ctx.monkeypatch.setenv("HOME", str(home))
    ctx.monkeypatch.delenv("TMUX", raising=False)
    ctx.monkeypatch.delenv("TMUX_PANE", raising=False)

    ctx.add_cleanup(functools.partial(_kill_private_servers, tmux_tmpdir))


def _kill_private_servers(expected_tmpdir: Path) -> None:
    """Kill every tmux server whose socket lives under this page's tmpdir.

    Each server is addressed by its socket *path*, so a name a page invented
    is torn down as surely as the default one. The guard is the reason this
    is safe: it refuses to act unless the environment still points at the
    directory the page was given, and it only ever touches sockets found
    inside that directory. An untargeted kill would take out whatever tmux
    the person running the suite has open.

    Parameters
    ----------
    expected_tmpdir : pathlib.Path
        The private ``TMUX_TMPDIR`` this cleanup is allowed to act on.
    """
    if os.environ.get("TMUX_TMPDIR") != str(expected_tmpdir):
        return

    from libtmux.server import Server

    for socket in sorted(expected_tmpdir.glob("tmux-*/*")):
        if not socket.is_socket():
            continue
        server = Server(socket_path=str(socket))
        if server.is_alive():
            server.kill()


def _load_sidecar(page: Path) -> types.ModuleType:
    """Import a page's sidecar module.

    Parameters
    ----------
    page : pathlib.Path
        Path to a how-to markdown page.

    Returns
    -------
    types.ModuleType
        The imported sidecar.

    Raises
    ------
    HowtoContractError
        If no sidecar module exists for the page.
    """
    name = sidecar_name(page)
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        msg = (
            f"{page.name} has no sidecar: expected {name} "
            f"({REPO_ROOT / name.replace('.', '/')}.py). Every how-to page "
            f"must be paired with one."
        )
        raise HowtoContractError(msg) from exc


def _require_tmux_version(page: Path, sidecar: types.ModuleType) -> None:
    """Skip a page whose examples need a newer tmux than this one.

    A guide to a version-specific feature cannot run everywhere, and the
    honest answer on an older tmux is a reported skip rather than a failure
    the page was written to produce. The declaration lives on the sidecar
    because the page carries no test scaffolding: a reader copying the block
    should meet the feature, not a marker addressed at the suite.

    Parameters
    ----------
    page : pathlib.Path
        The how-to page about to run.
    sidecar : types.ModuleType
        Its sidecar, which may define ``MIN_TMUX_VERSION``.
    """
    minimum = getattr(sidecar, "MIN_TMUX_VERSION", None)
    if minimum is None:
        return

    from libtmux.common import get_version, has_gte_version

    if not has_gte_version(minimum):
        pytest.skip(
            f"{page.name} documents a tmux {minimum}+ feature; this tmux is "
            f"{get_version()}",
        )


def resolve_checks(
    sidecar: types.ModuleType,
    block_count: int,
) -> list[Callable[[HowtoContext], None]]:
    """Return a sidecar's per-block checks, verifying the contract.

    Parameters
    ----------
    sidecar : types.ModuleType
        The page's sidecar module.
    block_count : int
        Number of ``python`` blocks on the page.

    Returns
    -------
    list of callable
        ``check_1`` through ``check_<block_count>``.

    Raises
    ------
    HowtoContractError
        If a ``check_N`` is missing, or the sidecar defines checks for blocks
        the page no longer has.
    """
    checks: list[Callable[[HowtoContext], None]] = []
    for number in range(1, block_count + 1):
        check = getattr(sidecar, f"check_{number}", None)
        if not callable(check):
            msg = (
                f"{sidecar.__name__} must define check_{number}(ctx) for "
                f"block {number} of the page"
            )
            raise HowtoContractError(msg)
        checks.append(check)

    orphans = sorted(
        name
        for name in vars(sidecar)
        if name.startswith("check_")
        and name[len("check_") :].isdigit()
        and int(name[len("check_") :]) > block_count
    )
    if orphans:
        msg = (
            f"{sidecar.__name__} defines {', '.join(orphans)} but the page "
            f"only has {block_count} python block(s)"
        )
        raise HowtoContractError(msg)
    return checks


def run_page(page: Path, on_stage: Callable[[str], None] = lambda _stage: None) -> None:
    """Run one how-to page end to end, raising on the first failure.

    Separate from the pytest item so a test can drive a page directly — the
    mutation probe in :mod:`tests.docs.test_howto_mutations` runs a page under
    a deliberately broken libtmux and requires it to fail.

    Parameters
    ----------
    page : pathlib.Path
        The how-to page to run.
    on_stage : callable, optional
        Called with a description each time execution moves on, so a caller
        can report which block or check was running when something raised.

    Raises
    ------
    HowtoContractError
        If the page has no ``python`` block, or its sidecar does not satisfy
        the contract.
    """
    blocks = parse_python_blocks(page)
    if not blocks:
        msg = (
            f"{page.name} has no backtick-fenced ```python block. A how-to "
            f"page must carry at least one runnable example."
        )
        raise HowtoContractError(msg)

    sidecar = _load_sidecar(page)
    checks = resolve_checks(sidecar, len(blocks))
    setup = getattr(sidecar, "setup", None)
    teardown = getattr(sidecar, "teardown", None)

    # Resolved above rather than below, so a page documenting a newer tmux
    # still has its contract enforced on an older one. Only running the
    # examples is skipped; a missing sidecar or a stray check_N is a failure
    # at every tmux version.
    _require_tmux_version(page, sidecar)

    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        tempfile.TemporaryDirectory(prefix="libtmux-howto-") as tmp,
    ):
        ctx = HowtoContext(
            page=page,
            blocks=blocks,
            monkeypatch=monkeypatch,
            tmp_path=Path(tmp),
        )
        try:
            on_stage("isolating tmux")
            _isolate_tmux(ctx)
            if callable(setup):
                on_stage(f"{sidecar.__name__}.setup")
                setup(ctx)
            for block, check in zip(blocks, checks, strict=True):
                on_stage(f"{page.name}:{block.first_line} (block {block.number})")
                ctx.output[block.number] = ctx.run_block(block.number)
                on_stage(f"{sidecar.__name__}.check_{block.number}")
                check(ctx)
        finally:
            if callable(teardown):
                teardown(ctx)
            ctx.run_cleanups()


class HowtoPageItem(pytest.Item):
    """Execute one how-to page's blocks and run its sidecar's checks."""

    #: Which block or check is running, for the failure report.
    _stage: str | None = None

    def runtest(self) -> None:
        """Run the page end to end."""
        run_page(Path(self.path), self._record_stage)

    def _record_stage(self, stage: str) -> None:
        """Remember what is running, for :meth:`repr_failure`.

        Parameters
        ----------
        stage : str
            Description of the block or check about to run.
        """
        self._stage = stage

    def repr_failure(
        self,
        excinfo: pytest.ExceptionInfo[BaseException],
        style: t.Any = None,
    ) -> t.Any:
        """Report a failure, naming the block or check that raised.

        Parameters
        ----------
        excinfo : pytest.ExceptionInfo
            The captured exception.
        style : str, optional
            Traceback style pytest asked for.

        Returns
        -------
        object
            pytest's own representation, with a section naming the stage.
        """
        # When the page's own code raised, start the report at the markdown
        # frame so a maintainer reads the offending line first instead of
        # pytest's and this plugin's call chain.
        page = str(self.path)
        if any(str(entry.path) == page for entry in excinfo.traceback):
            excinfo.traceback = excinfo.traceback.cut(path=page)
        report = self._repr_failure_py(excinfo, style=style)
        if self._stage is not None and hasattr(report, "addsection"):
            report.addsection("how-to stage", self._stage)
        return report

    def reportinfo(self) -> tuple[Path, int, str]:
        """Return where this item lives, for the test report.

        Returns
        -------
        tuple
            Page path, line offset, and a human-readable description.
        """
        return Path(self.path), 0, f"how-to: {Path(self.path).name}"


class HowtoPage(pytest.File):
    """Collector for a single ``docs/howto/*.md`` page."""

    def collect(self) -> Iterator[HowtoPageItem]:
        """Yield the page's single item.

        The whole page is one test on purpose. Blocks share a namespace, so
        splitting them into separate items would break under ``--reruns`` and
        under ``pytest-xdist``, both of which are configured here.

        Yields
        ------
        HowtoPageItem
            The item that runs every block on the page.
        """
        yield HowtoPageItem.from_parent(self, name="howto")


def is_howto_page(path: Path) -> bool:
    """Return whether a path is a how-to page this plugin owns.

    Parameters
    ----------
    path : pathlib.Path
        Candidate path.

    Returns
    -------
    bool
        True for a markdown page anywhere under ``docs/howto/`` that is not a
        section index.
    """
    return (
        path.suffix == ".md" and path.name != "index.md" and HOWTO_DIR in path.parents
    )


@pytest.hookimpl(wrapper=True)
def pytest_collect_file(
    file_path: Path,
    parent: pytest.Collector,
) -> Generator[None, t.Any, t.Any]:
    """Claim how-to pages, and only how-to pages.

    ``pytest_collect_file`` aggregates every plugin's answer, so gp-libs'
    doctest collector would otherwise return a second collector for the same
    file. Replacing the aggregate result keeps a how-to page to exactly one
    collector while leaving every other page in ``docs/`` untouched.

    Parameters
    ----------
    file_path : pathlib.Path
        The file being considered.
    parent : pytest.Collector
        The parent collector.

    Yields
    ------
    None
        Control, so the wrapped hook implementations run.

    Returns
    -------
    object
        The collectors for this path.
    """
    collectors = yield
    if is_howto_page(file_path):
        return [HowtoPage.from_parent(parent, path=file_path)]
    return collectors
