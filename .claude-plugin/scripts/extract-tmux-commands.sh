#!/usr/bin/env bash
# Extract tmux command entries from cmd-*.c files
# Usage: extract-tmux-commands.sh [tmux-source-dir]
# Output: command_name|alias|getopt_string|target_type
#
# Parses cmd_entry structs to enumerate all tmux commands with their
# flags and target types.

set -euo pipefail

TMUX_DIR="${1:-$HOME/study/c/tmux}"

if [[ ! -d "$TMUX_DIR" ]]; then
    echo "Error: tmux source dir not found at $TMUX_DIR" >&2
    exit 1
fi

# Process each cmd-*.c file (skip internal files)
for f in "$TMUX_DIR"/cmd-*.c; do
    base=$(basename "$f" .c)
    case "$base" in
        cmd-parse|cmd-queue|cmd-find) continue ;;
    esac

    # Use perl for reliable multi-field extraction from cmd_entry structs
    perl -0777 -ne '
        while (/const\s+struct\s+cmd_entry\s+\w+\s*=\s*\{(.*?)\n\};/gs) {
            my $block = $1;
            my ($name, $alias, $args, $target) = ("", "-", "", "none");

            $name  = $1 if $block =~ /\.name\s*=\s*"([^"]+)"/;
            $alias = $1 if $block =~ /\.alias\s*=\s*"([^"]+)"/;
            $args  = $1 if $block =~ /\.args\s*=\s*\{\s*"([^"]*)"/;

            $target = "pane"    if $block =~ /CMD_FIND_PANE/;
            $target = "window"  if $block =~ /CMD_FIND_WINDOW/;
            $target = "session" if $block =~ /CMD_FIND_SESSION/;
            $target = "client"  if $block =~ /CMD_FIND_CLIENT/;

            print "$name|$alias|$args|$target\n" if $name;
        }
    ' "$f"
done | sort
