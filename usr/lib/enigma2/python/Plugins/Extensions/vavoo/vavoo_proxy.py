#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import gzip
import requests
# import uuid
import time
import threading
import socket
import select
import urllib3
import atexit
import os
from collections import OrderedDict
from json import loads, load, dumps

from . import (
    PORT,
    PROXY_HOST,
    PROXY_STATUS_URL,
    PROXY_HEALTH_URL,
    PROXY_SHUTDOWN_URL,
    BASE_SITES,
    HOST_GIT,
    SREF_MAP_FILE,
    __version__
)

from .vUtils import (
    _starting_lock,
    is_proxy_running,
    log_exception,
    make_print,
    trace_error,
    # RequestAgent
)

_starting = False

try:
    unicode
except NameError:
    unicode = str

print = make_print("PROXY")


try:
    from urllib.parse import unquote, urlparse, parse_qs
except ImportError:
    from urllib import unquote
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
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


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

Example:
    wget -S -O /dev/null "http://127.0.0.1:4323/vavoo?channel=abc123"

Expected Response:
    HTTP/1.1 302 Found


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
PING_URL2 = "https://www.lokke.app/api/app/ping"
PID_FILE = "/tmp/vavoo_proxy.pid"
BOOTING_FILE = "/tmp/vavoo_proxy_booting"

# Primary + mirror. Some regions get HTTP 451 from the primary.

# HEADERS = {
    # "accept": "*/*",
    # # "user-agent": RequestAgent(),
    # "user-agent": "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36",
    # "Accept-Encoding": "gzip, deflate",
    # # NOTE: do NOT set "Connection": "close" here – it disables keep-alive
    # # for the entire session including streaming upstream connections.
# }
HEADERS = {
    "accept": "*/*",
    "user-agent": "MediaHubMX/2",
    "Accept-Language": "de",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}


def is_proxy_booting():
    """Check if another proxy instance is currently starting up."""
    return os.path.exists(BOOTING_FILE)


def write_booting_file():
    with open(BOOTING_FILE, 'w') as f:
        f.write(str(os.getpid()))


def remove_booting_file():
    if os.path.exists(BOOTING_FILE):
        os.unlink(BOOTING_FILE)


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


