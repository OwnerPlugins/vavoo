# -*- coding: utf-8 -*-
"""The proxy's state read in this process (vavoo_proxy.proxy_state(),
vUtils.get_proxy_status() / is_proxy_ready()) - no HTTP from the GUI
thread - and what the screens say with it: the status line, the start
screen, the watchdog."""
from __future__ import print_function
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session  # noqa: E402
plugin = harness.plugin
vu = plugin.vUtils
vp = plugin.vavoo_proxy

print("== proxy_state(): from the instance, no HTTP")
calls = []


def no_http(*a, **k):
    calls.append(a)
    raise AssertionError("HTTP asked")


real_get_url, vu.getUrl = vu.getUrl, no_http
real_running, vu.is_proxy_running = vu.is_proxy_running, no_http
real_proxy = vp.proxy
p = vp.VavooProxy()
vp.proxy = p
p.initialized = False
p.server = None
state = vp.proxy_state()
check(set(("initialized",
           "channels_count",
           "catalog_source",
           "token_required",
           "addon_sig_valid",
           "addon_sig_age",
           "booting",
           "listening",
           "ready")) <= set(state),
      "every field: %s" % sorted(state))
check(not state["ready"] and not state["listening"],
      "no server yet: not listening, not ready")
p.initialized = True
check(
    not vp.proxy_state()["ready"],
    "a catalog but no server (the moment before it binds): not ready")
p.server = object()
p.all_filtered_items = [1, 2, 3]
p.catalog_source = "geil"
state = vp.proxy_state()
check(state["ready"] and state["listening"] and state["channels_count"]
      == 3, "server and catalog: ready (3 channels)")
check(vu.is_proxy_ready() is True and vu.is_proxy_ready(
    timeout=0.5) is True, "vUtils.is_proxy_ready(): True")
check(vu.get_proxy_status()["catalog_source"] ==
      "geil", "vUtils.get_proxy_status(): the same state")
check(state["token_required"] is False, "Geil: no token needed")
check(set(vp.status_of(p)) == set(("initialized",
                                   "channels_count",
                                   "catalog_source",
                                   "token_required",
                                   "addon_sig_valid",
                                   "addon_sig_age",
                                   "local_ip",
                                   "port")),
      "status_of(): what /status answers, unchanged")
p.stop()
check(not vp.proxy_state()["listening"] and vu.is_proxy_ready(
) is False, "stopped: not listening, not ready")
vp.proxy = vp.VavooProxy()
check(vu.is_proxy_ready() is False,
      "a restart's new instance (no catalog yet): not ready")
check(not calls, "no HTTP request at all (%d)" % len(calls))
vu.getUrl = real_get_url
vu.is_proxy_running = real_running

print("== the status line")


def text(*a):
    return plugin.to_text(plugin.proxy_status_text(*a))   # (bytes on Python 2)


check(text(None) == "? Proxy Unknown", "nothing read: unknown")
check(text({"booting": True, "ready": False}) ==
      "Loading channels...", "starting: 'Loading channels...'")
check(text({"listening": True, "initialized": False, "ready": False})
      == "Loading channels...", "listening without a catalog: loading")
check(text({"booting": False, "listening": False, "ready": False})
      == u"✗ Proxy Offline", "stopped: offline")
geil = {"ready": True, "token_required": False, "channels_count": 9818}
check(text(geil) == u"✓ Geil OK · 9818 ch", "Geil: %r" % text(geil))
check(text(geil, 9000) == u"✓ Geil OK · 9000 ch",
      "the main list's own total when it has one")
vavoo = {
    "ready": True,
    "token_required": True,
    "addon_sig_valid": True,
    "addon_sig_age": 100,
    "channels_count": 5}
check(text(vavoo) == u"✓ Vavoo OK · 5 ch", "Vavoo with a fresh token")
check(
    "token expiring" in text(
        dict(
            vavoo,
            addon_sig_age=600)),
    "Vavoo, token about to run out")
check(text(dict(vavoo, addon_sig_valid=False)) ==
      u"✗ Proxy Error", "Vavoo with no token: error")

print("== the start screen and the watchdog")
plugin.get_proxy_status = lambda: {"ready": True, "channels_count": 42}
start = make(plugin.startVavoo, Session())
start._check_ready()
check(
    "42" in plugin.to_text(
        start["status"].text),
    "start screen: done as soon as the proxy is ready: %r" %
    start["status"].text)
plugin.get_proxy_status = lambda: {"ready": False, "booting": True}
start = make(plugin.startVavoo, Session())
start._elapsed_ms = 0
start._check_ready()
check(
    "42" not in plugin.to_text(
        start["status"].text),
    "not ready: keeps waiting")
plugin.get_proxy_status = vu.get_proxy_status

restarts = []
plugin.run_proxy_in_background = lambda: restarts.append(1) or True
plugin.is_proxy_running = lambda: False
plugin.is_proxy_booting = lambda: True
main = make(plugin.MainVavoo, Session())
del restarts[:]                 # (opening MainVavoo starts the proxy itself)
main._proxy_watchdog_check()
check(
    not restarts and plugin.to_text(
        main["proxy_status"].text) == u"Loading channels...",
    "port closed while starting: no restart, 'Loading channels...'")
plugin.is_proxy_booting = lambda: False
main._proxy_watchdog_check()
check(restarts == [1] and plugin.to_text(main["proxy_status"].text) == u"Starting the proxy...",
      "port closed and not starting: restarted, 'Starting the proxy...' (no false 'Restarted')")
vp.proxy = real_proxy
finish()
