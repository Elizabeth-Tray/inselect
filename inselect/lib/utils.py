from __future__ import print_function

import errno
import os
import shutil
import stat
import string

from collections import Counter
from itertools import ifilterfalse
from pathlib import Path

from inselect.lib.inselect_error import InselectError

DEBUG_PRINT = False


def debug_print(*args, **kwargs):
    if DEBUG_PRINT:
        print(*args, **kwargs)

def make_readonly(path):
    """Alters path to be read-only and return the original mode
    """
    path = Path(path)
    mode = path.stat()[stat.ST_MODE]
    path.chmod(mode ^ (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    return mode

def rmtree_readonly(path):
    """Like shutil.rmtree() but removes read-only files on Windows
    """

    # http://stackoverflow.com/a/9735134
    def handle_remove_readonly(func, path, exc):
        excvalue = exc[1]
        if func in (os.rmdir, os.remove) and excvalue.errno == errno.EACCES:

            # ensure parent directory is writeable too
            pardir = os.path.abspath(os.path.join(path, os.path.pardir))
            if not os.access(pardir, os.W_OK):
                os.chmod(pardir, stat.S_IRWXU| stat.S_IRWXG| stat.S_IRWXO)

            os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO) # 0777

            func(path)
        else:
            raise

    shutil.rmtree(str(path), ignore_errors=False, onerror=handle_remove_readonly)

def unique_everseen(iterable, key=None):
    "List unique elements, preserving order. Remember all elements ever seen."
    # Taken from https://docs.python.org/2/library/itertools.html
    # unique_everseen('AAAABBBCCDAABBB') --> A B C D
    # unique_everseen('ABBCcAD', str.lower) --> A B C D
    seen = set()
    seen_add = seen.add
    if key is None:
        for element in ifilterfalse(seen.__contains__, iterable):
            seen_add(element)
            yield element
    else:
        for element in iterable:
            k = key(element)
            if k not in seen:
                seen_add(k)
                yield element

def duplicated(v):
    """Returns values within v that appear more than once
    """
    return [x for x, y in Counter(v).items() if y > 1]


class FormatDefault(string.Formatter):
    """A string formatter than returns a default value for missing keys
    http://stackoverflow.com/a/19800610

    >>> fmt = FormatDefault(default='???')
    >>> metadata = {'ItemNumber' : 23, 'catalogNumber' : '1234'}
    >>> template = '{ItemNumber:03}-{catalogNumber}-{x}'
    >>> print(fmt.format(template, **metadata))
    '023-1234-???'

    """
    def __init__(self, default=''):
        self.default=default

    def get_value(self, key, args, kwds):
        # key will be either an integer or a string. If it is an integer, it
        # represents the index of the positional argument in args; if it is
        # a string, then it represents a named argument in kwargs.
        if isinstance(key, int):
            Formatter.get_value(key, args, kwds)
        else:
            return kwds.get(key, self.default)