class ProxyHealthMonitor:
    """Monitors proxy health and restarts it if necessary"""

    def __init__(self, proxy_instance):
        self.proxy = proxy_instance
        self.last_health_check = time.time()
        self.failure_count = 0
        self.max_failures = 3
        self.monitor_thread = None
        self.running = False
        self.stop_event = threading.Event()

    def start(self):
        """Start the background health monitor"""
        self.running = True
        self.stop_event.clear()
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.setDaemon(True)
        self.monitor_thread.start()
        print("[Proxy Health Monitor] Started")

    def stop(self):
        self.running = False
        self.stop_event.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)

    def _monitor_loop(self):
        """Main monitor loop"""
        while self.running and not self.stop_event.is_set():
            try:
                self._check_proxy_health()
                self.stop_event.wait(60)
            except Exception as e:
                print(str(e))
                log_exception(
                    "[Health Monitor] Unexpected error",
                    area="PROXY")

    def _check_proxy_health(self):
        """Check proxy health status"""
        try:
            # 1. Check if proxy responds
            response = requests.get(
                PROXY_HEALTH_URL, timeout=2)

            if response.status_code == 200:
                data = response.json()

                # 2. Check token status
                token_age = data.get("token", {}).get("age", 0)
                # needs_refresh = data.get("needs_refresh", False)

                if token_age > TOKEN_REFRESH_AGE:  # aligned with token_monitor_loop threshold
                    print(
                        "[Health Monitor] Old token (" +
                        str(token_age) +
                        "s), forcing refresh..."
                    )
                    self.proxy.refresh_addon_sig_if_needed(force=True)

                # 3. Reset failure count if everything is OK
                self.failure_count = 0
                self.last_health_check = time.time()

            else:
                self._handle_proxy_failure()

        except Exception as e:
            print("[Health Monitor] Proxy not responding: " + str(e))
            self._handle_proxy_failure()

    def _handle_proxy_failure(self):
        """Handle proxy failure"""
        self.failure_count += 1
        print(
            "[Health Monitor] Proxy failure #" +
            str(self.failure_count)
        )

        if self.failure_count >= self.max_failures:
            print(
                "[Health Monitor] Too many failures, attempting to restart proxy..."
            )
            self._restart_proxy()
            self.failure_count = 0

    def _restart_proxy(self):
        try:
            global proxy, _starting
            # 1. Try to shut down the current proxy
            try:
                requests.get(PROXY_SHUTDOWN_URL, timeout=2)
                select.select([], [], [], 2)
            except Exception:
                pass

            # Remove the old PID file
            remove_pid_file()

            # 2. Kill any zombie processes still holding the port ─────────────
            try:
                import subprocess
                with open('/dev/null', 'w') as devnull:
                    subprocess.call(
                        ["pkill", "-f", "python.*vavoo_proxy"],
                        stdout=devnull,
                        stderr=devnull
                    )
            except Exception as kill_err:
                print("[Health Monitor] pkill: " + str(kill_err))
            select.select([], [], [], 2)

            # Reset the global flag
            _starting = False

            # 3. Restart the proxy
            proxy = VavooProxy()

            if proxy.initialize_proxy():
                server = ThreadedHTTPServer(
                    ('0.0.0.0', PORT), VavooHTTPHandler)
                proxy.server = server
                server_thread = threading.Thread(target=server.serve_forever)
                server_thread.setDaemon(True)
                server_thread.start()
                write_pid_file()
                print("[Health Monitor] Proxy restarted successfully")
                return True

        except Exception as e:
            print("[Health Monitor] Failed to restart proxy: " + str(e))
        return False


