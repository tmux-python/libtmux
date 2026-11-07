r"""Fail when code a reader sees in rendered documentation is too wide.

Shared by every libtmux port; change it in all of them together. It
enforces the example rules in WRITING.md. Configuration lives in
``.github/example-width.toml``::

    width = 80
    tab_width = 4
    markdown = ["**/*.md"]
    sources = ["examples/**/*.rs"]
    doc_comments = ["src/**/*.rs"]
    shared_digest = "<sha256 printed by --digest>"
    checker_digest = "<sha256 printed by --digest>"
    allow_ceiling = 1

    [[exclude]]
    glob = "docs/decisions/**"
    reason = "dated decision records, not reader-facing examples"

    [[formatter_copies]]
    copy = "examples/rustfmt.toml"
    root = "rustfmt.toml"
    key = "max_width"

    [[allow]]
    path = "README.md"
    line = "the exact line, as it appears in the file"
    reason = "why breaking it would make the example worse"

It checks code in ``markdown`` files (fences, indented blocks, including
one four columns past a list item's text, and ``<pre>`` blocks; literal
and ``code-block`` blocks in a ``.rst`` one), every line of ``sources``
files, and the code inside doc comments of ``doc_comments`` files:
fences, read as a Markdown page reads them, ``>>>`` doctests, and reST
literal blocks in Python docstrings. Output is not checked: fences
tagged ``text``, and the lines a session prints (a ``console``,
``shell-session`` or ``pycon`` block, or a ``python`` fence that opens
with ``>>> ``). A command runs on through an open quote, heredoc, loop,
conditional or brace block and past a trailing ``\``, backtick, pipe,
``&&`` or ``||``; a ``$ `` command must continue with ``\`` and a
``PS> `` command with a backtick. An untagged Markdown fence is code,
and a ``text`` fence that opens with a ``$ `` or ``PS> `` prompt is a
console session. A line that is only a URL (after an optional comment, list or
quote marker) and a hidden line (a rustdoc ``# `` line, a doctest marked
``# doctest: +HIDE``) are skipped. Wide characters count as two columns;
a tab advances to the next multiple of 4.

``width`` must be 80, the shared rule, and ``tab_width``, if set, 4.
Every key must be known, at the top level and inside each ``[[...]]``
entry, so a key written below a table header cannot be swallowed by that
entry; every entry must hold
the keys the check reads, and every value must have the type it reads.
Every glob must match a tracked file, and every exclusion a checked file
or a file under ``examples``;
every exclusion and allow entry must give a reason, and every allow
entry must match a line. Every tracked file under a directory named
``examples`` must be checked or excluded, so a new example file cannot
go unread. ``allow_ceiling`` must equal the number of allow entries, so
the list grows only through a reviewed change to that number and a fixed
line must lower it. Each formatter copy must equal its root file once
its ``key`` value is set aside, and the digests of this checker and of
WRITING.md's shared section must equal ``checker_digest`` and
``shared_digest``, both required, so a local edit to either fails until
every port changes together. A WRITING.md without both shared markers is
reported by name. AGENTS.md must hold a Markdown link that resolves to
this WRITING.md and the heading the shared section sits under, so an
agent is routed to the rules, and WRITING.md's
``### In this repository`` block must hold the four labelled bullets in
order, then one Bad and one Good example, with the Bad example still
past 80 columns.

Run ``--self-test`` to prove the checker can fail. ``--digest`` prints the
SHA-256 of this file and of WRITING.md's shared example section (between
``<!-- shared:examples -->`` and ``<!-- /shared:examples -->``), so a job
that reads every port can confirm they still agree.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import typing as t
import unicodedata

try:
    import tomllib
except ModuleNotFoundError:  # tomllib is in the standard library from 3.11.
    sys.exit("check_example_width.py needs Python 3.11 or newer")

CONFIG = pathlib.PurePosixPath(".github/example-width.toml")
KEYS = frozenset(
    {
        "width",
        "tab_width",
        "markdown",
        "sources",
        "doc_comments",
        "exclude",
        "allow",
        "allow_ceiling",
        "formatter_copies",
        "shared_digest",
        "checker_digest",
    }
)
# Keys each [[table]] entry holds.
TABLE_KEYS = {
    "exclude": frozenset({"glob", "reason"}),
    "allow": frozenset({"path", "line", "reason"}),
    "formatter_copies": frozenset({"copy", "root", "key"}),
}
GLOB_KEYS = ("markdown", "sources", "doc_comments")
# The reason the printed allow entry carries until someone writes a real one.
PLACEHOLDER = "why breaking this line would make the example worse"
# The type each top-level value must have; a TOML string where a list belongs
# would otherwise be read one character at a time.
VALUE_TYPES: dict[str, tuple[type, str]] = {
    "width": (int, "an integer"),
    "tab_width": (int, "an integer"),
    "allow_ceiling": (int, "an integer"),
    "shared_digest": (str, "a string"),
    "checker_digest": (str, "a string"),
}
CODE_DIRECTIVES = frozenset({"code-block", "code", "code-cell", "sourcecode"})
# gp-libs hides a doctest line carrying this directive from the rendered page.
HIDDEN = re.compile(r"^\s*(?:>>>|\.\.\.) .*# doctest: \+HIDE\b")
OUTPUT_TAGS = frozenset({"text"})
# Fences that mix prompted commands with the output they print.
SESSION_TAGS = frozenset({"console", "shell-session", "pycon"})
# Fences of shell script, with no prompts and no output.
SCRIPT_TAGS = frozenset({"sh", "bash", "zsh", "shell", "powershell", "pwsh", "ps1"})
# A Python fence that opens with a doctest prompt is a session too.
PYTHON_TAGS = frozenset({"python", "py", "python3"})
PROMPTS = ("$ ", "PS> ", ">>> ", "... ")
# Shell words that open and close a block a command continues through.
SHELL_OPEN = frozenset({"if", "for", "while", "until", "case", "select"})
SHELL_CLOSE = frozenset({"fi", "done", "esac"})
HEREDOC = re.compile(r"(?<!<)<<-?[ \t]*(['\"]?)(?P<word>[A-Za-z_]\w*)\1")
# A reST line that opens an indented code block: a paragraph ending in
# ``::`` or a code directive. Other directives, such as toctree, hold no code.
REST_BLOCK = re.compile(
    r"^\s*(?!\.\. )\S.*::\s*$|^\s*\.\. (code-block|code|sourcecode)::"
)
FENCE = re.compile(r"^(?P<indent>\s*)(?P<mark>`{3,}|~{3,})\s*(?P<info>[^`]*)$")
RUSTDOC_TAGS = frozenset({"rust", "no_run", "ignore", "should_panic", "compile_fail"})
SHARED = re.compile(
    r"<!-- shared:examples -->\n(?P<body>.*?)<!-- /shared:examples -->", re.DOTALL
)
DOC_LINE = re.compile(r"^\s*(?:///|//!|\*(?!/)|#'|--- ?)\s?")
# Files under examples/ with no text lines to measure.
BINARY = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".zip",
    ".gz",
    ".tar",
    ".wasm",
    ".so",
    ".dll",
    ".exe",
    ".jar",
    ".class",
    ".bin",
    ".dylib",
    ".a",
    ".o",
    ".db",
    ".sqlite",
)
# Comments a test compares or a copy step reads: Go's `// Output:` and
# `// docs:` lines, java's `// →` results, and region markers.
MARKER = re.compile(
    r"(?:Output:|Unordered output:|docs:|→|#?(?:end)?region\b)", re.IGNORECASE
)
# Shell and PowerShell scripts, whose lines continue the way a console command does.
SCRIPTS = (".sh", ".bash", ".zsh", ".ps1", ".psm1")
# Go marks doc-comment code with a tab after a bare //.
GO_DOC = re.compile(r"^\s*//\t")
DOCTEST = re.compile(r"(?:>>>|\.\.\.) ")
BLOCK_OPEN = re.compile(r"<pre>\s*\{@code|<code>\s*$")
BLOCK_CLOSE = re.compile(r"\}\s*</pre>|^\s*</code>")
URL = re.compile(r"^(?:(?:#+|//+!?|-+|\*|>|<!--)\s*)?<?[a-z][a-z0-9+.-]*://\S+$")
EXAMPLE_DIR = re.compile(r"(^|/)examples/", re.IGNORECASE)
HEADING = re.compile(r"^(#{1,6}) (.+)$", re.MULTILINE)
# A Markdown link target: [text](target).
LINK = re.compile(
    r"""(?<![!\\])\[[^\[\]]*\]\(<?([^)\s>]+)>?(?:\s+(?:"[^"]*"|'[^']*'))?\)"""
    r"""|^\s*\[[^\]]+\]:\s*<?([^\s>]+)>?""",
    re.MULTILINE,
)
PORT_BLOCK = re.compile(
    r"^### In this repository\n(?P<body>.*?)(?=^#{1,3} |\Z)", re.MULTILINE | re.DOTALL
)
PORT_LABELS = (
    "- **Hard limit:**",
    "- **Not formatted:**",
    "- **Runs, compiles, exempt:**",
    "- **Compared output and copied blocks:**",
)
# Where every port lists its copy, so a digest change reaches all of them.
PORTS = "PORTS in libtmux/docs scripts/check_shared_examples.py"


def fence_tag(info: str) -> str:
    """Return a fence's language, reading past a MyST ``{directive}``.

    >>> fence_tag("rust,no_run")
    'rust'
    >>> fence_tag("{code-block} python")
    'python'
    >>> [fence_tag(f"{{{d}}} sh") for d in ("code", "code-cell", "sourcecode")]
    ['sh', 'sh', 'sh']
    >>> fence_tag("{note}")
    'text'
    >>> fence_tag("")
    ''
    """
    words = info.strip().lower().split()
    if words and words[0].startswith("{"):
        if words[0].strip("{}") not in CODE_DIRECTIVES:
            return "text"
        words = words[1:]
    return words[0].split(",")[0] if words else ""


@dataclasses.dataclass(frozen=True)
class Finding:
    """One line wider than the configured width."""

    path: str
    number: int
    columns: int
    width: int
    # The line as an allow entry must quote it.
    text: str = ""
    # Where the line sits, which decides the fix: "command" (a console
    # command), "note" (a comment above one), "promptless" (a console fence
    # with no prompt), "doc" (code in a doc comment), "source" (an example
    # program), or "" (other code in Markdown).
    kind: str = ""

    def __str__(self) -> str:
        """Render as ``path:line: width > limit``.

        >>> print(Finding("README.md", 3, 90, 80))
        README.md:3: 90 columns > 80
        """
        return f"{self.path}:{self.number}: {self.columns} columns > {self.width}"


def columns(text: str) -> int:
    """Return the columns a line occupies; wide characters take two.

    >>> columns("abc")
    3
    >>> columns("日本")
    4
    """
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def is_url(text: str) -> bool:
    """Return whether a line is one URL, which cannot be broken.

    >>> is_url("    https://example.com/" + "x" * 90)
    True
    >>> is_url("// <https://example.com/a>")
    True
    >>> is_url('let body=reqwest::get("https://example.com/").await?;')
    False
    >>> is_url("server.sessions().stream().filter(s->s.isAttached()).toList()")
    False
    """
    return bool(URL.match(text.strip()))


class Shell(t.NamedTuple):
    """What a shell command still holds open at the end of a line."""

    dialect: str = "$ "
    quote: str | None = None
    heredoc: str | None = None
    depth: int = 0


def other_continuation(code: str, dialect: str) -> bool:
    r"""Return whether a line ends with the other shell's continuation.

    A ``$ `` line ending in an unpaired backtick, or a ``PS> `` line ending
    in a ``\`` after a space, continues the way the other shell would.

    >>> other_continuation("$ ls `", "$ "), other_continuation("$ echo `date`", "$ ")
    (True, False)
    >>> ps = "PS> "
    >>> other_continuation("PS> dir \\", ps), other_continuation("PS> cd C:\\", ps)
    (True, False)
    """
    if dialect == "$ ":
        return code.endswith("`") and code.count("`") % 2 == 1
    return code.endswith(" \\")


def scan(text: str, state: Shell) -> tuple[str | None, str, bool, int]:
    r"""Return a line's open quote, unquoted text, trailing escape and comment.

    A backslash (a backtick in PowerShell) escapes the next character
    outside single quotes, and an unquoted # starts a comment, so the last
    value is where the code ends:

    >>> scan('echo "a # b" `', Shell()), scan("ls  # see `ls`", Shell())
    ((None, 'echo  `', False, 14), (None, 'ls  ', False, 4))
    >>> scan("'it", Shell()), scan("dir `", Shell("PS> "))
    (("'", '', False, 3), (None, 'dir ', True, 5))
    """
    escape = "\\" if state.dialect == "$ " else "`"
    quote, plain, escaped, cut = state.quote, [], False, len(text)
    for index, char in enumerate(text):
        if escaped:
            escaped = False
            if quote is None:
                plain.append(char)
        elif char == escape and quote != "'":
            escaped = True
        elif (
            quote is None and char == "#" and (index == 0 or text[index - 1].isspace())
        ):
            cut = index
            break
        elif quote is None and char in "'\"":
            quote = char
        elif char == quote:
            quote = None
        elif quote is None:
            plain.append(char)
    return quote, "".join(plain), escaped, cut


def shell_after(line: str, state: Shell, following: str | None = None) -> Shell | None:
    r"""Return what the command holds open after a line, or None if it ended.

    A command goes on past an open quote, an open heredoc, a ``\`` or
    backtick, a trailing pipe, ``&&`` or ``||``, and an unclosed loop,
    conditional or brace block:

    >>> def after(lines: list[str]) -> Shell | None:
    ...     state = None
    ...     for line in lines:
    ...         state = shell_after(line, state or Shell())
    ...     return state
    >>> after(["$ julia -e 'using Pkg"]).quote
    "'"
    >>> after(["$ julia -e 'using Pkg", "Pkg.add(1)'"]) is None
    True
    >>> after(["$ for pane in a b; do", "  echo $pane"]).depth
    1
    >>> after(["$ for pane in a b; do", "  echo $pane", "done"]) is None
    True
    >>> opens = ["if x; then", "while x; do", "until x; do", "case x in"]
    >>> opens.append("select x in a; do")
    >>> [after([f"$ {line}", "  y"]).depth for line in opens]
    [1, 1, 1, 1, 1]
    >>> [after(["$ if x; then", "  y", "fi"]), after(["$ case x in", "esac"])]
    [None, None]
    >>> after(["$ make &&"]) is None, after(["$ echo $("]) is None
    (False, False)
    >>> after(["$ cat <<EOF", "... a line"]).heredoc
    'EOF'
    >>> after(["$ cat <<-EOF", "\tbody"]).heredoc, after(["$ cat <<-EOF", "\tEOF"])
    ('EOF', None)
    >>> after(["$ git commit -F - <<'EOF'", 'say "hi'])
    Shell(dialect='$ ', quote=None, heredoc='EOF', depth=0)
    >>> after(["$ git commit -F - <<'EOF'", 'say "hi', "EOF"]) is None
    True
    >>> after(["PS> if ($x) {", "  Get-Item"]).depth
    1
    >>> after(["PS> if ($x) {", "  Get-Item", "}"]) is None
    True
    >>> after(['$ echo "a b" | tr a b']) is None
    True
    >>> after(["$ ls  # a comment ending in {"]) is None
    True
    >>> after(["$ ls  # don't"]) is None, after([r"$ echo it\'s"]) is None
    (True, True)
    >>> after(["$ ls |"]) is None, after(["$ ls |", "  grep x"]) is None
    (False, True)
    >>> after(["$ ls `"]) is None, after(["PS> Get-Item \\"]) is None
    (False, False)
    >>> after(["$ ls \\"]) is None, after(["PS> Get-Item `"]) is None
    (False, False)

    A ``<<`` inside quotes or arithmetic opens no heredoc, and a ``\`` after
    ``PS> `` names a path unless an indented line follows it:

    >>> after(['$ echo "type <<EOF to start"']), after(["$ echo $((x<<y))"])
    (None, None)
    >>> shell_after("PS> Get-ChildItem \\", Shell("PS> "), "")
    >>> shell_after("PS> Get-ChildItem \\", Shell("PS> "), "    -Force").dialect
    'PS> '
    >>> shell_after("PS> Get-ChildItem \\", Shell("PS> "), "    ") is None
    True
    """
    text = line.lstrip()
    # A prompt-like line inside a heredoc, quote or block is that command's text.
    held = state.heredoc or state.quote or state.depth
    if text.startswith((">>> ", "... ")) and not held:
        return None
    if state.heredoc is not None:
        if line.strip() == state.heredoc:
            state = state._replace(heredoc=None)
            return state if state.quote or state.depth else None
        return state
    for prompt in ("$ ", "PS> "):
        if text.startswith(prompt):
            state, text = Shell(dialect=prompt), text[len(prompt) :]
    quote, bare, escaped, cut = scan(text, state)
    depth = state.depth
    for segment in re.split(r"[;&|()]", bare):
        words = segment.split()
        if state.dialect == "$ " and words and words[0] in SHELL_OPEN:
            depth += 1
        if state.dialect == "$ " and words and words[0] in SHELL_CLOSE:
            depth -= 1
        depth += sum(w.endswith("{") for w in words)
        depth -= sum(w.startswith("}") for w in words)
    arithmetic = re.sub(r"\(\(.*?\)\)", lambda m: " " * len(m[0]), text[:cut])
    opened = [
        m["word"]
        for m in HEREDOC.finditer(arithmetic)
        if scan(text[: m.start()], state)[0] is None
    ]
    heredoc = opened[0] if opened else None
    state = Shell(state.dialect, quote, heredoc, max(depth, 0))
    # A trailing \ or backtick continues the command under either prompt, so
    # a line continued the other shell's way is still measured.
    tail = text[:cut].rstrip()
    other = other_continuation(tail, state.dialect)
    if other and state.dialect == "PS> " and following is not None:
        other = following[:1].isspace() and bool(following.strip())
    ends = escaped or other
    ends = ends or bare.rstrip().endswith(("|", "&&", "("))
    return state if quote or state.heredoc or state.depth or ends else None


LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")


def indent_code(line: str) -> bool:
    """Return whether a Markdown line is indented far enough to be code."""
    return line.startswith(("    ", "\t"))


def depth(line: str) -> int:
    """Return the column a Markdown line's text starts at, tabs stopping at 4."""
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip())


def has_prompt(lines: list[str], mark: str) -> bool:
    """Return whether a session fence holds a prompt before it closes.

    >>> has_prompt(["$ ls", "```"], "```"), has_prompt(["ls", "```", "$ x"], "```")
    (True, False)
    """
    for line in lines:
        match = FENCE.match(line)
        if match and match["mark"].startswith(mark) and not match["info"].strip():
            return False
        if line.lstrip().startswith(PROMPTS):
            return True
    return False


def comments_a_command(lines: list[str], mark: str) -> bool:
    """Return whether ``# `` lines lead to a prompt before the fence closes.

    A comment above a console command is code a reader copies; a ``# `` line
    among a command's output is output.

    >>> comments_a_command(["# and", "$ ls", "```"], "```")
    True
    >>> comments_a_command(["more output", "```"], "```"), comments_a_command([], "`")
    (False, False)
    """
    for line in lines:
        match = FENCE.match(line)
        if match and match["mark"].startswith(mark) and not match["info"].strip():
            return False
        stripped = line.lstrip()
        if not stripped.startswith("# "):
            return stripped.startswith(PROMPTS)
    return False


def doctest_first(lines: list[str], mark: str) -> bool:
    """Return whether a fence's first code line is a ``>>>`` doctest prompt.

    >>> doctest_first(["", ">>> 1 + 1", "2", "```"], "```")
    True
    >>> doctest_first(["x = 1", ">>> x", "```"], "```")
    False
    """
    for line in lines:
        match = FENCE.match(line)
        if match and match["mark"].startswith(mark) and not match["info"].strip():
            return False
        if line.strip():
            return line.lstrip().startswith(">>> ")
    return False


def selected(config: dict[str, t.Any], path: str) -> bool:
    """Return whether a glob key of the config selects a path.

    >>> selected({"sources": ["examples/*.rs"]}, "examples/a.rs")
    True
    >>> selected({"sources": ["examples/*.rs"]}, "examples/a.toml")
    False
    """
    return matches(path, [g for key in GLOB_KEYS for g in config.get(key, [])])


def untracked_matches(config: dict[str, t.Any], untracked: list[str]) -> list[str]:
    """Return untracked files the check would read once git tracks them.

    >>> untracked_matches({"markdown": ["*.md"]}, ["new.md", "build.log"])
    ['new.md']
    >>> excluded = {"exclude": [{"glob": "examples/x/**", "reason": "r"}]}
    >>> untracked_matches(excluded, ["examples/new.rs", "examples/x/y.rs"])
    ['examples/new.rs']
    """
    read = [g for key in GLOB_KEYS for g in config.get(key, [])]
    skip = [entry["glob"] for entry in entries(config, "exclude")]
    return [
        path
        for path in untracked
        if (matches(path, read) or EXAMPLE_DIR.search(path)) and not matches(path, skip)
    ]


def markdown_lines(
    text: str, indented: bool = True, kinds: dict[int, str] | None = None
) -> list[tuple[int, str]]:
    r"""Return the code lines of the fences a reader runs or copies.

    Output fences are skipped, and so are the lines a ``console`` block
    prints after its ``$`` commands. An untagged fence counts as code.

    >>> doc = "\n".join([
    ...     "```rust", "let a = 1;", "```",
    ...     "```text", "output", "```",
    ...     "```", "untagged();", "```",
    ...     "```console", "$ cargo test \\", "    --doc", "ok", "```",
    ... ])
    >>> [line for _, line in markdown_lines(doc)]
    ['let a = 1;', 'untagged();', '$ cargo test \\', '    --doc']
    >>> rust = "```rust\n# let hidden = 1;\nlet shown = 2;\n```"
    >>> [line for _, line in markdown_lines(rust)]
    ['let shown = 2;']
    >>> session = "```{}\n$ ls\nout\n```"
    >>> [markdown_lines(session.format(t)) for t in ("console", "shell-session")]
    [[(2, '$ ls')], [(2, '$ ls')]]
    >>> doctest = "```{}\n>>> for x in y:\n...     f(x)\nout\n```"
    >>> [len(markdown_lines(doctest.format(t))) for t in ("pycon", "py", "python3")]
    [2, 2, 2]
    >>> hidden = "```{}\n# hidden()\nshown()\n```"
    >>> tags = ("no_run", "ignore", "should_panic", "compile_fail")
    >>> [markdown_lines(hidden.format(t)) for t in tags]
    [[(3, 'shown()')], [(3, 'shown()')], [(3, 'shown()')], [(3, 'shown()')]]
    >>> markdown_lines("~~~text\nout\n~~~\n~~~sh\nls\n~~~")
    [(5, 'ls')]
    >>> myst = "```{code-block} text\nplain output\n```"
    >>> markdown_lines(myst)
    []
    >>> ps = "```console\nPS> Get-Item `\n    -Path x\nok\n```"
    >>> [line for _, line in markdown_lines(ps)]
    ['PS> Get-Item `', '    -Path x']
    >>> quoted = "```console\n$ julia -e '\n    using Pkg'\nok\n```"
    >>> [line for _, line in markdown_lines(quoted)]
    ["$ julia -e '", "    using Pkg'"]
    >>> listing = "```console\nPS> Get-ChildItem \\\n\n    Directory: C:\\\n```"
    >>> [line for _, line in markdown_lines(listing)]
    ['PS> Get-ChildItem \\']
    >>> noted = "```console\n# Install the tool\n$ ls\n# not a note\n```"
    >>> [line for _, line in markdown_lines(noted)]
    ['# Install the tool', '$ ls']
    >>> kinds: dict[int, str] = {}
    >>> build = "```console\n# Build\n$ cmake \\\n    -DX=1\nok\n```"
    >>> _ = markdown_lines(build, True, kinds)
    >>> kinds
    {2: 'note', 3: 'command', 4: 'command'}
    >>> data: dict[int, str] = {}
    >>> heredoc = "```console\n$ cat <<EOF\nbody\nEOF\n>>> x\n```"
    >>> _ = markdown_lines(heredoc, True, data)
    >>> [n for n, kind in data.items() if kind == "command"], data[3]
    ([2], 'session')
    >>> bare: dict[int, str] = {}
    >>> _ = markdown_lines("```console\ncargo test\n```", True, bare)
    >>> bare
    {2: 'promptless'}
    >>> script: dict[int, str] = {}
    >>> _ = markdown_lines("```bash\nmake all\n```", True, script)
    >>> script
    {2: 'script'}

    A ``console`` block with no prompt line holds no output to skip, so it is
    measured as code:

    >>> bare = "```console\ncargo test --doc\n```"
    >>> [line for _, line in markdown_lines(bare)]
    ['cargo test --doc']
    >>> pydoc = "```python\n>>> pane.capture()\n['output line']\n```"
    >>> [line for _, line in markdown_lines(pydoc)]
    ['>>> pane.capture()']

    A ``text`` fence that opens with a prompt is a console session, and an
    indented code block or a ``<pre>`` block outside a list is code:

    >>> prompted = "```text\n$ ls -l\ntotal 0\n```"
    >>> [line for _, line in markdown_lines(prompted)]
    ['$ ls -l']
    >>> markdown_lines("## Setup\n    make\nText\n    more text")
    [(2, '    make')]
    >>> markdown_lines("Text\n```sh\nls\n```\n    make")
    [(3, 'ls'), (5, '    make')]
    >>> page = "Before:\n\n    new Server()\n\n- item\n\n    more of the item"
    >>> [line for _, line in markdown_lines(page)]
    ['    new Server()']
    >>> [line for _, line in markdown_lines("1. item\n\n       code()\n   text")]
    ['       code()']
    >>> [line for _, line in markdown_lines("<pre><code>run()\n</code></pre>")]
    ['<pre><code>run()', '</code></pre>']
    """
    found: list[tuple[int, str]] = []
    fence: tuple[str, str] | None = None
    first = promptless = False
    shell: Shell | None = None
    blank, in_list, in_block, in_pre = True, False, False, False
    content = 0
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        match = FENCE.match(line)
        if fence is None and match:
            fence = (match["mark"], fence_tag(match["info"]))
            if fence[1] in PYTHON_TAGS and doctest_first(lines[number:], fence[0]):
                fence = (fence[0], "pycon")
            promptless = fence[1] in SESSION_TAGS
            if promptless and not has_prompt(lines[number:], fence[0]):
                fence = (fence[0], "sh")
            promptless = promptless and fence[1] == "sh"
            first, shell, in_block = True, None, False
            continue
        if fence is None:
            if not indented:
                continue
            stripped = line.strip()
            if in_pre or stripped.startswith("<pre"):
                found.append((number, line))
                in_pre = "</pre>" not in line
            elif not stripped:
                blank = True
                continue
            elif item := LIST_ITEM.match(line):
                in_list, in_block = True, False
                # Content starts after the marker and up to four spaces; more
                # than that and the extra spaces open an indented block.
                gap = len(line) - item.end() - len(line[item.end() :].lstrip(" "))
                content = item.end() + (gap if gap < 4 else 0)
            elif indent_code(line) and not in_list and (blank or in_block):
                found.append((number, line))
                in_block = True
            elif in_list and (blank or in_block) and depth(line) >= content + 4:
                # Four columns past a list item's content is code in the item.
                found.append((number, line))
                in_block = True
            else:
                in_list = in_list and line.startswith((" ", "\t"))
                in_block = False
            # Only a paragraph keeps an indented line from starting code.
            blank = bool(HEADING.match(line))
            continue
        if match and match["mark"].startswith(fence[0]) and not match["info"].strip():
            fence, blank = None, True
            continue
        if first and line.strip():
            first = False
            if fence[1] in OUTPUT_TAGS and line.lstrip().startswith(("$ ", "PS> ")):
                fence = (fence[0], "console")
        tag = fence[1]
        if tag in OUTPUT_TAGS:
            continue
        if tag in RUSTDOC_TAGS and (
            line.strip() == "#" or line.lstrip().startswith("# ")
        ):
            continue
        kind = "promptless" if promptless else "script" if tag in SCRIPT_TAGS else ""
        if tag in SESSION_TAGS:
            prompt = line.lstrip().startswith(PROMPTS)
            note = not (prompt or shell) and line.lstrip().startswith("# ")
            note = note and comments_a_command(lines[number:], fence[0])
            if not (prompt or shell or note):
                continue
            kind = "note" if note else ""
            if not note:
                # A line inside a quote or heredoc is data, which a shell
                # continuation would change.
                level = line.lstrip().startswith(("$ ", "PS> ")) or bool(
                    shell and not (shell.quote or shell.heredoc)
                )
                following = lines[number] if number < len(lines) else ""
                shell = shell_after(line, shell or Shell(), following)
                kind = "command" if level else "session"
        if kinds is not None and kind:
            kinds[number] = kind
        found.append((number, line))
    return found


def prompt_mismatches(text: str) -> list[tuple[int, str]]:
    r"""Return lines that continue a command the other shell's way.

    A ``$ `` command continues with ``\``, a ``PS> `` one with a backtick.

    >>> prompt_mismatches("```console\n$ ls `\n  -l\nPS> dir \\\n  -x\n```")
    [(2, '$ '), (4, 'PS> ')]
    >>> prompt_mismatches("```console\n$ ls \\\n  -l\nPS> dir `\n  -x\n```")
    []
    >>> prompt_mismatches("```console\n$ ls\n```\n```go\nName string `json`\n```")
    []
    >>> prompt_mismatches("```console\n$ echo `date`\n$ ls  # see `ls`\n```")
    []
    >>> prompt_mismatches("```console\n$ ls `\n  -l `\n  -a\n```")
    [(2, '$ ')]

    Only a line the command goes on to is a continuation, so a ``\`` that
    names a path, or a ``#`` inside quotes, is read as code:

    >>> prompt_mismatches("```console\nPS> cd \\\nPS> dir\n```")
    []
    >>> prompt_mismatches("```console\n$ echo '# a' `\n  -n\n```")
    [(2, '$ ')]
    >>> prompt_mismatches("```console\n$ echo 'a `\n  b'\n```")
    []
    >>> prompt_mismatches("```console\nPS> Get-ChildItem \\\nName\n```")
    []
    >>> blank = "```console\nPS> Get-ChildItem \\\n\n    Directory: C:\\\n```"
    >>> prompt_mismatches(blank), prompt_mismatches(blank.replace("\n\n", "\n"))
    ([], [(2, 'PS> ')])
    """
    found: list[tuple[int, str]] = []
    state: Shell | None = None
    pending: tuple[int, str] | None = None
    last = first = 0
    for number, line in markdown_lines(text):
        stripped = line.lstrip()
        prompt = stripped.startswith(("$ ", "PS> "))
        if pending and number == last + 1 and not prompt and pending not in found:
            found.append(pending)
        pending = None
        if prompt:
            state = Shell(dialect=stripped[: stripped.index(" ") + 1])
            first = number
        elif state is None or number != last + 1:
            state = None
            continue
        dialect, last = state.dialect, number
        quote, _, _, cut = scan(line, state)
        if quote is None and other_continuation(line[:cut].rstrip(), dialect):
            pending = (first, dialect)
        state = shell_after(line, state)
    return found


def prompt_problems(
    root: pathlib.Path, config: dict[str, t.Any], files: list[str]
) -> list[str]:
    """Return console commands in Markdown and doc comments continued wrongly."""
    skip = [entry["glob"] for entry in entries(config, "exclude")]
    fix = {
        "$ ": "this `$ ` command is continued with a backtick; end the line with "
        "`\\` instead, or use a `PS> ` prompt for a PowerShell command",
        "PS> ": "this `PS> ` command is continued with `\\`; end the line with a "
        "backtick instead, or, if `\\` ends a path, keep the blank line PowerShell "
        "prints between the command and its output",
    }
    problems = []
    for path in files:
        markdown = matches(path, config.get("markdown", []))
        doc = not markdown and matches(path, config.get("doc_comments", []))
        if not (markdown or doc) or matches(path, skip) or path.endswith(".rst"):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found: list[tuple[int, str]] = []
        if doc:
            doc_comment_lines(text, pathlib.PurePath(path).suffix, prompts=found)
        else:
            found = prompt_mismatches(text)
        problems += [f"{path}:{n}: {fix[d]}" for n, d in found]
    return problems


