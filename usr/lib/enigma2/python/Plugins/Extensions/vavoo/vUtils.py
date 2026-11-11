#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import base64
import glob
import hashlib
import io
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
import zlib
from datetime import datetime as _datetime
from collections import OrderedDict
from difflib import SequenceMatcher
from json import dump, load, loads
from Components.config import config
from Components.NimManager import nimmanager
from os import listdir, makedirs, remove, unlink, rename
from os.path import basename, exists, getmtime, getsize, isfile, join, splitext
from enigma import eTimer
from random import choice
from re import DOTALL, IGNORECASE, compile, findall, search, sub
from shutil import copy2
from sys import maxsize
from six import iteritems, unichr
from six.moves import html_entities, html_parser
from time import time, strftime, localtime
from unicodedata import normalize

from . import (
    __version__,
    country_codes,
    PY2,
    PY3,
    PORT,
    PLUGIN_ROOT,
    PROXY_HOST,
    PROXY_BASE_URL,
    PROXY_STATUS_URL,
    FLAG_CACHE_DIR,
    PICON_CACHE_DIR,
    GROUP_NAME_SEPARATORS,
    LOG_FILE,
    CACHE_FILE,
    UNMATCHED_FILE,
    HOST_MAIN,
    ALIAS_FILE,
    INSTALLER_URL,
    export_lock,
)
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
        with open(LOG_FILE, "a") as log_file:
            log_file.write(line + "\n")
    except Exception:
        pass


def log(msg, level="INFO", area="VUTILS"):
    try:
        msg = ensure_str(msg, errors='ignore')
    except Exception:
        try:
            msg = str(msg)
        except Exception:
            msg = '<unprintable message>'
    line = "[{0}] [{1}] [{2}] {3}".format(
        _datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        level,
        area,
        msg
    )
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

# Plugin-local bookkeeping, same category/directory as Favorite.txt
# (bouquet_manager.py) - not receiver-wide EPG state, so it follows the
# PLUGIN_PATH convention rather than ENIGMA_PATH's.
FAVOURITES_FILE = join(PLUGIN_PATH, 'vavoo_favourites.json')


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


def b64decoder(data):
    """Robust base64 decoding with padding correction"""
    if not data:
        return ""

    try:
        data = ensure_str(data, errors='ignore').strip()
        pad = len(data) % 4
        if pad == 1:
            return ""
        if pad:
            data += "=" * (4 - pad)

        decoded = base64.b64decode(data.encode('ascii'))
        try:
            return decoded.decode('utf-8')
        except UnicodeDecodeError:
            return decoded

    except Exception as e:
        print("Base64 decoding error: %s" % e)
        return ""


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

            if PY3:
                import ssl
                unverified_context = ssl.create_default_context()
                unverified_context.check_hostname = False
                unverified_context.verify_mode = ssl.CERT_NONE
                response = urlopen(
                    request,
                    timeout=timeout,
                    context=unverified_context)
            else:
                # Python 2: prova a usare ssl se disponibile, altrimenti
                # fallback
                try:
                    import ssl
                    # Python 2.7.9+ supporta ssl._create_unverified_context
                    unverified_context = ssl._create_unverified_context() if hasattr(
                        ssl, '_create_unverified_context') else None
                    if unverified_context:
                        response = urlopen(
                            request, timeout=timeout, context=unverified_context)
                    else:
                        response = urlopen(request, timeout=timeout)
                except ImportError:
                    response = urlopen(request, timeout=timeout)

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


def set_cache(key, data, timeout):
    file_path = join(PLUGIN_PATH, key + '.json')
    try:
        if not isinstance(data, dict):
            data = {"value": data}
        # _is_cache_valid() requires both of these to consider a cache
        # entry valid - previously never written here, so timeout had no
        # effect and get_cache() would always treat this entry as expired.
        data['sigValidUntil'] = int(time()) + timeout
        data['ip'] = get_external_ip()
        temp_path = file_path + ".tmp"
        if PY2:
            converted_data = convert_to_unicode(data)
            with io.open(temp_path, 'w', encoding='utf-8') as cache_file:
                dump(
                    converted_data,
                    cache_file,
                    indent=4,
                    ensure_ascii=False)
        else:
            with io.open(temp_path, 'w', encoding='utf-8') as cache_file:
                dump(data, cache_file, indent=4, ensure_ascii=False)
        rename(temp_path, file_path)
    except Exception as e:
        print("Error saving cache:", e)
        trace_error()


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

def get_proxy_catalog_url():
    """
    Get the proxy catalog URL
    """
    return PROXY_BASE_URL + "/catalog"


def get_proxy_playlist_url():
    """
    Get the proxy playlist URL
    """
    return PROXY_BASE_URL + "/playlist.m3u"


def get_proxy_status():
    """Get detailed proxy status"""
    try:
        if requests is not None:
            response = requests.get(PROXY_STATUS_URL, timeout=3)
            if response.status_code == 200:
                return response.json()
        else:
            req = Request(PROXY_STATUS_URL)
            response = urlopen(req, timeout=3)
            if response.getcode() == 200:
                return loads(response.read().decode('utf-8', 'ignore'))
    except BaseException:
        return None
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
    """Check if the proxy is ready to receive requests.

    The proxy's HTTP server only binds its port after the full channel
    catalog has loaded, so while that is in progress every connection is
    refused. getUrl() retries refused connections with exponential
    backoff (seconds of blocking per call) which is fine for a one-off
    fetch but far too slow for a readiness poll called every few hundred
    ms from the UI/reactor thread. Check the port cheaply first (a plain
    connect_ex, effectively instant) and only pay for the HTTP round trip
    - with a single attempt, since we already know the port is open -
    once it is actually listening.
    """
    try:
        if not is_proxy_running():
            return False
        response = getUrl(PROXY_STATUS_URL, timeout=timeout, retries=1)
        if response:
            data = loads(response)
            return data.get("initialized", False)
        return False
    except BaseException:
        return False


# ===================================

def fetch_vec_list():
    """Fetch vector list from GitHub"""
    try:
        url = "{}/data.json".format(HOST_MAIN)

        if requests is not None:
            # Use requests if available
            response = requests.get(url, timeout=10)
            vec_list = response.json()
        else:
            # Fallback to urllib
            req = Request(url)
            response = urlopen(req, timeout=10)
            data = response.read()
            if isinstance(data, bytes):
                data = data.decode('utf-8', 'ignore')
            vec_list = loads(data)

        set_cache("vec_list", vec_list, 3600)
        print(
            "[Fetch] Vector list loaded: {} entries".format(
                len(vec_list) if vec_list else 0))
        return vec_list

    except Exception as e:
        print("[Fetch] Vector list error: {}".format(str(e)))
        return None


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


