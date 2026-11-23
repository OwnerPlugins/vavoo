#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import calendar
import glob
import hashlib
try:
    import six
except ImportError:
    # six is a hard runtime dependency (python3-six, declared in
    # CONTROL/control) used throughout this module for Py2/3 text
    # helpers - there is no functional fallback without it, but a clear
    # message here beats a bare traceback on images missing the package.
    print("[VUTILS] FATAL: 'six' package not found - install python3-six")
    raise
import socket
import ssl
import select
import threading
import types
try:
    import urllib3
except ImportError:
    urllib3 = None
import xml.etree.ElementTree as ET
try:
    # Python 2: the C parser lives here (plain ElementTree is the
    # slow pure-Python one there). Gone in Python 3.9+, where
    # ElementTree itself already is the C parser.
    import xml.etree.cElementTree as _fast_ET
except ImportError:
    _fast_ET = ET
import zlib
from datetime import datetime as _datetime
from collections import OrderedDict
from difflib import SequenceMatcher
from json import dump, load, loads
from Components.config import config
from os import listdir, makedirs, remove, unlink, rename
from os.path import basename, exists, getmtime, getsize, isfile, join, splitext
from enigma import eTimer
from random import choice
from re import DOTALL, IGNORECASE, compile, search, sub
from shutil import copy2
from sys import maxsize
from six import iteritems, unichr
from six.moves import html_entities, html_parser
from time import time, strftime, localtime, gmtime, sleep
from unicodedata import combining, normalize
from email.utils import parsedate_tz, mktime_tz

from . import (
    __version__,
    country_codes,
    PY2,
    PY3,
    PORT,
    PLUGIN_ROOT,
    PROXY_HOST,
    FLAG_CACHE_DIR,
    PICON_CACHE_DIR,
    group_separators,
    LOG_FILE,
    CACHE_FILE,
    UNMATCHED_FILE,
    HOST_MAIN,
    EPG_COPY_URL,
    EPG_DAILY_SOURCES,
    EPG_DAILY_URL,
    ALIAS_FILE,
    INSTALLER_URL,
    ENIGMA_PATH,
)
from . import vavoo_store
from .epg_name_utils import (
    clean_name_for_similarity,
    tokenize_for_compat,
    token_pair_compatible,
    tokens_compatible,
)
"""
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin                             #
#  Created by Lululla (https://github.com/Belfagor2005) #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0    #
#  Last Modified: 202600503                             #
#                                                       #
#  Credits:                                             #
#  - Original concept by Lululla                        #
#  - Background images by @oktus                        #
#  - Additional contributions by Qu4k3                  #
#  - Linuxsat-support.com & Corvoboys communities       #
#                                                       #
#  Usage of this code without proper attribution        #
#  is strictly prohibited.                              #
#  For modifications and redistribution,                #
#  please maintain this credit header.                  #
#########################################################
"""

# Disable SSL warnings
if urllib3 is not None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
_original_getaddrinfo = socket.getaddrinfo

try:
    from . import channel_alias
    alias_available = True
except Exception:
    alias_available = False
    print("[VavooEPGMatcher] channel_alias module not found, using default matching")
    pass


try:
    import requests
except Exception:
    requests = None


try:
    unicode
except NameError:
    unicode = str

try:
    from Components.AVSwitch import AVSwitch
except ImportError:
    from Components.AVSwitch import eAVControl as AVSwitch


_epg_lock = threading.Lock()
_starting_lock = threading.Lock()
_unmatched_lock = threading.Lock()
# CACHE_FILE's own read-modify-write (save_cache(), update_complete_cache(),
# fix_cache_format()). Never export_lock here: an export holds that for
# its whole run and calls find_match() inside it - a plain Lock asked
# for again by the same thread never comes back (a box's scheduled
# bouquet update hung for good at the first cached channel the feed no
# longer had, and every export after it was refused until a reboot).
_cache_file_lock = threading.Lock()

LOG_MAX_BYTES = 1024 * 1024
DEBUG_ENABLED = str(
    __import__("os").environ.get(
        "VAVOO_DEBUG",
        "0")).lower() in (
            "1",
            "true",
            "yes",
    "on")


def set_debug_enabled(enabled):
    """Toggle DEBUG-level logging at runtime (config menu "Debug logging").

    VAVOO_DEBUG only takes effect at process start and, since the proxy
    runs as a thread inside the same Enigma2 process, an env var set in
    an SSH session never reaches it anyway (Enigma2 itself is started
    by the box's init supervisor, not that shell). This is checked on
    every debug() call instead, so a config toggle takes effect
    immediately with no restart needed.
    """
    global DEBUG_ENABLED
    DEBUG_ENABLED = bool(enabled)


def _rotate_log_if_needed():
    try:
        if isfile(LOG_FILE) and getsize(LOG_FILE) >= LOG_MAX_BYTES:
            backup = LOG_FILE + ".1"
            try:
                if isfile(backup):
                    remove(backup)
            except Exception:
                pass
            try:
                __import__("os").rename(LOG_FILE, backup)
            except Exception:
                pass
    except Exception:
        pass


def _safe_console_write(line):
    try:
        import sys
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _append_to_log(line):
    try:
        _rotate_log_if_needed()
        if PY2:
            with open(LOG_FILE, "a") as log_file:
                log_file.write(line + "\n")
        else:
            # (UTF-8 whatever the box's locale is)
            with open(LOG_FILE, "a", encoding="utf-8", errors="replace") as log_file:
                log_file.write(line + "\n")
    except Exception:
        pass


def log(msg, level="INFO", area="VUTILS"):
    """One line into vavoo.log (and the console). Never raises: on
    Python 2 the line is built as unicode and written as UTF-8 bytes -
    a byte-string template with a non-ASCII message (every "✓" / "✗"
    line, an accented channel name) used to raise UnicodeEncodeError
    out of print(), which stopped the proxy at its own "[✓] Ready"."""
    try:
        msg = ensure_str(msg, errors='ignore')
    except Exception:
        try:
            msg = str(msg)
        except Exception:
            msg = '<unprintable message>'
    stamp = _datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        line = u"[{0}] [{1}] [{2}] {3}".format(stamp, level, area, msg)
    except Exception:
        line = u"[{0}] [{1}] [{2}] <unprintable message>".format(
            stamp, level, area)
    if PY2:
        line = line.encode("utf-8", "replace")
    _safe_console_write(line)
    _append_to_log(line)
    return line


def debug(msg, area="VUTILS"):
    if DEBUG_ENABLED:
        return log(msg, level="DEBUG", area=area)
    return None


def warning(msg, area="VUTILS"):
    return log(msg, level="WARNING", area=area)


def error(msg, area="VUTILS"):
    return log(msg, level="ERROR", area=area)


def log_exception(msg="", area="VUTILS"):
    import traceback
    if msg:
        error(msg, area=area)
    try:
        tb = traceback.format_exc()
        if not tb or tb.strip() == "NoneType: None":
            tb = "".join(traceback.format_stack()[:-1])
        for line in tb.rstrip().splitlines():
            error(line, area=area)
    except Exception as e:
        error("Failed to capture traceback: {0}".format(e), area=area)


def trace_error(prefix="", area="VUTILS"):
    log_exception(prefix, area=area)


def plugin_print(*args, **kwargs):
    sep = kwargs.get('sep', ' ')
    end = kwargs.get('end', '\n')
    level = kwargs.get('level', 'INFO')
    area = kwargs.get('area', 'VUTILS')
    try:
        msg = sep.join([ensure_str(x, errors='ignore') for x in args])
    except Exception:
        try:
            msg = sep.join([str(x) for x in args])
        except Exception:
            msg = '<print formatting error>'
    if end and msg.endswith('\n'):
        msg = msg.rstrip('\n')
    return log(msg, level=level, area=area)


def make_print(area, level="INFO"):
    """Return a drop-in print() replacement that routes through log()."""
    def _module_print(*args, **kwargs):
        kwargs.setdefault("area", area)
        kwargs.setdefault("level", level)
        return plugin_print(*args, **kwargs)
    return _module_print


PLUGIN_PATH = PLUGIN_ROOT

# The favourites (with their folders and order), hidden countries,
# parental control and backups: vavoo_store.py, under ENIGMA_PATH - a
# plugin update deletes the plugin folder, where the favourites used
# to be (moved out by vavoo_store.migrate_old_files()).
vavoo_store.set_paths(ENIGMA_PATH, PLUGIN_PATH)
FAVOURITES_FILE = vavoo_store.favourites_file()


if PY3:
    from urllib.request import urlopen, Request
    from urllib.error import URLError, HTTPError
    ssl_context = ssl.create_default_context()
    for _ssl_opt in (
        "OP_NO_SSLv2",
        "OP_NO_SSLv3",
        "OP_NO_TLSv1",
            "OP_NO_TLSv1_1"):
        ssl_context.options |= getattr(ssl, _ssl_opt, 0)
    unichr_func = unichr
else:
    from urllib2 import urlopen, Request, URLError, HTTPError
    ssl = None
    ssl_context = None
    unichr_func = chr


print = make_print("VUTILS")


# Heavy loops (reading a country's guide, comparing a channel's name
# with thousands of others) run in background threads inside Enigma2's
# own process, next to the video and the menus. After this much work
# such a loop rests this long, so it takes at most about two thirds of
# a core and the box never stalls behind it (the box was seen
# overloaded while a guide was read).
_BREATHE_WORK = 0.05
_BREATHE_REST = 0.025
# While a stream plays such a loop gives way far more: a fifth of a
# core, Python's lock free four fifths of the time for the menus and
# for the proxy's answers to the player's playlist refresh (a box's
# channels stuttered and its menus dragged after 1.90, which reads the
# countries' guides - 13 to 47 MB each - inside Enigma2's process).
_BREATHE_WORK_PLAYING = 0.01
_BREATHE_REST_PLAYING = 0.04
# "A stream plays": the proxy was asked for one within this many
# seconds (the player comes back to /vavoo every ~10 s, bouquet
# channels watched outside the plugin too), or the plugin started one.
STREAM_WINDOW = 30
_stream_seen = [0.0]


def note_stream():
    """A stream is playing right now (the proxy's /vavoo and /file, the
    plugin's preview and player): heavy loops give way for a while -
    see _Breather and stream_playing()."""
    _stream_seen[0] = time()


def stream_playing(window=STREAM_WINDOW, now=None):
    """True while a stream plays: note_stream() within `window`
    seconds."""
    now = time() if now is None else now
    return now - _stream_seen[0] < window


class _Breather(object):
    """One per heavy loop: call tick() on every turn (cheap - the clock
    is only read every 64th). Never rests on the GUI (main) thread.
    Rests more while a stream plays (stream_playing())."""

    __slots__ = ("since", "count", "active")

    def __init__(self):
        self.since = time()
        self.count = 0
        self.active = threading.current_thread().name != "MainThread"

    def tick(self):
        if not self.active:
            return
        self.count += 1
        if self.count & 63:
            return
        now = time()
        if now - _stream_seen[0] < STREAM_WINDOW:
            work, rest = _BREATHE_WORK_PLAYING, _BREATHE_REST_PLAYING
        else:
            work, rest = _BREATHE_WORK, _BREATHE_REST
        if now - self.since >= work:
            sleep(rest)
            self.since = time()


log("===== Vavoo session start =====", area="VUTILS")


def getDNSinfo():
    """Return (local_dns, external_dns). Never raises – returns 'n/a' on failure."""
    dns_box = "n/a"
    dns_external = "n/a"
    try:
        with open("/etc/resolv.conf", "r") as f:
            for line in f:
                if line.startswith("nameserver"):
                    dns_box = line.split()[1]
                    break
    except BaseException:
        dns_box = "n/a"

    try:
        data = urlopen("https://1.1.1.1/cdn-cgi/trace", timeout=5).read()
        data = data.decode("utf-8")
        for line in data.split("\n"):
            if line.startswith("h="):
                dns_external = line.split("=")[1].strip()
                break
    except Exception as e:
        debug("External DNS check failed: {}".format(e))

    return dns_box, dns_external


def _log_dns_info_async():
    """Runs getDNSinfo() (a real network call) off the import path so
    plugin/menu load never blocks on a slow/unreachable network."""
    try:
        dns_box, dns_ext = getDNSinfo()
    except Exception:
        dns_box, dns_ext = "n/a", "n/a"
    print("DNS box:", dns_box)
    print("DNS out:", dns_ext)


print("Vavoo Version: ", __version__)

# Marks this copy of the plugin's modules. A box loaded them twice in
# one Enigma2 (the same files under a second module name - from outside
# the plugin, whose own imports are all relative): the second copy's
# proxy held the port and the screens of the first waited for their
# own for ever. vavoo_proxy now takes the port over; this says in the
# log which copy came second and what loaded it.
VAVOO_COPY = __name__


def _note_second_copy():
    import sys
    import traceback
    first = [name for name, module in list(sys.modules.items())
             if name != __name__ and module is not None and
             getattr(module, "VAVOO_COPY", None) == name]
    if not first:
        return False
    other = sys.modules[first[0]]
    print("Second copy of the plugin: {0} ({1}); first: {2} "
          "({3}) - loaded from:".format(
              __name__, __file__, first[0],
              getattr(other, "__file__", "?")))
    for frame in traceback.extract_stack()[:-1][-20:]:
        print("  {0}:{1} {2}".format(frame[0], frame[1], frame[2]))
    return True


try:
    _note_second_copy()
except Exception as e:
    print("Copy check failed: {}".format(e))

_dns_info_thread = threading.Thread(target=_log_dns_info_async)
_dns_info_thread.setDaemon(True)
_dns_info_thread.start()


def get_screen_width():
    """Get current screen width"""
    try:
        from enigma import getDesktop
        desktop = getDesktop(0)
        width = desktop.size().width()
        print("Screen width detected: %d" % width)
        return width
    except Exception as e:
        print("Error getting screen width: %s" % str(e))
        return 1920


class AspectManager(object):
    """Manages aspect ratio settings for the plugin"""

    def __init__(self):
        try:
            self.init_aspect = self.get_current_aspect()
            print("[INFO] Initial aspect ratio:", self.init_aspect)
        except Exception as e:
            print("[ERROR] Failed to initialize aspect manager:", str(e))
            self.init_aspect = 0

    def get_current_aspect(self):
        """Get current aspect ratio setting"""
        try:
            aspect = AVSwitch().getAspectRatioSetting()
            return int(aspect) if aspect is not None else 0
        except (ValueError, TypeError, Exception) as e:
            print("[ERROR] Failed to get aspect ratio:", str(e))
            return 0

    def restore_aspect(self):
        """Restore original aspect ratio"""
        try:
            if hasattr(self, 'init_aspect') and self.init_aspect is not None:
                print("[INFO] Restoring aspect ratio to:", self.init_aspect)
                AVSwitch().setAspectRatio(self.init_aspect)
            else:
                print("[WARNING] No initial aspect ratio to restore")
        except Exception as e:
            print("[ERROR] Failed to restore aspect ratio:", str(e))


aspect_manager = AspectManager()
class_types = (type,) if PY3 else (type, types.ClassType)
text_type = six.text_type
binary_type = six.binary_type
MAXSIZE = maxsize

_UNICODE_MAP = {
    k: unichr(v) for k,
    v in iteritems(
        html_entities.name2codepoint)}
_ESCAPE_RE = compile(r"[&<>\"']")
_UNESCAPE_RE = compile(r"&\s*(#?)(\w+?)\s*;")
_ESCAPE_DICT = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&apos;",
}


std_headers = {
    'User-Agent': 'Mozilla/5.0 (X11; U; Linux x86_64; en-US; rv:1.9.2.6) Gecko/20100627 Firefox/3.6.6',
    'Accept-Charset': 'ISO-8859-1,utf-8;q=0.7,*;q=0.7',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-us,en;q=0.5'}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.6312.88 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

]


def RequestAgent():
    """Get random user agent from list"""
    return choice(USER_AGENTS)


def ensure_str(s, encoding="utf-8", errors="strict"):
    if s is None:
        return ""
    if isinstance(s, text_type):
        return s
    if isinstance(s, binary_type):
        return s.decode(encoding, errors)
    return text_type(s)


def html_escape(value):
    """Escape HTML special characters"""
    value = ensure_str(value, errors='ignore').strip()
    return _ESCAPE_RE.sub(lambda m: _ESCAPE_DICT[m.group(0)], value)


def html_unescape(value):
    """Unescape HTML entities"""
    return _UNESCAPE_RE.sub(_convert_entity, ensure_str(value).strip())


def _convert_entity(m):
    """Helper for HTML entity conversion, compatible with Python 2 and 3"""
    if m.group(1) == "#":
        try:
            return unichr(int(m.group(2)[1:], 16)) if m.group(
                2)[:1].lower() == "x" else unichr(int(m.group(2)))
        except ValueError:
            return "&#%s;" % m.group(2)
    return _UNICODE_MAP.get(m.group(2), "&%s;" % m.group(2))


def _urlopen_unverified(request, timeout):
    """urlopen() the way getUrl() has always done it (certificate
    checks off), on whichever Python this box runs. Shared by getUrl()
    and open_url_stream() so the two cannot drift apart."""
    if PY3:
        import ssl
        unverified_context = ssl.create_default_context()
        unverified_context.check_hostname = False
        unverified_context.verify_mode = ssl.CERT_NONE
        return urlopen(
            request,
            timeout=timeout,
            context=unverified_context)
    # Python 2: use ssl if it is there, plain urlopen() otherwise
    try:
        import ssl
    except ImportError:
        return urlopen(request, timeout=timeout)
    # Python 2.7.9+ has ssl._create_unverified_context
    unverified_context = ssl._create_unverified_context() if hasattr(
        ssl, '_create_unverified_context') else None
    if unverified_context:
        return urlopen(
            request, timeout=timeout, context=unverified_context)
    return urlopen(request, timeout=timeout)


class _Inflated(object):
    """read(size) over another reader's gzip data, unpacked as it is
    read. Not gzip.GzipFile: on Python 2 that needs a seekable file,
    which a socket is not. zlib's own streaming decompressor has no
    such need and behaves the same on Python 2 and 3. `max_length`
    keeps each read() at about the size asked for, so a small
    compressed chunk that unpacks to megabytes never lands in memory
    all at once."""

    def __init__(self, read, pending=b''):
        self._read = read
        self._inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        self._pending = pending
        self._eof = False

    def read(self, size):
        while True:
            if self._pending:
                data = self._inflater.decompress(self._pending, size)
                self._pending = self._inflater.unconsumed_tail
                if data:
                    return data
            if self._eof:
                # Whatever the decompressor still holds, then b''
                # forever after (flush() of a drained one is empty).
                return self._inflater.flush()
            chunk = self._read(16384)
            if chunk:
                self._pending = chunk
            else:
                self._eof = True


