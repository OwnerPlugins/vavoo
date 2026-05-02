#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import base64
import glob
import io
import six
import socket
import ssl
import select
import threading
import types
import urllib3

from collections import OrderedDict
from difflib import SequenceMatcher
from json import dump, load, loads
from Components.config import config
from Components.NimManager import nimmanager
from os import listdir, makedirs, remove, system, unlink, rename
from os.path import basename, exists, getmtime, getsize, isfile, join, splitext
from random import choice
from re import IGNORECASE, compile, findall, search, sub
from shutil import copy2
from sys import maxsize
from six import iteritems, unichr
from six.moves import html_entities, html_parser
from time import sleep, time, strftime, localtime
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
    LOG_FILE,
    CACHE_FILE,
    UNMATCHED_FILE,
    HOST_MAIN,
    ALIAS_FILE
)
"""
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin                             #
#  Created by Lululla (https://github.com/Belfagor2005) #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0    #
#  Last Modified: 20260501                              #
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
    from urllib.parse import quote  # , unquote
except ImportError:
    from urllib import quote  # , unquote

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

LOG_MAX_BYTES = 1024 * 1024
DEBUG_ENABLED = str(
    __import__("os").environ.get(
        "VAVOO_DEBUG",
        "0")).lower() in (
            "1",
            "true",
            "yes",
    "on")


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
    from datetime import datetime
    try:
        msg = ensure_str(msg, errors='ignore')
    except Exception:
        try:
            msg = str(msg)
        except Exception:
            msg = '<unprintable message>'
    line = "[{0}] [{1}] [{2}] {3}".format(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
    def _module_print(*args, **kwargs):
        kwargs.setdefault('area', area)
        kwargs.setdefault('level', level)
        return plugin_print(*args, **kwargs)
    return _module_print


PLUGIN_PATH = PLUGIN_ROOT


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
    dns_box = None
    dns_external = None
    try:
        with open("/etc/resolv.conf", "r") as f:
            for line in f:
                if line.startswith("nameserver"):
                    dns_box = line.split()[1]
                    break
    except BaseException:
        dns_box = "n/a"

    data = urlopen("https://1.1.1.1/cdn-cgi/trace", timeout=5).read()
    data = data.decode("utf-8")
    for line in data.split("\n"):
        if line.startswith("h="):
            dns_external = line.split("=")[1]
            break
        else:
            dns_external = "n/a"
    return dns_box, dns_external


dns_box, dns_ext = getDNSinfo()
print("Vavoo Version: ", __version__)
print("DNS box:", dns_box)
print("DNS out:", dns_ext)


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


class AspectManager:
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
    """Fetch URL with exponential backoff retry logic"""
    # detect 451
    HTTP_451_SENTINEL = "__HTTP451__"

    headers = {'User-Agent': RequestAgent()}

    if not url:
        raise ValueError("Empty URL passed to getUrl")

    url = ensure_str(url, errors='ignore').strip()

    if not url.startswith(("http://", "https://")):
        raise ValueError("Invalid URL (missing scheme): %s" % url)

    for i in range(retries):
        try:
            socket.setdefaulttimeout(timeout)
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

            # detect 451
            code = getattr(e, 'code', None)
            if code == 451:
                print("HTTP 451 for URL: {0}".format(url))
                return HTTP_451_SENTINEL

            if i < retries - 1:
                wait_time = backoff ** i
                print(
                    "HTTP error {0} on attempt {1}, retrying in {2} seconds...".format(
                        code, i + 1, wait_time))
                select.select([], [], [], wait_time)
                continue
            print(
                "Failed after {0} attempts for URL: {1}".format(
                    retries, url))
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
                print(
                    "Failed after {0} attempts for URL: {1}".format(
                        retries, url))
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
                "Failed after {0} attempts for URL: {1}".format(
                    retries, url))
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
        lambda: Popen(
            [
                'curl',
                '-s',
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
        if PY2:
            converted_data = convert_to_unicode(data)
            with io.open(file_path, 'w', encoding='utf-8') as cache_file:
                dump(
                    converted_data,
                    cache_file,
                    indent=4,
                    ensure_ascii=False)
        else:
            with io.open(file_path, 'w', encoding='utf-8') as cache_file:
                dump(data, cache_file, indent=4, ensure_ascii=False)
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


def get_cache(key):
    file_path = join(PLUGIN_PATH, key + '.json')
    if not (exists(file_path) and getsize(file_path) > 0):
        return None
    try:
        data = _read_json_file(file_path)
        if isinstance(data, str):
            data = {"value": data}
            _write_json_file(file_path, data)

        if not isinstance(data, dict):
            print(
                "Unexpected data format in {}: Expected a dict, got {}".format(
                    file_path, type(data)))
            remove(file_path)
            return None

        if _is_cache_valid(data):
            return data.get('value')

    except ValueError as e:
        print("Error decoding JSON from", file_path, ":", e)
        trace_error()
    except Exception as e:
        print("Unexpected error reading cache file {}:".format(file_path), e)
        remove(file_path)
        trace_error()

    return None


def _read_json_file(file_path):
    with io.open(file_path, 'r', encoding='utf-8') as f:
        return load(f)


def _write_json_file(file_path, data):
    with io.open(file_path, 'w', encoding='utf-8') as f:
        dump(data, f, indent=4, ensure_ascii=False)


def _is_cache_valid(data):
    return (
        data.get('sigValidUntil', 0) > int(time())
        and data.get('ip', "") == get_external_ip()
    )


# ============================================================================
# FUNCTIONS FOR VAVOO PROXY
# ============================================================================

def getAuthSignature():
    """Get authentication - ALWAYS use proxy"""
    print("Using proxy authentication system")
    return "PROXY_ACTIVE"


def get_new_auth_signature():
    """
    New Vavoo authentication system via local proxy
    Returns a valid token for the proxy
    """
    try:
        print("Using new proxy authentication system...")

        try:
            req = Request(PROXY_STATUS_URL)
            response = urlopen(req, timeout=5)
            if response.getcode() == 200:
                data = loads(response.read().decode('utf-8'))
                if data.get("initialized", False):
                    print("Proxy active and running")
                    return "PROXY_ACTIVE"
        except BaseException:
            pass

        try:
            from .vavoo_proxy import run_proxy_in_background
            print("Starting proxy in background...")
            run_proxy_in_background()
            sleep(5)
            return "PROXY_STARTED"
        except Exception as e:
            trace_error()
            print("Proxy start error: " + str(e))

    except Exception as e:
        trace_error()
        print("New auth error: " + str(e))

    print("Falling back to old authentication system")
    return getAuthSignature()


def get_proxy_channels(country_name):
    """Get channels for a country from proxy - with retry"""
    country_name = ensure_str(country_name, errors='ignore').strip()
    max_retries = 3

    for attempt in range(max_retries):
        try:
            print("Getting channels for '" + str(country_name) +
                  "' (attempt " + str(attempt + 1) + "/" + str(max_retries) + ")")

            # URL-encode
            encoded_country = quote(country_name.encode(
                'utf-8')) if PY2 else quote(country_name)

            # Build URL
            proxy_url = PROXY_BASE_URL + \
                "/channels?country={}".format(encoded_country)
            # Fetch with timeout
            response = getUrl(proxy_url, timeout=15)
            print("Request URL: " + proxy_url)

            if not response:
                print(
                    "Empty response for '" +
                    str(country_name) +
                    "'")
                continue

            # Parse JSON
            channels = loads(response)

            if not isinstance(channels, list):
                print("Invalid response format: " + str(type(channels)))
                continue

            print("Successfully got " + str(len(channels)) +
                  " channels for '" + str(country_name) + "'")

            # Process channels
            processed_channels = []
            for channel in channels:
                if isinstance(channel, dict):
                    channel_id = channel.get('id', '')
                    if not channel_id:
                        continue

                    # Build proxy URL
                    proxy_stream_url = PROXY_BASE_URL + \
                        "/vavoo?channel={}".format(channel_id)
                    processed_channels.append({
                        'id': channel_id,
                        'name': channel.get('name', 'Unknown'),
                        'url': proxy_stream_url,
                        'logo': channel.get('logo', ''),
                        'country': channel.get('country', country_name)
                    })

            return processed_channels

        except Exception as e:
            print("Attempt " + str(attempt + 1) +
                  " failed for '" + str(country_name) + "': " + str(e))
            if attempt < max_retries - 1:
                sleep(2)  # Wait before retry

    print("All attempts failed for '" + str(country_name) + "'")
    return []


def get_proxy_stream_url(channel_id):
    """Get the stream URL via proxy"""
    return PROXY_BASE_URL + "/vavoo?channel=%s" % channel_id


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
        status_url = PROXY_STATUS_URL
        if requests is not None:
            response = requests.get(status_url, timeout=3)
            if response.status_code == 200:
                return response.json()
        else:
            req = Request(status_url)
            response = urlopen(req, timeout=3)
            if response.getcode() == 200:
                return loads(response.read().decode('utf-8', 'ignore'))
    except BaseException:
        return None
    return None


def is_proxy_running():
    """Check if the proxy is running"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            return s.connect_ex((PROXY_HOST, PORT)) == 0
        finally:
            s.close()
    except BaseException:
        return False