def purge(directory, pattern):
    """Delete files matching pattern in directory"""
    for f in listdir(directory):
        file_path = join(directory, f)
        if isfile(file_path) and search(pattern, f):
            remove(file_path)


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
    """Build a fallback (no Rytec/EPG match) service reference whose
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

    onid/namespace are deliberately left at 0: every real Rytec-sourced
    sref uses a non-zero namespace (the known satellite/terrestrial/
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

    replacements = {
        '&amp;': '&', '&apos;': "'", '&lt;': '<', '&gt;': '>', '&ndash;': '-',
        '&quot;': '"', '&ntilde;': 'ñ', '&rsquo;': "'", '&nbsp;': ' ',
        '&equals;': '=', '&quest;': '?', '&comma;': ',', '&period;': '.',
        '&colon;': ':', '&lpar;': '(', '&rpar;': ')', '&excl;': '!',
        '&dollar;': '$', '&num;': '#', '&ast;': '*', '&lowbar;': '_',
        '&lsqb;': '[', '&rsqb;': ']', '&half;': '1/2', '&DiacriticalTilde;': '~',
        '&OpenCurlyDoubleQuote;': '"', '&CloseCurlyDoubleQuote;': '"'
    }
    for entity, char in replacements.items():
        text = text.replace(entity, char)

    return text.strip()


def remove_line(filename, pattern):
    """Remove lines containing pattern from file"""
    if not isfile(filename):
        return
    with open(filename, 'r') as f:
        lines = [line for line in f if pattern not in line]
    with open(filename, 'w') as f:
        f.writelines(lines)


def getserviceinfo(service_ref):
    """Get service name and URL from service reference"""
    try:
        from ServiceReference import ServiceReference
        ref = ServiceReference(service_ref)
        return ref.getServiceName(), ref.getPath()
    except Exception:
        return None, None


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


def get_picon_cache_path(logo_url, cache_dir=PICON_CACHE_DIR):
    """Local path a picon for this logo URL would be cached at,
    whether or not it has actually been downloaded yet - the one
    place this filename is computed, shared by download_picon_online()
    (which writes it) and show_list() (which only ever reads it, never
    downloading synchronously itself), so the two can't drift apart.
    """
    if not logo_url:
        return None
    return join(cache_dir, _picon_cache_filename(logo_url))


def download_picon_online(logo_url, cache_dir=PICON_CACHE_DIR):
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
    for sep in GROUP_NAME_SEPARATORS:
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

    for sep in GROUP_NAME_SEPARATORS:
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


def cleanup_flag_cache(max_age_days=7):
    """
    Remove old cached flag files from cache directory.
    Only files older than max_age_days are deleted.
    """
    cache_dir = FLAG_CACHE_DIR

    if not exists(cache_dir):
        return

    now = time()
    max_age = max_age_days * 86400

    try:
        for filename in listdir(cache_dir):
            filepath = join(cache_dir, filename)
            if isfile(filepath):
                try:
                    file_age = now - getmtime(filepath)
                    if file_age > max_age:
                        unlink(filepath)
                        print("Removed old flag: %s" % filename)
                except Exception as e:
                    print(
                        "Error removing %s: %s" %
                        (filename, str(e)))
    except Exception as e:
        print("Error cleaning flag cache: %s" % str(e))


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


def preload_country_flags(country_list, cache_dir=FLAG_CACHE_DIR):
    """
    Preload flags for a list of countries.
    Each chunk of countries is downloaded in a separate daemon thread.
    Compatible with Python 2 and 3.
    """

    def download_flags_worker(countries):
        for country in countries:
            try:
                success, _ = download_flag_online(country, cache_dir)
                if success:
                    print("Preloaded flag for: %s" % country)
            except Exception as e:
                print(
                    "Error preloading flag for %s: %s" %
                    (country, str(e)))

    # Split list into chunks to avoid overloading
    chunk_size = 10
    threads = []

    if not country_list:
        return threads

    total = len(country_list)

    for i in range(0, total, chunk_size):
        chunk = country_list[i:i + chunk_size]
        t = threading.Thread(
            target=download_flags_worker,
            args=(chunk,)
        )
        t.setDaemon(True)
        t.start()
        threads.append(t)

    return threads


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


def calculate_similarity(a, b):
    """
    Calculate similarity ratio between two strings using SequenceMatcher.
    Returns a float between 0.0 and 1.0.
    """
    return SequenceMatcher(None, a, b).ratio()


def get_orbital_position(service_ref):
    """
    Extract orbital position from service reference namespace.
    Returns orbital position in tenths of a degree (e.g., 130 = 13.0°E, -50 = 5.0°W)
    """
    # sref format: type:flags:servicetype:sid:tsid:onid:namespace:... -
    # namespace (what actually encodes orbital position) is field 6,
    # not field 3 (that's the sid) - see _get_signal_priority()'s own
    # identical parsing a bit further down this file, which already
    # gets this right and warns about this exact mix-up in its own
    # comment. Getting this wrong here meant namespace was actually
    # the sid, which is always < 0x10000 - so "is it an exact multiple
    # of 0x10000" was false for every nonzero sid, and the masked
    # fallback (parts[3]'s value & 0xFFFF0000) was always 0, so this
    # function always returned 0 regardless of the real satellite.
    # Downstream in _find_match_internal(), orbpos being always 0
    # silently disabled the user-configured-satellite (1.5x) and
    # Italy-specific 13°E/5°W (1.3x) EPG-match boosts documented in
    # CLAUDE.md as this feature's whole point - every satellite match
    # fell through to the generic "other satellite" 1.2x boost
    # instead, with ties broken arbitrarily by score banding.
    parts = service_ref.split(':')
    if len(parts) < 7:
        return 0

    try:
        namespace_str = parts[6] if parts[6] else '0'
        namespace = int(namespace_str, 16)

        # Case 1: Default - Position * 65536
        # The namespace is a multiple of 65536 (0x10000)
        if namespace % 0x10000 == 0:
            pos = namespace // 0x10000
            # Determine East/West from sign (Enigma convention)
            if pos < 1800:  # East
                return pos
            else:  # West (pos > 1800, e.g., 3600-50=3550 for 5°W)
                return -(3600 - pos)

        # Case 2: Exception - also contains frequency and polarization
        # Extract the base part (Position * 65536)
        base = namespace & 0xFFFF0000
        pos = base // 0x10000

        if pos < 1800:
            return pos
        else:
            return -(3600 - pos)

    except (ValueError, TypeError):
        return 0


def _signed_orbital_position(orbpos):
    """Enigma2's own form of an orbital position (tenths of a degree,
    west stored as 3600 - position: 5.0W = 3550) converted to the
    signed form get_orbital_position() returns (5.0W = -50)."""
    try:
        orbpos = int(orbpos)
    except (TypeError, ValueError):
        return orbpos
    return orbpos - 3600 if orbpos >= 1800 else orbpos


def get_configured_satellites():
    """
    Get list of satellites configured by user in Enigma2.
    Returns orbital positions in tenths of a degree, west negative -
    the same form get_orbital_position() returns (e.g. [130, 192, -50]),
    since _find_match_internal() compares the two directly. They used
    to be returned in Enigma2's own 0-3600 form, so a western satellite
    (5.0W = 3550 there, -50 from get_orbital_position()) never compared
    equal and never got the configured-satellite boost.
    """
    try:
        configured_sats = []

        # Method 1: Direct from NimManager
        if hasattr(nimmanager, 'getConfiguredSats'):
            sats = nimmanager.getConfiguredSats()
            if sats:
                configured_sats = [
                    _signed_orbital_position(s) for s in sats]
                print(
                    "[SatConfig] Found {} configured satellites via NimManager".format(
                        len(configured_sats)))
                return configured_sats

        # Method 2: Parse from config
        for slot in nimmanager.nim_slots:
            if slot.isCompatible(
                    "DVB-S") and slot.config.dvbs.configMode.value != "nothing":
                # Simple mode - check diseqc settings
                if slot.config.dvbs.configMode.value == "simple":
                    for port in ['diseqcA', 'diseqcB', 'diseqcC', 'diseqcD']:
                        orbpos = getattr(slot.config.dvbs, port).value
                        if orbpos and orbpos not in configured_sats and orbpos < 3600:
                            configured_sats.append(orbpos)
                            print(
                                "[SatConfig] Found configured sat: {} (port {})".format(
                                    orbpos, port))

                # Advanced mode - check each configured satellite
                elif hasattr(slot.config.dvbs, 'advanced') and slot.config.dvbs.advanced:
                    for sat_config in slot.config.dvbs.advanced.sat.values():
                        if sat_config.enabled.value:
                            orbpos = sat_config.sat.value.orbital_position
                            if orbpos and orbpos not in configured_sats:
                                configured_sats.append(orbpos)
                                print(
                                    "[SatConfig] Found configured sat: {}".format(orbpos))

        configured_sats = [
            _signed_orbital_position(s) for s in configured_sats]
        print("[SatConfig] Total configured satellites: {}".format(configured_sats))
        return configured_sats

    except Exception as e:
        print("[SatConfig] Error getting configured satellites: {}".format(e))
        return []


def get_satellite_priority(orbpos, configured_sats):
    """
    Returns priority boost for a satellite based on user configuration.
    1.0 = same as configured
    0.5 = other satellite
    """
    if orbpos in configured_sats:
        return 1.0
    return 0.5


# Known satellite namespaces, masked to their top 16 bits (see
# _get_signal_priority()'s own comment on the 0xFFFF0000 mask/encoding
# convention) - a frozenset, not a list rebuilt on every call: this is
# checked once per candidate inside _find_match_internal()'s hot loop
# (run once per channel against what can be thousands of Rytec
# entries), and a set membership test is also O(1) instead of this
# list's O(19) linear scan.
_SATELLITE_NAMESPACES = frozenset((
    0x820000,   # 13.0°E HotBird (Italy)
    0xC00000,   # 19.2°E Astra
    0xEB0000,   # 23.5°E Astra 3
    0x11A0000,  # 28.2°E Astra 2
    0xA00000,   # 16.0°E Eutelsat 16A
    0x5A0000,   # 9.0°E Eutelsat 9B
    0x460000,   # 7.0°E Eutelsat 7E
    0xDDE0000,  # 5.0°W Eutelsat 5WA (Italy)
    0xCE40000,  # 30.0°W Hispasat
    0x1A40000,  # 42.0°E Türksat
    0x300000,   # 4.8°E Astra 4A / Sirius
    0x13B0000,  # 31.5°E Astra 5B
    0x14A0000,  # 33.0°E Eutelsat 33E
    0xFF0000,   # 25.5°E Es'hail / Arabsat
    0x1C20000,  # 45.0°E AzerSpace
    0x1860000,  # 39.0°E Hellas Sat
    0x1680000,  # 36.0°E Eutelsat 36B
    0x1040000,  # 26.0°E Badr
    0x130000,   # 1.9°E BulgariaSat
))


# get_country_code() returns real ISO 3166-1 codes (needed for flag
# downloads, e.g. "gb" for United Kingdom), but the Rytec database groups
# channels by its own historical suffix convention, which doesn't always
# match ISO - e.g. UK channels are "BBCOne.uk", not "BBCOne.gb". Without
# this translation, every channel from a mismatched country would find
# zero candidates in rytec_by_country and always report "ID not found".
RYTEC_COUNTRY_CODE_OVERRIDES = {
    'gb': 'uk',
}

# channel_alias.ALIAS_MAP is curated for Italian channels specifically
# (see its own module docstring) - used by find_match()'s country-gate
# below to always trust an alias hit when matching for Italy itself,
# even for the handful of entries pinned to a non-".it" Rytec id.
_ALIAS_MAP_HOME_COUNTRY = "it"


class VavooEPGMatcher(object):
    def __init__(self, similarity_threshold=0.70):
        self.similarity_threshold = similarity_threshold
        # Guards the lazy-init block below (_configured_sats) against a
        # TOCTOU race if find_match() is ever called concurrently on
        # this same matcher instance from two threads.
        self._lazy_init_lock = threading.Lock()
        # Guards self.cache/self.normalized_index/self.new_matches -
        # see find_match()'s docstring. RLock: _find_match_internal()
        # (called from inside find_match()'s locked section) does its
        # own lazy-init re-entrancy on this same thread.
        self._cache_lock = threading.RLock()
        # (clean_name, original_name, service_ref)
        self.rytec_entries = []
        # Same entries grouped by country code (from the id's suffix, e.g.
        # "Rai1.it" -> "it"), so matching against a specific country
        # doesn't have to linearly scan every other country's entries too.
        self.rytec_by_country = {}
        self.rytec_by_id = {}           # (original_id, service_ref)
        self.rytec_names = {}
        self.cache = load_cache()       # persistent cache
        self.new_matches = {}           # matches found in this session
        self.normalized_index = {}      # map normalized_key -> original_key
        self._build_normalized_index()  # build index at startup
        self.alias_map = {}
        self._load_alias_map()
        if not self.rytec_entries:
            self._load_rytec_database()

    @staticmethod
    def is_valid_rytec_id(id_val):
        """Returns True if id_val appears to be a valid Rytec ID (e.g. 'Rai1.it')."""
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

    @staticmethod
    def _normalize_rytec_sref(raw_sref):
        """Apply the same "1:" -> "4097:" type conversion
        _find_match_internal() applies to a freshly-matched Rytec sref,
        plus trailing-colon normalization, so a raw self.rytec_by_id[...]
        value can be compared against a cached sref on equal terms."""
        if not raw_sref:
            return None
        parts = raw_sref.split(':')
        if parts and parts[0] == '1':
            parts[0] = '4097'
        return ensure_sref_trailing_colon(':'.join(parts))

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

    def _load_rytec_database(self):
        rytec_paths = [
            "/etc/epgimport/rytec.channels.xml",
            "/usr/lib/enigma2/python/Plugins/Extensions/EPGImport/rytec.channels.xml"]
        rytec_file = None
        for path in rytec_paths:
            if exists(path):
                rytec_file = path
                break
        if not rytec_file:
            print("[VavooEPGMatcher] Rytec database not found.")
            return

        try:
            with io.open(rytec_file, 'r', encoding='utf-8') as f:
                content = f.read()

            pattern = r'<channel\s+id="([^"]+)">([^<]+)</channel>\s*(?:<!--\s*([^>]+)\s*-->)?'
            matches = findall(pattern, content, IGNORECASE)

            for match in matches:
                original_id = match[0].strip()
                service_ref = match[1].strip()
                comment = match[2].strip() if len(
                    match) > 2 and match[2] else None

                if comment:
                    # Rytec's comment text is HTML-escaped XML content
                    # (e.g. "AT&amp;T Sports") - left un-decoded, the
                    # "&" that clean_name_for_similarity() would
                    # otherwise just strip survives as the literal
                    # letters "amp" glued into the name instead,
                    # garbling every Rytec channel whose real name
                    # contains an escaped "&".
                    channel_name = decodeHtml(comment)
                else:
                    # original_id's own country suffix (e.g. ".uk",
                    # ".es") is stripped generically here - the
                    # previous version only handled .it/.de/.fr, so
                    # every OTHER country's comment-less entries (e.g.
                    # "BBCOne.uk") kept their suffix glued onto the
                    # name with no separating space, which
                    # clean_name_for_similarity() can't segment back
                    # out - producing a garbled key ("bbconeuk") that
                    # can never similarity-match a real channel name.
                    channel_name = original_id
                    if '.' in channel_name:
                        channel_name = channel_name.rsplit('.', 1)[0]
                    channel_name = channel_name.replace(
                        '-', ' ').replace('_', ' ')

                # clean_name = self._clean_name(channel_name)
                clean_name = self._clean_name_for_similarity(channel_name)
                # Precomputed once here instead of on every _find_match_internal()
                # call (which re-tokenized every candidate's clean_name on
                # every single channel match, against what can be
                # thousands of entries per country - this list never
                # changes after load).
                entry_tokens = _tokenize_for_compat(clean_name)
                entry = (
                    clean_name, channel_name, original_id, service_ref,
                    entry_tokens)
                self.rytec_entries.append(entry)
                entry_country = original_id.split(
                    '.')[-1] if '.' in original_id else ""
                self.rytec_by_country.setdefault(
                    entry_country, []).append(entry)
                self.rytec_names[original_id] = clean_name
                self.rytec_by_id[original_id] = service_ref

            print("[VavooEPGMatcher] Loaded {} Rytec channels".format(
                len(self.rytec_entries)))
        except Exception as e:
            print("[VavooEPGMatcher] Error loading database: {}".format(e))

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

    def _get_signal_priority(self, service_ref):
        """
        Determine signal priority based on service reference type.

        Priority levels:
        1 = Satellite (best) - Italian-satellite bonus is applied by the
            caller separately, via orbital position + a boost multiplier
        2 = Terrestrial DVB-T
        3 = Cable
        4 = Other / IPTV or unknown
        """
        parts = service_ref.split(':')
        if len(parts) < 7:
            return 4  # Unknown / other

        try:
            # sref format: type:flags:servicetype:sid:tsid:onid:namespace:...
            # - namespace (what encodes orbital position / terrestrial /
            # cable, checked below) is field 6, not field 3 (that's the
            # sid).
            namespace_str = parts[6] if parts[6] else '0'
            namespace = int(namespace_str, 16)

            # Known satellite namespaces (_SATELLITE_NAMESPACES, module
            # level - see its own comment). Enigma2 encodes orbital
            # position as (tenths_of_a_degree << 16) for east, or
            # ((3600 - tenths_of_a_degree) << 16) for west - verified
            # against the terrestrial/cable checks below, which use the
            # same top-16-bits convention (0xFFFF0000).
            #
            # Mask must be 0xFFFF0000 (top 16 bits, matching how those
            # values were built) - the previous 0xFFF00000 zeroed out
            # part of the orbital-position field itself, so it could
            # only ever match a namespace by coincidence, not because
            # it was actually that satellite.
            if namespace & 0xFFFF0000 in _SATELLITE_NAMESPACES:
                # Italian satellite bonus is applied by the caller via
                # priority + a boost multiplier, not by this priority
                # level - satellite is always priority 1.
                return 1

            # Terrestrial DVB-T
            if namespace & 0xFFFF0000 == 0xEEEE0000:
                return 2  # Terrestrial

            # Cable
            if namespace & 0xFFFF0000 == 0xFFFF0000:
                return 3  # Cable

            # Default fallback
            return 4  # Other / IPTV / unknown

        except (ValueError, TypeError):
            return 4

    def _find_match_internal(
            self, channel_name, country_code, channel_id=None,
            servicetype="4097", feed_index=None):
        """
        Search for a match in ALL Rytec channels, then apply boost based on user configuration.
        """
        if not channel_name:
            return None, None

        # Clean the input channel name
        clean_input = self._clean_name_for_similarity(channel_name)

        # Load user-configured satellites (e.g., [130] for 13°E)
        if not hasattr(self, '_configured_sats'):
            with self._lazy_init_lock:
                if not hasattr(self, '_configured_sats'):
                    self._configured_sats = get_configured_satellites()
                    print("[Match] User has {} configured satellites: {}".format(
                        len(self._configured_sats), self._configured_sats))

        candidates = []

        # Restrict the scan to the requested country's entries up front
        # (pre-grouped in rytec_by_country at load time) instead of
        # walking every entry for every country and discarding most of
        # them - this is the hot loop of EPG matching, run once per
        # channel against what can be thousands of Rytec entries.
        if not country_code:
            entries_to_scan = self.rytec_entries
        elif country_code == "bk":
            balkan_codes = [
                "ba", "hr", "rs", "si", "me", "mk", "al", "bg", "ro"]
            entries_to_scan = [
                entry
                for code in balkan_codes
                for entry in self.rytec_by_country.get(code, [])
            ]
        elif RYTEC_COUNTRY_CODE_OVERRIDES.get(country_code):
            entries_to_scan = self.rytec_by_country.get(
                RYTEC_COUNTRY_CODE_OVERRIDES[country_code], [])
        else:
            entries_to_scan = self.rytec_by_country.get(country_code, [])

        # Pass 1: search all matches by similarity (ignore priority for now)
        # Reuse one SequenceMatcher with seq1 fixed to clean_input instead
        # of building a new one per candidate (set_seq2() lets it skip
        # re-analyzing seq1 every time), and check the cheap upper-bound
        # estimates (real_quick_ratio(), then quick_ratio()) before paying
        # for the full ratio() computation - both are always >= the real
        # ratio, so this only skips candidates that could never reach the
        # threshold anyway, never a false negative. This loop runs against
        # every Rytec entry for the country on every uncached match, so it
        # matters most for countries with large Rytec databases (e.g. Italy).
        source_tokens = _tokenize_for_compat(clean_input)
        sm = SequenceMatcher(None, clean_input)
        for clean_entry, orig_name, rytec_id, service_ref, entry_tokens in entries_to_scan:
            # A shared textual prefix with a *different* word at a
            # position both share is a strong signal these are
            # different channels (e.g. "canal motogp" vs "canal plus
            # foot") - raw character similarity alone can clear even a
            # fairly high threshold for such pairs since most of the
            # string still overlaps. A longer entry may still add
            # trailing descriptive words - only a genuine word-for-word
            # prefix mismatch is rejected.
            if source_tokens:
                if entry_tokens and not _tokens_compatible(
                        source_tokens, entry_tokens):
                    continue
            sm.set_seq2(clean_entry)
            if sm.real_quick_ratio() < self.similarity_threshold:
                continue
            if sm.quick_ratio() < self.similarity_threshold:
                continue
            score = sm.ratio()
            if score < self.similarity_threshold:
                continue

            # Extract additional info
            signal_priority = self._get_signal_priority(service_ref)
            orbpos = 0
            if signal_priority == 1:
                orbpos = get_orbital_position(service_ref)

            # Calculate boost
            boost = 1.0

            # 1. User-configured satellite → max boost
            if orbpos and self._configured_sats and orbpos in self._configured_sats:
                boost = 1.5
                print(
                    "[Match] FOUND! Satellite {} is user-configured!".format(orbpos))

            # 2. Italian satellite (important) but not configured
            elif country_code == 'it' and orbpos in [130, -50]:  # 13°E or 5°W
                boost = 1.3

            # 3. Other satellites
            elif signal_priority == 1:
                boost = 1.2

            # 4. Terrestrial
            elif signal_priority == 2:
                boost = 1.1

            # 5. Cable/IPTV
            else:
                boost = 1.0

            adjusted_score = score * boost

            candidates.append((
                adjusted_score, score, signal_priority, orbpos,
                clean_entry, orig_name, rytec_id, service_ref
            ))

        # Sort primarily by raw textual score, using the satellite/signal
        # boost only as a tie-breaker among near-equal matches. Every
        # candidate here already cleared similarity_threshold, so using
        # `adjusted_score = score * boost` as the sort key let a marginal
        # boosted candidate (e.g. score 0.71 * 1.5 = 1.065) always beat a
        # near-perfect unboosted one (max possible 1.0 * 1.0) regardless of
        # how much better the textual match actually was. Bucketing raw
        # score into 0.05-wide bands means boost can only decide between
        # candidates that are already comparably good matches.
        _PRIORITY_TIE_BAND = 0.05
        candidates.sort(
            key=lambda x: (round(x[1] / _PRIORITY_TIE_BAND), x[0]),
            reverse=True)

        for adj_score, orig_score, priority, orbpos, clean_entry, orig_name, rytec_id, service_ref in candidates:
            # Pick the first candidate above base similarity threshold
            if orig_score >= self.similarity_threshold:
                parts = service_ref.split(':')
                if parts and parts[0] == '1':
                    # Conversion for Enigma2 service reference
                    parts[0] = '4097'
                converted = ':'.join(parts)

                sat_info = " (sat {})".format(orbpos) if orbpos else ""
                conf_info = " [CONFIGURED]" if orbpos in self._configured_sats else ""
                print("[Match] CHOSEN: '{}' -> {}{}{} (score:{}→{}, priority:{})".format(
                    channel_name, rytec_id, sat_info, conf_info,
                    orig_score, adj_score, priority
                ))

                # Many Rytec entries (pan-European channels like
                # Eurosport, Nickelodeon, Discovery, DMAX...) genuinely
                # broadcast via one shared satellite transponder
                # serving multiple countries, so Rytec correctly has
                # separate per-country ids that all point at the exact
                # same real DVB tuple. Every country whose Vavoo
                # catalog matches to one of those would otherwise
                # collide on that identical tuple in Enigma2's EPG
                # cache (which keys purely on the tuple, not the
                # embedded stream URL), showing one country's
                # programme data for all of them. Give this Vavoo
                # channel its own unique reference instead - the
                # correct id above still goes into channels.xml, and
                # EPGImport's own parser already supports one id
                # fanning out to multiple different service refs.
                if channel_id:
                    return rytec_id, unique_fallback_sref(
                        servicetype, channel_id)
                return rytec_id, converted

        # No Rytec candidate matched. Before giving up, try this
        # country's own EPG programme feed directly - some countries
        # (confirmed for es/pl/tr and others) have far richer channel
        # coverage in their own epg_<cc>.xml than Rytec does; Rytec may
        # simply never have catalogued this channel at all. Reuses the
        # same feed-index/name-matching machinery write_epg_mapping_file()
        # already uses as a same-purpose fallback for the opposite case
        # (Rytec matched, but under an id the feed itself doesn't use).
        # The feed only gives an id, not a real DVB service ref (it's
        # programme-guide metadata, not satellite broadcast data), so a
        # synthesized, collision-free sref is generated the same way an
        # otherwise-unmatched channel already gets one.
        #
        # feed_index is pre-fetched by find_match() before self._cache_lock
        # is taken (same reasoning as curated_db - _get_epg_feed_index()
        # can block on a cold, multi-MB network fetch, which must never
        # happen while holding the lock the concurrent EPG-overlay thread
        # also needs for its own find_match() calls).
        if channel_id and country_code:
            _feed_ids, name_index = feed_index if feed_index else (None, None)
            if name_index:
                feed_match_id = _find_feed_id_by_name(
                    channel_name, self, name_index)
                if feed_match_id:
                    fallback_sref = unique_fallback_sref(
                        servicetype, channel_id)
                    print(
                        "[Match] FEED-DIRECT MATCH: '{}' -> {} "
                        "(own EPG feed, no Rytec entry)".format(
                            channel_name, feed_match_id))
                    return feed_match_id, fallback_sref

        print("[Match] No match found for '{}'".format(channel_name))
        return None, "4097:0:0:0:0:0:0:0:0:0:"

    def _try_promote_to_curated(
            self, channel_name, country_code, servicetype, channel_id,
            cached, allow_curated_promotion, curated_db):
        """Called from a local-cache-hit branch in _find_match_locked().
        A cache entry written before the curated channel database
        existed for this country (or before this specific channel was
        added to it) is stuck on whatever it originally matched
        (usually live Rytec fuzzy-matching) forever, since step 1's
        cache hit returns early and step 2's curated-DB check is never
        reached again. When allow_curated_promotion is set (bouquet
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
        Lock) since _find_match_internal() below can itself re-enter
        lazy-init code paths on this same instance/thread.

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
        set, checked directly against this country's own EPG feed
        index before falling through to the existing curated-DB/live
        Rytec fuzzy-matching chain - see the "2.5" step below.

        Returns a (rytec_id, sref, source) 3-tuple; source is one of
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
        curated_db = _load_curated_channel_db(country_code) if country_code else None
        feed_index = _get_epg_feed_index(country_code) if country_code else None
        # A plain local list, not an instance attribute - _find_match_
        # locked() appends to it (under self._cache_lock, so that part
        # is already safe) when a cache downgrade needs persisting;
        # checked below, after releasing self._cache_lock, with no
        # cross-thread ambiguity since it's never shared beyond this
        # one call's stack.
        pending_save = []
        with self._cache_lock:
            result = self._find_match_locked(
                channel_name, country_code, servicetype, channel_id,
                allow_curated_promotion, curated_db, epg_guide_id,
                feed_index, pending_save)
        if pending_save:
            # save_cache() writes the same CACHE_FILE a bouquet
            # export's update_complete_cache() does - share
            # export_lock (the same convention plugin.py's cache-
            # format-fix call already follows) so the two writers
            # can't interleave and corrupt/drop each other's write.
            # Deliberately done here, AFTER self._cache_lock was
            # already released above: taking export_lock while still
            # holding _cache_lock would invert the lock order
            # update_complete_cache() itself relies on (its caller
            # holds export_lock first, then it takes _cache_lock
            # internally) - acquiring them in the opposite order here
            # could deadlock against a concurrent export.
            with export_lock:
                save_cache(self.cache)
        return result

    def _find_match_locked(
            self, channel_name, country_code=None, servicetype="4097",
            channel_id=None, allow_curated_promotion=False,
            curated_db=None, epg_guide_id=None, feed_index=None,
            pending_save=None):
        if not channel_name:
            return None, None, None

        # 0. Apply alias normalization (if available)
        if alias_available:
            # Clean the channel name using the same rules as playlist_generator
            norm_name = channel_alias.normalize_channel_name(channel_name)
            if norm_name:
                # If we have an EPG ID for this canonical name, use it
                # directly. self.alias_map (loaded from the on-disk
                # channel_alias.json, if present) can override/add to the
                # curated channel_alias.ALIAS_MAP, which is the actual
                # source of the ~300 hand-mapped Italian channel aliases.
                alias_id = self.alias_map.get(
                    norm_name) or channel_alias.ALIAS_MAP.get(norm_name)
                if alias_id:
                    # ALIAS_MAP is curated for Italian channels
                    # specifically (~300 hand-mapped entries, see
                    # channel_alias.py's own header), but this lookup
                    # had no country check - it fired identically for
                    # every country whose channel list happened to
                    # share a name with one of those entries (e.g.
                    # generic pan-European brands like "Eurosport 1" or
                    # "Nickelodeon"), so Poland's and Spain's own
                    # exports both got Italy's Rytec sref and collided
                    # in eEPGCache, since they became the same physical
                    # DVB tuple. Only trust the hit when the alias id's
                    # own country suffix agrees with the country
                    # actually being matched (same convention
                    # _load_rytec_database() uses to bucket entries) -
                    # or no country was specified at all (e.g. the
                    # in-player "now playing" overlay).
                    alias_country = (
                        alias_id.rsplit('.', 1)[-1].lower()
                        if '.' in alias_id else "")
                    effective_country = RYTEC_COUNTRY_CODE_OVERRIDES.get(
                        country_code, country_code) if country_code else None
                    # ALIAS_MAP's home country (see its own docstring) -
                    # always trust a hit when matching for Italy itself,
                    # even if the curator pinned a specific entry to a
                    # non-".it" Rytec id (e.g. "DISNEY CHANNEL"/"DISNEY
                    # JUNIOR" -> a ".ch" id, because Italy's own Rytec
                    # catalog has no native entry for them). The suffix
                    # check below still guards every OTHER country
                    # against reusing one of these curated Italian
                    # picks for an unrelated channel of the same name.
                    if (not effective_country or not alias_country or
                            effective_country.lower() ==
                            _ALIAS_MAP_HOME_COUNTRY or
                            alias_country == effective_country.lower()):
                        alias_sref = self.rytec_by_id.get(alias_id)
                        if alias_sref:
                            if alias_sref.startswith('1:'):
                                alias_sref = '4097' + alias_sref[1:]
                            print(
                                "[Match] ALIAS HIT: {} -> {}".format(norm_name, alias_id))
                            self._cleanup_stale_unmatched(
                                channel_name, country_code, servicetype)
                            # Rytec's raw tuple can be (correctly)
                            # shared by several countries' entries for
                            # the same pan-European channel brand - see
                            # the synthetic-sref note on the Rytec
                            # candidate match below. Same fix here:
                            # give this Vavoo channel its own unique
                            # reference instead of reusing the shared
                            # one directly, when we have a channel_id
                            # to key it off.
                            if channel_id:
                                return alias_id, unique_fallback_sref(
                                    servicetype, channel_id), 'alias'
                            return alias_id, alias_sref, 'alias'

        # Normalize the original name for key generation
        search_key = self._normalize_key(channel_name, country_code or "")

        # 1. Local cache via normalized index
        if search_key in self.normalized_index:
            cached_key = self.normalized_index[search_key]
            cached = self.cache[cached_key]
            id_val = cached.get('id')
            if self.is_valid_rytec_id(id_val):
                # Check if the channel name matches the Rytec name associated with that ID
                channel_clean = self._clean_name_for_similarity(channel_name)
                rytec_clean = self.rytec_names.get(id_val, '')
                if rytec_clean:
                    current_rytec_sref = self._normalize_rytec_sref(
                        self.rytec_by_id.get(id_val))
                    cached_sref = ensure_sref_trailing_colon(
                        cached.get('sref'))
                    if channel_clean == rytec_clean and (
                            not current_rytec_sref or
                            cached_sref == current_rytec_sref):
                        promoted = self._try_promote_to_curated(
                            channel_name, country_code, servicetype,
                            channel_id, cached, allow_curated_promotion,
                            curated_db)
                        if promoted:
                            return promoted
                        print(
                            "[Match] Local cache HIT (valid ID & name match): {}".format(cached_key))
                        self._cleanup_stale_unmatched(
                            channel_name, country_code, servicetype)
                        return (
                            cached.get('id'), cached.get('sref'),
                            cached.get('source') or 'live')
                    elif channel_clean != rytec_clean:
                        print(
                            "[Match] Cache ID '{}' name mismatch (channel='{}', rytec='{}'), will re-match".format(
                                id_val, channel_clean, rytec_clean))
                        # Do not return, proceed with live matching
                    else:
                        # Name still matches, but the cached sref no
                        # longer matches what Rytec has for this id -
                        # leftover from a stale/mismatched match (see
                        # find_match()'s live-rematch branch below).
                        # Re-match instead of trusting a sref that
                        # actually belongs to a different real channel.
                        print(
                            "[Match] Cache ID '{}' sref stale for '{}' (cached={}, rytec={}), will re-match".format(
                                id_val, channel_name, cached_sref, current_rytec_sref))
                else:
                    # We don't have the Rytec name, accept the cache
                    promoted = self._try_promote_to_curated(
                        channel_name, country_code, servicetype,
                        channel_id, cached, allow_curated_promotion,
                        curated_db)
                    if promoted:
                        return promoted
                    print(
                        "[Match] Local cache HIT (valid ID, no Rytec name): {}".format(cached_key))
                    self._cleanup_stale_unmatched(
                        channel_name, country_code, servicetype)
                    return (
                        cached.get('id'), cached.get('sref'),
                        cached.get('source') or 'live')
            else:
                # Invalid ID, proceed with live matching
                print("[Match] Local cache has invalid ID, will try to re-match.")

        # 2. Community-curated channel database (see
        # generate_epg_channel_db.py): a pre-solved name -> this
        # country's own EPG feed id mapping, built and reviewed offline
        # instead of guessed live by fuzzy-matching against Rytec.
        # Country-scoped by construction (one file per country), so no
        # collision risk from unrelated countries sharing a name.
        if country_code:
            # curated_db is the one find_match() pre-fetched before
            # taking self._cache_lock (see its docstring) - not
            # re-fetched here.
            if curated_db:
                curated_key = self._clean_name_for_similarity(channel_name)
                curated_id = curated_db.get(curated_key)
                if curated_id and channel_id:
                    print(
                        "[Match] CURATED DB HIT: {} -> {}".format(
                            channel_name, curated_id))
                    self._cleanup_stale_unmatched(
                        channel_name, country_code, servicetype)
                    return curated_id, unique_fallback_sref(
                        servicetype, channel_id), 'curated'

        # 2.5. The source catalog's own guide id (geil.to's "tvg" field,
        # threaded through as epg_guide_id - Vavoo's own catalog has no
        # equivalent, so this is always a no-op on that path). A more
        # direct variant of the name-based "own feed" fallback inside
        # _find_match_internal() below - same per-country EPG feed
        # index (feed_index, pre-fetched by find_match() before
        # self._cache_lock was taken - see its docstring), just checked
        # by the id the source already gave us instead of guessed from
        # a fuzzy name match. Deliberately placed after the curated DB
        # (human-reviewed) rather than before it - an automatically-
        # supplied id shouldn't override a curator's own mapping for
        # the same channel.
        if epg_guide_id and country_code and channel_id:
            feed_ids, _name_index = feed_index if feed_index else (None, None)
            if feed_ids and epg_guide_id in feed_ids:
                print(
                    "[Match] GUIDE ID HIT (source catalog): {} -> {}".format(
                        channel_name, epg_guide_id))
                self._cleanup_stale_unmatched(
                    channel_name, country_code, servicetype)
                return epg_guide_id, unique_fallback_sref(
                    servicetype, channel_id), 'live'

        # 3. Live matching
        print("[Match] Doing local matching for: {}".format(channel_name))
        if search_key in self.new_matches:
            m = self.new_matches[search_key]
            return m['id'], m['sref'], m.get('source', 'live')

        result_id, result_sref = self._find_match_internal(
            channel_name, country_code, channel_id=channel_id,
            servicetype=servicetype, feed_index=feed_index)

        # Is there already an entry in the cache (even with invalid ID)?
        # Resolve via normalized_index first: the raw key an entry is
        # stored under can differ from search_key (e.g. name-cleaning
        # rules changed since it was written, same drift as the
        # _clean_name_for_key '&' case). Step 1 above already proves such
        # an entry is reachable via normalized_index - looking it up with
        # self.cache.get(search_key) directly would miss it and silently
        # discard a valid existing match every time this branch runs.
        existing_key = self.normalized_index.get(search_key, search_key)
        existing_entry = self.cache.get(existing_key)

        if result_id and result_sref:
            # Decide which sref to keep
            final_sref = result_sref
            if existing_entry and existing_entry.get('id') == result_id:
                # Only reuse the previously cached sref when it's for the
                # SAME matched id - this keeps re-matches of an unchanged
                # channel stable. When the freshly matched id differs
                # from what's cached, the old sref belongs to whatever
                # channel the cache used to (possibly wrongly) point at;
                # blindly keeping it here is exactly how an id gets
                # updated to the right channel while its sref silently
                # keeps pointing at a different one.
                existing_sref = existing_entry.get('sref')
                current_rytec_sref = self._normalize_rytec_sref(
                    self.rytec_by_id.get(result_id))
                # If the existing one has a valid sref (not fallback) that
                # still agrees with what Rytec currently has for this id,
                # preserve it - this is a no-op in the common case
                # (result_sref should already match) and only matters for
                # candidate-selection ties. If it disagrees, it's stale
                # (e.g. left over from before this id was matched
                # correctly) - fall through to the freshly matched
                # result_sref instead of re-entrenching it.
                if (existing_sref and
                        existing_sref != "4097:0:0:0:0:0:0:0:0:0:" and
                        (not current_rytec_sref or
                         ensure_sref_trailing_colon(existing_sref) ==
                         current_rytec_sref)):
                    final_sref = existing_sref
                    print(
                        "[Match] Preserving existing sref: {}".format(existing_sref))
            # self.new_matches[search_key] = {'id': result_id, 'sref': final_sref}
            self.new_matches[search_key] = {
                'id': result_id,
                'sref': final_sref,
                'name': channel_name,
                'source': 'live'
            }
            save_unmatched(
                channel_name,
                country_code,
                servicetype,
                matched=True)
            return result_id, final_sref, 'live'
        else:
            # If no live match, but there is an existing entry with a valid
            # sref, use it (with matched=False)
            if existing_entry:
                # Compare against the normalized form: some legacy entries
                # were written without the trailing colon, which made this
                # equality check silently treat an actual fallback sref as
                # "valid" and skip the downgrade below.
                existing_sref = existing_entry.get('sref')
                normalized_sref = ensure_sref_trailing_colon(existing_sref)
                if normalized_sref and normalized_sref != "4097:0:0:0:0:0:0:0:0:0:":
                    print("[Match] No live match, using existing sref (invalid ID)")
                    # Update cache with matched=False if needed
                    if existing_entry.get('matched', True) is not False:
                        existing_entry['matched'] = False
                        self.cache[existing_key] = existing_entry
                        self._index_cache_key(existing_key)
                        # Not deferred to new_matches/update_complete_cache():
                        # that path always writes matched=True, which would
                        # be wrong here. This branch is rare (only when a
                        # previously-matched channel stops live-matching),
                        # so an eager write is an acceptable tradeoff - the
                        # actual save_cache() call happens in find_match(),
                        # after self._cache_lock is released (see its own
                        # comment on pending_save for why).
                        if pending_save is not None:
                            pending_save.append(True)
                    return (
                        existing_entry.get('id'), existing_sref,
                        existing_entry.get('source') or 'live')
                elif existing_entry.get('matched') is not False:
                    # Stale entry with an invalid id AND no usable sref -
                    # a leftover from before this channel ever properly
                    # matched. Live re-matching just failed too, so
                    # there's nothing worth preserving; without this, the
                    # cache keeps claiming matched=True with no real EPG
                    # data behind it, forever, since nothing else ever
                    # revisits an entry once it's "matched".
                    existing_entry['matched'] = False
                    self.cache[existing_key] = existing_entry
                    self._index_cache_key(existing_key)
                    if pending_save is not None:
                        pending_save.append(True)
            # Otherwise, no match and no valid sref
            save_unmatched(
                channel_name,
                country_code,
                servicetype,
                matched=False)
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
    """Save cache to file with complete format validation"""
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


