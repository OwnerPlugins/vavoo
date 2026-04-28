#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import gzip
import requests
import uuid
import time
import threading
import socket
import select
import urllib3
import atexit
import os
from json import loads, load, dumps

from . import (
    # PRIMARY_BASE_URL,
    # FALLBACK_BASE_URL,
    # PROXY_BASE_URL,
    PORT,
    PROXY_HOST,
    PROXY_STATUS_URL,
    PROXY_HEALTH_URL,
    PROXY_SHUTDOWN_URL,
    BASE_SITES,
    HOST_GIT,
    SREF_MAP_FILE
)

from .vUtils import (
    # log,
    # debug,
    # warning,
    # error,
    # log_exception,
    _starting_lock,
    is_proxy_running,
    make_print,
    trace_error,
    RequestAgent
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
socket.setdefaulttimeout(30)

try:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    # from urlparse import urlparse, parse_qs
    print(" Python 2 detected")
except ImportError:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    # from urllib.parse import urlparse, parse_qs
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
#  Last Modified: 20260315                              #
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
VAVOO PROXY ENDPOINTS (PROXY_HOST:{PORT})
1. /status - Proxy status
   URL: http://127.0.0.1:{PORT}/status
   Description: Returns the current status of the proxy, including initialization, number of channels, addonSig validity, local IP and port.

2. /channels?country=CountryName - Get channels for a country
   URL: http://127.0.0.1:{PORT}/channels?country=Italy
   Description: Returns the list of channels for the specified country. Country names must be URL-encoded.

3. /vavoo?channel=ChannelID - Resolve a channel by ID
   URL: http://127.0.0.1:{PORT}/vavoo?channel=abc123
   Description: Returns a 302 redirect to the stream URL for the given channel ID. This is the primary endpoint for playback.

4. /catalog - Full catalog
   URL: http://127.0.0.1:{PORT}/catalog
   Description: Returns the entire channel catalog in JSON format (all channels with proxy URLs).

5. /countries - List all countries
   URL: http://127.0.0.1:{PORT}/countries
   Description: Returns a list of all unique countries available in the catalog.

6. /refresh_token - Refresh addonSig token
   URL: http://127.0.0.1:{PORT}/refresh_token
   Description: Forces a refresh of the authentication token (addonSig).

7. /health - Monitors proxy
   URL: http://127.0.0.1:{PORT}/health
   Description: Monitors proxy health and restarts it if necessary.

8. /shutdown - Shutdown proxy
   URL: http://127.0.0.1:{PORT}/shutdown
   Description: Gracefully shuts down the proxy server.

9. /epg/<country>.xml - Get EPG for a specific country
    URL: http://127.0.0.1:{PORT}/epg/it.xml
    Description: Returns the EPG data in XMLTV format for the specified country (e.g., it, fr, de). The request is redirected to the corresponding file on GitHub.
"""

# API Endpoints
TOKEN_ADDON_SIG = 600  # 10 minutes - TOKEN EXPIRES EVERY 10 MINUTES!
TOKEN_REFRESH_AGE = 480
GEOIP_URL = "https://www.vavoo.tv/geoip"
PING_URL = "https://www.lokke.app/api/app/ping"
PING_URL2 = "https://www.vavoo.tv/api/app/ping"
PID_FILE = "/tmp/vavoo_proxy.pid"
# Primary + mirror. Some regions get HTTP 451 from the primary.

HEADERS = {
    "accept": "*/*",
    "user-agent": RequestAgent(),
    "Accept-Encoding": "gzip, deflate",
    "Connection": "close",
}


def decode_response(resp):
    """Decode gzip response if needed"""
    if resp.content[:2] == b'\x1f\x8b':
        return loads(gzip.decompress(resp.content))
    return resp.json()


def is_proxy_already_running():
    """Check if another proxy instance is running via PID file"""
    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())
            # Check if process exists
            os.kill(pid, 0)
            return True
    except (IOError, OSError, ProcessLookupError, ValueError):
        return False
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
                print("[Health Monitor] Error: " + str(e))
                # time.sleep(30)

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

                if token_age > 550:  # > 9 minutes (almost expired)
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
            # 1. Try to shut down the current proxy
            try:
                requests.get(PROXY_SHUTDOWN_URL, timeout=2)
                select.select([], [], [], 2)
            except Exception:
                pass

            # Remove the old PID file
            remove_pid_file()

            # 2. Kill proxy python processes
            import subprocess
            with open('/dev/null', 'w') as devnull:
                subprocess.call(
                    ["pkill", "-f", "python.*vavoo_proxy"],
                    stdout=devnull,
                    stderr=devnull
                )
            select.select([], [], [], 3)

            # Reset the global flag
            global _starting
            _starting = False

            # 3. Restart the proxy
            global proxy
            proxy = VavooProxy()

            if proxy.initialize_proxy():
                server = ThreadedHTTPServer(('0.0.0.0', PORT), VavooHTTPHandler)
                proxy.server = server
                server_thread = threading.Thread(target=server.serve_forever)
                server_thread.setDaemon(True)
                server_thread.start()
                write_pid_file()  # Write the new PID
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
        self.resolve_cache = {}
        self.resolve_cache_ttl = 30
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
        self.active_streams += 1
        print(
            "[Proxy] Stream started. Active streams: {}".format(
                self.active_streams))

    def stream_ended(self):
        if self.active_streams > 0:
            self.active_streams -= 1
        print(
            "[Proxy] Stream ended. Active streams: {}".format(
                self.active_streams))

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

    def token_monitor_loop(self):
        while not self._stop_event.is_set():
            if hasattr(self, 'active_streams') and self.active_streams > 0:
                select.select([], [], [], 30)
                continue

            try:
                now = time.time()
                token_age = now - \
                    self.addon_sig_data["ts"] if self.addon_sig_data["sig"] else 0
                if self.addon_sig_data["sig"] and token_age > TOKEN_REFRESH_AGE:
                    print(
                        "[Token Monitor] Token old ({}s), refreshing...".format(
                            int(token_age)))
                    self.refresh_addon_sig_if_needed(force=True)
            except Exception as e:
                print("[Token Monitor] Error: " + str(e))

            select.select([], [], [], 60)

    def start_token_monitor(self):
        """Monitor token age with minimal background traffic"""
        def token_monitor_loop():
            while not self._stop_event.is_set():
                if hasattr(self, 'active_streams') and self.active_streams:
                    select.select([], [], [], 120)
                else:
                    select.select([], [], [], 60)
                try:
                    now = time.time()
                    token_age = now - \
                        self.addon_sig_data["ts"] if self.addon_sig_data["sig"] else 0
                    if self.addon_sig_data["sig"] and token_age > TOKEN_REFRESH_AGE:
                        print("[Token Monitor] Token old ({}s), refreshing...".format(int(token_age)))
                        self.refresh_addon_sig_if_needed(force=True)
                    self.last_heartbeat = now
                except Exception as e:
                    print("[Token Monitor] Error: " + str(e))

        self._token_monitor_thread = threading.Thread(
            target=token_monitor_loop)
        self._token_monitor_thread.setDaemon(True)
        self._token_monitor_thread.start()
        print(" Token monitor started")

    def refresh_addon_sig_if_needed(self, force=False):
        """Refresh the addonSig if needed with better error handling"""
        with self.addon_sig_lock:
            now = time.time()
            if not force and self.addon_sig_data["sig"] and (
                    now - self.addon_sig_data["ts"] < 300):  # 8 minutes
                return self.addon_sig_data["sig"]

            try:
                unique_id = str(uuid.uuid4())
                current_timestamp = int(time.time() * 1000)

                payload = {
                    "reason": "app-focus",
                    "locale": self.current_language,
                    "theme": "dark",
                    "metadata": {
                        "device": {
                            "type": "desktop",
                            "uniqueId": unique_id},
                        "os": {
                            "name": "win32",
                            "version": "Windows 10 Pro",
                            "abis": ["x64"],
                            "host": "Lenovo"},
                        "app": {
                            "platform": "electron"},
                        "version": {
                            "package": "tv.vavoo.app",
                            "binary": "3.1.8",
                            "js": "3.1.8"}},
                    "appFocusTime": 0,
                    "playerActive": False,
                    "playDuration": 0,
                        "devMode": False,
                        "hasAddon": True,
                        "castConnected": False,
                        "package": "tv.vavoo.app",
                        "version": "3.1.8",
                        "process": "app",
                        "firstAppStart": current_timestamp,
                        "lastAppStart": current_timestamp,
                        "ipLocation": None,
                        "adblockEnabled": True,
                        "proxy": {
                            "supported": ["ss"],
                            "engine": "Mu",
                            "enabled": False,
                            "autoServer": True},
                    "iap": {
                        "supported": False}}

                # Use the robust request method
                urls = [PING_URL, PING_URL2]
                sig = None
                for url in urls:
                    try:
                        r = self._robust_request(
                            "POST", url, json=payload, timeout=15)
                        r.raise_for_status()
                        data = decode_response(r)
                        sig = data.get("addonSig")
                        if sig:
                            break  # Found, exit loop
                        else:
                            print(
                                "[AddonSig] No addonSig received from {}".format(url))
                    except Exception as e:
                        print(
                            "[AddonSig] Request to {} failed: {}".format(
                                url, e))

                if sig:
                    self.addon_sig_data["sig"] = sig
                    self.addon_sig_data["ts"] = now
                else:
                    print("[AddonSig] Unable to obtain addonSig from any URL")

                print(" Token refreshed successfully")
                return sig

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
                "Connection": "close",
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
                            timeout=30,
                            verify=False
                        )

                        # HTTP 451 -> immediately try next mirror
                        if r_catalog.status_code == 451:
                            self._switch_to_next_base("(HTTP 451 on catalog)")
                            if attempt < max_retries - 1:
                                continue

                            r_catalog = self.session.post(
                                self.catalog_url,
                                json=catalog_payload,
                                headers=catalog_headers,
                                timeout=30
                            )

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
            print(" Client disconnected during response - ignoring")
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

                    # Return the redirect immediately to reduce startup latency
                    if not self.safe_send_response(302):
                        return

                    self.send_header('Location', stream_url)
                    self.end_headers()
                    print(
                        " 302 Redirect to upstream stream for channel: " +
                        channel_id)

                except Exception as e:
                    print(" Error in /vavoo handler: " + str(e))
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
                        stream_url, stream=True, timeout=(10, 90))  # (connect, read) 10s/90s
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
                    # Aggiungi header per prevenire caching
                    self.send_header('Cache-Control', 'no-cache, no-store')
                    self.end_headers()

                    # 4. Forward data with timeout monitoring (chunk size aumentato)
                    last_data_time = time.time()
                    try:
                        # Aumenta chunk size da 65536 a 262144 (256KB)
                        for chunk in upstream.iter_content(chunk_size=262144):
                            if chunk:
                                self.wfile.write(chunk)
                                self.wfile.flush()
                                last_data_time = time.time()
                            else:
                                if time.time() - last_data_time > 15:  # aumentato da 10 a 15s
                                    print(
                                        "[Proxy Stream] Upstream timeout for channel: " + channel_id)
                                    break
                                select.select([], [], [], 0.1)
                    except (socket.timeout, ConnectionError, BrokenPipeError) as e:
                        print("[Proxy Stream] Downstream error: " + str(e))
                    finally:
                        upstream.close()
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
    """Shutdown the proxy server if running."""
    try:
        response = requests.get(
            PROXY_SHUTDOWN_URL, timeout=2)
        if response.status_code == 200:
            print(" Shutdown request sent successfully")
            return True
    except Exception as e:
        print(" Shutdown via HTTP failed: {}".format(e))

    # Fallback: kill process
    try:
        import subprocess
        subprocess.call(["pkill", "-f", "python.*vavoo_proxy"])
        print(" Killed by pkill")
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
    STOP_EVENT.clear()
    max_restarts = 3
    restart_count = 0

    while restart_count < max_restarts:
        try:
            print("=" * 50)
            print("VAVOO PROXY v1.0 (Attempt " +
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


def run_proxy_in_background():
    """
    Start the proxy in a background thread without blocking the main thread.
    Returns True if the start request was accepted, False if already starting.
    """
    global _starting

    # Simple check: if proxy is running, assume it's OK (don't restart)
    if is_proxy_running():
        print("[Proxy] Already running, skipping")
        return True

    with _starting_lock:
        if _starting:
            print("[Proxy] Already starting, skipping...")
            return False
        _starting = True

    try:
        # Start a fresh proxy thread
        import threading
        proxy_thread = threading.Thread(target=start_proxy, daemon=True)
        proxy_thread.start()
        return True
    finally:
        with _starting_lock:
            _starting = False


if __name__ == "__main__":
    start_proxy()