def is_proxy_ready(timeout=2):
    """Check if the proxy is ready to receive requests"""
    try:
        response = getUrl(PROXY_STATUS_URL, timeout=timeout)
        if response:
            data = loads(response)
            return data.get("initialized", False)
        return False
    except BaseException:
        return False


_original_getAuthSignature = getAuthSignature


def getAuthSignature():
    """
    Wrapper that uses the proxy first, then falls back to the old system
    """
    print("getAuthSignature called...")

    try:
        if is_proxy_running():
            print("Proxy active, using new system")
            return "PROXY_AUTH"
    except BaseException:
        trace_error()
        pass

    print("Falling back to old authentication system")
    return _original_getAuthSignature()


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


def MemClean():
    """Clear system memory cache"""
    try:
        system('sync')
        for i in range(1, 4):
            system("echo " + str(i) + " > /proc/sys/vm/drop_caches")
    except Exception:
        pass


def ReloadBouquets(delay=2000):
    """Reload Enigma2 bouquets and service lists after a delay (in ms)"""
    from enigma import eDVBDB, eTimer
    try:
        def do_reload():
            try:
                db = eDVBDB.getInstance()
                db.reloadBouquets()
                db.reloadServicelist()
                print("Bouquets reloaded successfully")
            except Exception as e:
                print("Error during service reload: " + str(e))

        reload_timer = eTimer()
        try:
            reload_timer.callback.append(do_reload)
        except BaseException:
            reload_timer.timeout.connect(do_reload)
        reload_timer.start(delay, True)
    except Exception as e:
        print("Error setting up service reload: " + str(e))
        do_reload()