def _favourite_key(name, url):
    return "{}###{}".format(name, url)


def load_favourites():
    """Return the persisted favourites dict ({key: {name, url,
    timestamp}}), or {} on any error/missing file - never raises,
    matching every other cache reader in this module."""
    try:
        if not isfile(FAVOURITES_FILE):
            return {}
        with open(FAVOURITES_FILE, 'r') as f:
            data = load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print("[Favourites] Error loading {}: {}".format(FAVOURITES_FILE, e))
        return {}


def is_favourite(name, url):
    return _favourite_key(name, url) in load_favourites()


def toggle_favourite(name, url, country_name=None, country_code=None):
    """Add the (name, url) channel if it isn't already a favourite,
    remove it if it is. Returns the new state (True = now a favourite)
    on success, or None on error - same atomic temp-file-then-rename
    write as save_cache()/_update_favorite_file().

    country_name/country_code are stored alongside the channel so a
    favourite played back later can still be checked against
    parental-control's locked-country list (which matches on the
    display name, e.g. "Italy") and still carry a country_code through
    to Playstream2 for EPG matching - neither is available again once
    the user has left the channel-browsing screen that knew them."""
    try:
        favourites = load_favourites()
        key = _favourite_key(name, url)
        now_favourite = key not in favourites
        if now_favourite:
            favourites[key] = {
                'name': name,
                'url': url,
                'country_name': country_name,
                'country_code': country_code,
                'timestamp': strftime('%Y-%m-%d %H:%M:%S', localtime())
            }
        else:
            del favourites[key]

        temp_file = FAVOURITES_FILE + ".tmp"
        with open(temp_file, 'w') as f:
            dump(favourites, f, indent=2, sort_keys=True)
        rename(temp_file, FAVOURITES_FILE)
        return now_favourite
    except Exception as e:
        print("[Favourites] Error saving {}: {}".format(FAVOURITES_FILE, e))
        return None


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
    used as a fast, pre-solved alternative to live Rytec fuzzy-matching
    for names Rytec doesn't cover well. Keys are normalized the same
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
                'id': m['rytec_id'],
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
            print("[Cache] Added matched: %s -> %s" % (key, m['rytec_id']))

        # Save main cache
        complete_cache = _prune_cache_if_needed(complete_cache)
        temp_file = CACHE_FILE + ".tmp"
        with open(temp_file, 'w') as f:
            dump(complete_cache, f, indent=4, sort_keys=True)
        rename(temp_file, CACHE_FILE)

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


