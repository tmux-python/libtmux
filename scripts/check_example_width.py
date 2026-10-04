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

It checks code in ``markdown`` files (fences, indented blocks outside
lists and ``<pre>`` blocks; literal and ``code-block`` blocks in a
``.rst`` one), every line of ``sources`` files, and the code inside doc
comments of ``doc_comments`` files: fences, ``>>>`` doctests, and reST
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
a tab advances to the next multiple of ``tab_width`` (default 4).

``width`` must be 80, the shared rule. Every key must be known, at the
top level and inside each ``[[...]]`` entry, so a key written below a
table header cannot be swallowed by that entry; every entry must hold
the keys the check reads, and every value must have the type it reads.
Every glob must match a tracked file and every exclusion a checked one;
every exclusion and allow entry must give a reason, and every allow
entry must match a line. Every tracked file under a directory named
``examples`` must be checked or excluded, so a new example file cannot
go unread. ``allow_ceiling`` must equal the number of allow entries, so
the list grows only through a reviewed change to that number and a fixed
line must lower it. Each formatter copy must equal its root file except
for the lines naming ``key``, and the digests of this checker and of
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
BLOCK_OPEN = re.compile(r"<pre>\s*\{@code|<code>\s*$")
BLOCK_CLOSE = re.compile(r"\}\s*</pre>|^\s*</code>")
URL = re.compile(r"^(?:(?:#+|//+!?|-+|\*|>|<!--)\s*)?<?[a-z][a-z0-9+.-]*://\S+$")
EXAMPLE_DIR = re.compile(r"(^|/)examples/", re.IGNORECASE)
HEADING = re.compile(r"^(#{1,6}) (.+)$", re.MULTILINE)
# A Markdown link target: [text](target).
LINK = re.compile(r"\]\(<?([^)\s>]+)>?\)")
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


def shell_after(line: str, state: Shell) -> Shell | None:
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
    """
    text = line.lstrip()
    if text.startswith((">>> ", "... ")):
        return None
    if state.heredoc is not None:
        if line.strip() == state.heredoc:
            state = state._replace(heredoc=None)
            return state if state.quote or state.depth else None
        return state
    for prompt in ("$ ", "PS> "):
        if text.startswith(prompt):
            state, text = Shell(dialect=prompt), text[len(prompt) :]
    # A backslash (a backtick in PowerShell) escapes the next character
    # outside single quotes, and an unquoted # starts a comment.
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
    bare = "".join(plain)
    depth = state.depth
    for segment in re.split(r"[;&|()]", bare):
        words = segment.split()
        if state.dialect == "$ " and words and words[0] in SHELL_OPEN:
            depth += 1
        if state.dialect == "$ " and words and words[0] in SHELL_CLOSE:
            depth -= 1
        depth += sum(w.endswith("{") for w in words)
        depth -= sum(w.startswith("}") for w in words)
    opened = HEREDOC.search(text)
    heredoc = opened["word"] if opened else None
    state = Shell(state.dialect, quote, heredoc, max(depth, 0))
    # A trailing \ or backtick continues the command under either prompt, so
    # a line continued the other shell's way is still measured.
    tail = text[:cut].rstrip()
    ends = escaped or tail.endswith(("\\", "`"))
    ends = ends or bare.rstrip().endswith(("|", "&&", "("))
    return state if quote or state.heredoc or state.depth or ends else None


LIST_ITEM = re.compile(r"^\s*([-*+]|\d+[.)])\s")


def indent_code(line: str) -> bool:
    """Return whether a Markdown line is indented far enough to be code."""
    return line.startswith(("    ", "\t"))


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


def markdown_lines(text: str, indented: bool = True) -> list[tuple[int, str]]:
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
    >>> page = "Before:\n\n    new Server()\n\n- item\n\n    more of the item"
    >>> [line for _, line in markdown_lines(page)]
    ['    new Server()']
    >>> [line for _, line in markdown_lines("<pre><code>run()\n</code></pre>")]
    ['<pre><code>run()', '</code></pre>']
    """
    found: list[tuple[int, str]] = []
    fence: tuple[str, str] | None = None
    first = False
    shell: Shell | None = None
    blank, in_list, in_block, in_pre = True, False, False, False
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        match = FENCE.match(line)
        if fence is None and match:
            fence = (match["mark"], fence_tag(match["info"]))
            if fence[1] in PYTHON_TAGS and doctest_first(lines[number:], fence[0]):
                fence = (fence[0], "pycon")
            if fence[1] in SESSION_TAGS and not has_prompt(lines[number:], fence[0]):
                fence = (fence[0], "sh")
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
            elif LIST_ITEM.match(line):
                in_list, in_block = True, False
            elif indent_code(line) and not in_list and (blank or in_block):
                found.append((number, line))
                in_block = True
            else:
                in_list = in_list and line.startswith((" ", "\t"))
                in_block = False
            blank = False
            continue
        if match and match["mark"].startswith(fence[0]) and not match["info"].strip():
            fence = None
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
        if tag in SESSION_TAGS:
            prompt = line.lstrip().startswith(PROMPTS)
            if not (prompt or shell):
                continue
            shell = shell_after(line, shell or Shell())
        found.append((number, line))
    return found


