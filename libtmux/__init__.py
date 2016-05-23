# -*- coding: utf-8 -*-
"""API for interfacing with tmux servers, sessions, windows and panes.

libtmux
~~~~~~~

:copyright: Copyright 2016 Tony Narlock.
:license: BSD, see LICENSE for details

"""

from .__about__ import __title__, __package_name__, __version__, \
    __description__, __email__, __author__, __license__, __copyright__

from .pane import Pane
from .server import Server
from .session import Session
from .window import Window