def rest_block_lines(text: str) -> list[tuple[int, str]]:
    r"""Return the lines of reST literal and code-directive blocks.

    A block is every line indented past the line that opens it, up to the
    next non-blank line at or left of that indent.

    >>> doc = "Use it::\n\n    pane.run(1)\n\nProse.\n.. code-block:: sh\n\n   ls\n"
    >>> [line for _, line in rest_block_lines(doc)]
    ['    pane.run(1)', '   ls']
    >>> rest_block_lines(".. toctree::\n\n   capture\n")
    []
    """
    found: list[tuple[int, str]] = []
    opener: int | None = None
    for number, line in enumerate(text.splitlines(), 1):
        indent = len(line) - len(line.lstrip())
        if opener is not None and line.strip():
            if indent > opener:
                found.append((number, line))
                continue
            opener = None
        if REST_BLOCK.search(line) and not line.lstrip().startswith((">>>", "...")):
            opener = indent
    return found


def doc_comment_lines(
    text: str,
    suffix: str,
    kinds: dict[int, str] | None = None,
    prompts: list[tuple[int, str]] | None = None,
) -> list[tuple[int, str]]:
    r"""Return code inside doc comments: fences and ``{@code}``/``<code>``.

    Python docstrings contribute their doctest lines and reST literal
    blocks, Go doc comments their tab-indented code blocks, and Julia
    docstrings their fences. A fence is read the way a Markdown page
    reads it, so output, hidden rustdoc lines and the output in a console
    session are skipped. A plain ``//`` comment is not a doc comment.

    >>> src = "\n".join([
    ...     "/// ```", "/// let wide = 1;", "/// # hidden();", "/// ```",
    ...     "/// ```text", "/// output", "/// ```",
    ...     "// ```", "// not a doc comment", "// ```",
    ...     "/// prose is not code", "fn f() {}",
    ... ])
    >>> [line for _, line in doc_comment_lines(src, ".rs")]
    ['/// let wide = 1;']
    >>> cs = "/// <code>\n/// var x = 1;\n/// </code>\n/// prose"
    >>> [line for _, line in doc_comment_lines(cs, ".cs")]
    ['/// var x = 1;']
    >>> py = '    >>> pane.send_keys("x")\n    plain prose'
    >>> [line for _, line in doc_comment_lines(py, ".py")]
    ['    >>> pane.send_keys("x")']
    >>> literal = '    Example::\n\n        server.cmd("x")\n    Prose.'
    >>> [line for _, line in doc_comment_lines(literal, ".py")]
    ['        server.cmd("x")']
    >>> go = "// Run starts a pane:\n//\tpane.Run(ctx)\nfunc Run() {}"
    >>> [line for _, line in doc_comment_lines(go, ".go")]
    ['//\tpane.Run(ctx)']
    >>> java = " * <pre>{@code\n * pane.run();\n * }</pre>\n * prose"
    >>> [line for _, line in doc_comment_lines(java, ".java")]
    [' * pane.run();']
    >>> tsdoc = " * ```ts\n * pane.run();\n * ```\n * prose"
    >>> [line for _, line in doc_comment_lines(tsdoc, ".ts")]
    [' * pane.run();']
    >>> rs = "/// ```console\n/// $ cargo run\n/// " + "x" * 90 + "\n/// ```"
    >>> [line for _, line in doc_comment_lines(rs, ".rs")]
    ['/// $ cargo run']
    >>> fence = ["```console", "$ ls `", "    -l", "# note", "$ ls", "```"]
    >>> console = "\n".join("/// " + line for line in fence)
    >>> data: dict[int, str] = {}
    >>> wrong: list[tuple[int, str]] = []
    >>> _ = doc_comment_lines(console, ".rs", data, wrong)
    >>> data, wrong
    ({2: 'doc:command', 3: 'doc:command', 4: 'doc:note', 5: 'doc:command'}, [(2, '$ ')])
    >>> data, wrong = {}, []
    >>> jdoc = "```console\n$ julia `\n  -e 1\n```"
    >>> _ = doc_comment_lines(jdoc, ".jl", data, wrong)
    >>> data, wrong
    ({2: 'doc:command', 3: 'doc:command'}, [(2, '$ ')])
    >>> hidden = "/// ```\n/// # use std::io;\n/// let x = 1;\n/// ```"
    >>> [line for _, line in doc_comment_lines(hidden, ".rs")]
    ['/// let x = 1;']
    >>> jl = "    f(x)\n\nRun it:\n\n```julia\nf(1)\n```"
    >>> [line for _, line in doc_comment_lines(jl, ".jl")]
    ['f(1)']
    """
    if suffix == ".jl":
        local: dict[int, str] = {}
        lines = markdown_lines(text, indented=False, kinds=local)
        if kinds is not None:
            kinds.update((n, "doc:" + kind) for n, kind in local.items())
        if prompts is not None:
            prompts.extend(prompt_mismatches(text))
        return lines
    if suffix == ".py":
        doctests = [
            (number, line)
            for number, line in enumerate(text.splitlines(), 1)
            if line.lstrip().startswith((">>> ", "... "))
        ]
        return sorted(set(doctests + rest_block_lines(text)))
    found: list[tuple[int, str]] = []
    inside = False
    fenced: list[tuple[int, str, str]] | None = None
    info = ""

    def flush() -> None:
        if fenced:
            block = "\n".join([f"```{info}", *[b for _, _, b in fenced], "```"])
            # The fence's lines carry their Markdown kind, so a console line
            # in a doc comment is advised as one.
            local: dict[int, str] = {}
            kept = {n for n, _ in markdown_lines(block, indented=False, kinds=local)}
            for i, (n, line, _) in enumerate(fenced, 2):
                if i in kept:
                    found.append((n, line))
                    if kinds is not None and i in local:
                        kinds[n] = "doc:" + local[i]
            if prompts is not None:
                prompts.extend(
                    (fenced[i - 2][0], d) for i, d in prompt_mismatches(block)
                )

    for number, line in enumerate(text.splitlines(), 1):
        if suffix == ".go":
            if line.lstrip().startswith("//\t"):
                found.append((number, line))
            continue
        if BLOCK_OPEN.search(line):
            inside = not BLOCK_CLOSE.search(line)
            continue
        prefix = DOC_LINE.match(line)
        if prefix is None:
            flush()
            inside, fenced = False, None
            continue
        body = line[prefix.end() :]
        fence = FENCE.match(body)
        if fenced is not None:
            if fence and not fence["info"].strip():
                flush()
                fenced = None
            else:
                fenced.append((number, line, body))
            continue
        if fence:
            # rustdoc runs an untagged fence as Rust.
            info = fence["info"].strip() or ("rust" if suffix == ".rs" else "")
            fenced = []
            continue
        if inside and BLOCK_CLOSE.search(body):
            inside = False
            continue
        if inside:
            found.append((number, line))
    flush()
    return found


def glob_regex(pattern: str) -> re.Pattern[str]:
    """Translate a glob: ``*`` stays within a directory, ``**`` spans them.

    >>> bool(glob_regex("docs/*.md").fullmatch("docs/plans/a.md"))
    False
    >>> bool(glob_regex("docs/**/*.md").fullmatch("docs/a.md"))
    True
    """
    out = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out))


def matches(path: str, patterns: list[str]) -> bool:
    """Return whether a repository-relative path matches any glob.

    >>> matches("README.md", ["**/README.md"])
    True
    >>> matches("docs/a/b.md", ["docs/**/*.md"])
    True
    >>> matches("src/a.rs", ["docs/**/*.md"])
    False
    """
    return any(glob_regex(pattern).fullmatch(path) for pattern in patterns)


def allow_hint(finding: Finding) -> str:
    r"""Return an ``[[allow]]`` entry for a finding, ready to paste.

    JSON string escapes are valid TOML basic-string escapes, so a tab or a
    quote in the line survives the copy.

    >>> print(allow_hint(Finding("main.go", 3, 90, 80, '\tx := "y"')))
    [[allow]]
    path = "main.go"
    line = "\tx := \"y\""
    reason = "why breaking this line would make the example worse"
    """
    return "\n".join(
        [
            "[[allow]]",
            f"path = {json.dumps(finding.path, ensure_ascii=False)}",
            f"line = {json.dumps(finding.text, ensure_ascii=False)}",
            f"reason = {json.dumps(PLACEHOLDER)}",
        ]
    )


def plural(count: int, one: str, many: str | None = None) -> str:
    """Return a count with its noun in the matching number.

    >>> plural(1, "wide line"), plural(2, "wide line")
    ('1 wide line', '2 wide lines')
    """
    return f"{count} {one if count == 1 else (many or one + 's')}"


