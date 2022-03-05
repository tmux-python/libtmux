# flake8: NOQA
import sys
from collections.abc import MutableMapping

console_encoding = sys.__stdout__.encoding


def console_to_str(s):
    """From pypa/pip project, pip.backwardwardcompat. License MIT."""
    try:
        return s.decode(console_encoding, "ignore")
    except UnicodeDecodeError:
        return s.decode("utf_8", "ignore")


def reraise(tp, value, tb=None):
    if value.__traceback__ is not tb:
        raise (value.with_traceback(tb))
    raise value


def str_from_console(s):
    try:
        return str(s)
    except UnicodeDecodeError:
        return str(s, encoding="utf_8")