def ensure_sref_trailing_colon(sref):
    if sref and not sref.endswith(':'):
        return sref + ':'
    return sref


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
        '&quot;': '"', '&ntilde;': '~', '&rsquo;': "'", '&nbsp;': ' ',
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
def initialize_cache_with_local_flags():
    """Copy all local flags from skin/cowntry/ to cache directory"""
    local_dir = join(PLUGIN_PATH, 'skin/cowntry')
    cache_dir = FLAG_CACHE_DIR

    if not exists(local_dir):
        print("Local flags directory not found: %s" % local_dir)
        return 0

    # Python 2 compatible directory creation
    if not exists(cache_dir):
        try:
            makedirs(cache_dir)
        except Exception:
            pass

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
            except Exception:
                pass

        # 4. Cache file path
        cache_file = join(cache_dir, "%s.png" % country_code_lower)

        # 5. Check fresh cache (<7 days)
        if exists(cache_file):
            try:
                file_age = time() - getmtime(cache_file)
                if file_age < 604800:
                    print("Cache HIT: %s" % country_name)
                    return True, cache_file
            except Exception:
                pass

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

        # 11. Save to cache
        try:
            f = open(cache_file, 'wb')
            f.write(flag_data)
            f.close()

            # Verify PNG header
            f = open(cache_file, 'rb')
            header = f.read(8)
            f.close()
            if header != b'\x89PNG\r\n\x1a\n':
                print("ERROR: Not a valid PNG file!")
                try:
                    unlink(cache_file)
                except Exception:
                    pass
                return False, "Invalid PNG file downloaded"

            print("Flag %dx%d saved: %s (%d bytes)" %
                  (width, height, cache_file, len(flag_data)))
            return True, cache_file

        except Exception as e:
            print("Error saving to cache: %s" % e)
            return False, "Save error: %s" % e

    except Exception as e:
        print("Flag download error: %s" % e)
        return False, "Flag download error: %s" % e


def download_flag_with_size(
        country_name,
        size="40x30",
        cache_dir=FLAG_CACHE_DIR):
    """
    Download flag with specific size (40x30, 80x60, etc.)
    Returns: success (True/False)
    """
    try:
        country_code = get_country_code(country_name)
        if not country_code:
            print("No code for: %s" % country_name)
            return False

        if "x" in size:
            try:
                width, height = size.split("x")
                width = int(width)
                height = int(height)
            except BaseException:
                width, height = 40, 30
        else:
            width, height = 40, 30

        # URL with fixed size w/h
        url = "https://flagcdn.com/w%d/h%d/%s.png" % (
            width, height, country_code.lower())

        print("Downloading %s flag %dx%d from: %s" %
              (country_name, width, height, url))

        if not exists(cache_dir):
            try:
                makedirs(cache_dir)
            except Exception:
                pass

        cache_file = join(cache_dir, "%s.png" % country_code.lower())

        req = Request(url, headers={'User-Agent': 'Vavoo-Stream/1.0'})

        try:
            if PY3:
                response = urlopen(req, timeout=5, context=ssl_context)
            else:
                response = urlopen(req, timeout=5)
        except Exception as e:
            print("Network error: %s" % str(e))
            return False

        if response.getcode() == 200:
            flag_data = response.read()
            response.close()

            # Save to cache
            with open(cache_file, 'wb') as f:
                f.write(flag_data)

            print("✓ Flag %dx%d saved: %s (%d bytes)" %
                  (width, height, cache_file, len(flag_data)))
            return True
        else:
            print(
                "✗ Download failed for %s (HTTP %d)" %
                (country_name, response.getcode()))
            return False

    except Exception as e:
        print("Error downloading %s: %s" % (country_name, str(e)))
        return False