def prompt_mismatches(text: str) -> list[tuple[int, str]]:
    r"""Return lines that continue a command the other shell's way.

    A ``$ `` command continues with ``\``, a ``PS> `` one with a backtick.

    >>> prompt_mismatches("```console\n$ ls `\n  -l\nPS> dir \\\n```")
    [(2, '$ '), (4, 'PS> ')]
    >>> prompt_mismatches("```console\n$ ls \\\n  -l\nPS> dir `\n  -x\n```")
    []
    >>> prompt_mismatches("```console\n$ ls\n```\n```go\nName string `json`\n```")
    []
    """
    found: list[tuple[int, str]] = []
    state: Shell | None = None
    last = 0
    for number, line in markdown_lines(text):
        stripped = line.lstrip()
        if stripped.startswith(("$ ", "PS> ")):
            state = Shell(dialect=stripped[: stripped.index(" ") + 1])
        elif state is None or number != last + 1:
            state = None
            continue
        dialect, last = state.dialect, number
        end = line.rstrip()
        if (dialect == "$ " and end.endswith("`")) or (
            dialect == "PS> " and end.endswith(" \\")
        ):
            found.append((number, dialect))
        state = shell_after(line, state)
    return found


def prompt_problems(
    root: pathlib.Path, config: dict[str, t.Any], files: list[str]
) -> list[str]:
    """Return console commands in checked Markdown continued the wrong way."""
    skip = [entry["glob"] for entry in entries(config, "exclude")]
    fix = {
        "$ ": "this `$ ` command is continued with a backtick; end the line with "
        "`\\` instead, or use a `PS> ` prompt for a PowerShell command",
        "PS> ": "this `PS> ` command is continued with `\\`; end the line with a "
        "backtick instead",
    }
    problems = []
    for path in files:
        if not matches(path, config.get("markdown", [])) or matches(path, skip):
            continue
        if path.endswith(".rst"):
            continue
        try:
            text = (root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        problems += [f"{path}:{n}: {fix[d]}" for n, d in prompt_mismatches(text)]
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


def doc_comment_lines(text: str, suffix: str) -> list[tuple[int, str]]:
    r"""Return code inside doc comments: fences and ``{@code}``/``<code>``.

    Python docstrings contribute their doctest lines and reST literal
    blocks, Go doc comments their tab-indented code blocks, and Julia
    docstrings their fences. A fence
    tagged as output is skipped, and a plain ``//`` comment is not a doc
    comment.

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
    >>> jl = "    f(x)\n\nRun it:\n\n```julia\nf(1)\n```"
    >>> [line for _, line in doc_comment_lines(jl, ".jl")]
    ['f(1)']
    """
    if suffix == ".jl":
        return markdown_lines(text, indented=False)
    if suffix == ".py":
        doctests = [
            (number, line)
            for number, line in enumerate(text.splitlines(), 1)
            if line.lstrip().startswith((">>> ", "... "))
        ]
        return sorted(set(doctests + rest_block_lines(text)))
    found: list[tuple[int, str]] = []
    inside = False
    output = False
    for number, line in enumerate(text.splitlines(), 1):
        if suffix == ".go":
            if line.lstrip().startswith("//\t"):
                found.append((number, line))
            continue
        if BLOCK_OPEN.search(line):
            inside, output = not BLOCK_CLOSE.search(line), False
            continue
        prefix = DOC_LINE.match(line)
        if prefix is None:
            inside = False
            continue
        body = line[prefix.end() :]
        fence = FENCE.match(body)
        if fence:
            inside = not inside
            output = inside and fence_tag(fence["info"]) in OUTPUT_TAGS
            continue
        if inside and BLOCK_CLOSE.search(body):
            inside = False
            continue
        hidden = suffix == ".rs" and (body == "#" or body.startswith("# "))
        if inside and not output and not hidden:
            found.append((number, line))
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


def type_problems(config: dict[str, t.Any]) -> list[str]:
    """Return values whose type the check cannot use.

    >>> for problem in type_problems({"width": "80", "markdown": "**/*.md"}):
    ...     print(problem)
    width must be an integer, not '80'
    markdown must be a list of globs, not '**/*.md'
    >>> type_problems({"width": 80, "markdown": ["**/*.md"], "exclude": []})
    []
    >>> type_problems({"exclude": [{"glob": 5, "reason": "r"}]})
    ['glob in an [[exclude]] entry must be a string, not 5']
    >>> type_problems({"allow_ceiling": True})
    ['allow_ceiling must be an integer, not True']
    """
    problems = [
        f"{key} must be {name}, not {config[key]!r}"
        for key, (kind, name) in VALUE_TYPES.items()
        if key in config
        and (not isinstance(config[key], kind) or isinstance(config[key], bool))
    ]
    for key in GLOB_KEYS:
        value = config.get(key, [])
        if not isinstance(value, list) or not all(isinstance(g, str) for g in value):
            problems.append(f"{key} must be a list of globs, not {value!r}")
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
            f"{key} in an [[{table}]] entry must be a string, not {entry[key]!r}"
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

    >>> config = {"allow": [{"path": "a", "line": "b"}], "allow_ceiling": 1}
    >>> config_problems(config, ["a"])
    ["allow entry for a has no reason: 'b'"]
    >>> for problem in config_problems({"width": 100, "exclude": ["a"]}, ["a"]):
    ...     print(problem)
    an [[exclude]] entry is not a table: 'a'
    width is 100; the shared rule is 80
    allow_ceiling is missing; set it to 0, the number of allow entries
    >>> excluded = {"glob": "notes/*.md", "reason": "drafts"}
    >>> config = {"markdown": ["*.md"], "exclude": [excluded], "allow_ceiling": 0}
    >>> config_problems(config, ["a.md", "notes/b.md"])
    ['exclude glob matches no checked file: notes/*.md']
    >>> config = {"markdwn": ["**/*.md"], "exclude": [excluded], "allow_ceiling": 0}
    >>> [problem.split(";")[0] for problem in config_problems(config, ["notes/b.md"])]
    ['unknown key: markdwn']
    >>> config = {"sources": ["examples/*.go"], "allow_ceiling": 0}
    >>> files = ["examples/a.go", "examples/go.mod"]
    >>> config_problems(config, files)[0].split(";")[0]
    'examples/go.mod is under examples/ but neither checked nor excluded'
    >>> mod = {"glob": "examples/go.mod", "reason": "module file"}
    >>> config_problems(dict(config, exclude=[mod]), files)
    []
    >>> config["exclude"] = [dict(mod, doc_comments=["*.go"])]
    >>> config_problems(config, files)[0].split(";")[0]
    'unknown key in an [[exclude]] entry: doc_comments'
    >>> nested = {"exclude": [{"glob": "x", "reason": "r", "sources": ["*.go"]}]}
    >>> [p.split(";")[0] for p in config_problems(nested, ["examples/a.go"])]
    ['unknown key in an [[exclude]] entry: sources', 'allow_ceiling is missing']
    >>> config = {"allow": [{"file": "a", "line": "b", "reason": "c"}]}
    >>> config_problems(dict(config, allow_ceiling=1), ["a"])[1]
    "an [[allow]] entry has no path: {'file': 'a', 'line': 'b', 'reason': 'c'}"
    >>> pasted = {"path": "a", "line": "b", "reason": PLACEHOLDER}
    >>> config_problems({"allow": [pasted], "allow_ceiling": 1}, ["a"])[0]
    'allow entry for a keeps the placeholder reason; say why this line cannot break'
    >>> misspelled = {"markdwn": ["*.md"], "allow_ceiling": 0}
    >>> found = config_problems(misspelled, ["examples/a.md"])
    >>> [problem.split(";")[0] for problem in found]
    ['unknown key: markdwn']
    """
    entry_keys = set().union(*TABLE_KEYS.values())
    problems = [
        f"unknown key: {key}; "
        + (
            f"{key} belongs inside an [[...]] entry, below its header"
            if key in entry_keys
            else f"the config takes {', '.join(sorted(KEYS))}"
        )
        for key in sorted(set(config) - KEYS)
    ]
    for table, keys in TABLE_KEYS.items():
        for entry in config.get(table, []):
            if not isinstance(entry, dict):
                problems.append(f"an [[{table}]] entry is not a table: {entry!r}")
                continue
            problems.extend(
                f"unknown key in an [[{table}]] entry: {key}; "
                + (
                    "TOML puts every key below a [[...]] header into that "
                    "entry, so top-level keys go above the first one"
                    if key in KEYS
                    else f"an [[{table}]] entry takes {', '.join(sorted(keys))}"
                )
                for key in sorted(set(entry) - keys)
            )
            problems.extend(
                f"an [[{table}]] entry has no {key}: {entry!r}"
                for key in sorted(keys - set(entry) - {"reason"})
            )
    if config.get("width", 80) != 80:
        problems.append(f"width is {config['width']}; the shared rule is 80")
    globs = [(key, pattern) for key in GLOB_KEYS for pattern in config.get(key, [])]
    problems.extend(
        f"{key} glob matches no tracked file: {pattern}"
        for key, pattern in globs
        if not any(glob_regex(pattern).fullmatch(path) for path in files)
    )
    checked = [path for path in files if matches(path, [p for _, p in globs])]
    examples = [path for path in files if EXAMPLE_DIR.search(path)]
    # An unknown top-level key is usually a misspelled glob key, which leaves
    # files unchecked: exclusions look unused and example files look unread.
    # Report the key alone until it is fixed.
    known = not set(config) - KEYS and not any(
        isinstance(entry, dict) and set(entry) & KEYS
        for table in TABLE_KEYS
        for entry in config.get(table, [])
    )
    excluded: list[str] = []
    for entry in config.get("exclude", []):
        if not isinstance(entry, dict):
            continue
        if not str(entry.get("reason", "")).strip():
            problems.append(f"exclude entry has no reason: {entry!r}")
            continue
        if "glob" not in entry:
            continue
        excluded.append(entry["glob"])
        pattern = glob_regex(entry["glob"])
        if known and not any(pattern.fullmatch(path) for path in checked + examples):
            problems.append(f"exclude glob matches no checked file: {entry['glob']}")
    if known:
        problems.extend(
            f"{path} is under examples/ but neither checked nor excluded; add it "
            "to sources, or to [[exclude]] with a reason"
            for path in examples
            if path not in checked and not matches(path, excluded)
        )
    count = len(config.get("allow", []))
    ceiling = config.get("allow_ceiling")
    if ceiling is None:
        problems.append(
            f"allow_ceiling is missing; set it to {count}, the number of allow entries"
        )
    elif count > int(ceiling):
        problems.append(
            f"allow_ceiling {ceiling} is below the "
            f"{plural(count, 'allow entry', 'allow entries')}; shorten the "
            "new line, or raise the ceiling in a change that gives the reason"
        )
    elif count < int(ceiling):
        problems.append(
            f"allow_ceiling {ceiling} is above the "
            f"{plural(count, 'allow entry', 'allow entries')}; lower it"
        )
    problems.extend(
        f"allow entry for {entry.get('path')} has no reason: {entry.get('line')!r}"
        for entry in config.get("allow", [])
        if isinstance(entry, dict) and not str(entry.get("reason", "")).strip()
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


def copy_problems(root: pathlib.Path, config: dict[str, t.Any]) -> list[str]:
    """Return formatter copies that drifted from their root file.

    A copy may differ from its root only on lines naming the width key. A
    drifted copy is reported against its own path, the file to change.
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
            lines = (root / path).read_text(encoding="utf-8").splitlines()
            return [line for line in lines if key not in line]

        lines = (root / pair["copy"]).read_text(encoding="utf-8").splitlines()
        if not any(
            pair["key"] in line and re.search(r"\b80\b", line) for line in lines
        ):
            problems.append(
                f"{pair['copy']}: {pair['key']} is not 80; set it to 80, the "
                "width every example keeps"
            )
        if kept(pair["copy"]) != kept(pair["root"]):
            problems.append(
                f"{pair['copy']}: differs from {pair['root']} beyond {pair['key']}; "
                f"make it equal to {pair['root']} except the {pair['key']} line"
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
        if kind == "markdown" and suffix == ".rst":
            lines = rest_block_lines(text)
        elif kind == "markdown":
            lines = markdown_lines(text)
        elif kind == "doc":
            lines = doc_comment_lines(text, suffix)
        else:
            lines = list(enumerate(text.splitlines(), 1))
        for number, line in lines:
            shown = line.expandtabs(tab_width).rstrip()
            wide = columns(shown)
            if wide <= width or is_url(shown) or HIDDEN.match(shown):
                continue
            key = (path, line.rstrip())
            if key in allowed:
                used.add(key)
                continue
            findings.append(Finding(path, number, wide, width, key[1]))
    stale = [entry for entry in allow if (entry["path"], entry["line"]) not in used]
    return findings, stale


def tracked_files(root: pathlib.Path, others: bool = False) -> list[str]:
    """Return the files git tracks, as POSIX paths relative to the root.

    With ``others``, return instead the untracked files git does not ignore.
    """
    untracked = ["--others", "--exclude-standard"] if others else []
    output = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z", *untracked],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [path for path in output.split("\0") if path]


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
    route = unfenced(agents.read_text(encoding="utf-8")) if agents.is_file() else ""
    route = re.sub(r"<!--.*?-->|`[^`\n]*`", "", route, flags=re.DOTALL)
    links = LINK.findall(route)
    for target in links:
        path, _, fragment = target.partition("#")
        if fragment == anchor and (root / path).resolve() == writing.resolve():
            return []
    where = f"{writing.relative_to(root).as_posix()}#{anchor}"
    link = f"[{headings[-1]}]({where})"
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
    """
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


def edited_finding(
    findings: list[Finding], stale: list[dict[str, t.Any]], bad_path: str | None
) -> Finding | None:
    """Return the wide line that most resembles a stale entry in its file.

    An edited allowed line is a stale entry plus a wide line in the same
    file; other wide lines in that file are new.

    >>> stale = [{"path": "a.md", "line": "print(total, " + "x" * 80 + ")"}]
    >>> new = Finding("a.md", 2, 90, 80, "y" * 90)
    >>> edit = Finding("a.md", 9, 95, 80, "print(totals, " + "x" * 80 + ")")
    >>> edited_finding([new, edit], stale, None).number
    9
    >>> edited_finding([new, edit], stale, "a.md") is None
    True
    """
    import difflib

    pairs = [
        (difflib.SequenceMatcher(None, f.text, e["line"]).ratio(), i, f)
        for i, f in enumerate(findings)
        for e in stale
        if f.path == e["path"] and f.path != bad_path
    ]
    return max(pairs)[2] if pairs else None


def ceiling_hints(
    findings: list[Finding],
    stale: list[dict[str, t.Any]],
    count: int,
    bad_path: str | None = None,
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
    >>> edited = {"path": "a.md", "line": "old"}
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
    >>> other = Finding("c.md", 7, 85, 80, "y" * 85)
    >>> for hint in ceiling_hints([wide, other], [edited], 1):
    ...     print(hint)
    a.md: an allowed line changed; put its new text in the stale entry.
    Set allow_ceiling to 1 plus one for each line you add to [[allow]].
    >>> bad = {"path": "WRITING.md", "line": "x" * 90}
    >>> for hint in ceiling_hints([], [bad], 1, "WRITING.md"):
    ...     print(hint)
    WRITING.md: restore a Bad example past 80; its [[allow]] entry quotes it.
    allow_ceiling stays 1.
    >>> other = Finding("WRITING.md", 9, 85, 80, "y" * 85)
    >>> for hint in ceiling_hints([other], [bad], 1, "WRITING.md"):
    ...     print(hint)
    WRITING.md: restore a Bad example past 80; its [[allow]] entry quotes it.
    Set allow_ceiling to 1 plus one for each line you add to [[allow]].
    """
    edited = {entry["path"] for entry in stale} & {f.path for f in findings}
    edited.discard(bad_path or "")
    hints = [
        f"{path}: an allowed line changed; put its new text in the stale entry."
        for path in sorted(edited)
    ]
    restored = [entry for entry in stale if entry["path"] == bad_path]
    hints += [
        f"{bad_path}: restore a Bad example past 80; its [[allow]] entry quotes it."
    ] * bool(restored)
    gone = [e for e in stale if e["path"] not in edited and e not in restored]
    hints += [f"Delete the stale allow entry for {entry['path']}." for entry in gone]
    target = count - len(gone)
    if any(f.path not in edited for f in findings):
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
            f"`git show HEAD:{shared}` so port-block edits stay"
        ),
    }
    missing = [
        f"{CONFIG}: {name}_digest is missing; run `python3 {script} --digest` "
        f"and set {name}_digest to the {name} value it prints"
        for name in ("checker", "shared")
        if name + "_digest" not in config
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
        (root / "copy.toml").write_text("edition = 1\nmax_width = 120\n")
        expect(bool(copy_problems(root, copies)), "a copy wider than 80 passed")
        (root / "copy.toml").write_text("edition = 1\nmax_width = 80\n")
        (root / "copy.toml").write_text("edition = 2\nmax_width = 80\n")
        expect(bool(copy_problems(root, copies)), "a drifted copy was not reported")
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
        recorded = {"checker_digest": checker_now, "shared_digest": "0" * 64}
        expect(bool(digest_problems(root, recorded)), "a digest change was missed")
        shared_now = digests(root)[1].split(" ", 1)[1]
        recorded = {"checker_digest": checker_now, "shared_digest": shared_now}
        expect(not digest_problems(root, recorded), "a matching digest was reported")
        del recorded["checker_digest"]
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
        for hidden_link in ("```\n{}\n```\n", "`{}`\n", "<!-- {} -->\n"):
            link = "[Examples](WRITING.md#examples)"
            (root / "AGENTS.md").write_text(hidden_link.format(link))
            expect(bool(routing_problems(root)), f"a link in {hidden_link!r} passed")
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
        expect(bool(config_problems(ceiling, ["a"])), "a grown allow list passed")
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
            f'line = "{edited}"' in advice and f'line = "{"y" * 90}"' not in advice,
            "an edited allowed line was paired with another wide line",
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
            f"{path}: untracked, under examples/ but selected by no glob; add it "
            "to sources or to [[exclude]] with a reason"
            for path in new
            if path not in chosen
        ]
    )
    bad_path = writing_rel = None
    if writing:
        where = writing_rel = writing.relative_to(root).as_posix()
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
    for entry in stale:
        print(
            f"{CONFIG}: allow entry for {entry['path']} matches no line: "
            f"{entry['line']!r}"
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
        if findings:
            first = findings[0]
            many = len(findings) > 1
            changed = edited_finding(findings, stale, bad_path)
            if changed is not None:
                # An allowed line changed: its entry takes the new text.
                first, edited = changed, changed.path
                advice = f"replace the line in the stale entry for {edited} with:"
                if edited == writing_rel:
                    # The port block's Bad example must stay wide.
                    advice = (
                        "or if the Bad example in the port block changed, " + advice
                    )
            else:
                advice = f"add the line to [[allow]] in {CONFIG} with a reason. " + (
                    f"The first of {len(findings)}, as an entry:"
                    if many
                    else "As an entry:"
                )
            print(
                "Fix a wide line by changing the code, not the line breaks: "
                f"{rules}#reaching-80. If no change keeps the example clear, " + advice
            )
            hint = allow_hint(first)
            print(hint.splitlines()[2] if edited else hint)
        if findings or stale:
            count = len(config.get("allow", []))
            for hint in ceiling_hints(findings, stale, count, bad_path):
                if not (edited and hint.startswith(f"{edited}: ")):
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
