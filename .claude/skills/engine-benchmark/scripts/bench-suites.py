#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
# Greek sigma (σ) and multiplication sign (×) are intentional in
# docstrings, comments, and emitted strings — they match hyperfine's
# own conventions and the worked-example output the script reproduces.
r"""Hyperfine-driven full-suite engine benchmark for libtmux + tmuxp.

Runs ``uv run pytest`` under each of the three protocol engines
(``subprocess``, ``imsg``, ``control_mode``) for one or both repos
and prints a unified markdown table comparing mean / median / min /
max wall time, plus a short insights section flagging speedup
ratios and σ noise.

Wraps ``hyperfine -L engine subprocess,imsg,control_mode`` so a
single invocation produces all measurements; uses
``--export-json`` so the post-processing can compute speedup
ratios against an arbitrary baseline engine and detect noisy runs.

Usage
-----
::

    $ python3 .claude/skills/engine-benchmark/scripts/bench-suites.py

    $ python3 .claude/skills/engine-benchmark/scripts/bench-suites.py \\
        --repos libtmux \\
        --warmup 2 \\
        --runs 7 \\
        --baseline-engine imsg \\
        --extra-pytest-args "-k workspace"

Repo paths default to the working tree on this host
(``~/work/python/libtmux-protocol-engines`` and
``~/work/python/tmuxp-libtmux-protocol``); override per repo via
``BENCH_LIBTMUX_PATH`` / ``BENCH_TMUXP_PATH`` env vars.

The pytest invocation uses ``--engine={engine}`` (libtmux's pytest
plugin) which flows through to tmuxp transparently because tmuxp
depends on libtmux. Pre-existing test failures don't bork the
sweep — ``hyperfine -i`` ignores non-zero exit codes; the wall
timings stay valid as long as the failing set is stable across
engines.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import typing as t
from pathlib import Path

ENGINES = ("subprocess", "imsg", "control_mode")

DEFAULT_PYTEST_CMD = "uv run --active pytest --reruns 0 -q --engine={engine}"


class RepoSpec(t.TypedDict):
    """Per-repo configuration for the bench sweep."""

    label: str
    path: Path
    cmd_template: str
    env_unset: tuple[str, ...]


def repo_config(extra_pytest_args: str) -> dict[str, RepoSpec]:
    """Build the repo→spec map with optional extra pytest args injected.

    Hard-coded defaults match this host; ``BENCH_LIBTMUX_PATH`` /
    ``BENCH_TMUXP_PATH`` env-var overrides let users on different
    layouts point at their own clones without editing the script.
    """
    suffix = f" {extra_pytest_args}" if extra_pytest_args else ""
    cmd = DEFAULT_PYTEST_CMD + suffix
    return {
        "libtmux": {
            "label": "libtmux",
            "path": Path(
                os.environ.get(
                    "BENCH_LIBTMUX_PATH",
                    "~/work/python/libtmux-protocol-engines",
                ),
            ).expanduser(),
            "cmd_template": cmd,
            "env_unset": (),
        },
        "tmuxp": {
            "label": "tmuxp",
            "path": Path(
                os.environ.get(
                    "BENCH_TMUXP_PATH",
                    "~/work/python/tmuxp-libtmux-protocol",
                ),
            ).expanduser(),
            "cmd_template": cmd,
            # ``uv run --active`` honours the ambient VIRTUAL_ENV. When
            # invoked from inside libtmux's venv, that leaks into the
            # tmuxp subprocess and uv emits a "VIRTUAL_ENV does not
            # match" warning before falling back to the project venv —
            # not strictly broken, but noisy and risks running tmuxp
            # against the wrong libtmux. Unset to force tmuxp's own
            # `.venv`.
            "env_unset": ("VIRTUAL_ENV",),
        },
    }


def bench_repo(
    name: str,
    spec: RepoSpec,
    *,
    warmup: int,
    runs: int,
    outdir: Path,
) -> dict[str, t.Any] | None:
    """Run one hyperfine sweep across the three engines for one repo.

    Returns the parsed hyperfine JSON dict, or ``None`` when the
    repo path is missing (skip-with-warning behaviour).
    """
    if not spec["path"].is_dir():
        print(
            f"warning: skipping {name}: repo path {spec['path']} does not exist",
            file=sys.stderr,
        )
        return None

    json_out = outdir / f"{name}.json"
    md_out = outdir / f"{name}.md"

    cmd = [
        "hyperfine",
        # Pre-existing test failures (e.g. environmental
        # ``test_no_server_*`` on this host) are stable across
        # engines, so non-zero exit codes don't invalidate the
        # comparison — let hyperfine carry on.
        "-i",
        "-w",
        str(warmup),
        "-m",
        str(runs),
        "-L",
        "engine",
        ",".join(ENGINES),
        "--command-name",
        f"{spec['label']} {{engine}}",
        "--export-markdown",
        str(md_out),
        "--export-json",
        str(json_out),
        spec["cmd_template"],
    ]

    env = os.environ.copy()
    for key in spec["env_unset"]:
        env.pop(key, None)

    print(
        f"==> {name} ({spec['path']}): hyperfine -L engine {','.join(ENGINES)} ...",
        file=sys.stderr,
    )
    subprocess.run(cmd, cwd=spec["path"], env=env, check=False)

    if not json_out.exists():
        print(
            f"error: hyperfine produced no JSON output at {json_out}",
            file=sys.stderr,
        )
        return None

    return t.cast("dict[str, t.Any]", json.loads(json_out.read_text()))


def median(values: list[float]) -> float:
    """Return the median of *values* (assumed non-empty)."""
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def engine_from_command(command: str) -> str:
    """Extract the engine name from a hyperfine ``--command-name``.

    Command names follow the ``"<repo> <engine>"`` template (per
    :func:`bench_repo`). Last whitespace-separated token wins.
    """
    return command.split()[-1]


def render_table(
    repo_results: dict[str, dict[str, t.Any]],
    *,
    baseline_engine: str,
) -> str:
    """Render the unified per-repo per-engine wall-time table."""
    lines = [
        f"| Repo | Engine | Mean ± σ | Median | Min | Max | vs {baseline_engine} |",
        "|------|--------|---------:|-------:|----:|----:|-----------------:|",
    ]
    for repo, payload in repo_results.items():
        results = payload["results"]
        baseline_mean = next(
            (
                r["mean"]
                for r in results
                if engine_from_command(r["command"]) == baseline_engine
            ),
            None,
        )
        if baseline_mean is None:
            print(
                f"warning: {repo} has no {baseline_engine} run; speedup column blank",
                file=sys.stderr,
            )
        for r in results:
            engine = engine_from_command(r["command"])
            med = median(r["times"]) if r.get("times") else float("nan")
            if baseline_mean is None:
                speedup = "—"
            elif engine == baseline_engine:
                speedup = "1.00×"
            else:
                ratio = baseline_mean / r["mean"]
                speedup = f"**{ratio:.2f}× faster**"
            lines.append(
                f"| **{repo}** | {engine} | "
                f"{r['mean']:.2f} s ± {r['stddev']:.2f} | "
                f"{med:.2f} s | "
                f"{r['min']:.2f} s | "
                f"{r['max']:.2f} s | "
                f"{speedup} |",
            )
    return "\n".join(lines)


def insights(
    repo_results: dict[str, dict[str, t.Any]],
    *,
    baseline_engine: str,
) -> list[str]:
    """Return the insight bullets — speedup, divergence, σ-noise."""
    bullets: list[str] = []
    means: dict[str, dict[str, float]] = {}
    stddevs: dict[str, dict[str, float]] = {}
    for repo, payload in repo_results.items():
        means[repo] = {
            engine_from_command(r["command"]): r["mean"] for r in payload["results"]
        }
        stddevs[repo] = {
            engine_from_command(r["command"]): r["stddev"] for r in payload["results"]
        }

    # Per-repo speedup ratios.
    for repo, engine_means in means.items():
        base = engine_means.get(baseline_engine)
        if base is None:
            continue
        deltas = [
            (engine, base / mean, mean)
            for engine, mean in engine_means.items()
            if engine != baseline_engine
        ]
        for engine, ratio, mean in deltas:
            bullets.append(
                f"- **{repo}**: {engine} is **{ratio:.2f}× faster** "
                f"than {baseline_engine} ({base:.1f} s → {mean:.1f} s).",
            )

    # Cross-repo divergence callout: same engine with very different
    # speedup ratios usually means the slower repo is shell-bound
    # (`_wait_for_pane_ready` polling absorbs the engine win).
    if len(repo_results) >= 2:
        repos = list(means.keys())
        for engine in ENGINES:
            if engine == baseline_engine:
                continue
            ratios = {
                repo: means[repo][baseline_engine] / means[repo][engine]
                for repo in repos
                if baseline_engine in means[repo] and engine in means[repo]
            }
            if len(ratios) < 2:
                continue
            highest_repo, highest_ratio = max(ratios.items(), key=lambda kv: kv[1])
            lowest_repo, lowest_ratio = min(ratios.items(), key=lambda kv: kv[1])
            if highest_ratio - lowest_ratio >= 0.3:
                bullets.append(
                    f"- **{engine} speedup compresses** from "
                    f"{highest_ratio:.2f}× on `{highest_repo}` to "
                    f"{lowest_ratio:.2f}× on `{lowest_repo}` — likely "
                    "shell-readiness wait absorbing the engine win "
                    "(see `libtmux-profiler` worked example).",
                )

    # σ-noise warnings (>10 % of mean).
    for repo, engine_means in means.items():
        for engine, mean in engine_means.items():
            sigma = stddevs[repo].get(engine, 0.0)
            if mean > 0 and sigma / mean > 0.10:
                bullets.append(
                    f"- ⚠️  **{repo} {engine}** σ is "
                    f"{sigma:.2f} s ({100 * sigma / mean:.1f} % of mean) — "
                    "consider rerunning on a quieter system.",
                )

    return bullets


def main() -> int:
    """CLI entry point — parse args, run sweep, print table + insights."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--repos",
        nargs="+",
        default=["libtmux", "tmuxp"],
        choices=["libtmux", "tmuxp"],
        help="which repos to benchmark (default: both)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=1,
        help="hyperfine warmup runs (default: 1)",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=5,
        help="hyperfine measured runs per (repo, engine) (default: 5)",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=None,
        help=(
            "where to write hyperfine artifacts "
            "(default: /tmp/bench-engines/<YYYY-MM-DD-HH-MM-SS>)"
        ),
    )
    parser.add_argument(
        "--baseline-engine",
        choices=ENGINES,
        default="subprocess",
        help="reference engine for the speedup ratio column (default: subprocess)",
    )
    parser.add_argument(
        "--extra-pytest-args",
        default="",
        help="extra arguments forwarded to pytest (e.g. '-k workspace')",
    )
    args = parser.parse_args()

    if shutil.which("hyperfine") is None:
        print(
            "error: hyperfine is not on PATH. install via:\n"
            "    cargo install hyperfine\n"
            "  or:\n"
            "    apt install hyperfine  # debian/ubuntu",
            file=sys.stderr,
        )
        return 1

    if args.outdir is None:
        timestamp = dt.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")
        args.outdir = Path("/tmp/bench-engines") / timestamp
    args.outdir.mkdir(parents=True, exist_ok=True)

    specs = repo_config(args.extra_pytest_args)
    repo_results: dict[str, dict[str, t.Any]] = {}
    for name in args.repos:
        result = bench_repo(
            name,
            specs[name],
            warmup=args.warmup,
            runs=args.runs,
            outdir=args.outdir,
        )
        if result is not None:
            repo_results[name] = result

    if not repo_results:
        print("error: no repos produced results — nothing to render", file=sys.stderr)
        return 1

    print()
    print(
        f"## Engine benchmark — `uv run pytest` full suite, "
        f"{args.warmup} warmup + {args.runs} measured runs",
    )
    print()
    print(render_table(repo_results, baseline_engine=args.baseline_engine))
    print()
    print("## Insights")
    print()
    bullets = insights(repo_results, baseline_engine=args.baseline_engine)
    if bullets:
        print("\n".join(bullets))
    else:
        print("- (no significant deltas — engines all within ~10 % of each other)")
    print()
    print(f"_Artifacts: {args.outdir}/{{repo}}.{{json,md}}_")
    return 0


if __name__ == "__main__":
    sys.exit(main())
