#!/usr/bin/env bash
# Bootstrap a Python 3.15-backed venv for Tachyon profiling.
#
# Idempotent: safe to re-run. Skips work when .venv-3.15 already exists
# and reports Tachyon's status.
#
# Usage:
#   bash ~/work/python/libtmux/.claude/skills/libtmux-profiler/scripts/setup-tachyon-venv.sh
#
# Run from the libtmux (or any libtmux/tmuxp) repo root, OR the script
# will detect the repo root from $PWD.

set -euo pipefail

PYTHON_315="${HOME}/.config/mise/installs/python/3.15.0a8/bin/python3.15"

if [ ! -x "${PYTHON_315}" ]; then
    echo "ERROR: Python 3.15.0a8 not installed via mise."
    echo "  fix: cd into a repo with .tool-versions declaring 3.15.0a8 and run \`mise install\`"
    echo "  or:  mise install python@3.15.0a8"
    exit 1
fi

# Find the repo root from $PWD by walking up looking for pyproject.toml.
repo_root="${PWD}"
while [ "${repo_root}" != "/" ] && [ ! -f "${repo_root}/pyproject.toml" ]; do
    repo_root="$(dirname "${repo_root}")"
done

if [ ! -f "${repo_root}/pyproject.toml" ]; then
    echo "ERROR: no pyproject.toml found in ${PWD} or any parent."
    echo "  fix: cd into a libtmux or tmuxp repo first."
    exit 1
fi

cd "${repo_root}"
echo "==> repo: ${repo_root}"

venv=".venv-3.15"

if [ -d "${venv}" ]; then
    if "${venv}/bin/python" -c "import profiling.sampling" 2>/dev/null; then
        echo "==> ${venv} already exists with Tachyon importable — skipping setup."
        echo "==> verify: ${venv}/bin/python -m profiling.sampling --help"
        exit 0
    fi
    echo "==> ${venv} exists but Tachyon import failed; rebuilding."
    rm -rf "${venv}"
fi

echo "==> creating ${venv} with Python 3.15"
uv venv --python "${PYTHON_315}" "${venv}" >/dev/null

# Install with the testing group only — `dev` pulls in sphinx-autobuild
# → watchfiles, which has no Rust wheel for 3.15a8 yet and fails to build.
echo "==> installing project (editable) + testing group"
VIRTUAL_ENV="${repo_root}/${venv}" uv pip install --quiet \
    --editable . --group testing

# pyproject.toml's addopts requires `--no-cov`, which only exists when
# pytest-cov is installed. The `coverage` group exists for this but adds
# nothing else useful to a profiler venv, so install pytest-cov directly.
echo "==> installing pytest-cov (required by repo's pytest addopts)"
VIRTUAL_ENV="${repo_root}/${venv}" uv pip install --quiet pytest-cov

echo "==> verifying Tachyon import"
"${venv}/bin/python" -c "import profiling.sampling; print('  Tachyon at:', profiling.sampling.__file__)"

echo
echo "==> done. Try:"
echo "    ${venv}/bin/python -m profiling.sampling run --help"
