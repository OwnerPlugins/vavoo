#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import base64
import gzip
try:
    import requests
except ImportError:
    # requests is a hard runtime dependency (python3-requests, declared
    # in CONTROL/control) - VavooProxy is built directly on
    # requests.Session() and cannot function without it, but a clear
    # message here beats a bare traceback on images missing the package.
    print("[PROXY] FATAL: 'requests' package not found - install python3-requests")
    raise
import time
import threading
import socket
import select
try:
    import urllib3
except ImportError:
    urllib3 = None
import atexit
import os
import re
from json import loads, load, dumps

from . import (
    PORT,
    PROXY_HOST,
    PROXY_STATUS_URL,
    BASE_SITES,
    GEIL_SITES,
    GEIL_LIVE_PATH,
    GROUP_NAME_SEPARATORS,
    HOST_GIT,
    SOURCE_PREFS_FILE,
    SREF_MAP_FILE,
    __version__
)

from .vUtils import (
    _starting_lock,
    debug,
    decodeHtml,
    get_external_ip,
    is_proxy_running,
    log_exception,
    make_print,
    remove_parentheses,
    strip_control_chars,
    trace_error,
)


# Same convention vUtils.py already uses to read this plugin's own
# config (config.plugins.vavoo.*) without importing from plugin.py
# itself, which would be circular (plugin.py imports this module).
from Components.config import config as e2_config


try:
    unicode
except NameError:
    unicode = str

print = make_print("PROXY")


try:
    from urllib.parse import unquote, quote, urlparse, parse_qs
except ImportError:
    from urllib import unquote, quote
    from urlparse import urlparse, parse_qs

# Python 2/3 compatibility for exception names used in handlers
try:
    BrokenPipeError
except NameError:  # Python 2
    BrokenPipeError = IOError
try:
    ConnectionResetError
except NameError:  # Python 2
    ConnectionResetError = IOError
try:
    ConnectionError
except NameError:  # Python 2
    ConnectionError = IOError

# Global stop flag used for clean shutdown (prevents restart loop)
STOP_EVENT = threading.Event()
# NOTE: do NOT call socket.setdefaulttimeout() globally – it poisons
# streaming sockets and all other network ops in the same process.

try:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    print(" Python 2 detected")
except ImportError:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    print(" Python 3 detected")


# Threaded HTTP server (prevents one streaming client from blocking others)
try:
    # Py3
    from socketserver import ThreadingMixIn
except ImportError:
    # Py2
    from SocketServer import ThreadingMixIn


# Disable SSL warnings
if urllib3 is not None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    # listen() backlog. Must be a class attribute: the socket starts
    # listening inside __init__, so assigning it on the instance
    # afterwards (as start_proxy() used to) changed nothing and left
    # the default of 5 - connections arriving in a burst beyond that
    # are silently dropped by the kernel and only retried by the
    # client seconds later.
    request_queue_size = 64


"""
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin                             #
#  Created by Lululla (https://github.com/Belfagor2005) #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0    #
#  Last Modified: 202600503                              #
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

# ========== CONFIGURATIONS ==========


"""
====================================================================
VAVOO PROXY API HELP
====================================================================

Proxy Base URL:
    http://127.0.0.1:4323

All endpoints are accessible locally from:
    - Enigma2
    - wget
    - curl
    - VLC
    - ffplay
    - IPTV players

====================================================================
1. /status - Proxy Status
====================================================================

URL:
    http://127.0.0.1:4323/status

Description:
    Returns current proxy runtime status.

Includes:
    - proxy initialization state
    - loaded channels count
    - addonSig validity
    - addonSig age
    - local IP address
    - listening port

Example:
    wget -qO- http://127.0.0.1:4323/status

Example Response:
{
    "initialized": true,
    "channels_count": 1250,
    "catalog_source": "geil",
    "token_required": false,
    "addon_sig_valid": true,
    "addon_sig_age": 42,
    "local_ip": "192.168.1.10",
    "port": 4323
}


====================================================================
2. /health - Health Check
====================================================================

URL:
    http://127.0.0.1:4323/health

Description:
    Returns detailed health and monitoring information.

Includes:
    - overall health status
    - token validity
    - token TTL
    - uptime
    - heartbeat age
    - local IP
    - listening port

Important:
    This endpoint is READ-ONLY.
    It does NOT restart or refresh the proxy.

Example:
    wget -qO- http://127.0.0.1:4323/health


====================================================================
3. /countries - Available Countries
====================================================================

URL:
    http://127.0.0.1:4323/countries

Description:
    Returns all unique countries available in the catalog.

Excluded:
    - empty country names
    - "default"

Example:
    wget -qO- http://127.0.0.1:4323/countries

Example Response:
[
    "France",
    "Germany",
    "Italy",
    "Spain"
]


====================================================================
4. /channels?country=CountryName - Channels By Country
====================================================================

URL:
    http://127.0.0.1:4323/channels?country=Italy

Description:
    Returns all channels matching the specified country.

Each channel contains:
    - id
    - name
    - logo
    - country
    - local playback URL

Notes:
    - country matching is case-insensitive
    - country names should be URL encoded

Example:
    wget -qO- "http://127.0.0.1:4323/channels?country=Italy"

Example Response:
[
    {
        "id": "abc123",
        "name": "RAI 1",
        "url": "http://192.168.1.10:4323/vavoo?channel=abc123",
        "logo": "https://logo.png",
        "country": "Italy"
    }
]


====================================================================
5. /catalog - Full Catalog
====================================================================

URL:
    http://127.0.0.1:4323/catalog

Description:
    Returns the complete filtered catalog currently loaded
    in memory.

Contains:
    - all channels
    - metadata
    - original stream information

Example:
    wget -qO- http://127.0.0.1:4323/catalog


====================================================================
6. /vavoo?channel=ChannelID - Stream Redirect
====================================================================

URL:
    http://127.0.0.1:4323/vavoo?channel=abc123

Description:
    Resolves the upstream stream URL and immediately returns
    a HTTP 302 redirect.

Optimized for:
    - Enigma2 IPTV bouquets
    - VLC
    - ffplay
    - gstplayer
    - exteplayer3
    - serviceapp

Behavior:
    Client receives direct upstream stream URL.

    Players come back here on every playlist refresh (about every
    10 seconds while a channel is watched), so the answer stays the
    same address for as long as it keeps being asked for, and is
    forgotten 45 seconds after the last request. A channel with
    several sources ("grp:<country>:<name>" ids) stays on one source
    the same way. Takes no other parameters.

Example:
    wget -S -O /dev/null "http://127.0.0.1:4323/vavoo?channel=abc123"

Expected Response:
    HTTP/1.1 302 Found


====================================================================
6b. /group_sources?group=GroupID - Sources Of One Channel
====================================================================

URL:
    http://127.0.0.1:4323/group_sources?group=grp%3Aitaly%3Arai%201

Description:
    Lists the individual sources of a multi-source channel and which
    one is in use. Read-only.

Example Response:
{
    "members": [
        {"id": "abc123", "label": "RAI 1 .b"},
        {"id": "def456", "label": "RAI 1 HD .s"}
    ],
    "current": "abc123"
}


====================================================================
7. /stream?ref=ServiceReference - Direct Stream Proxy
====================================================================

URL:
    http://127.0.0.1:4323/stream?ref=1%3A0%3A1%3A...

Description:
    Streams MPEG-TS content directly through the proxy
    instead of redirecting the client.

Features:
    - upstream buffering
    - keep-alive
    - timeout monitoring
    - chunked streaming
    - disabled caching

Workflow:
    1. Decode service reference
    2. Map reference to channel ID
    3. Resolve upstream stream
    4. Proxy TS stream to client

Recommended for:
    - Enigma2 service references
    - local TS proxying
    - IPTV middleware
    - transcoding pipelines

Example:
    ffplay "http://127.0.0.1:4323/stream?ref=1%3A0%3A1%3A..."


====================================================================
8. /refresh_token - Refresh addonSig
====================================================================

URL:
    http://127.0.0.1:4323/refresh_token

Description:
    Forces addonSig token refresh.

Returns:
    - success
    - error

Example:
    wget -qO- http://127.0.0.1:4323/refresh_token

Example Response:
{
    "status": "success",
    "message": "Token refreshed"
}


====================================================================
9. /epg/<country>.xml - EPG Redirect
====================================================================

URL:
    http://127.0.0.1:4323/epg/it.xml

Description:
    Redirects to XMLTV EPG file hosted on GitHub.

Examples:
    /epg/it.xml
    /epg/fr.xml
    /epg/de.xml

Response:
    HTTP 302 Redirect

Example:
    wget -O epg.xml "http://127.0.0.1:4323/epg/it.xml"


====================================================================
10. /shutdown - Graceful Shutdown
====================================================================

URL:
    http://127.0.0.1:4323/shutdown

Description:
    Gracefully shuts down the proxy server.

Behavior:
    - stops HTTP server
    - closes sockets
    - stops proxy threads
    - sets global stop event

Example:
    wget -qO- http://127.0.0.1:4323/shutdown


====================================================================
USEFUL ENIGMA2 TEST COMMANDS
====================================================================

Check proxy status:
    wget -qO- http://127.0.0.1:4323/status

Check health:
    wget -qO- http://127.0.0.1:4323/health

List countries:
    wget -qO- http://127.0.0.1:4323/countries

Get Italy channels:
    wget -qO- "http://127.0.0.1:4323/channels?country=Italy"

Check redirect:
    wget -S -O /dev/null "http://127.0.0.1:4323/vavoo?channel=abc123"

Check listening port:
    netstat -lntp | grep 4323

or:
    ss -lntp | grep 4323
