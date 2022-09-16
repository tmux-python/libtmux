"""Invokable :mod:`subprocess` wrapper.

Defer running a subprocess, such as by handing to an executor.

Note
----
This is an internal API not covered by versioning policy.

Examples
--------

- :class:`~SubprocessCommand`: Wraps :class:`subprocess.Popen` and
  :func:`subprocess.run` in a :func:`~dataclasses.dataclass`.

  Before:

  >>> import subprocess
  >>> subprocess.run(
  ...    ['echo', 'hi'],
  ...    capture_output=True, universal_newlines=True
  ... ).stdout
  'hi\\n'

  With this:

  >>> cmd = SubprocessCommand(['echo', 'hi'])
  >>> cmd.args
  ['echo', 'hi']
  >>> cmd.run(capture_output=True, universal_newlines=True).stdout
  'hi\\n'

  Tweak params before invocation:

  >>> cmd = SubprocessCommand(['echo', 'hi'])
  >>> cmd.args[1] = 'hello'
  >>> cmd.args
  ['echo', 'hello']
  >>> cmd.run(capture_output=True, universal_newlines=True).stdout
  'hello\\n'
"""
import dataclasses
import subprocess
import sys
from collections.abc import Mapping, Sequence
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    Callable,
    List,
    Optional,
    TypeVar,
    Union,
    overload,
)

from typing_extensions import Literal, TypeAlias

from .dataclasses import SkipDefaultFieldsReprMixin
from .types import StrOrBytesPath

F = TypeVar("F", bound=Callable[..., Any])


if sys.platform == "win32":
    _ENV: TypeAlias = "Mapping[str, str]"
else:
    _ENV: TypeAlias = Union[
        "Mapping[bytes, StrOrBytesPath]", "Mapping[str, StrOrBytesPath]"
    ]
_FILE: TypeAlias = Union[None, int, IO[Any]]
_TXT: TypeAlias = Union[bytes, str]

if TYPE_CHECKING:
    #: Command
    _CMD: TypeAlias = Union[StrOrBytesPath, "Sequence[StrOrBytesPath]"]