def literal(value: t.Any) -> str:
    """Return a config value as TOML writes it, for a message to quote.

    >>> literal(True), literal("80"), literal(["a", 5]), literal({"glob": "x"})
    ('true', '"80"', '["a", 5]', '{glob = "x"}')
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(literal(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = ", ".join(f"{key} = {literal(item)}" for key, item in value.items())
        return "{" + pairs + "}"
    return str(value)


def article(table: str) -> str:
    """Return the article for a table name: an [[allow]], a [[formatter_copies]].

    >>> article("allow"), article("exclude"), article("formatter_copies")
    ('an', 'an', 'a')
    """
    return "an" if table[0] in "aeiou" else "a"


def glob_key(path: str) -> str:
    """Return the config key whose glob should select ``path``.

    >>> [glob_key(f"a.{suffix}") for suffix in ("md", "markdown", "mdx", "rst", "rs")]
    ['markdown', 'markdown', 'markdown', 'markdown', 'sources']
    """
    return (
        "markdown" if path.endswith((".md", ".markdown", ".mdx", ".rst")) else "sources"
    )


def select_advice(path: str) -> str:
    """Return how to select or exclude an unselected file under examples/.

    >>> select_advice("examples/a.md")
    'add "examples/a.md" to markdown, or to [[exclude]] with a reason'
    >>> select_advice("examples/blob.bin").split("; ")[1]
    'a binary file holds no lines'
    >>> select_advice("examples/logo.png")
    'add "examples/logo.png" to [[exclude]] with a reason; a binary file holds no lines'
    """
    if path.lower().endswith(BINARY):
        return (
            f'add "{path}" to [[exclude]] with a reason; a binary file holds no lines'
        )
    return f'add "{path}" to {glob_key(path)}, or to [[exclude]] with a reason'


def syntax_hint(pattern: str) -> str:
    """Return a note for a glob that uses syntax the check reads literally.

    >>> syntax_hint("docs/{a,b}.md"), syntax_hint("docs/*.md")
    ('; globs here take `*`, `**` and `?`, not `{a,b}` or `[...]`', '')
    """
    if re.search(r"[{\[]", pattern):
        return "; globs here take `*`, `**` and `?`, not `{a,b}` or `[...]`"
    return ""


def misspelled(entry: dict[str, t.Any], key: str) -> bool:
    """Return whether an entry carries an unknown key close to ``key``.

    >>> misspelled({"reson": "r"}, "reason"), misspelled({"path": "a"}, "reason")
    (True, False)
    """
    return any(nearest(other, {key}) for other in entry if other != key)


def nearest(key: str, keys: t.Collection[str] = KEYS) -> str:
    """Return a "did you mean" clause for a misspelled config key, or "".

    >>> nearest("widht"), nearest("zzz"), nearest("reson", {"path", "reason"})
    ('did you mean width? ', '', 'did you mean reason? ')
    """
    match = meant(key, keys)
    return f"did you mean {match}? " if match else ""


def meant(key: str, keys: t.Collection[str] = KEYS) -> str:
    """Return the known key a misspelled one is closest to, or "".

    >>> meant("allow_cieling"), meant("zzz")
    ('allow_ceiling', '')
    """
    import difflib

    match = difflib.get_close_matches(key, sorted(keys), n=1)
    return match[0] if match else ""


def suggest(key: str, keys: t.Collection[str], rest: str) -> str:
    """Return the "did you mean" clause, if any, then the keys a table takes.

    >>> suggest("widht", {"width"}, "the config takes width")
    'did you mean width? The config takes width'
    >>> suggest("zzz", {"width"}, "the config takes width")
    'the config takes width'
    """
    hint = nearest(key, keys)
    return hint + rest[:1].upper() + rest[1:] if hint else rest


def type_problems(config: dict[str, t.Any]) -> list[str]:
    """Return values whose type the check cannot use.

    >>> for problem in type_problems({"width": "80", "markdown": "**/*.md"}):
    ...     print(problem)
    width must be an integer, not "80"
    markdown must be a list of globs, not "**/*.md"
    >>> type_problems({"width": 80, "markdown": ["**/*.md"], "exclude": []})
    []
    >>> type_problems({"exclude": [{"glob": 5, "reason": "r"}]})
    ['glob in an [[exclude]] entry must be a string, not 5: {glob = 5, reason = "r"}']
    >>> type_problems({"allow_ceiling": True})
    ['allow_ceiling must be an integer, not true']
    """
    problems = [
        f"{key} must be {name}, not {literal(config[key])}"
        for key, (kind, name) in VALUE_TYPES.items()
        if key in config
        and (not isinstance(config[key], kind) or isinstance(config[key], bool))
    ]
    for key in GLOB_KEYS:
        value = config.get(key, [])
        if not isinstance(value, list) or not all(isinstance(g, str) for g in value):
            problems.append(f"{key} must be a list of globs, not {literal(value)}")
    problems.extend(
        f"{table} must be written as [[{table}]] entries"
        for table in TABLE_KEYS
        if not isinstance(config.get(table, []), list)
    )
    for table, keys in TABLE_KEYS.items():
        table_entries = config.get(table, [])
        if not isinstance(table_entries, list):
            continue
        problems.extend(
            f"{key} in {article(table)} [[{table}]] entry must be a string, "
            f"not {literal(entry[key])}: {literal(entry)}"
            for entry in table_entries
            if isinstance(entry, dict)
            for key in sorted(keys & set(entry))
            if not isinstance(entry[key], str)
        )
    return problems


def config_problems(config: dict[str, t.Any], files: list[str]) -> list[str]:
    """Return configuration mistakes that would silently weaken the check.

    >>> config = {"widht": 80, "markdown": ["nope/*.md"], "allow_ceiling": 0}
    >>> [problem.split(";")[0] for problem in config_problems(config, ["README.md"])]
    ['unknown key: widht', 'markdown glob matches no tracked file: nope/*.md']
    >>> config_problems({"reason": "r", "allow_ceiling": 0}, [])[0]
    'unknown key: reason; reason belongs inside an [[...]] entry, below its header'

    >>> config_problems({"tab_width": 0, "allow_ceiling": 0}, [])[0].split("; ")[::2]
    ['tab_width is 0', 'set it to 4']
    >>> config_problems(config, ["README.md"])[1].split("; ")[1]
    'fix the glob or remove it'
    >>> held = {"markdown": ["docs/{a,b}.md"], "allow_ceiling": 0}
    >>> held["exclude"] = [{"glob": "notes/*", "reason": "r"}]
    >>> len(config_problems(held, ["docs/a.md", "notes/b.md", "examples/c.md"]))
    1
    >>> braces = {"markdown": ["docs/{a,b}.md"], "allow_ceiling": 0}
    >>> config_problems(braces, ["docs/a.md"])[0].split("; ")[-1]
    'globs here take `*`, `**` and `?`, not `{a,b}` or `[...]`'
    >>> config = {"allow": [{"path": "a", "line": "b"}], "allow_ceiling": 1}
    >>> config_problems(config, ["a"])
    ['allow entry for a has no reason: "b"']
    >>> for problem in config_problems({"width": 100, "exclude": ["a"]}, ["a"]):
    ...     print(problem)
    an [[exclude]] entry is not a table: "a"
    width is 100; the shared rule is 80
    allow_ceiling is missing; set it to 0, the number of allow entries
    >>> excluded = {"glob": "notes/*.md", "reason": "drafts"}
    >>> config = {"markdown": ["*.md"], "exclude": [excluded], "allow_ceiling": 0}
    >>> unused = config_problems(config, ["a.md", "notes/b.md"])[0].split("; ")
    >>> unused[0]
    'exclude glob matches no checked file or file under examples/: notes/*.md'
    >>> unused[1]
    'fix the glob or delete the entry'
    >>> copy = {"copy": "notes/x.toml", "root": "x.toml", "key": "width"}
    >>> moved = {"glob": "notes/x.toml", "reason": "formatter copy"}
    >>> config = dict(config, exclude=[moved], formatter_copies=[copy])
    >>> config_problems(config, ["a.md"])
    []
    >>> config = {"markdwn": ["**/*.md"], "exclude": [excluded], "allow_ceiling": 0}
    >>> [problem.split(";")[0] for problem in config_problems(config, ["notes/b.md"])]
    ['unknown key: markdwn']
    >>> config = {"sources": ["examples/*.go"], "allow_ceiling": 0}
    >>> files = ["examples/a.go", "examples/go.mod"]
    >>> unread = config_problems(config, files)[0].split("; ")
    >>> unread[0]
    'examples/go.mod is under examples/ but neither checked nor excluded'
    >>> unread[1]
    'add "examples/go.mod" to sources, or to [[exclude]] with a reason'
    >>> typo = {"globb": "examples/go.mod", "reason": "module file"}
    >>> found = config_problems(dict(config, exclude=[typo]), files)
    >>> [problem for problem in found if "neither" in problem]
    []
    >>> mod = {"glob": "examples/go.mod", "reason": "module file"}
    >>> config_problems(dict(config, exclude=[mod]), files)
    []
    >>> config["exclude"] = [dict(mod, doc_comments=["*.go"])]
    >>> config_problems(config, files)[0].split(";")[0]
    'unknown key in an [[exclude]] entry: doc_comments'
    >>> nested = {"exclude": [{"glob": "x", "reason": "r", "sources": ["*.go"]}]}
    >>> [p.split(";")[0] for p in config_problems(nested, ["examples/a.go"])]
    ['unknown key in an [[exclude]] entry: sources', 'allow_ceiling is missing']
    >>> below = {"path": "a", "line": "b", "reason": "r", "allow_ceiling": 1}
    >>> [p.split(";")[0] for p in config_problems({"allow": [below]}, ["a"])]
    ['unknown key in an [[allow]] entry: allow_ceiling']
    >>> config = {"allow": [{"file": "a", "line": "b", "reason": "c"}]}
    >>> config_problems(dict(config, allow_ceiling=1), ["a"])[1]
    'an [[allow]] entry has no path: {file = "a", line = "b", reason = "c"}'
    >>> pasted = {"path": "a", "line": "b", "reason": PLACEHOLDER}
    >>> config_problems({"allow": [pasted], "allow_ceiling": 1}, ["a"])[0]
    'allow entry for a keeps the placeholder reason; say why this line cannot break'
    >>> misspelled = {"markdwn": ["*.md"], "allow_ceiling": 0}
    >>> config_problems({"widht": 80, "allow_ceiling": 0}, [])[0].split("; ")[1][:24]
    'did you mean width? The '
    >>> [p.split(";")[0] for p in config_problems({"allow_cieling": 0}, [])]
    ['unknown key: allow_cieling']
    >>> broken = {"glob": "examples/LICENS[E]", "reason": "license text"}
    >>> config = {"sources": ["examples/*.go"], "exclude": [broken], "allow_ceiling": 0}
    >>> found = config_problems(config, ["examples/a.go", "examples/LICENSE"])
    >>> [p.split(";")[0] for p in found]
    ['exclude glob matches no checked file or file under examples/: examples/LICENS[E]']
    >>> found = config_problems(misspelled, ["examples/a.md"])
    >>> [problem.split(";")[0] for problem in found]
    ['unknown key: markdwn']
    >>> typo = {"path": "a", "line": "b", "reson": "r"}
    >>> found = config_problems({"allow": [typo], "allow_ceiling": 1}, ["a"])
    >>> found[0].split("; ")[1].split("?")[0], len(found)
    ('did you mean reason', 1)
    >>> typo = {"glob": "a", "reson": "r"}
    >>> len(config_problems({"exclude": [typo], "allow_ceiling": 0}, ["a"]))
    1
    >>> typo = {"globb": "a", "reason": "r"}
    >>> len(config_problems({"exclude": [typo], "allow_ceiling": 0}, ["a"]))
    1
    >>> bracket = {"glob": "docs/[ab].md", "reason": "r"}
    >>> config = {"markdown": ["*.md"], "exclude": [bracket], "allow_ceiling": 0}
    >>> config_problems(config, ["a.md"])[0].split("; ")[-1][:20]
    'globs here take `*`,'
    """
    entry_keys = set().union(*TABLE_KEYS.values())
    problems = [
        f"unknown key: {key}; "
        + (
            f"{key} belongs inside an [[...]] entry, below its header"
            if key in entry_keys
            else suggest(key, KEYS, f"the config takes {', '.join(sorted(KEYS))}")
        )
        for key in sorted(set(config) - KEYS)
    ]
    for table, keys in TABLE_KEYS.items():
        for entry in config.get(table, []):
            if not isinstance(entry, dict):
                problems.append(
                    f"{article(table)} [[{table}]] entry is not a table: "
                    f"{literal(entry)}"
                )
                continue
            problems.extend(
                f"unknown key in {article(table)} [[{table}]] entry: {key}; "
                + (
                    "TOML puts every key below a [[...]] header into that "
                    "entry, so top-level keys go above the first one"
                    if key in KEYS
                    else suggest(
                        key,
                        keys,
                        f"{article(table)} [[{table}]] entry takes "
                        f"{', '.join(sorted(keys))}",
                    )
                )
                for key in sorted(set(entry) - keys)
            )
            problems.extend(
                f"{article(table)} [[{table}]] entry has no {key}: {literal(entry)}"
                for key in sorted(keys - set(entry) - {"reason"})
                if not misspelled(entry, key)
            )
    if config.get("width", 80) != 80:
        problems.append(f"width is {config['width']}; the shared rule is 80")
    if config.get("tab_width", 4) != 4:
        problems.append(
            f"tab_width is {config['tab_width']}; the check counts a tab as 4 "
            "columns, as the formatters here do; set it to 4"
        )
    globs = [(key, pattern) for key in GLOB_KEYS for pattern in config.get(key, [])]
    problems.extend(
        f"{key} glob matches no tracked file: {pattern}; fix the glob or remove it"
        + syntax_hint(pattern)
        for key, pattern in globs
        if not any(glob_regex(pattern).fullmatch(path) for path in files)
    )
    checked = [path for path in files if matches(path, [p for _, p in globs])]
    examples = [path for path in files if EXAMPLE_DIR.search(path)]
    # An unknown top-level key is usually a misspelled glob key, which leaves
    # files unchecked: exclusions look unused and example files look unread.
    # Report the key alone until it is fixed.
    known = not set(config) - KEYS and not any(
        isinstance(entry, dict) and (set(entry) & KEYS or set(entry) - keys)
        for table, keys in TABLE_KEYS.items()
        for entry in config.get(table, [])
    )
    # A glob that matches nothing leaves its files unread, so exclusions and
    # example files would look wrong until it is fixed.
    known = known and all(
        any(glob_regex(pattern).fullmatch(path) for path in files)
        for _, pattern in globs
    )
    excluded: list[str] = []
    dead = False
    for entry in config.get("exclude", []):
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("reason", "")).strip() and not misspelled(entry, "reason"):
            problems.append(f"exclude entry has no reason: {literal(entry)}")
            continue
        if "glob" not in entry:
            continue
        excluded.append(entry["glob"])
        pattern = glob_regex(entry["glob"])
        # A missing formatter copy is reported by the copy check instead.
        copies = [pair.get("copy", "") for pair in config.get("formatter_copies", [])]
        unread = not any(pattern.fullmatch(path) for path in checked + examples)
        if known and unread and not any(pattern.fullmatch(c) for c in copies):
            dead = True
            problems.append(
                "exclude glob matches no checked file or file under examples/: "
                f"{entry['glob']}; fix the glob or delete the entry"
                + syntax_hint(entry["glob"])
            )
    # A broken exclusion glob leaves its file looking unexcluded; asking for a
    # new entry would duplicate the one that needs fixing.
    if known and not dead:
        problems.extend(
            f"{path} is under examples/ but neither checked nor excluded; "
            + select_advice(path)
            for path in examples
            if path not in checked and not matches(path, excluded)
        )
    count = len(config.get("allow", []))
    ceiling = config.get("allow_ceiling")
    nested = any(
        isinstance(entry, dict) and "allow_ceiling" in entry
        for table in TABLE_KEYS
        for entry in config.get(table, [])
    ) or any(meant(key) == "allow_ceiling" for key in set(config) - KEYS)
    if ceiling is None:
        # Written below a [[...]] header or misspelled, the key is already
        # reported; asking for it again would invite a second copy.
        if not nested:
            problems.append(
                f"allow_ceiling is missing; set it to {count}, "
                "the number of allow entries"
            )
    elif count > int(ceiling):
        problems.append(
            f"allow_ceiling {ceiling} is below the "
            f"{plural(count, 'allow entry', 'allow entries')}; delete the new "
            "entry and shorten its line, or raise the ceiling in a change that "
            "gives the reason"
        )
    elif count < int(ceiling):
        problems.append(
            f"allow_ceiling {ceiling} is above the "
            f"{plural(count, 'allow entry', 'allow entries')}; lower it"
        )
    problems.extend(
        f"allow entry for {entry.get('path')} has no reason: "
        f"{literal(entry.get('line'))}"
        for entry in config.get("allow", [])
        if isinstance(entry, dict)
        and not str(entry.get("reason", "")).strip()
        and not misspelled(entry, "reason")
    )
    problems.extend(
        f"allow entry for {entry.get('path')} keeps the placeholder reason; "
        "say why this line cannot break"
        for entry in config.get("allow", [])
        if isinstance(entry, dict) and entry.get("reason") == PLACEHOLDER
    )
    return problems


def entries(config: dict[str, t.Any], table: str) -> list[dict[str, t.Any]]:
    """Return the ``[[table]]`` entries that hold every key the check reads.

    ``config_problems`` reports the others, so the check skips them.

    >>> entries({"allow": [{"path": "a", "line": "b"}, {"line": "c"}]}, "allow")
    [{'path': 'a', 'line': 'b'}]
    """
    need = TABLE_KEYS[table] - {"reason"}
    return [
        entry
        for entry in config.get(table, [])
        if isinstance(entry, dict) and need <= set(entry)
    ]


def setting_text(line: str) -> str:
    """Return a config line without its comment, quoted text left alone.

    >>> setting_text("max_width = 80  # was 120"), setting_text("# all comment")
    ('max_width = 80', '')
    >>> setting_text('"name": "a # b", // note')
    '"name": "a # b",'
    """
    quote = None
    for index, char in enumerate(line):
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif line.startswith(("#", "//", ";"), index) and (
            index == 0 or line[index - 1].isspace()
        ):
            return line[:index].rstrip()
    return line.rstrip()


def copy_problems(root: pathlib.Path, config: dict[str, t.Any]) -> list[str]:
    """Return formatter copies that drifted from their root file.

    A copy may differ from its root only in the width key's value and the
    comment on that line; every other setting, on that line too, must match.
    A drifted copy is reported against its own path, the file to change.
    """
    problems = []
    for pair in entries(config, "formatter_copies"):
        missing = [
            pair[side] for side in ("copy", "root") if not (root / pair[side]).is_file()
        ]
        if missing:
            problems.extend(
                f"{CONFIG}: formatter copy file does not exist: {m}" for m in missing
            )
            continue

        def kept(path: str, key: str = pair["key"]) -> list[str]:
            # The key's value becomes a placeholder, so another setting written
            # on the same line still has to match.
            value = rf'("?{re.escape(key)}"?\s*[=:]\s*"?)\w+'
            lines = (root / path).read_text(encoding="utf-8").splitlines()
            return [
                re.sub(value, r"\g<1>width", setting_text(line))
                if key in line
                else line
                for line in lines
            ]

        lines = (root / pair["copy"]).read_text(encoding="utf-8").splitlines()
        key = re.escape(pair["key"])
        code = "\n".join(setting_text(line) for line in lines)
        setting = rf'(?:^|[\s{{,])"?{key}"?\s*[=:]\s*"?(\w+)'
        sets = re.findall(setting, code, re.MULTILINE)
        if len(sets) > 1:
            # JSON keeps the last of two equal keys, so a second setting wins.
            problems.append(
                f"{pair['copy']}: sets {pair['key']} {len(sets)} times; keep one "
                "setting, set to 80"
            )
        elif sets != ["80"]:
            problems.append(
                f"{pair['copy']}: {pair['key']} is not 80; set it to 80, the "
                "width every example keeps"
            )
        if kept(pair["copy"]) != kept(pair["root"]):
            problems.append(
                f"{pair['copy']}: differs from {pair['root']} beyond the {pair['key']} "
                f"value; make it equal to {pair['root']} except that value"
            )
    return problems


def check(
    root: pathlib.Path, config: dict[str, t.Any], files: list[str]
) -> tuple[list[Finding], list[dict[str, str]]]:
    """Return lines over the width, and allow entries that matched nothing."""
    width = int(config.get("width", 80))
    tab_width = int(config.get("tab_width", 4))
    exclude = [entry["glob"] for entry in entries(config, "exclude")]
    allow = entries(config, "allow")
    allowed = {(entry["path"], entry["line"]) for entry in allow}
    used: set[tuple[str, str]] = set()
    findings: list[Finding] = []
    for path in files:
        if matches(path, exclude):
            continue
        suffix = pathlib.PurePosixPath(path).suffix
        if matches(path, config.get("markdown", [])):
            kind = "markdown"
        elif matches(path, config.get("sources", [])):
            kind = "source"
        elif matches(path, config.get("doc_comments", [])):
            kind = "doc"
        else:
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        kinds: dict[int, str] = {}
        if kind == "markdown" and suffix == ".rst":
            lines = rest_block_lines(text)
        elif kind == "markdown":
            lines = markdown_lines(text, kinds=kinds)
        elif kind == "doc":
            lines = doc_comment_lines(text, suffix, kinds)
            kinds = {number: kinds.get(number, "doc") for number, _ in lines}
        else:
            lines = list(enumerate(text.splitlines(), 1))
            kinds = {number: "source" for number, _ in lines}
        for number, line in lines:
            shown = line.expandtabs(tab_width).rstrip()
            wide = columns(shown)
            if wide <= width or is_url(shown) or HIDDEN.match(shown):
                continue
            key = (path, line.rstrip())
            if key in allowed:
                used.add(key)
                continue
            where = kinds.get(number, "")
            findings.append(Finding(path, number, wide, width, key[1], where))
    stale = [entry for entry in allow if (entry["path"], entry["line"]) not in used]
    return findings, stale


def tracked_files(root: pathlib.Path, others: bool = False) -> list[str]:
    """Return the files git tracks, as POSIX paths relative to the root.

    With ``others``, return instead the untracked files git does not ignore.
    A symbolic link is left out: its target is checked under its own path, so
    a link such as CLAUDE.md to AGENTS.md would report every line twice.
    """
    untracked = ["--others", "--exclude-standard"] if others else []
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *untracked],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [p for p in output.split("\0") if p and not (root / p).is_symlink()]


def writing_path(root: pathlib.Path) -> pathlib.Path | None:
    """Return the WRITING.md that carries the shared section, if any."""
    for name in (".github/WRITING.md", "WRITING.md"):
        path = root / name
        if path.is_file() and SHARED.search(path.read_text(encoding="utf-8")):
            return path
    return None


def writing_file(root: pathlib.Path) -> pathlib.Path | None:
    """Return the repository's WRITING.md, with or without the markers."""
    for name in (".github/WRITING.md", "WRITING.md"):
        if (root / name).is_file():
            return root / name
    return None