====================================================================
"""

# API Endpoints
TOKEN_ADDON_SIG = 600  # 10 minutes - TOKEN EXPIRES EVERY 10 MINUTES!
TOKEN_REFRESH_AGE = 480
GEOIP_URL = "https://www.vavoo.tv/geoip"
PING_URL = "https://www.vavoo.tv/api/app/ping"
PING_URL2 = "https://www.vypn.net/api/app/ping"
# Real VYPN app identity (package/version from its APK metadata),
# matching a confirmed-working ping payload for this endpoint.
VYPN_PACKAGE = "net.vypn.app"
VYPN_VERSION = "1.4.1"
PID_FILE = "/tmp/vavoo_proxy.pid"
BOOTING_FILE = "/tmp/vavoo_proxy_booting"

# Primary + mirror. Some regions get HTTP 451 from the primary.

# NOTE: do NOT set "Connection": "close" here - self.session.headers is
# applied to every request through this session (catalog pages, resolve
# calls, and the /stream handler's upstream GET), so it would force a
# fresh TCP/TLS handshake on all of them instead of reusing a pooled
# connection from the HTTPAdapter configured below.
HEADERS = {
    "accept": "*/*",
    "user-agent": "MediaHubMX/2",
    "Accept-Language": "de",
    "Accept-Encoding": "gzip, deflate",
}


# Ceiling on how long a "booting" marker is trusted. A crash, power loss,
# or plugin/box restart during boot can leave this file behind forever;
# without a staleness check every later start would think a boot is
# permanently in progress. A normal catalog load is usually well under a
# minute, but this needs to stay above the worst case, not the normal
# case: load_catalog()'s retry loop alone can spend up to ~90s x 3
# attempts on a single stalled page before giving up on it and moving on,
# and a failed initialize_proxy() is retried up to 3 times
# (start_proxy()'s max_restarts) before the boot gives up entirely. 180s
# was tight enough that a real (not crashed) boot stuck retrying a couple
# of slow/451-blocked pages could cross it - making a second,
# concurrently-starting instance see the marker as stale and start
# booting too, racing the still-legitimately-running first one.
MAX_BOOT_AGE = 300


def is_proxy_booting():
    """Check if another proxy instance is currently starting up.

    Treats the marker as stale (and removes it) if it is older than
    MAX_BOOT_AGE seconds, so a leftover file from a crashed process can't
    make every future start think a boot is still running.
    """
    if not os.path.exists(BOOTING_FILE):
        return False
    try:
        age = time.time() - os.path.getmtime(BOOTING_FILE)
    except OSError:
        return False
    if age > MAX_BOOT_AGE:
        print("[PROXY] Stale booting marker ({}s old), removing".format(int(age)))
        remove_booting_file()
        return False
    return True


def write_booting_file():
    with open(BOOTING_FILE, 'w') as f:
        f.write(str(os.getpid()))


def remove_booting_file():
    try:
        os.unlink(BOOTING_FILE)
    except OSError:
        # Already gone - nothing to do.
        pass


def decode_response(resp):
    """Decode gzip response if needed (Py2/3 compatible)."""
    if resp.content[:2] == b'\x1f\x8b':
        # gzip.decompress is Py3.2+ only; use GzipFile for Py2 compat
        try:
            raw = gzip.decompress(resp.content)
        except AttributeError:
            import io as _io
            with gzip.GzipFile(fileobj=_io.BytesIO(resp.content)) as gz:
                raw = gz.read()
        return loads(raw.decode('utf-8', 'ignore'))
    try:
        return resp.json()
    except ValueError:
        return loads(resp.content.decode('utf-8', 'ignore'))


# Vavoo's catalog still names logo.huhu.to for channel pictures, which
# no longer answers (https refused, http an empty image) - the same
# pictures are actually served by vavoo.to under /live2/logo/<n>.png,
# the same relative path geil.to gives directly for its own channels.
# Ported from the companion Android app's ChannelLogos.fix() - applied
# uniformly to every channel regardless of which catalog loaded it, so
# picons work the same way on both the geil.to default and the Vavoo
# fallback.
_HUHU_LOGO_RE = re.compile(r'^https?://logo\.huhu\.to/logo\?c=(\d+)\.png$')


def fix_logo_url(url):
    if not url:
        return url
    m = _HUHU_LOGO_RE.match(url)
    if m:
        return "https://vavoo.to/live2/logo/%s.png" % m.group(1)
    if url.startswith("/live2/logo/"):
        return "https://vavoo.to" + url
    return url


# geil.to numbers a channel's alternate sources with a trailing
# "(N)" (e.g. "RAI 1 (1)"); Vavoo's own catalog tags the same idea
# with a per-source letter suffix instead (e.g. "RAI 1 .b" - see
# channel_alias.py/epg_name_utils.py's _VAVOO_SUFFIX_RE, which strips
# exactly this ".X" pattern during EPG name matching). Left
# unconverted, a geil channel's "(1)" survives into every display
# and into EPG matching, where it's not recognized as a source
# suffix at all. Ported from the companion Android app's
# CatalogParser.geilName() - same source-number -> Vavoo-letter
# mapping, so the same channel keeps the same base name (and so
# favourites/EPG matches) regardless of which catalog it came from.
_GEIL_SOURCE_RE = re.compile(r'\s*\((\d{1,2})\)$')
_GEIL_SOURCE_TAGS = {"1": "b", "6": "c", "7": "s"}


def fix_geil_name(name):
    if not name:
        return name
    # _GEIL_SOURCE_RE anchors on $ (end of string) - match against a
    # right-stripped copy so a trailing space (a plausible artifact of
    # scraped/externally-sourced catalog text) doesn't silently defeat
    # the whole suffix-stripping step.
    stripped = name.rstrip()
    m = _GEIL_SOURCE_RE.search(stripped)
    if not m:
        return name
    tag = _GEIL_SOURCE_TAGS.get(m.group(1), m.group(1))
    return stripped[:m.start()].rstrip() + " ." + tag


# Channel grouping (like the companion Android app's "group sources"
# option): several catalog entries are really the same channel from
# different sources, distinguished only by a trailing Vavoo-style
# ".b"/".c"/".s" suffix (geil.to's own "(N)" suffix is already
# normalized to match this by fix_geil_name() above), or a genuine
# quality/backup variant of the exact same feed. /channels folds every
# source sharing the same _group_key() into one row, addressed by a
# synthetic "grp:<country>:<key>" id instead of a single catalog id -
# see resolve_group_with_retry() for how /vavoo resolves that into an
# actual source's stream.
#
# Deliberately NOT epg_name_utils.clean_name_for_similarity() - that
# function is tuned for *fuzzy EPG matching* (tolerant of noise by
# design) and strips "ITA"/"PLUS"/"TIMVISION" as if they were pure
# quality tags. For EPG matching that tolerance is fine; for grouping
# it is not - those words mark a genuinely different channel/feed
# (a language dub, a separately-branded sibling, a different IPTV
# rebrand), not just another source of the same one. Reusing it here
# caused real catalog pairs like "Comedy Central" + "Comedy Central
# Plus" or "Discovery Channel" + "Discovery Channel ITA" to collapse
# into a single row, silently stranding whichever channel didn't win
# resolve_group_with_retry()'s first-success pick. This stricter key
# only strips what the Vavoo/geil.to source-suffix convention itself
# adds (the suffix, [..]/(..) annotations) plus genuine quality/backup
# variants (HD/FHD/UHD/SD/4K/HEVC/H265/BACKUP, looped so "X HD BACKUP"
# still fully collapses to "X") - nothing that could itself be part of
# a real channel's name.
GROUP_ID_PREFIX = "grp:"
# How many times a grouped channel's CURRENT source is retried (with a
# fresh address) after the player reports a failure, before
# report_stream_failure() gives up on it and moves to a different
# source - see that method's own docstring.
GROUP_SAME_SOURCE_RETRIES = 1
# Failure reports for the same grouped channel closer together than
# this (seconds) count as one incident and add up towards
# GROUP_SAME_SOURCE_RETRIES; a report after a longer healthy stretch
# starts counting from 1 again.
GROUP_FAILURE_WINDOW = 60
# A source report_stream_failure() just gave up on is tried last for
# this long (seconds), then goes back to its normal place.
GROUP_AVOID_SECONDS = 300
# How long a resolved stream address is kept after the LAST request
# for it (seconds) - an idle timeout, not an age. See
# VavooProxy.resolve_with_retry()'s own docstring for why.
RESOLVE_IDLE_TTL = 45
# Same pattern used both to compute the grouping KEY (_group_key(),
# via this name) and to strip the suffix for DISPLAY
# (_strip_source_suffix()) - one constant, not two, so a future tweak
# to "what counts as a source suffix" can't apply to one and silently
# not the other.
_GROUP_SUFFIX_RE = re.compile(r'\s+\.[A-Za-z0-9]{1,3}$')
_SOURCE_DISPLAY_SUFFIX_RE = _GROUP_SUFFIX_RE
_GROUP_BRACKETS_RE = re.compile(r'\[[^\]]*\]')
_GROUP_PARENS_RE = re.compile(r'\([^)]*\)')
_GROUP_QUALITY_RE = re.compile(
    r'\s+(HD|FHD|UHD|SD|4K|HEVC|H265|BACKUP)$', re.IGNORECASE)
_GROUP_NON_WORD_RE = re.compile(r'[^\w ]', re.UNICODE)
_GROUP_MULTI_SPACE_RE = re.compile(r'\s+')
# geil.to's and Vavoo's own catalogs both separate a channel's full
# "group" label into country/category with one of these - shared by
# load_catalog() and load_geil_catalog() (see _base_country_from_group()).
# GROUP_NAME_SEPARATORS (__init__.py) is the one shared copy of this
# list, imported everywhere a country/category or bouquet name needs
# splitting the same way, instead of each module keeping its own
# literal (which had already drifted out of sync - see its own
# comment).
_GROUP_SEPARATORS = GROUP_NAME_SEPARATORS


def _base_country_from_group(group):
    """The country portion of a catalog item's "group" label (e.g.
    "Italy ➾ Sport" -> "Italy"), or "default" if nothing recognizable
    is there. Shared by load_catalog() and load_geil_catalog() - was
    two separately-maintained copies of the same split/strip logic
    (one of which rebuilt the separators tuple on every single catalog
    item instead of once)."""
    base_country = group
    for sep in _GROUP_SEPARATORS:
        if sep in base_country:
            base_country = base_country.split(sep)[0].strip()
            break
    return base_country or "default"


def _group_key(name):
    """Grouping key: same key = sources of the same channel. Empty
    when nothing recognizable is left (never grouped with another
    empty-key channel - see /channels' own handling of that case)."""
    if not name:
        return ""
    n = _GROUP_MULTI_SPACE_RE.sub(' ', name).strip().upper()
    n = _GROUP_BRACKETS_RE.sub(' ', n)
    n = _GROUP_PARENS_RE.sub(' ', n).strip()
    n = _GROUP_SUFFIX_RE.sub('', n).strip()
    while True:
        stripped = _GROUP_QUALITY_RE.sub('', n).strip()
        if stripped == n:
            break
        n = stripped
    n = n.replace('+', ' PLUS ')
    n = _GROUP_NON_WORD_RE.sub('', n)
    return _GROUP_MULTI_SPACE_RE.sub(' ', n).strip().lower()


def _strip_source_suffix(name):
    """Trailing source-variant suffix stripped for DISPLAY - unlike
    _group_key(), this keeps everything else about the name as-is
    (case, spacing, quality tags), since it's what a channel list
    row/EPG actually shows."""
    if not name:
        return name
    return _SOURCE_DISPLAY_SUFFIX_RE.sub('', name).strip()


def make_group_id(country, key):
    return GROUP_ID_PREFIX + (country or "").lower() + ":" + key


def _source_label(member, index):
    """Label for one source of a grouped channel in the player's
    source menu (plugin.py's chooseStreamSource()) and /group_sources:
    that source's own catalog name, exactly as the channel list showed
    it before sources were folded into one row (e.g. "RAI 1 .b",
    "RAI 1 HD .s") - same as the companion Android app's menu. Used to
    be a made-up "Source B"/"Source S", which hid the one thing that
    tells sources apart at a glance (HD/FHD and the like). A plain
    1-based "Source N" only for an entry with no name at all."""
    name = (member.get("name", "") or "").strip()
    if name:
        return name
    return "Source {}".format(index + 1)


def _unique_source_labels(members):
    """_source_label() for every member, in order, made unique: when
    two sources of a channel carry exactly the same name, the later
    ones get " (2)", " (3)" so they can still be told apart in the
    menu."""
    labels = []
    seen = {}
    for index, member in enumerate(members):
        label = _source_label(member, index)
        count = seen.get(label, 0) + 1
        seen[label] = count
        if count > 1:
            # "+", not str.format(): on Python 2 the name is unicode,
            # and "{}".format(u"...") fails on any non-ASCII character.
            label = label + " (%d)" % count
        labels.append(label)
    return labels


def parse_group_id(group_id):
    """("italy", "rai 1") from "grp:italy:rai 1", or (None, None) if
    group_id isn't one of ours."""
    if not group_id or not group_id.startswith(GROUP_ID_PREFIX):
        return None, None
    rest = group_id[len(GROUP_ID_PREFIX):]
    if ":" not in rest:
        return None, None
    country, key = rest.split(":", 1)
    return country, key


def _load_source_prefs():
    """The user's saved per-channel source picks from
    SOURCE_PREFS_FILE ({group id: member id}), or {} if there are none
    yet or the file can't be read - a missing/broken file only means
    "no picks", never an error."""
    try:
        with open(SOURCE_PREFS_FILE, 'r') as f:
            data = load(f)
    except (IOError, OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return dict((k, v) for k, v in data.items() if k and v)


def _rewrite_addon_sig_ip(sig, client_ip):
    """Rewrite the client IP embedded inside a base64-encoded addonSig.

    The token is base64(JSON) where the JSON has a "data" field that is
    itself a JSON string carrying an "ips"/"ip" pair. Point those at our
    own public IP so the resolved stream matches where our requests
    actually come from, matching a confirmed-working reference
    implementation. Falls back to the original, unmodified sig if the
    token doesn't have the expected shape.
    """
    try:
        padded = sig + '=' * (-len(sig) % 4)
        decoded = base64.b64decode(padded)
        if isinstance(decoded, bytes):
            decoded = decoded.decode('utf-8')
        sig_obj = loads(decoded)
        if not isinstance(sig_obj, dict) or "data" not in sig_obj:
            return sig

        data_obj = loads(sig_obj["data"])
        current_ips = data_obj.get("ips")
        if not isinstance(current_ips, list):
            current_ips = []
        data_obj["ips"] = [client_ip] + \
            [ip for ip in current_ips if ip and ip != client_ip]
        if isinstance(data_obj.get("ip"), (str, unicode)):
            data_obj["ip"] = client_ip

        sig_obj["data"] = dumps(data_obj)
        new_sig = base64.b64encode(dumps(sig_obj).encode('utf-8'))
        if isinstance(new_sig, bytes):
            new_sig = new_sig.decode('ascii')
        return new_sig
    except Exception as e:
        print("[AddonSig] IP rewrite failed, keeping original sig: {}".format(e))
        return sig


def is_proxy_already_running():
    """Check if another proxy instance is running via PID file"""
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
            # Check if process exists
            os.kill(pid, 0)
            return True
    except (IOError, OSError, ValueError):
        return False
    except Exception as e:
        print(str(e))
        log_exception("is_proxy_already_running error", area="PROXY")
        return False


def write_pid_file():
    """Write current PID to file"""
    try:
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        return True
    except Exception:
        return False


def remove_pid_file():
    """Remove PID file on exit"""
    try:
        if os.path.exists(PID_FILE):
            os.unlink(PID_FILE)
    except Exception:
        pass


atexit.register(remove_pid_file)


class VavooProxy(object):
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

        # 1. ADAPTER IMPROVED: more intelligent retries
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,
            pool_maxsize=20,
            max_retries=2,
            pool_block=False
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        self.session.verify = False
        self.session.timeout = 60
        self.session.stream = True

        # 2. REPLACE request wrapper with safer version
        self.session.request = self._robust_request

        self.active_streams = 0
        self._stream_lock = threading.Lock()  # guards active_streams counter
        self.addon_sig_data = {"sig": None, "ts": 0}
        self.addon_sig_lock = threading.Lock()
        self.all_filtered_items = []
        # Keyed by country.lower() (catalog casing varies) - was built
        # but never actually read by anything; now used by /channels
        # and /playlist.m3u (see do_GET()) to answer a "channels in
        # this one country" query in O(channels-in-that-country)
        # instead of scanning the entire multi-country catalog.
        self.channels_by_country = {}
        self.channels_by_id = {}
        # (country.lower(), _group_key(name)) -> its member channels -
        # built once alongside the above, read by _group_members().
        # Safe to fully precompute: initialize_proxy() (which builds
        # all of these) only ever runs once at startup, never again
        # for the life of the process.
        self._group_members_cache = {}
        self.countries_list = []
        self.current_language = "en"
        self.current_region = "US"
        self.external_ip = None
        self.initialized = False
        self.last_heartbeat = time.time()
        self.local_ip = None
        # channel_url -> {"url": resolved stream address, "ts": when
        # it was last asked for} - see resolve_with_retry().
        self.resolve_cache = {}
        self.resolve_cache_lock = threading.Lock()
        # In-flight resolve markers (channel_url -> threading.Event),
        # guarded by resolve_cache_lock - lets a second concurrent
        # cache-miss request for the SAME channel wait for the first
        # request's network resolve instead of also hitting the network
        # itself ("thundering herd" on popular channels).
        self._resolve_inflight = {}
        self.resolve_cache_ttl = RESOLVE_IDLE_TTL
        self.server = None
        self.start_time = time.time()

        # Stop flag for background workers
        self._stop_event = threading.Event()
        self._token_monitor_thread = None

        # Mirror-aware endpoints
        self.base_sites = list(BASE_SITES)
        self.base_site_index = 0
        self._update_endpoints()

        # geil.to (and its mirrors): same kind of IPTV catalog, no
        # addonSig/token step - tried first in initialize_proxy(),
        # with base_sites above as the fallback catalog source. Which
        # one actually ended up loading the current catalog is tracked
        # in catalog_source ("geil"/"vavoo") so resolve_with_retry()
        # knows which API to resolve a channel's stream through,
        # without needing to sniff each channel's url.
        self.geil_sites = list(GEIL_SITES)
        self.geil_site_index = 0
        self.catalog_source = "vavoo"

        # Per grouped (multi-source) channel, guarded by group_lock:
        # group_id -> {"member": id of the source it is playing from,
        # "failures"/"failed_at": the current run of failure reports,
        # "avoid": {member id: when it was given up on}} - see
        # resolve_group_with_retry() and report_stream_failure().
        self._group_state = {}
        self.group_lock = threading.Lock()
        # group_id -> the source the user picked for it (YELLOW in the
        # player), kept on disk so it survives a restart - see
        # set_group_source(). Also guarded by group_lock; the file
        # itself by _group_pins_file_lock.
        self._group_pins = _load_source_prefs()
        self._group_pins_file_lock = threading.Lock()

        # Start lightweight token monitor only
        self.start_token_monitor()
        print(" Initialized at " + time.ctime())

    def stream_started(self):
        with self._stream_lock:
            self.active_streams += 1
            count = self.active_streams
        print("[Proxy] Stream started. Active streams: {}".format(count))

    def stream_ended(self):
        with self._stream_lock:
            if self.active_streams > 0:
                self.active_streams -= 1
            count = self.active_streams
        print("[Proxy] Stream ended. Active streams: {}".format(count))

    def _update_endpoints(self):
        """Update API endpoints from the current base site."""
        base = self.base_sites[self.base_site_index].rstrip('/')
        self.catalog_url = base + "/mediahubmx-catalog.json"
        self.resolve_url = base + "/mediahubmx-resolve.json"

    def _switch_to_next_base(self, reason=""):
        """Switch to next mirror base site."""
        if not self.base_sites:
            return
        old = self.base_sites[self.base_site_index]
        self.base_site_index = (self.base_site_index +
                                1) % len(self.base_sites)
        self._update_endpoints()
        new = self.base_sites[self.base_site_index]
        print(
            " Switching base site: {0} -> {1} {2}".format(old, new, reason))

    def geil_base(self):
        """Current geil.to mirror (changes on _switch_to_next_geil())."""
        return self.geil_sites[self.geil_site_index]

    def _switch_to_next_geil(self, reason=""):
        """Switch to the next geil.to mirror - same idea as
        _switch_to_next_base(), separate list/index since geil.to's
        mirrors and Vavoo's are two unrelated services."""
        if not self.geil_sites:
            return
        old = self.geil_sites[self.geil_site_index]
        self.geil_site_index = (self.geil_site_index +
                                1) % len(self.geil_sites)
        new = self.geil_sites[self.geil_site_index]
        print(
            " Switching geil mirror: {0} -> {1} {2}".format(old, new, reason))

    def _robust_request(self, method, url, **kwargs):
        """Simplified and safer version"""
        # Set reasonable timeouts
        if 'timeout' not in kwargs:
            kwargs['timeout'] = (5, 15)  # 5s connect, 15s read

        try:
            # SINGLE REQUEST, no infinite retries
            # Call the real Session.request, bypassing our override to avoid
            # recursion
            response = requests.Session.request(
                self.session, method, url, **kwargs)
            return response
        except (requests.exceptions.Timeout, socket.timeout) as e:
            print(" Timeout on " + str(url) + ": " + str(e))
            raise
        except requests.exceptions.ConnectionError as e:
            print(" Connection error on " + str(url) + ": " + str(e))
            raise
        except Exception as e:
            print(" Error on " + str(url) + ": " + str(e))
            raise

    def start_token_monitor(self):
        """Monitor token age with minimal background traffic"""
        def token_monitor_loop():
            while not self._stop_event.is_set():
                # Check FIRST, then sleep (first check is immediate at startup)
                try:
                    now = time.time()
                    token_age = (now - self.addon_sig_data["ts"]
                                 if self.addon_sig_data["sig"] else 0)
                    if self.addon_sig_data["sig"] and token_age > TOKEN_REFRESH_AGE:
                        print(
                            "[Token Monitor] Token old ({}s), refreshing...".format(
                                int(token_age)))
                        self.refresh_addon_sig_if_needed(force=True)
                    self.last_heartbeat = now
                except Exception as e:
                    print("[Token Monitor] Error: " + str(e))

                # Sleep interval:
                #  - Streaming active → check every 30s (token must not expire mid-stream)
                #  - Idle            → check every 60s
                with self._stream_lock:
                    streaming = self.active_streams > 0
                if streaming:
                    self._stop_event.wait(30)
                else:
                    self._stop_event.wait(60)

        self._token_monitor_thread = threading.Thread(
            target=token_monitor_loop)
        self._token_monitor_thread.setDaemon(True)
        self._token_monitor_thread.start()
        print(" Token monitor started")

    def _get_cached_external_ip(self):
        """Public IP of this box, cached for the process lifetime.

        Used to rewrite the IP embedded in the addonSig token so it
        matches where our actual resolve/stream requests come from,
        instead of whatever the ping endpoint saw or guessed.
        """
        if not self.external_ip:
            try:
                self.external_ip = get_external_ip()
            except Exception:
                self.external_ip = None
        return self.external_ip

    def refresh_addon_sig_if_needed(self, force=False):
        with self.addon_sig_lock:
            now = time.time()
            if not force and self.addon_sig_data["sig"] and (
                    now - self.addon_sig_data["ts"] < 300):
                return self.addon_sig_data["sig"]

            try:
                import uuid
                unique_id = str(uuid.uuid4())
                current_timestamp = int(time.time() * 1000)

                # Matches a confirmed-working VYPN ping payload exactly -
                # the previous version carried extra fields (buildId,
                # engine, signatures, installer, devMode=True, ...) copied
                # from an older reverse-engineered client that this
                # endpoint no longer accepts as a real free-tier client.
                payload = {
                    "token": "",
                    "reason": "app-focus",
                    "locale": self.current_language,
                    "theme": "dark",
                    "metadata": {
                        "device": {
                            "type": "phone",
                            "uniqueId": unique_id},
                        "os": {
                            "name": "android",
                            "version": "14",
                            "abis": ["arm64-v8a"],
                            "host": "android"},
                        "app": {
                            "platform": "android"},
                        "version": {
                            "package": VYPN_PACKAGE,
                            "binary": VYPN_VERSION,
                            "js": VYPN_VERSION}},
                    "appFocusTime": 0,
                    "playerActive": False,
                    "playDuration": 0,
                    "devMode": False,
                    "hasAddon": True,
                    "castConnected": False,
                    "package": VYPN_PACKAGE,
                    "version": VYPN_VERSION,
                    "process": "app",
                    "firstAppStart": current_timestamp - 86400000,
                    "lastAppStart": current_timestamp,
                    "ipLocation": None,
                    "adblockEnabled": True,
                    "migrationApplied": False,
                    "migrationTargetInstalled": False,
                    "proxy": {
                        "supported": ["ss"],
                        "engine": "Mu",
                        "ssVersion": "2022",
                        "enabled": False,
                        "autoServer": True,
                        "id": ""},
                    "iap": {
                        "supported": False,
                        "error": ""}}

                headers = {
                    "user-agent": "okhttp/4.11.0",
                    "accept": "application/json",
                    "content-type": "application/json; charset=utf-8",
                    "accept-encoding": "gzip",
                }

                # Try PING_URL (vavoo.tv) first, then PING_URL2 (vypn.net)
                urls = [PING_URL, PING_URL2]
                sig = None
                for url in urls:
                    try:
                        r = self.session.post(
                            url, json=payload, headers=headers, timeout=15)
                        if r.status_code == 200:
                            data = r.json()
                            sig = data.get("addonSig") or data.get("mhub")
                            if sig:
                                break
                            else:
                                print(
                                    "[AddonSig] No addonSig received from {}".format(url))
                    except Exception as e:
                        print(
                            "[AddonSig] Request to {} failed: {}".format(
                                url, e))
                        continue
                if sig:
                    client_ip = self._get_cached_external_ip()
                    if client_ip:
                        sig = _rewrite_addon_sig_ip(sig, client_ip)
                    self.addon_sig_data["sig"] = sig
                    self.addon_sig_data["ts"] = now
                    print("[AddonSig] Token obtained successfully")
                    return sig
                else:
                    print("[AddonSig] Unable to obtain token from any URL")
                    return None

            except Exception as e:
                print(" Error updating addonSig: " + str(e))
                if self.addon_sig_data["sig"]:
                    # Serving the stale token is still the right
                    # fallback (no token is worse), but make this
                    # visible in the log - there's no retry/backoff for
                    # this specific failure until the next regularly
                    # scheduled token_monitor_loop tick or the next
                    # force=True caller, so a token past Vavoo's
                    # 10-minute anonymous-block window could otherwise
                    # keep silently failing resolves in the meantime.
                    print(
                        "[AddonSig] WARNING: refresh failed, serving "
                        "possibly-stale token (age {}s)".format(
                            int(time.time() - self.addon_sig_data["ts"])))
                    return self.addon_sig_data["sig"]
                return None

    def initialize_proxy(self):
        """Initialize the proxy by loading the catalog: geil.to first
        (no addonSig/token step needed at all), Vavoo's sites
        (vavoo.to/kool.to) as the fallback catalog source when
        geil.to's whole catalog can't be loaded - same default/
        fallback order the companion Android app uses.

        This default/fallback order is itself overridable via
        config.plugins.vavoo.catalog_source ("auto" by default, or
        pinned to "geil"/"vavoo") - same config-read convention
        playlist_key already uses elsewhere in this module (see its
        own e2_config import comment). A pinned choice is respected
        as-is, with no fallback to the other source if it fails - an
        explicit preference shouldn't be silently overridden the same
        way "auto"'s best-effort fallback is.
        """
        try:
            print(" Initializing...")

            source_preference = "auto"
            try:
                source_preference = e2_config.plugins.vavoo.catalog_source.value
            except Exception as e:
                print(" Could not read catalog_source config: {}".format(e))

            if source_preference == "vavoo":
                print(" Catalog source pinned to Vavoo - skipping Geil")
                self.catalog_source = "vavoo"
                sig = self.refresh_addon_sig_if_needed()
                if not sig:
                    print(
                        " Warning: Could not get a valid token, but continuing anyway")
                print(" Attempting to load catalog...")
                all_channels = self.load_catalog(sig)
            else:
                print(" Attempting to load catalog from Geil (no token needed)...")
                all_channels = self.load_geil_catalog()
                if all_channels:
                    self.catalog_source = "geil"
                elif source_preference == "geil":
                    print(
                        " Catalog source pinned to Geil - not falling back to Vavoo")
                    self.catalog_source = "geil"
                else:
                    print(" Geil catalog unavailable, falling back to Vavoo")
                    self.catalog_source = "vavoo"

                    # First, obtain a valid token
                    sig = self.refresh_addon_sig_if_needed()
                    if not sig:
                        print(
                            " Warning: Could not get a valid token, but continuing anyway")
                        # We may continue with an old token or no token at all

                    # Load the catalog
                    print(" Attempting to load catalog...")
                    all_channels = self.load_catalog(sig)

            if not all_channels or len(all_channels) == 0:
                print(" Warning: Catalog is empty or failed to load")
                # Create an empty list but mark as initialized
                self.all_filtered_items = []
                self.channels_by_id = {}
                self.channels_by_country = {}
                self._group_members_cache = {}
                self.countries_list = []
                self.initialized = True
                print(" Initialized with empty catalog")
                return True

            self.all_filtered_items = all_channels
            self.channels_by_id = {}
            self.channels_by_country = {}
            self._group_members_cache = {}
            countries = set()
            for channel in all_channels:
                channel_id = channel.get("id")
                if channel_id:
                    self.channels_by_id[channel_id] = channel
                country = channel.get("country")
                if country:
                    country_lower = country.lower()
                    self.channels_by_country.setdefault(
                        country_lower, []).append(channel)
                    group_key = _group_key(channel.get("name", ""))
                    if group_key:
                        self._group_members_cache.setdefault(
                            (country_lower, group_key), []).append(channel)
                if country and country != "default":
                    countries.add(country)
            self.countries_list = sorted(list(countries))
            self.local_ip = self.get_local_ip(force_refresh=True)
            self.initialized = True

            # Analysis

            print(
                " ✓ Initialized: %d channels, %d countries" %
                (len(all_channels), len(countries))
            )
            return True

        except Exception as e:
            print(" Initialization error: %s" % str(e))
            # Even in case of error, try to continue with an empty catalog
            print(" Continuing with empty catalog")
            self.all_filtered_items = []
            self.channels_by_id = {}
            self.channels_by_country = {}
            self._group_members_cache = {}
            self.countries_list = []
            self.initialized = True
            return True  # Always return True; the proxy can work even without a catalog

    def _parse_geil_group(self, item):
        """geil.to's group comes as a tags array (first tag), not a
        bare 'group' string field like Vavoo's - everything after
        that (country/separator parsing) is identical."""
        tags = item.get("tags")
        if isinstance(tags, list) and tags:
            return tags[0] or ""
        return ""

    def load_geil_catalog(self):
        """Load the full IPTV catalog from geil.to (or a mirror) -
        same kind of catalog as Vavoo's, paginated by an opaque
        cursor, but with no addonSig/token step at all. Returns a
        list of channel dicts in the exact same shape load_catalog()
        produces ({country, id, name, url, logo, group}) so every
        downstream consumer (the /channels endpoint, bouquet_manager.py,
        M3U export...) needs no changes to work with either source.
        Returns None on total failure (every mirror tried, nothing
        usable) so initialize_proxy() knows to fall back to Vavoo."""
        headers = {
            "user-agent": "MediaHubMX/2",
            "accept": "application/json",
        }
        max_pages = 200
        max_retries = 3

        for _mirror_attempt in range(len(self.geil_sites)):
            base = self.geil_base().rstrip('/')
            all_channels = []
            cursor = None
            page = 1
            last_exception = None
            try:
                while page <= max_pages:
                    url = base + GEIL_LIVE_PATH + "/catalog/live/channels.json"
                    if cursor:
                        url += "?cursor=" + quote(cursor, safe='')

                    data = None
                    # Same "give up fast on an empty page, retry harder
                    # once there's already something" asymmetry the
                    # Android app uses - a dead mirror on page 1 should
                    # move on to the next mirror quickly, but losing a
                    # later page after the mirror proved itself working
                    # is worth a couple of retries rather than throwing
                    # away everything already downloaded.
                    attempts = 1 if not all_channels else max_retries
                    for attempt in range(attempts):
                        try:
                            r = self.session.get(
                                url, headers=headers, timeout=30)
                            r.raise_for_status()
                            data = r.json()
                            break
                        except Exception as e:
                            last_exception = e
                            print(
                                "[Geil] {0} page {1} attempt {2}/{3} "
                                "failed: {4}".format(
                                    base, page, attempt + 1, attempts, e))
                            if attempt < attempts - 1:
                                select.select([], [], [], 2 ** attempt)

                    if data is None:
                        if not all_channels:
                            raise last_exception or IOError(
                                "no channel list from " + base)
                        break

                    items = data.get("items") or []
                    if not items:
                        break

                    for item in items:
                        try:
                            channel_id = item.get("id")
                            url_field = item.get("url")
                            if not channel_id or not url_field:
                                continue
                            # /vavoo?channel=<id> always looks this id up
                            # as a string (it comes straight out of a URL
                            # query parameter) - if geil.to's JSON ever
                            # sends a numeric id, storing it unconverted
                            # here would key channels_by_id by an int,
                            # making every lookup from that endpoint miss
                            # even though the channel lists/browses fine
                            # (the /channels response just stringifies it
                            # into a URL, never round-trips it back).
                            channel_id = str(channel_id)
                            group = self._parse_geil_group(item)
                            base_country = _base_country_from_group(group)
                            # "images"/"ids" are only falsy-defaulted to
                            # {} - a present-but-non-dict value (a
                            # malformed/placeholder record a live
                            # third-party catalog can plausibly send)
                            # would raise AttributeError on .get() below
                            # and, uncaught, would abort this whole
                            # page/mirror instead of just this one item.
                            images = item.get("images")
                            ids = item.get("ids")
                            if not isinstance(images, dict):
                                images = {}
                            if not isinstance(ids, dict):
                                ids = {}
                            all_channels.append({
                                "country": base_country,
                                "id": channel_id,
                                "name": fix_geil_name(item.get("name", "")),
                                "url": url_field,
                                "logo": fix_logo_url(
                                    images.get("logo", "")),
                                "group": group,
                                # geil.to's own guide id for this channel,
                                # when it has one - checked directly
                                # against the country's own EPG feed index
                                # as a new highest-priority exact match in
                                # VavooEPGMatcher.find_match(), before the
                                # existing alias/cache/curated-DB/Rytec
                                # fuzzy-matching chain.
                                "epg_id": ids.get("tvg", "")
                            })
                        except Exception as e:
                            print(
                                "[Geil] Skipping malformed catalog item: {0}".format(e))
                            continue

                    cursor = data.get("nextCursor")
                    if not cursor:
                        break
                    page += 1
                    if page % 10 == 0:
                        select.select([], [], [], 0.1)

                # Same sanity floor the Android app uses - a handful of
                # channels means a broken/placeholder response, not a
                # real catalog; fall through to the next mirror instead
                # of accepting it.
                if len(all_channels) < 100:
                    raise IOError(
                        "only {0} channels from {1}".format(
                            len(all_channels), base))

                print(
                    "[Geil] Catalog loaded from {0}: {1} channels "
                    "({2} pages)".format(base, len(all_channels), page))
                return all_channels

            except Exception as e:
                print("[Geil] {0} failed: {1}".format(base, e))
                self._switch_to_next_geil("({0})".format(e))

        print("[Geil] All mirrors failed, no catalog")
        return None

    def load_catalog(self, sig):
        """Load the complete catalog with improved error handling including JSON decode errors."""
        try:
            catalog_headers = {
                "content-type": "application/json; charset=utf-8",
                "mediahubmx-signature": sig,
                "user-agent": "MediaHubMX/2",
                "accept": "*/*",
                "Accept-Language": self.current_language,
                "Accept-Encoding": "gzip, deflate",
                # Connection: close is intentional for short-lived catalog
                # requests
            }

            all_channels = []
            cursor = None
            page = 1
            max_retries = 3
            # Safety cap: real catalogs run to a few thousand channels /
            # a few dozen pages (300 items/page). Nothing should bound
            # this loop otherwise - a buggy or malicious upstream
            # response that kept returning a non-empty cursor forever
            # would keep it running indefinitely, since each page fetch
            # is a real network call that only stops the loop via an
            # empty items list/cursor, not a page count.
            max_pages = 200

            print("Loading catalog...")

            while page <= max_pages:
                catalog_payload = {
                    "language": self.current_language,
                    "region": self.current_region,
                    "catalogId": "iptv",
                    "id": "iptv",
                    "adult": False,
                    "search": "",
                    "sort": "",
                    "filter": {},
                    "cursor": cursor,
                    "clientVersion": "3.0.2"
                }

                success = False
                last_exception = None

                for attempt in range(max_retries):
                    try:
                        print(
                            "Fetching catalog page {0} (attempt {1}/{2})".format(page, attempt + 1, max_retries))

                        r_catalog = self.session.post(
                            self.catalog_url,
                            json=catalog_payload,
                            headers=catalog_headers,
                            timeout=90,
                            verify=False
                        )

                        # HTTP 451 -> immediately try next mirror. self.session
                        # defaults to stream=True (for the actual video-stream
                        # proxying path), so this response's body was never
                        # downloaded - closing it here returns the connection
                        # to the pool instead of leaving it dangling while we
                        # discard the Response object and retry/switch mirrors.
                        if r_catalog.status_code == 451:
                            r_catalog.close()
                            self._switch_to_next_base("(HTTP 451 on catalog)")
                            if attempt < max_retries - 1:
                                continue
                            # Last attempt on new mirror
                            try:
                                r_catalog = self.session.post(
                                    self.catalog_url,
                                    json=catalog_payload,
                                    headers=catalog_headers,
                                    timeout=30
                                )
                            except Exception as e:
                                print("Mirror fallback also failed: " + str(e))
                                break

                        if r_catalog.status_code == 502:
                            r_catalog.close()
                            print(
                                "502 Bad Gateway on page {0}, attempt {1}".format(
                                    page, attempt + 1))
                            if attempt < max_retries - 1:
                                select.select([], [], [], 2 ** attempt)
                                continue
                            else:
                                print(
                                    "Giving up on page {0} after {1} attempts".format(
                                        page, max_retries))
                                break

                        r_catalog.raise_for_status()

                        # ---------- JSON decode handling ----------
                        try:
                            catalog_data = r_catalog.json()
                        except ValueError as json_err:
                            print(
                                "JSON decode error on page {0}, attempt {1}: {2}".format(
                                    page, attempt + 1, json_err))

                            if attempt == max_retries - 1:
                                # last attempt -> switch base and retry page
                                self._switch_to_next_base(
                                    "(JSON decode error)")
                                break
                            else:
                                select.select([], [], [], 2 ** attempt)
                                continue
                        # ------------------------------------------

                        success = True
                        break

                    except requests.exceptions.HTTPError as e:
                        last_exception = e
                        print("HTTP error on page {0}: {1}".format(page, e))

                        if e.response is not None and e.response.status_code == 451:
                            self._switch_to_next_base(
                                "(HTTP 451 on catalog HTTPError)")
                            if attempt < max_retries - 1:
                                continue

                        if e.response is not None and e.response.status_code == 502 and attempt < max_retries - 1:
                            select.select([], [], [], 2 ** attempt)
                            continue
                        else:
                            break

                    except Exception as e:
                        last_exception = e
                        print("Error on page {0}: {1}".format(page, e))

                        if attempt < max_retries - 1:
                            select.select([], [], [], 2 ** attempt)
                            continue
                        else:
                            break

                if not success:
                    print(
                        "Failed to load page {0}, stopping catalog download".format(page))
                    if last_exception:
                        print("Last error: {0}".format(last_exception))
                    break

                items = catalog_data.get("items", [])
                if not items:
                    print("No more items on page {0}".format(page))
                    break

                items_processed = 0

                for item in items:
                    if item.get("type") == "iptv":
                        # Mirrors load_geil_catalog()'s per-item
                        # try/except - "id"/"name"/"url" are accessed
                        # with bracket notation (KeyError on a
                        # malformed item), and without this, one bad
                        # item used to raise out to the outer
                        # try/except and abort the whole catalog load
                        # (falling back to only whatever earlier pages
                        # had already collected) instead of just
                        # skipping that one item.
                        try:
                            group = item.get("group", "")
                            base_country = _base_country_from_group(group)

                            channel_data = {
                                "country": base_country,
                                "id": item["ids"]["id"],
                                "name": item["name"],
                                "url": item["url"],
                                "logo": fix_logo_url(item.get("logo", "")),
                                "group": group,
                                # Vavoo's own catalog has no separate guide
                                # id field the way geil.to's does - this
                                # key is always empty here, so
                                # find_match()'s new epg_guide_id check is
                                # a no-op on this path (falls straight
                                # through to the existing matching chain).
                                "epg_id": ""
                            }

                            all_channels.append(channel_data)
                            items_processed += 1
                        except Exception as e:
                            print(
                                "Skipping malformed catalog item: {0}".format(e))
                            continue

                print(
                    "Page {0}: processed {1} items, total {2} channels".format(
                        page, items_processed, len(all_channels)))

                cursor = catalog_data.get("nextCursor")

                if not cursor:
                    print("No more pages, catalog complete")
                    break

                page += 1

                if page % 10 == 0:
                    select.select([], [], [], 0.1)

            print(
                "Catalog loaded: {0} channels in {1} pages".format(
                    len(all_channels), page - 1))
            return all_channels

        except Exception as e:
            print("Catalog load error: %s" % str(e))
            trace_error()

            if all_channels:
                print(
                    "Returning {0} channels already loaded".format(
                        len(all_channels)))
                return all_channels

            return None

    def resolve_with_retry(
            self,
            channel_url,
            max_retries=2,
            force_refresh=False):
        """Resolve a channel's stream address, kept for as long as it
        keeps being asked for.

        Enigma2's players do not ask /vavoo once per viewing: /vavoo
        answers with a 302, so they come back here on every HLS
        playlist refresh, roughly every 10 seconds, for the whole time
        a channel is watched. Whatever this returns therefore has to
        stay the SAME address for the whole viewing - handing the
        player a different one in mid-play is what made streams stop.
        So the cache lifetime is an idle timeout (resolve_cache_ttl
        seconds since the LAST request - see _get_cached_url()), not
        an age: a stream being watched never expires, and one nobody
        is watching any more is forgotten almost at once. This used to
        be a fixed 300 seconds from the moment of resolving, which
        re-resolved every watched stream in mid-play every 5 minutes.

        A stream that actually failed is dropped explicitly instead -
        see invalidate_resolved() and report_stream_failure().

        force_refresh=True skips the cache read (still updates it with
        the fresh result below).
        """
        if not channel_url:
            print(" No channel URL provided")
            return None

        if not force_refresh:
            cached_url = self._get_cached_url(channel_url)
            if cached_url:
                return cached_url

        # Dedup concurrent resolves of the same channel_url on a cache
        # miss/expiry - two requests for the same popular channel (e.g.
        # a UI "browse" request and the player's actual playback request
        # for it) arriving together would otherwise both hit the
        # network. The first requester ("leader") does the real work;
        # concurrent requesters for the SAME url wait on its Event and
        # then read the cache entry it fills in, instead of resolving it
        # themselves. Requests for DIFFERENT channel urls are
        # unaffected - this only serializes per-url, never globally.
        is_leader = False
        with self.resolve_cache_lock:
            event = self._resolve_inflight.get(channel_url)
            if event is None:
                event = threading.Event()
                self._resolve_inflight[channel_url] = event
                is_leader = True

        if not is_leader:
            event.wait(30)  # bounded - never wait forever on a stuck leader
            cached_url = self._get_cached_url(channel_url)
            if cached_url:
                return cached_url
            # Leader's resolve failed or timed out - fall through and
            # try ourselves rather than giving up.

        try:
            return self._do_resolve_with_retry(channel_url, max_retries)
        finally:
            if is_leader:
                with self.resolve_cache_lock:
                    self._resolve_inflight.pop(channel_url, None)
                event.set()

    def _get_cached_url(self, channel_url):
        """The cached stream address for channel_url if it was asked
        for within the last resolve_cache_ttl seconds, else None.
        Finding it also marks it as just used - that is the whole
        mechanism that keeps a watched stream on one address (see
        resolve_with_retry()'s own docstring)."""
        now = time.time()
        with self.resolve_cache_lock:
            cached = self.resolve_cache.get(channel_url)
            if cached and (now - cached["ts"] < self.resolve_cache_ttl):
                cached["ts"] = now
                return cached["url"]
        return None

    def invalidate_resolved(self, channel_url):
        """Forget channel_url's cached stream address, so the next
        request for it resolves a fresh one."""
        with self.resolve_cache_lock:
            self.resolve_cache.pop(channel_url, None)

    def _group_members(self, country, key):
        """Every catalog entry that is a source of the channel group
        (country, key) - a direct lookup into _group_members_cache,
        precomputed once in initialize_proxy() (which only ever runs
        once per process, so this can never go stale). Used to be a
        full linear scan of all_filtered_items with a _group_key()
        regex call per entry, on every single tune-in/EOF-retry of a
        grouped channel - needlessly expensive for data that never
        changes after startup."""
        return self._group_members_cache.get(
            ((country or "").lower(), key), [])

    def _ordered_group_members(self, group_id, members):
        """members in the order resolve_group_with_retry() should try
        them: the source this group is already playing from first
        (never swap a working source for another), then the one the
        user picked, then catalog order - with any source
        report_stream_failure() gave up on in the last
        GROUP_AVOID_SECONDS at the very end, oldest failure first, so
        a run of failures rotates through every source instead of
        bouncing between the first two."""
        now = time.time()
        with self.group_lock:
            state = self._group_state.get(group_id) or {}
            current = state.get("member")
            avoid = dict(state.get("avoid") or {})
            pin = self._group_pins.get(group_id)

        def sort_key(item):
            index, member = item
            member_id = member.get("id")
            failed_at = avoid.get(member_id, 0)
            recently_failed = bool(failed_at) and (
                now - failed_at) < GROUP_AVOID_SECONDS
            if member_id == current:
                rank = 0
            elif recently_failed:
                rank = 3
            elif member_id == pin:
                rank = 1
            else:
                rank = 2
            return (rank, failed_at if recently_failed else 0, index)

        return [member for _index, member in sorted(
            enumerate(members), key=sort_key)]

    def resolve_group_with_retry(self, group_id):
        """Resolve a grouped channel (a "grp:<country>:<key>" id - see
        /channels and make_group_id()/parse_group_id()) to the stream
        address of one of its sources.

        Called on every /vavoo request for the group, i.e. on every
        playlist refresh of a stream that is being watched (see
        resolve_with_retry()'s own docstring) - so it must keep
        answering with the SAME source. It remembers which source the
        group is playing from and always tries that one first; as long
        as that source's address is still cached this is one dict
        lookup and no network at all. A different source is only ever
        chosen when there is no current one yet (first tune-in), when
        the user picks one (set_group_source()), or when the player
        reported the current one as failed often enough
        (report_stream_failure()).

        Earlier versions took the "this is a retry"/"keep the
        source"/"use this source" decisions as force=1/keep=1/source=
        query parameters on /vavoo itself. Since the player repeats
        the whole address on every refresh, those one-off instructions
        were repeated every ~10 seconds for the rest of the viewing -
        re-resolving constantly and hopping between sources in
        mid-play."""
        country, key = parse_group_id(group_id)
        if not key:
            return None
        members = self._group_members(country, key)
        if not members:
            return None

        for member in self._ordered_group_members(group_id, members):
            stream_url = self.resolve_with_retry(member.get("url"))
            if not stream_url:
                continue
            member_id = member.get("id")
            with self.group_lock:
                state = self._group_state.setdefault(group_id, {})
                changed = state.get("member") != member_id
                if changed:
                    state["member"] = member_id
                    state["failures"] = 0
            if changed:
                print("[Proxy] {0} now playing from source {1}".format(
                    group_id, member_id))
            return stream_url
        return None

    def report_stream_failure(self, channel_id):
        """The player's side of failure handling: plugin.py's
        Playstream2 calls this (in-process, like stream_started())
        when the stream it got for channel_id ended or broke, right
        before it asks /vavoo for it again.

        Drops the cached address, so that next request resolves a
        fresh one instead of the one that just failed. For a grouped
        channel it also decides whether to stay on the same source:
        the first report retries it (a fresh address for the same
        source fixes an ordinary hiccup, and jumping to an untested
        source could make things worse), but more than
        GROUP_SAME_SOURCE_RETRIES reports within GROUP_FAILURE_WINDOW
        seconds of each other give up on it and let
        resolve_group_with_retry() move to the next one."""
        if not channel_id:
            return

        if not channel_id.startswith(GROUP_ID_PREFIX):
            channel = self.channels_by_id.get(channel_id)
            if channel:
                self.invalidate_resolved(channel.get("url"))
            return

        country, key = parse_group_id(channel_id)
        members = self._group_members(country, key) if key else []
        now = time.time()
        failed_member_id = None
        gave_up = False
        with self.group_lock:
            state = self._group_state.get(channel_id)
            if state:
                failed_member_id = state.get("member")
            if failed_member_id is not None:
                if now - state.get("failed_at", 0) <= GROUP_FAILURE_WINDOW:
                    state["failures"] = state.get("failures", 0) + 1
                else:
                    state["failures"] = 1
                state["failed_at"] = now
                if state["failures"] > GROUP_SAME_SOURCE_RETRIES:
                    state.setdefault("avoid", {})[failed_member_id] = now
                    state["member"] = None
                    state["failures"] = 0
                    gave_up = True
        if failed_member_id is None:
            # Nothing known to be playing (e.g. the proxy was
            # restarted since) - the next request resolves from
            # scratch anyway.
            return

        for member in members:
            if member.get("id") == failed_member_id:
                self.invalidate_resolved(member.get("url"))
                break
        if gave_up:
            print("[Proxy] {0}: source {1} keeps failing, trying another".format(
                channel_id, failed_member_id))
        else:
            print("[Proxy] {0}: source {1} failed, retrying it".format(
                channel_id, failed_member_id))

    def get_group_sources(self, group_id):
        """A grouped channel's individual sources and which one is in
        use: {"members": [{"id", "label"}, ...], "current": id or
        None} - for the player's source menu (plugin.py's
        chooseStreamSource()) and the /group_sources endpoint."""
        country, key = parse_group_id(group_id)
        members = self._group_members(country, key) if key else []
        with self.group_lock:
            state = self._group_state.get(group_id) or {}
            current = state.get("member") or self._group_pins.get(group_id)
        member_ids = [m.get("id") for m in members]
        if current not in member_ids:
            current = None
        labels = _unique_source_labels(members)
        return {
            "members": [
                {"id": m.get("id"), "label": labels[i]}
                for i, m in enumerate(members)
            ],
            "current": current,
        }

    def set_group_source(self, group_id, member_id):
        """The user picked member_id as group_id's source (YELLOW in
        the player). It becomes the source the group plays from - the
        player restarts the stream right after calling this, and that
        request then resolves this source - and is saved to
        SOURCE_PREFS_FILE so it is still the preferred one after a
        restart. Returns False (changing nothing) if member_id isn't
        one of this group's sources."""
        country, key = parse_group_id(group_id)
        members = self._group_members(country, key) if key else []
        if member_id not in [m.get("id") for m in members]:
            return False
        with self.group_lock:
            state = self._group_state.setdefault(group_id, {})
            state["member"] = member_id
            state["failures"] = 0
            state.setdefault("avoid", {}).pop(member_id, None)
            self._group_pins[group_id] = member_id
            pins = dict(self._group_pins)
        self._save_source_prefs(pins)
        print("[Proxy] {0}: source {1} picked by user".format(
            group_id, member_id))
        return True

    def _save_source_prefs(self, pins):
        """Write the user's source picks to SOURCE_PREFS_FILE - via a
        temp file and rename, so a power cut mid-write can't leave a
        half-written file behind. Best effort: a failure here only
        means the pick isn't remembered across a restart."""
        temp_path = SOURCE_PREFS_FILE + ".tmp"
        with self._group_pins_file_lock:
            try:
                with open(temp_path, 'w') as f:
                    f.write(dumps(pins))
                os.rename(temp_path, SOURCE_PREFS_FILE)
            except Exception as e:
                print("[Proxy] Could not save source picks: {}".format(e))

    def _cache_resolved_url(self, channel_url, stream_url):
        """Store a freshly-resolved stream URL in resolve_cache -
        shared by both the Vavoo and geil.to resolve paths."""
        now = time.time()
        with self.resolve_cache_lock:
            self.resolve_cache[channel_url] = {"url": stream_url, "ts": now}
            # Entries nobody asked for within resolve_cache_ttl can
            # never be returned again (see _get_cached_url()) - drop
            # them once the cache has grown, so it stays bounded
            # without ever evicting an address that is still in use.
            if len(self.resolve_cache) > 200:
                for key in [k for k, v in self.resolve_cache.items()
                            if now - v["ts"] >= self.resolve_cache_ttl]:
                    self.resolve_cache.pop(key, None)

    def _resolve_geil_channel(self, channel_url, max_retries):
        """Resolve a geil.to channel's stream address - GET
        {base}/live/resolve?url=<its play address>, no token at all.
        Tries the current geil mirror first, then the others, same
        shape as the Vavoo resolve path but a different API entirely
        (never falls back to Vavoo's API for this same channel_url -
        it's a geil.to catalog id/url, which Vavoo's API has no
        knowledge of)."""
        headers = {
            "user-agent": "MediaHubMX/2",
            "accept": "application/json",
        }
        # Read geil_base() once into a local - a concurrent
        # _switch_to_next_geil() call (from another in-flight resolve)
        # between two separate reads here could make this list comp
        # exclude the mirror it actually put first, silently dropping
        # a different mirror from this attempt's candidates instead.
        current_base = self.geil_base()
        sites = [current_base] + [
            s for s in self.geil_sites if s != current_base]
        last_exception = None
        for site in sites[:max(1, max_retries)]:
            url = site.rstrip('/') + GEIL_LIVE_PATH + "/resolve?url=" + \
                quote(channel_url, safe='')
            try:
                r = self.session.get(url, headers=headers, timeout=15)
                r.raise_for_status()
                result = decode_response(r)
                stream_url = None
                if isinstance(result, dict):
                    stream_url = result.get("url") or result.get(
                        "streamUrl")
                if stream_url:
                    self._cache_resolved_url(channel_url, stream_url)
                    return stream_url
                print("[Geil] {0} answered with no stream url".format(site))
            except Exception as e:
                last_exception = e
                print("[Geil] Resolve via {0} failed: {1}".format(site, e))
                if site == self.geil_base():
                    self._switch_to_next_geil("({0} on resolve)".format(e))
        if last_exception:
            print(
                "[Geil] Failed to resolve channel after trying all "
                "mirrors: {0}".format(last_exception))
        return None

    def _do_resolve_with_retry(self, channel_url, max_retries):
        """The actual network resolve + retry loop - see
        resolve_with_retry() for the in-flight dedup wrapping this."""
        if self.catalog_source == "geil":
            return self._resolve_geil_channel(channel_url, max_retries)
        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    # Not force=True: that unconditionally bypassed the
                    # "already fresh" short-circuit above, so a burst of
                    # concurrently failing streams (e.g. right after
                    # _switch_to_next_base()) each forced their own full
                    # network round-trip to PING_URL/PING_URL2 in a row
                    # instead of reusing whatever another thread had just
                    # refreshed a moment earlier - exactly the kind of
                    # extra ping traffic the token system exists to
                    # avoid.
                    self.refresh_addon_sig_if_needed()

                with self.addon_sig_lock:
                    current_sig = self.addon_sig_data["sig"]

                resolve_headers = {
                    "content-type": "application/json; charset=utf-8",
                    "mediahubmx-signature": current_sig,
                    "user-agent": "MediaHubMX/2",
                    "accept": "*/*",
                    "Accept-Language": self.current_language,
                    "Accept-Encoding": "gzip, deflate",
                    "Connection": "close",
                }

                resolve_payload = {
                    "language": self.current_language,
                    "region": self.current_region,
                    "url": channel_url,
                    "clientVersion": "3.0.2"
                }

                print(
                    " Resolving channel URL (attempt %d/%d)" %
                    (attempt + 1, max_retries))
                r_resolve = self.session.post(
                    self.resolve_url,
                    json=resolve_payload,
                    headers=resolve_headers,
                    timeout=30
                )

                # self.session defaults to stream=True (for the video-stream
                # proxying path) - close() returns the connection to the
                # pool instead of leaking it when we discard this response
                # and retry/switch mirrors without ever reading its body.
                if r_resolve.status_code == 451:
                    r_resolve.close()
                    self._switch_to_next_base("(HTTP 451 on resolve)")
                    if attempt < max_retries - 1:
                        continue

                if r_resolve.status_code == 502 and attempt < max_retries - 1:
                    r_resolve.close()
                    select.select([], [], [], 0.25)
                    continue

                r_resolve.raise_for_status()
                result = decode_response(r_resolve)
                stream_url = None
                if isinstance(result, list) and result:
                    stream_url = result[0].get("url")
                elif isinstance(result, dict):
                    stream_url = result.get("url") or result.get("streamUrl")

                if stream_url:
                    self._cache_resolved_url(channel_url, stream_url)
                    print(" Successfully resolved channel URL")
                    return stream_url
                print(" Resolve response missing URL")

            except requests.exceptions.HTTPError as e:
                print(
                    " HTTP error in resolve attempt %d: %s" %
                    (attempt + 1, str(e)))
                try:
                    if e.response is not None and e.response.status_code == 451:
                        self._switch_to_next_base(
                            "(HTTP 451 on resolve HTTPError)")
                except Exception as e2:
                    debug("_switch_to_next_base failed: {}".format(e2))
                if attempt < max_retries - 1:
                    select.select([], [], [], 0.25)
            except Exception as e:
                print(
                    " Error in resolve attempt %d: %s" %
                    (attempt + 1, str(e)))
                if attempt < max_retries - 1:
                    select.select([], [], [], 0.25)

        print(" Failed to resolve channel URL after all retries")
        return None

    def get_local_ip(self, force_refresh=False):
        # Deliberately always 127.0.0.1, not the box's real LAN IP: the
        # /channels endpoint embeds this directly into the proxy URLs
        # returned for bouquet export (http://<local_ip>:PORT/vavoo?...),
        # and localhost is "the core trick that makes streams stable"
        # (see CLAUDE.md) - a real LAN IP would still often work, but
        # loses that guarantee for no benefit. The API docs' own example
        # showing a LAN-looking address is just misleading, not a
        # promise this should actually return one.
        return PROXY_HOST

    def is_stopped(self):
        """True once stop() has been called - this instance's token
        monitor has ended and it must not be served from again."""
        return self._stop_event.is_set()

    def stop(self):
        """Stop background workers/timers and close session (safe for Py2/3)."""
        try:
            self._stop_event.set()
        except Exception:
            pass
        try:
            self.session.close()
        except Exception:
            pass


class VavooHTTPHandler(BaseHTTPRequestHandler):
    timeout = 10

    def do_HEAD(self):
        # BaseHTTPRequestHandler returns 501 for any method without a
        # do_* handler - some EPG importers (and other HTTP clients)
        # probe a URL with HEAD before actually fetching it, and would
        # treat that 501 as the source being unreachable, silently
        # skipping it entirely rather than falling back to GET. Reuse
        # do_GET's routing/headers for every endpoint, just without a
        # body, which is what HEAD is supposed to return anyway.
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def safe_write(self, data):
        if getattr(self, '_head_only', False):
            return True
        try:
            if isinstance(data, unicode):
                data = data.encode('utf-8')
            elif not isinstance(data, bytes):
                data = str(data).encode('utf-8')
            self.wfile.write(data)
        except (socket.error, IOError):
            return False
        return True

    def safe_send_response(self, code, message=None):
        """Safe response sending"""
        try:
            if message:
                self.send_response(code, message)
            else:
                self.send_response(code)
        except (BrokenPipeError, ConnectionResetError):
            print("Client disconnected during response - ignoring")
            return False
        return True

    def do_GET(self):
        # client_address = self.client_address[0]
        # print(" Request {1} from {0}"
        #    .format(client_address, self.path))
        try:
            parsed_path = urlparse(self.path)
            query_params = parse_qs(parsed_path.query)

            # Bind the module-global proxy once for this whole request.
            # start_proxy() reassigns `proxy` on every restart
            # (proxy = VavooProxy()) with no synchronization - reading
            # the global repeatedly further down let a restart landing
            # mid-request split a single request across two different
            # VavooProxy instances (e.g. a channel lookup against the
            # old instance but the resolve/stream-counting against a
            # brand-new, uninitialized one).
            p = proxy

            if parsed_path.path == '/vavoo':
                channel_id = query_params.get('channel', [None])[0]
                if not channel_id:
                    self.send_error(400, "Missing channel parameter")
                    return

                # No other parameters, on purpose: the player repeats
                # this whole address on every playlist refresh (see
                # resolve_with_retry()'s own docstring), so anything
                # here would be applied again every ~10 seconds for
                # the rest of the viewing. A failed stream or a source
                # pick is reported once instead - see
                # report_stream_failure()/set_group_source().
                try:
                    if channel_id.startswith(GROUP_ID_PREFIX):
                        # A grouped channel (see /channels' own grouping
                        # step) - no single catalog entry to look up.
                        stream_url = p.resolve_group_with_retry(channel_id)
                    else:
                        channel = p.channels_by_id.get(channel_id)
                        if not channel:
                            self.send_error(404, "Channel not found")
                            return
                        stream_url = p.resolve_with_retry(channel.get("url"))

                    if not stream_url:
                        self.send_error(404, "Stream not resolved")
                        return

                    # Redirect 302 all'URL dello stream
                    self.send_response(302)
                    self.send_header('Location', stream_url)
                    self.end_headers()
                    # Once per playlist refresh of every watched
                    # stream - debug-only, or it buries the rest of
                    # the log. A real (re)resolve is still always
                    # logged by the resolve path itself.
                    debug("[Proxy] Redirect to: " + stream_url[:100])

                except Exception as e:
                    print("[Proxy] /vavoo error: " + str(e))
                    self.send_error(500, "Internal proxy error")

            elif parsed_path.path == '/stream':
                # Get the 'ref' parameter (the converted service reference)
                ref_encoded = query_params.get('ref', [None])[0]
                if not ref_encoded:
                    self.send_error(400, "Missing ref parameter")
                    return

                # Decode the ref (replace %3a back to :)
                ref = unquote(ref_encoded)

                # Load the sref map
                try:
                    with open(SREF_MAP_FILE, 'r') as f:
                        sref_map = load(f)
                except BaseException:
                    sref_map = {}

                channel_id = sref_map.get(ref)
                if not channel_id:
                    self.send_error(404, "Channel not found in map")
                    return

                # Now get the channel object from p.channels_by_id
                channel = p.channels_by_id.get(channel_id) if hasattr(
                    p, 'channels_by_id') else None
                if not channel:
                    self.send_error(404, "Channel not found")
                    return

                try:
                    # 1. Get stream URL. force=1 skips the resolve
                    # cache, for a client that knows the address it
                    # was just given is broken.
                    force_refresh = query_params.get(
                        'force', ['0'])[0] == '1'
                    stream_url = p.resolve_with_retry(
                        channel["url"], force_refresh=force_refresh)
                    if not stream_url:
                        self.send_error(404, "Stream not resolved")
                        return

                    # 2-4 all live under one try/finally so upstream is
                    # always closed, including if raise_for_status() raises
                    # or the client disconnects before headers are sent -
                    # previously the connection/response was only closed if
                    # the forwarding loop below was actually reached.
                    upstream = None
                    counted_stream = False
                    try:
                        # 2. Connect to upstream with streaming (timeout
                        # aumentato)
                        upstream = p.session.get(
                            stream_url, stream=True, timeout=(
                                10, 90))  # (connect, read) 10s/90s
                        upstream.raise_for_status()

                        # 3. Send headers to player
                        if not self.safe_send_response(200):
                            return
                        self.send_header(
                            'Content-Type',
                            upstream.headers.get(
                                'Content-Type',
                                'video/mp2t'))
                        self.send_header('Connection', 'keep-alive')
                        # Add headers to prevent caching
                        self.send_header(
                            'Cache-Control', 'no-cache, no-store')
                        self.end_headers()

                        # HEAD requests get headers only - the caller
                        # (do_HEAD) wants to know the stream is reachable
                        # without paying for the actual video transfer.
                        if getattr(self, '_head_only', False):
                            return

                        # 4. Forward data with timeout monitoring (chunk
                        # size increased)
                        p.stream_started()
                        counted_stream = True
                        last_data_time = time.time()
                        try:
                            # Increase chunk size from 65536 to 262144 (256KB)
                            for chunk in upstream.iter_content(
                                    chunk_size=262144):
                                if chunk:
                                    self.wfile.write(chunk)
                                    self.wfile.flush()
                                    last_data_time = time.time()
                                else:
                                    if time.time() - last_data_time > 15:
                                        print(
                                            "[Proxy Stream] Upstream stalled for: " + channel_id)
                                        break
                                    select.select([], [], [], 0.1)
                        except (socket.timeout, ConnectionError, BrokenPipeError) as e:
                            print("[Proxy Stream] Network error: " + str(e))
                        except Exception as e:
                            print("[Proxy Stream] Unexpected error: " + str(e))
                    finally:
                        if upstream is not None:
                            try:
                                upstream.close()
                            except Exception:
                                pass
                        if counted_stream:
                            p.stream_ended()
                        print(
                            "[Proxy Stream] Finished for channel: " +
                            channel_id)
                except Exception as e:
                    print("[Proxy Stream] Error: " + str(e))
                    self.send_error(500, "Streaming error")

            elif parsed_path.path == '/channels':
                # p is already bound once at the top of do_GET()
                country = query_params.get('country', [None])[0]
                if not country:
                    self.send_error(400, "Missing country parameter")
                    return

                # O(channels-in-this-country) via the precomputed
                # per-country index, instead of scanning the entire
                # (every-country) catalog on every single /channels
                # call.
                matching_channels = p.channels_by_country.get(
                    country.lower(), []) if hasattr(
                    p, 'channels_by_country') else []

                response_channels = []
                local_ip = p.get_local_ip()

                # Group sources of the same channel (Vavoo's own
                # ".b"/".c"/".s" convention, which geil.to's "(N)"
                # suffix is already normalized to by fix_geil_name())
                # into a single row, like the companion Android app's
                # "group sources" option - see _group_key()'s own
                # docstring for why that, and not EPG matching's more
                # tolerant clean_name_for_similarity(), is used here. A
                # name that normalizes to "" (nothing recognizable
                # left) is never grouped with anything else - shown
                # standalone, same as today.
                #
                # _group_key() computed once per channel here (not
                # twice, once per pass) and carried forward as
                # channel_keys - halves the regex cost of this
                # endpoint, which bouquet export calls once per
                # country *and* once per category on every run.
                channel_keys = [
                    (channel, _group_key(channel.get("name", "")))
                    for channel in matching_channels]

                key_members = {}
                for channel, key in channel_keys:
                    if key:
                        key_members.setdefault(key, []).append(channel)

                emitted_keys = set()
                for channel, key in channel_keys:
                    members = key_members.get(key) if key else None

                    if members and len(members) > 1:
                        # Several sources of one channel - one row for
                        # all of them, emitted the first time any of
                        # its sources is reached (so the row lands
                        # where the first source would have, instead
                        # of reordering the list), skipped every other
                        # time. Resolved through resolve_group_with_
                        # retry() via its synthetic group id, which
                        # picks one source and stays on it until the
                        # player reports it as failed.
                        if key in emitted_keys:
                            continue
                        emitted_keys.add(key)
                        group_id = make_group_id(country, key)
                        display_names = [
                            _strip_source_suffix(m.get("name", "")) or
                            m.get("name", "") for m in members]
                        display_name = min(display_names, key=len)
                        logo = next(
                            (m.get("logo") for m in members if m.get("logo")), "")
                        epg_id = next(
                            (m.get("epg_id") for m in members if m.get("epg_id")), "")
                        proxy_url = "http://%s:%d/vavoo?channel=%s" % (
                            local_ip, PORT, quote(group_id, safe=''))
                        response_channels.append({
                            "id": group_id,
                            "name": display_name,
                            "url": proxy_url,
                            "logo": logo,
                            # The catalog's own casing (e.g. "Italy"),
                            # same as the standalone branch below -
                            # not the raw query string (e.g. "italy"),
                            # which made this field's casing differ
                            # between a grouped and a standalone row
                            # in the same response.
                            "country": members[0].get("country", country),
                            "epg_id": epg_id
                        })
                    else:
                        channel_id = channel.get("id", "")
                        if not channel_id:
                            continue
                        # Quoted the same way the grouped branch above
                        # (group_id) and /playlist.m3u (channel_id) already
                        # are - this was the one place a raw catalog id
                        # with a "&"/"#"/space in it could still corrupt
                        # the query string.
                        proxy_url = "http://%s:%d/vavoo?channel=%s" % (
                            local_ip, PORT, quote(str(channel_id), safe=''))
                        raw_name = channel.get("name", "")
                        response_channels.append({
                            "id": channel_id,
                            # Strip the same source-variant suffix the
                            # grouped branch above already strips -
                            # this channel just happens to have no
                            # sibling source present in this country's
                            # catalog right now (common - not every
                            # channel actually has multiple sources
                            # even though Vavoo/geil still tags it with
                            # a letter), which is no reason to show the
                            # raw ".b"/".c"/".s" suffix forever.
                            "name": _strip_source_suffix(raw_name) or raw_name,
                            "url": proxy_url,
                            "logo": channel.get("logo", ""),
                            "country": channel.get("country", country),
                            "epg_id": channel.get("epg_id", "")
                        })

                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if not self.safe_write(dumps(response_channels)):
                    return

            elif parsed_path.path == '/group_sources':
                # Lists a grouped channel's individual sources (Vavoo/
                # Geil's ".b"/".c"/".s" convention - see /channels'
                # own grouping step and _group_key()) and which one is
                # in use. Read-only; the player's own source menu
                # reads the same thing in-process via
                # get_group_sources().
                group_id = query_params.get('group', [None])[0]
                if not group_id or not group_id.startswith(GROUP_ID_PREFIX):
                    self.send_error(400, "Missing or invalid group parameter")
                    return

                try:
                    result = p.get_group_sources(group_id)
                    if not self.safe_send_response(200):
                        return
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    if not self.safe_write(dumps(result)):
                        return
                except Exception as e:
                    print("[Proxy] /group_sources error: " + str(e))
                    self.send_error(500, "Internal proxy error")

            elif parsed_path.path == '/playlist.m3u':
                # Live-serving twin of plugin.py's "Generate .m3u
                # files" wizard (generate_single_m3u()) - same header/
                # entry format, but built fresh from the in-memory
                # catalog on every request instead of a one-shot file
                # a user has to remember to regenerate. p is already
                # bound once at the top of do_GET().
                playlist_key = ""
                try:
                    playlist_key = e2_config.plugins.vavoo.playlist_key.value
                except Exception as e:
                    # Fails open (no key required) rather than closed -
                    # acceptable since config.plugins.vavoo is always
                    # set by plugin.py long before this thread can ever
                    # start, but log it so a configured key silently
                    # not applying wouldn't go unnoticed.
                    print("[Proxy] Could not read playlist_key config: {}".format(e))
                    playlist_key = ""
                if playlist_key:
                    supplied_key = query_params.get('key', [None])[0]
                    if supplied_key != playlist_key:
                        self.send_error(401, "Invalid or missing playlist key")
                        return

                country = query_params.get('country', [None])[0]
                local_ip = p.get_local_ip()

                m3u_lines = ["#EXTM3U"]
                # A country was given: look it up directly via the
                # per-country index instead of scanning every country
                # in the whole catalog to find the ones that match.
                if country:
                    playlist_channels = p.channels_by_country.get(
                        country.lower(), []) if hasattr(
                        p, 'channels_by_country') else []
                else:
                    playlist_channels = getattr(p, 'all_filtered_items', [])
                if playlist_channels:
                    for channel in playlist_channels:
                        channel_id = channel.get("id", "")
                        if not channel_id:
                            continue
                        channel_name = decodeHtml(channel.get("name", "Unknown"))
                        channel_name = remove_parentheses(channel_name)
                        # Catalog data is remote/mirror-switchable and
                        # already treated as attacker-influenceable
                        # elsewhere in this codebase (see
                        # bouquet_manager.py's own control-char
                        # stripping for #NAME/Favorite.txt lines) - an
                        # embedded newline here would inject extra
                        # lines into the generated playlist.
                        channel_name = strip_control_chars(channel_name)
                        # channel_id is catalog data too (same threat
                        # model as channel_name above) and is embedded
                        # directly into this line's URL, not just its
                        # text - quote() closes both the newline-
                        # injection gap and a stray "&"/"#"/space
                        # corrupting the query string itself.
                        channel_url = "http://%s:%d/vavoo?channel=%s" % (
                            local_ip, PORT, quote(str(channel_id), safe=''))
                        m3u_lines.append("#EXTINF:-1,%s" % channel_name)
                        m3u_lines.append(channel_url)
                m3u_text = "\n".join(m3u_lines) + "\n"

                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'audio/x-mpegurl; charset=utf-8')
                self.end_headers()
                if not self.safe_write(m3u_text.encode('utf-8')):
                    return

            elif parsed_path.path == '/catalog':
                # p is already bound once at the top of do_GET()
                if hasattr(p, 'all_filtered_items'):
                    if not self.safe_send_response(200):
                        return
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    if not self.safe_write(dumps(p.all_filtered_items)):
                        return
                else:
                    self.send_error(404, "No catalog loaded")

            elif parsed_path.path == '/countries':
                # p is already bound once at the top of do_GET() -
                # initialize_proxy() already computed this exact
                # sorted list once at catalog-load time; no need to
                # rescan the whole catalog and re-sort on every call.
                countries_list = getattr(p, 'countries_list', [])
                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if not self.safe_write(dumps(countries_list)):
                    return

            elif parsed_path.path == '/status':
                # p is already bound once at the top of do_GET()
                # Locked read - the writer (refresh_addon_sig_if_needed())
                # updates "sig" and "ts" as two separate statements under
                # this same lock, so an unlocked read here could observe
                # a freshly-updated sig paired with the old ts.
                with p.addon_sig_lock:
                    addon_sig = dict(p.addon_sig_data)
                status = {
                    "initialized": p.initialized,
                    "channels_count": len(
                        p.all_filtered_items),
                    "catalog_source": p.catalog_source,
                    # geil.to needs no token at all, so addon_sig_valid
                    # is permanently false and addon_sig_age a huge
                    # nonsense number on that source - this flag tells
                    # a consumer not to treat either as a problem, same
                    # disambiguation /health's "status" field already
                    # makes internally.
                    "token_required": p.catalog_source != "geil",
                    "addon_sig_valid": addon_sig["sig"] is not None,
                    "addon_sig_age": int(
                        time.time() -
                        addon_sig["ts"]),
                    "local_ip": p.get_local_ip(),
                    "port": PORT}
                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if not self.safe_write(dumps(status)):
                    return

            # Redirect per-country EPG requests to GitHub raw files
            elif parsed_path.path.startswith('/epg/') and parsed_path.path.endswith('.xml'):
                # Lowercase: the actual files on GitHub are lowercase
                # (epg_it.xml, epg_fr.xml, ...) and raw.githubusercontent.com
                # paths are case-sensitive, unlike every other caller of a
                # country code in this codebase (_get_epg_feed_index(),
                # update_epg_sources(), etc.), which already lowercase
                # first - an uppercase/mixed-case request here would
                # otherwise redirect straight to a 404.
                country_code = parsed_path.path.split(
                    '/')[-1].replace('.xml', '').lower()
                github_url = "{}/vavoo-player/master/epg_{}.xml".format(
                    HOST_GIT, country_code)
                self.send_response(302)
                self.send_header('Location', github_url)
                self.end_headers()

            elif parsed_path.path == '/health':
                """Health check endpoint with detailed status"""
                # p is already bound once at the top of do_GET()
                try:
                    now = time.time()
                    # Locked read, same reasoning as /status.
                    with p.addon_sig_lock:
                        addon_sig = dict(p.addon_sig_data)
                    token_age = now - addon_sig["ts"]
                    token_valid = addon_sig["sig"] is not None
                    needs_refresh = token_age > 300  # 5 minutes

                    # Calculate token expiration
                    ttl = max(0, TOKEN_ADDON_SIG - int(token_age))

                    # Check if proxy is initialized
                    initialized = p.initialized
                    channels_count = len(
                        p.all_filtered_items) if initialized else 0

                    # When geil.to is the active catalog source, no
                    # token is ever fetched (it needs none) - requiring
                    # token_valid here too would always report
                    # "unhealthy" even though everything is working.
                    token_required = p.catalog_source != "geil"
                    proxy_status = {
                        "status": "healthy" if initialized and (
                            token_valid or not token_required) else "unhealthy",
                        "initialized": initialized,
                        "channels_count": channels_count,
                        "catalog_source": p.catalog_source,
                        "token": {
                            # Only the top-level "status" field above
                            # accounted for token_required before - on
                            # geil.to, where no token is ever fetched,
                            # "valid"/"needs_refresh" otherwise read as
                            # a permanent false/true contradicting a
                            # "healthy" overall status, which would
                            # false-positive-alert any monitoring that
                            # watches this sub-object directly instead
                            # of the top-level field.
                            "required": token_required,
                            "valid": token_valid if token_required else True,
                            "age": int(token_age),
                            "ttl": ttl,
                            "needs_refresh": needs_refresh if token_required else False,
                            "expires_in": str(ttl) + "s"
                        },
                        "system": {
                            "uptime": int(now - p.start_time if hasattr(p, 'start_time') else 0),
                            "heartbeat": int(now - p.last_heartbeat),
                            "port": PORT,
                            "local_ip": p.get_local_ip()
                        },
                        "timestamp": now,
                        "message": "Proxy is running normally" if initialized else "Proxy not initialized"
                    }

                    # Read-only health endpoint: no forced refresh here

                    # self.send_response(200)
                    if not self.safe_send_response(200):
                        return
                    self.send_header('Content-Type', 'application/json')
                    self.send_header(
                        'Cache-Control',
                        'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    self.end_headers()
                    if not self.safe_write(dumps(proxy_status)):
                        return
                except Exception as e:
                    error_response = {
                        "status": "error",
                        "message": str(e),
                        "timestamp": time.time()
                    }
                    if not self.safe_send_response(500):
                        return
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    if not self.safe_write(dumps(error_response)):
                        return

            elif parsed_path.path == '/refresh_token':
                # Use the request-bound `p`, not the bare `proxy` global -
                # see the comment on `p = proxy` above.
                sig = p.refresh_addon_sig_if_needed(force=True)
                response = {
                    "status": "success" if sig else "error",
                    "message": "Token refreshed" if sig else "Failed to refresh token"}
                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if not self.safe_write(dumps(response)):
                    return

            elif parsed_path.path == '/shutdown':
                # Signal stop to prevent the restart loop from
                # re-spawning the server: the global flag, and the
                # one on the instance being served (start_proxy()
                # checks both - the global one is cleared by the next
                # start, the instance's never is).
                STOP_EVENT.set()
                p._stop_event.set()

                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                if not self.safe_write(b"Proxy shutting down..."):
                    return

                def shutdown_server():
                    select.select([], [], [], 0.2)
                    # self.server is always the exact ThreadedHTTPServer
                    # that dispatched this very request - unlike `proxy`/
                    # `p`, there's no possible race with a concurrent
                    # restart rebinding the global to a different
                    # VavooProxy instance.
                    if self.server:
                        try:
                            self.server.shutdown()
                        except Exception:
                            pass
                        try:
                            self.server.server_close()
                        except Exception:
                            pass
                    # Deliberately the live global here, not `p`: if a
                    # restart raced in during the 0.2s above, we want to
                    # stop whichever VavooProxy instance is actually live
                    # now, not a possibly-already-superseded one.
                    try:
                        proxy.stop()
                    except Exception:
                        pass

                t = threading.Thread(target=shutdown_server)
                t.setDaemon(True)  # Py2/3 compatible
                t.start()

            else:
                self.send_error(404, "Not Found")

        except BrokenPipeError:
            print(" Client disconnected (BrokenPipeError)")
            return
        except ConnectionResetError:
            print(" Connection reset by client")
            return
        except Exception as e:
            print("[Handler] Error: %s" % str(e))
            try:
                self.send_error(500, "Internal Server Error")
            except (BrokenPipeError, ConnectionResetError):
                print(" Client gone while sending error")
                return

    def handle_one_request(self):
        """Handle a single request with guaranteed cleanup"""
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        except (socket.timeout, socket.error) as e:
            print(" Socket error in request: " + str(e))
            try:
                self.connection.close()
            except BaseException:
                pass
        except Exception as e:
            print(" Unexpected error in request: " + str(e))

    def finish(self):
        """Override finish to manage cleanup"""
        try:
            BaseHTTPRequestHandler.finish(self)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def setup(self):
        """Setup with timeout"""
        BaseHTTPRequestHandler.setup(self)
        self.request.settimeout(self.timeout)
        # Streaming writes are flushed per-chunk (see the /stream handler);
        # without this, Nagle's algorithm can hold small/odd-sized writes
        # briefly waiting to coalesce them, adding needless latency.
        try:
            self.request.setsockopt(
                socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except (socket.error, OSError, AttributeError):
            pass

    def log_message(self, format, *args):
        pass


proxy = VavooProxy()


def shutdown_proxy():
    """Stop the in-process proxy: its HTTP server and its background
    token monitor. Returns once the server has stopped serving and
    released its port (normally within one serve_forever() poll
    interval, 0.5s).

    Used to ask the server to stop itself over HTTP (/shutdown) and
    then clear STOP_EVENT as soon as that request was answered -
    which is before the server thread had got around to checking it.
    That thread then saw "no stop requested", treated its own
    shutdown as a crash and started the proxy straight back up: a
    "stopped" proxy kept running, and since stop() had already ended
    its token monitor, it kept running without one. Stopping it
    directly, and leaving the stop flag on the instance itself (never
    cleared, since a stopped instance is never reused - see
    start_proxy()), makes it deterministic.
    """
    old = proxy
    # Before server.shutdown(): start_proxy()'s loop checks this flag
    # the moment serve_forever() returns.
    try:
        old.stop()
    except Exception as e:
        print(" Failed to stop proxy instance: {}".format(e))
    server = old.server
    if server is not None:
        try:
            server.shutdown()
        except Exception as e:
            print(" Error stopping proxy server: {}".format(e))
        try:
            server.server_close()
        except Exception as e:
            print(" Error closing proxy server: {}".format(e))
    print(" Proxy stopped")
    return True


def restart_proxy_in_background():
    """Stop the running proxy (if any) and start a fresh one, without
    blocking the caller - stopping waits for the old server to wind
    down, and callers are on Enigma2's GUI thread.

    is_proxy_booting() is True from the moment this returns until the
    new server is up: the old one keeps answering for a moment while
    it winds down, so "the port answers" alone can't tell a caller
    whether it is talking to the old proxy or the new one."""
    with _starting_lock:
        try:
            write_booting_file()
        except Exception as e:
            print("[Proxy] Could not write booting marker: {}".format(e))

    def _task():
        try:
            shutdown_proxy()
            # The new server can't bind until the old one has let go
            # of the port.
            for _attempt in range(50):
                if not is_proxy_port_listening():
                    break
                select.select([], [], [], 0.1)
            with _starting_lock:
                if not _spawn_proxy_thread():
                    remove_booting_file()
        except Exception as e:
            print("[Proxy] Restart failed: {}".format(e))
            trace_error()
            remove_booting_file()

    restart_thread = threading.Thread(target=_task)
    restart_thread.daemon = True
    restart_thread.start()


def start_proxy():
    """Start the proxy server with restart on failure"""
    global proxy
    # IMPORTANT: allow restart only if the current process is not running
    # (the PID file may be stale if the process has died)
    if is_proxy_running():
        print("[PROXY] Proxy is already running, checking if it's responsive...")
        try:
            resp = requests.get(PROXY_STATUS_URL, timeout=2)
            if resp.status_code == 200:
                print("[PROXY] Proxy is responsive, not starting another instance")
                # run_proxy_in_background() set the "booting" marker
                # before starting this thread - nothing is booting
                # after all.
                remove_booting_file()
                return True
            else:
                print("[PROXY] Proxy is running but not responsive, will restart")
        except Exception:
            print("[PROXY] Proxy running but not responding, restarting...")
            # The proxy only ever runs as an in-process daemon thread of
            # Enigma2 itself - there is no separate process for pkill to
            # match, so that call was silently a no-op and this "restart"
            # never actually stopped anything. Stop the in-process
            # instance directly instead.
            try:
                if proxy.server:
                    proxy.server.shutdown()
                    proxy.server.server_close()
                proxy.stop()
                # Every other restart branch in this function recreates
                # the instance after stop() - this one didn't, so the
                # server would come back up fine on the very next
                # attempt below, but permanently running with a dead
                # token_monitor_loop (stop() already ended it), leaving
                # the addonSig refreshed only reactively, on the next
                # failed resolve, instead of proactively in the
                # background.
                proxy = VavooProxy()
                select.select([], [], [], 2)
            except Exception as e:
                debug("Stopping unresponsive proxy failed: {}".format(e))

    # A stopped instance is never reused: stop() ends its token
    # monitor for good, so starting the server on it again would
    # leave the addonSig refreshed only after a resolve has already
    # failed with an expired one.
    if proxy.is_stopped():
        proxy = VavooProxy()

    # Write the PID file for this instance
    write_pid_file()

    # Indicate that we are booting
    write_booting_file()

    STOP_EVENT.clear()
    max_restarts = 3
    restart_count = 0

    while restart_count < max_restarts:
        try:
            print("=" * 50)
            print("VAVOO PROXY v" + str(__version__) + " (Attempt " +
                  str(restart_count + 1) + "/" + str(max_restarts) + ")")
            print("=" * 50)

            if not proxy.initialize_proxy():
                print("[✗] Failed to initialize proxy")
                restart_count += 1
                if restart_count < max_restarts:
                    select.select([], [], [], 3)
                    # Stop the failed instance's token_monitor_loop
                    # thread before dropping the reference to it -
                    # otherwise it keeps polling Vavoo's ping endpoint
                    # forever, orphaned, undermining the anti-throttling
                    # point of the token-refresh design.
                    try:
                        proxy.stop()
                    except Exception:
                        pass
                    proxy = VavooProxy()  # Recreate proxy
                    continue
                else:
                    print("[✗] Max restart attempts reached")
                    # Gave up - without this the marker stayed behind
                    # until MAX_BOOT_AGE, and every start attempt in
                    # that time was skipped as "already booting".
                    remove_booting_file()
                    return False

            server = ThreadedHTTPServer(('0.0.0.0', PORT), VavooHTTPHandler)
            # Boot completed, remove booting file
            remove_booting_file()

            # The instance this server belongs to - `proxy` itself can
            # be rebound by a restart while serve_forever() below is
            # still running.
            serving_proxy = proxy
            proxy.server = server
            local_ip = proxy.get_local_ip()

            print("[✓] Channels: " + str(len(proxy.all_filtered_items)))
            print("[✓] IP: " + str(local_ip) + ":" + str(PORT))
            print("[✓] Ready")
            print("=" * 50)

            # Reset restart counter on success
            restart_count = 0

            try:
                server.serve_forever(poll_interval=0.5)

                # If serve_forever returned, decide whether to restart or exit
                if STOP_EVENT.is_set() or serving_proxy.is_stopped():
                    print("[!] Shutdown requested, exiting proxy loop")
                    try:
                        server.server_close()
                    except Exception:
                        pass
                    try:
                        serving_proxy.stop()
                    except Exception:
                        pass
                    # A clean, intentional /shutdown-triggered exit is
                    # not a failure to start - returning here (instead
                    # of falling through to the "cannot start after N
                    # attempts" branch below) avoids logging a
                    # misleading failure for what was actually a
                    # successful graceful shutdown.
                    return True
            except KeyboardInterrupt:
                print("\n[!] Proxy stopped by user")
                break
            except Exception as e:
                print("[✗] Server error: " + str(e))
                restart_count += 1
                if restart_count < max_restarts:
                    print("[!] Restarting proxy in 5 seconds...")
                    select.select([], [], [], 5)
                    # Shutdown old server if exists
                    if proxy.server:
                        try:
                            proxy.server.shutdown()
                            proxy.server.server_close()
                        except BaseException as e:
                            debug("Old proxy server cleanup before "
                                  "restart failed: {}".format(e))
                    # Always stop the old instance's background thread,
                    # even if proxy.server was never assigned (exception
                    # before that point) - previously only reached inside
                    # the "if proxy.server:" branch above, so a failure
                    # earlier than that skipped it entirely and leaked
                    # the old token_monitor_loop thread.
                    try:
                        proxy.stop()
                    except Exception:
                        pass
                    proxy = VavooProxy()  # Recreate proxy
                    continue

        except Exception as e:
            print("[✗] Critical error: " + str(e))
            trace_error()
            restart_count += 1
            if restart_count < max_restarts:
                print("[!] Restarting proxy in 5 seconds...")
                select.select([], [], [], 5)
                # Shutdown old server if exists
                if proxy.server:
                    try:
                        proxy.server.shutdown()
                        proxy.server.server_close()
                    except BaseException:
                        pass
                # Same reasoning as the server-error branch above - must
                # run regardless of whether proxy.server was ever set.
                try:
                    proxy.stop()
                except Exception:
                    pass
                proxy = VavooProxy()  # Recreate proxy
                continue

    print("[✗] Proxy cannot start after " + str(max_restarts) + " attempts")
    remove_booting_file()
    return False


def is_proxy_port_listening():
    """Check if proxy is actually listening on PORT."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Bounded: this runs on the GUI thread in several call paths.
        # A local connect is normally instant either way (accepted or
        # refused), but with no timeout at all a full listen backlog
        # would leave it hanging for the kernel's own connect timeout.
        sock.settimeout(1)
        return sock.connect_ex((PROXY_HOST, PORT)) == 0
    except (socket.error, OSError):
        return False
    finally:
        sock.close()


def _proxy_thread_main():
    """Thread target for run_proxy_in_background() - start_proxy()
    plus a last-resort cleanup, so an unexpected crash in it can't
    leave the "booting" marker behind (which would make every start
    attempt for the next MAX_BOOT_AGE seconds think one is still in
    progress)."""
    try:
        start_proxy()
    except Exception as e:
        print("[Proxy] Proxy thread crashed: {}".format(e))
        trace_error()
        remove_booting_file()


def run_proxy_in_background():
    """Start the proxy in a background thread, unless it is already
    running or already starting.

    Always returns at once. Loading the catalog takes anywhere from a
    few seconds to minutes, and most callers are on Enigma2's GUI
    thread - they poll is_proxy_ready() for actual readiness. This
    used to wait up to 10 seconds right here whenever another start
    was already in progress (e.g. the plugin being opened while the
    start-at-boot was still loading the catalog), freezing the whole
    box for that long.

    Returns True when a proxy is running, already starting, or was
    just started; False only if the thread itself could not be
    created.
    """
    # One caller at a time, and the "booting" marker is written in
    # here, before the thread exists - not by the thread itself once
    # it gets going. Two calls in quick succession used to be able to
    # both get past every check and start two proxy threads racing
    # each other for the same port.
    with _starting_lock:
        if is_proxy_booting():
            print("[Proxy] Start already in progress")
            return True

        if is_proxy_port_listening():
            print("[Proxy] Already running and listening, skipping start")
            return True

        if not _spawn_proxy_thread():
            remove_booting_file()
            return False
    return True


def _spawn_proxy_thread():
    """Mark a boot as in progress and start the proxy thread. Caller
    holds _starting_lock and has already made sure nothing is
    listening on the port."""
    # A PID file without a listening port is just left over from an
    # earlier proxy thread of this same Enigma2 process (the proxy
    # never runs as a separate process, so the PID in it is always
    # Enigma2's own - there is nothing to kill).
    remove_pid_file()

    try:
        write_booting_file()
    except Exception as e:
        print("[Proxy] Could not write booting marker: {}".format(e))

    try:
        proxy_thread = threading.Thread(target=_proxy_thread_main)
        proxy_thread.daemon = True
        proxy_thread.start()
    except Exception as e:
        print("[Proxy] Could not start proxy thread: {}".format(e))
        return False
    return True


if __name__ == "__main__":
    start_proxy()
