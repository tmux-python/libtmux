#!/usr/bin/env bash
# Bootstrap a per-session profile output directory.
#
# Usage:
#   PROFILE_DIR=$(bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/init-profile-session.sh <session_name>)
#
# Creates: /tmp/py-profiling/<YYYY-MM-DD-HH-MM-SS>/<project>/<branch>/<session_name>/
#   ├── README.md       (auto-generated session metadata)
#   └── (artifacts go here — .bin, .html, .pstats, etc.)
#
# Prints the absolute path to stdout (so the caller can capture it via
# command substitution). All other output goes to stderr.

set -euo pipefail

session_name="${1:-}"
if [ -z "${session_name}" ]; then
    echo "ERROR: session_name required" >&2
    echo "  usage: $(basename "$0") <session_name>" >&2
    echo "  example: $(basename "$0") server-cmd-baseline" >&2
    exit 1
fi

# Sanitize session name (replace path-unsafe chars).
session_name="${session_name//\//_}"
session_name="${session_name// /_}"

ts="$(date +%Y-%m-%d-%H-%M-%S)"

# Detect git repo from $PWD.
if root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    project="$(basename "${root}")"
    branch="$(git -C "${root}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo no-branch)"
    branch="${branch//\//_}"  # sanitize / in branch names like 'feature/foo'
    head_sha="$(git -C "${root}" rev-parse --short HEAD 2>/dev/null || echo unknown)"
else
    root="${PWD}"
    project="non-git-$(basename "${PWD}")"
    branch="non-git"
    head_sha="none"
fi

dir="/tmp/py-profiling/${ts}/${project}/${branch}/${session_name}"
mkdir -p "${dir}"

# Per-session README captures invocation context.
cat > "${dir}/README.md" <<EOF
# Profile session: \`${session_name}\`

| field | value |
|---|---|
| timestamp | \`${ts}\` |
| project | \`${project}\` |
| repo root | \`${root}\` |
| branch | \`${branch}\` |
| HEAD | \`${head_sha}\` |
| python | \`$(python --version 2>&1 | head -1 || echo unknown)\` |
| invoked from | \`${PWD}\` |
| user shell | \`${SHELL:-unset}\` |

## Files in this session

(populated as artifacts are written)

## How to read

- \`*.bin\` — Tachyon binary captures, replay-able via
  \`python -m profiling.sampling replay <file>.bin --flamegraph -o out.html\`
- \`*.html\` — interactive flamegraphs (open in browser; Ctrl+F to search)
- \`*.pstats\` — Python pstats binaries:
  \`python -c "import pstats; pstats.Stats('<file>.pstats').sort_stats('cumulative').print_stats(30)"\`
- \`heatmap-*/\` — per-source-file HTML heatmaps (start at \`index.html\`)

EOF

echo "==> profile session ready: ${dir}" >&2
echo "${dir}"
