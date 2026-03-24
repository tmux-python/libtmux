#!/usr/bin/env bash
# Extract tmux command invocations from libtmux Python source
# Usage: extract-libtmux-methods.sh [libtmux-src-dir]
# Output: unique tmux command names invoked via .cmd() or as command args
#
# Searches for .cmd("command"), tmux_cmd(..., "command"), and
# args = ["command"] patterns that represent actual tmux command calls.

set -euo pipefail

LIBTMUX_DIR="${1:-$HOME/work/python/libtmux/src/libtmux}"

if [[ ! -d "$LIBTMUX_DIR" ]]; then
    echo "Error: libtmux source dir not found at $LIBTMUX_DIR" >&2
    exit 1
fi

echo "# Unique tmux commands invoked by libtmux"
{
    # Pattern 1: self.cmd("command-name", ...) or .cmd("command-name")
    grep -rn '\.cmd(' "$LIBTMUX_DIR"/*.py 2>/dev/null | \
        grep -oP '\.cmd\(\s*"([a-z]+-[a-z-]+)"' | \
        sed 's/.*"\(.*\)"/\1/'

    # Pattern 2: args/cmd = ["command-name", ...] or args/cmd += ["command-name"]
    grep -rn '\(args\|cmd\)\s*[+=]\+\s*\["[a-z]\+-' "$LIBTMUX_DIR"/*.py 2>/dev/null | \
        grep -oP '\["([a-z]+-[a-z-]+)"' | \
        tr -d '["'

    # Pattern 3: tmux_args += ("command-name",) or tmux_args = ("command-name",)
    grep -rn 'tmux_args\s*[+=]\+.*"[a-z]\+-' "$LIBTMUX_DIR"/*.py 2>/dev/null | \
        grep -oP '"([a-z]+-[a-z-]+)"' | \
        tr -d '"'

    # Pattern 4: string literals in command-building contexts (hooks.py, options.py, common.py)
    # Match lines with command strings used in args lists or cmd() calls
    grep -rn '^\s*"[a-z]\+-[a-z-]*",' "$LIBTMUX_DIR"/*.py 2>/dev/null | \
        grep -oP '"([a-z]+-[a-z-]+)"' | \
        tr -d '"' | \
        grep -E '^(capture|kill|move|select|set|show|split|clear)-'
} | sort -u

echo ""
echo "# Detailed: command|file:line"
grep -rn '\.cmd(\|args\s*[+=]\+\s*\["\|tmux_args\s*[+=]' "$LIBTMUX_DIR"/*.py 2>/dev/null | \
    perl -ne 'if (/^(.+?):(\d+):.*"([a-z]+-[a-z]+-?[a-z]*)"/ && $3 =~ /^(attach|break|capture|choose|clear|clock|command|confirm|copy|customize|delete|detach|display|find|has|if|join|kill|last|link|list|load|lock|move|new|next|paste|pipe|previous|refresh|rename|resize|respawn|rotate|run|save|select|send|server|set|show|source|split|start|suspend|swap|switch|unbind|unlink|wait)-/) { print "$3|$1:$2\n" }' | \
    sort