def invalidate_unmatched_cache():
    """Force the next save_unmatched()/flush_unmatched_cache() call to
    reload from disk. Call this after anything writes UNMATCHED_FILE
    directly instead of through save_unmatched() (e.g. a cache-repair
    routine), so a later flush doesn't overwrite that write with a
    stale in-memory copy."""
    global _unmatched_cache_data, _unmatched_cache_dirty
    with _unmatched_lock:
        _unmatched_cache_data = None
        _unmatched_cache_dirty = False


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

    Used by write_epg_mapping_file() as a fallback for channels whose
    Rytec-matched id isn't one the feed itself uses - the same class of
    mismatch plugin.py's get_current_epg() already works around for the
    in-plugin overlay, but that fix doesn't cover this separate,
    epgimport-facing pipeline (exported bouquets), which is what this is
    for.

    Never raises - returns (None, None) on any failure so callers just
    skip the fallback and keep existing (correct-for-most-channels)
    behavior.
    """
    if not country_code:
        return None, None

    cached = _epg_feed_index_cache.get(country_code)
    if cached:
        cached_time, cached_ids, cached_index = cached
        ttl = (_EPG_FEED_INDEX_TTL if cached_ids is not None
               else _EPG_FEED_INDEX_NEGATIVE_TTL)
        if time() - cached_time < ttl:
            return cached_ids, cached_index

    try:
        url = "http://{}:{}/epg/{}.xml".format(
            PROXY_HOST, PORT, country_code.lower())
        # These feeds run several MB to 10+ MB (full multi-day guide for
        # every channel in the country) - the default 10s/3-retries
        # getUrl() timeout budget (tuned for small JSON/HTML responses)
        # routinely isn't enough to pull one down over a set-top box's
        # real-world connection, which silently disabled this whole
        # id-correction path and left most channels stuck on their
        # (usually wrong, see below) Rytec-matched id.
        xml_data = getUrl(url, timeout=30, retries=2)
        if not xml_data:
            warning(
                "EPG feed fetch returned empty for {} - id-correction "
                "fallback disabled for this export, channels will keep "
                "their Rytec-matched id even if the feed uses a "
                "different one".format(country_code))
            # Cache the failure too (empty result, same TTL) - without
            # this, a country with no feed at all (most of them - only
            # a minority of country codes have one) would re-attempt this
            # same failing network fetch for every single unmatched
            # channel once _find_match_internal() starts consulting this
            # index as a fallback, instead of once per TTL window.
            _epg_feed_index_cache[country_code] = (time(), None, None)
            return None, None

        xml_source = io.BytesIO(
            xml_data if isinstance(xml_data, binary_type)
            else xml_data.encode('utf-8'))

        matcher = get_epg_matcher()
        feed_ids = set()
        name_index = {}
        # Stream-parse instead of ET.fromstring(): these feeds are almost
        # entirely <programme> entries (tens of thousands of them) with
        # the actual <channel> definitions front-loaded before any of
        # them, per the XMLTV convention. Building a full DOM of the
        # whole guide just to read the channel list is both slow and
        # memory-heavy on box-class hardware - stop as soon as the
        # <programme> section starts instead.
        for event, elem in ET.iterparse(xml_source, events=('start', 'end')):
            if event == 'end' and elem.tag == 'channel':
                chan_id = elem.get('id')
                if chan_id:
                    feed_ids.add(chan_id)
                    for dn in elem.findall('display-name'):
                        dn_text = (dn.text or '').strip()
                        if not dn_text:
                            continue
                        clean_dn = matcher._clean_name_for_similarity(dn_text)
                        if clean_dn:
                            # Tokens precomputed once here rather than by
                            # every _find_feed_id_by_name() call that
                            # scans this same index (once per channel
                            # whose Rytec id isn't one this feed uses,
                            # which - see write_epg_mapping_file() - can
                            # be a large fraction of a country's channels).
                            name_index[clean_dn] = (
                                chan_id, _tokenize_for_compat(clean_dn))
                elem.clear()
            elif event == 'start' and elem.tag == 'programme':
                break
    except Exception as e:
        warning("Could not fetch/parse EPG feed for {}: {}".format(country_code, e))
        # Same reasoning as the empty-response branch above: cache the
        # failure so repeated calls for this country within the TTL
        # window short-circuit instead of retrying the network fetch.
        _epg_feed_index_cache[country_code] = (time(), None, None)
        return None, None

    _epg_feed_index_cache[country_code] = (time(), feed_ids, name_index)
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
    # Only the threshold-or-above outcome is ever used by callers (a
    # below-threshold best_score is never returned), so - same as the
    # equivalent Rytec-scanning loop in _find_match_internal() - a
    # candidate whose cheap upper-bound estimate already can't reach the
    # threshold can be skipped before paying for the full ratio()
    # computation. Feed indexes run into the hundreds/thousands of
    # entries (see this function's callers), scanned once per exported
    # channel whose Rytec id isn't in this feed's own id set, so this
    # matters for country-wide export time.
    for dn_key, (dn_id, candidate_tokens) in name_index.items():
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


def _build_epg_channels_xml(unique):
    """The channels.xml text for write_epg_mapping_file() - `unique`
    maps each full service reference to its (epg_id, channel_name).

    Everything is XML-escaped: EPGImport reads this file with a strict
    XML parser and skips the whole file (every channel of the country)
    on the first malformed line. Ids taken from an EPG feed arrive here
    already un-escaped (so one containing "&" would have been written
    raw into the attribute), and a channel name containing "--" is not
    allowed inside an XML comment at all. Ids parsed out of Rytec's own
    file by regex can still be in their escaped form - un-escaping
    first makes the result the same either way instead of escaping
    them twice."""
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
    epg_entries: list of tuples (rytec_id, full_service_ref, channel_name),
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

    # Some channels' Rytec-matched id isn't one this country's actual
    # feed uses for <channel id> (it has its own convention for a
    # handful of channels, e.g. "RTP.1.HD.pt" vs the Rytec
    # "rtp1.pt") - epgimport can't find programme data filed under
    # an id the feed never defines. Fall back to the feed's own id,
    # found by display-name match, but only when the Rytec id
    # genuinely isn't one the feed already has - this never touches
    # a channel that's already matching correctly.
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
                        "EPG mapping fallback: '{}' rytec id '{}' not "
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