def marker_problems(root: pathlib.Path) -> list[str]:
    """Return a problem when no WRITING.md holds both shared markers.

    Without them the routing and port-block checks have nothing to read, so
    the run says so instead of skipping them.
    """
    if writing_path(root) is not None:
        return []
    writing = writing_file(root)
    if writing is None:
        return ["no WRITING.md: add .github/WRITING.md with the shared section"]
    where = writing.relative_to(root).as_posix()
    restore = f"`git show HEAD:{where}` or from another port"
    return [
        f"{where}: the shared markers are missing or unbalanced; restore the "
        + f"section from {restore}"
    ]


def slug(heading: str) -> str:
    """Return the anchor GitHub gives a Markdown heading.

    >>> slug("Documented examples that run")
    'documented-examples-that-run'
    >>> slug("Reaching 80")
    'reaching-80'
    """
    text = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return text.replace(" ", "-")


def unfenced(text: str) -> str:
    r"""Return Markdown text without its fenced blocks.

    A ``# comment`` inside a shell fence is not a heading.

    >>> unfenced("## A\n```sh\n# not a heading\n```\ntext\n")
    '## A\ntext\n'
    """
    kept, fence = [], ""
    for line in text.splitlines(keepends=True):
        mark = FENCE.match(line.rstrip("\n"))
        if mark and not fence:
            fence = mark["mark"]
        elif mark and mark["mark"].startswith(fence) and not mark["info"].strip():
            fence = ""
        elif not fence:
            kept.append(line)
    return "".join(kept)


def prose(text: str) -> str:
    r"""Return Markdown text without its code and comments.

    Fenced, indented and ``<pre>`` blocks, code spans of any backtick count
    and HTML comments are dropped, so a link inside one is not a link:

    >>> prose("a `[x](y)` b ``[x](`y`)`` <!-- [x](y) -->\n\n    [x](y)\n- [z](w)\n")
    'a  b  \n\n- [z](w)\n'
    >>> prose("```text\n[x](y)\n```\n")
    ''
    """
    text = unfenced(text)
    code = {number for number, _ in markdown_lines(text)}
    lines = text.splitlines(keepends=True)
    text = "".join(line for n, line in enumerate(lines, 1) if n not in code)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    span = r"(?<!`)(`+)(?!`)(?:(?!\n[ \t]*\n).)+?(?<!`)\1(?!`)"
    return re.sub(span, "", text, flags=re.DOTALL)


def links(text: str) -> list[str]:
    r"""Return the targets of a Markdown text's inline and reference links.

    >>> links('[A](a.md#x "A"), [B](<b.md>) and [C](c.md \'C\')\n[d]: d.md')
    ['a.md#x', 'b.md', 'c.md', 'd.md']
    >>> links("![E](e.md) \\[F](f.md) [G\nH](g.md)")
    ['g.md']
    """
    return [inline or reference for inline, reference in LINK.findall(text)]


def routing_problems(root: pathlib.Path) -> list[str]:
    """Return a problem unless AGENTS.md links the shared section's heading.

    The heading is the last one of level one or two above the shared
    markers: the section an agent routed from AGENTS.md should land in.
    """
    writing = writing_path(root)
    if writing is None:
        return []
    text = writing.read_text(encoding="utf-8")
    above = unfenced(text[: text.index("<!-- shared:examples -->")])
    headings = [m[2] for m in HEADING.finditer(above) if len(m[1]) <= 2]
    if not headings:
        where = writing.relative_to(root).as_posix()
        return [f"{where}: no heading above the shared section"]
    anchor = slug(headings[-1])
    agents = root / "AGENTS.md"
    where = f"{writing.relative_to(root).as_posix()}#{anchor}"
    link = f"[{headings[-1]}]({where})"
    if not agents.is_file():
        return [f"AGENTS.md is missing; add it with a link such as {link}"]
    route = prose(agents.read_text(encoding="utf-8"))
    for target in links(route):
        path, _, fragment = target.partition("#")
        # GitHub reads a leading slash as the repository root.
        here = root / path.removeprefix("/")
        if fragment == anchor and here.resolve() == writing.resolve():
            return []
    return [
        f"AGENTS.md: no link to {where}, the section with the example rules; "
        + f"add one such as {link}"
    ]


def port_block_problems(text: str) -> list[str]:
    r"""Return how a WRITING.md's ``### In this repository`` block strays.

    >>> labels = "\n".join(label + " x" for label in PORT_LABELS)
    >>> bad = "```text\n" + "x" * 81 + "\n```"
    >>> head = f"### In this repository\n\n{labels}\n\n"
    >>> block = head + f"Bad, over 80:\n\n{bad}\n\nGood, named:\n"
    >>> port_block_problems(block)
    []
    >>> [p.split(";")[0] for p in port_block_problems(block.replace("x" * 81, "x"))]
    ['In this repository: the Bad example fits in 80 columns']
    >>> port_block_problems(block.replace("- **Not formatted:**", "- **Other:**"))
    ['In this repository: no "- **Not formatted:**" bullet in its place']
    >>> port_block_problems("## Examples\n")
    ['no "### In this repository" block']
    >>> port_block_problems(block + "\n" + block)
    ['2 "### In this repository" blocks; keep one']
    """
    blocks = PORT_BLOCK.findall(unfenced(text))
    if len(blocks) > 1:
        return [f'{len(blocks)} "### In this repository" blocks; keep one']
    match = PORT_BLOCK.search(unfenced(text))
    if match is None:
        return ['no "### In this repository" block']
    lines = match["body"].splitlines()
    problems = []
    at = 0
    for label in PORT_LABELS:
        found = next((i for i, line in enumerate(lines) if line.startswith(label)), -1)
        if found < at:
            problems.append(f'In this repository: no "{label}" bullet in its place')
        else:
            at = found
    for example in ("Bad, over 80", "Good"):
        count = sum(line.startswith(example) for line in lines[at:])
        if count != 1:
            problems.append(f'In this repository: {count} "{example}" examples, want 1')
    # The fence after "Bad, over 80" is stripped above, so read it raw: a
    # Bad example that a later edit brought within 80 no longer shows a fault.
    raw = text[text.find("### In this repository") :].splitlines()
    start = next(
        (i for i, line in enumerate(raw) if line.startswith("Bad, over 80")), None
    )
    if start is not None:
        opens = [i for i in range(start + 1, len(raw)) if FENCE.match(raw[i])]
        code = raw[opens[0] + 1 : opens[1]] if len(opens) > 1 else []
        if not any(columns(line.expandtabs(4)) > 80 for line in code):
            problems.append(
                "In this repository: the Bad example fits in 80 columns; "
                "show a line that does not"
            )
    return problems


# A comment after code, set off by two spaces as most style guides ask.
TRAILING = re.compile(r"\S\s{2,}(?://|#|--)\s+(?P<body>.*)$")
# How a comment line starts in the languages the examples use.
COMMENTS = ("# ", "// ", "-- ", "/// ", "//! ", "/* ", "* ", "<!-- ")


def kept_whole(rules: str) -> str:
    """Return the rule that sends compared output and marker lines to allow."""
    return f"Compared output and marker lines stay whole ({rules}#what-never-breaks)"


def fix_advice(finding: Finding, rules: str) -> str:
    r"""Return how to fix a wide line: a command splits, other code changes.

    >>> code = Finding("a.md", 1, 90, 80, "let total = first + second;")
    >>> fix_advice(code, "W.md").split(":")[0]
    'Fix a wide line by changing the code, not the line breaks'
    >>> fix_advice(code, "W.md").split(" ")[-2]
    'W.md#in-this-repository'
    >>> flag = Finding("a.md", 2, 90, 80, "    -DCMAKE_BUILD_TYPE=x -DX=1", "command")
    >>> fix_advice(flag, "W.md").split(":")[0]
    'Split a wide command the way its shell continues'
    >>> said = Finding("a.md", 2, 90, 80, "$ ls  # list them", "command")
    >>> note = Finding("a.md", 2, 90, 80, "# Build the tree", "note")
    >>> fix_advice(said, "W.md") == fix_advice(note, "W.md")
    True
    >>> fix_advice(note, "W.md")
    'Move the comment out of the block into the prose around it: W.md#code-blocks.'
    >>> remark = Finding("a.rs", 2, 90, 80, "    // explain the call", "source")
    >>> fix_advice(remark, "W.md").split(";")[0]
    'Wrap the comment at 80 (W.md#width)'
    >>> "(W.md#what-never-breaks)" in fix_advice(remark, "W.md")
    True
    >>> "copied" in fix_advice(remark, "W.md")
    False
    >>> output = Finding("a_test.go", 9, 90, 80, "\t// Output: " + "x" * 80, "source")
    >>> fix_advice(output, "W.md").split(":")[0]
    'Compared output and marker lines stay whole (W.md#what-never-breaks)'
    >>> token = Finding("a.md", 3, 90, 80, "    --features=" + "x" * 70, "command")
    >>> fix_advice(token, "W.md").split(":")[0]
    'Fix a wide line by changing the code, not the line breaks'
    >>> bare = Finding("a.md", 2, 90, 80, "cargo test --doc", "promptless")
    >>> fix_advice(bare, "W.md").split(",")[0]
    'If it is a command'
    >>> "(W.md#reaching-80)" in fix_advice(bare, "W.md")
    True
    >>> fix_advice(bare, "W.md").split("; ")[-1]
    'if it is output, tag the fence `text`.'
    >>> fix_advice(Finding("a.md", 2, 90, 80, "# Build it", "promptless"), "W.md")
    'Move the comment out of the block into the prose around it: W.md#code-blocks.'
    >>> program = Finding("a.rs", 2, 90, 80, "let total = first + second;", "source")
    >>> "copied" in fix_advice(program, "W.md"), "copied" in fix_advice(code, "W.md")
    (False, True)
    >>> fix_advice(program, "W.md").split(",")[0]
    'If the port block names a formatter for this file'
    >>> fix_advice(program, "W.md").split(". ")[-1]
    'If a Markdown block copies this file, re-copy it as W.md#in-this-repository says.'
    >>> script = Finding("run.sh", 3, 90, 80, "cmake -S . -B build -DX=1", "source")
    >>> fix_advice(script, "W.md").split(". ")[-2]
    'If it is one command, it may instead continue the way its shell does'
    >>> fenced = Finding("a.md", 3, 90, 80, "cmake -S . -B build -DX=1", "script")
    >>> fix_advice(fenced, "W.md").split(". ")[1]
    'If it is one command, it may instead continue the way its shell does'
    >>> "goes in a `console` fence with its prompt" in fix_advice(fenced, "W.md")
    True
    >>> fix_advice(Finding("a.md", 2, 90, 80, "# build it", "script"), "W.md")[:22]
    'Wrap the comment at 80'
    >>> html = Finding("a.md", 2, 90, 80, "<!-- a note for the next editor -->")
    >>> fix_advice(html, "W.md")[:22]
    'Wrap the comment at 80'
    >>> doc = Finding("a.rs", 2, 90, 80, "/// // a comment line in doc code", "doc")
    >>> fix_advice(doc, "W.md")[:22]
    'Wrap the comment at 80'
    >>> go = Finding("a.go", 2, 90, 80, "//\t// Wait for the marker line", "doc")
    >>> pydoc = Finding("a.py", 2, 90, 80, "    >>> # Wait for the marker", "doc")
    >>> [fix_advice(f, "W.md")[:22] for f in (go, pydoc)]
    ['Wrap the comment at 80', 'Wrap the comment at 80']
    >>> said = Finding("a.md", 2, 90, 80, ">>> # Wait for the marker", "session")
    >>> data = Finding("a.md", 2, 90, 80, "# a heredoc line, not a comment", "session")
    >>> fix_advice(said, "W.md")[:22]
    'Wrap the comment at 80'
    >>> fix_advice(data, "W.md").split(":")[0]
    'Fix a wide line by changing the code, not the line breaks'
    >>> doc = Finding("a.rs", 2, 90, 80, "/// let total = first + second;", "doc")
    >>> fix_advice(doc, "W.md").split(":")[0], "copied" in fix_advice(doc, "W.md")
    ('Fix a wide line by changing the code, not the line breaks', True)
    >>> note = Finding("README.md", 3, 84, 80, "// wait until the pane prints it")
    >>> "copied" in fix_advice(note, "W.md")
    True
    >>> line = "/// $ tmux new-session -d -s demo \\"
    >>> doced = Finding("a.rs", 4, 90, 80, line, "doc:command")
    >>> fix_advice(doced, "W.md").split(":")[0]
    'Split a wide command the way its shell continues'
    >>> noted = Finding("a.rs", 5, 90, 80, "/// # Create a session first", "doc:note")
    >>> fix_advice(noted, "W.md")[:24]
    'Move the comment out of '
    >>> bare_note = Finding("a.rs", 2, 90, 80, "/// # Create it", "doc:promptless")
    >>> fix_advice(bare_note, "W.md")[:24]
    'Move the comment out of '
    >>> labelled = Finding("A.md", 3, 90, 80, "session.name();  // → demo", "")
    >>> fix_advice(labelled, "W.md").split(": ")[0]
    'Keep the code and its marker on one line (W.md#what-never-breaks)'
    >>> "shorten the code before the marker (W.md#reaching-80)" in fix_advice(
    ...     labelled, "W.md"
    ... )
    True
    >>> remark_copy = fix_advice(remark, "W.md").split(". ")[-1]
    >>> remark_copy
    'If a Markdown block copies this file, re-copy it as W.md#in-this-repository says.'
    >>> command = Finding("a.md", 1, 90, 80, "  PS> Get-Item -Path x")
    >>> fix_advice(command, "W.md")
    'Split a wide command the way its shell continues: W.md#reaching-80.'
    """
    kind, text = finding.kind, finding.text.lstrip()
    # A line in a doc-comment fence carries its Markdown kind after "doc:";
    # read it past its comment marker, as the Markdown line would be read.
    if kind.startswith("doc:"):
        marker = GO_DOC if GO_DOC.match(finding.text) else DOC_LINE
        kind, text = kind[4:], marker.sub("", finding.text, count=1).lstrip()
    reach = f"{rules}#reaching-80"
    advice = f"Fix a wide line by changing the code, not the line breaks: {reach}."
    # Code blocks keeps explanations out of a console block, in the prose.
    prose = (
        f"Move the comment out of the block into the prose around it: "
        f"{rules}#code-blocks."
    )
    if kind == "note":
        return prose
    if kind == "promptless":
        if text.startswith("# "):
            return prose
        return (
            "If it is a command, add the prompt its shell takes, `$ ` or `PS> `, "
            f"and continue it the way that shell does ({reach}); if it is "
            "output, tag the fence `text`."
        )
    if kind == "command" or text.startswith(("$ ", "PS> ")):
        dialect = "PS> " if text.startswith("PS> ") else "$ "
        if scan(text, Shell(dialect))[3] < len(text):
            return prose
        if len(text.rstrip(" \\`").split()) < 2:
            # One token has nowhere to split.
            return advice
        return f"Split a wide command the way its shell continues: {reach}."
    if kind == "doc":
        marker = GO_DOC if GO_DOC.match(finding.text) else DOC_LINE
        text = marker.sub("", finding.text, count=1).lstrip()
    # A doctest comment sits behind its prompt. A session line without one is
    # heredoc or other data, where # starts no comment.
    doctest = DOCTEST.match(text) if kind in ("doc", "session") else None
    text = text[doctest.end() :] if doctest else text
    commented = kind in ("", "source", "doc", "script") or bool(doctest)
    # Markdown blocks and doc-comment fences can be copies of a source file,
    # and a source file can be the original a block copies.
    copied = (
        " In a block copied from a source file, fix the source, then follow the "
        f"copy step that {rules}#in-this-repository gives."
        if kind in ("", "doc", "script")
        else " If a Markdown block copies this file, re-copy it as "
        f"{rules}#in-this-repository says."
        if kind == "source"
        else ""
    )
    if commented and text.startswith(COMMENTS):
        if MARKER.match(text.split(None, 1)[1] if " " in text else ""):
            return kept_whole(rules) + ": add this one to [[allow]] with its reason."
        # Width says comments wrap at 80; What never breaks keeps compared
        # output and marker lines whole.
        return (
            f"Wrap the comment at 80 ({rules}#width); compared output and marker "
            f"lines stay whole ({rules}#what-never-breaks).{copied}"
        )
    # A marker after the code it labels, such as `name();  // → demo`, keeps
    # its line whole too.
    trailing = TRAILING.search(text) if commented else None
    if trailing and MARKER.match(trailing["body"]):
        return (
            f"Keep the code and its marker on one line ({rules}#what-never-breaks): "
            f"shorten the code before the marker ({reach}); add it to [[allow]] only "
            "if it still runs past 80."
        )
    # A script line is a shell command, which breaks at its continuation.
    script = kind == "script" or (kind == "source" and finding.path.endswith(SCRIPTS))
    if script and len(text.rstrip(" \\`").split()) > 1:
        paste = (
            " A command a reader pastes goes in a `console` fence with its prompt "
            f"({rules}#code-blocks)."
            if kind == "script"
            else ""
        )
        return (
            f"{advice} If it is one command, it may instead continue the way its "
            f"shell does.{paste}{copied}"
        )
    if kind == "source":
        return (
            f"If the port block names a formatter for this file, run it. {advice}"
            + copied
        )
    return advice + copied


