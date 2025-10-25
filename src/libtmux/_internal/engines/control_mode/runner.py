"""Control mode command execution engine."""

from __future__ import annotations

import subprocess
import typing as t
from threading import Lock

if t.TYPE_CHECKING:
    pass

from .parser import ProtocolParser
from .result import ControlModeResult


class ControlModeCommandRunner:
    """Command runner using persistent tmux control mode connection.

    Maintains a single persistent connection to tmux server for faster
    command execution compared to spawning subprocess for each command.

    Thread-safe: Uses Lock to serialize command execution.

    Parameters
    ----------
    socket_name : str
        Socket name for tmux server (-L flag)

    Examples
    --------
    >>> runner = ControlModeCommandRunner("test_socket")
    >>> result = runner.run("list-sessions")  # doctest: +SKIP
    >>> print(result.stdout)  # doctest: +SKIP
    ['0: session1 ...']
    >>> runner.close()  # doctest: +SKIP

    Or use as context manager:

    >>> with ControlModeCommandRunner("test_socket") as runner:  # doctest: +SKIP
    ...     result = runner.run("list-sessions")
    ...     # ... more commands ...
    # Auto-closes on exit
    """

    def __init__(self, socket_name: str) -> None:
        self.socket_name = socket_name
        self._lock = Lock()
        self._command_counter = 0
        self._process: subprocess.Popen[str] | None = None
        self._parser: ProtocolParser | None = None
        self._connect()

    def _connect(self) -> None:
        """Start tmux in control mode."""
        self._process = subprocess.Popen(
            ["tmux", "-C", "-L", self.socket_name],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
        )

        if self._process.stdout is None:
            msg = "Failed to get stdout from control mode process"
            raise RuntimeError(msg)

        self._parser = ProtocolParser(self._process.stdout)

        # Consume any initial output blocks from session auto-creation
        # tmux may automatically create/attach a session on connect
        self._consume_initial_blocks()

    def _consume_initial_blocks(self) -> None:
        """Consume any output blocks sent during connection.

        When tmux starts in control mode, it may automatically create/attach
        a session, which generates output blocks. We need to consume these
        before we start sending commands, otherwise our parser will read
        the initial blocks instead of our command responses.
        """
        if self._parser is None or self._process is None:
            return

        # Read lines until we're past any %begin/%end blocks
        # We stop when we see only notifications (lines starting with %)
        # or when the stream is empty for a moment
        import select

        while True:
            # Check if there's data available (non-blocking with 50ms timeout)
            if not select.select([self._process.stdout], [], [], 0.05)[0]:
                # No more data available, we're past initial blocks
                break

            # Peek at next line to see if it's a %begin
            line = self._parser.stdout.readline()
            if not line:
                break

            line = line.rstrip("\n")

            if line.startswith("%begin"):
                # This is start of a block - consume until %end or %error
                while True:
                    inner_line = self._parser.stdout.readline()
                    if not inner_line:
                        break
                    inner_line = inner_line.rstrip("\n")
                    if inner_line.startswith("%end") or inner_line.startswith(
                        "%error",
                    ):
                        break
            elif line.startswith("%"):
                # Notification - queue it for later
                self._parser.notifications.append(line)
            else:
                # Shouldn't happen - orphaned output line
                pass

    def _filter_args(self, args: tuple[str, ...]) -> list[str]:
        """Filter server-level and incompatible flags from args.

        Control mode connection is already bound to socket, so we must
        remove -L/-S/-f flags that were prepended by Server.cmd().

        Additionally, tmux control mode does not support custom format
        strings with -F, so those flags must also be removed.

        Parameters
        ----------
        args : tuple[str, ...]
            Arguments from Server.cmd() like ("-Lsocket", "list-sessions")

        Returns
        -------
        list[str]
            Filtered args like ["list-sessions"]
        """
        filtered = []
        skip_next = False

        for arg in args:
            if skip_next:
                skip_next = False
                continue

            # Skip socket-related flags (already in connection)
            if arg.startswith("-L") or arg.startswith("-S"):
                if len(arg) == 2:  # -L socket (two-part)
                    skip_next = True
                # else: -Lsocket (one-part), already skipped
                continue

            # Skip config file flag
            if arg.startswith("-f"):
                if len(arg) == 2:  # -f file (two-part)
                    skip_next = True
                continue

            # Skip color flags (not relevant in control mode)
            if arg in ("-2", "-8"):
                continue

            # Skip format flags (not supported in control mode)
            if arg.startswith("-F"):
                if len(arg) == 2:  # -F format (two-part)
                    skip_next = True
                # else: -Fformat (one-part), already skipped
                continue

            filtered.append(arg)

        return filtered

    def run(self, *args: str) -> ControlModeResult:
        """Execute tmux command via control mode.

        Thread-safe: Only one command executes at a time.

        Parameters
        ----------
        *args : str
            Arguments to pass to tmux (may include server flags)

        Returns
        -------
        ControlModeResult
            Command result with stdout, stderr, returncode

        Raises
        ------
        ConnectionError
            If control mode connection is lost
        """
        with self._lock:  # Serialize command execution
            if self._process is None or self._parser is None:
                msg = "Control mode not connected"
                raise ConnectionError(msg)

            if self._process.poll() is not None:
                msg = "Control mode process terminated"
                raise ConnectionError(msg)

            # Filter server-level flags
            filtered_args = self._filter_args(args)

            if not filtered_args:
                # Edge case: only flags, no command
                msg = "No command after filtering flags"
                raise ValueError(msg)

            # Build command line
            command_line = " ".join(filtered_args)

            # Send command
            if self._process.stdin:
                self._process.stdin.write(f"{command_line}\n")
                self._process.stdin.flush()
            else:
                msg = "Control mode stdin closed"
                raise ConnectionError(msg)

            # Parse response
            self._command_counter += 1
            result = self._parser.parse_response(
                cmd=["tmux", "-C", "-L", self.socket_name, *filtered_args]
            )

            return result

    def close(self) -> None:
        """Close the control mode connection.

        Safe to call multiple times.
        """
        if self._process and self._process.poll() is None:
            # Try graceful shutdown
            if self._process.stdin:
                try:
                    self._process.stdin.close()
                    self._process.wait(timeout=2)
                except Exception:
                    # Force kill if graceful fails
                    self._process.kill()
                    self._process.wait()
            else:
                self._process.kill()
                self._process.wait()

        self._process = None
        self._parser = None

    def __enter__(self) -> ControlModeCommandRunner:
        """Context manager entry."""
        return self

    def __exit__(self, *args: t.Any) -> None:
        """Context manager exit - close connection."""
        self.close()

    def __del__(self) -> None:
        """Ensure connection is closed on object destruction."""
        import contextlib

        with contextlib.suppress(Exception):
            self.close()
