# flake8: NOQA
import sys
import types
import typing as t

console_encoding = sys.__stdout__.encoding


def console_to_str(s: bytes) -> str:
    """From pypa/pip project, pip.backwardwardcompat. License MIT."""
    try:
        return s.decode(console_encoding, "ignore")
    except UnicodeDecodeError:
        return s.decode("utf_8", "ignore")


# TODO Consider removing, reraise does not seem to be called anywhere
def reraise(
    tp: t.Type[BaseException],
    value: BaseException,
    tb: types.TracebackType,
) -> t.NoReturn:

    if value.__traceback__ is not tb:
        raise (value.with_traceback(tb))
    raise value


def str_from_console(s: t.Union[str, bytes]) -> str:
    try:
        return str(s)
    except UnicodeDecodeError:
        return str(s, encoding="utf_8") if isinstance(s, bytes) else s