# A line edited in place keeps most of its text; a stale entry and a wide line
# that share less are a deleted allowed line and a new wide one.
SIMILAR = 0.6


def resemblance(finding: Finding, entry: dict[str, t.Any]) -> float:
    """Return how alike a wide line and a stale entry's line are, 0 to 1.

    >>> line = Finding("a.md", 1, 90, 80, "print(totals, values)")
    >>> round(resemblance(line, {"line": "print(total, values)"}), 2)
    0.98
    """
    return alike(finding.text, entry["line"])


def alike(one: str, other: str) -> float:
    """Return how alike two lines are, 0 to 1.

    >>> alike("abcd", "abce")
    0.75
    """
    import difflib

    return difflib.SequenceMatcher(None, one, other).ratio()


def edit_pairs(
    findings: list[Finding],
    stale: list[dict[str, t.Any]],
    bad_path: str | None,
    shortened: list[dict[str, t.Any]] | None = None,
) -> list[tuple[Finding, dict[str, t.Any]]]:
    """Pair stale entries with the wide lines that kept most of their text.

    Each stale entry and each wide line joins at most one pair, closest
    first, so two allowed lines edited in one file make two pairs; the rest
    of the wide lines are new.

    >>> stale = [{"path": "a.md", "line": "alpha(" + "x" * 80 + ")"}]
    >>> stale.append({"path": "a.md", "line": "beta(" + "y" * 80 + ")"})
    >>> one = Finding("a.md", 3, 90, 80, "alpha(" + "x" * 82 + ")")
    >>> two = Finding("a.md", 7, 90, 80, "beta(" + "y" * 83 + ")")
    >>> new = Finding("a.md", 9, 90, 80, "z" * 90)
    >>> pairs = edit_pairs([two, new, one], stale, None)
    >>> [(f.number, e["line"][:4]) for f, e in pairs]
    [(7, 'beta'), (3, 'alph')]
    >>> edit_pairs([one], stale, "a.md")
    []
    >>> edit_pairs([one], stale, None, shortened=stale)
    []
    """
    scored = sorted(
        (
            (resemblance(f, e), i, j)
            for i, f in enumerate(findings)
            for j, e in enumerate(stale)
            if f.path == e["path"] and f.path != bad_path and e not in (shortened or [])
        ),
        reverse=True,
    )
    pairs, taken_lines, taken_entries = [], set(), set()
    for score, i, j in scored:
        if score < SIMILAR:
            break
        if i in taken_lines or j in taken_entries:
            continue
        taken_lines.add(i)
        taken_entries.add(j)
        pairs.append((i, findings[i], stale[j]))
    return [(finding, entry) for _, finding, entry in sorted(pairs, key=lambda p: p[0])]


def edited_finding(
    findings: list[Finding], stale: list[dict[str, t.Any]], bad_path: str | None
) -> Finding | None:
    """Return the first wide line that is an edited allowed line, if any.

    >>> stale = [{"path": "a.md", "line": "print(total, " + "x" * 80 + ")"}]
    >>> new = Finding("a.md", 2, 90, 80, "y" * 90)
    >>> edit = Finding("a.md", 9, 95, 80, "print(totals, " + "x" * 80 + ")")
    >>> edited_finding([new, edit], stale, None).number
    9
    >>> edited_finding([new, edit], stale, "a.md") is None
    True
    >>> far = Finding("a.md", 3, 92, 80, "print(total, " + "y" * 20 + "x" * 60 + ")")
    >>> edited_finding([far, edit], stale, None).number
    9
    """
    pairs = edit_pairs(findings, stale, bad_path)
    return pairs[0][0] if pairs else None