class _HttpStream(object):
    """File-like read()/close() over an HTTP response body, unpacking
    it on the fly when it is gzip: sent compressed (Content-Encoding),
    or a .gz file itself - told by its first two bytes, as the app
    does (the daily programme guides are .xml.gz files: a server sends
    those as they are, not as an encoding). `headers`: the response's.
    """

    def __init__(self, response, compressed):
        self._response = response
        try:
            self.headers = response.info()
        except Exception:
            self.headers = {}
        # Bytes that actually came over the network.
        self.bytes_received = 0
        source = self._network_read
        if compressed:
            source = _Inflated(source).read
        self._source = source
        self._sniffed = False

    def _network_read(self, size):
        data = self._response.read(size)
        self.bytes_received += len(data)
        return data

    def _sniff(self, size):
        """The first bytes: a gzip file's (1f 8b) -> read it unpacked."""
        self._sniffed = True
        head = b''
        while len(head) < 2:
            data = self._source(max(size, 2) - len(head))
            if not data:
                break
            head += data
        if head[:2] == b'\x1f\x8b':
            self._source = _Inflated(self._source, head).read
            return b''
        return head

    def read(self, size=-1):
        if size is None or size < 0:
            chunks = []
            while True:
                chunk = self.read(65536)
                if not chunk:
                    break
                chunks.append(chunk)
            return b''.join(chunks)
        if size == 0:
            return b''
        if not self._sniffed:
            head = self._sniff(size)
            if head:
                return head
        return self._source(size)

    def close(self):
        try:
            self._response.close()
        except Exception:
            pass


def response_header(stream, name):
    """A header of an open_url_stream() answer, "" when it has none."""
    try:
        return ensure_str(stream.headers.get(name) or '', errors='ignore')
    except Exception:
        return ''


def open_url_stream(url, timeout=20):
    """Open `url` for reading piece by piece instead of loading the
    whole answer into memory the way getUrl() does. Returns a
    file-like object (read(n), close(), bytes_received, headers);
    raises on any failure - the caller decides what a failure means.

    Asks for a gzip-compressed answer. The programme-guide files this
    exists for are 2 to 60 MB of XML and GitHub serves them at roughly
    a tenth of that when asked (16.7 MB -> 1.55 MB for Portugal, 63 MB
    -> 9.1 MB for Poland, measured). `timeout` is per network read,
    not for the whole download.
    """
    url = ensure_str(url, errors='ignore').strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL (missing scheme): %s" % url)
    request = Request(url, headers={
        'User-Agent': RequestAgent(),
        'Accept-Encoding': 'gzip',
    })
    response = _urlopen_unverified(request, timeout)
    encoding = ''
    try:
        encoding = response.info().get('Content-Encoding') or ''
    except Exception:
        pass
    return _HttpStream(response, 'gzip' in encoding.lower())


def getUrl(url, timeout=30, retries=3, backoff=2):
    """Fetch URL with exponential backoff retry logic. Returns the
    response body, or "" on failure."""
    headers = {'User-Agent': RequestAgent()}

    if not url:
        raise ValueError("Empty URL passed to getUrl")

    url = ensure_str(url, errors='ignore').strip()

    if not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL (missing scheme): %s" % url)

    for i in range(retries):
        try:
            # No socket.setdefaulttimeout() here - every urlopen() call
            # below already gets an explicit timeout=timeout, and this
            # runs in the same process as the proxy, whose own comments
            # elsewhere warn that mutating the global default poisons
            # unrelated sockets (e.g. streaming) that don't set their own.
            request = Request(url, headers=headers)
            response = _urlopen_unverified(request, timeout)
            data = response.read()
            return data

        except HTTPError as e:

            code = getattr(e, 'code', None)
            if code == 451:
                # "Unavailable for legal reasons" - asking again
                # won't change the answer. (Used to return a
                # "__HTTP451__" marker string here, which only the
                # long-gone vavoo.to/kool.to listing fallback knew to
                # look for - every other caller would have treated it
                # as the response body.)
                print("HTTP 451 for URL: {0}".format(url))
                return ""

            if i < retries - 1:
                wait_time = backoff ** i
                print(
                    "HTTP error {0} on attempt {1}, retrying in {2} seconds...".format(
                        code, i + 1, wait_time))
                select.select([], [], [], wait_time)
                continue
            print(
                "Failed after {0} attempt(s) for URL: {1}".format(
                    i + 1, url))
            print("HTTPError: {0}".format(e))
            return ""

        except (URLError, socket.timeout, socket.error) as e:
            err_no = getattr(e, 'errno', None)
            if err_no is None and getattr(e, 'args', None):
                err_no = e.args[0]

            retryable_socket_errors = (104, 110, 111)
            is_retryable_socket = isinstance(e, socket.error) and (
                err_no in retryable_socket_errors or err_no is None
            )
            is_retryable = not isinstance(
                e, socket.error) or is_retryable_socket

            if is_retryable and i < retries - 1:
                wait_time = backoff ** i  # Exponential backoff
                print(
                    "Attempt {0} failed, retrying in {1} seconds...".format(
                        i + 1, wait_time))
                select.select([], [], [], wait_time)
            else:
                # i + 1, not `retries`: a timeout or other
                # non-retryable error gives up on the first attempt,
                # and the log used to claim "after 3 attempts" for it
                # anyway.
                print(
                    "Failed after {0} attempt(s) for URL: {1}".format(
                        i + 1, url))
                print("Error: {0}".format(e))
                return ""

        except Exception as e:
            if i < retries - 1:
                wait_time = backoff ** i
                print(
                    "Unexpected error on attempt {0}, retrying in {1} seconds...".format(
                        i + 1, wait_time))
                print("Error: {0}".format(e))
                select.select([], [], [], wait_time)
                continue

            print(
                "Failed after {0} attempt(s) for URL: {1}".format(
                    i + 1, url))
            print("Unexpected error: {0}".format(e))
            try:
                trace_error()
            except BaseException:
                pass
            return ""


def get_external_ip():
    """Get external IP using multiple fallback services"""
    from subprocess import Popen, PIPE

    def _decode_cmd_output(value):
        if value is None:
            return ""
        if isinstance(value, binary_type):
            return value.decode('utf-8', 'ignore').strip()
        return ensure_str(value, errors='ignore').strip()

    services = [
        # --max-time bounds curl itself (Python 2 has no
        # Popen.communicate(timeout=...), so this is the only reliable
        # way to bound both versions) - this call runs while holding
        # addon_sig_lock (see refresh_addon_sig_if_needed()), which
        # every channel resolve retry also needs, so an unbounded hang
        # here previously meant an unbounded freeze for all playback.
        lambda: Popen(
            [
                'curl',
                '-s',
                '--max-time', '5',
                'ifconfig.me'],
            stdout=PIPE).communicate()[0],
    ]

    if requests is not None:
        services.extend([
            lambda: requests.get(
                'https://v4.ident.me',
                timeout=5).text.strip(),
            lambda: requests.get(
                'https://api.ipify.org',
                timeout=5).text.strip(),
            lambda: requests.get(
                'https://api.myip.com',
                timeout=5).json().get(
                "ip",
                "").strip(),
            lambda: requests.get(
                'https://checkip.amazonaws.com',
                timeout=5).text.strip(),
        ])

    for service in services:
        try:
            ip = service()
            ip = _decode_cmd_output(ip)
            if ip:
                return ip
        except Exception:
            continue
    return None


def convert_to_unicode(data):
    if isinstance(data, dict):
        return {convert_to_unicode(key): convert_to_unicode(value)
                for key, value in data.items()}
    elif isinstance(data, list):
        return [convert_to_unicode(element) for element in data]
    elif PY2 and isinstance(data, str):
        # Decode strings to Unicode for Python 2
        return data.decode('utf-8', 'ignore')
    elif PY2 and isinstance(data, unicode):
        return data
    else:
        return data


# ============================================================================
# FUNCTIONS FOR VAVOO PROXY
# ============================================================================


def get_proxy_status():
    """The proxy's status (what /status answers, plus "booting",
    "listening" and "ready"), read in this process: the proxy is a
    thread of Enigma2's own Python (vavoo_proxy.proxy_state()), so
    asking it over HTTP - from the GUI thread, every few seconds - only
    cost time. None if it cannot be read."""
    try:
        from . import vavoo_proxy   # (here: vavoo_proxy imports this module)
        return vavoo_proxy.proxy_state()
    except Exception as e:
        debug("get_proxy_status: {}".format(e))
        return None


def is_proxy_running():
    """Check if the proxy is running"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Bounded: called from the GUI thread all over the plugin.
            # A local connect is normally instant either way, but with
            # no timeout a full listen backlog on the proxy would
            # leave this hanging for the kernel's own connect timeout.
            s.settimeout(1)
            return s.connect_ex((PROXY_HOST, PORT)) == 0
        finally:
            s.close()
    except BaseException:
        return False


def is_proxy_ready(timeout=2):
    """True once the proxy has its catalog and is listening - read in
    this process (get_proxy_status()), so it never blocks: `timeout` is
    only kept for the callers that pass one."""
    state = get_proxy_status()
    return bool(state and state.get("ready"))


# ===================================


def _version_tuple(version_str):
    """Turn '1.9' / '1.10' into comparable (1, 9) / (1, 10) tuples -
    plain string comparison would wrongly say '1.9' > '1.10'."""
    parts = []
    for chunk in sub(r'[^0-9.]', '', version_str or '').split('.'):
        try:
            parts.append(int(chunk))
        except ValueError:
            parts.append(0)
    return tuple(parts) if parts else (0,)


def is_remote_version_newer(local_version, remote_version):
    """True if remote_version is numerically greater than local_version."""
    return _version_tuple(remote_version) > _version_tuple(local_version)


def check_remote_installer_version():
    """Fetch installer.sh from GitHub and pull out its version and
    changelog. Returns (version, changelog, raw_content), any/all of
    which are None on failure.

    installer.sh is expected to contain lines shaped like:
        version='1.76'
        changelog="- line one
        - line two"

    raw_content is returned too so callers that want to actually run the
    installer don't need a second fetch.
    """
    try:
        content = getUrl(INSTALLER_URL, timeout=10, retries=2)
        if not content:
            print("[Update] Could not fetch installer.sh")
            return None, None, None
        content = ensure_str(content, errors='ignore')

        version_match = search(r"version\s*=\s*['\"]([^'\"]+)['\"]", content)
        if not version_match:
            print("[Update] Could not find version= in installer.sh")
            return None, None, None
        remote_version = version_match.group(1).strip()

        changelog_match = search(
            r'changelog\s*=\s*"(.*?)"', content, IGNORECASE | DOTALL)
        changelog = changelog_match.group(
            1).strip() if changelog_match else ""

        return remote_version, changelog, content

    except Exception as e:
        print("[Update] Error checking installer.sh version: {}".format(e))
        return None, None, None


def remove_parentheses(text):
    """Remove parentheses and their content from text"""
    return sub(
        r'\s*\([^()]*\)\s*',
        ' ',
        ensure_str(
            text,
            errors='ignore')).strip()


"""
# def ReloadBouquets(delay=2000):
    # from enigma import eDVBDB, eTimer
    # try:
        # def do_reload():
            # try:
                # db = eDVBDB.getInstance()
                # db.reloadBouquets()
                # db.reloadServicelist()
                # print("Bouquets reloaded successfully")
            # except Exception as e:
                # print("Error during service reload: " + str(e))

        # reload_timer = eTimer()
        # try:
            # reload_timer.callback.append(do_reload)
        # except BaseException:
            # reload_timer.timeout.connect(do_reload)
        # reload_timer.start(delay, True)
    # except Exception as e:
        # print("Error setting up service reload: " + str(e))
        # do_reload()