def get_country_code_from_bouquet_name(name):
    """Extract country code from a bouquet display name (e.g., 'Italy', 'Italy ➾ Sports')."""
    separators = ["➾", "⟾", "->", "→"]
    base_name = name
    for sep in separators:
        if sep in name:
            base_name = name.split(sep)[0].strip()
            break
    return country_codes.get(base_name.capitalize(), None)


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

    separators = ["➾", "⟾", "->", "→", "»", "›"]
    for sep in separators:
        if sep in country_name:
            country_name = country_name.split(sep)[0].strip()
            break

    country_name = country_name.strip()

    if len(country_name) < 2:
        return ""

    special_mapping = {
        'America': 'us',
        'Arabia': 'sa',
        'Balkans': 'bk',
        'Baltic': 'baltic',
        'Czech Republic': 'cz',
        'Czech': 'cz',
        'Global': 'internat',
        'Great Britain': 'gb',
        'Holy See': 'va',
        'Internat': 'internat',
        'International': 'internat',
        'Internaz': 'internat',
        'North Korea': 'kp',
        'Russia': 'ru',
        'Russian Federation': 'ru',
        'Scandinavia': 'scandinavia',
        'Slovak Republic': 'sk',
        'Slovakia': 'sk',
        'South Korea': 'kr',
        'UAE': 'ae',
        'UK': 'gb',
        'USA': 'us',
        'United Arab Emirates': 'ae',
        'United Kingdom': 'gb',
        'United States': 'us',
        'Vatican City': 'va',
        'World': 'internat',
    }

    if country_name in special_mapping:
        return special_mapping[country_name]

    # Full country map
    country_map = {
        # Europe
        'Albania': 'al',
        'Arabia': 'sa',
        'Austria': 'at',
        'Balkans': 'bk',
        'Belgium': 'be',
        'Bulgaria': 'bg',
        'Croatia': 'hr',
        'Czech Republic': 'cz',
        'France': 'fr',
        'Germany': 'de',
        'Greece': 'gr',
        'Hungary': 'hu',
        'Italy': 'it',
        'Netherlands': 'nl',
        'Poland': 'pl',
        'Portugal': 'pt',
        'Romania': 'ro',
        'Russia': 'ru',
        'Slovakia': 'sk',
        'Slovenia': 'si',
        'Spain': 'es',
        'Switzerland': 'ch',
        'Turkey': 'tr',
        'UK': 'gb',
        'United Kingdom': 'gb',

        # Special cases
        'Global': 'internat',
        'Internat': 'internat',
        'International': 'internat',
        'Internaz': 'internat',
        'World': 'internat',

        'Italia': 'it',
        'Italiana': 'it',
        'Italian': 'it',
        'German': 'de',
        'French': 'fr',
        'Spanish': 'es',
        'English': 'gb',
        'British': 'gb',

        # Default
        'default': 'us'
    }

    # Exact match
    if country_name in country_map:
        return country_map[country_name]

    # Case-insensitive
    name_lower = country_name.lower()
    for key, code in country_map.items():
        if key.lower() == name_lower:
            return code

    # Partial match
    for key, code in country_map.items():
        if key.lower() in name_lower or name_lower in key.lower():
            return code

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

        cleaned = 0
        for pattern in patterns:
            for filepath in glob.glob(pattern):
                try:
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
    import threading

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


def get_epg_matcher(similarity_threshold=None):
    global _epg_matcher
    # Se non viene passato un valore, usa quello dalla configurazione
    if similarity_threshold is None:
        similarity_threshold = config.plugins.vavoo.similarity_threshold.value / 100.0
    if _epg_matcher is None:
        _epg_matcher = VavooEPGMatcher(similarity_threshold)
    else:
        # Aggiorna la soglia nel matcher esistente (per modifiche dinamiche)
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
    parts = service_ref.split(':')
    if len(parts) < 4:
        return 0

    try:
        namespace_str = parts[3] if parts[3] else '0'
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


def get_configured_satellites():
    """
    Get list of satellites configured by user in Enigma2.
    Returns list of orbital positions in tenths of degree (e.g., [130, 192, 282])
    """
    try:
        configured_sats = []

        # Method 1: Direct from NimManager
        if hasattr(nimmanager, 'getConfiguredSats'):
            sats = nimmanager.getConfiguredSats()
            if sats:
                configured_sats = list(sats)
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