def shortened_entries(
    root: pathlib.Path,
    stale: list[dict[str, t.Any]],
    width: int,
    tab_width: int,
) -> list[dict[str, t.Any]]:
    """Return stale entries whose line was shortened to fit since the last commit.

    Such an entry's file holds a line that fits, resembles the entry and is
    not in the committed file. A wide line that also resembles the entry is
    then new, not the allowed line edited, so it gets an entry of its own.
    """
    found = []
    for entry in stale:
        path = str(entry["path"])
        shown = subprocess.run(
            ["git", "-C", str(root), "show", f"HEAD:{path}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if shown.returncode != 0:
            continue
        before = {line.rstrip() for line in shown.stdout.splitlines()}
        if any(
            line not in before
            and columns(line.expandtabs(tab_width)) <= width
            and alike(line, str(entry["line"])) >= SIMILAR
            for line in source_lines(root, entry)
        ):
            found.append(entry)
    return found


def source_lines(root: pathlib.Path, entry: dict[str, t.Any]) -> set[str]:
    """Return the stripped lines of an allow entry's file, or none if unreadable."""
    try:
        text = (root / str(entry["path"])).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    return {line.rstrip() for line in text.splitlines()}


def entry_name(entry: dict[str, t.Any], entries: list[dict[str, t.Any]]) -> str:
    r"""Name an allow entry by its path, and by its line when the path has two.

    >>> one = {"path": "a.md", "line": "first line"}
    >>> entry_name(one, [one]), entry_name(one, [one, {"path": "a.md", "line": "x"}])
    ('a.md', "a.md whose line begins 'first line'")
    >>> indented = {"path": "a.md", "line": "        first line"}
    >>> entry_name(indented, [indented, one])
    "a.md whose line begins 'first line'"
    >>> long = {"path": "a.md", "line": "print(total, first + second + third + fourth)"}
    >>> entry_name(long, [long, one])
    "a.md whose line begins 'print(total, first +'"
    >>> path = {"path": "a.ps1", "line": r"C:\Users\me\AppData\Local\Temp\run.ps1"}
    >>> entry_name(path, [path, {"path": "a.ps1", "line": "x"}])
    "a.ps1 whose line begins 'C:\\Users\\me\\AppData\\Local\\Temp'"
    """
    if sum(e.get("path") == entry["path"] for e in entries) < 2:
        return str(entry["path"])
    text = entry["line"].strip()
    if len(text) > 32:
        # Cut at a space, or else before a backslash, so the quoted start
        # never ends inside an escape.
        space, slash = text.find(" ", 20), text.rfind("\\", 20, 33)
        if 0 < space <= 40:
            text = text[:space]
        else:
            text = text[:slash].rstrip("\\") if slash > 0 else text[:32]
    return f"{entry['path']} whose line begins {quoted(text)}"


def quoted(text: str) -> str:
    r"""Return a line in single quotes, as a TOML literal string writes it.

    A line that holds a single quote falls back to an escaped basic string.

    >>> print(quoted(r'"C:\Windows"'), quoted("it's"))
    '"C:\Windows"' "it's"
    """
    return f"'{text}'" if "'" not in text else literal(text)


def ceiling_hints(
    findings: list[Finding],
    stale: list[dict[str, t.Any]],
    count: int,
    bad_path: str | None = None,
    hidden: list[dict[str, t.Any]] | None = None,
    entries: list[dict[str, t.Any]] | None = None,
    shortened: list[dict[str, t.Any]] | None = None,
) -> list[str]:
    r"""Return what to change in the allow list after a failed run.

    A stale entry in a file that also has a wide line is an edited allowed
    line, so its entry takes the new text. A stale entry for ``bad_path``,
    the WRITING.md whose Bad example now fits, asks for a wide Bad line
    again. Every other stale entry goes, and the last line gives the
    ceiling all of that leaves.

    >>> wide = Finding("a.md", 3, 90, 80, "x" * 90)
    >>> ceiling_hints([wide], [], 1)
    ['Set allow_ceiling to 1 plus one for each line you add to [[allow]].']
    >>> edited = {"path": "a.md", "line": "x" * 88}
    >>> for hint in ceiling_hints([wide], [edited], 1):
    ...     print(hint)
    a.md: an allowed line changed; put its new text in the stale entry.
    allow_ceiling stays 1.
    >>> gone = {"path": "b.md", "line": "old"}
    >>> for hint in ceiling_hints([wide], [edited, gone], 2):
    ...     print(hint)
    a.md: an allowed line changed; put its new text in the stale entry.
    Delete the stale allow entry for b.md.
    Lower allow_ceiling to 1.
    >>> kept = {"path": "b.md", "line": "kept"}
    >>> ceiling_hints([], [gone], 2, entries=[gone, kept])[0]
    "Delete the stale allow entry for b.md whose line begins 'old'."
    >>> second = Finding("a.md", 5, 88, 80, "z" * 88)
    >>> ceiling_hints([wide, second], [edited], 1)[-1]
    'Set allow_ceiling to 1 plus one for each line you add to [[allow]].'
    >>> other = Finding("c.md", 7, 85, 80, "y" * 85)
    >>> for hint in ceiling_hints([wide, other], [edited], 1):
    ...     print(hint)
    a.md: an allowed line changed; put its new text in the stale entry.
    Set allow_ceiling to 1 plus one for each line you add to [[allow]].
    >>> both = [edited, {"path": "a.md", "line": "y" * 88}]
    >>> lines = [wide, Finding("a.md", 5, 90, 80, "y" * 90)]
    >>> for hint in ceiling_hints(lines, both, 2):
    ...     print(hint)
    a.md: an allowed line changed; put its new text in the stale entry.
    a.md: an allowed line changed; put its new text in the stale entry.
    allow_ceiling stays 2.
    >>> kept = {"path": "a.md", "line": "x" * 90}
    >>> for hint in ceiling_hints([], [kept], 1, hidden=[kept]):
    ...     print(hint.split(";")[0])
    a.md: the allowed line is still there but the check no longer reads it as wide
    allow_ceiling stays 1.
    >>> unrelated = {"path": "a.md", "line": "old"}
    >>> for hint in ceiling_hints([wide], [unrelated], 1):
    ...     print(hint)
    Delete the stale allow entry for a.md.
    Set allow_ceiling to 0 plus one for each line you add to [[allow]].
    >>> bad = {"path": "WRITING.md", "line": "x" * 90}
    >>> for hint in ceiling_hints([], [bad], 1, "WRITING.md"):
    ...     print(hint)
    WRITING.md: restore a Bad example past 80; its [[allow]] entry quotes it.
    allow_ceiling stays 1.
    >>> other = Finding("WRITING.md", 9, 85, 80, "x" * 85)
    >>> for hint in ceiling_hints([other], [bad], 1, "WRITING.md"):
    ...     print(hint)
    WRITING.md: restore a Bad example past 80; its [[allow]] entry quotes it.
    Set allow_ceiling to 1 plus one for each line you add to [[allow]].
    """
    pairs = edit_pairs(findings, stale, bad_path, shortened)
    edited = [entry for _, entry in pairs]
    hints = [
        f"{entry['path']}: an allowed line changed; put its new text in the "
        "stale entry."
        for entry in edited
    ]
    restored = [entry for entry in stale if entry["path"] == bad_path]
    hints += [
        f"{bad_path}: restore a Bad example past 80; its [[allow]] entry quotes it."
    ] * bool(restored)
    # An allowed line still in its file was hidden by a config change, not
    # fixed: deleting its entry would only weaken the gate.
    hidden = [entry for entry in hidden or [] if entry in stale]
    hints += [
        f"{entry_name(e, entries or stale)}: the allowed line is still there but "
        "the check no longer reads it as wide; undo the change that hid it: a "
        "glob, [[exclude]] or tab_width edit, or a fence tag or comment marker "
        "around the line."
        for e in hidden
    ]
    gone = [e for e in stale if e not in edited + restored + hidden]
    hints += [
        f"Delete the stale allow entry for {entry_name(e, entries or stale)}."
        for e in gone
    ]
    target = count - len(gone)
    # Every wide line not paired with a stale entry is new.
    if len(findings) > len(pairs):
        hints.append(
            f"Set allow_ceiling to {target} plus one for each line you add "
            "to [[allow]]."
        )
    elif target == count:
        hints.append(f"allow_ceiling stays {count}.")
    else:
        hints.append(f"Lower allow_ceiling to {target}.")
    return hints


def digests(root: pathlib.Path) -> list[str]:
    """Return ``checker <sha256>`` and ``shared <sha256>`` lines.

    The shared digest covers the text between the markers in WRITING.md;
    ``shared missing`` means no WRITING.md carries them.
    """
    checker = hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest()
    shared = "missing"
    writing = writing_path(root)
    if writing is not None:
        match = SHARED.search(writing.read_text(encoding="utf-8"))
        if match:
            shared = hashlib.sha256(match["body"].encode()).hexdigest()
    return [f"checker {checker}", f"shared {shared}"]


def digest_problems(root: pathlib.Path, config: dict[str, t.Any]) -> list[str]:
    """Return digests that differ from the ones the configuration records.

    Each message names the file that changed. Both files are the same in
    every port, so an intended change goes to all of them; an edit meant for
    one repository is undone instead.
    """
    actual = dict(line.split(" ", 1) for line in digests(root))
    here, top = pathlib.Path(__file__).resolve(), root.resolve()
    script = here.relative_to(top) if here.is_relative_to(top) else here.name
    writing = writing_file(root)
    shared = writing.relative_to(root).as_posix() if writing else "WRITING.md"
    where = {"checker": script, "shared": shared}
    names = {"checker": "this checker", "shared": "the shared section"}
    undo = {
        "checker": f"it (`git checkout -- {script}`, or a copy from another port)",
        "shared": (
            "the text between the shared markers, copied from "
            f"`git show HEAD:{shared}` so port-block edits stay, or from another "
            "port once the edit is committed"
        ),
    }
    # A digest written below a [[...]] header or misspelled is reported as
    # an unknown key already.
    nested = {
        key
        for table in TABLE_KEYS
        for entry in config.get(table, [])
        if isinstance(entry, dict)
        for key in entry
    } | {meant(key) for key in set(config) - KEYS}
    missing = [
        f"{CONFIG}: {name}_digest is missing; run `python3 {script} --digest` "
        f"and set {name}_digest to the {name} value it prints"
        for name in ("checker", "shared")
        if name + "_digest" not in config and name + "_digest" not in nested
    ]
    return missing + [
        f"{where[name]}: {names[name]} has digest {actual[name][:12]}, but "
        f"{name}_digest in {CONFIG} records {config[name + '_digest'][:12]}.\n"
        f"  To undo an edit meant for this repository only, restore {undo[name]}.\n"
        "  To change it everywhere, change libtmux/docs and each repository "
        f"listed in {PORTS}, which also names where each keeps this checker; "
        "run each copy with `--digest` and set checker_digest and "
        "shared_digest to the values it prints."
        for name in ("checker", "shared")
        if name + "_digest" in config
        and actual[name] not in (config[name + "_digest"], "missing")
    ]


def self_test() -> int:
    """Run the doctests above, plus planted failures and clean controls."""
    import contextlib
    import doctest
    import io
    import tempfile

    failures, _ = doctest.testmod(sys.modules[__name__])

    def expect(condition: bool, message: str) -> None:
        nonlocal failures
        if not condition:
            print(f"self-test: {message}", file=sys.stderr)
            failures += 1

    with tempfile.TemporaryDirectory() as scratch:
        root = pathlib.Path(scratch)
        wide = "let total = " + " + ".join(["value"] * 12) + ";"
        (root / "README.md").write_text(f"```rust\n{wide}\n```\n")
        config: dict[str, t.Any] = {"width": 60, "markdown": ["README.md"]}
        planted, _ = check(root, config, ["README.md"])
        expect(len(planted) == 1, "a planted wide line was not reported")
        if planted:
            pasted = tomllib.loads(allow_hint(planted[0]))["allow"][0]
            expect(pasted["line"] == wide, "the allow hint does not round-trip")
        excluded = dict(config, exclude=[{"glob": "README.md", "reason": "r"}])
        expect(not check(root, excluded, ["README.md"])[0], "an exclusion was read")
        config["allow"] = [{"path": "README.md", "line": wide, "reason": "test"}]
        clean, stale = check(root, config, ["README.md"])
        expect(not clean and not stale, "an allowed line was reported")
        url = "https://example.com/" + "x" * 80
        hidden = ">>> setup = " + "x" * 70 + "  # doctest: +HIDE"
        (root / "skip.md").write_text(f"```\n{url}\n```\n```python\n{hidden}\n```\n")
        skipped, _ = check(root, {"width": 80, "markdown": ["skip.md"]}, ["skip.md"])
        expect(not skipped, "a URL line or a hidden doctest line was reported")
        body = "x" * 90
        (root / "here.md").write_text(
            f"```console\n$ cat <<EOF\n... a line\n{body}\nEOF\n```\n"
        )
        here, _ = check(root, {"width": 80, "markdown": ["here.md"]}, ["here.md"])
        expect(
            [f.text for f in here] == [body],
            "a heredoc line after a ... line was read as output",
        )
        flag = "    -DCMAKE_BUILD_TYPE=Release -DCMAKE_TOOLCHAIN_FILE=" + "x" * 40
        (root / "flag.md").write_text(f"```console\n$ cmake \\\n{flag}\n```\n")
        continued, _ = check(root, {"width": 80, "markdown": ["flag.md"]}, ["flag.md"])
        expect(
            len(continued) == 1 and fix_advice(continued[0], "W").startswith("Split"),
            "a wide continuation line was not given the command advice",
        )
        (root / "prog.py").write_text("total = " + "x" * 80 + "\n")
        program, _ = check(root, {"width": 80, "sources": ["prog.py"]}, ["prog.py"])
        expect(
            len(program) == 1 and "copied" not in fix_advice(program[0], "W"),
            "a wide line in an example program was told to edit a copied block",
        )
        doc = "/// ```\n/// let total = " + "x" * 80 + ";\n/// ```\nfn f() {}\n"
        (root / "doc.rs").write_text(doc)
        coded, _ = check(root, {"width": 80, "doc_comments": ["doc.rs"]}, ["doc.rs"])
        expect(
            len(coded) == 1 and fix_advice(coded[0], "W").startswith("Fix a wide"),
            "a wide line of doc-comment code was given the comment advice",
        )
        (root / "bare.md").write_text("```console\ncargo test " + "x" * 80 + "\n```\n")
        bare, _ = check(root, {"width": 80, "markdown": ["bare.md"]}, ["bare.md"])
        expect(
            len(bare) == 1
            and fix_advice(bare[0], "W").startswith("If it is a command, add the"),
            "a wide line in a promptless console fence was not told to add a prompt",
        )
        mixed = "```console\n$ ls `\n  -l\n```\n```console\nPS> dir `\n  -x\n```\n"
        (root / "mixed.md").write_text(mixed)
        mixed_problems = prompt_problems(root, {"markdown": ["mixed.md"]}, ["mixed.md"])
        expect(
            [p.split(":")[1] for p in mixed_problems] == ["2"],
            "a `$ ` command continued with a backtick passed, or a PS> one failed",
        )
        (root / "page.rst").write_text(".. code-block:: sh\n\n   " + "x" * 81 + "\n")
        rst, _ = check(root, {"width": 80, "markdown": ["page.rst"]}, ["page.rst"])
        expect(len(rst) == 1, "a wide line in a reST code block passed")
        config["allow"].append({"path": "README.md", "line": "gone", "reason": "x"})
        _, stale = check(root, config, ["README.md"])
        expect(len(stale) == 1, "a stale allow entry was not reported")
        tabbed = "\t" + wide
        (root / "main.go").write_text(tabbed + "\n")
        config = {"width": 60, "sources": ["*.go"]}
        config["allow"] = [{"path": "main.go", "line": tabbed, "reason": "test"}]
        clean, stale = check(root, config, ["main.go"])
        expect(not clean and not stale, "a raw tabbed allow entry did not match")
        (root / "tab.go").write_text("\t" + "x" * 78 + "\n")
        tabbed_config = {"width": 80, "tab_width": 4, "sources": ["tab.go"]}
        expanded, _ = check(root, tabbed_config, ["tab.go"])
        expect(len(expanded) == 1, "a tab counted as one column")
        (root / "tab.go").write_text("\t" + "x" * 76 + "\n")
        expanded, _ = check(root, tabbed_config, ["tab.go"])
        expect(not expanded, "a tabbed line within 80 was reported")
        (root / "fmt.toml").write_text("edition = 1\nmax_width = 100\n")
        (root / "copy.toml").write_text("edition = 1\nmax_width = 80\n")
        pair = {"copy": "copy.toml", "root": "fmt.toml", "key": "max_width"}
        copies = {"formatter_copies": [pair]}
        expect(not copy_problems(root, copies), "a width-only copy was reported")
        wider_copies = (
            "max_width = 120",
            "max_width = 100 # was 80",
            "# max_width = 80",
            "# keep max_width = 80\nmax_width = 100",
            "max_width = 80\nmax_width = 120",
            "max_width = 80, max_width = 120",
        )
        for wider in wider_copies:
            (root / "copy.toml").write_text(f"edition = 1\n{wider}\n")
            expect(bool(copy_problems(root, copies)), f"a copy with {wider!r} passed")
        (root / "copy.toml").write_text(
            "edition = 1\nmax_width = 80, max_width = 120\n"
        )
        doubled = copy_problems(root, copies)
        expect(bool(doubled) and "2 times" in doubled[0], "a doubled width passed")
        (root / "copy.toml").write_text("edition = 1\nmax_width = 80  # was 120\n")
        expect(not copy_problems(root, copies), "a commented width was read twice")
        (root / "copy.toml").write_text(
            "edition = 1\nmax_width = 80  # the root sets max_width = 100\n"
        )
        expect(
            not copy_problems(root, copies), "a width named in a comment was counted"
        )
        (root / "copy.toml").write_text("edition = 1\nmax_width = 80\n")
        (root / "copy.toml").write_text("edition = 2\nmax_width = 80\n")
        expect(bool(copy_problems(root, copies)), "a drifted copy was not reported")
        (root / "fmt.json").write_text('{\n  "lineLength": 100, "indent": 2\n}\n')
        (root / "copy.json").write_text('{\n  "lineLength": 80, "indent": 9\n}\n')
        same_line = {"copy": "copy.json", "root": "fmt.json", "key": "lineLength"}
        expect(
            bool(copy_problems(root, {"formatter_copies": [same_line]})),
            "a setting changed on the width line passed",
        )
        (root / "copy.json").write_text('{\n  "lineLength": 80, "indent": 2\n}\n')
        expect(
            not copy_problems(root, {"formatter_copies": [same_line]}),
            "a copy differing only in its width value was reported",
        )
        expect(digests(root)[1] == "shared missing", "a missing section was digested")
        shared = "<!-- shared:examples -->\nrule\n<!-- /shared:examples -->\n"
        (root / "WRITING.md").write_text(shared)
        expect(digests(root)[1] != "shared missing", "a shared section was missed")
        headless = routing_problems(root)
        expect(
            bool(headless) and "no heading" in headless[0],
            "a shared section with no heading above passed",
        )
        checker_now = digests(root)[0].split(" ", 1)[1]
        recorded: dict[str, t.Any] = {
            "checker_digest": checker_now,
            "shared_digest": "0" * 64,
        }
        changed = digest_problems(root, recorded)
        expect(
            bool(changed) and "or from another port" in changed[0],
            "a shared-section change was missed or offered only HEAD to restore",
        )
        shared_now = digests(root)[1].split(" ", 1)[1]
        recorded = {"checker_digest": checker_now, "shared_digest": shared_now}
        expect(not digest_problems(root, recorded), "a matching digest was reported")
        below = {"path": "a", "line": "b", "reason": "r"}
        below["checker_digest"] = recorded.pop("checker_digest")
        recorded["allow"] = [below]
        expect(
            not digest_problems(root, recorded),
            "a digest below [[allow]] was also reported missing",
        )
        del recorded["allow"]
        recorded["checker_digset"] = below["checker_digest"]
        expect(
            not digest_problems(root, recorded),
            "a misspelled digest key was also reported missing",
        )
        del recorded["checker_digset"]
        expect(bool(digest_problems(root, recorded)), "a missing digest passed")
        (root / "WRITING.md").write_text("## Examples\n\n" + shared)
        alone = root / "alone" / ".github"
        alone.mkdir(parents=True)
        section = "## Examples\n\n<!-- shared:examples -->\n"
        (alone / "WRITING.md").write_text(section)
        broken = marker_problems(alone.parent)
        expect(
            bool(broken) and ".github/WRITING.md" in broken[0],
            "a missing closing marker passed or named the wrong file",
        )
        (alone / "WRITING.md").write_text(section + "x\n<!-- /shared:examples -->\n")
        expect(not marker_problems(alone.parent), "balanced markers were reported")
        body = "  echo " + "x" * 80
        loop = f"```console\n$ for x in a; do\n{body}\ndone\n{'y' * 81}\n```\n"
        (root / "loop.md").write_text(loop)
        looped, _ = check(root, {"width": 80, "markdown": ["loop.md"]}, ["loop.md"])
        expect(
            [finding.number for finding in looped] == [3],
            "a wide loop body passed, or printed output was measured",
        )
        expect(bool(routing_problems(root)), "a missing AGENTS.md link passed")
        (root / "AGENTS.md").write_text("Code examples: WRITING.md#examples\n")
        expect(bool(routing_problems(root)), "a bare anchor counted as a link")
        (root / "AGENTS.md").write_text("[Examples](docs/WRITING.md#examples)\n")
        expect(bool(routing_problems(root)), "a link to a missing file passed")
        (root / "AGENTS.md").write_text("[Examples](WRITING.md#other)\n")
        expect(bool(routing_problems(root)), "a link to the wrong heading passed")
        (root / "AGENTS.md").write_text("[Examples](WRITING.md#examples)\n")
        expect(not routing_problems(root), "a linked section was reported")
        (root / "AGENTS.md").write_text("[Examples](<WRITING.md#examples>)\n")
        expect(not routing_problems(root), "an angle-bracket link was reported")
        (root / "AGENTS.md").write_text("[Examples][ex]\n\n[ex]: WRITING.md#examples\n")
        expect(not routing_problems(root), "a reference-style link was reported")
        (root / "AGENTS.md").write_text("[Examples](/WRITING.md#examples)\n")
        expect(not routing_problems(root), "a root-relative link was reported")
        for hidden_link in (
            "- Code examples:\n\n      {}\n",
            "```\n{}\n```\n",
            "`{}`\n",
            "<!-- {} -->\n",
            "!{}\n",
            "\\{}\n",
        ):
            link = "[Examples](WRITING.md#examples)"
            (root / "AGENTS.md").write_text(hidden_link.format(link))
            expect(bool(routing_problems(root)), f"a link in {hidden_link!r} passed")
        (root / "AGENTS.md").write_text("[Examples](WRITING.md#examples)\n")
        (root / "AGENTS.md").unlink()
        gone = routing_problems(root)
        expect(
            bool(gone) and "is missing" in gone[0], "a missing AGENTS.md was unnamed"
        )
        (root / "AGENTS.md").write_text("[Examples](WRITING.md#examples)\n")
        labels = "\n".join(label + " x" for label in PORT_LABELS)
        wide = "```text\n" + "x" * 81 + "\n```"
        head = f"### In this repository\n\n{labels}\n\n"
        block = head + f"Bad, over 80:\n\n{wide}\n\nGood, x:\n"
        expect(not port_block_problems(block), "a complete port block was reported")
        twice = block + f"\nBad, over 80:\n\n{wide}\n"
        expect(bool(port_block_problems(twice)), "a second Bad example passed")
        missing = block.replace(PORT_LABELS[2], "- **Other:**")
        expect(
            bool(port_block_problems(missing)), "a port block missing a label passed"
        )
        fenced = "## Examples\n\n```sh\n# a comment\n```\n\n" + shared
        (root / "WRITING.md").write_text(fenced)
        expect(not routing_problems(root), "a fenced comment read as a heading")
        nested = tomllib.loads(
            'allow_ceiling = 0\n[[exclude]]\nglob = "a"\nreason = "r"\n'
            'doc_comments = ["a"]\n'
        )
        nested["markdown"] = ["a"]
        expect(
            any("doc_comments" in p for p in config_problems(nested, ["a"])),
            "a key nested under [[exclude]] passed",
        )
        del nested["exclude"][0]["doc_comments"]
        expect(not config_problems(nested, ["a"]), "a clean [[exclude]] was reported")
        nested["exclude"][0]["reason"] = " "
        expect(
            any("no reason" in p for p in config_problems(nested, ["a"])),
            "an exclusion without a reason passed",
        )
        table = {"exclude": {"glob": "a", "reason": "r"}}
        expect(bool(type_problems(table)), "[exclude] written as one table passed")
        typed = {"width": "80", "markdown": "**/*.md"}
        expect(len(type_problems(typed)) == 2, "a string width or glob list passed")
        listed = {"allow": [{"path": ["a"], "line": "b", "reason": "c"}]}
        expect(bool(type_problems(listed)), "a list where a string belongs passed")
        absent = {"copy": "gone.toml", "root": "fmt.toml", "key": "max_width"}
        expect(
            bool(copy_problems(root, {"formatter_copies": [absent]})),
            "a missing formatter copy passed",
        )
        expect(not type_problems({"width": 80, "markdown": ["a"]}), "good types failed")
        misnamed: dict[str, t.Any] = {
            "markdown": ["README.md"],
            "exclude": [{"path": "README.md", "reason": "r"}],
            "allow": [{"file": "README.md", "line": wide, "reason": "r"}],
            "formatter_copies": [{"copy": "copy.toml", "root": "fmt.toml"}],
            "allow_ceiling": 1,
        }
        found = " ".join(config_problems(misnamed, ["README.md"]))
        expect(
            all(f"has no {key}" in found for key in ("glob", "path", "key")),
            "an entry missing a key the check reads passed",
        )
        try:
            check(root, misnamed, ["README.md"])
            copy_problems(root, misnamed)
        except KeyError as error:
            expect(False, f"an entry missing {error} crashed the check")
        entry = {"path": "a", "line": "b", "reason": "c"}
        ceiling: dict[str, t.Any] = {"allow": [entry, entry], "allow_ceiling": 1}
        grown = config_problems(ceiling, ["a"])
        expect(
            bool(grown) and "delete the new entry" in grown[0],
            "a grown allow list passed or was not told to delete the new entry",
        )
        ceiling = {"allow": [entry], "allow_ceiling": 2}
        expect(bool(config_problems(ceiling, ["a"])), "a shrunk list kept its ceiling")
        ceiling = {"allow": [entry], "allow_ceiling": 1}
        expect(not config_problems(ceiling, ["a"]), "an exact ceiling was reported")
    with tempfile.TemporaryDirectory() as scratch:
        top = pathlib.Path(scratch)
        git = ["git", "-C", scratch, "-c", "init.defaultBranch=main"]
        subprocess.run([*git, "init", "-q"], check=True)
        (top / ".github").mkdir()
        (top / "README.md").write_text("x\n")
        subprocess.run([*git, "add", "README.md"], check=True)
        (top / "LINKED.md").symlink_to("README.md")
        subprocess.run([*git, "add", "LINKED.md"], check=True)
        expect(
            tracked_files(top) == ["README.md"],
            "a tracked symbolic link was read beside its target",
        )

        def run(config_text: str) -> str:
            (top / CONFIG).write_text(config_text)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--root", scratch])
            expect(code == 1, "a broken config passed")
            return out.getvalue()

        expect(
            "fix the config first" in run('width = "80"\n'),
            "a string width reached the width pass",
        )
        expect(
            "cannot read the config" in run("width = [\n"),
            "a config that is not TOML went unreported",
        )
        misspelled = (
            'markdwn = ["*.md"]\nallow_ceiling = 1\n[[allow]]\n'
            'path = "README.md"\nline = "x"\nreason = "r"\n'
        )
        expect(
            "0 stale allow entries" in run(misspelled),
            "a misspelled glob key made an allow entry look stale",
        )
        allowed = "print(total, " + "x" * 80 + ")"
        edited = allowed.replace("total", "totals")
        (top / "README.md").write_text(f"```py\n{'y' * 90}\n{edited}\n```\n")
        config_text = (
            'markdown = ["README.md"]\nallow_ceiling = 1\n[[allow]]\n'
            f'path = "README.md"\nline = "{allowed}"\nreason = "r"\n'
        )
        advice = run(config_text)
        expect(
            advice.count(f'line = "{edited}"') == 1
            and f'[[allow]]\npath = "README.md"\nline = "{"y" * 90}"' in advice,
            "an edited allowed line was paired with another wide line, or the "
            "new wide line got no entry",
        )
        expect(
            "\nREADME.md: an allowed line changed; its entry says why it stays"
            in "\n" + advice
            and "give it an entry of its own" in advice
            and "Fix a wide line by changing the code" in advice,
            "an edited allowed line was told to change its code",
        )
        (top / "README.md").write_text(f"```go\n// Output: {'o' * 80}\n```\n")
        marked = run('markdown = ["README.md"]\nallow_ceiling = 0\n')
        expect(
            marked.split("\n[[allow]]")[0].count("[[allow]]") == 1
            and "#what-never-breaks); add the line to [[allow]]" in marked,
            "a marker line's advice named [[allow]] twice",
        )
        (top / "README.md").write_text(f"```py\nprint({'w' * 80})\n```\n")
        plain = "\n" + run('markdown = ["README.md"]\nallow_ceiling = 0\n')
        expect(
            "\nFix a wide line by changing the code" in plain
            and "\nIf no change keeps the example clear, add the line to" in plain,
            "a wide line's advice and its allow fallback were not on lines of "
            "their own",
        )
        with tempfile.TemporaryDirectory() as other:
            repo = pathlib.Path(other)
            sub = ["git", "-C", other, "-c", "user.name=t", "-c", "user.email=t@t"]
            subprocess.run([*sub, "init", "-q"], check=True)
            allowed_line = "print(total, " + "x" * 80 + ")"
            (repo / "README.md").write_text(f"```py\n{allowed_line}\n```\n")
            subprocess.run([*sub, "add", "README.md"], check=True)
            subprocess.run([*sub, "commit", "-qm", "x"], check=True)
            # The allowed line is shortened to fit, and a new wide line that
            # resembles it is added: the entry goes, the new line gets its own.
            fits = "print(total, " + "x" * 40 + ")"
            new = "print(totals, " + "x" * 80 + ")"
            (repo / "README.md").write_text(f"```py\n{fits}\n{new}\n```\n")
            (repo / ".github").mkdir()
            (repo / CONFIG).write_text(
                'markdown = ["README.md"]\nallow_ceiling = 1\n[[allow]]\n'
                f'path = "README.md"\nline = "{allowed_line}"\nreason = "r"\n'
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(["--root", other])
            told = out.getvalue()
            expect(
                "an allowed line changed" not in told
                and f"names a line shortened to fit in 80: '{allowed_line}'" in told
                and "Delete the stale allow entry for README.md." in told
                and "Set allow_ceiling to 0 plus one" in told,
                "a new wide line beside a shortened allowed line was taken for "
                "its edit",
            )
            # A short similar line already committed is not a shortening: an
            # edit to the allowed line still takes its entry.
            (repo / "README.md").write_text(f"```py\n{fits}\n{allowed_line}\n```\n")
            subprocess.run([*sub, "commit", "-qam", "y"], check=True)
            edited_line = allowed_line.replace("total", "totals")
            (repo / "README.md").write_text(f"```py\n{fits}\n{edited_line}\n```\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(["--root", other])
            expect(
                "an allowed line changed" in out.getvalue(),
                "an edited allowed line beside a committed short line lost its entry",
            )
        (top / "lib.rs").write_text("/// ```console\n/// $ ls `\n///     -l\n/// ```\n")
        subprocess.run([*git, "add", "lib.rs"], check=True)
        shells = run('doc_comments = ["lib.rs"]\nallow_ceiling = 0\n')
        expect(
            "lib.rs:2: this `$ ` command is continued with a backtick" in shells,
            "a doc-comment console fence continued the other shell's way passed",
        )
        subprocess.run([*git, "rm", "-q", "--cached", "lib.rs"], check=True)
        (top / "lib.rs").unlink()
        labelled = f"session.name();  // → {'d' * 80}"
        (top / "README.md").write_text(f"```java\n{labelled}\n```\n")
        told = run('markdown = ["README.md"]\nallow_ceiling = 0\n')
        expect(
            "Keep the code and its marker on one line" in told
            and told.split("\n[[allow]]")[0].count("[[allow]]") == 1,
            "a trailing marker line's advice named [[allow]] twice",
        )
        output = f"// Output: {'o' * 80}"
        (top / "README.md").write_text(f"```go\n{edited}\n{output}\n```\n")
        marked = run(
            'markdown = ["README.md"]\nallow_ceiling = 1\n[[allow]]\n'
            f'path = "README.md"\nline = "{allowed}"\nreason = "r"\n'
        )
        expect(
            "#what-never-breaks); add the first other wide line to [[allow]]" in marked,
            "a marker line after an edited allowed line named [[allow]] twice",
        )
        second = "print(count, " + "z" * 80 + ")"
        moved = second.replace("count", "counts")
        (top / "README.md").write_text(f"```py\n{edited}\n{moved}\n```\n")
        both = run(
            'markdown = ["README.md"]\nallow_ceiling = 2\n[[allow]]\n'
            f'path = "README.md"\nline = "{allowed}"\nreason = "r"\n'
            f'[[allow]]\npath = "README.md"\nline = "{second}"\nreason = "r"\n'
        )
        expect(
            "[[allow]]" not in both
            and f'line = "{moved}"' in both
            and "allow_ceiling stays 2" in both,
            "two allowed lines edited in one file were not both paired",
        )
        (top / "notes.md").write_text("x\n")
        subprocess.run([*git, "add", "notes.md"], check=True)
        (top / "README.md").write_text(f"```py\n{allowed}\n```\n")
        unread = run(
            'markdown = ["notes.md"]\nallow_ceiling = 1\n[[allow]]\n'
            f'path = "README.md"\nline = "{allowed}"\nreason = "r"\n'
        )
        expect(
            "no longer reads it as wide" in unread and "Delete" not in unread,
            "an allowed line a glob change hid was offered for deletion",
        )
        (top / "README.md").write_text("```py\nprint(1)\n```\n")
        fits = run(
            'markdown = ["README.md"]\nallow_ceiling = 1\n[[allow]]\n'
            'path = "README.md"\nline = "print(1)"\nreason = "r"\n'
        )
        expect(
            "Delete the stale allow entry for README.md" in fits
            and "names a line that now fits in 80" in fits
            and "no longer reads" not in fits,
            "an allowed line that now fits was not offered for deletion",
        )
        (top / "README.md").write_text(f"```py\n{allowed}\n```\n")
        (top / "examples").mkdir()
        (top / "examples" / "new.txt").write_text("x\n")
        expect(
            "examples/new.txt: untracked, under examples/ but selected by no glob; "
            '`git add` it, then add "examples/new.txt" to sources'
            in run('markdown = ["README.md"]\nallow_ceiling = 0\nwidth = 1\n'),
            "an untracked, unselected example file went unnamed",
        )
        (top / "README.md").write_text("```console\n$ ls `\n  -l\n```\n")
        expect(
            "is continued with a backtick"
            in run('markdown = ["README.md"]\nallow_ceiling = 0\n'),
            "a run left a `$ ` command continued with a backtick unreported",
        )
    print("self-test:", "failed" if failures else "ok")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    """Check the repository, or run the self-test."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--self-test", action="store_true", help="prove the checker can fail"
    )
    parser.add_argument(
        "--digest",
        action="store_true",
        help="print digests of this checker and the shared WRITING.md section",
    )
    parser.add_argument(
        "--root", type=pathlib.Path, help="repository root (default: git toplevel)"
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    root = args.root or pathlib.Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )
    if args.digest:
        for line in digests(root):
            print(line)
        return 0
    try:
        config = tomllib.loads((root / CONFIG).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        print(f"{CONFIG}: cannot read the config: {error}")
        print("1 setup problem; fix the config first.")
        return 1
    wrong = type_problems(config)
    if wrong:
        for problem in wrong:
            print(f"{CONFIG}: {problem}")
        print(f"{plural(len(wrong), 'setup problem')}; fix the config first.")
        return 1
    files = tracked_files(root)
    writing = writing_path(root)
    # Each problem names the file to change; routing problems name their own.
    setup = config_problems(config, files)
    problems = (
        [f"{CONFIG}: {problem}" for problem in setup]
        + copy_problems(root, config)
        + digest_problems(root, config)
        + marker_problems(root)
        + routing_problems(root)
    )
    new = untracked_matches(config, tracked_files(root, others=True))
    chosen = [path for path in new if selected(config, path)]
    shown = ", ".join(chosen[:3]) + (", ..." if len(chosen) > 3 else "")
    notice = (
        f"Not checked until `git add`: {plural(len(chosen), 'untracked file')} "
        f"the config selects ({shown})."
        if chosen
        else ""
    )
    # An untracked file does not fail the run, but its wide lines are shown
    # so a new example can be fixed before it is added.
    pending, _ = check(root, config, chosen) if chosen and not setup else ([], [])
    if pending:
        they = "it fails" if len(chosen) == 1 else "they fail"
        notice += f" Once added, {they} on {plural(len(pending), 'wide line')}: " + (
            "; ".join(str(finding) for finding in pending[:3])
        )
    notice = "\n".join(
        [notice] * bool(notice)
        + [
            f"{path}: untracked, under examples/ but selected by no glob; `git add` "
            "it, then " + select_advice(path)
            for path in new
            if path not in chosen
        ]
    )
    bad_path = None
    if writing:
        where = writing.relative_to(root).as_posix()
        text = writing.read_text(encoding="utf-8")
        block = port_block_problems(text)
        problems += [f"{where}: {problem}" for problem in block]
        bad_path = where if any("Bad example fits" in p for p in block) else None
    # A config problem such as a misspelled glob key would make allow entries
    # look stale, so the width pass waits until the config is right.
    findings, stale = check(root, config, files) if not setup else ([], [])
    problems += prompt_problems(root, config, files) if not setup else []
    annotate = os.environ.get("GITHUB_ACTIONS") == "true"
    for problem in problems:
        print(problem)
    for finding in findings:
        print(finding)
        if annotate:
            print(
                f"::error file={finding.path},line={finding.number}::"
                f"{finding.columns} columns > {finding.width}"
            )
    # A line still in its file is hidden only while it is still wide; one that
    # now fits needs its entry deleted.
    width, tab_width = config.get("width", 80), config.get("tab_width", 4)
    present = [entry for entry in stale if entry["line"] in source_lines(root, entry)]
    hidden = [
        entry
        for entry in present
        if columns(entry["line"].expandtabs(tab_width)) > width
    ]
    absent = [entry for entry in stale if entry not in present]
    shortened = shortened_entries(root, absent, width, tab_width) if absent else []
    for entry in stale:
        how = (
            "names a line the check no longer reads"
            if entry in hidden
            else f"names a line that now fits in {width}"
            if entry in present
            else f"names a line shortened to fit in {width}"
            if entry in shortened
            else "matches no line"
        )
        print(
            f"{CONFIG}: allow entry for {entry['path']} {how}: {quoted(entry['line'])}"
        )
    if problems or findings or stale:
        page = writing or writing_file(root)
        rules = page.relative_to(root).as_posix() if page else "WRITING.md"
        print(
            f"{plural(len(problems), 'problem')}, "
            f"{plural(len(findings), 'wide line')}, "
            f"{plural(len(stale), 'stale allow entry', 'stale allow entries')}."
        )
        if setup:
            print(f"The width check runs once the problems in {CONFIG} are fixed.")
        edited = ""
        # Name an entry by its line when its file has two allow entries.
        allowed = [e for e in config.get("allow", []) if isinstance(e, dict)]
        if findings:
            first = findings[0]
            many = len(findings) > 1
            pairs = edit_pairs(findings, stale, bad_path, shortened)
            if pairs:
                # An allowed line changed: its entry already says why it stays
                # whole, so it takes the new text.
                first, edited = pairs[0][0], pairs[0][0].path
                named = entry_name(pairs[0][1], allowed)
                print(
                    f"{edited}: an allowed line changed; its entry says why it stays "
                    f"whole. Put its new text in the stale entry for {named} (if the "
                    "line is new instead, give it an entry of its own):"
                )
            else:
                lead = (
                    f"The first of {len(findings)}, as an entry:"
                    if many
                    else "As an entry:"
                )
                advice = fix_advice(first, rules)
                if "[[allow]]" in advice and not advice.startswith(kept_whole(rules)):
                    # The advice already says when to allow the line.
                    print(advice)
                    print(lead)
                elif advice.startswith(kept_whole(rules)):
                    # The rule itself says to allow it; say [[allow]] once.
                    print(
                        f"{kept_whole(rules)}; add the line to [[allow]] in "
                        f"{CONFIG} with its reason. {lead}"
                    )
                else:
                    print(advice)
                    print(
                        "If no change keeps the example clear, add the line to "
                        f"[[allow]] in {CONFIG} with a reason. {lead}"
                    )
            hint = allow_hint(first)
            print(hint.splitlines()[2] if edited else hint)
            for finding, entry in pairs[1:]:
                print(f"In the stale entry for {entry_name(entry, allowed)}, put:")
                print(allow_hint(finding).splitlines()[2])
            paired = [finding for finding, _ in pairs]
            others = [finding for finding in findings if finding not in paired]
            if edited and others:
                advice = fix_advice(others[0], rules)
                if advice.startswith(kept_whole(rules)):
                    print(
                        f"{kept_whole(rules)}; add the first other wide line to "
                        f"[[allow]] in {CONFIG} with its reason:"
                    )
                else:
                    print(advice)
                    print(
                        "If no change keeps the example clear, add the first "
                        f"other wide line to [[allow]] in {CONFIG}:"
                    )
                print(allow_hint(others[0]))
        if findings or stale:
            count = len(config.get("allow", []))
            for hint in ceiling_hints(
                findings, stale, count, bad_path, hidden, allowed, shortened
            ):
                if not (edited and "an allowed line changed" in hint):
                    print(hint)
        if notice:
            print(notice)
        return 1
    read = [g for key in GLOB_KEYS for g in config.get(key, [])]
    skip = [entry["glob"] for entry in entries(config, "exclude")]
    count = sum(matches(path, read) and not matches(path, skip) for path in files)
    print(f"{count} files checked; no example is over {config.get('width', 80)}.")
    if notice:
        print(notice)
    return 0


if __name__ == "__main__":
    sys.exit(main())
