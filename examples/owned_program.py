"""Run and clean up a private pane program on tmux 3.8 or later."""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import typing as t

import libtmux


def main() -> None:
    """Assert exit evidence and preserve the parent until owned-server cleanup."""
    os.environ.pop("TMUX", None)
    os.environ.pop("TMUX_PANE", None)
    operation_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    with tempfile.TemporaryDirectory(prefix="libtmux-program-") as directory:
        server = libtmux.Server(
            socket_path=pathlib.Path(directory) / "socket", config_file="/dev/null"
        )
        job = None
        try:
            parent = server.new_session(session_name="parent")
            identity_format = "#{pid}|#{session_id}|#{window_id}|#{pane_id}|#{pane_pid}"
            before = parent.cmd("display-message", "-p", identity_format).stdout
            job = parent.run_program(
                [
                    sys.executable,
                    "-c",
                    "print('hello from the program'); raise SystemExit(7)",
                ]
            )
            result = job.wait()
            observation = job.collect(start=-100)
            assert result.exit_status == 7
            assert result.exit_signal is None
            assert observation.text == "hello from the program"
            job.cleanup()
            assert parent.cmd("display-message", "-p", identity_format).stdout == before
            print(f"exit status: {result.exit_status}")
            print(observation.text)
        except BaseException as error:  # noqa: BLE001
            operation_error = error
        finally:
            cleanup: list[t.Callable[[], object]] = [server.kill]
            if job is not None:
                cleanup = [job.terminate, job.cleanup, server.kill]
            for close in cleanup:
                try:
                    close()
                except BaseException as error:  # noqa: BLE001, PERF203
                    cleanup_errors.append(error)
    if operation_error is not None:
        operation_error.cleanup_errors = (  # type: ignore[attr-defined]
            *getattr(operation_error, "cleanup_errors", ()),
            *cleanup_errors,
        )
        raise operation_error
    if cleanup_errors:
        failure = cleanup_errors[0]
        failure.cleanup_errors = tuple(cleanup_errors[1:])  # type: ignore[attr-defined]
        raise failure


if __name__ == "__main__":
    main()