@dataclasses.dataclass(repr=False)
class SubprocessCommand(SkipDefaultFieldsReprMixin):
    """Wraps a :mod:`subprocess` request. Inspect, mutate, control before invocation.

    Attributes
    ----------
    args : _CMD
        A string, or a sequence of program arguments.

    bufsize : int
        supplied as the buffering argument to the open() function when creating the
        stdin/stdout/stderr pipe file objects

    executable : Optional[StrOrBytesPath]
        A replacement program to execute.

    stdin : _FILE
        standard output for executed program

    stdout :
        standard output for executed program

    stderr :
        standard output for executed program

    close_fds : Controls closing or inheriting of file descriptors.

    shell : If true, the command will be executed through the shell.

    cwd : Sets the current directory before the child is executed.

    env : Defines the environment variables for the new process.

    text :
        If ``True``, decode stdin, stdout and stderr using the given encoding (if set)
        or the system default otherwise.

    universal_newlines :
        Alias of text, provided for backwards compatibility.

    startupinfo :
        Windows only

    creationflags :
        Windows only

    preexec_fn :
        (POSIX only) An object to be called in the child process just before the child
        is executed.

    restore_signals :
        POSIX only

    start_new_session :
        POSIX only

    group :
        POSIX only

    extra_groups :
        POSIX only

    user :
        POSIX only

    umask :
        POSIX only

    pass_fds :
        POSIX only

    encoding :
        Text mode encoding to use for file objects stdin, stdout and stderr.

    errors :
        Text mode error handling to use for file objects stdin, stdout and stderr.

    Examples
    --------
    >>> cmd = SubprocessCommand("ls")
    >>> cmd.args
    'ls'

    With ``shell=True``:

    >>> cmd = SubprocessCommand("ls -l", shell=True)
    >>> cmd.shell
    True
    >>> cmd.args
    'ls -l'
    >>> cmd.check_call()
    0
    """

    args: "_CMD"
    bufsize: int = -1
    executable: Optional[StrOrBytesPath] = None
    stdin: _FILE = None
    stdout: _FILE = None
    stderr: _FILE = None
    preexec_fn: Optional[Callable[[], Any]] = None
    close_fds: bool = True
    shell: bool = False
    cwd: Optional[StrOrBytesPath] = None
    env: Optional[_ENV] = None

    # Windows
    creationflags: int = 0
    startupinfo: Optional[Any] = None

    # POSIX-only
    restore_signals: bool = True
    start_new_session: bool = False
    pass_fds: Any = ()
    if sys.version_info >= (3, 9):
        umask: int = -1
    if sys.version_info >= (3, 10):
        pipesize: int = -1

    if sys.version_info >= (3, 9):
        user: Optional[str] = None
        group: Optional[str] = None
        extra_groups: Optional[List[str]] = None

    # Alias of text, for backwards compatibility
    universal_newlines: Optional[bool] = None
    text: Optional[Literal[True]] = None

    # Text mode encoding and error handling to use for file objects
    # stdin, stdout, stderr
    encoding: Optional[str] = None
    errors: Optional[str] = None

    # user, group, extra_groups, umask were added in 3.9
    @overload
    def Popen(
        self,
        args: Optional["_CMD"] = ...,
        universal_newlines: bool = ...,
        *,
        text: Optional[bool] = ...,
        encoding: str,
        errors: Optional[str] = ...,
    ) -> "subprocess.Popen[str]":
        ...

    @overload
    def Popen(
        self,
        args: Optional["_CMD"] = ...,
        universal_newlines: bool = ...,
        *,
        text: Optional[bool] = ...,
        encoding: Optional[str] = ...,
        errors: str,
    ) -> "subprocess.Popen[str]":
        ...

    @overload
    def Popen(
        self,
        args: Optional["_CMD"] = ...,
        *,
        universal_newlines: Literal[True],
        # where the *real* keyword only args start
        text: Optional[bool] = ...,
        encoding: Optional[str] = ...,
        errors: Optional[str] = ...,
    ) -> "subprocess.Popen[str]":
        ...

    @overload
    def Popen(
        self,
        args: Optional["_CMD"] = ...,
        universal_newlines: bool = ...,
        *,
        text: Literal[True],
        encoding: Optional[str] = ...,
        errors: Optional[str] = ...,
    ) -> "subprocess.Popen[str]":
        ...

    @overload
    def Popen(
        self,
        args: Optional["_CMD"] = ...,
        universal_newlines: Literal[False] = ...,
        *,
        text: Literal[None, False] = ...,
        encoding: None = ...,
        errors: None = ...,
    ) -> "subprocess.Popen[bytes]":
        ...

    def Popen(
        self,
        args: Optional["_CMD"] = None,
        universal_newlines: Optional[bool] = None,
        *,
        text: Optional[bool] = None,
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        **kwargs: Any,
    ) -> "subprocess.Popen[Any]":
        """Run commands :class:`subprocess.Popen`, optionally overrides via kwargs.

        Parameters
        ----------
        **kwargs : dict, optional
            Overrides existing attributes for :class:`subprocess.Popen`

        Examples
        --------
        >>> cmd = SubprocessCommand(args=['echo', 'hello'])
        >>> proc = cmd.Popen(stdout=subprocess.PIPE)
        >>> proc.communicate() # doctest: +SKIP
        """
        return subprocess.Popen(
            **dataclasses.replace(
                self,
                args=args or self.args,
                encoding=encoding,
                errors=errors,
                text=text,
                universal_newlines=universal_newlines,
                **kwargs,
            ).__dict__,
        )

    def check_call(self, **kwargs: Any) -> int:
        """Run command :func:`subprocess.check_call`, optionally overrides via kwargs.

        Parameters
        ----------
        **kwargs : dict, optional
            Overrides existing attributes for :func:`subprocess.check_call`

        Examples
        --------
        >>> cmd = SubprocessCommand(args=['echo', 'hello'])
        >>> cmd.check_call(stdout=subprocess.PIPE)
        0
        """
        return subprocess.check_call(**dataclasses.replace(self, **kwargs).__dict__)

    @overload
    def check_output(
        self,
        universal_newlines: bool = ...,
        *,
        input: Optional[Union[str, bytes]] = ...,
        encoding: Optional[str] = ...,
        errors: Optional[str] = ...,
        text: Literal[True],
        **kwargs: Any,
    ) -> str:
        ...

    @overload
    def check_output(
        self,
        universal_newlines: Optional[bool] = ...,
        *,
        input: Optional[Union[str, bytes]] = ...,
        encoding: str,
        errors: Optional[str] = ...,
        text: Optional[bool] = ...,
        **kwargs: Any,
    ) -> str:
        ...

    @overload
    def check_output(
        self,
        universal_newlines: bool = ...,
        *,
        input: Optional[Union[str, bytes]] = ...,
        encoding: Optional[str] = ...,
        errors: str,
        text: Optional[bool] = ...,
        **kwargs: Any,
    ) -> str:
        ...

    @overload
    def check_output(
        self,
        universal_newlines: Literal[True] = ...,
        *,
        input: Optional[Union[str, bytes]] = ...,
        encoding: Optional[str] = ...,
        errors: Optional[str] = ...,
        text: Optional[bool] = ...,
        **kwargs: Any,
    ) -> str:
        ...

    @overload
    def check_output(
        self,
        universal_newlines: Literal[False],
        *,
        input: Optional[Union[str, bytes]] = ...,
        encoding: None = ...,
        errors: None = ...,
        text: Literal[None, False] = ...,
        **kwargs: Any,
    ) -> bytes:
        ...

    def check_output(
        self,
        universal_newlines: Optional[bool] = None,
        *,
        input: Optional[Union[str, bytes]] = None,
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        text: Optional[bool] = None,
        **kwargs: Any,
    ) -> Union[bytes, str]:
        r"""Run command :func:`subprocess.check_output`, optionally override via kwargs.

        Parameters
        ----------
        input : Union[bytes, str], optional
            pass string to subprocess's stdin. Bytes by default, str in text mode.

            Text mode is triggered by setting any of text, encoding, errors or
            universal_newlines.
        **kwargs : dict, optional
            Overrides existing attributes for :func:`subprocess.check_output`

        Examples
        --------
        >>> cmd = SubprocessCommand(args=['echo', 'hello'])
        >>> proc = cmd.check_output(shell=True)

        Examples from :mod:`subprocess`:

        >>> import subprocess
        >>> cmd = SubprocessCommand(
        ...     ["/bin/sh", "-c", "ls -l non_existent_file ; exit 0"])
        >>> cmd.check_output(stderr=subprocess.STDOUT)
        b"ls: ...non_existent_file...: No such file or directory\n"

        >>> cmd = SubprocessCommand(["sed", "-e", "s/foo/bar/"])
        >>> cmd.check_output(input=b"when in the course of fooman events\n")
        b'when in the course of barman events\n'
        """
        params = dataclasses.replace(self, **kwargs).__dict__
        params.pop("stdout")
        output = subprocess.check_output(input=input, **params)
        if isinstance(output, (bytes, str)):
            return output
        raise Exception(f"output is not str or bytes: {output}")

    @overload
    def run(
        self,
        universal_newlines: bool = ...,
        *,
        capture_output: bool = ...,
        check: bool = ...,
        encoding: Optional[str] = ...,
        errors: Optional[str] = ...,
        input: Optional[str] = ...,
        text: Literal[True],
    ) -> "subprocess.CompletedProcess[str]":
        ...

    @overload
    def run(
        self,
        universal_newlines: bool = ...,
        *,
        capture_output: bool = ...,
        check: bool = ...,
        encoding: str,
        errors: Optional[str] = ...,
        input: Optional[str] = ...,
        text: Optional[bool] = ...,
    ) -> "subprocess.CompletedProcess[str]":
        ...

    @overload
    def run(
        self,
        universal_newlines: bool = ...,
        *,
        capture_output: bool = ...,
        check: bool = ...,
        encoding: Optional[str] = ...,
        errors: str,
        input: Optional[str] = ...,
        text: Optional[bool] = ...,
    ) -> "subprocess.CompletedProcess[str]":
        ...

    @overload
    def run(
        self,
        *,
        universal_newlines: Literal[True],
        # where the *real* keyword only args start
        capture_output: bool = ...,
        check: bool = ...,
        encoding: Optional[str] = ...,
        errors: Optional[str] = ...,
        input: Optional[str] = ...,
        text: Optional[bool] = ...,
    ) -> "subprocess.CompletedProcess[str]":
        ...

    @overload
    def run(
        self,
        universal_newlines: Literal[False] = ...,
        *,
        capture_output: bool = ...,
        check: bool = ...,
        encoding: None = ...,
        errors: None = ...,
        input: Optional[bytes] = ...,
        text: Literal[None, False] = ...,
    ) -> "subprocess.CompletedProcess[bytes]":
        ...

    def run(
        self,
        universal_newlines: Optional[bool] = None,
        *,
        capture_output: bool = False,
        check: bool = False,
        encoding: Optional[str] = None,
        errors: Optional[str] = None,
        input: Optional[Union[str, bytes]] = None,
        text: Optional[bool] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> "subprocess.CompletedProcess[Any]":
        r"""Run command in :func:`subprocess.run`, optionally overrides via kwargs.

        Parameters
        ----------
        input : Union[bytes, str], optional
            pass string to subprocess's stdin. Bytes by default, str in text mode.

            Text mode is triggered by setting any of text, encoding, errors or
            universal_newlines.

        check : bool
            If True and the exit code was non-zero, it raises a
            :exc:`subprocess.CalledProcessError`. The CalledProcessError object will
            have the return code in the returncode attribute, and output & stderr
            attributes if those streams were captured.

        timeout : int
            If given, and the process takes too long, a :exc:`subprocess.TimeoutExpired`

        **kwargs : dict, optional
            Overrides existing attributes for :func:`subprocess.run`

        Examples
        --------
        >>> import subprocess
        >>> cmd = SubprocessCommand(
        ...     ["/bin/sh", "-c", "ls -l non_existent_file ; exit 0"])
        >>> cmd.run()
        CompletedProcess(args=['/bin/sh', '-c', 'ls -l non_existent_file ; exit 0'],
                         returncode=0)

        >>> import subprocess
        >>> cmd = SubprocessCommand(
        ...     ["/bin/sh", "-c", "ls -l non_existent_file ; exit 0"])
        >>> cmd.run(check=True)
        CompletedProcess(args=['/bin/sh', '-c', 'ls -l non_existent_file ; exit 0'],
                         returncode=0)

        >>> cmd = SubprocessCommand(["sed", "-e", "s/foo/bar/"])
        >>> completed = cmd.run(input=b"when in the course of fooman events\n")
        >>> completed
        CompletedProcess(args=['sed', '-e', 's/foo/bar/'], returncode=0)
        >>> completed.stderr

        >>> cmd = SubprocessCommand(["sed", "-e", "s/foo/bar/"])
        >>> completed = cmd.run(input=b"when in the course of fooman events\n",
        ...                     capture_output=True)
        >>> completed
        CompletedProcess(args=['sed', '-e', 's/foo/bar/'], returncode=0,
                        stdout=b'when in the course of barman events\n', stderr=b'')
        >>> completed.stdout
        b'when in the course of barman events\n'
        >>> completed.stderr
        b''
        """
        return subprocess.run(
            **dataclasses.replace(
                self,
                universal_newlines=universal_newlines,
                errors=errors,
                text=text,
                **kwargs,
            ).__dict__,
            check=check,
            capture_output=capture_output,
            input=input,
            timeout=timeout,
        )