class VavooProxy:
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
        self.channels_by_country = {}
        self.channels_by_id = {}
        self.countries_list = []
        self.current_language = "en"
        self.current_region = "US"
        self.initialized = False
        self.last_heartbeat = time.time()
        self.local_ip = None
        self.refresh_timer = None
        # ordered for deterministic LRU eviction (Py2+3)
        self.resolve_cache = OrderedDict()
        # stream URLs valid for ~5min; was 30s (too aggressive)
        self.resolve_cache_ttl = 300
        self.server = None
        self.start_time = time.time()

        # Stop flag for background workers
        self._stop_event = threading.Event()
        self._token_monitor_thread = None

        # Mirror-aware endpoints
        self.base_sites = list(BASE_SITES)
        self.base_site_index = 0
        self._update_endpoints()

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
                if hasattr(self, 'active_streams') and self.active_streams:
                    select.select([], [], [], 120)
                else:
                    select.select([], [], [], 60)
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

                # PAYLOAD DI KODI
                payload = {
                    "reason": "app-focus",
                    "locale": self.current_language,
                    "theme": "dark",
                    "metadata": {
                        "device": {
                            "type": "Handset",
                            "brand": "google",
                            "model": "Nexus",
                            "name": "21081111RG",
                            "uniqueId": unique_id
                        },
                        "os": {
                            "name": "android",
                            "version": "7.1.2",
                            "abis": ["arm64-v8a"],
                            "host": "android"
                        },
                        "app": {
                            "platform": "android",
                            "version": "1.1.0",
                            "buildId": "97215000",
                            "engine": "hbc85",
                            "signatures": ["6e8a975e3cbf07d5de823a760d4c2547f86c1403105020adee5de67ac510999e"],
                            "installer": "com.android.vending"
                        },
                        "version": {
                            "package": "app.lokke.main",
                            "binary": "1.1.0",
                            "js": "1.1.0"
                        }
                    },
                    "appFocusTime": 0,
                    "playerActive": False,
                    "playDuration": 0,
                    "devMode": True,
                    "hasAddon": True,
                    "castConnected": False,
                    "package": "app.lokke.main",
                    "version": "1.1.0",
                    "process": "app",
                    "firstAppStart": current_timestamp - 86400000,
                    "lastAppStart": current_timestamp,
                    "ipLocation": None,
                    "adblockEnabled": False,
                    "proxy": {
                        "supported": ["ss", "openvpn"],
                        "engine": "openvpn",
                        "ssVersion": 1,
                        "enabled": False,
                        "autoServer": True,
                        "id": "fi-hel"
                    },
                    "iap": {
                        "supported": True
                    }
                }

                # User-Agent Kodi
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json; charset=utf-8",
                    "user-agent": "okhttp/4.11.0",
                    "Accept-Language": self.current_language,
                }

                # Usa PING_URL2 (vavoo.tv) prima, poi lokke.app
                urls = [PING_URL, PING_URL2]  # PING_URL2 = vavoo.tv, PING_URL = lokke.app
                sig = None
                for url in urls:
                    try:
                        r = self.session.post(
                            url, json=payload, headers=headers, timeout=15)
                        if r.status_code == 200:
                            data = r.json()
                            sig = data.get("addonSig")
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
                    print(" Using old token")
                    return self.addon_sig_data["sig"]
                return None

    def initialize_proxy(self):
        """Initialize the proxy by loading the catalog with fallback"""
        try:
            print(" Initializing...")

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
                self.countries_list = []
                self.initialized = True
                print(" Initialized with empty catalog")
                return True

            self.all_filtered_items = all_channels
            self.channels_by_id = {}
            self.channels_by_country = {}
            countries = set()
            for channel in all_channels:
                channel_id = channel.get("id")
                if channel_id:
                    self.channels_by_id[channel_id] = channel
                country = channel.get("country")
                if country:
                    self.channels_by_country.setdefault(
                        country, []).append(channel)
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
            self.countries_list = []
            self.initialized = True
            return True  # Always return True; the proxy can work even without a catalog

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

            print("Loading catalog...")

            while True:
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

                        # HTTP 451 -> immediately try next mirror
                        if r_catalog.status_code == 451:
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

                        if e.response.status_code == 502 and attempt < max_retries - 1:
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

                        group = item.get("group", "")
                        base_country = group

                        separators = ["➾", "⟾", "->", "→", "»", "›"]

                        for sep in separators:
                            if sep in base_country:
                                base_country = base_country.split(sep)[
                                    0].strip()
                                break

                        if not base_country:
                            base_country = "default"

                        channel_data = {
                            "country": base_country,
                            "id": item["ids"]["id"],
                            "name": item["name"],
                            "url": item["url"],
                            "logo": item.get("logo", ""),
                            "group": group
                        }

                        all_channels.append(channel_data)
                        items_processed += 1

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

    def resolve_with_retry(self, channel_url, max_retries=2):
        """Resolve URLs with short-lived caching and fast retries"""
        if not channel_url:
            print(" No channel URL provided")
            return None

        now = time.time()
        cached = self.resolve_cache.get(channel_url)
        if cached and (now - cached["ts"] < self.resolve_cache_ttl):
            return cached["url"]

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    self.refresh_addon_sig_if_needed(force=True)

                resolve_headers = {
                    "content-type": "application/json; charset=utf-8",
                    "mediahubmx-signature": self.addon_sig_data["sig"],
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

                if r_resolve.status_code == 451:
                    self._switch_to_next_base("(HTTP 451 on resolve)")
                    if attempt < max_retries - 1:
                        continue

                if r_resolve.status_code == 502 and attempt < max_retries - 1:
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
                    self.resolve_cache[channel_url] = {
                        "url": stream_url, "ts": time.time()}
                    # Evict oldest 500 entries (OrderedDict preserves insertion
                    # order in Py2+3)
                    if len(self.resolve_cache) > 1000:
                        keys = list(self.resolve_cache.keys())[:-500]
                        for key in keys:
                            self.resolve_cache.pop(key, None)
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
                except Exception:
                    pass
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
        return PROXY_HOST

    def stop(self):
        """Stop background workers/timers and close session (safe for Py2/3)."""
        try:
            self._stop_event.set()
        except Exception:
            pass
        try:
            if self.refresh_timer:
                self.refresh_timer.cancel()
        except Exception:
            pass
        try:
            self.session.close()
        except Exception:
            pass


class VavooHTTPHandler(BaseHTTPRequestHandler):
    timeout = 10

    def safe_write(self, data):
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
            print(
                "[DEBUG][VAVOO_PROXY][safe_send_response] Client disconnected during response - ignoring")
            return False
        return True

    def do_GET(self):
        # client_address = self.client_address[0]
        # print(" Request {1} from {0}"
        #    .format(client_address, self.path))
        try:
            parsed_path = urlparse(self.path)
            query_params = parse_qs(parsed_path.query)

            if parsed_path.path == '/vavoo':
                channel_id = query_params.get('channel', [None])[0]
                if not channel_id:
                    self.send_error(400, "Missing channel parameter")
                    return

                channel = proxy.channels_by_id.get(channel_id) if hasattr(
                    proxy, 'channels_by_id') else None

                if not channel:
                    self.send_error(404, "Channel not found")
                    return

                try:
                    # 1. Resolve the Vavoo stream URL
                    stream_url = proxy.resolve_with_retry(channel.get("url"))
                    if not stream_url:
                        self.send_error(404, "Stream not resolved")
                        return

                    # Redirect 302 all'URL dello stream
                    self.send_response(302)
                    self.send_header('Location', stream_url)
                    self.end_headers()
                    print("[Proxy] Redirect to: " + stream_url[:100])

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

                # Now get the channel object from proxy.channels_by_id
                channel = proxy.channels_by_id.get(channel_id) if hasattr(
                    proxy, 'channels_by_id') else None
                if not channel:
                    self.send_error(404, "Channel not found")
                    return

                try:
                    # 1. Get stream URL
                    stream_url = proxy.resolve_with_retry(channel["url"])
                    if not stream_url:
                        self.send_error(404, "Stream not resolved")
                        return

                    # 2. Connect to upstream with streaming (timeout aumentato)
                    upstream = proxy.session.get(
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
                    self.send_header('Cache-Control', 'no-cache, no-store')
                    self.end_headers()

                    # 4. Forward data with timeout monitoring (chunk size
                    # increased)
                    last_data_time = time.time()
                    try:
                        # Increase chunk size from 65536 to 262144 (256KB)
                        for chunk in upstream.iter_content(chunk_size=262144):
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
                        try:
                            upstream.close()
                        except Exception:
                            pass
                        print(
                            "[Proxy Stream] Finished for channel: " +
                            channel_id)
                except Exception as e:
                    print("[Proxy Stream] Error: " + str(e))
                    self.send_error(500, "Streaming error")

            elif parsed_path.path == '/channels':
                country = query_params.get('country', [None])[0]
                if not country:
                    self.send_error(400, "Missing country parameter")
                    return

                matching_channels = []
                if hasattr(proxy, 'all_filtered_items'):
                    for channel in proxy.all_filtered_items:
                        channel_country = channel.get("country", "")
                        if channel_country.lower() == country.lower():
                            matching_channels.append(channel)

                response_channels = []
                local_ip = proxy.get_local_ip()

                for channel in matching_channels:
                    channel_id = channel.get("id", "")
                    if channel_id:
                        proxy_url = "http://%s:%d/vavoo?channel=%s" % (
                            local_ip, PORT, channel_id)
                        response_channels.append({
                            "id": channel_id,
                            "name": channel.get("name", ""),
                            "url": proxy_url,
                            "logo": channel.get("logo", ""),
                            "country": channel.get("country", country)
                        })

                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if not self.safe_write(dumps(response_channels)):
                    return

            elif parsed_path.path == '/catalog':
                if hasattr(proxy, 'all_filtered_items'):
                    if not self.safe_send_response(200):
                        return
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    if not self.safe_write(dumps(proxy.all_filtered_items)):
                        return
                else:
                    self.send_error(404, "No catalog loaded")

            elif parsed_path.path == '/countries':
                countries = set()
                if hasattr(proxy, 'all_filtered_items'):
                    for channel in proxy.all_filtered_items:
                        country = channel.get("country", "")
                        if country and country != "default":
                            countries.add(country)

                countries_list = sorted(list(countries))
                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if not self.safe_write(dumps(countries_list)):
                    return

            elif parsed_path.path == '/status':
                status = {
                    "initialized": proxy.initialized,
                    "channels_count": len(
                        proxy.all_filtered_items),
                    "addon_sig_valid": proxy.addon_sig_data["sig"] is not None,
                    "addon_sig_age": int(
                        time.time() -
                        proxy.addon_sig_data["ts"]),
                    "local_ip": proxy.get_local_ip(),
                    "port": PORT}
                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                if not self.safe_write(dumps(status)):
                    return

            # Redirect per-country EPG requests to GitHub raw files
            elif parsed_path.path.startswith('/epg/') and parsed_path.path.endswith('.xml'):
                country_code = parsed_path.path.split(
                    '/')[-1].replace('.xml', '')
                github_url = "{}/vavoo-player/master/epg_{}.xml".format(
                    HOST_GIT, country_code)
                self.send_response(302)
                self.send_header('Location', github_url)
                self.end_headers()

            elif parsed_path.path == '/health':
                """Health check endpoint with detailed status"""
                try:
                    now = time.time()
                    token_age = now - proxy.addon_sig_data["ts"]
                    token_valid = proxy.addon_sig_data["sig"] is not None
                    needs_refresh = token_age > 300  # 8 minutes

                    # Calculate token expiration
                    ttl = max(0, TOKEN_ADDON_SIG - int(token_age))

                    # Check if proxy is initialized
                    initialized = proxy.initialized
                    channels_count = len(
                        proxy.all_filtered_items) if initialized else 0

                    # Proxy status
                    proxy_status = {
                        "status": "healthy" if initialized and token_valid else "unhealthy",
                        "initialized": initialized,
                        "channels_count": channels_count,
                        "token": {
                            "valid": token_valid,
                            "age": int(token_age),
                            "ttl": ttl,
                            "needs_refresh": needs_refresh,
                            "expires_in": str(ttl) + "s"
                        },
                        "system": {
                            "uptime": int(now - proxy.start_time if hasattr(proxy, 'start_time') else 0),
                            "heartbeat": int(now - proxy.last_heartbeat),
                            "port": PORT,
                            "local_ip": proxy.get_local_ip()
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
                sig = proxy.refresh_addon_sig_if_needed(force=True)
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
                # Signal global stop to prevent the restart loop from
                # re-spawning the server
                STOP_EVENT.set()

                if not self.safe_send_response(200):
                    return
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                if not self.safe_write(b"Proxy shutting down..."):
                    return

                def shutdown_server():
                    select.select([], [], [], 0.2)
                    if proxy.server:
                        try:
                            proxy.server.shutdown()
                        except Exception:
                            pass
                        try:
                            proxy.server.server_close()
                        except Exception:
                            pass
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

    def log_message(self, format, *args):
        pass


proxy = VavooProxy()


def shutdown_proxy():
    """Shutdown the proxy server if running.
    Sets STOP_EVENT first so background threads stop even if HTTP call fails.
    """
    # Signal all proxy threads to exit regardless of HTTP outcome
    STOP_EVENT.set()
    try:
        response = requests.get(
            PROXY_SHUTDOWN_URL, timeout=2)
        if response.status_code == 200:
            print(" Shutdown request sent successfully")
            STOP_EVENT.clear()  # reset for next start
            return True
    except Exception as e:
        print(" Shutdown via HTTP failed: {}".format(e))

    # Fallback: kill process
    try:
        import subprocess
        subprocess.call(["pkill", "-f", "python.*vavoo_proxy"])
        print(" Killed by pkill")
        STOP_EVENT.clear()
        return True
    except Exception as e:
        print(" Failed to kill process: {}".format(e))
    return False


def start_proxy():
    """Start the proxy server with restart on failure"""
    global proxy
    import subprocess
    # IMPORTANT: allow restart only if the current process is not running
    # (the PID file may be stale if the process has died)
    if is_proxy_running():
        print("[PROXY] Proxy is already running, checking if it's responsive...")
        try:
            resp = requests.get(PROXY_STATUS_URL, timeout=2)
            if resp.status_code == 200:
                print("[PROXY] Proxy is responsive, not starting another instance")
                return True
            else:
                print("[PROXY] Proxy is running but not responsive, will restart")
        except Exception:
            print("[PROXY] Proxy running but not responding, restarting...")
            # Kill the unresponsive process
            try:
                subprocess.call(["pkill", "-f", "python.*vavoo_proxy"])
                select.select([], [], [], 2)
            except Exception:
                pass

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
                    proxy = VavooProxy()  # Recreate proxy
                    continue
                else:
                    print("[✗] Max restart attempts reached")
                    return False

            server = ThreadedHTTPServer(('0.0.0.0', PORT), VavooHTTPHandler)
            # Boot completed, remove booting file
            remove_booting_file()

            server.timeout = 30
            server.request_queue_size = 64
            proxy.server = server
            local_ip = proxy.get_local_ip()

            print("[✓] Channels: " + str(len(proxy.all_filtered_items)))
            print("[✓] IP: " + str(local_ip) + ":" + str(PORT))
            print("[✓] Timeout: " + str(server.timeout) + "s")
            print("[✓] Ready")
            print("=" * 50)

            # Reset restart counter on success
            restart_count = 0

            try:
                server.serve_forever(poll_interval=0.5)

                # If serve_forever returned, decide whether to restart or exit
                if STOP_EVENT.is_set():
                    print("[!] Shutdown requested, exiting proxy loop")
                    try:
                        server.server_close()
                    except Exception:
                        pass
                    try:
                        proxy.stop()
                    except Exception:
                        pass
                    break
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
                            try:
                                proxy.stop()
                            except Exception:
                                pass
                        except BaseException:
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
                proxy = VavooProxy()  # Recreate proxy
                continue

    print("[✗] Proxy cannot start after " + str(max_restarts) + " attempts")
    return False


def is_proxy_port_listening():
    """Check if proxy is actually listening on PORT."""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('127.0.0.1', PORT))
    sock.close()
    return result == 0


def run_proxy_in_background(startup_timeout=30):

    global _starting

    # Wait for another booting instance up to startup_timeout seconds
    if is_proxy_booting():
        print("[Proxy] Another proxy is booting, waiting up to {} seconds...".format(
            startup_timeout))
        max_attempts = startup_timeout * 2
        for attempt in range(max_attempts):
            if not is_proxy_booting() and is_proxy_port_listening():
                print("[Proxy] Proxy boot completed, instance is running")
                return True
            select.select([], [], [], 0.5)
        print("[Proxy] Boot still present after timeout, attempting start anyway")

    # Final check: if already active and listening, exit
    if is_proxy_running() and is_proxy_port_listening():
        print("[Proxy] Already running and listening, skipping start")
        return True

    # Stale PID file? Clean it up
    if os.path.exists(PID_FILE) and not is_proxy_port_listening():
        try:
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)          # verify process exists
            os.kill(pid, 9)          # kill if it exists but is not listening
            select.select([], [], [], 0.2)
        except Exception:
            pass
        try:
            os.unlink(PID_FILE)
        except Exception:
            pass

    # Acquire lock for atomic startup
    with _starting_lock:
        if _starting:
            print("[Proxy] Already starting, skipping...")
            return False
        _starting = True

    try:
        proxy_thread = threading.Thread(target=start_proxy, daemon=True)
        proxy_thread.start()
        return True
    finally:
        with _starting_lock:
            _starting = False


if __name__ == "__main__":
    start_proxy()
