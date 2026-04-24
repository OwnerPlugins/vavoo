# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import hashlib
import threading
import time
import os
import random
import json

from enigma import eTimer

from . import __version__


try:
    from .vUtils import debug, error
except ImportError:
    def debug(*args):
        print("[Stats]", *args)

    def error(*args):
        print("[Stats ERROR]", *args)


# Config
# STATS_SERVER_URL = "https://eok6mh4569lds82.m.pipedream.net/"
STATS_SERVER_URL = "https://script.google.com/macros/s/AKfycbz2xuo6WrL9JpVK_YMKDdndQjFrH12K0SzPCd2M7lH7tZzxMGUrtWEm-B9cxy4trU1agQ/exec"
SESSION_ID_FILE = "/tmp/vavoo_session_id"
STATS_DISABLE_FILE = "/etc/enigma2/disable_vavoo_stats"


def _http_post(url, payload):
    try:
        # Python 3
        from urllib.request import Request, urlopen
    except ImportError:
        # Python 2
        from urllib2 import Request, urlopen

    data = json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    req = Request(url, data=data, headers=headers)

    try:
        response = urlopen(req, timeout=10)
        return response.read()
    except Exception as e:
        error("HTTP POST error: {}".format(e))
        return None


class AnonymousStats:
    def __init__(self):
        self._session_id = None
        self._send_timer = None

    def _get_anonymous_session_id(self):
        seed = "{}_{}_{}".format(
            time.time(),
            os.getpid(),
            random.randint(
                1,
                1000000))
        return hashlib.md5(seed.encode('utf-8')).hexdigest()[:16]

    def _is_disabled(self):
        return os.path.exists(STATS_DISABLE_FILE)

    def _should_send_for_session(self):
        if os.path.exists(SESSION_ID_FILE):
            try:
                with open(SESSION_ID_FILE, 'r') as f:
                    return f.read().strip() == self._session_id
            except Exception:
                pass
        return False

    def _mark_session_sent(self):
        try:
            dirname = os.path.dirname(SESSION_ID_FILE)
            if dirname and not os.path.exists(dirname):
                os.makedirs(dirname)
            with open(SESSION_ID_FILE, 'w') as f:
                f.write(self._session_id)
        except Exception:
            pass

    def start_heartbeat(self):
        if self._is_disabled() or hasattr(
                self, '_heartbeat_active') and self._heartbeat_active:
            return

        self._heartbeat_active = True
        debug("Heartbeat started for session: {}".format(
            self._session_id[:16]))
        self._send_heartbeat()

    def _send_heartbeat(self):
        print("[Stats] _send_heartbeat ENTRATO")
        if not getattr(self, '_heartbeat_active', False):
            print("[Stats] Heartbeat non attivo, esco")
            return

        # TEST: __version__
        # print("[DEBUG] _send_heartbeat __version__ vale:", __version__)
        payload = {
            "event": "heartbeat",
            "session_id": self._session_id,
            "plugin_name": "vavoo",
            "plugin_version": "1.64",
            "timestamp": int(time.time()),
            "date": time.strftime("%Y-%m-%d %H:%M:%S")
        }
        # print("[DEBUG] _send_heartbeat Payload plugin_version:", payload["plugin_version"])
        print("[Stats] Sending heartbeat...")
        _http_post(STATS_SERVER_URL, payload)

        if self._heartbeat_active:
            self._heartbeat_timer = eTimer()
            self._heartbeat_timer.callback.append(self._send_heartbeat)
            self._heartbeat_timer.start(60000, True)

    def stop_heartbeat(self):
        self._heartbeat_active = False
        if hasattr(self, '_heartbeat_timer') and self._heartbeat_timer:
            try:
                self._heartbeat_timer.stop()
            except BaseException:
                pass
            self._heartbeat_timer = None
        debug("Heartbeat stopped")

    def _send_in_background(self):
        def _send():
            try:
                if self._is_disabled():
                    debug("Stats disabled by user")
                    return

                if self._should_send_for_session():
                    debug("Stats already sent for this session")
                    return

                payload = {
                    "event": "plugin_startup",
                    "session_id": self._session_id,
                    "plugin_name": "vavoo",
                    "plugin_version": "1.64",
                    "timestamp": int(time.time()),
                    "date": time.strftime("%Y-%m-%d")
                }

                debug("Sending stats to {}...".format(STATS_SERVER_URL))
                debug(
                    "Payload: event={}, session={}, version={}".format(
                        payload['event'],
                        payload['session_id'],
                        payload['plugin_version']))

                result = _http_post(STATS_SERVER_URL, payload)

                if result:
                    self._mark_session_sent()
                    debug("Stats sent successfully!")
                else:
                    error("Stats send failed - no response")

            except Exception as e:
                error("Stats send error: {}".format(e))
                import traceback
                error(traceback.format_exc())

        t = threading.Thread(target=_send)
        t.daemon = True
        t.start()

    def record_startup(self):
        if self._is_disabled():
            debug("Stats disabled")
            return
        self._session_id = self._get_anonymous_session_id()
        debug(
            "Recording startup - Session ID: {}".format(self._session_id[:16]))
        self._send_in_background()


# Singleton
_stats_instance = None


def get_stats_collector():
    global _stats_instance
    if _stats_instance is None:
        _stats_instance = AnonymousStats()
    return _stats_instance


def record_anonymous_startup():
    get_stats_collector().record_startup()


def is_stats_enabled():
    return not os.path.exists(STATS_DISABLE_FILE)


def start_heartbeat():
    collector = get_stats_collector()
    if collector._session_id:
        collector.start_heartbeat()
    else:
        debug("Cannot start heartbeat: no session yet")


def stop_heartbeat():
    get_stats_collector().stop_heartbeat()
