# -*- coding: utf-8 -*-
from __future__ import absolute_import
from __future__ import division

import abc
import logging
import os
import re
import six
import string
import subprocess
import sys
import threading
import time

from six.moves import range

from pwnlib import atexit
from pwnlib import term
from pwnlib.context import context
from pwnlib.log import Logger
from pwnlib.timeout import Timeout
from pwnlib.tubes.buffer import Buffer
from pwnlib.util import fiddling
from pwnlib.util import iters
from pwnlib.util import misc
from pwnlib.util import packing


class tube(Timeout, Logger):
    """
    Container of all the tube functions common to sockets, TTYs and SSH connetions.
    """

    default = Timeout.default
    forever = Timeout.forever

    def __init__(self, timeout = default, level = None, *a, **kw):
        super(tube, self).__init__(timeout)

        Logger.__init__(self, None)
        if level is not None:
            self.setLevel(level)

        self.buffer = Buffer(*a, **kw)
        self._newline = None
        atexit.register(self.close)

    def _normalize_keepends_drop(self, keepends, drop, drop_default):
        '''
        >>> t = tube()
        >>> t._normalize_keepends_drop(None, None, True)
        True
        >>> t._normalize_keepends_drop(None, None, False)
        False
        >>> t._normalize_keepends_drop(None, True, True)
        True
        >>> t._normalize_keepends_drop(None, True, False)
        True
        >>> t._normalize_keepends_drop(True, None, True)
        False
        >>> t._normalize_keepends_drop(True, None, False)
        False
        >>> t._normalize_keepends_drop(None, False, True)
        False
        >>> t._normalize_keepends_drop(None, False, False)
        False
        >>> t._normalize_keepends_drop(False, None, True)
        True
        >>> t._normalize_keepends_drop(False, None, False)
        True
        >>> t._normalize_keepends_drop(False, True, False)
        Traceback (most recent call last):
            ...
        pwnlib.exception.PwnlibException: 'drop' and 'keepends' arguments cannot be used together.
        '''
        if keepends is not None:
            self.warn_once("'keepends' argument is deprecated. Use 'drop' instead.")
        if drop is None and keepends is None:
            return drop_default
        elif drop is not None:
            if keepends is not None:
                self.error("'drop' and 'keepends' arguments cannot be used together.")
            return drop
        return not keepends

    @property
    def newline(self):
        r'''Character sent with methods like sendline() or used for recvline().

            >>> t = tube()
            >>> t.newline = b'X'
            >>> t.unrecv(b'A\nB\nCX')
            >>> t.recvline()
            b'A\nB\nCX'

            >>> t = tube()
            >>> context.newline = b'\r\n'
            >>> t.newline
            b'\r\n'

            # Clean up
            >>> context.clear()
        '''
        if self._newline is not None:
            return self._newline
        return context.newline

    @newline.setter
    def newline(self, newline):
        self._newline = packing._need_bytes(newline)

    # Functions based on functions from subclasses
    def recv(self, numb = None, timeout = default):
        r"""recv(numb = 4096, timeout = default) -> bytes

        Receives up to `numb` bytes of data from the tube, and returns
        as soon as any quantity of data is available.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        Raises:
            exceptions.EOFError: The connection is closed

        Returns:
            A bytes object containing bytes received from the socket,
            or ``''`` if a timeout occurred while waiting.

        Examples:

            >>> t = tube()
            >>> # Fake a data source
            >>> t.recv_raw = lambda n: b'Hello, world'
            >>> t.recv() == b'Hello, world'
            True
            >>> t.unrecv(b'Woohoo')
            >>> t.recv() == b'Woohoo'
            True
            >>> with context.local(log_level='debug'):
            ...    _ = t.recv()
            [...] Received 0xc bytes:
                b'Hello, world'
        """
        numb = self.buffer.get_fill_size(numb)
        return self._recv(numb, timeout) or b''

    def unrecv(self, data):
        """unrecv(data)

        Puts the specified data back at the beginning of the receive
        buffer.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b'hello'
            >>> t.recv()
            b'hello'
            >>> t.recv()
            b'hello'
            >>> t.unrecv(b'world')
            >>> t.recv()
            b'world'
            >>> t.recv()
            b'hello'
        """
        data = packing._need_bytes(data)
        self.buffer.unget(data)

    def _fillbuffer(self, timeout = default):
        """_fillbuffer(timeout = default)

        Fills the internal buffer from the pipe, by calling
        :meth:`recv_raw` exactly once.

        Returns:

            The bytes of data received, or ``''`` if no data was received.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda *a: b'abc'
            >>> len(t.buffer)
            0
            >>> t._fillbuffer()
            b'abc'
            >>> len(t.buffer)
            3
        """
        data = b''

        with self.local(timeout):
            data = self.recv_raw(self.buffer.get_fill_size())

        if data and self.isEnabledFor(logging.DEBUG):
            self.debug('Received %#x bytes:' % len(data))
            self.maybe_hexdump(data, level=logging.DEBUG)
        if data:
            self.buffer.add(data)

        return data


    def _recv(self, numb = None, timeout = default):
        """_recv(numb = 4096, timeout = default) -> str

        Receives one chunk of from the internal buffer or from the OS if the
        buffer is empty.
        """
        numb = self.buffer.get_fill_size(numb)

        # No buffered data, could not put anything in the buffer
        # before timeout.
        if not self.buffer and not self._fillbuffer(timeout):
            return b''

        return self.buffer.get(numb)

    def recvpred(self, pred, timeout = default):
        """recvpred(pred, timeout = default) -> bytes

        Receives one byte at a time from the tube, until ``pred(all_bytes)``
        evaluates to True.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        Arguments:
            pred(callable): Function to call, with the currently-accumulated data.
            timeout(int): Timeout for the operation

        Raises:
            exceptions.EOFError: The connection is closed

        Returns:
            A bytes object containing bytes received from the socket,
            or ``''`` if a timeout occurred while waiting.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b'abbbaccc'
            >>> pred = lambda p: p.count(b'a') == 2
            >>> t.recvpred(pred)
            b'abbba'
            >>> pred = lambda p: p.count(b'd') > 0
            >>> t.recvpred(pred, timeout=0.05)
            b''
        """

        data = b''

        with self.countdown(timeout):
            while not pred(data):
                if not self.countdown_active():
                    self.unrecv(data)
                    return b''

                try:
                    res = self.recv(1, timeout=timeout)
                except Exception:
                    self.unrecv(data)
                    return b''

                if res:
                    data += res
                else:
                    self.unrecv(data)
                    return b''

        return data

    def recvn(self, numb, timeout = default):
        """recvn(numb, timeout = default) -> bytes

        Receives exactly `n` bytes.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        Raises:
            exceptions.EOFError: The connection closed before the request could be satisfied

        Returns:
            A string containing bytes received from the socket,
            or ``''`` if a timeout occurred while waiting.

        Examples:

            >>> t = tube()
            >>> data = b'hello world'
            >>> t.recv_raw = lambda *a: data
            >>> t.recvn(len(data)) == data
            True
            >>> t.recvn(len(data)+1) == data + data[:1]
            True
            >>> t.recv_raw = lambda *a: None
            >>> # The remaining data is buffered
            >>> t.recv() == data[1:]
            True
            >>> t.recv_raw = lambda *a: time.sleep(0.01) or b'a'
            >>> t.recvn(10, timeout=0.05)
            b''
            >>> t.recvn(10, timeout=0.06)
            b'aaaaaa...'
        """
        # Keep track of how much data has been received
        # It will be pasted together at the end if a
        # timeout does not occur, or put into the tube buffer.
        with self.countdown(timeout):
            while self.countdown_active() and len(self.buffer) < numb and self._fillbuffer(self.timeout):
                pass

        if len(self.buffer) < numb:
            return b''

        return self.buffer.get(numb)

    def recvuntil(self, delims, drop=False, timeout=default):
        """recvuntil(delims, drop=False, timeout=default) -> bytes

        Receive data until one of `delims` is encountered.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        arguments:
            delims(bytes,tuple): Byte-string of delimiters characters, or list of delimiter byte-strings.
            drop(bool): Drop the ending.  If :const:`True` it is removed from the end of the return value.

        Raises:
            exceptions.EOFError: The connection closed before the request could be satisfied

        Returns:
            A string containing bytes received from the socket,
            or ``''`` if a timeout occurred while waiting.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b"Hello World!"
            >>> t.recvuntil(b' ')
            b'Hello '
            >>> _=t.clean(0)
            >>> # Matches on 'o' in 'Hello'
            >>> t.recvuntil((b' ',b'W',b'o',b'r'))
            b'Hello'
            >>> _=t.clean(0)
            >>> # Matches expressly full string
            >>> t.recvuntil(b' Wor')
            b'Hello Wor'
            >>> _=t.clean(0)
            >>> # Matches on full string, drops match
            >>> t.recvuntil(b' Wor', drop=True)
            b'Hello'

            >>> # Try with regex special characters
            >>> t = tube()
            >>> t.recv_raw = lambda n: b"Hello|World"
            >>> t.recvuntil(b'|', drop=True)
            b'Hello'

        """
        # Convert string into singleton tupple
        if isinstance(delims, (bytes, bytearray, six.text_type)):
            delims = (delims,)
        delims = tuple(map(packing._need_bytes, delims))

        # Longest delimiter for tracking purposes
        longest = max(map(len, delims))

        # Cumulative data to search
        data = []
        top = b''

        with self.countdown(timeout):
            while self.countdown_active():
                try:
                    res = self.recv(timeout=self.timeout)
                except Exception:
                    self.unrecv(b''.join(data) + top)
                    raise

                if not res:
                    self.unrecv(b''.join(data) + top)
                    return b''

                top += res
                start = len(top)
                for d in delims:
                    j = top.find(d)
                    if start > j > -1:
                        start = j
                        end = j + len(d)
                if start < len(top):
                    self.unrecv(top[end:])
                    if drop:
                        top = top[:start]
                    else:
                        top = top[:end]
                    return b''.join(data) + top
                if len(top) > longest:
                    i = -longest - 1
                    data.append(top[:i])
                    top = top[i:]

        return b''

    def recvlines(self, numlines=2**20, keepends=None, drop=None, timeout=default):
        r"""recvlines(numlines, drop=True, timeout=default) -> list of bytes objects

        Receive up to ``numlines`` lines.

        A "line" is any sequence of bytes terminated by the byte sequence
        set by :attr:`newline`, which defaults to ``'\n'``.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        Arguments:
            numlines(int): Maximum number of lines to receive
            drop(bool): Drop newlines at the end of each line (:const:`True`).
            timeout(int): Maximum timeout

        Raises:
            exceptions.EOFError: The connection closed before the request could be satisfied

        Returns:
            A string containing bytes received from the socket,
            or ``''`` if a timeout occurred while waiting.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b'\n'
            >>> t.recvlines(3)
            [b'', b'', b'']
            >>> t.recv_raw = lambda n: b'Foo\nBar\nBaz\n'
            >>> t.recvlines(3)
            [b'Foo', b'Bar', b'Baz']
            >>> t.recvlines(3, True)
            [b'Foo\n', b'Bar\n', b'Baz\n']
            >>> t.recvlines(3, drop=False)
            [b'Foo\n', b'Bar\n', b'Baz\n']
        """
        drop = self._normalize_keepends_drop(keepends, drop, True)
        del keepends

        lines = []
        with self.countdown(timeout):
            for _ in range(numlines):
                try:
                    # We must set 'drop' to False here so that we can
                    # restore the original, unmodified data to the buffer
                    # in the event of a timeout.
                    res = self.recvline(drop=False, timeout=timeout)
                except Exception:
                    self.unrecv(b''.join(lines))
                    raise

                if res:
                    lines.append(res)
                else:
                    break

        if drop:
            lines = [line.rstrip(self.newline) for line in lines]

        return lines

    def recvlinesS(self, numlines=2**20, keepends=None, drop=None, timeout=default):
        r"""recvlinesS(numlines, drop=True, timeout=default) -> str list

        This function is identical to :meth:`recvlines`, but decodes
        the received bytes into string using :func:`context.encoding`.
        You should use :meth:`recvlines` whenever possible for better performance.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b'\n'
            >>> t.recvlinesS(3)
            ['', '', '']
            >>> t.recv_raw = lambda n: b'Foo\nBar\nBaz\n'
            >>> t.recvlinesS(3)
            ['Foo', 'Bar', 'Baz']
        """
        return [packing._decode(x) for x in self.recvlines(numlines, keepends=keepends, drop=drop, timeout=timeout)]

    def recvlinesb(self, numlines=2**20, keepends=None, drop=None, timeout=default):
        r"""recvlinesb(numlines, drop=True, timeout=default) -> bytearray list

        This function is identical to :meth:`recvlines`, but returns a bytearray.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b'\n'
            >>> t.recvlinesb(3)
            [bytearray(b''), bytearray(b''), bytearray(b'')]
            >>> t.recv_raw = lambda n: b'Foo\nBar\nBaz\n'
            >>> t.recvlinesb(3)
            [bytearray(b'Foo'), bytearray(b'Bar'), bytearray(b'Baz')]
        """
        return [bytearray(x) for x in self.recvlines(numlines, keepends=keepends, drop=drop, timeout=timeout)]

    def recvline(self, keepends=None, drop=None, timeout=default):
        r"""recvline(drop=False, timeout=default) -> bytes

        Receive a single line from the tube.

        A "line" is any sequence of bytes terminated by the byte sequence
        set in :attr:`newline`, which defaults to ``b'\n'``.

        If the connection is closed (:class:`EOFError`) before a newline
        is received, the buffered data is returned by default and a warning
        is logged. If the buffer is empty, an :class:`EOFError` is raised.
        This behavior can be changed by setting :meth:`pwnlib.context.ContextType.throw_eof_on_incomplete_line`.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty byte string (``b''``) is returned.

        Arguments:
            drop(bool): Drop the line ending (:const:`False`).
            timeout(int): Timeout

        Raises:
            :class:`EOFError`: The connection closed before the request
                                 could be satisfied and the buffer is empty

        Return:
            All bytes received over the tube until the first
            newline ``'\n'`` is received.  Optionally retains
            the ending. If the connection is closed before a newline
            is received, the remaining data received up to this point
            is returned.


        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b'Foo\nBar\r\nBaz\n'
            >>> t.recvline()
            b'Foo\n'
            >>> t.recvline()
            b'Bar\r\n'
            >>> t.recvline(False)
            b'Baz'
            >>> t.newline = b'\r\n'
            >>> t.recvline(drop=True)
            b'Foo\nBar'
            >>> t = tube()
            >>> def _recv_eof(n):
            ...     if not _recv_eof.throw:
            ...         _recv_eof.throw = True
            ...         return b'real line\ntrailing data'
            ...     raise EOFError
            >>> _recv_eof.throw = False
            >>> t.recv_raw = _recv_eof
            >>> t.recvline()
            b'real line\n'
            >>> t.recvline()
            b'trailing data'
            >>> t.recvline()
            Traceback (most recent call last):
                ...
            EOFError
        """
        drop = self._normalize_keepends_drop(keepends, drop, False)
        del keepends

        try:
            return self.recvuntil(self.newline, drop=drop, timeout=timeout)
        except EOFError:
            if not context.throw_eof_on_incomplete_line and self.buffer.size > 0:
                if context.throw_eof_on_incomplete_line is None:
                    self.warn_once('EOFError during recvline. Returning buffered data without trailing newline.')
                return self.buffer.get()
            raise

    def recvline_pred(self, pred, keepends=None, drop=None, timeout=default):
        r"""recvline_pred(pred, drop=True, timeout=default) -> bytes

        Receive data until ``pred(line)`` returns a truthy value.
        Drop all other data.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        Arguments:
            pred(callable): Function to call.  Returns the line for which
                this function returns :const:`True`.
            drop(bool): Drop the line ending (:const:`True`).

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b"Foo\nBar\nBaz\n"
            >>> t.recvline_pred(lambda line: line == b"Bar\n")
            b'Bar'
            >>> t.recvline_pred(lambda line: line == b"Bar\n", True)
            b'Bar\n'
            >>> t.recvline_pred(lambda line: line == b"Bar\n", drop=False)
            b'Bar\n'
            >>> t.recvline_pred(lambda line: line == b'Nope!', timeout=0.1)
            b''
        """
        drop = self._normalize_keepends_drop(keepends, drop, True)
        del keepends

        tmpbuf = Buffer()
        line   = b''
        with self.countdown(timeout):
            while self.countdown_active():
                try:
                    line = self.recvline(drop=False)
                except Exception:
                    self.buffer.unget(tmpbuf)
                    raise

                if not line:
                    self.buffer.unget(tmpbuf)
                    return b''

                if pred(line):
                    if drop:
                        line = line.rstrip(self.newline)
                    return line
                else:
                    tmpbuf.add(line)

        return b''

    def recvline_contains(self, items, keepends=None, drop=None, timeout=default):
        r"""recvline_contains(items, drop=True, timeout=default) -> bytes

        Receive lines until one line is found which contains at least
        one of `items`.

        Arguments:
            items(str,tuple): List of strings to search for, or a single string.
            drop(bool): Drop the line ending (:const:`True`).
            timeout(int): Timeout, in seconds

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b"Hello\nWorld\nXylophone\n"
            >>> t.recvline_contains(b'r')
            b'World'
            >>> f = lambda n: b"cat dog bird\napple pear orange\nbicycle car train\n"
            >>> t = tube()
            >>> t.recv_raw = f
            >>> t.recvline_contains(b'pear')
            b'apple pear orange'
            >>> t = tube()
            >>> t.recv_raw = f
            >>> t.recvline_contains((b'car', b'train'))
            b'bicycle car train'
        """
        if isinstance(items, (bytes, bytearray, six.text_type)):
            items = (items,)
        items = tuple(map(packing._need_bytes, items))

        def pred(line):
            return any(d in line for d in items)

        return self.recvline_pred(pred, keepends=keepends, drop=drop, timeout=timeout)

    def recvline_startswith(self, delims, keepends=None, drop=None, timeout=default):
        r"""recvline_startswith(delims, drop=True, timeout=default) -> bytes

        Keep receiving lines until one is found that starts with one of
        `delims`.  Returns the last line received.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        Arguments:
            delims(str,tuple): List of strings to search for, or string of single characters
            drop(bool): Drop the line ending (:const:`True`).
            timeout(int): Timeout, in seconds

        Returns:
            The first line received which starts with a delimiter in ``delims``.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b"Hello\nWorld\nXylophone\n"
            >>> t.recvline_startswith((b'W',b'X',b'Y',b'Z'))
            b'World'
            >>> t.recvline_startswith((b'W',b'X',b'Y',b'Z'), drop=False)
            b'Xylophone\n'
            >>> t.recvline_startswith(b'Wo')
            b'World'
        """
        # Convert string into singleton tupple
        if isinstance(delims, (bytes, bytearray, six.text_type)):
            delims = (delims,)
        delims = tuple(map(packing._need_bytes, delims))

        return self.recvline_pred(lambda line: any(map(line.startswith, delims)),
                                  keepends=keepends,
                                  drop=drop,
                                  timeout=timeout)

    def recvline_endswith(self, delims, keepends=None, drop=None, timeout=default):
        r"""recvline_endswith(delims, drop=True, timeout=default) -> bytes

        Keep receiving lines until one is found that ends with one of
        `delims`.  Returns the last line received.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        See :meth:`recvline_startswith` for more details.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b'Foo\nBar\nBaz\nKaboodle\n'
            >>> t.recvline_endswith(b'r')
            b'Bar'
            >>> t.recvline_endswith((b'a',b'b',b'c',b'd',b'e'), drop=False)
            b'Kaboodle\n'
            >>> t.recvline_endswith(b'oodle')
            b'Kaboodle'
        """
        # Convert string into singleton tupple
        if isinstance(delims, (bytes, bytearray, six.text_type)):
            delims = (delims,)

        delims = tuple(packing._need_bytes(delim) + self.newline for delim in delims)

        return self.recvline_pred(lambda line: any(map(line.endswith, delims)),
                                  keepends=keepends,
                                  drop=drop,
                                  timeout=timeout)

    def recvregex(self, regex, exact=False, timeout=default, capture=False):
        r"""recvregex(regex, exact=False, timeout=default, capture=False) -> bytes

        Wrapper around :func:`recvpred`, which will return when a regex
        matches the string in the buffer.

        Returns all received data up until the regex matched. If `capture` is
        set to True, a :class:`re.Match` object is returned instead.

        By default :func:`re.RegexObject.search` is used, but if `exact` is
        set to True, then :func:`re.RegexObject.match` will be used instead.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.

        Examples:

            >>> t = tube()
            >>> t.recv_raw = lambda n: b'The lucky number is 1337 as always\nBla blubb blargh\n'
            >>> m = t.recvregex(br'number is ([0-9]+) as always\n', capture=True)
            >>> m.group(1)
            b'1337'
            >>> t.recvregex(br'Bla .* blargh\n')
            b'Bla blubb blargh\n'
        """

        if isinstance(regex, (bytes, bytearray, six.text_type)):
            regex = packing._need_bytes(regex)
            regex = re.compile(regex)

        if exact:
            pred = regex.match
        else:
            pred = regex.search

        if capture:
            return pred(self.recvpred(pred, timeout = timeout))
        else:
            return self.recvpred(pred, timeout = timeout)

    def recvline_regex(self, regex, exact=False, keepends=None, drop=None, timeout=default):
        """recvline_regex(regex, exact=False, drop=True, timeout=default) -> bytes

        Wrapper around :func:`recvline_pred`, which will return when a regex
        matches a line.

        By default :func:`re.RegexObject.search` is used, but if `exact` is
        set to True, then :func:`re.RegexObject.match` will be used instead.

        If the request is not satisfied before ``timeout`` seconds pass,
        all data is buffered and an empty string (``''``) is returned.
        """

        if isinstance(regex, (bytes, bytearray, six.text_type)):
            regex = packing._need_bytes(regex)
            regex = re.compile(regex)

        if exact:
            pred = regex.match
        else:
            pred = regex.search

        return self.recvline_pred(pred, keepends=keepends, drop=drop, timeout=timeout)

    def recvrepeat(self, timeout=default):
        """recvrepeat(timeout=default) -> bytes

        Receives data until a timeout or EOF is reached.

        Examples:

            >>> data = [
            ... b'd',
            ... b'', # simulate timeout
            ... b'c',
            ... b'b',
            ... b'a',
            ... ]
            >>> def delayrecv(n, data=data):
            ...     return data.pop()
            >>> t = tube()
            >>> t.recv_raw = delayrecv
            >>> t.recvrepeat(0.2)
            b'abc'
            >>> t.recv()
            b'd'
        """

        try:
            while self._fillbuffer(timeout=timeout):
                pass
        except EOFError:
            pass

        return self.buffer.get()

    def recvall(self, timeout=Timeout.forever):
        """recvall(timeout=Timeout.forever) -> bytes

        Receives data until EOF is reached and closes the tube.
        """

        with self.waitfor('Receiving all data') as h:
            l = len(self.buffer)
            with self.local(timeout):
                try:
                    while True:
                        l = misc.size(len(self.buffer))
                        h.status(l)
                        if not self._fillbuffer():
                            break
                except EOFError:
                    pass
            h.success("Done (%s)" % l)
        self.close()

        return self.buffer.get()

    def send(self, data):
        """send(data)

        Sends data.

        If log level ``DEBUG`` is enabled, also prints out the data
        received.

        If it is not possible to send anymore because of a closed
        connection, it raises ``exceptions.EOFError``

        Examples:

            >>> def p(x): print(repr(x))
            >>> t = tube()
            >>> t.send_raw = p
            >>> t.send(b'hello')
            b'hello'
        """

        data = packing._need_bytes(data)

        if self.isEnabledFor(logging.DEBUG):
            self.debug('Sent %#x bytes:' % len(data))
            self.maybe_hexdump(data, level=logging.DEBUG)

        self.send_raw(data)

    def sendline(self, line=b''):
        r"""sendline(data)

        Shorthand for ``t.send(data + t.newline)``.

        Examples:

            >>> def p(x): print(repr(x))
            >>> t = tube()
            >>> t.send_raw = p
            >>> t.sendline(b'hello')
            b'hello\n'
            >>> t.newline = b'\r\n'
            >>> t.sendline(b'hello')
            b'hello\r\n'
        """

        line = packing._need_bytes(line)

        self.send(line + self.newline)

    def sendlines(self, lines=[]):
        for line in lines:
            line = packing._need_bytes(line)
            self.sendline(line)

    def sendafter(self, delim, data, timeout = default):
        """sendafter(delim, data, timeout = default) -> str

        A combination of ``recvuntil(delim, timeout=timeout)`` and ``send(data)``.
        """

        data = packing._need_bytes(data)
        res = self.recvuntil(delim, timeout=timeout)
        self.send(data)
        return res

    def sendlineafter(self, delim, data, timeout = default):
        """sendlineafter(delim, data, timeout = default) -> str

        A combination of ``recvuntil(delim, timeout=timeout)`` and ``sendline(data)``."""

        data = packing._need_bytes(data)
        res = self.recvuntil(delim, timeout=timeout)
        self.sendline(data)
        return res

    def sendthen(self, delim, data, timeout = default):
        """sendthen(delim, data, timeout = default) -> str

        A combination of ``send(data)`` and ``recvuntil(delim, timeout=timeout)``."""

        data = packing._need_bytes(data)
        self.send(data)
        return self.recvuntil(delim, timeout=timeout)

    def sendlinethen(self, delim, data, timeout = default):
        """sendlinethen(delim, data, timeout = default) -> str

        A combination of ``sendline(data)`` and ``recvuntil(delim, timeout=timeout)``."""

        data = packing._need_bytes(data)
        self.sendline(data)
        return self.recvuntil(delim, timeout=timeout)

    def interactive(self, prompt = term.text.bold_red('$') + ' '):
        """interactive(prompt = pwnlib.term.text.bold_red('$') + ' ')

        Does simultaneous reading and writing to the tube. In principle this just
        connects the tube to standard in and standard out, but in practice this
        is much more usable, since we are using :mod:`pwnlib.term` to print a
        floating prompt.

        Thus it only works while in :data:`pwnlib.term.term_mode`.
        """

        self.info('Switching to interactive mode')

        go = threading.Event()
        def recv_thread():
            while not go.is_set():
                try:
                    cur = self.recv(timeout = 0.05)
                    cur = cur.replace(self.newline, b'\n')
                    if cur:
                        stdout = sys.stdout
                        if not term.term_mode:
                            stdout = getattr(stdout, 'buffer', stdout)
                        stdout.write(cur)
                        stdout.flush()
                except EOFError:
                    self.info('Got EOF while reading in interactive')
                    break

        t = context.Thread(target = recv_thread)
        t.daemon = True
        t.start()

        from pwnlib.args import term_mode
        try:
            os_linesep = os.linesep.encode()
            to_skip = b''
            while not go.is_set():
                if term.term_mode:
                    data = term.readline.readline(prompt = prompt, float = True)
                    if data.endswith(b'\n') and self.newline != b'\n':
                        data = data[:-1] + self.newline
                else:
                    stdin = getattr(sys.stdin, 'buffer', sys.stdin)
                    data = stdin.read(1)
                    # Keep OS's line separator if NOTERM is set and
                    # the user did not specify a custom newline
                    # even if stdin is a tty.
                    if sys.stdin.isatty() and (
                        term_mode
                        or context.newline != b"\n"
                        or self._newline is not None
                    ):
                        if to_skip:
                            if to_skip[:1] != data:
                                data = os_linesep[: -len(to_skip)] + data
                            else:
                                to_skip = to_skip[1:]
                                if to_skip:
                                    continue
                                data = self.newline
                        # If we observe a prefix of the line separator in a tty,
                        # assume we'll see the rest of it immediately after.
                        # This could stall until the next character is seen if
                        # the line separator is started but never finished, but
                        # that is unlikely to happen in a dynamic tty.
                        elif data and os_linesep.startswith(data):
                            if len(os_linesep) > 1:
                                to_skip = os_linesep[1:]
                                continue
                            data = self.newline

                if data:
                    try:
                        self.send(data)
                    except EOFError:
                        go.set()
                        self.info('Got EOF while sending in interactive')
                else:
                    go.set()
        except KeyboardInterrupt:
            self.info('Interrupted')
            go.set()

        while t.is_alive():
            t.join(timeout = 0.1)

    def stream(self, line_mode=True):
        """stream()

        Receive data until the tube exits, and print it to stdout.

        Similar to :func:`interactive`, except that no input is sent.

        Similar to ``print(tube.recvall())`` except that data is printed
        as it is received, rather than after all data is received.

        Arguments:
            line_mode(bool): Whether to receive line-by-line or raw data.

        Returns:
            All data printed.
        """
        buf = Buffer()
        function = self.recvline if line_mode else self.recv
        try:
            while True:
                buf.add(function())
                stdout = sys.stdout
                if not term.term_mode:
                    stdout = getattr(stdout, 'buffer', stdout)
                stdout.write(buf.data[-1])
        except KeyboardInterrupt:
            pass
        except EOFError:
            pass

        return buf.get()

    def clean(self, timeout = 0.05):
        """clean(timeout = 0.05)

        Removes all the buffered data from a tube by calling
        :meth:`pwnlib.tubes.tube.tube.recv` with a low timeout until it fails.

        If ``timeout`` is zero, only cached data will be cleared.

        Note: If timeout is set to zero, the underlying network is
        not actually polled; only the internal buffer is cleared.

        Returns:

            All data received

        Examples:

            >>> t = tube()
            >>> t.unrecv(b'clean me up')
            >>> t.clean(0)
            b'clean me up'
            >>> len(t.buffer)
            0
        """
        if timeout == 0:
            return self.buffer.get()

        return self.recvrepeat(timeout)

    def clean_and_log(self, timeout = 0.05):
        r"""clean_and_log(timeout = 0.05)

        Works exactly as :meth:`pwnlib.tubes.tube.tube.clean`, but logs received
        data with :meth:`pwnlib.self.info`.

        Returns:

            All data received

        Examples:

            >>> def recv(n, data=[b'', b'hooray_data']):
            ...     while data: return data.pop()
            >>> t = tube()
            >>> t.recv_raw      = recv
            >>> t.connected_raw = lambda d: True
            >>> t.fileno        = lambda: 1234
            >>> with context.local(log_level='info'):
            ...     data = t.clean_and_log()
            [...] Received 0xb bytes:
                b'hooray_data'
            >>> data
            b'hooray_data'
            >>> context.clear()
        """
        cached_data = self.buffer.get()
        if cached_data and not self.isEnabledFor(logging.DEBUG):
            with context.local(log_level='debug'):
                self.debug('Received %#x bytes:' % len(cached_data))
                self.maybe_hexdump(cached_data, level=logging.DEBUG)
        with context.local(log_level='debug'):
            return cached_data + self.clean(timeout)

    def upload_manually(self, data, target_path = './payload', prompt = b'$', chunk_size = 0x200, chmod_flags = 'u+x', compression='auto', end_marker = 'PWNTOOLS_DONE'):
        """upload_manually(data, target_path = './payload', prompt = b'$', chunk_size = 0x200, chmod_flags = 'u+x', compression='auto', end_marker = 'PWNTOOLS_DONE')

        Upload a file manually using base64 encoding and compression.
        This can be used when the tube is connected to a shell.

        The file is uploaded in base64-encoded chunks by appending to a file
        and then decompressing it:

        .. code-block::

            loop:
                echo <chunk> | base64 -d >> <target_path>.<compression>
            <compression> -d -f <target_path>.<compression>
            chmod <chmod_flags> <target_path>

        It is assumed that a `base64` command is available on the target system.
        When ``compression`` is ``auto`` the best compression utility available
        between ``gzip`` and ``xz`` is chosen with a fallback to uncompressed
        upload.

        Arguments:

            data(bytes): The data to upload.
            target_path(str): The path to upload the data to.
            prompt(bytes): The shell prompt to wait for.
            chunk_size(int): The size of each chunk to upload.
            chmod_flags(str): The flags to use with chmod. ``""`` to ignore.
            compression(str): The compression to use. ``auto`` to automatically choose the best compression or ``gzip`` or ``xz``.	
            end_marker(str): The marker to use to detect the end of the output. Only used when prompt is not set.

        Examples:

        .. doctest::
            :options: +POSIX +TODO

            >>> l = listen()
            >>> l.spawn_process('/bin/sh')
            >>> r = remote('127.0.0.1', l.lport)
            >>> r.upload_manually(b'some\\xca\\xfedata\\n', prompt=b'', chmod_flags='')
            >>> r.sendline(b'cat ./payload')
            >>> r.recvline()
            b'some\\xca\\xfedata\\n'

            >>> r.upload_manually(cyclic(0x1000), target_path='./cyclic_pattern', prompt=b'', chunk_size=0x10, compression='gzip')
            >>> r.sendline(b'sha256sum ./cyclic_pattern')
            >>> r.recvlineS(keepends=False).startswith(sha256sumhex(cyclic(0x1000)))
            True

            >>> blob = ELF.from_assembly(shellcraft.echo('Hello world!\\n') + shellcraft.exit(0))
            >>> r.upload_manually(blob.data, prompt=b'')
            >>> r.sendline(b'./payload')
            >>> r.recvline()
            b'Hello world!\\n'
            >>> r.close()
            >>> l.close()
        """
        echo_end = ""
        if not prompt:
            echo_end = "; echo {}".format(end_marker)
            end_markerb = end_marker.encode()
        else:
            end_markerb = prompt

        # Detect available compression utility, fallback to uncompressed upload.
        compression_mode = None
        possible_compression = ['gzip']
        if six.PY3:
            possible_compression.insert(0, 'xz')
        if not prompt:
            self.sendline("echo {}".format(end_marker).encode())
        if compression == 'auto':
            for utility in possible_compression:
                self.sendlineafter(end_markerb, "command -v {} && echo YEP || echo NOPE{}".format(utility, echo_end).encode())
                result = self.recvuntil([b'YEP', b'NOPE'])
                if b'YEP' in result:
                    compression_mode = utility
                    break
        elif compression in possible_compression:
            compression_mode = compression
        else:
            self.error('Invalid compression mode: %s, has to be one of %s', compression, possible_compression)

        self.debug('Manually uploading using compression mode: %s', compression_mode)

        compressed_data = b''
        if compression_mode == 'xz':
            import lzma
            compressed_data = lzma.compress(data, format=lzma.FORMAT_XZ, preset=9)
            compressed_path = target_path + '.xz'
        elif compression_mode == 'gzip':
            import gzip
            from six import BytesIO
            f = BytesIO()
            with gzip.GzipFile(fileobj=f, mode='wb', compresslevel=9) as g:
                g.write(data)
            compressed_data = f.getvalue()
            compressed_path = target_path + '.gz'
        else:
            compressed_path = target_path

        # Don't compress if it doesn't reduce the size.
        if len(compressed_data) >= len(data):
            compression_mode = None
            compressed_path = target_path
        else:
            data = compressed_data

        # Upload data in `chunk_size` chunks. Assume base64 is available.
        with self.progress('Uploading payload') as p:
            for idx, chunk in enumerate(iters.group(chunk_size, data)):
                if None in chunk:
                    chunk = chunk[:chunk.index(None)]
                if idx == 0:
                    self.sendlineafter(end_markerb, "echo {} | base64 -d > {}{}".format(fiddling.b64e(bytearray(chunk)), compressed_path, echo_end).encode())
                else:
                    self.sendlineafter(end_markerb, "echo {} | base64 -d >> {}{}".format(fiddling.b64e(bytearray(chunk)), compressed_path, echo_end).encode())
                p.status('{}/{} {}'.format(idx+1, len(data)//chunk_size+1, misc.size(idx*chunk_size + len(chunk))))
            p.success(misc.size(len(data)))

        # Decompress the file and set the permissions.
        if compression_mode is not None:
            self.sendlineafter(end_markerb, '{} -d -f {}{}'.format(compression_mode, compressed_path, echo_end).encode())
        if chmod_flags:
            self.sendlineafter(end_markerb, 'chmod {} {}{}'.format(chmod_flags, target_path, echo_end).encode())
        if not prompt:
            self.recvuntil(end_markerb + b'\n')

    def connect_input(self, other):
        """connect_input(other)

        Connects the input of this tube to the output of another tube object.


        Examples:

            >>> def p(x): print(x.decode())
            >>> def recvone(n, data=[b'data']):
            ...     while data: return data.pop()
            ...     raise EOFError
            >>> a = tube()
            >>> b = tube()
            >>> a.recv_raw = recvone
            >>> b.send_raw = p
            >>> a.connected_raw = lambda d: True
            >>> b.connected_raw = lambda d: True
            >>> a.shutdown      = lambda d: True
            >>> b.shutdown      = lambda d: True
            >>> import time
            >>> _=(b.connect_input(a), time.sleep(0.1))
            data
        """

        def pump():
            import sys as _sys
            while self.countdown_active():
                if not (self.connected('send') and other.connected('recv')):
                    break

                try:
                    data = other.recv(timeout = 0.05)
                except EOFError:
                    break

                if not _sys:
                    return

                if not data:
                    continue

                try:
                    self.send(data)
                except EOFError:
                    break

                if not _sys:
                    return

            self.shutdown('send')
            other.shutdown('recv')

        t = context.Thread(target = pump)
        t.daemon = True
        t.start()

    def connect_output(self, other):
        """connect_output(other)

        Connects the output of this tube to the input of another tube object.

        Examples:

            >>> def p(x): print(repr(x))
            >>> def recvone(n, data=[b'data']):
            ...     while data: return data.pop()
            ...     raise EOFError
            >>> a = tube()
            >>> b = tube()
            >>> a.recv_raw = recvone
            >>> b.send_raw = p
            >>> a.connected_raw = lambda d: True
            >>> b.connected_raw = lambda d: True
            >>> a.shutdown      = lambda d: True
            >>> b.shutdown      = lambda d: True
            >>> _=(a.connect_output(b), time.sleep(0.1))
            b'data'
        """

        other.connect_input(self)

    def connect_both(self, other):
        """connect_both(other)

        Connects the both ends of this tube object with another tube object."""

        self.connect_input(other)
        self.connect_output(other)

    def spawn_process(self, *args, **kwargs):
        """Spawns a new process having this tube as stdin, stdout and stderr.

        Takes the same arguments as :class:`subprocess.Popen`."""

        return subprocess.Popen(
            *args,
            stdin = self.fileno(),
            stdout = self.fileno(),
            stderr = self.fileno(),
            **kwargs
        )

    def __lshift__(self, other):
        """
        Shorthand for connecting multiple tubes.

        See :meth:`connect_input` for more information.

        Examples:

            The following are equivalent ::

                tube_a >> tube.b
                tube_a.connect_input(tube_b)

            This is useful when chaining multiple tubes ::

                tube_a >> tube_b >> tube_a
                tube_a.connect_input(tube_b)
                tube_b.connect_input(tube_a)
        """
        self.connect_input(other)
        return other

    def __rshift__(self, other):
        """
        Inverse of the ``<<`` operator.  See :meth:`__lshift__`.

        See :meth:`connect_input` for more information.
        """
        self.connect_output(other)
        return other

    def __ne__(self, other):
        """
        Shorthand for connecting tubes to eachother.

        The following are equivalent ::

            a >> b >> a
            a <> b

        See :meth:`connect_input` for more information.
        """
        self << other << self

    def wait_for_close(self, timeout=default):
        """Waits until the tube is closed."""

        with self.countdown(timeout):
            while self.countdown_active():
                if not self.connected():
                    return
                time.sleep(min(self.timeout, 0.05))

    wait = wait_for_close

    def can_recv(self, timeout = 0):
        """can_recv(timeout = 0) -> bool

        Returns True, if there is data available within `timeout` seconds.

        Examples:

            >>> import time
            >>> t = tube()
            >>> t.can_recv_raw = lambda *a: False
            >>> t.can_recv()
            False
            >>> _=t.unrecv(b'data')
            >>> t.can_recv()
            True
            >>> _=t.recv()
            >>> t.can_recv()
            False
        """

        return bool(self.buffer or self.can_recv_raw(timeout))

    def settimeout(self, timeout):
        """settimeout(timeout)

        Set the timeout for receiving operations. If the string "default"
        is given, then :data:`context.timeout` will be used. If None is given,
        then there will be no timeout.

        Examples:

            >>> t = tube()
            >>> t.settimeout_raw = lambda t: None
            >>> t.settimeout(3)
            >>> t.timeout == 3
            True
        """

        self.timeout = timeout


    shutdown_directions = {
        'in':    'recv',
        'read':  'recv',
        'recv':  'recv',
        'out':   'send',
        'write': 'send',
        'send':  'send',
    }

    connected_directions = shutdown_directions.copy()
    connected_directions['any'] = 'any'

    def shutdown(self, direction = "send"):
        """shutdown(direction = "send")

        Closes the tube for futher reading or writing depending on `direction`.

        Arguments:
          direction(str): Which direction to close; "in", "read" or "recv"
            closes the tube in the ingoing direction, "out", "write" or "send"
            closes it in the outgoing direction.

        Returns:
          :const:`None`

        Examples:

            >>> def p(x): print(x)
            >>> t = tube()
            >>> t.shutdown_raw = p
            >>> _=list(map(t.shutdown, ('in', 'read', 'recv', 'out', 'write', 'send')))
            recv
            recv
            recv
            send
            send
            send
            >>> t.shutdown('bad_value')
            Traceback (most recent call last):
            ...
            KeyError: "direction must be in ['in', 'out', 'read', 'recv', 'send', 'write']"
        """
        try:
            direction = self.shutdown_directions[direction]
        except KeyError:
            raise KeyError('direction must be in %r' % sorted(self.shutdown_directions))
        else:
            self.shutdown_raw(self.shutdown_directions[direction])

    def connected(self, direction = 'any'):
        """connected(direction = 'any') -> bool

        Returns True if the tube is connected in the specified direction.

        Arguments:
          direction(str): Can be the string 'any', 'in', 'read', 'recv',
                          'out', 'write', 'send'.

        Doctest:

            >>> def p(x): print(x)
            >>> t = tube()
            >>> t.connected_raw = p
            >>> _=list(map(t.connected, ('any', 'in', 'read', 'recv', 'out', 'write', 'send')))
            any
            recv
            recv
            recv
            send
            send
            send
            >>> t.connected('bad_value')
            Traceback (most recent call last):
            ...
            KeyError: "direction must be in ['any', 'in', 'out', 'read', 'recv', 'send', 'write']"
        """
        try:
            direction = self.connected_directions[direction]
        except KeyError:
            raise KeyError('direction must be in %r' % sorted(self.connected_directions))
        else:
            return self.connected_raw(direction)

    def __enter__(self):
        """Permit use of 'with' to control scoping and closing sessions.

        Examples:

            >>> t = tube()
            >>> def p(x): print(x)
            >>> t.close = lambda: p("Closed!")
            >>> with t: pass
            Closed!
        """
        return self

    def __exit__(self, type, value, traceback):
        """Handles closing for 'with' statement

        See :meth:`__enter__`
        """
        self.close()

    # The minimal interface to be implemented by a child
    @abc.abstractmethod
    def recv_raw(self, numb):
        """recv_raw(numb) -> str

        Should not be called directly. Receives data without using the buffer
        on the object.

        Unless there is a timeout or closed connection, this should always
        return data. In case of a timeout, it should return None, in case
        of a closed connection it should raise an ``exceptions.EOFError``.
        """

        raise EOFError('Not implemented')

    @abc.abstractmethod
    def send_raw(self, data):
        """send_raw(data)

        Should not be called directly. Sends data to the tube.

        Should return ``exceptions.EOFError``, if it is unable to send any
        more, because of a closed tube.
        """

        raise EOFError('Not implemented')

    def settimeout_raw(self, timeout):
        """settimeout_raw(timeout)

        Should not be called directly. Sets the timeout for
        the tube.
        """

        raise NotImplementedError()

    def timeout_change(self):
        """
        Should not be called directly. Informs the raw layer of the tube that the timeout has changed.


        Inherited from :class:`Timeout`.
        """
        try:
            self.settimeout_raw(self.timeout)
        except NotImplementedError:
            pass

    def can_recv_raw(self, timeout):
        """can_recv_raw(timeout) -> bool

        Should not be called directly. Returns True, if
        there is data available within the timeout, but
        ignores the buffer on the object.
        """

        raise NotImplementedError()

    def connected_raw(self, direction):
        """connected(direction = 'any') -> bool

        Should not be called directly.  Returns True iff the
        tube is connected in the given direction.
        """

        raise NotImplementedError()

    def close(self):
        """close()

        Closes the tube.
        """
        pass
        # Ideally we could:
        # raise NotImplementedError()
        # But this causes issues with the unit tests.

    def fileno(self):
        """fileno() -> int

        Returns the file number used for reading.
        """

        raise NotImplementedError()

    def shutdown_raw(self, direction):
        """shutdown_raw(direction)

        Should not be called directly.  Closes the tube for further reading or
        writing.
        """

        raise NotImplementedError()


    def p64(self, *a, **kw):        return self.send(packing.p64(*a, **kw))
    def p32(self, *a, **kw):        return self.send(packing.p32(*a, **kw))
    def p16(self, *a, **kw):        return self.send(packing.p16(*a, **kw))
    def p8(self, *a, **kw):         return self.send(packing.p8(*a, **kw))
    def pack(self, *a, **kw):       return self.send(packing.pack(*a, **kw))

    def u64(self, *a, **kw):        return packing.u64(self.recvn(8), *a, **kw)
    def u32(self, *a, **kw):        return packing.u32(self.recvn(4), *a, **kw)
    def u16(self, *a, **kw):        return packing.u16(self.recvn(2), *a, **kw)
    def u8(self, *a, **kw):         return packing.u8(self.recvn(1), *a, **kw)
    def unpack(self, *a, **kw):     return packing.unpack(self.recvn(context.bytes), *a, **kw)

    def flat(self, *a, **kw):       return self.send(packing.flat(*a,**kw))
    def fit(self, *a, **kw):        return self.send(packing.fit(*a, **kw))

    # Dynamic functions

    def make_wrapper(func):
        def wrapperb(self, *a, **kw):
            return bytearray(func(self, *a, **kw))
        def wrapperS(self, *a, **kw):
            return packing._decode(func(self, *a, **kw))
        wrapperb.__doc__ = 'Same as :meth:`{func.__name__}`, but returns a bytearray'.format(func=func)
        wrapperb.__name__ = func.__name__ + 'b'
        wrapperS.__doc__ = 'Same as :meth:`{func.__name__}`, but returns a str, ' \
                           'decoding the result using `context.encoding`. ' \
                           '(note that the binary versions are way faster)'.format(func=func)
        wrapperS.__name__ = func.__name__ + 'S'
        return wrapperb, wrapperS

    for func in [recv,
                 recvn,
                 recvall,
                 recvrepeat,
                 recvuntil,
                 recvpred,
                 recvregex,
                 recvline,
                 recvline_contains,
                 recvline_startswith,
                 recvline_endswith,
                 recvline_regex]:
        for wrapper in make_wrapper(func):
            locals()[wrapper.__name__] = wrapper

    def make_wrapper(func, alias):
        def wrapper(self, *a, **kw):
            return func(self, *a, **kw)
        wrapper.__doc__ = 'Alias for :meth:`{func.__name__}`'.format(func=func)
        wrapper.__name__ = alias
        return wrapper

    for _name in list(locals()):
        if 'recv' in _name:
            _name2 = _name.replace('recv', 'read')
        elif 'send' in _name:
            _name2 = _name.replace('send', 'write')
        else:
            continue
        locals()[_name2] = make_wrapper(locals()[_name], _name2)

    # Clean up the scope
    del wrapper, func, make_wrapper, _name, _name2
