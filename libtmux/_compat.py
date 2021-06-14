# -*- coding: utf8 -*-
# flake8: NOQA
import configparser
import pickle
import sys
import urllib.parse as urlparse
from collections.abc import MutableMapping
from io import BytesIO, StringIO
from string import ascii_lowercase
from urllib.request import urlretrieve

PY2 = sys.version_info[0] == 2

_identity = lambda x: x


unichr = chr
text_type = str
string_types = (str,)
integer_types = (int,)

text_to_native = lambda s, enc: s

iterkeys = lambda d: iter(d.keys())
itervalues = lambda d: iter(d.values())
iteritems = lambda d: iter(d.items())


izip = zip
imap = map
range_type = range

cmp = lambda a, b: (a > b) - (a < b)

console_encoding = sys.__stdout__.encoding

implements_to_string = _identity


def console_to_str(s):
    """ From pypa/pip project, pip.backwardwardcompat. License MIT. """
    try:
        return s.decode(console_encoding, 'ignore')
    except UnicodeDecodeError:
        return s.decode('utf_8', 'ignore')


def reraise(tp, value, tb=None):
    if value.__traceback__ is not tb:
        raise (value.with_traceback(tb))
    raise value


number_types = integer_types + (float,)


def str_from_console(s):
    try:
        return text_type(s)
    except UnicodeDecodeError:
        return text_type(s, encoding='utf_8')
