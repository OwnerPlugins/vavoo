# -*- coding: utf-8 -*-
"""The proxy started for real (start_proxy() in its own thread, as
run_proxy_in_background() does) on a free port with a fake catalog:
it comes up, answers, says it is ready in this process, and stops -
on Python 2 too, where its own "[✓] Ready" line used to stop it."""
from __future__ import print_function
import json
import os
import socket
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
plugin = harness.plugin
vu = plugin.vUtils
vp = plugin.vavoo_proxy
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = free_port()
vp.PORT = PORT
vu.PORT = PORT
vp.BOOTING_FILE = os.path.join(harness.DATA, "vavoo_proxy_booting")
vp.catalog_setting = lambda: "auto"
CHANNELS = [{"id": u"%d" % i, "name": u"Canal %d Más" % i, "url": u"http://x/%d" % i,
             "country": u"Portugal", "logo": u"", "group": u"Portugal ➾ Geral", "epg_id": u""}
            for i in range(150)]
vp.VavooProxy._download_catalog = lambda self, setting: (list(CHANNELS), "geil")
vp.VavooProxy.refresh_addon_sig_if_needed = lambda self, force=False: None


def get(path):
    return urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=5)


print("== start_proxy() for real")
if os.path.exists(vp.CATALOG_FILE):
    os.remove(vp.CATALOG_FILE)
vp._catalog_digest[0] = None
vp.proxy = vp.VavooProxy()
thread = threading.Thread(target=vp._proxy_thread_main)
thread.daemon = True
thread.start()
state = {}
for _i in range(100):
    state = vp.proxy_state()
    if state.get("ready"):
        break
    time.sleep(0.05)
check(state.get("ready") and state.get("channels_count") == 150, "up and ready (in this process): %r"
      % dict((k, state.get(k)) for k in ("ready", "listening", "channels_count")))
check(vu.is_proxy_ready() and vu.is_proxy_running(), "is_proxy_ready() / the port")
check(not vp.is_proxy_booting(), "the booting marker is gone")
status = json.loads(get("/status").read().decode("utf-8"))
check(status.get("initialized") and status.get("channels_count") == 150 and status.get("catalog_source") == "geil",
      "/status answers")
rows = json.loads(get("/channels?country=Portugal").read().decode("utf-8"))
check(len(rows) == 150, "/channels answers (%d)" % len(rows))
check(os.path.exists(vp.CATALOG_FILE), "the catalog saved for the next start")
check(thread.is_alive(), "still serving")

print("== stop")
vp.shutdown_proxy()
thread.join(5)
check(not thread.is_alive(), "the server thread ended")
check(not vp.proxy_state()["listening"] and not vu.is_proxy_ready(), "not listening, not ready")

print("== the next start: the saved catalog at once")
vp.VavooProxy._download_catalog = lambda self, setting: (time.sleep(1.5), (list(CHANNELS[:120]), "geil"))[1]
vp.proxy = vp.VavooProxy()
t0 = time.time()
thread = threading.Thread(target=vp._proxy_thread_main)
thread.daemon = True
thread.start()
for _i in range(100):
    if vp.proxy_state().get("ready"):
        break
    time.sleep(0.02)
took = time.time() - t0
check(vp.proxy_state().get("ready") and vp.proxy_state()["channels_count"] == 150 and took < 1.0,
      "ready in %.2f s with the saved 150, the download (1.5 s) still going" % took)
for _i in range(150):
    if vp.proxy_state()["channels_count"] == 120:
        break
    time.sleep(0.05)
check(vp.proxy_state()["channels_count"] == 120 and vp.proxy_state()["catalog_version"] == 2,
      "then the new catalog in, behind it (version 2)")
vp.shutdown_proxy()
thread.join(5)
check(not thread.is_alive(), "stopped again")
finish()