"""


def _in_main_thread():
    """True on Enigma2's main/GUI thread. Not threading.main_thread():
    that only exists on Python 3.4+, and this has to run on Python 2
    images too."""
    return isinstance(threading.current_thread(), threading._MainThread)


def ReloadBouquets(delay=500):
    """Reload Enigma2's bouquets and service list after `delay` ms.

    The reload itself always runs on the GUI thread and the caller is
    never blocked. Called from a background thread (every bouquet
    export does, via bouquet_manager._add_to_main_bouquet()) this used
    to sleep for the delay and then call eDVBDB right there - Enigma2's
    service database is not safe to touch off the GUI thread - and on
    Python 2 it never got that far at all, dying on
    threading.main_thread() (Python 3 only), so bouquets were never
    reloaded after an export.
    """
    from enigma import eDVBDB

    def do_reload():
        try:
            db = eDVBDB.getInstance()
            db.reloadBouquets()
            db.reloadServicelist()
            print("Bouquets reloaded successfully")
        except Exception as e:
            print("Error during service reload: " + str(e))

    seconds = max(delay, 0) / 1000.0
    reactor = None
    try:
        from twisted.internet import reactor
    except Exception as e:
        debug("twisted reactor unavailable: {}".format(e))

    if not _in_main_thread():
        if reactor is not None and reactor.running:
            reactor.callFromThread(reactor.callLater, seconds, do_reload)
        else:
            # No running reactor to hand it to - never the case inside
            # Enigma2, where the reactor is the main loop.
            do_reload()
        return

    if delay <= 0:
        do_reload()
        return

    if reactor is not None and reactor.running:
        reactor.callLater(seconds, do_reload)
        return

    # Fallback: eTimer
    timer = eTimer()
    try:
        timer.callback.append(do_reload)
    except AttributeError:
        timer.timeout.connect(do_reload)
    timer.start(delay, True)


def ensure_sref_trailing_colon(sref):
    if sref and not sref.endswith(':'):
        return sref + ':'
    return sref


def unique_fallback_sref(servicetype, channel_id):
    """Build a synthetic service reference whose
    sid:tsid pair is unique per Vavoo channel_id, instead of the old
    literal "servicetype:0:0:0:0:0:0:0:0:0:" used for every unmatched
    channel.

    Enigma2's eEPGCache indexes events by the sid:tsid:onid:namespace
    portion of a service reference, not by the stream URL appended after
    it - so every unmatched channel sharing that identical all-zero
    tuple was, as far as EPG lookup is concerned, literally the same
    service: whatever programme data ever ended up cached under that one
    shared null key got shown for all of them at once (confirmed via a
    user's box: a cluster of unrelated, genuinely-unmatched channels -
    "13EME RUE", "A LA CARTE 1-11", "20 MINUTES TV" - all displaying one
    other channel's guide data).

    onid/namespace are deliberately left at 0: every real DVB service
    reference uses a non-zero namespace (the known satellite/terrestrial/
    cable ranges), so a synthetic entry here can never collide with an
    actual matched channel - only sid/tsid need to vary to keep
    unmatched channels apart from each other.
    """
    h = zlib.crc32(
        ensure_str(
            channel_id,
            errors='ignore').encode('utf-8')) & 0xffffffff
    sid = (h & 0xffff) or 1
    tsid = ((h >> 16) & 0xffff) or 1
    return "%s:0:1:%x:%x:0:0:0:0:0:" % (servicetype, sid, tsid)


def strip_control_chars(text):
    """Strip characters with ord() <= 31 (e.g. an embedded newline) from
    network-sourced text before it's written as a raw playlist/bouquet
    line - same logic as bouquet_manager.py's own private
    _strip_control_chars(), kept here too (not imported from there) so
    vavoo_proxy.py can use it without creating a circular import
    (bouquet_manager.py already imports from vavoo_proxy.py)."""
    return ''.join(c for c in ensure_str(text, errors='ignore') if ord(c) > 31)


def sanitizeFilename(filename):
    """Sanitize filename for safe filesystem use"""
    filename = ensure_str(filename, errors='ignore')

    # Remove unsafe characters
    filename = sub(r'[\\/:*?"<>|\0]', '', filename)
    filename = ''.join(c for c in filename if ord(c) > 31)

    normalized = normalize('NFKD', filename).encode('ascii', 'ignore')
    if isinstance(normalized, binary_type):
        filename = normalized.decode('ascii', 'ignore')
    else:
        filename = normalized

    filename = filename.rstrip('. ').strip()

    # Handle reserved names
    reserved = (
        ["CON", "PRN", "AUX", "NUL"]
        + ["COM" + str(i) for i in range(1, 10)]
        + ["LPT" + str(i) for i in range(1, 10)]
    )

    if filename.upper() in reserved or not filename:
        if filename:
            filename = "__" + filename
        else:
            filename = "__"

    # Truncate if necessary
    if len(filename) > 255:
        base, ext = splitext(filename)
        ext = ext[:254]
        filename = base[:255 - len(ext)] + ext

    return filename or "__"


def decodeHtml(text):
    text = ensure_str(text, errors='ignore')

    if PY3:
        import html
        text = html.unescape(text)
    else:
        h = html_parser.HTMLParser()
        text = h.unescape(text)

    # (unicode, as `text` is: on Python 2 the byte "\u00f1" here made
    # every call fail - names for the guide, bouquets, M3U)
    replacements = {
        u'&amp;': u'&', u'&apos;': u"'", u'&lt;': u'<', u'&gt;': u'>',
        u'&ndash;': u'-', u'&quot;': u'"', u'&ntilde;': u'\u00f1',
        u'&rsquo;': u"'", u'&nbsp;': u' ', u'&equals;': u'=',
        u'&quest;': u'?', u'&comma;': u',', u'&period;': u'.',
        u'&colon;': u':', u'&lpar;': u'(', u'&rpar;': u')', u'&excl;': u'!',
        u'&dollar;': u'$', u'&num;': u'#', u'&ast;': u'*', u'&lowbar;': u'_',
        u'&lsqb;': u'[', u'&rsqb;': u']', u'&half;': u'1/2',
        u'&DiacriticalTilde;': u'~', u'&OpenCurlyDoubleQuote;': u'"',
        u'&CloseCurlyDoubleQuote;': u'"'
    }
    for entity, char in replacements.items():
        text = text.replace(entity, char)

    return text.strip()


# ============================================================================
# FLAG DOWNLOAD FUNCTIONS
# ============================================================================
def _write_file_atomic(path, data):
    """Write bytes to path via a temp file + rename, so a reader (the
    channel list loads these images while they are still being
    downloaded in the background) can never see a half-written file.
    The temp name carries the thread id: two threads fetching the same
    image at once must not write into each other's temp file."""
    temp_path = "%s.%s.tmp" % (path, threading.current_thread().ident)
    try:
        with open(temp_path, 'wb') as f:
            f.write(data)
        rename(temp_path, path)
    except Exception:
        try:
            unlink(temp_path)
        except Exception:
            pass
        raise


def initialize_cache_with_local_flags():
    """Copy all local flags from skin/cowntry/ to cache directory.

    Skips the copy if a previous run in this boot session already
    populated the (tmpfs) cache dir, since FLAG_CACHE_DIR contents only
    disappear on reboot and the source files never change without one.
    """
    local_dir = join(PLUGIN_PATH, 'skin/cowntry')
    cache_dir = FLAG_CACHE_DIR

    if not exists(local_dir):
        print("Local flags directory not found: %s" % local_dir)
        return 0

    marker = join(cache_dir, '.flags_initialized')
    if exists(marker):
        print("Flag cache already initialized, skipping copy")
        return 0

    # Python 2 compatible directory creation
    if not exists(cache_dir):
        try:
            makedirs(cache_dir)
        except Exception as e:
            debug("Could not create flag cache dir {}: {}".format(cache_dir, e))

    copied = 0
    for filename in listdir(local_dir):
        if filename.lower().endswith('.png'):
            src = join(local_dir, filename)
            dst = join(cache_dir, filename.lower())

            try:
                with open(src, 'rb') as f:
                    # Check PNG header
                    header = f.read(8)
                    if header == b'\x89PNG\r\n\x1a\n':
                        copy2(src, dst)
                        copied += 1
                        print("Copied local flag: %s" % filename)
                    else:
                        print("Skipping invalid PNG: %s" % filename)
            except Exception as e:
                print("Error copying %s: %s" % (filename, e))

    print("Initialized cache with %d local flags" % copied)
    try:
        with open(marker, 'wb') as f:
            f.write(b'1')
    except Exception as e:
        debug("Could not write flag cache marker {}: {} (flags will "
              "be re-copied on next start)".format(marker, e))
    return copied


def download_flag_online(
        country_name,
        cache_dir=FLAG_CACHE_DIR,
        screen_width=None):
    """
    Download country flag from online service (TV Garden style)
    Returns: (success, flag_path_or_error_message)
    """
    try:
        # 1. Determine screen width if not provided
        if screen_width is None:
            screen_width = get_screen_width()  # must return int

        print(
            "Processing %s with screen_width=%d" %
            (country_name, screen_width))

        # 2. Get country code
        country_code = get_country_code(country_name)
        if not country_code:
            return False, "No country code found for: %s" % country_name

        country_code_lower = country_code.lower()
        special_flags = ['bk', 'internat']

        if country_code_lower in special_flags:
            local_path = join(
                PLUGIN_PATH,
                'skin/cowntry',
                '%s.png' %
                country_code_lower)
            if exists(local_path):
                print(
                    "Using special flag: %s -> %s" %
                    (country_name, local_path))
                return True, local_path

        # 3. Create cache directory (Python 2 safe)
        if not exists(cache_dir):
            try:
                makedirs(cache_dir)
            except Exception as e:
                debug(
                    "Could not create flag cache dir {}: {}".format(
                        cache_dir, e))

        # 4. Cache file path
        cache_file = join(cache_dir, "%s.png" % country_code_lower)

        # 5. Check fresh cache (<7 days)
        if exists(cache_file):
            try:
                file_age = time() - getmtime(cache_file)
                if file_age < 604800:
                    print("Cache HIT: %s" % country_name)
                    return True, cache_file
            except Exception as e:
                debug("Flag cache freshness check failed for {}: {}".format(
                    cache_file, e))

        # 6. Set fixed flag dimensions
        if screen_width >= 2560:      # WQHD
            width, height = 80, 60
        elif screen_width >= 1920:    # FHD
            width, height = 60, 45
        else:                         # HD
            width, height = 40, 30

        # 7. Build URL
        url = "https://flagcdn.com/%dx%d/%s.png" % (
            width, height, country_code_lower)
        print("Downloading %s (%dx%d) from: %s" %
              (country_name, width, height, url))

        # 8. Download
        req = Request(url, headers={'User-Agent': 'Vavoo-Stream/1.0'})
        try:
            if PY3:
                response = urlopen(req, timeout=5, context=ssl_context)
            else:
                response = urlopen(req, timeout=5)
        except Exception as e:
            print("Network error for %s: %s" % (country_name, e))
            return False, "Network error: %s" % e

        # 9. Read data
        if response.getcode() != 200:
            return False, "Download failed (HTTP %d)" % response.getcode()
        flag_data = response.read()
        try:
            response.close()
        except Exception:
            pass

        # 10. Validate small file
        if len(flag_data) < 100:
            print(
                "Warning: Flag file too small (%d bytes)" %
                len(flag_data))

        # 11. Validate PNG header in memory BEFORE writing (no double file
        # open)
        if flag_data[:8] != b'\x89PNG\r\n\x1a\n':
            print("ERROR: Downloaded data is not a valid PNG file!")
            return False, "Invalid PNG file downloaded"

        # 12. Save to cache
        try:
            _write_file_atomic(cache_file, flag_data)
            print("Flag %dx%d saved: %s (%d bytes)" %
                  (width, height, cache_file, len(flag_data)))
            return True, cache_file

        except Exception as e:
            print("Error saving to cache: %s" % e)
            return False, "Save error: %s" % e

    except Exception as e:
        print("Flag download error: %s" % e)
        return False, "Flag download error: %s" % e


# ============================================================================
# PICON DOWNLOAD FUNCTIONS
# ============================================================================
def _picon_cache_filename(logo_url):
    """Stable, filesystem-safe cache filename for a channel's logo URL.

    An md5 hash of the whole URL, not any part of its own path - the
    URL comes straight from a third-party catalog (geil.to/Vavoo) this
    plugin doesn't control, so no part of it should double as a
    filename untouched. Two channels that happen to share the exact
    same logo URL naturally share one cache entry instead of each
    re-downloading it.
    """
    return hashlib.md5(logo_url.encode('utf-8')).hexdigest() + '.png'


def get_picon_cache_path(logo_url, cache_dir=None):
    """Local path a picon for this logo URL would be cached at,
    whether or not it has actually been downloaded yet - the one
    place this filename is computed, shared by download_picon_online()
    (which writes it) and show_list() (which only ever reads it, never
    downloading synchronously itself), so the two can't drift apart.
    """
    if not logo_url:
        return None
    return join(cache_dir or _picon_cache[0], _picon_cache_filename(logo_url))


# The logo cache is in /tmp, which on a box is RAM: kept to this size
# (the oldest files go first; a logo is downloaded again when needed).
PICON_CACHE_MAX = 8 * 1024 * 1024
# ...unless the plugin found a flash disk for it (set_picon_cache_dir()):
# there it keeps more, and it survives a reboot.
PICON_CACHE_MAX_DISK = 64 * 1024 * 1024
_picon_cache = [PICON_CACHE_DIR, PICON_CACHE_MAX]


def set_picon_cache_dir(folder, max_bytes=None):
    """Keep the logos in `folder` (a flash disk the plugin chose,
    ui_record.logo_folder()), or in /tmp again with None."""
    if folder:
        _picon_cache[0] = folder
        _picon_cache[1] = PICON_CACHE_MAX_DISK if max_bytes is None else max_bytes
    else:
        _picon_cache[0] = PICON_CACHE_DIR
        _picon_cache[1] = PICON_CACHE_MAX
    return _picon_cache[0]


def picon_cache_dir():
    return _picon_cache[0]


def picon_cache_in_ram():
    """True while the logos are in /tmp (RAM on a box)."""
    return _picon_cache[0] == PICON_CACHE_DIR


def trim_picon_cache(cache_dir=None, max_bytes=None):
    """Delete the oldest cached logos until the cache is at most
    max_bytes (the folder in use and its limit by default). Returns how
    many were deleted."""
    cache_dir = cache_dir or _picon_cache[0]
    max_bytes = _picon_cache[1] if max_bytes is None else max_bytes
    try:
        names = listdir(cache_dir)
    except Exception:
        return 0
    files = []
    total = 0
    for name in names:
        path = join(cache_dir, name)
        try:
            if not isfile(path):
                continue
            size = getsize(path)
            files.append((getmtime(path), size, path))
            total += size
        except Exception:
            continue
    removed = 0
    files.sort()
    for _mtime, size, path in files:
        if total <= max_bytes:
            break
        try:
            remove(path)
            total -= size
            removed += 1
        except Exception:
            pass
    if removed:
        print("[Picons] {} old logos deleted from {} (now {} KB)".format(
            removed, cache_dir, total // 1024))
    return removed


def read_meminfo(path="/proc/meminfo"):
    """{field: kB} from /proc/meminfo ({} when it cannot be read)."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                name, _sep, rest = line.partition(":")
                fields = rest.split()
                if fields:
                    try:
                        out[name.strip()] = int(fields[0])
                    except ValueError:
                        pass
    except Exception:
        pass
    return out


def process_memory(proc="/proc", top=8):
    """[(rss_kb, pid, name)] of the processes using the most memory,
    the biggest first (read from /proc/<pid>/status)."""
    rows = []
    try:
        names = listdir(proc)
    except Exception:
        return rows
    for pid in names:
        if not pid.isdigit():
            continue
        name, rss = "?", None
        try:
            with open(join(proc, pid, "status")) as f:
                for line in f:
                    if line.startswith("Name:"):
                        name = line.split(None, 1)[1].strip()
                    elif line.startswith("VmRSS:"):
                        rss = int(line.split()[1])
                        break
        except Exception:
            continue
        if rss:
            rows.append((rss, int(pid), name))
    rows.sort(reverse=True)
    return rows[:top]


def memory_report(proc="/proc", meminfo="/proc/meminfo"):
    """What the box's memory looked like, in a few lines: what was left,
    /tmp's share (Shmem), the kernel's (Slab), and the processes holding
    the most - so a box that ran out can be explained afterwards."""
    info = read_meminfo(meminfo)

    def mb(field):
        value = info.get(field)
        return "?" if value is None else "%d MB" % (value // 1024)

    lines = ["{}  free {} of {}, Shmem (/tmp) {}, Slab {}".format(
        strftime("%Y-%m-%d %H:%M:%S", localtime()), mb("MemAvailable"),
        mb("MemTotal"), mb("Shmem"), mb("Slab"))]
    for rss, pid, name in process_memory(proc):
        lines.append("    {:>7} MB  {} ({})".format(rss // 1024, name, pid))
    return "\n".join(lines) + "\n"


def memory_note():
    """"enigma2 148 MB, box 412 MB free" - this process's memory and
    what the box has left (for the log: was the box short of memory,
    and was it this process that grew?). "" where it cannot be read."""
    parts = []
    try:
        name = open("/proc/self/comm").read().strip() or "process"
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS:"):
                parts.append("{} {} MB".format(
                    name, int(line.split()[1]) // 1024))
                break
    except Exception:
        pass
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                parts.append("box {} MB free".format(
                    int(line.split()[1]) // 1024))
                break
    except Exception:
        pass
    return ", ".join(parts)


def thread_cpu(task_dir="/proc/self/task"):
    """{thread id: (name, seconds of CPU so far)} for every thread of
    this process (Enigma2's: the GUI, the proxy's "vv-http", the
    plugin's "vv-guide" / "vv-catalog"... - name_this_thread()). {}
    where /proc cannot be read. Cheap: one small file per thread."""
    import os
    try:
        tick = float(os.sysconf("SC_CLK_TCK"))
    except (AttributeError, ValueError, OSError):
        tick = 100.0
    out = {}
    try:
        tids = listdir(task_dir)
    except OSError:
        return out
    for tid in tids:
        try:
            with open(join(task_dir, tid, "stat")) as f:
                data = f.read()
            end = data.rindex(")")
            name = data[data.index("(") + 1:end]
            fields = data[end + 2:].split()
            # utime + stime: fields 14 and 15 of stat
            out[tid] = (name, (int(fields[11]) + int(fields[12])) / tick)
        except (IOError, OSError, ValueError, IndexError):
            continue
    return out


def cpu_by_name(before, after):
    """Seconds of CPU per thread name between two thread_cpu() samples
    (a thread that started in between counts from 0), largest first:
    [(name, seconds)]."""
    used = {}
    for tid, (name, seconds) in after.items():
        prev = before.get(tid)
        spent = seconds - prev[1] if prev is not None else seconds
        if spent > 0:
            used[name] = used.get(name, 0.0) + spent
    return sorted(used.items(), key=lambda item: -item[1])


def busy_text(used, least=0.05, most=5):
    """ "vv-guide 1.2 s, enigma2 0.4 s" - the threads that used at least
    `least` seconds, the `most` busiest."""
    return ", ".join("{} {:.1f} s".format(name, seconds)
                     for name, seconds in used[:most] if seconds >= least)


def cpu_report(before, after, elapsed):
    """The "[CPU]" line's text: "enigma2 14 % of a core (30 min) -
    vv-guide 48.0 s, enigma2 200.0 s, vv-http 3.0 s" (what this process
    spent between two thread_cpu() samples, `elapsed` seconds apart,
    and who spent it). "" when there is nothing to say."""
    if not after or elapsed <= 0:
        return ""
    used = cpu_by_name(before, after)
    total = sum(seconds for _name, seconds in used)
    busy = busy_text(used, least=0.5, most=6)
    # (halves up on both Pythons: round() is "to even" on Python 3)
    text = "{} % of a core ({} min)".format(
        int(100.0 * total / elapsed + 0.5), int(elapsed / 60.0 + 0.5))
    return text + (" - " + busy if busy else "")


def download_picon_online(logo_url, cache_dir=None):
    """Download and cache a channel picon from its catalog-provided
    logo URL (geil.to's own picons, or Vavoo's - see vavoo_proxy.py's
    fix_logo_url()). Mirrors download_flag_online()'s mechanics
    (timeout, cache-dir creation, PNG-header validation before
    writing) for the same reasons - including graceful failure: if
    the URL doesn't actually serve a valid PNG, this just reports
    failure and the caller keeps showing its default icon, same as
    before this existed.

    Returns: (success, cache_path_or_error_message)
    """
    if not logo_url:
        return False, "No logo URL"
    cache_dir = cache_dir or _picon_cache[0]

    try:
        if not exists(cache_dir):
            try:
                makedirs(cache_dir)
            except Exception as e:
                debug("Could not create picon cache dir {}: {}".format(
                    cache_dir, e))

        cache_file = get_picon_cache_path(logo_url, cache_dir)

        # Fresh cache (<7 days, same window as flags - channel logos
        # change about as rarely as country flags do).
        if exists(cache_file):
            try:
                if (time() - getmtime(cache_file) < 604800
                        and getsize(cache_file) > 100):
                    return True, cache_file
            except Exception as e:
                debug("Picon cache freshness check failed for {}: {}".format(
                    cache_file, e))

        req = Request(logo_url, headers={'User-Agent': 'Vavoo-Stream/1.0'})
        try:
            if PY3:
                response = urlopen(req, timeout=5, context=ssl_context)
            else:
                response = urlopen(req, timeout=5)
        except Exception as e:
            return False, "Network error: %s" % e

        if response.getcode() != 200:
            return False, "Download failed (HTTP %d)" % response.getcode()
        picon_data = response.read()
        try:
            response.close()
        except Exception:
            pass

        if len(picon_data) < 100:
            return False, "Picon file too small (%d bytes)" % len(
                picon_data)

        # Validate the PNG header in memory before writing anything -
        # fix_logo_url() only ever points this at a *.png path, but
        # that's a hint from the catalog, not a guarantee.
        if picon_data[:8] != b'\x89PNG\r\n\x1a\n':
            return False, "Not a valid PNG"

        try:
            _write_file_atomic(cache_file, picon_data)
            return True, cache_file
        except Exception as e:
            return False, "Save error: %s" % e

    except Exception as e:
        print("Picon download error: %s" % e)
        return False, "Picon download error: %s" % e


def get_country_code_from_bouquet_name(name):
    """Extract country code from a bouquet display name (e.g., 'Italy', 'Italy ➾ Sports')."""
    base_name = name
    for sep in group_separators(name):
        if sep in name:
            base_name = name.split(sep)[0].strip()
            break
    # Case-insensitive lookup: .capitalize() breaks multi-word names
    # like "United Kingdom" -> "United kingdom", which then can't match
    # the Title-Case keys in country_codes.
    base_name_lower = base_name.lower()
    for key, code in country_codes.items():
        if key.lower() == base_name_lower:
            return code
    return None


# Language/demonym adjectives sometimes used as IPTV group names instead
# of a country name (e.g. "Italian", "German") - not real country names,
# so they don't belong in __init__.py's country_codes table, but
# get_country_code() has always accepted them too.
_EXTRA_COUNTRY_ALIASES = {
    'italia': 'it',
    'italiana': 'it',
    'italian': 'it',
    'german': 'de',
    'french': 'fr',
    'spanish': 'es',
    'english': 'gb',
    'british': 'gb',
    'default': 'us',
}


def get_country_code(country_name):
    """
    Extract country code from country name.
    Handles formats like 'France', 'France ➾ Sports', etc.
    Returns ISO 2-letter country code or empty string if not found.
    """
    country_name = ensure_str(country_name, errors='ignore').strip()
    if not country_name:
        return ""

    if any(char in country_name for char in '0123456789.'):
        return ""

    for sep in group_separators(country_name):
        if sep in country_name:
            country_name = country_name.split(sep)[0].strip()
            break

    country_name = country_name.strip()

    if len(country_name) < 2:
        return ""

    # country_codes (__init__.py) is the single source of truth for real
    # country names - checked case-insensitively.
    name_lower = country_name.lower()
    for key, code in country_codes.items():
        if key.lower() == name_lower:
            return code

    if name_lower in _EXTRA_COUNTRY_ALIASES:
        return _EXTRA_COUNTRY_ALIASES[name_lower]

    # Partial match against the canonical table, for group names that
    # embed a country name inside a longer string (e.g. "France Sport"
    # contains "France"). Deliberately one-directional: only "a known
    # country name is a substring of the input" - never the reverse
    # ("input is a substring of a country name"), which used to let a
    # short/abbreviated input spuriously match any country name that
    # happens to contain those letters (e.g. "Ira" matching "United
    # Arab Emirates" via "em-IRA-tes") with no real use case needing
    # it - any legitimate abbreviation is already handled by the
    # exact-match loop above via its own country_codes entry. Prefer
    # the longest/most specific matching name when more than one embeds
    # in the input, alphabetically tie-broken so the result never
    # depends on Python's dict iteration order (not guaranteed on
    # Python 2).
    candidates = [key for key in country_codes if key.lower() in name_lower]
    if candidates:
        best = sorted(candidates, key=lambda k: (-len(k), k))[0]
        return country_codes[best]

    return ""


def cleanup_old_temp_files(max_age_hours=1):
    """
    Remove old temporary files in /tmp matching specific patterns.
    Files older than max_age_hours are deleted.
    """
    try:
        now = time()
        max_age = max_age_hours * 3600  # seconds

        patterns = [
            "/tmp/*vavoo*",
            "/tmp/*flag*",
            "/tmp/tmp*.png"
        ]

        # "/tmp/*vavoo*" also matches the proxy's own bookkeeping files
        # (vavoo_proxy.py's PID_FILE/BOOTING_FILE - hardcoded here rather
        # than imported to avoid a circular import, since vavoo_proxy.py
        # itself imports from this module). Deleting either out from
        # under a running/booting proxy would confuse its own PID/boot
        # tracking.
        excluded_basenames = ("vavoo_proxy.pid", "vavoo_proxy_booting")

        cleaned = 0
        for pattern in patterns:
            for filepath in glob.glob(pattern):
                try:
                    if basename(filepath) in excluded_basenames:
                        continue
                    if isfile(filepath):
                        file_age = now - getmtime(filepath)
                        if file_age > max_age:
                            unlink(filepath)
                            cleaned += 1
                            print(
                                "Cleaned old temp file: %s" %
                                filepath)
                except Exception as e:
                    print(
                        "Error removing %s: %s" %
                        (filepath, str(e)))

        if cleaned > 0:
            print("Total cleaned old temp files: %d" % cleaned)

        return cleaned

    except Exception as e:
        print("Error cleaning temp files: %s" % str(e))
        return 0


# ==================== START EPG ====================
_epg_matcher = None
_epg_matcher_lock = threading.Lock()


# Minimum name similarity (0-1) for a fuzzy EPG match. Was a settings
# option ("EPG Similarity Threshold"), always left at this default in
# practice - a tuning number, not something to choose in a menu.
EPG_SIMILARITY_THRESHOLD = 0.75


def get_epg_matcher(similarity_threshold=None):
    global _epg_matcher
    if similarity_threshold is None:
        similarity_threshold = EPG_SIMILARITY_THRESHOLD
    if _epg_matcher is None:
        with _epg_matcher_lock:
            if _epg_matcher is None:
                _epg_matcher = VavooEPGMatcher(similarity_threshold)
                return _epg_matcher
    _epg_matcher.similarity_threshold = similarity_threshold
    return _epg_matcher


def forget_epg_matches():
    """A factory reset: the matcher (its cache files are deleted
    already) and the curated databases are made again on next use."""
    global _epg_matcher
    with _epg_matcher_lock:
        _epg_matcher = None
    with _curated_channel_db_lock:
        _curated_channel_db_cache.clear()


# get_country_code() returns real ISO 3166-1 codes (needed for flag
# downloads, e.g. "gb" for United Kingdom), but channel_alias.ALIAS_MAP's
# ids keep the EPG world's own suffix convention, which doesn't always
# match ISO - UK channels are "BBCOne.uk", not "BBCOne.gb". Used by the
# alias step's country check below.
ALIAS_COUNTRY_OVERRIDES = {
    'gb': 'uk',
}

# channel_alias.ALIAS_MAP is curated for Italian channels specifically
# (see its own module docstring) - used by find_match()'s country-gate
# below to always trust an alias hit when matching for Italy itself,
# even for the handful of entries pinned to a non-".it" id.
_ALIAS_MAP_HOME_COUNTRY = "it"

# id(feed_ids) -> (feed_ids, {lower case id: id}, {lower case id without
# its dots: id}) - see _feed_spelling(). A few sets: one per country's
# feed index or loaded guide.
_feed_spellings = {}
_feed_spellings_lock = threading.Lock()
_FEED_SPELLINGS_KEEP = 8


def _feed_spelling(epg_id, feed_ids):
    """epg_id as the country's EPG feed itself writes it, or None when
    the feed has no such channel: the same id, else the same but for
    upper / lower case (the app: a source's guide ids differ in case at
    times), else the same but for the dots (as EpgGuide.channel_for():
    of several such ids, the shortest)."""
    if not epg_id or not feed_ids:
        return None
    if epg_id in feed_ids:
        return epg_id
    with _feed_spellings_lock:
        entry = _feed_spellings.get(id(feed_ids))
        if entry is None or entry[0] is not feed_ids:
            lower = {}
            dotless = {}
            for feed_id in feed_ids:
                lower.setdefault(feed_id.lower(), feed_id)
                key = feed_id.replace('.', '').lower()
                other = dotless.get(key)
                if other is None or len(feed_id) < len(other):
                    dotless[key] = feed_id
            if len(_feed_spellings) >= _FEED_SPELLINGS_KEEP:
                _feed_spellings.clear()
            entry = (feed_ids, lower, dotless)
            _feed_spellings[id(feed_ids)] = entry
    text = epg_id.lower()
    return entry[1].get(text) or entry[2].get(text.replace('.', ''))


_NO_SREF = "4097:0:0:0:0:0:0:0:0:0:"


class VavooEPGMatcher(object):
    """Finds the id a channel has in its country's EPG feed - the order
    in _find_match_locked(): the source catalog's own guide id, the
    alias table, this box's cache, the curated channel database, the
    feed's own channel names."""

    def __init__(self, similarity_threshold=0.70):
        self.similarity_threshold = similarity_threshold
        # Guards self.cache/self.normalized_index/self.new_matches -
        # see find_match()'s docstring.
        self._cache_lock = threading.RLock()
        self.cache = load_cache()       # persistent cache
        self.new_matches = {}           # matches found in this session
        self.normalized_index = {}      # map normalized_key -> original_key
        self._build_normalized_index()  # build index at startup
        self.alias_map = {}
        self._load_alias_map()

    @staticmethod
    def is_valid_epg_id(id_val):
        """Returns True if id_val looks like an EPG channel id (e.g.
        'Rai.1.it': a country suffix)."""
        # isinstance(id_val, str) alone rejects every value on Python 2,
        # where json.load()/XML parsing produce `unicode` (not a `str`
        # subclass there) - use text_type (six.text_type) too so this
        # doesn't silently reject every cached/parsed id on Python 2.
        if not id_val or not isinstance(id_val, (str, text_type)):
            return False
        if '.' not in id_val:
            return False
        parts = id_val.split('.')
        if len(parts) < 2:
            return False
        suffix = parts[-1]
        return len(suffix) in (2, 3) and suffix.isalpha()

    def _cleanup_stale_unmatched(
            self,
            channel_name,
            country_code,
            servicetype):
        """Remove this channel's entry from the unmatched cache if one
        exists there from before it started matching successfully.

        Only the live-rematch success path in find_match() used to do
        this (via save_unmatched(matched=True)); the alias/local-cache/
        temp-cache fast-path hits never did, leaving "ghost" unmatched
        entries around indefinitely for channels that actually match
        fine now. Checks the same in-memory unmatched cache
        save_unmatched() itself stages against (lazily loaded once, kept
        for the process lifetime) - cheap on the common case (nothing to
        clean up), and always current with anything staged earlier in
        this same run, unlike a separate per-matcher-instance snapshot
        would be.
        """
        key = "%s_%s" % (channel_name.strip(), country_code or '')
        with _unmatched_lock:
            _load_unmatched_cache_locked()
            found = key in _unmatched_cache_data
        if found:
            save_unmatched(
                channel_name,
                country_code,
                servicetype,
                matched=True)

    def _load_alias_map(self):
        if exists(ALIAS_FILE):
            try:
                with open(ALIAS_FILE, 'r') as f:
                    self.alias_map = load(f)
                    return
            except Exception:
                self.alias_map = {}
                pass

    def _clean_name_for_key(self, name):
        """Pulisce il nome per generare la chiave: mantiene suffissi .c, .s, .b."""
        if not name:
            return ""
        cleaned = name.lower()
        # Rimuovi solo parentesi e indicatori di qualità (NON i suffissi)
        cleaned = sub(r'\s*\([^)]*\)\s*', '', cleaned)
        cleaned = sub(r'\b(4k|hd|sd|fhd|uhd|hq|hevc|h265|h264)\b', '', cleaned)
        # Mantieni i punti, sostituisci altri non alfanumerici con spazio
        cleaned = sub(r'[^\w\s\.]', ' ', cleaned)
        cleaned = sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    def _clean_name_for_similarity(self, name):
        """Normalize a channel name for similarity comparison - see
        epg_name_utils.clean_name_for_similarity() (single source of
        truth, shared with generate_epg_channel_db.py's off-box
        mirror)."""
        return clean_name_for_similarity(name)

    def _normalize_key(self, channel_name, country_code):
        clean_name = self._clean_name_for_key(channel_name)
        return "{}_{}".format(clean_name, country_code)

    def _build_normalized_index(self):
        self.normalized_index = {}
        for key in self.cache:
            self._index_cache_key(key)

    def _index_cache_key(self, key):
        """Add/update a single cache key in normalized_index without
        rescanning the whole cache - see find_match(), which calls this
        once per matched channel and would otherwise turn a bulk export
        into an O(n^2) scan as the cache grows over time."""
        if '_' in key:
            name_part, country_part = key.rsplit('_', 1)
        else:
            name_part, country_part = key, ''
        norm_key = self._normalize_key(name_part, country_part)
        self.normalized_index[norm_key] = key

    def _match_feed_name(
            self, channel_name, country_code, channel_id=None,
            servicetype="4097", feed_index=None):
        """The last step: the channel's name against the display names
        of its country's own EPG feed (feed_index, pre-fetched by
        find_match() before self._cache_lock was taken -
        _get_epg_feed_index() can block on a cold network fetch).
        (id, sref) or (None, None). The feed gives an id, not a DVB
        service ref, so the sref is the channel's own synthetic one."""
        if not channel_name or not country_code:
            return None, None
        _feed_ids, name_index = feed_index if feed_index else (None, None)
        feed_match_id = _find_feed_id_by_name(
            channel_name, self, name_index) if name_index else None
        if not feed_match_id:
            print("[Match] No match found for '{}'".format(channel_name))
            return None, None
        print("[Match] FEED NAME MATCH: '{}' -> {}".format(
            channel_name, feed_match_id))
        if channel_id:
            return feed_match_id, unique_fallback_sref(servicetype, channel_id)
        return feed_match_id, _NO_SREF

    def _try_promote_to_curated(
            self, channel_name, country_code, servicetype, channel_id,
            cached, allow_curated_promotion, curated_db):
        """Called from a local-cache-hit branch in _find_match_locked().
        A cache entry written before the curated channel database
        existed for this country (or before this specific channel was
        added to it) is stuck on whatever it originally matched
        (a name match) forever, since the cache step returns early
        and the curated-DB step after it is never reached again. When allow_curated_promotion is set (bouquet
        export only, never the live overlay lookup), give a non-curated
        cache entry one more chance to upgrade to the curated result.
        curated_db is pre-fetched by find_match() before the cache
        lock is taken (see its docstring) - this is just a dict lookup
        against it, never a network call of its own.
        Returns a (id, sref, source) tuple to return immediately on a
        promotion, or None to fall through to the normal cache-hit
        return."""
        if (not allow_curated_promotion or not country_code or
                cached.get('source') == 'curated'):
            return None
        if not curated_db:
            return None
        curated_key = self._clean_name_for_similarity(channel_name)
        curated_id = curated_db.get(curated_key)
        if not curated_id or not channel_id:
            return None
        print(
            "[Match] Promoting cached match to curated DB: {} -> {}".format(
                channel_name, curated_id))
        self._cleanup_stale_unmatched(channel_name, country_code, servicetype)
        return (
            curated_id, unique_fallback_sref(servicetype, channel_id),
            'curated')

    def find_match(
            self, channel_name, country_code=None, servicetype="4097",
            channel_id=None, allow_curated_promotion=False,
            epg_guide_id=None):
        """_find_match_untimed(), with the ones that take long in the
        log ("[EPG] slow match": what loaded the box)."""
        started = time()
        try:
            return self._find_match_untimed(
                channel_name, country_code, servicetype, channel_id,
                allow_curated_promotion, epg_guide_id)
        finally:
            took = time() - started
            if took >= 1.0:
                print("[EPG] slow match: {} ({}) {:.1f}s".format(
                    ensure_str(channel_name or '', errors='ignore'),
                    country_code or '-', took))

    def _find_match_untimed(
            self, channel_name, country_code=None, servicetype="4097",
            channel_id=None, allow_curated_promotion=False,
            epg_guide_id=None):
        """Public entry point - serializes the whole lookup (including
        every self.cache/self.normalized_index/self.new_matches read
        and write below) behind self._cache_lock. This matcher is a
        per-process singleton (get_epg_matcher()) called concurrently
        from real, sanctioned usage - a bouquet export's background
        thread looping this per channel, while watching an already
        exported channel spawns a separate per-channel EPG-overlay
        daemon thread that also calls this - and those dicts were
        previously mutated with no locking at all: reassigning
        self.normalized_index mid-iteration elsewhere
        (_build_normalized_index(), also called from
        update_complete_cache() - see its matching lock use there) could
        raise "dictionary changed size during iteration" and abort EPG
        matching for a whole country's remaining channels, or silently
        drop a concurrent thread's cache write. An RLock (not a plain
        Lock), as the lookup may re-enter locked code paths on this
        same instance/thread.

        allow_curated_promotion: when True, a local-cache hit that
        wasn't originally sourced from the curated channel database
        gets one extra check against it, and is upgraded to the
        curated result if it now has an entry for this channel - see
        _find_match_locked()'s cache-hit branches. Only bouquet-export
        callers pass True; the live "Now Playing" overlay lookup
        leaves this at the default so a channel's EPG binding can only
        change as a result of an export the user explicitly triggered.

        epg_guide_id: the source catalog's own guide id for this
        channel, if it has one (geil.to's "tvg" field - Vavoo's own
        catalog has none, so this is always None on that path). When
        the country's EPG feed has it, it is the answer - step 1 of
        _find_match_locked().

        Returns an (epg_id, sref, source) 3-tuple; source is one of
        "alias", "curated", "live" or None (no match).

        Deliberately fetches the curated DB, and this country's own EPG
        feed index, *before* acquiring self._cache_lock: both
        _load_curated_channel_db() and _get_epg_feed_index() have their
        own independent caches and never touch self.cache/
        self.normalized_index, but either can block on a cold,
        multi-second-to-multi-MB network fetch - doing that while
        holding the lock the concurrent EPG-overlay thread also needs
        for its own, unrelated find_match() calls would stall it for
        that whole duration for no reason."""
        curated_db = _load_curated_channel_db(
            country_code) if country_code else None
        feed_index = _get_epg_feed_index(
            country_code) if country_code else None
        # A plain local list, not an instance attribute - _find_match_
        # locked() appends to it (under self._cache_lock, so that part
        # is already safe) when a cache downgrade needs persisting;
        # checked below, after releasing self._cache_lock, with no
        # cross-thread ambiguity since it's never shared beyond this
        # one call's stack.
        pending_save = []
        snapshot = None
        with self._cache_lock:
            result = self._find_match_locked(
                channel_name, country_code, servicetype, channel_id,
                allow_curated_promotion, curated_db, epg_guide_id,
                feed_index, pending_save)
            if pending_save:
                # (a copy: another thread may change the cache while
                # it is written)
                snapshot = dict(self.cache)
        if snapshot is not None:
            # save_cache() takes CACHE_FILE's own lock (_cache_file_lock),
            # after self._cache_lock was released - never export_lock:
            # a bouquet export holds that for its whole run and calls
            # this inside it (the same thread asking a plain Lock again
            # hung the export for good).
            save_cache(snapshot)
        return result

    def _find_match_locked(
            self, channel_name, country_code=None, servicetype="4097",
            channel_id=None, allow_curated_promotion=False,
            curated_db=None, epg_guide_id=None, feed_index=None,
            pending_save=None):
        if not channel_name:
            return None, None, None
        feed_ids = feed_index[0] if feed_index else None

        def hit(epg_id, source, sref=None):
            """A match: every channel with an id gets its own synthetic
            service reference (unique_fallback_sref()), so channels and
            countries sharing an EPG id never collide in eEPGCache."""
            self._cleanup_stale_unmatched(
                channel_name, country_code, servicetype)
            if channel_id:
                sref = unique_fallback_sref(servicetype, channel_id)
            return epg_id, sref or _NO_SREF, source

        # 1. The source catalog's own guide id (geil.to's "tvg" -
        # Vavoo's own catalog has none), as the feed writes it: first,
        # as in the app - the source knows its channel better than any
        # name match.
        if epg_guide_id and country_code:
            feed_id = _feed_spelling(epg_guide_id, feed_ids)
            if feed_id:
                print(
                    "[Match] GUIDE ID HIT (source catalog): {} -> {}".format(
                        channel_name, feed_id))
                return hit(feed_id, 'live')

        # 2. The alias table. self.alias_map (loaded from the on-disk
        # channel_alias.json, if present) can override/add to the
        # curated channel_alias.ALIAS_MAP (~300 hand-mapped Italian
        # channels). It counts when the feed has that channel (when the
        # feed's channel list is not known, as it is).
        if alias_available:
            norm_name = channel_alias.normalize_channel_name(channel_name)
            alias_id = (self.alias_map.get(norm_name) or channel_alias.ALIAS_MAP.get(
                norm_name)) if norm_name else None
            if alias_id:
                # ALIAS_MAP is curated for Italian channels: for another
                # country only an id with that country's own suffix
                # counts (generic pan-European names like "Eurosport 1"
                # or "Nickelodeon" would otherwise get Italy's id), or
                # when no country was given at all. Italy itself trusts
                # every entry, even one pinned to a non-".it" id
                # (e.g. "DISNEY CHANNEL" -> a ".ch" id).
                alias_country = (
                    alias_id.rsplit('.', 1)[-1].lower()
                    if '.' in alias_id else "")
                effective_country = ALIAS_COUNTRY_OVERRIDES.get(
                    country_code, country_code) if country_code else None
                if (not effective_country or not alias_country or
                        effective_country.lower() ==
                        _ALIAS_MAP_HOME_COUNTRY or
                        alias_country == effective_country.lower()):
                    feed_id = (_feed_spelling(alias_id, feed_ids)
                               if feed_ids else alias_id)
                    if feed_id:
                        print("[Match] ALIAS HIT: {} -> {}".format(
                            norm_name, feed_id))
                        return hit(feed_id, 'alias')

        search_key = self._normalize_key(channel_name, country_code or "")

        # 3. This box's own cache: its id counts while the feed has it
        # (an entry from an older matcher - Rytec's ids - often is not
        # one of the feed's, and is matched again).
        if search_key in self.normalized_index:
            cached_key = self.normalized_index[search_key]
            cached = self.cache.get(cached_key) or {}
            id_val = cached.get('id')
            if self.is_valid_epg_id(id_val):
                feed_id = (_feed_spelling(id_val, feed_ids)
                           if feed_ids else id_val)
                if feed_id:
                    promoted = self._try_promote_to_curated(
                        channel_name, country_code, servicetype,
                        channel_id, cached, allow_curated_promotion,
                        curated_db)
                    if promoted:
                        return promoted
                    print("[Match] Local cache HIT: {}".format(cached_key))
                    return hit(feed_id, cached.get('source') or 'live',
                               cached.get('sref'))
                print("[Match] Cache id '{}' is not in the {} feed, "
                      "will re-match".format(id_val, country_code))
            else:
                print("[Match] Local cache has invalid ID, will try to re-match.")

        # 4. The curated channel database. curated_db is the one
        # find_match() pre-fetched before taking self._cache_lock (see
        # its docstring) - not re-fetched here.
        if country_code and curated_db and channel_id:
            curated_id = curated_db.get(
                self._clean_name_for_similarity(channel_name))
            if curated_id:
                print("[Match] CURATED DB HIT: {} -> {}".format(
                    channel_name, curated_id))
                return hit(curated_id, 'curated')

        # 5. The feed's own channel names.
        print("[Match] Doing local matching for: {}".format(channel_name))
        if search_key in self.new_matches:
            m = self.new_matches[search_key]
            return m['id'], m['sref'], m.get('source', 'live')
        result_id, result_sref = self._match_feed_name(
            channel_name, country_code, channel_id=channel_id,
            servicetype=servicetype, feed_index=feed_index)
        if result_id:
            self.new_matches[search_key] = {
                'id': result_id,
                'sref': result_sref,
                'name': channel_name,
                'source': 'live'
            }
            save_unmatched(
                channel_name, country_code, servicetype, matched=True)
            return result_id, result_sref, 'live'

        # 6. Nothing. A cache entry for it no longer stands for a match
        # (its id is not the feed's): saved as matched=False here and
        # not through new_matches/update_complete_cache(), which always
        # writes matched=True. The save_cache() itself happens in
        # find_match(), after self._cache_lock is released (see its
        # comment on pending_save).
        # Resolved via normalized_index: the raw key an entry is stored
        # under can differ from search_key (name-cleaning rules changed
        # since it was written).
        existing_key = self.normalized_index.get(search_key, search_key)
        existing_entry = self.cache.get(existing_key)
        if existing_entry and existing_entry.get('matched') is not False:
            existing_entry['matched'] = False
            self.cache[existing_key] = existing_entry
            self._index_cache_key(existing_key)
            if pending_save is not None:
                pending_save.append(True)
        save_unmatched(channel_name, country_code, servicetype, matched=False)
        return None, None, None


# ==================== EPG CACHE FUNCTIONS ====================

# Safety-net cap: the matched-channel cache is meant to persist
# indefinitely (unlike vavoo_proxy.py's short-TTL resolve_cache), so
# this is deliberately generous - real usage (every unique channel
# name across every country a user has ever exported) tops out well
# below this. It only guards against unbounded/pathological growth,
# trimming the oldest entries by their own 'timestamp' field.
MAX_CACHE_ENTRIES = 15000


def _prune_cache_if_needed(cache, max_entries=MAX_CACHE_ENTRIES):
    """Drop the oldest entries (by 'timestamp') if cache exceeds max_entries."""
    if len(cache) <= max_entries:
        return cache
    try:
        ordered = sorted(
            cache.items(),
            key=lambda kv: kv[1].get('timestamp', ''),
        )
        to_drop = len(cache) - max_entries
        for key, _ in ordered[:to_drop]:
            del cache[key]
        print(
            "[Cache] Pruned {} oldest entries (cap: {})".format(
                to_drop, max_entries))
    except Exception as e:
        print("[Cache] Error pruning cache: {}".format(e))
    return cache


def load_cache():
    try:
        with open(CACHE_FILE, 'r') as f:
            data = load(f, object_pairs_hook=OrderedDict)
        # Converti tutte le chiavi in minuscolo per compatibilità
        return OrderedDict((k.lower(), v) for k, v in data.items())
    except BaseException:
        return OrderedDict()


def save_cache(cache):
    """Save cache to file with complete format validation (under
    _cache_file_lock)."""
    with _cache_file_lock:
        return _save_cache_unlocked(cache)


def _save_cache_unlocked(cache):
    try:
        required_fields = [
            'id',
            'name',
            'country',
            'sref',
            'timestamp',
            'matched']

        for key, value in cache.items():
            missing = [f for f in required_fields if f not in value]
            if missing:
                print(
                    "[Cache] ERROR: Entry {} missing fields: {}".format(
                        key, missing))
                return False

        cache = _prune_cache_if_needed(cache)
        temp_file = CACHE_FILE + ".tmp"
        with open(temp_file, 'w') as f:
            dump(cache, f, indent=2, sort_keys=True)
        rename(temp_file, CACHE_FILE)
        print("[Cache] Saved {} entries".format(len(cache)))
        return True
    except Exception as e:
        print("[Cache] Error saving cache: {}".format(e))
        return False


def load_favourites():
    """[{name, url, country_name, country_code, logo, folder,
    timestamp}] in the user's order, or [] - never raises (see
    vavoo_store)."""
    try:
        return vavoo_store.load_favourites()
    except Exception as e:
        print("[Favourites] Error loading {}: {}".format(FAVOURITES_FILE, e))
        return []


def favourite_urls():
    """The favourites' addresses (a channel is its address)."""
    try:
        return vavoo_store.favourite_urls()
    except Exception as e:
        print("[Favourites] Error loading {}: {}".format(FAVOURITES_FILE, e))
        return set()


def is_favourite(name, url):
    return vavoo_store.to_text(url) in favourite_urls()


def toggle_favourite(name, url, country_name=None, country_code=None,
                     logo=None):
    """Add the channel if it isn't a favourite yet (at the end, as in
    the app), remove it if it is. Returns the new state (True = now a
    favourite), or None on error.

    country_name/country_code are kept with the channel so a favourite
    played later is still checked against parental control's locked
    countries and still carries a country code for the programme
    guide - neither is known again once the screen that knew them is
    gone."""
    try:
        return vavoo_store.toggle_favourite(
            name, url, country_name, country_code, logo)
    except Exception as e:
        print("[Favourites] Error saving {}: {}".format(FAVOURITES_FILE, e))
        return None


# Recently watched channels (the app's "Recently watched"): newest
# first, each channel once. Under /etc/enigma2, so an update of the
# plugin (which replaces the plugin folder) keeps it.
RECENT_FILE = vavoo_store.recent_file()
RECENT_MAX = 20
# Every zap adds one, from a background thread (plugin.py) - two quick
# zaps must not write the file at the same time.
_recent_lock = threading.Lock()


def load_recent():
    """[{name, url, country_name, country_code, logo, timestamp}],
    newest first, or [] on any error / missing file - never raises."""
    try:
        if not isfile(RECENT_FILE):
            return []
        with open(RECENT_FILE, 'r') as f:
            data = load(f)
        if not isinstance(data, list):
            return []
        return [entry for entry in data
                if isinstance(entry, dict) and entry.get('name')
                and entry.get('url')][:RECENT_MAX]
    except Exception as e:
        print("[Recent] Error loading {}: {}".format(RECENT_FILE, e))
        return []


def _save_recent(entries):
    try:
        temp_file = RECENT_FILE + ".tmp"
        with open(temp_file, 'w') as f:
            dump(entries[:RECENT_MAX], f, indent=2)
        rename(temp_file, RECENT_FILE)
        return True
    except Exception as e:
        print("[Recent] Error saving {}: {}".format(RECENT_FILE, e))
        return False


def add_recent(name, url, country_name=None, country_code=None, logo=None):
    """Put a channel that was just watched at the top of the list
    (moved there if it was already in it). Same channel = same name and
    address, as for the favourites."""
    if not name or not url:
        return False
    with _recent_lock:
        entries = [entry for entry in load_recent()
                   if (entry.get('name'), entry.get('url')) != (name, url)]
        entries.insert(0, {
            'name': name,
            'url': url,
            'country_name': country_name,
            'country_code': country_code,
            'logo': logo or "",
            'timestamp': strftime('%Y-%m-%d %H:%M:%S', localtime()),
        })
        return _save_recent(entries)


def clear_recent():
    with _recent_lock:
        return _save_recent([])


_curated_channel_db_cache = {}
_curated_channel_db_lock = threading.Lock()
_CURATED_CHANNEL_DB_TTL = 86400
# How long a failed/empty fetch is remembered - see
# _load_curated_channel_db(). Same value and reasoning as
# _EPG_FEED_INDEX_NEGATIVE_TTL further down.
_CURATED_CHANNEL_DB_NEGATIVE_TTL = 60


def _load_curated_channel_db(country_code):
    """Fetch/cache this country's community-curated Vavoo channel name
    -> EPG feed channel id mapping (see generate_epg_channel_db.py),
    used as a fast, pre-solved alternative to matching names against
    the feed for names that match poorly. Keys are normalized the same
    way _clean_name_for_similarity() normalizes names for comparison
    elsewhere in this file - the generator script uses the identical
    normalization when building the file.

    Never raises - returns {} on any failure so callers just fall
    through to the existing matching chain, same convention as
    _get_epg_feed_index().
    """
    if not country_code:
        return {}

    with _curated_channel_db_lock:
        cached = _curated_channel_db_cache.get(country_code)
        if cached:
            ttl = (_CURATED_CHANNEL_DB_TTL if cached[1]
                   else _CURATED_CHANNEL_DB_NEGATIVE_TTL)
            if time() - cached[0] < ttl:
                return cached[1]

        # Held across the fetch itself (not just the cache read/write) -
        # this is a per-country cache and the lock is process-wide, so
        # two threads racing the SAME cold country previously could both
        # fire the network fetch; the tradeoff is two DIFFERENT
        # countries' cold-cache fetches now also serialize against each
        # other, which is fine given this only runs once per country
        # per export, not per channel.
        db = {}
        try:
            url = "{}/epg-channel-db/vavoo_channels_{}.json".format(
                HOST_MAIN, country_code.lower())
            data = getUrl(url, timeout=15, retries=1)
            if data:
                parsed = loads(ensure_str(data))
                if isinstance(parsed, dict):
                    db = parsed
        except Exception as e:
            debug(
                "Could not fetch curated channel db for {}: {}".format(
                    country_code, e))

        # A good result is kept for _CURATED_CHANNEL_DB_TTL. An empty
        # one (no file for this country, or GitHub unreachable right
        # now) is remembered too, but only for
        # _CURATED_CHANNEL_DB_NEGATIVE_TTL (see the ttl choice above):
        # find_match() asks for this on EVERY channel lookup, so not
        # remembering a failure at all meant one GitHub request per
        # channel for a country with no file - and, with GitHub
        # unreachable, up to this fetch's whole timeout per channel,
        # with this process-wide lock held the entire time. A minute is
        # short enough that a transient failure is retried by the next
        # export.
        _curated_channel_db_cache[country_code] = (time(), db)
        return db


def _merge_matched_into_cache_file(matcher, matched_channels, country_code):
    """CACHE_FILE read, the matched channels put in, written back (the
    caller holds _cache_file_lock). The new cache dict."""
    complete_cache = {}
    # Load existing cache
    if exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r') as f:
                complete_cache = load(f)
            print(
                "[Cache] Loaded %d existing entries" %
                len(complete_cache))
        except Exception as e:
            print("[Cache] Error loading cache: %s" % e)
            complete_cache = {}

    # Add matched channels (only these go to main cache)
    for m in matched_channels:
        key = matcher._normalize_key(m['name'], country_code)
        complete_cache[key] = {
            'id': m['feed_id'],
            'sref': ensure_sref_trailing_colon(m['dvb_ref']),
            'name': m['name'],
            'country': country_code,
            'matched': True,
            # Carried over from find_match()'s return value so a
            # future cache hit knows whether this entry already
            # came from the curated DB (see
            # _try_promote_to_curated()) without re-deriving it -
            # defaults to 'live' for callers that don't pass it
            # through (pre-existing entries/older code paths).
            'source': m.get('source', 'live'),
            'timestamp': strftime('%Y-%m-%d %H:%M:%S', localtime())
        }
        print("[Cache] Added matched: %s -> %s" % (key, m['feed_id']))

    # Save main cache
    complete_cache = _prune_cache_if_needed(complete_cache)
    temp_file = CACHE_FILE + ".tmp"
    with open(temp_file, 'w') as f:
        dump(complete_cache, f, indent=4, sort_keys=True)
    rename(temp_file, CACHE_FILE)
    return complete_cache


def update_complete_cache(
        matched_channels,
        unmatched_channels,
        country_code,
        servicetype="4097"):
    """Update the complete cache with matched channels only; unmatched go to unmatched.json.

    This is the sole writer of CACHE_FILE for a bouquet export -
    matched_channels (built by create_bouquet_file()/
    process_epg_matching_background()) is already a full superset of
    VavooEPGMatcher.new_matches (every entry added there came from a
    find_match() call that also produced a matched_channels entry), so
    a separate matcher.save_cache() call right before this one would
    just re-read, re-write, and re-index the exact same file a second
    time for no additional coverage. Clearing matcher.new_matches here
    takes over save_cache()'s other job - without it, that dict (a
    per-process singleton's, so never otherwise reset) would grow
    unbounded across every export for the life of the process.
    """
    try:
        matcher = get_epg_matcher()
        complete_cache = {}
        # (the file's read-modify-write under its own lock - the caller
        # holds export_lock, which nothing in here asks for again)
        _cache_file_lock.acquire()
        try:
            complete_cache = _merge_matched_into_cache_file(
                matcher, matched_channels, country_code)
        finally:
            _cache_file_lock.release()

        # Update matcher with new cache - under the same lock find_match()
        # holds around its own cache/normalized_index/new_matches use,
        # since this wholesale swap+clear can otherwise race with a
        # concurrent find_match() call on the same singleton (e.g. the
        # Now Playing EPG overlay) reading/writing those same attributes
        # mid-export.
        with matcher._cache_lock:
            matcher.cache = complete_cache
            matcher._build_normalized_index()
            matcher.new_matches.clear()

        # Process unmatched channels: save them to unmatched.json with their
        # original sref
        for u in unmatched_channels:
            # u should contain 'name' and optionally 'original_sref'
            sref = u.get('original_sref')  # if available
            save_unmatched(
                u['name'],
                country_code,
                servicetype,
                matched=False,
                sref=sref)

        print(
            "[Cache] Updated main cache with %d entries" %
            len(complete_cache))
    except Exception as e:
        print("[Cache] Error updating complete cache: %s" % e)
        trace_error()


def save_unmatched(
        channel_name,
        country_code,
        servicetype="4097",
        matched=False,
        sref=None):
    """Stage an unmatched-channel update in memory. Call flush_unmatched_cache()
       once per batch (e.g. once per bouquet export) to actually write it -
       see that function's docstring for why.
       If sref is provided, it will be used as the service reference;
       otherwise a fallback is built from servicetype.
    """
    global _unmatched_cache_dirty
    with _unmatched_lock:
        try:
            _load_unmatched_cache_locked()

            key = "%s_%s" % (channel_name.strip(), country_code or '')

            if matched and key in _unmatched_cache_data:
                # Remove if now matched
                del _unmatched_cache_data[key]
                _unmatched_cache_dirty = True
                print("[Unmatched] Removed matched channel: %s" % key)
            elif not matched:
                # Add or update unmatched
                timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
                # Use provided sref or build fallback
                if sref is not None:
                    fallback_sref = ensure_sref_trailing_colon(sref)
                else:
                    fallback_sref = "%s:0:0:0:0:0:0:0:0:0:" % servicetype

                old_data = _unmatched_cache_data.get(key, {})
                attempts = old_data.get('attempts', 0) + 1

                _unmatched_cache_data[key] = {
                    'id': key,
                    'name': channel_name.strip(),
                    'country': country_code or '',
                    'sref': fallback_sref,
                    'timestamp': timestamp,
                    'matched': False,
                    'attempts': attempts
                }
                _unmatched_cache_dirty = True
                print(
                    "[Unmatched] Staged: %s (attempt #%d)" %
                    (key, attempts))

        except Exception as e:
            print("[Unmatched] Error: %s" % e)


# In-memory mirror of UNMATCHED_FILE, lazily loaded once and kept for the
# life of the process instead of every save_unmatched() call doing its
# own full read+parse+write+rename - that was previously called once per
# channel processed (both matched and unmatched) during every bouquet
# export, from find_match() itself and again from callers looping over
# their own matched/unmatched lists, making a multi-hundred-channel
# export do a multi-hundred-entry full file rewrite that many times.
# All access must go through _unmatched_lock.
_unmatched_cache_data = None
_unmatched_cache_dirty = False


def _load_unmatched_cache_locked():
    """Populate _unmatched_cache_data from disk if not already loaded.
    Caller must already hold _unmatched_lock."""
    global _unmatched_cache_data
    if _unmatched_cache_data is not None:
        return
    data = {}
    if exists(UNMATCHED_FILE):
        try:
            with open(UNMATCHED_FILE, 'r') as f:
                content = f.read().strip()
                if content:
                    data = loads(content)
                    # Convert old format if needed
                    for key, value in list(data.items()):
                        if 'matched' not in value:
                            data[key] = {
                                'id': value.get('id', key),
                                'name': value.get(
                                    'name',
                                    key.split('_')[0] if '_' in key else key),
                                'country': value.get('country', ''),
                                'sref': value.get(
                                    'sref', "4097:0:0:0:0:0:0:0:0:0:"),
                                'timestamp': value.get(
                                    'timestamp', strftime(
                                        '%Y-%m-%d %H:%M:%S', localtime())),
                                'matched': False,
                                'attempts': 1}
                            print(
                                "[Unmatched] Converted old format: %s" % key)
        except Exception as read_error:
            print(
                "[Unmatched] Corrupted file, starting fresh: %s" %
                read_error)
            data = {}
    _unmatched_cache_data = data


def flush_unmatched_cache():
    """Write pending save_unmatched() updates to UNMATCHED_FILE, if any.
    Call once per batch (e.g. at the end of a bouquet export, alongside
    update_complete_cache()) - not once per channel."""
    global _unmatched_cache_dirty
    with _unmatched_lock:
        if not _unmatched_cache_dirty or _unmatched_cache_data is None:
            return
        try:
            temp_file = UNMATCHED_FILE + ".tmp"
            with open(temp_file, 'w') as f:
                dump(_unmatched_cache_data, f, indent=4, sort_keys=True)
            rename(temp_file, UNMATCHED_FILE)
            _unmatched_cache_dirty = False
            print(
                "[Unmatched] Cache flushed - total entries: %d" %
                len(_unmatched_cache_data))
        except Exception as e:
            print("[Unmatched] Error flushing cache: %s" % e)


# ---------------------------------------------------------------------
# Where a country's programmes come from (the Android app's Epg.kt):
# its daily files from epgshare01.online (EPG_DAILY_SOURCES, the
# Balkans from three) first, the copy on GitHub (EPG_COPY_URL) when
# they fail or are out of date. The proxy's /epg/<cc>.xml is the one
# place that chooses (country_epg_chunks() below), so the plugin's
# guide, the feed index and EPGImport all get the same thing - always
# plain XMLTV, never a .gz (EPGImport tells a .gz by its file name).
EPG_DAILY_FAIL_BACKOFF = 5 * 60        # the app's FAILED_BACKOFF_MS
EPG_DAILY_STALE_BACKOFF = 6 * 3600     # all programmes over: the copy
# A daily file not changed for this long is out of date (it covers
# several days ahead, so a day or two old still has programmes).
EPG_DAILY_MAX_AGE = 3 * 86400
_epg_daily_unusable = {}               # country -> time it may be tried again
_epg_daily_lock = threading.Lock()
_EPG_CHUNK = 65536


class EpgFeedStale(Exception):
    """The daily files are there but out of date."""


def _epg_code(country_code):
    return ensure_str(country_code or '', errors='ignore').strip().lower()


def epg_copy_url(country_code):
    """The GitHub copy of a country's guide."""
    return EPG_COPY_URL % _epg_code(country_code)


def epg_daily_urls(country_code):
    """The country's daily guide files, [] when it has none, or they
    failed or were out of date not long ago (mark_epg_daily_unusable())."""
    code = _epg_code(country_code)
    feeds = EPG_DAILY_SOURCES.get(code)
    if not feeds:
        return []
    with _epg_daily_lock:
        until = _epg_daily_unusable.get(code)
        if until is not None and time() < until:
            return []
    return [EPG_DAILY_URL % feed for feed in feeds]


def mark_epg_daily_unusable(country_code, seconds):
    """Use the GitHub copy for this country for `seconds`."""
    code = _epg_code(country_code)
    if not code:
        return
    with _epg_daily_lock:
        _epg_daily_unusable[code] = max(
            _epg_daily_unusable.get(code, 0), time() + seconds)


def _http_date(text):
    """An HTTP date ("Wed, 18 Nov 2026 03:10:00 GMT") as a time, or None."""
    try:
        parsed = parsedate_tz(text) if text else None
        return mktime_tz(parsed) if parsed else None
    except Exception:
        return None


def _file_name(url):
    return url.rsplit('/', 1)[-1]


def _open_daily_feed(url, opener):
    """A daily file, opened and checked: its first bytes (unpacked)
    and the stream. Raises EpgFeedStale for one not changed for
    EPG_DAILY_MAX_AGE, another error for anything not an XMLTV file
    (a server's error page)."""
    stream = opener(url, timeout=30)
    try:
        modified = response_header(stream, 'Last-Modified')
        changed = _http_date(modified)
        if changed is not None and time() - changed > EPG_DAILY_MAX_AGE:
            raise EpgFeedStale("%s not changed since %s" % (
                _file_name(url), modified))
        head = b''
        while len(head) < 4096:
            data = stream.read(_EPG_CHUNK)
            if not data:
                break
            head += data
        if b'<tv' not in head[:8192]:
            raise ValueError("%s is not an XMLTV file" % _file_name(url))
        return head, stream
    except Exception:
        stream.close()
        raise


_XMLTV_MARK = compile(br'<(channel|programme)[\s>/]|</tv\s*>')
_XMLTV_KEY = {
    b'channel': compile(br'\sid\s*=\s*(?:"([^"]*)"|\'([^\']*)\')'),
    b'programme': compile(br'\schannel\s*=\s*(?:"([^"]*)"|\'([^\']*)\')'),
}


class _XmltvPieces(object):
    """An XMLTV file's bytes cut into its elements as they arrive, with
    no XML tree: ("head", text) - all before the first channel or
    programme; ("channel", id, text); ("programme", channel, text);
    ("tail", text) - from </tv> on. Each element's text runs up to the
    next one (the white space between them goes with it)."""

    def __init__(self):
        self._buf = b''
        self._kind = b'head'
        self._from = 0       # where the next mark may start in _buf

    def _piece(self, text):
        kind = self._kind
        pattern = _XMLTV_KEY.get(kind)
        if pattern is not None:
            match = pattern.search(text[:1024])
            key = (match.group(1) or match.group(2) or b'') if match else b''
            return (kind.decode('ascii'), key, text)
        return (kind.decode('ascii'), text)

    def feed(self, data):
        buf = self._buf + data
        out = []
        start = 0
        if self._kind != b'tail':
            for match in _XMLTV_MARK.finditer(buf, self._from):
                if match.start() > start or self._kind == b'head':
                    out.append(self._piece(buf[start:match.start()]))
                start = match.start()
                self._kind = match.group(1) or b'tail'
                if self._kind == b'tail':
                    break
        self._buf = buf[start:]
        # The element just begun is at 0 (its own mark is not the next
        # one); a mark cut in two by the chunk's end is found next time.
        self._from = max(0 if self._kind == b'head' else 1,
                         len(self._buf) - 16)
        return out

    def finish(self):
        out = [self._piece(self._buf)] if self._buf else []
        self._buf = b''
        return out


def _feed_pieces(head, stream, breather):
    """Every piece of one file: `head` (its first bytes, already read)
    and then the rest of `stream`."""
    pieces = _XmltvPieces()
    data = head
    while data:
        for piece in pieces.feed(data):
            yield piece
        breather.tick()
        data = stream.read(_EPG_CHUNK)
    for piece in pieces.finish():
        yield piece


def country_epg_chunks(country_code, urls, opener=None):
    """A country's guide as plain XMLTV bytes, from its daily files
    `urls` (epg_daily_urls()). A generator: the first next() raises
    if nothing can be read (EpgFeedStale when what is there is out of
    date) - then the caller sends the GitHub copy instead. Closing it
    closes the downloads.

    One file goes through as it is (unpacked). Several make one guide,
    as in the app: each channel from the first file that has it, with
    that file's programmes. In two passes, because the channels must
    all come before the first programme (_read_epg_feed_channels()
    stops there): first every file's channels (each file read only up
    to its first programme), then every file's programmes - the files
    are opened again for that, one at a time. A file that fails is
    left out; all of them failing is the error."""
    opener = opener or open_url_stream
    code = _epg_code(country_code)
    breather = _Breather()
    if len(urls) == 1:
        head, stream = _open_daily_feed(urls[0], opener)
        try:
            data = head
            while data:
                yield data
                breather.tick()
                data = stream.read(_EPG_CHUNK)
        finally:
            stream.close()
        return

    # 1. The channels, and whose each one is.
    owner = {}
    usable = []
    channel_text = []
    first_head = None
    problems = []
    for index, url in enumerate(urls):
        try:
            head, stream = _open_daily_feed(url, opener)
        except Exception as e:
            problems.append(e)
            warning(
                "EPG {}: {} not read ({})".format(
                    code, _file_name(url), e))
            continue
        try:
            for piece in _feed_pieces(head, stream, breather):
                if piece[0] == 'head':
                    if first_head is None:
                        first_head = piece[1]
                elif piece[0] == 'channel':
                    if piece[1] not in owner:
                        owner[piece[1]] = index
                        channel_text.append(piece[2])
                else:
                    break
        except Exception as e:
            problems.append(e)
            warning(
                "EPG {}: {} not read ({})".format(
                    code, _file_name(url), e))
            continue
        finally:
            stream.close()
        usable.append(index)
    if not usable:
        if problems and all(isinstance(e, EpgFeedStale) for e in problems):
            raise EpgFeedStale("; ".join(str(e) for e in problems))
        raise IOError("; ".join(str(e) for e in problems) or "no feed")
    yield first_head or b'<?xml version="1.0" encoding="UTF-8"?>\n<tv>\n'
    for text in channel_text:
        yield text
    del channel_text[:]

    # 2. The programmes, each from its channel's file.
    for index in usable:
        url = urls[index]
        try:
            head, stream = _open_daily_feed(url, opener)
        except Exception as e:
            warning("EPG {}: {} programmes not read ({})".format(
                code, _file_name(url), e))
            continue
        try:
            for piece in _feed_pieces(head, stream, breather):
                if piece[0] == 'programme':
                    if owner.setdefault(piece[1], index) == index:
                        yield piece[2]
                elif piece[0] == 'tail':
                    break
        except Exception as e:
            # (what was sent stays: the rest of the guide still counts)
            warning("EPG {}: {} programmes cut short ({})".format(
                code, _file_name(url), e))
        finally:
            stream.close()
    yield b'</tv>\n'


# country_code -> (timestamp, set(ids), {clean_name: id})
_epg_feed_index_cache = {}
_EPG_FEED_INDEX_TTL = 300
# getUrl() swallows the HTTP status code on any failure (always returns
# "" whether it was a genuine 404 or a transient timeout/connection
# error), so a permanent "this country has no feed" can't be reliably
# told apart from a one-off blip here. Cache a failure/empty result
# much more briefly than a real success - still long enough to avoid
# re-fetching per unmatched channel within one export (which can be
# hundreds of calls in a few seconds), but short enough that a
# transient failure doesn't keep the feed-fallback disabled for the
# rest of an in-progress export or an immediate retry.
_EPG_FEED_INDEX_NEGATIVE_TTL = 60


def _get_epg_feed_index(country_code):
    """
    Fetch and index this country's actual EPG feed: the set of
    <channel id> values it defines, plus a cleaned-display-name -> id
    lookup.

    Used by find_match() (the ids it gives are the feed's own: the
    source's guide id, an alias or a cache entry counts only when the
    feed has it; the last step matches the feed's display names) and
    by write_epg_mapping_file() for exported bouquets.

    Never raises - returns (None, None) on any failure so callers just
    skip the fallback and keep existing (correct-for-most-channels)
    behavior.
    """
    if not country_code:
        return None, None

    # A programme guide already in memory for this country (see
    # load_epg_guide()) was read from this very file and carries the
    # same channel list - no need to ask the network for it again.
    # find_match() calls this once per channel, and the channel list's
    # Now/Next panel calls find_match() for every row the user stops
    # on, right after loading that guide.
    guide = peek_epg_guide(country_code)
    if guide is not None and guide.feed_ids:
        return guide.feed_ids, guide.name_index

    cached = _epg_feed_index_cache.get(country_code)
    if cached:
        cached_time, cached_ids, cached_index = cached
        ttl = (_EPG_FEED_INDEX_TTL if cached_ids is not None
               else _EPG_FEED_INDEX_NEGATIVE_TTL)
        if time() - cached_time < ttl:
            return cached_ids, cached_index

    url = "http://{}:{}/epg/{}.xml".format(
        PROXY_HOST, PORT, country_code.lower())
    feed_ids = None
    name_index = None
    last_error = None
    # Two tries, as before (this used to be getUrl(url, retries=2)).
    for _attempt in range(2):
        stream = None
        try:
            # These files are 2 to 60 MB (a multi-day guide for every
            # channel in the country), almost all of it <programme>
            # entries, with the <channel> definitions this needs all at
            # the very top, per the XMLTV convention. Read as a stream
            # and stop at the first <programme>: that is the first few
            # hundred KB (less, compressed) instead of the whole file,
            # which this used to download in full on every call just to
            # read that list.
            stream = open_url_stream(url, timeout=30)
            feed_ids, name_index = _read_epg_feed_channels(stream)
            break
        except Exception as e:
            last_error = e
            feed_ids = None
            name_index = None
        finally:
            if stream is not None:
                stream.close()

    if not feed_ids:
        warning(
            "Could not read the EPG feed's channel list for {} ({}) - "
            "ids are not checked against it and channels are not "
            "matched by the feed's names".format(
                country_code, last_error or "empty"))
        # Remember the failure too (briefly): a country with no feed at
        # all (most of them - only a minority of country codes have
        # one) would otherwise re-attempt this same failing fetch for
        # every single channel instead of once per TTL window.
        _epg_feed_index_cache[country_code] = (time(), None, None)
        return None, None

    _epg_feed_index_cache[country_code] = (time(), feed_ids, name_index)
    return feed_ids, name_index


def _index_epg_feed_channel(elem, feed_ids, name_index, folded_names=None):
    """Record one <channel> element of an EPG feed: its id, and each
    of its display names, cleaned, -> (id, tokens). With
    `folded_names`, also each cleaned name without its accents -> id
    (see EpgGuide.folded_names)."""
    chan_id = elem.get('id')
    if not chan_id:
        return
    feed_ids.add(chan_id)
    for dn in elem.findall('display-name'):
        dn_text = (dn.text or '').strip()
        if not dn_text:
            continue
        clean_dn = clean_name_for_similarity(dn_text)
        if clean_dn and folded_names is not None:
            folded_names.setdefault(_fold_accents(clean_dn), chan_id)
        if clean_dn:
            # Tokens precomputed once here rather than by every
            # _find_feed_id_by_name() call that scans this same index
            # (once per channel the earlier steps of find_match() do
            # not place, which can be a large fraction of a country's
            # channels).
            name_index[clean_dn] = (
                chan_id, _tokenize_for_compat(clean_dn))


def _read_epg_feed_channels(stream):
    """(set of channel ids, {cleaned display name: (id, tokens)}) from
    the top of an EPG feed, reading no further than the first
    <programme>."""
    feed_ids = set()
    name_index = {}
    for event, elem in _fast_ET.iterparse(stream, events=('start', 'end')):
        if event == 'end' and elem.tag == 'channel':
            _index_epg_feed_channel(elem, feed_ids, name_index)
            elem.clear()
        elif event == 'start' and elem.tag == 'programme':
            break
    return feed_ids, name_index


# _tokenize_for_compat/_token_pair_compatible/_tokens_compatible are
# thin aliases onto epg_name_utils - single source of truth, shared
# with generate_epg_channel_db.py's off-box mirror. Kept as
# module-level names here since they're called that way throughout
# this file.
_tokenize_for_compat = tokenize_for_compat
_token_pair_compatible = token_pair_compatible
_tokens_compatible = tokens_compatible


def _find_feed_id_by_name(channel_name, matcher, name_index):
    """Fuzzy-match channel_name against an EPG feed's display-name index."""
    if not name_index:
        return None
    clean = matcher._clean_name_for_similarity(channel_name)
    if not clean:
        return None
    # name_index is already keyed by this exact cleaned name
    # (_get_epg_feed_index() builds it that way) - an exact hit means
    # the fuzzy loop below (a full scan, scored with SequenceMatcher)
    # isn't needed at all.
    exact = name_index.get(clean)
    if exact:
        return exact[0]
    source_tokens = _tokenize_for_compat(clean)
    best_score = 0.0
    best_id = None
    threshold = matcher.similarity_threshold
    sm = SequenceMatcher(None, clean)
    breather = _Breather()
    # Only the threshold-or-above outcome is ever used by callers (a
    # below-threshold best_score is never returned), so a
    # candidate whose cheap upper-bound estimate already can't reach the
    # threshold can be skipped before paying for the full ratio()
    # computation. Feed indexes run into the hundreds/thousands of
    # entries (see this function's callers), scanned once per exported
    # channel the earlier steps of find_match() do not place, so this
    # matters for country-wide export time.
    for dn_key, (dn_id, candidate_tokens) in name_index.items():
        breather.tick()
        if (source_tokens and candidate_tokens and
                not _tokens_compatible(source_tokens, candidate_tokens)):
            continue
        sm.set_seq2(dn_key)
        if sm.real_quick_ratio() < threshold:
            continue
        if sm.quick_ratio() < threshold:
            continue
        score = sm.ratio()
        if score > best_score:
            best_score = score
            best_id = dn_id
    if best_id and best_score >= threshold:
        return best_id
    return None


# ---------------------------------------------------------------------
# Programme guide: what is on now, and what comes next
# ---------------------------------------------------------------------
# One country's epg_<cc>.xml reduced to what the channel list's
# Now/Next panel and the player's OK overlay need.
#
# The files are 2 to 60 MB of XML with 15 000 to 110 000 programmes
# (measured: tr 2.4 MB, it 13.6, pt 16.7, es 20.4, de 21.3, fr 46.1,
# pl 63.2). The overlay used to download one whole, build the complete
# document in memory with ET.fromstring() and keep it - hundreds of MB
# on a set-top box for the larger countries, never freed. Here the
# file is read while it downloads (compressed: about a tenth of the
# size on the wire) and only the programmes that can still matter are
# kept, as small tuples: a few MB at most.
#
# Times: every entry carries its own UTC offset and the files mix
# them freely ("+0000", "+0100", "+0300", "-0600" all occur, pl is
# almost entirely "-0600"). The offset used to be thrown away and the
# rest read as UTC, which is only right for "+0000": the programme
# shown as current was 1 hour off for es, 3 for tr, 6 for pl.

# A loaded guide is reused this long before it is fetched again: it
# holds programmes from 3 hours before its load to 24 hours after it,
# so at 6 hours old it still reaches 18 hours ahead. (It was 1 hour:
# reading a large guide costs a set-top box 10-30 s of a core, and a
# box playing a channel paid that every hour - seen as overload.)
_EPG_GUIDE_TTL = 6 * 3600
# If fetching it again fails, the old copy is still used up to this
# age (12 hours ahead left) before giving up on it.
_EPG_GUIDE_STALE_MAX = 12 * 3600
# After a failed load, wait this long before the next attempt.
_EPG_GUIDE_RETRY = 120
# Programmes are kept from this long before load time (the guide grid
# looks back 3 hours, as the app's) to this long after it (the grid's
# window reaches its end). Measured with the largest files: pl keeps
# about 22 000 programmes in 11 MB, fr 17 000 in 6 MB (12 hours ahead
# and nothing before, as it used to be: 6 and 3 MB).
_EPG_GUIDE_BEHIND = 3 * 3600
_EPG_GUIDE_AHEAD = 24 * 3600
# Countries kept in memory at once (least recently used goes first) -
# three (a large one is ~10 MB; a box with 1 GB was seen running out of
# memory), still enough for a page of Favourites mixing countries.
_EPG_GUIDE_KEEP = 3
# Descriptions are cut to this many characters; they are only ever
# shown in the player overlay's few lines.
_EPG_GUIDE_DESC_MAX = 400
# Per network read, not for the whole download.
_EPG_GUIDE_TIMEOUT = 20
# Widest UTC offset an XMLTV time can carry (real ones span -12h to
# +14h) - see the coarse pre-filter in _parse_epg_guide().
_XMLTV_MAX_OFFSET = 14 * 3600

_XMLTV_TIME_RE = compile(
    r'^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})?'
    r'\s*(?:([+-])(\d{2}):?(\d{2})|Z|UTC|GMT)?$')

_epg_guide_cache = {}       # country code -> EpgGuide
_epg_guide_failed = {}      # country code -> time of the last failed load
_epg_guide_load_locks = {}  # country code -> Lock held while downloading
# Guards the three dicts above (never held during a download).
_epg_guide_lock = threading.Lock()


# Character codes that reached the file as text instead of as the
# character: "Praça" - or, with the backslash lost on the way,
# "Prau00e7a" - for "Praça". Counted in the real files: about 1400
# titles/descriptions in pl (nearly all "&" for "&") and 90 in
# pt ("Prau00e7a da Alegria", "O Preu00e7o Certo", ...).
_BROKEN_ESCAPE_RE = compile(r'(\\?)u00([0-9a-fA-F]{2})')

# Letters that Unicode does not split into "base letter + accent",
# for _fold_accents().
_UNSPLIT_LETTERS = {
    u'ł': u'l', u'Ł': u'L',     # l with stroke (pl)
    u'ø': u'o', u'Ø': u'O',     # o with stroke
    u'đ': u'd', u'Đ': u'D',     # d with stroke
    u'ı': u'i',                      # dotless i (tr)
    u'ß': u'ss',
    u'æ': u'ae', u'Æ': u'AE',
    u'œ': u'oe', u'Œ': u'OE',
}


def _repair_guide_text(text):
    """Put back characters that arrived as their code (see
    _BROKEN_ESCAPE_RE). With the backslash still there it is
    unmistakable; without it only codes of accented letters are
    touched, so ordinary text that merely contains "u00" and two more
    hex digits ("Menu0026") is left alone."""
    if 'u00' not in text:
        return text

    def _put_back(m):
        code = int(m.group(2), 16)
        if code < 0x20 or (not m.group(1) and code < 0xA0):
            return m.group(0)
        if code == 0xA0:
            return u' '
        return unichr(code)

    return _BROKEN_ESCAPE_RE.sub(_put_back, text)


def _fold_accents(text):
    """Text with its accents dropped ("notícias" -> "noticias"), for
    comparing a channel name written without them - Vavoo's lists
    often are: "SIC NOTICIAS", "RTP ACORES" - against a guide that
    writes them."""
    text = ensure_str(text, errors='ignore')
    return u''.join(
        _UNSPLIT_LETTERS.get(ch, ch)
        for ch in normalize('NFKD', text) if not combining(ch))


def parse_xmltv_time(value):
    """An XMLTV time such as "20261111233000 +0100" as Unix time (an
    int), or None if it is not one. No offset means UTC.

    Parsed by hand rather than with datetime.strptime(): this runs
    from background threads, and strptime()'s first call from two
    threads at once is a known crash on Python 2 (its lazy import of
    _strptime is not thread-safe).
    """
    if not value:
        return None
    m = _XMLTV_TIME_RE.match(value.strip())
    if not m:
        return None
    try:
        timestamp = calendar.timegm((
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6) or 0),
            0, 0, 0))
    except (ValueError, OverflowError):
        return None
    if m.group(7):
        offset = int(m.group(8)) * 3600 + int(m.group(9)) * 60
        # "23:30 +0100" is 22:30 UTC: local = UTC + offset.
        if m.group(7) == '+':
            timestamp -= offset
        else:
            timestamp += offset
    return timestamp


def epg_clock(timestamp):
    """A Unix time as "HH:MM" on this box's own clock."""
    return strftime('%H:%M', localtime(timestamp))


def _guide_id(feed_id):
    """A feed channel id as text. On Python 2 an id arrives as UTF-8
    bytes from one place and as unicode from another
    ("RTP.África.pt"); as text it still meets itself."""
    return ensure_str(feed_id, errors='ignore')


class EpgGuide(object):
    """One country's programme guide, reduced to the hours around now.

    programmes: {feed channel id: [(start, stop, title, description),
    ...]} sorted by start, times as Unix time, from _EPG_GUIDE_BEHIND
    before load time to _EPG_GUIDE_AHEAD after it. Only channels that
    have something in those hours are in it.
    feed_ids / name_index: the feed's own channel list, in the exact
    shape _get_epg_feed_index() returns it.
    """

    def __init__(self, country_code, loaded_at):
        self.country_code = country_code
        self.loaded_at = loaded_at
        self.last_used = loaded_at
        self.programmes = {}
        # id with its dots dropped -> the id in `programmes` to use
        # for it - see channel_for().
        self.dotless = {}
        self.feed_ids = set()
        self.name_index = {}
        # cleaned display name with its accents dropped -> feed id
        # (the first channel carrying that name) - see
        # _resolve_guide_channel().
        self.folded_names = {}
        self.programme_count = 0
        # cleaned channel name -> id in `programmes` ("" = not in
        # this guide), so a channel is matched once per loaded guide
        # and every later look at it is a dictionary lookup.
        self.resolved = {}

    def age(self):
        return time() - self.loaded_at

    def channel_for(self, some_id):
        """The id in `programmes` that `some_id` means, or None.

        The id itself if this guide has programmes under it. Failing
        that, an id that differs from it only in its dots: the EPG
        matcher often hands back another source's spelling of the
        same channel ("RTP1.pt" for the feed's "RTP.1.pt"), which is
        the comparison the player overlay has always made.

        Exact first, and never the two merged: the real files list
        some channels twice under ids that differ only in dots
        (fr: "France.2.fr" and "France.2..fr", also France 3/4/5 and
        Arte; it: "Sky.Uno.+.it" and "Sky.Uno.+..it"), and the two
        copies do not agree on the time zone - in the French file the
        same programme sits one hour apart in them. Mixing them, as
        keying everything by its dotless form used to, gives a
        schedule that jumps between the two.
        """
        if not some_id:
            return None
        text = _guide_id(some_id)
        if text in self.programmes:
            return text
        return self.dotless.get(text.replace('.', ''))

    def now_next(self, key, now=None):
        """(current, following) for one id in `programmes`; either
        can be None. Each is a (start, stop, title, description)
        tuple."""
        entries = self.programmes.get(key)
        if not entries:
            return None, None
        if now is None:
            now = time()
        current = None
        following = None
        for entry in entries:
            if entry[0] > now:
                following = entry
                break
            if now < entry[1]:
                # Overlapping entries (it happens): the one that
                # started last is the one on air.
                current = entry
        return current, following

    def between(self, key, start, stop):
        """The programmes of one id that are on at any moment between
        `start` and `stop` (the guide grid's window), by start time."""
        return [entry for entry in self.programmes.get(key) or ()
                if entry[1] > start and entry[0] < stop]

    def schedule(self, key, count=4, now=None):
        """The programme on now (if any) and the ones after it, up to
        `count` in all - the player's mini guide. Same tuples as
        now_next()."""
        entries = self.programmes.get(key)
        if not entries:
            return []
        if now is None:
            now = time()
        out = []
        for entry in entries:
            if entry[1] <= now:
                continue
            if out and entry[0] <= now:
                # Overlapping entries: the one that started last is
                # the one on air (as in now_next()).
                out[-1] = entry
                continue
            out.append(entry)
            if len(out) >= count:
                break
        return out


def _parse_epg_guide(stream, country_code, now):
    """Read an XMLTV stream into an EpgGuide - see the notes above."""
    guide = EpgGuide(country_code, now)
    keep_from = now - _EPG_GUIDE_BEHIND
    keep_until = now + _EPG_GUIDE_AHEAD
    # Most of a file is other days. An entry's digits, read as if they
    # were UTC, are at most _XMLTV_MAX_OFFSET away from its real time,
    # so anything outside this wider range can be dropped on a plain
    # string comparison, before paying for two timestamp conversions.
    coarse_from = strftime(
        '%Y%m%d%H%M%S', gmtime(keep_from - _XMLTV_MAX_OFFSET))
    coarse_until = strftime(
        '%Y%m%d%H%M%S', gmtime(keep_until + _XMLTV_MAX_OFFSET))

    programmes = guide.programmes
    # One programme's stop is normally the next one's start.
    parsed_times = {}
    kept = 0
    root = None
    breather = _Breather()
    for event, elem in _fast_ET.iterparse(stream, events=('start', 'end')):
        breather.tick()
        if event == 'start':
            if root is None:
                root = elem
            continue
        tag = elem.tag
        if tag == 'programme':
            channel = elem.get('channel')
            start_raw = elem.get('start') or ''
            stop_raw = elem.get('stop') or ''
            if (channel and stop_raw[:14] >= coarse_from
                    and start_raw[:14] <= coarse_until):
                if len(parsed_times) > 2000:
                    # Only the last few are ever asked for again.
                    parsed_times.clear()
                start = parsed_times.get(start_raw)
                if start is None:
                    start = parsed_times[start_raw] = parse_xmltv_time(
                        start_raw)
                stop = parsed_times.get(stop_raw)
                if stop is None:
                    stop = parsed_times[stop_raw] = parse_xmltv_time(
                        stop_raw)
                if (start is not None and stop is not None
                        and start < stop
                        and stop > keep_from and start < keep_until):
                    title = _repair_guide_text(
                        elem.findtext('title') or '').strip()
                    description = _repair_guide_text(
                        elem.findtext('desc') or '').strip()
                    if len(description) > _EPG_GUIDE_DESC_MAX:
                        description = (
                            description[:_EPG_GUIDE_DESC_MAX].rstrip() +
                            '...')
                    programmes.setdefault(_guide_id(channel), []).append(
                        (start, stop, title, description))
                    kept += 1
            # Drop the element, and everything read so far, from the
            # tree iterparse() builds behind the scenes - without this
            # the whole document would pile up in memory anyway.
            root.clear()
        elif tag == 'channel':
            _index_epg_feed_channel(
                elem, guide.feed_ids, guide.name_index, guide.folded_names)
            root.clear()

    for entries in programmes.values():
        # By time only: never let two entries with the same times fall
        # through to comparing their titles (bytes against unicode on
        # Python 2).
        entries.sort(key=lambda entry: (entry[0], entry[1]))
    # Of several ids that are the same but for their dots, the
    # shortest stands for all of them when a lookup only matches
    # without dots (see EpgGuide.channel_for()): the longer ones
    # ("France.2..fr", "Arte...fr") come from a source that turned a
    # stray space or sign in the channel's name into an extra dot,
    # and in the files checked those are the copies with the wrong
    # time zone. Not dependent on the order in the file.
    dotless = guide.dotless
    for feed_id in programmes:
        key = feed_id.replace('.', '')
        other = dotless.get(key)
        if other is None or len(feed_id) < len(other):
            dotless[key] = feed_id
    guide.programme_count = kept
    return guide


def _guide_is_current(guide, now):
    """Whether any programme of this guide is still to end (the app's
    requireCurrent: a file nobody updates any more has none)."""
    for entries in guide.programmes.values():
        for entry in entries:
            if entry[1] > now:
                return True
    return False


def _download_epg_guide(country_code):
    """Fetch and read one country's guide. None on any failure
    (including "this country has no guide file": a 404).

    The proxy answers with the daily files (X-Vavoo-EPG: daily) or the
    GitHub copy. Daily files whose programmes are all over are out of
    date: the copy is used for this country for EPG_DAILY_STALE_BACKOFF
    and fetched at once."""
    url = "http://{}:{}/epg/{}.xml".format(PROXY_HOST, PORT, country_code)
    for _attempt in range(2):
        started = time()
        stream = None
        try:
            stream = open_url_stream(url, timeout=_EPG_GUIDE_TIMEOUT)
            source = (
                "daily" if response_header(
                    stream,
                    'X-Vavoo-EPG') == 'daily' else "GitHub copy")
            guide = _parse_epg_guide(stream, country_code, started)
            received = stream.bytes_received
        except Exception as e:
            warning("Could not load the programme guide for {}: {}".format(
                country_code, e))
            return None
        finally:
            if stream is not None:
                stream.close()
        if source == "daily" and not _guide_is_current(guide, started):
            print("[EPG] Guide {}: daily feeds out of date, using the "
                  "GitHub copy".format(country_code))
            mark_epg_daily_unusable(country_code, EPG_DAILY_STALE_BACKOFF)
            continue
        break
    if not guide.feed_ids and not guide.programmes:
        warning("Programme guide for {} is empty".format(country_code))
        return None
    print("[EPG] Guide {} loaded in {:.1f}s: {} channels, {} programmes "
          "kept, {} KB downloaded ({}, {})".format(
              country_code, time() - started, len(guide.feed_ids),
              guide.programme_count, received // 1024, source,
              memory_note()))
    return guide


def _usable_epg_guide(guide):
    """A guide that can still answer (fresh, or stale but recent)."""
    return guide is not None and guide.age() < _EPG_GUIDE_STALE_MAX


def release_guides(keep=None):
    """Drop the guides held in memory, but `keep`'s (the country being
    watched) - the box is short of memory. Returns how many went."""
    keep = ensure_str(keep or '', errors='ignore').lower()
    with _epg_guide_lock:
        gone = [code for code in _epg_guide_cache if code != keep]
        for code in gone:
            del _epg_guide_cache[code]
    return len(gone)


def peek_epg_guide(country_code):
    """The guide for this country if a usable one is already in
    memory, else None. Never touches the network, so it is safe on
    the GUI thread."""
    code = ensure_str(country_code or '', errors='ignore').lower()
    if not code:
        return None
    with _epg_guide_lock:
        guide = _epg_guide_cache.get(code)
        if not _usable_epg_guide(guide):
            return None
        guide.last_used = time()
        return guide


def load_epg_guide(country_code):
    """The guide for this country, downloading it if there is none in
    memory or the one there is older than _EPG_GUIDE_TTL. Blocks for
    the length of the download - call it from a background thread.

    Returns None when there is nothing usable (no guide file for this
    country, or the download failed and no recent copy is left).
    Several threads asking for the same country share one download.
    """
    code = ensure_str(country_code or '', errors='ignore').lower()
    if not code:
        return None

    def _current():
        """(guide or None, whether a download should be tried) -
        call with _epg_guide_lock held."""
        guide = _epg_guide_cache.get(code)
        if guide is not None and guide.age() < _EPG_GUIDE_TTL:
            guide.last_used = time()
            return guide, False
        if not _usable_epg_guide(guide):
            guide = None
        failed_at = _epg_guide_failed.get(code)
        if failed_at is not None and time() - failed_at < _EPG_GUIDE_RETRY:
            return guide, False
        return guide, True

    with _epg_guide_lock:
        guide, should_load = _current()
        if not should_load:
            return guide
        load_lock = _epg_guide_load_locks.get(code)
        if load_lock is None:
            load_lock = _epg_guide_load_locks[code] = threading.Lock()

    with load_lock:
        # Another thread may have finished the same download (or just
        # failed at it) while this one waited for the lock.
        with _epg_guide_lock:
            guide, should_load = _current()
            if not should_load:
                return guide

        fresh = _download_epg_guide(code)

        with _epg_guide_lock:
            if fresh is None:
                _epg_guide_failed[code] = time()
                return guide
            _epg_guide_failed.pop(code, None)
            _epg_guide_cache[code] = fresh
            while len(_epg_guide_cache) > _EPG_GUIDE_KEEP:
                oldest = min(
                    (other for other in _epg_guide_cache if other != code),
                    key=lambda other: _epg_guide_cache[other].last_used)
                del _epg_guide_cache[oldest]
            return fresh


# preload_epg_guides() loads nothing while the box has less than this
# available (MemAvailable)
PRELOAD_MIN_FREE_KB = 200 * 1024


def preload_epg_guides(country_codes, go_on=None, max_new=2,
                       min_free_kb=PRELOAD_MIN_FREE_KB, meminfo=None):
    """Load these countries' guides ahead of use (the favourites'
    countries, when the main list has settled), one at a time - each
    is a download and a parse that rests for other threads (_Breather).
    Blocks: a background thread only. Skips a guide already in memory
    or one that failed a moment ago; stops after `max_new`, when one
    more would push another guide out (one place under
    _EPG_GUIDE_KEEP stays free), when the box has less than
    `min_free_kb` available, or when go_on() says no (the player
    opened - no download while a stream plays). The codes loaded."""
    meminfo = meminfo or read_meminfo
    loaded = []
    for code in country_codes:
        code = ensure_str(code or '', errors='ignore').lower()
        if not code or code in loaded:
            continue
        if len(loaded) >= max_new or (go_on is not None and not go_on()):
            break
        with _epg_guide_lock:
            guide = _epg_guide_cache.get(code)
            if guide is not None and guide.age() < _EPG_GUIDE_TTL:
                continue
            failed_at = _epg_guide_failed.get(code)
            if failed_at is not None and time() - failed_at < _EPG_GUIDE_RETRY:
                continue
            if len(_epg_guide_cache) >= _EPG_GUIDE_KEEP - 1:
                break
        available = meminfo().get("MemAvailable")
        if available is not None and available < min_free_kb:
            print(
                "[EPG] Guides not loaded ahead: {} MB available".format(
                    available // 1024))
            break
        if load_epg_guide(code) is not None:
            loaded.append(code)
    if loaded:
        print("[EPG] Guides ready ahead: {}".format(", ".join(loaded)))
    return loaded


def _guide_channel_name(channel_name):
    """A channel name the way it is handed to the matcher for a guide
    lookup - what the player overlay has always done to it first."""
    return remove_parentheses(decodeHtml(channel_name))


def _resolve_guide_channel(guide, clean_name, country_code, channel_id,
                           epg_id=None):
    """The id in guide.programmes for this channel, "" if the guide
    has nothing for it. Slow the first time for a channel (it runs the
    EPG matcher), a dictionary lookup afterwards.

    The same two steps the player overlay has always taken: the id
    find_match() gives (the catalog's own guide id, alias table, local
    cache, curated database, the feed's own names - see its
    docstring), and if this
    feed has no programmes under that id, the channel's name against
    the feed's own channel names - which now also finds a name that
    differs only in its accents. `epg_id`: the catalog's own guide id
    for the channel, when known (find_match()'s epg_guide_id).
    """
    key = guide.resolved.get(clean_name)
    if key is not None:
        return key

    # The catalog's own guide id (geil.to's), when this guide has
    # programmes under it, is the answer - no matcher at all (the
    # app's sourceId(); most of geil.to's channels).
    if epg_id:
        key = guide.channel_for(
            _feed_spelling(epg_id, guide.feed_ids) or epg_id) or ''
        if key:
            guide.resolved[clean_name] = key
            return key

    matcher = get_epg_matcher()
    key = ''
    matched_id = None
    try:
        matched_id, _unused_sref, _unused_source = matcher.find_match(
            clean_name, country_code=country_code, channel_id=channel_id,
            epg_guide_id=epg_id or None)
    except Exception as e:
        debug("EPG match failed for {}: {}".format(clean_name, e))
    if matched_id:
        key = guide.channel_for(matched_id) or ''
    if not key:
        feed_id = None
        try:
            cleaned = matcher._clean_name_for_similarity(clean_name)
            # The feed's own name for it, letter for letter ...
            exact = guide.name_index.get(cleaned)
            if exact:
                feed_id = exact[0]
            # ... or the same name but for its accents ("SIC NOTICIAS"
            # is the feed's "SIC Notícias": the similarity search
            # below refuses that pair, its two second words not being
            # the same word) ...
            if not feed_id and cleaned:
                feed_id = guide.folded_names.get(_fold_accents(cleaned))
            # ... or the closest name that is similar enough.
            if not feed_id:
                feed_id = _find_feed_id_by_name(
                    clean_name, matcher, guide.name_index)
        except Exception as e:
            feed_id = None
            debug("EPG name match failed for {}: {}".format(clean_name, e))
        if feed_id:
            key = guide.channel_for(feed_id) or ''
    guide.resolved[clean_name] = key
    return key


def lookup_now_next(channel_name, country_code, channel_id=None):
    """What is on this channel now, and what follows.

    Returns (status, current, following). current / following are
    (start, stop, title, description) tuples with Unix times, or None.
    status says why they may be missing:
      "ok"           at least one of the two was found
      "no_country"   no country code to look under
      "no_guide"     no programme guide for this country (none exists,
                     or it could not be downloaded)
      "no_match"     the guide has no channel that matches this one
      "no_programme" the channel is in the guide, with nothing listed
                     for now or later

    Can block on a download (see load_epg_guide()) and on the EPG
    matcher: background threads only. peek_now_next() is the variant
    for the GUI thread.
    """
    if not country_code:
        return "no_country", None, None
    guide = load_epg_guide(country_code)
    if guide is None:
        return "no_guide", None, None
    key = _resolve_guide_channel(
        guide, _guide_channel_name(channel_name), country_code, channel_id)
    if not key:
        return "no_match", None, None
    current, following = guide.now_next(key)
    if current is None and following is None:
        return "no_programme", None, None
    return "ok", current, following


def peek_now_next(channel_name, country_code):
    """lookup_now_next() answered from memory alone: the same
    (status, current, following), or None when answering would need a
    download or the matcher. Never blocks - safe on the GUI thread."""
    if not country_code:
        return "no_country", None, None
    guide = peek_epg_guide(country_code)
    if guide is None:
        return None
    key = guide.resolved.get(_guide_channel_name(channel_name))
    if key is None:
        return None
    if not key:
        return "no_match", None, None
    current, following = guide.now_next(key)
    if current is None and following is None:
        return "no_programme", None, None
    return "ok", current, following


def lookup_schedule(channel_name, country_code, channel_id=None, count=4):
    """(status, programmes): the programme on now and the next ones,
    up to `count` - the player's mini guide. Same matching and the same
    status words as lookup_now_next(); can block the same way:
    background threads only (peek_schedule() on the GUI thread)."""
    if not country_code:
        return "no_country", []
    guide = load_epg_guide(country_code)
    if guide is None:
        return "no_guide", []
    key = _resolve_guide_channel(
        guide, _guide_channel_name(channel_name), country_code, channel_id)
    if not key:
        return "no_match", []
    programmes = guide.schedule(key, count)
    return ("ok" if programmes else "no_programme"), programmes


def peek_schedule(channel_name, country_code, count=4):
    """lookup_schedule() from memory alone, or None when it would need
    a download or the matcher. Never blocks."""
    if not country_code:
        return "no_country", []
    guide = peek_epg_guide(country_code)
    if guide is None:
        return None
    key = guide.resolved.get(_guide_channel_name(channel_name))
    if key is None:
        return None
    if not key:
        return "no_match", []
    programmes = guide.schedule(key, count)
    return ("ok" if programmes else "no_programme"), programmes


def lookup_programmes(channel_name, country_code, start, stop,
                      channel_id=None, epg_id=None):
    """(status, programmes): what is on this channel between `start`
    and `stop` - the guide grid. Same matching and status words as
    lookup_schedule(); can block the same way: background threads only
    (peek_programmes() on the GUI thread)."""
    if not country_code:
        return "no_country", []
    guide = load_epg_guide(country_code)
    if guide is None:
        return "no_guide", []
    key = _resolve_guide_channel(
        guide, _guide_channel_name(channel_name), country_code, channel_id,
        epg_id)
    if not key:
        return "no_match", []
    programmes = guide.between(key, start, stop)
    return ("ok" if programmes else "no_programme"), programmes


def peek_programmes(channel_name, country_code, start, stop):
    """lookup_programmes() from memory alone, or None when it would
    need a download or the matcher. Never blocks."""
    if not country_code:
        return "no_country", []
    guide = peek_epg_guide(country_code)
    if guide is None:
        return None
    key = guide.resolved.get(_guide_channel_name(channel_name))
    if key is None:
        return None
    if not key:
        return "no_match", []
    programmes = guide.between(key, start, stop)
    return ("ok" if programmes else "no_programme"), programmes


def _build_epg_channels_xml(unique):
    """The channels.xml text for write_epg_mapping_file() - `unique`
    maps each full service reference to its (epg_id, channel_name).

    Everything is XML-escaped: EPGImport reads this file with a strict
    XML parser and skips the whole file (every channel of the country)
    on the first malformed line. Ids taken from an EPG feed arrive here
    already un-escaped (so one containing "&" would have been written
    raw into the attribute), and a channel name containing "--" is not
    allowed inside an XML comment at all. Ids from older caches or the
    alias table can still be in their escaped form - un-escaping first
    makes the result the same either way instead of escaping them
    twice."""
    xml_lines = ['<?xml version="1.0" encoding="utf-8"?>', '<channels>']
    for dvb_ref, (epg_id, ch_name) in unique.items():
        comment = ensure_str(ch_name, errors='ignore')
        while '--' in comment:
            comment = comment.replace('--', '- -')
        xml_lines.append(
            '  <channel id="{}">{}</channel><!-- {} -->'.format(
                html_escape(html_unescape(epg_id)),
                html_escape(dvb_ref),
                comment))
    xml_lines.append('</channels>')
    return '\n'.join(xml_lines)


def write_epg_mapping_file(epg_entries, country_code):
    """
    Write the EPG mapping file for a specific country.
    epg_entries: list of tuples (epg_id, full_service_ref, channel_name),
    where full_service_ref is the DVB-style tuple *with the stream URL
    appended* (e.g. "4097:0:1:...:0:0:0:http%3a//host/stream") - not the
    bare tuple. EPGImport's own channelFilter() only fast-accepts a
    channel ref if it contains an embedded URL; a bare tuple falls
    through to a fake-recording probe that fails silently for it, so
    passing the bare tuple here means the channel gets dropped entirely
    during EPGImport's own channels.xml parse pass.
    """
    epg_dir = "/etc/epgimport"
    if not exists(epg_dir):
        makedirs(epg_dir)

    if country_code:
        filename = "vavoo_{}.channels.xml".format(country_code.lower())
    else:
        filename = "vavoo.channels.xml"
    channels_file = join(epg_dir, filename)

    # An id may still not be one this country's feed uses for
    # <channel id> (a curated entry for another feed, or an old one) -
    # epgimport can't find programme data filed under an id the feed
    # never defines. Fall back to the feed's own id, found by
    # display-name match, but only when the id genuinely isn't one
    # the feed already has - this never touches a channel that's
    # already matching correctly.
    #
    # Deliberately outside _epg_lock below: this can fetch and parse a
    # whole country's multi-MB XMLTV feed (up to ~60s across getUrl()'s
    # own retries), only refreshed every 300s per _get_epg_feed_index()'s
    # own cache. Holding a single global lock across that would make
    # every other country's (unrelated) channels.xml write queue up
    # behind whichever one's feed happens to be slow/uncached - the lock
    # only needs to protect the actual file write below.
    feed_ids, feed_name_index = _get_epg_feed_index(country_code)
    matcher = get_epg_matcher() if feed_ids else None

    # Use the full ref as key to avoid duplicates, but also store the
    # channel name. Unlike a bare dvb_ref, a full_service_ref
    # (tuple + URL) never needs a trailing-colon fixup - it already
    # ends with the stream URL, and blindly appending ':' here would
    # corrupt that URL instead of "completing" a bare tuple.
    unique = {}
    for epg_id, dvb_ref, ch_name in epg_entries:
        # isinstance(dvb_ref, (str, text_type)): plain `str` alone
        # would drop every `unicode` dvb_ref on Python 2, silently
        # writing an empty/near-empty EPG mapping file.
        if dvb_ref and isinstance(
                dvb_ref, (str, text_type)) and dvb_ref.strip():
            if feed_ids and epg_id not in feed_ids:
                fallback_id = _find_feed_id_by_name(
                    ch_name, matcher, feed_name_index)
                if fallback_id:
                    debug(
                        "EPG mapping fallback: '{}' id '{}' not "
                        "in feed, using '{}' instead".format(
                            ch_name, epg_id, fallback_id))
                    epg_id = fallback_id
            unique[dvb_ref] = (epg_id, ch_name)

    if not unique:
        print("[EPG] No entries to write, skipping.")
        return None

    channels_xml = _build_epg_channels_xml(unique)

    with _epg_lock:
        try:
            temp_path = channels_file + ".tmp"
            with open(temp_path, 'w') as f:  # 'encoding' arg removed for Py2 compatibility
                f.write(channels_xml)
            rename(temp_path, channels_file)
            print(
                "[EPG] Written {} entries to {}".format(
                    len(unique), filename))
            return filename
        except Exception as e:
            print("[EPG] Error writing {}: {}".format(filename, e))
            return None


def update_epg_sources():
    """
    Scan /etc/epgimport for vavoo_*.channels.xml files and generate
    a master vavoo.sources.xml containing a source for each.
    """
    epg_dir = "/etc/epgimport"
    sources_file = join(epg_dir, "vavoo.sources.xml")
    pattern = join(epg_dir, "vavoo_*.channels.xml")
    files = glob.glob(pattern)

    if not files:
        with _epg_lock:
            if exists(sources_file):
                remove(sources_file)
                print("[EPG] Removed sources file (no channels).")
        return

    sources_list = []

    for f in sorted(files):
        basename_file = basename(f)

        # Extract country code from filename (example: vavoo_it.channels.xml ->
        # it)
        parts = basename_file.replace(".channels.xml", "").split("_")
        if len(parts) > 1:
            country_code = parts[1].lower()
        else:
            country_code = "unknown"

        # Build the source entry WITHOUT XML header
        source_entry = '''    <source type="gen_xmltv" channels="{}">
      <description>Vavoo {}</description>
      <url>http://{}:{}/epg/{}.xml</url>
    </source>'''.format(
            basename_file,
            country_code.upper(),
            PROXY_HOST,
            PORT,
            country_code
        )

        sources_list.append(source_entry)

    # Build the complete XML with a SINGLE header
    sources_xml = '''<?xml version="1.0" encoding="utf-8"?>
<sources>
  <sourcecat sourcecatname="Vavoo">
{}
  </sourcecat>
</sources>'''.format("\n".join(sources_list))

    try:
        with _epg_lock:
            temp_path = sources_file + ".tmp"
            with open(temp_path, "w") as f:
                f.write(sources_xml)
            rename(temp_path, sources_file)

        print(
            "[EPG] Sources file updated with %d entries." %
            len(sources_list))

    except Exception as e:
        print("[EPG] Error writing sources file: %s" % e)

    ensure_vavoo_epg_sources_enabled()


def ensure_vavoo_epg_sources_enabled():
    """Auto-enable every currently-exported Vavoo EPG source ("Vavoo
    <COUNTRY>", one per exported country - see the <description> built
    above) in EPGImport's own settings, using its proper save API
    (EPGConfig.storeUserSettings()) instead of hand-editing
    epgimport.conf - that file is a pickle blob, not plain text, and an
    earlier attempt at this by appending a raw line to it corrupted
    EPGImport's own config. Merges into whatever the user already has
    enabled there; never removes anything.

    Only runs with "Enable Vavoo EPG" on - without it EPGImport's own
    source list is left exactly as the user configured it. (This used
    to need a second toggle as well, "Auto-update EPG"; it is simply
    part of enabling the EPG now.) Never raises - this is a
    best-effort convenience a failure here shouldn't be allowed to
    break bouquet export over.
    """
    try:
        if not config.plugins.vavoo.epg_enabled.value:
            return

        epg_dir = "/etc/epgimport"
        pattern = join(epg_dir, "vavoo_*.channels.xml")
        files = glob.glob(pattern)
        if not files:
            return

        wanted = set()
        for f in files:
            basename_file = basename(f)
            parts = basename_file.replace(".channels.xml", "").split("_")
            country_code = parts[1].upper() if len(parts) > 1 else "UNKNOWN"
            wanted.add("Vavoo {}".format(country_code))

        from Plugins.Extensions.EPGImport import EPGConfig
        settings = EPGConfig.loadUserSettings()
        current = list(settings.get("sources") or [])
        missing = sorted(wanted - set(current))
        if not missing:
            return
        EPGConfig.storeUserSettings(sources=current + missing)
        print(
            "[EPG] Auto-enabled EPGImport source(s): %s" %
            ", ".join(missing))
    except ImportError:
        # EPGImport not installed - nothing to enable.
        pass
    except Exception as e:
        print("[EPG] Error auto-enabling EPGImport sources: %s" % e)


def fix_cache_format(
        remove_duplicates=True,
        remove_unmatched=False,
        remove_invalid=False):
    """_fix_cache_format_unlocked() under CACHE_FILE's own lock
    (_cache_file_lock)."""
    with _cache_file_lock:
        return _fix_cache_format_unlocked(
            remove_duplicates, remove_unmatched, remove_invalid)


def _fix_cache_format_unlocked(
        remove_duplicates=True,
        remove_unmatched=False,
        remove_invalid=False):
    """
    Fix cache file.
    - Lowercase keys only (not name or id)
    - Remove extra fields
    - Mark duplicates as matched=False (case-insensitive comparison for names)
    - Remove entries based on flags
    Returns (fixed_count, removed_count)
    """
    try:
        if not exists(CACHE_FILE):
            print("[Cache] No cache file found")
            return 0, 0

        with open(CACHE_FILE, 'r') as f:
            cache = load(f)

        required = {'id', 'name', 'country', 'sref', 'timestamp', 'matched'}
        # 'source' (alias/curated/live - see update_complete_cache())
        # is optional but meaningful: dropping it as an "extra" field
        # made every entry look non-curated again after a cache fix.
        allowed = required | {'source'}
        new_cache = {}
        modified = 0
        duplicates = 0
        keys_changed = False

        # Lista degli sref di fallback da considerare invalidi
        fallback_srefs = [
            "4097:0:0:0:0:0:0:0:0:0:",
            "4097:0:1:1:1:40:0:0:0:0"
        ]

        for key, value in cache.items():
            new_key = key.lower().strip()
            if new_key != key:
                keys_changed = True
            changed = False

            # Remove extra fields
            extra = set(value.keys()) - allowed
            if extra:
                for k in extra:
                    del value[k]
                changed = True

            # Name: keep original case
            if 'name' not in value:
                value['name'] = key
                changed = True

            # Country: lowercase
            if 'country' not in value or not value['country']:
                parts = new_key.rsplit('_', 1)
                value['country'] = parts[-1] if len(parts) > 1 else ''
                changed = True
            else:
                new_country = str(value['country']).lower().strip()
                if new_country != value['country']:
                    value['country'] = new_country
                    changed = True

            # ID: keep original case
            if 'id' not in value or not value['id']:
                value['id'] = key
                changed = True

            # sref: se è vuoto o mancante, assegna il primo fallback (ma poi
            # verrà eventualmente rimosso)
            if 'sref' not in value or not value['sref']:
                value['sref'] = fallback_srefs[0]
                changed = True

            # timestamp
            if 'timestamp' not in value:
                value['timestamp'] = strftime('%Y-%m-%d %H:%M:%S', localtime())
                changed = True

            # matched
            if 'matched' not in value:
                value['matched'] = False
                changed = True

            if changed:
                modified += 1

            new_cache[new_key] = value

        # Mark duplicates (case-insensitive comparison on name)
        if remove_duplicates:
            groups = {}
            for k, v in new_cache.items():
                name_key = v['name'].lower().strip() if v['name'] else ''
                country_key = v['country']
                group = (name_key, country_key)
                groups.setdefault(group, []).append(k)

            for group, keys in groups.items():
                if len(keys) > 1:
                    for dup in keys[1:]:
                        if new_cache[dup].get('matched', False):
                            new_cache[dup]['matched'] = False
                            duplicates += 1
                            modified += 1

        # Remove entries based on flags
        removed = 0
        to_delete = []
        for k, v in new_cache.items():
            if remove_unmatched and v.get('matched') is False:
                to_delete.append(k)
            elif remove_invalid and v.get('sref') in fallback_srefs:
                to_delete.append(k)

        to_delete = list(set(to_delete))
        for k in to_delete:
            del new_cache[k]
            removed += 1

        if removed:
            print(
                "[Cache] Removed %d entries (unmatched=%s, invalid=%s)" %
                (removed, remove_unmatched, remove_invalid))

        # Save if any changes
        if modified > 0 or duplicates > 0 or keys_changed or removed > 0:
            temp_file = CACHE_FILE + ".tmp"
            with open(temp_file, 'w') as f:
                dump(
                    new_cache,
                    f,
                    indent=4,
                    sort_keys=True,
                    ensure_ascii=False)
            rename(temp_file, CACHE_FILE)
            print(
                "[Cache] Fixed %d entries, marked %d duplicates, removed %d entries, keys lowercased" %
                (modified, duplicates, removed))
            return modified, removed
        else:
            print("[Cache] No changes needed")
            return 0, 0

    except Exception as e:
        print("[Cache] Error: %s" % e)
        trace_error()
        return 0, 0


def returnIMDB(text_clear, session):
    from Tools.Directories import SCOPE_PLUGINS, resolveFilename
    TMDB = resolveFilename(SCOPE_PLUGINS, "Extensions/{}".format('TMDB'))
    tmdbx = resolveFilename(SCOPE_PLUGINS, "Extensions/{}".format('tmdb'))
    IMDb = resolveFilename(SCOPE_PLUGINS, "Extensions/{}".format('IMDb'))
    text = html_unescape(text_clear)

    if exists(TMDB):
        try:
            # from Plugins.Extensions.TMBD.plugin import TMBD
            # print("[XCF] Opening TMDB for: %s" % text)
            # session.open(TMBD.tmdbScreen, text, 0)
            from Plugins.Extensions.TMBD.plugin import tmdbScreen
            print("[XCF] Opening TMDB for: %s" % text)
            session.open(tmdbScreen, text, 2)
            return True
        except Exception as e:
            print("[XCF] TMDB error: ", str(e))

    if exists(tmdbx):
        try:
            # from Plugins.Extensions.tmdb.plugin import tmdb
            # print("[XCF] Opening tmdb for: %s" % text)
            # session.open(tmdbScreen, text, 0)
            from Plugins.Extensions.tmdb.tmdb import tmdbScreen
            session.open(tmdbScreen, text, 2)
            return True
        except Exception as e:
            print("[XCF] tmdb error: ", str(e))

    if exists(IMDb):
        try:
            from Plugins.Extensions.IMDb.plugin import IMDB  # main as imdb
            print("[XCF] Opening IMDb for: %s" % text)
            session.open(IMDB, text, False)
            # imdb(session, text)
            return True
        except Exception as e:
            print("[XCF] IMDb error: ", str(e))

    return False