class VavooEPGMatcher:
    def __init__(self, similarity_threshold=0.70):
        self.similarity_threshold = similarity_threshold
        # (clean_name, original_name, service_ref)
        self.rytec_entries = []
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
        if not id_val or not isinstance(id_val, str):
            return False
        if '.' not in id_val:
            return False
        parts = id_val.split('.')
        if len(parts) < 2:
            return False
        suffix = parts[-1]
        return len(suffix) in (2, 3) and suffix.isalpha()

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
            with open(rytec_file, 'r', encoding='utf-8') as f:
                content = f.read()

            pattern = r'<channel\s+id="([^"]+)">([^<]+)</channel>\s*(?:<!--\s*([^>]+)\s*-->)?'
            matches = findall(pattern, content, IGNORECASE)

            for match in matches:
                original_id = match[0].strip()
                service_ref = match[1].strip()
                comment = match[2].strip() if len(
                    match) > 2 and match[2] else None

                if comment:
                    channel_name = comment
                else:
                    channel_name = original_id.replace(
                        '.it',
                        '').replace(
                        '.de',
                        '').replace(
                        '.fr',
                        '')
                    channel_name = channel_name.replace(
                        '-', ' ').replace('_', ' ')

                # clean_name = self._clean_name(channel_name)
                clean_name = self._clean_name_for_similarity(channel_name)
                self.rytec_entries.append(
                    (clean_name, channel_name, original_id, service_ref))
                self.rytec_names[original_id] = clean_name

                # NEW: store the cleaned name associated with the ID
                self.rytec_names[original_id] = clean_name

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
        """Pulisce il nome per il calcolo della similarità: rimuove suffissi .c, .s, .b e indicatori."""
        if not name:
            return ""
        n = name.upper()  # usiamo maiuscolo come nell'esterno, poi abbassiamo
        n = sub(r'\[.*\]', '', n)
        n = sub(r'\(.*\)', '', n)
        n = sub(r'\s+(HD|FHD|SD|4K|ITA|ITALIA|BACKUP|TIMVISION|PLUS)$', '', n)
        # Remove suffiss Vavoo (.c, .s, .b, ...)
        if not n.startswith("HISTORY"):
            n = sub(r'\s+\.[A-Z0-9]{1,3}$', '', n)
        n = sub(r'\s+\+$', '', n)
        n = sub(r'[^A-Z0-9 ]', '', n)
        n = sub(r'\s+', ' ', n)
        return n.strip().lower()

    def _normalize_key(self, channel_name, country_code):
        clean_name = self._clean_name_for_key(channel_name)
        return "{}_{}".format(clean_name, country_code)

    def _build_normalized_index(self):
        self.normalized_index = {}
        for key, value in self.cache.items():
            if '_' in key:
                name_part = key.rsplit('_', 1)[0]
                country_part = key.rsplit('_', 1)[1]
            else:
                name_part = key
                country_part = ''
            norm_key = self._normalize_key(name_part, country_part)
            self.normalized_index[norm_key] = key

    def _get_signal_priority(self, service_ref, country_code=None):
        """
        Determine signal priority based on service reference type.

        Priority levels:
        1 = Satellite (best) - with bonus for Italian satellites
        2 = Terrestrial DVB-T
        3 = Cable
        4 = Other / IPTV or unknown
        """
        parts = service_ref.split(':')
        if len(parts) < 4:
            return 4  # Unknown / other

        try:
            namespace_str = parts[3] if parts[3] else '0'
            namespace = int(namespace_str, 16)

            # Known satellite namespaces
            satellite_namespaces = [
                0x5A0000,   # 13.0°E HotBird (Italy)
                0xC00000,   # 19.2°E Astra
                0xEB0000,   # 23.5°E Astra 3
                0xEF0000,   # 28.2°E Astra 2
                0xE080000,  # 16.0°E Eutelsat 16A
                0x9E0000,   # 9.0°E Eutelsat 9B
                0x7E0000,   # 7.0°E Eutelsat 7E
                0xDDE0000,  # 5.0°W Eutelsat 5WA (Italy)
                0xCE40000,  # 30.0°W Hispasat
                0x2A00000,  # 42.0°E Türksat
                0x4C0000,   # 4.8°E Astra 4A / Sirius
                0x1F80000,  # 31.5°E Astra 5B
                0x2100000,  # 33.0°E Eutelsat 33E
                0x1980000,  # 25.5°E Es'hail / Arabsat
                0x1C20000,  # 45.0°E AzerSpace
                0x1860000,  # 39.0°E Hellas Sat
                0x36E0000,  # 36.0°E Eutelsat 36B
                0x1040000,  # 26.0°E Badr
                0x130000,   # 1.9°E BulgariaSat
            ]

            # Italian satellites (bonus priority)
            italian_satellites = [0x5A0000, 0xDDE0000]

            # Check for satellite match
            for sat_ns in satellite_namespaces:
                if namespace & 0xFFF00000 == sat_ns:
                    if country_code == 'it' and sat_ns in italian_satellites:
                        return 1  # Italian satellite - top priority
                    return 1      # Other satellite

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

    def _find_match_internal(self, channel_name, country_code):
        """
        Search for a match in ALL Rytec channels, then apply boost based on user configuration.
        """
        if not channel_name:
            return None, None

        # Clean the input channel name
        clean_input = self._clean_name_for_similarity(channel_name)

        # Load user-configured satellites (e.g., [130] for 13°E)
        if not hasattr(self, '_configured_sats'):
            self._configured_sats = get_configured_satellites()
            print("[Match] User has {} configured satellites: {}".format(
                len(self._configured_sats), self._configured_sats))

        candidates = []

        # Pass 1: search all matches by similarity (ignore priority for now)
        for clean_entry, orig_name, rytec_id, service_ref in self.rytec_entries:
            entry_country = rytec_id.split('.')[-1] if '.' in rytec_id else ""

            # --- FILTER BY COUNTRY (including the Balkans) ---
            if country_code:
                if country_code == "bk":
                    # List of Balkan countries (extend if necessary)
                    balkan_codes = [
                        "ba", "hr", "rs", "si", "me", "mk", "al", "bg", "ro"]
                    if entry_country not in balkan_codes:
                        continue
                else:
                    if entry_country != country_code:
                        continue
            # If country_code is None, we do not filter by country

            # Calculate base similarity
            score = calculate_similarity(clean_input, clean_entry)
            if score < self.similarity_threshold:
                continue

            # Calculate base similarity
            score = calculate_similarity(clean_input, clean_entry)
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

        # Sort by adjusted score (highest first)
        candidates.sort(key=lambda x: -x[0])

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

                return rytec_id, converted

        print("[Match] No match found for '{}'".format(channel_name))
        return None, "4097:0:0:0:0:0:0:0:0:0:"

    def find_match(self, channel_name, country_code=None, servicetype="4097"):
        if not channel_name:
            return None, None

        # 0. Apply alias normalization (if available)
        if alias_available:
            # Clean the channel name using the same rules as playlist_generator
            norm_name = channel_alias.normalize_channel_name(channel_name)
            if norm_name:
                # If we have an EPG ID for this canonical name, use it directly
                alias_id = self.alias_map.get(norm_name)
                if alias_id:
                    alias_sref = self.rytec_by_id.get(alias_id)
                    if alias_sref:
                        if alias_sref.startswith('1:'):
                            alias_sref = '4097' + alias_sref[1:]
                        print(
                            "[Match] ALIAS HIT: {} -> {}".format(norm_name, alias_id))
                        return alias_id, alias_sref

        # Normalize the original name for key generation
        search_key = self._normalize_key(channel_name, country_code or "")

        # 1. Local cache via normalized index
        if search_key in self.normalized_index:
            cached_key = self.normalized_index[search_key]
            cached = self.cache[cached_key]
            id_val = cached.get('id')
            if self.is_valid_rytec_id(id_val):
                # Check if the channel name matches the Rytec name associated with that ID
                # rytec_clean = self.rytec_names.get(id_val, '')
                channel_clean = self._clean_name_for_similarity(channel_name)
                rytec_clean = self.rytec_names.get(id_val, '')
                if rytec_clean:
                    channel_clean = self._clean_name_for_similarity(
                        channel_name)
                    if channel_clean == rytec_clean:
                        print(
                            "[Match] Local cache HIT (valid ID & name match): {}".format(cached_key))
                        return cached.get('id'), cached.get('sref')
                    else:
                        print(
                            "[Match] Cache ID '{}' name mismatch (channel='{}', rytec='{}'), will re-match".format(
                                id_val, channel_clean, rytec_clean))
                        # Do not return, proceed with live matching
                else:
                    # We don't have the Rytec name, accept the cache
                    print(
                        "[Match] Local cache HIT (valid ID, no Rytec name): {}".format(cached_key))
                    return cached.get('id'), cached.get('sref')
            else:
                # Invalid ID, proceed with live matching
                print("[Match] Local cache has invalid ID, will try to re-match.")

        # 2. Online cache
        if not hasattr(self, '_checked_temp_cache'):
            self._checked_temp_cache = False
            self._temp_cache = None

        if not self._checked_temp_cache:
            print("[Match] Checking temp cache once...")
            self._temp_cache = load_temp_cache()
            if not self._temp_cache:
                print("[Match] Temp cache not found, downloading once...")
                if download_epg_cache_if_needed():
                    self._temp_cache = load_temp_cache()
            self._checked_temp_cache = True

        if self._temp_cache and search_key in self._temp_cache:
            cached = self._temp_cache[search_key]
            print("[Match] Temp cache HIT: {}".format(search_key))
            new_entry = cached.copy()
            new_entry['name'] = channel_name   # original name
            self.cache[search_key] = new_entry
            self._build_normalized_index()
            save_cache(self.cache)
            return cached.get('id'), cached.get('sref')

        # 3. Live matching
        print("[Match] Doing local matching for: {}".format(channel_name))
        if search_key in self.new_matches:
            m = self.new_matches[search_key]
            return m['id'], m['sref']

        result_id, result_sref = self._find_match_internal(
            channel_name, country_code)

        # Is there already an entry in the cache (even with invalid ID)?
        existing_entry = self.cache.get(
            search_key) if search_key in self.cache else None

        if result_id and result_sref:
            # Decide which sref to keep
            final_sref = result_sref
            if existing_entry:
                existing_sref = existing_entry.get('sref')
                # If the existing one has a valid sref (not fallback), preserve
                # it
                if existing_sref and existing_sref != "4097:0:0:0:0:0:0:0:0:0:":
                    final_sref = existing_sref
                    print(
                        "[Match] Preserving existing sref: {}".format(existing_sref))
            # self.new_matches[search_key] = {'id': result_id, 'sref': final_sref}
            self.new_matches[search_key] = {
                'id': result_id,
                'sref': final_sref,
                'name': channel_name
            }
            save_unmatched(
                channel_name,
                country_code,
                servicetype,
                matched=True)
            return result_id, final_sref
        else:
            # If no live match, but there is an existing entry with a valid
            # sref, use it (with matched=False)
            if existing_entry:
                existing_sref = existing_entry.get('sref')
                if existing_sref and existing_sref != "4097:0:0:0:0:0:0:0:0:0:":
                    print("[Match] No live match, using existing sref (invalid ID)")
                    # Update cache with matched=False if needed
                    if existing_entry.get('matched', True) is not False:
                        existing_entry['matched'] = False
                        self.cache[search_key] = existing_entry
                        self._build_normalized_index()
                        save_cache(self.cache)
                    return existing_entry.get('id'), existing_sref
            # Otherwise, no match and no valid sref
            save_unmatched(
                channel_name,
                country_code,
                servicetype,
                matched=False)
            return None, None

    def save_cache(self):
        if self.new_matches:
            complete_cache = load_cache()
            for key, value in self.new_matches.items():
                # Use the original name if present
                name = value.get('name')
                if not name:
                    parts = key.rsplit('_', 1)
                    name = parts[0] if len(parts) > 1 else key
                country = key.split('_')[-1] if '_' in key else ''
                complete_cache[key] = {
                    'id': value.get('id'),
                    'sref': ensure_sref_trailing_colon(value.get('sref')),
                    'name': name,   # <-- original name
                    'country': country,
                    'matched': True,
                    'timestamp': strftime('%Y-%m-%d %H:%M:%S', localtime())
                }
            with open(CACHE_FILE, 'w') as f:
                dump(complete_cache, f, indent=2, sort_keys=True)
            self.cache = complete_cache
            self._build_normalized_index()
            self.new_matches.clear()
            print(
                "[VavooEPGMatcher] Cache saved with {} entries".format(
                    len(complete_cache)))


