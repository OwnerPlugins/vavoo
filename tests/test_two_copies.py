# -*- coding: utf-8 -*-
"""The plugin's modules loaded twice in one Enigma2 (a box: a second
copy under another module name held port 4323, and the screens - which
read the first copy's proxy - waited for it for ever, "Proxy not ready"
twice a second): the second copy says so in the log, with what loaded
it; the copy whose screens ask takes the port over (/shutdown to the
other one, its own proxy started); a port held by something that is
not a proxy is given up on, with the reason, not tried for ever."""
from __future__ import print_function
import importlib
import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
plugin = harness.plugin
vp = plugin.vavoo_proxy
vu = plugin.vUtils
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


PORT = free_port()
BOOT = os.path.join(harness.DATA, "vavoo_proxy_booting")
CHANNELS = [{"id": u"%d" % i,
             "name": u"Canal %d" % i,
             "url": u"http://x/%d" % i,
             "country": u"Portugal",
             "logo": u"",
             "group": u"Portugal ➾ Geral",
             "epg_id": u""} for i in range(150)]


def prepare(proxy_module, utils_module):
    """A copy's proxy on the test port, a fake catalog, the temp folder."""
    proxy_module.PORT = PORT
    utils_module.PORT = PORT
    proxy_module.BOOTING_FILE = BOOT       # (one file for all, as on a box)
    proxy_module.CATALOG_FILE = vp.CATALOG_FILE
    proxy_module.catalog_setting = lambda: "auto"
    proxy_module.VavooProxy._download_catalog = lambda self, setting: (
        list(CHANNELS), "geil")
    proxy_module.VavooProxy.refresh_addon_sig_if_needed = \
        lambda self, force=False: None


class Tee(object):
    """stdout, kept: the log lines a copy writes."""

    def __init__(self, out):
        self.out = out
        self.lines = []

    def write(self, text):
        self.lines.append(text)
        self.out.write(text)

    def flush(self):
        self.out.flush()

    def text(self):
        return "".join(self.lines)


def wait(condition, seconds=10):
    end = time.time() + seconds
    while time.time() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


prepare(vp, vu)
if os.path.exists(vp.CATALOG_FILE):
    os.remove(vp.CATALOG_FILE)

print("== the modules loaded a second time, under another name")
copies = os.path.join(harness.DATA, "copies")
try:
    os.makedirs(copies)
except OSError:
    pass
link = os.path.join(copies, "vavoo_copy")
if not os.path.exists(link):
    os.symlink(os.path.dirname(os.path.abspath(vp.__file__)), link)
sys.path.insert(0, copies)
tee = Tee(sys.stdout)
sys.stdout = tee
try:
    bvp = importlib.import_module("vavoo_copy.vavoo_proxy")
finally:
    sys.stdout = tee.out
bvu = sys.modules["vavoo_copy.vUtils"]
sys.modules["vavoo_copy.vavoo_store"].set_paths(
    harness.DATA, None, os.path.join(harness.DATA, "tiles"))
prepare(bvp, bvu)
check(bvp is not vp and bvp.INSTANCE_ID != vp.INSTANCE_ID,
      "two copies, each its own INSTANCE_ID")
said = tee.text()
check("Second copy of the plugin: vavoo_copy.vUtils" in said and
      "first: vavoo.vUtils" in said,
      "the log says which copy came second and which was first")
check("test_two_copies.py" in said,
      "...and what loaded it (the import's stack)")

print("== the second copy holds the port (the box)")
tee = Tee(sys.stdout)
sys.stdout = tee
bvp.proxy = bvp.VavooProxy()
import threading                                # noqa: E402
other = threading.Thread(target=bvp._proxy_thread_main)
other.daemon = True
other.start()
check(
    wait(
        lambda: bvp.proxy_state()["ready"]),
    "the second copy's proxy is up")
vp.proxy = vp.VavooProxy()
check(vp.is_proxy_port_listening() and not vp.serving_here() and
      not vu.is_proxy_ready(),
      "the port answers, but this copy's own proxy is not up: not ready "
      "(the list waited for ever)")
holder = vp.port_holder()
check(holder and holder.get("instance") == bvp.INSTANCE_ID and
      holder.get("module") == "vavoo_copy.vavoo_proxy" and
      holder.get("pid") == os.getpid(),
      "/status says whose proxy it is: %r" %
      (holder and holder.get("module")))

print("== this copy takes the port over")
check(vp.run_proxy_in_background() is True, "run_proxy_in_background(): True")
check(wait(lambda: vp.proxy_state()["ready"]),
      "this copy's proxy is up: ready in this process")
holder = vp.port_holder()
check(holder and holder.get("instance") == vp.INSTANCE_ID,
      "the port is this copy's now")
check(bvp.proxy.is_stopped() and not bvp.serving_here(),
      "the other copy's proxy stopped")
said = tee.text()
check("taking over" in said and "held by another copy" in said,
      "the log says so (taking over / held by another copy)")
check(not vp.is_proxy_booting(), "no booting marker left")
calls = []
real_spawn = vp._spawn_proxy_thread
vp._spawn_proxy_thread = lambda: calls.append(1) or True
check(vp.run_proxy_in_background() is True and not calls,
      "asked again: its own proxy serves, nothing started")
vp._spawn_proxy_thread = real_spawn

print("== a port held by something that is not a proxy")
vp.shutdown_proxy()
check(wait(lambda: not vp.is_proxy_port_listening()), "proxy stopped, port free")
blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
blocker.bind(("127.0.0.1", PORT))
blocker.listen(5)               # (connects, never answers)
vp.proxy = vp.VavooProxy()
started = time.time()
check(vp.run_proxy_in_background() is True, "a start asked")
check(wait(lambda: "is taken by another program" in tee.text(), 15),
      "given up with the reason, after %.1f s" % (time.time() - started))
check(wait(lambda: not vp.is_proxy_booting(), 5), "booting marker removed")
check(not vp.serving_here(), "nothing of this copy serving")
sys.stdout = tee.out
blocker.close()
finish()