# ==================== EPG CACHE FUNCTIONS ====================


def load_temp_cache():
    """Load EPG cache from /tmp/vavoo_epg_cache.json"""
    temp_file = "/tmp/vavoo_epg_cache.json"
    try:
        if exists(temp_file):
            with open(temp_file, 'r') as f:
                return load(f)
    except Exception as e:
        print("[Cache] Error loading {}: {}".format(temp_file, e))

    return None


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

        with open(CACHE_FILE, 'w') as f:
            dump(cache, f, indent=2, sort_keys=True)
        print("[Cache] Saved {} entries".format(len(cache)))
        return True
    except Exception as e:
        print("[Cache] Error saving cache: {}".format(e))
        return False


def clean_cache_and_unmatched():
    """
    Move to the unmatched cache all entries from the main cache
    that have invalid IDs or that do not match the channel name.
    Also fixes the formatting of sref.
    """
    # Load main cache
    if not exists(CACHE_FILE):
        return
    with open(CACHE_FILE, 'r') as f:
        main_cache = load(f)

    # Load existing unmatched cache
    unmatched = {}
    if exists(UNMATCHED_FILE):
        with open(UNMATCHED_FILE, 'r') as f:
            unmatched = load(f)

    # Get matcher to access Rytec names
    matcher = get_epg_matcher()

    new_main = {}
    moved = 0

    for key, value in main_cache.items():
        # Fix sref
        sref = value.get('sref', '')
        if sref and not sref.endswith(':'):
            value['sref'] = sref + ':'

        id_val = value.get('id')
        if not matcher.is_valid_rytec_id(id_val):
            # Move to unmatched
            unmatched[key] = value
            moved += 1
            continue

        # Check if the ID matches the channel name
        # Extract name from Rytec comment if possible, otherwise use the ID
        rytec_name = matcher.rytec_names.get(id_val, '')
        if not rytec_name:
            # Try to derive from ID: remove country suffix and replace dots
            # with spaces
            rytec_name = id_val.split('.')[0].replace('.', ' ')
        # clean_rytec_name = matcher._clean_name(rytec_name)
        # clean_channel_name = matcher._clean_name(key.split('_')[0])
        clean_rytec_name = matcher._clean_name_for_similarity(rytec_name)
        clean_channel_name = matcher._clean_name_for_similarity(key.split('_')[
                                                                0])

        if clean_rytec_name != clean_channel_name:
            # Move to unmatched to be re-matched
            unmatched[key] = value
            moved += 1
        else:
            new_main[key] = value

    # Save caches
    with open(CACHE_FILE, 'w') as f:
        dump(new_main, f, indent=2)
    with open(UNMATCHED_FILE, 'w') as f:
        dump(unmatched, f, indent=2)
    matcher.cache = new_main
    matcher._build_normalized_index()
    print("[Cache] Cleanup completed: moved {} entries to unmatched".format(moved))
    return moved


def cleanup_cache_matched_flag():
    """Fix the matched flag for entries with invalid id."""
    if not exists(CACHE_FILE):
        return
    with open(CACHE_FILE, 'r') as f:
        cache = load(f)
    changed = False
    for key, value in cache.items():
        if not VavooEPGMatcher.is_valid_rytec_id(value.get('id')):
            if value.get('matched', False):
                value['matched'] = False
                changed = True
    if changed:
        with open(CACHE_FILE, 'w') as f:
            dump(cache, f, indent=2)
        print("[Cache] Cleaned matched flags for invalid IDs.")


def download_epg_cache_if_needed():
    """Download vavoo_epg_cache.json to /tmp/ if not exists"""
    temp_file = "/tmp/vavoo_epg_cache.json"

    # If already exists, don't download
    if exists(temp_file):
        return True

    try:
        import requests
        url = "{}/vavoo_epg_cache.json".format(HOST_MAIN)
        print("[Cache] Downloading to /tmp...")

        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            with open(temp_file, 'wb') as f:
                f.write(response.content)
            print("[Cache] Downloaded to: {}".format(temp_file))
            return True
    except Exception as e:
        print("[Cache] Download error: {}".format(e))

    return False


def update_complete_cache(
        matched_channels,
        unmatched_channels,
        country_code,
        servicetype="4097"):
    """Update the complete cache with matched channels only; unmatched go to unmatched.json."""
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
                'timestamp': strftime('%Y-%m-%d %H:%M:%S', localtime())
            }
            print("[Cache] Added matched: %s -> %s" % (key, m['rytec_id']))

        # Save main cache
        with open(CACHE_FILE, 'w') as f:
            dump(complete_cache, f, indent=4, sort_keys=True)

        # Update matcher with new cache
        matcher.cache = complete_cache
        matcher._build_normalized_index()

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
    """Save or update an unmatched channel with consistent format.
       If sref is provided, it will be used as the service reference;
       otherwise a fallback is built from servicetype.
    """
    try:
        unmatched_data = {}

        if exists(UNMATCHED_FILE):
            try:
                with open(UNMATCHED_FILE, 'r') as f:
                    content = f.read().strip()
                    if content:
                        unmatched_data = loads(content)

                        # Convert old format if needed
                        for key, value in list(unmatched_data.items()):
                            if 'matched' not in value:
                                # Convert to new format
                                unmatched_data[key] = {
                                    'id': value.get(
                                        'id', key), 'name': value.get(
                                        'name', key.split('_')[0] if '_' in key else key), 'country': value.get(
                                        'country', country_code), 'sref': value.get(
                                        'sref', "%s:0:0:0:0:0:0:0:0:0:" %
                                        servicetype), 'timestamp': value.get(
                                        'timestamp', strftime(
                                            '%Y-%m-%d %H:%M:%S', localtime())), 'matched': False, 'attempts': 1}
                                print(
                                    "[Unmatched] Converted old format: %s" %
                                    key)
            except Exception as read_error:
                print(
                    "[Unmatched] Corrupted file, starting fresh: %s" %
                    read_error)
                unmatched_data = {}

        key = "%s_%s" % (channel_name.strip(), country_code or '')

        if matched and key in unmatched_data:
            # Remove if now matched
            del unmatched_data[key]
            print("[Unmatched] Removed matched channel: %s" % key)
        elif not matched:
            # Add or update unmatched
            timestamp = strftime('%Y-%m-%d %H:%M:%S', localtime())
            # Use provided sref or build fallback
            if sref is not None:
                fallback_sref = ensure_sref_trailing_colon(sref)
            else:
                fallback_sref = "%s:0:0:0:0:0:0:0:0:0:" % servicetype

            old_data = unmatched_data.get(key, {})
            attempts = old_data.get('attempts', 0) + 1

            unmatched_data[key] = {
                'id': key,
                'name': channel_name.strip(),
                'country': country_code or '',
                'sref': fallback_sref,
                'timestamp': timestamp,
                'matched': False,
                'attempts': attempts
            }
            print(
                "[Unmatched] Added/updated: %s (attempt #%d)" %
                (key, attempts))

        # Write complete file
        temp_file = UNMATCHED_FILE + ".tmp"
        with open(temp_file, 'w') as f:
            dump(unmatched_data, f, indent=4, sort_keys=True)
        rename(temp_file, UNMATCHED_FILE)

        print(
            "[Unmatched] Cache updated - total entries: %d" %
            len(unmatched_data))

    except Exception as e:
        print("[Unmatched] Error: %s" % e)


def write_epg_mapping_file(epg_entries, country_code):
    """
    Write the EPG mapping file for a specific country.
    epg_entries: list of tuples (rytec_id, dvb_ref, channel_name)
    """
    with _epg_lock:
        epg_dir = "/etc/epgimport"
        if not exists(epg_dir):
            makedirs(epg_dir)

        if country_code:
            filename = "vavoo_{}.channels.xml".format(country_code.lower())
        else:
            filename = "vavoo.channels.xml"
        channels_file = join(epg_dir, filename)

        # Use dvb_ref as key to avoid duplicates, but also store the channel
        # name
        unique = {}
        for epg_id, dvb_ref, ch_name in epg_entries:
            if dvb_ref and isinstance(dvb_ref, str) and dvb_ref.strip():
                if not dvb_ref.endswith(':'):
                    dvb_ref = dvb_ref + ':'
                unique[dvb_ref] = (epg_id, ch_name)

        if not unique:
            print("[EPG] No entries to write, skipping.")
            return None

        xml_lines = ['<?xml version="1.0" encoding="utf-8"?>', '<channels>']
        for dvb_ref, (epg_id, ch_name) in unique.items():
            # Add comment with channel name (optional but useful for
            # readability)
            xml_lines.append(
                '  <channel id="{}">{}</channel><!-- {} -->'.format(epg_id, dvb_ref, ch_name))
        xml_lines.append('</channels>')

        try:
            with open(channels_file, 'w') as f:  # 'encoding' arg removed for Py2 compatibility
                f.write('\n'.join(xml_lines))
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
        with open(sources_file, "w") as f:
            f.write(sources_xml)

        print(
            "[EPG] Sources file updated with %d entries." %
            len(sources_list))

    except Exception as e:
        print("[EPG] Error writing sources file: %s" % e)


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
            extra = set(value.keys()) - required
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
                from time import strftime, localtime
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
            with open(CACHE_FILE, 'w') as f:
                dump(
                    new_cache,
                    f,
                    indent=4,
                    sort_keys=True,
                    ensure_ascii=False)
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
