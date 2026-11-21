# -*- coding: utf-8 -*-
"""The audit's fixes: the proxy's controls only from the box itself,
the disks read from /proc/mounts (autofs, links), the package's postrm
only on a real removal."""
from __future__ import print_function
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
plugin = harness.plugin
vp = plugin.vavoo_proxy
vr = plugin.vavoo_record
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
try:
    from urllib.request import Request, build_opener, ProxyHandler
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import Request, build_opener, ProxyHandler, HTTPError

print("== the proxy's controls: only the box itself")
check(vp.is_loopback("127.0.0.1") and vp.is_loopback("127.1.2.3") and vp.is_loopback("::1")
      and vp.is_loopback("::ffff:127.0.0.1"), "loopback addresses")
check(not vp.is_loopback("192.168.1.20") and not vp.is_loopback("::ffff:10.0.0.2")
      and not vp.is_loopback("") and not vp.is_loopback(None), "the network's are not")


class FakeProxy(object):
    def __init__(self):
        self.refreshed = 0
        self._stop_event = threading.Event()

    def is_stopped(self):
        return False

    def refresh_addon_sig_if_needed(self, force=False):
        self.refreshed += 1
        return "SIG"


fake = FakeProxy()
vp.proxy = fake
server = vp.ThreadedHTTPServer(("127.0.0.1", 0), vp.VavooHTTPHandler)
threading.Thread(target=server.serve_forever).start()
base = "http://127.0.0.1:%d" % server.server_address[1]


def get(path):
    try:
        r = build_opener(ProxyHandler({})).open(Request(base + path), timeout=10)
        return r.getcode(), r.read()
    except HTTPError as e:
        return e.code, b""


code, body = get("/refresh_token")
check(code == 200 and fake.refreshed == 1, "/refresh_token from 127.0.0.1: done (%s)" % code)
real_loopback = vp.is_loopback
vp.is_loopback = lambda address: False         # as if from 192.168.1.20
code, body = get("/refresh_token")
check(code == 403 and fake.refreshed == 1, "...from the network: 403, nothing done (%s)" % code)
code, body = get("/shutdown")
check(code == 403 and not fake._stop_event.is_set() and not vp.STOP_EVENT.is_set(),
      "/shutdown from the network: 403, the proxy goes on")
code, body = get("/status")
check(code != 403, "other paths still answer the network (%s)" % code)
vp.is_loopback = real_loopback
server.shutdown()

print("== the disks, from /proc/mounts")
TMP = tempfile.mkdtemp(prefix="vavoo_audit_")
MOUNTS = []
real_points = vr.mount_points
vr.mount_points = lambda: list(MOUNTS)
real_isdir = os.path.isdir
plugin.os.path.isdir = lambda p: p.startswith("/media/") or real_isdir(p)
MOUNTS[:] = [("/", "ubifs"), ("/tmp", "tmpfs"), ("/media/hdd", "ext4"),
             ("/media/autofs/sdb1", "vfat"), ("/media/net/nas", "nfs"), ("/media/hdd", "ext4"),
             ("/media/ram", "tmpfs"), ("/media/cifs", "cifs")]
check(plugin.media_mounts() == ["/media/autofs/sdb1", "/media/hdd"],
      "local disks only, an autofs one too: %r" % plugin.media_mounts())
check(plugin.media_mounts(network=True) == ["/media/autofs/sdb1", "/media/cifs", "/media/hdd", "/media/net/nas"],
      "with the network shares (by their file system): %r" % plugin.media_mounts(network=True))
plugin.os.path.isdir = real_isdir
vr.mount_points = real_points
check(vr._unescape_mount("/media/My\\040Disk") == "/media/My Disk", "a space in a mount point")
here = vr.mount_points()
check(here and any(point == "/" for point, _fs in here), "this machine's /proc/mounts read (%d)" % len(here))
check(vr.mount_of("/")[0] == "/" and vr.mount_of("/")[1], "mount_of() still works: %r" % (vr.mount_of("/"),))

print("== the package's postrm: only a real removal")
POSTRM = os.path.join(harness.REPO, "CONTROL", "postrm")
fakebin = os.path.join(TMP, "bin")
os.makedirs(fakebin)
log = os.path.join(TMP, "calls.log")
for tool in ("rm", "find", "wget"):
    path = os.path.join(fakebin, tool)
    with open(path, "w") as f:
        f.write('#!/bin/sh\necho "%s $*" >> "%s"\n' % (tool, log))
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
env = dict(os.environ, PATH=fakebin + os.pathsep + os.environ.get("PATH", ""))


def postrm(*args):
    if os.path.exists(log):
        os.remove(log)
    subprocess.call(["sh", POSTRM] + list(args), env=env,
                    stdout=open(os.devnull, "w"), stderr=subprocess.STDOUT)
    return open(log).read().splitlines() if os.path.exists(log) else []


for arg in ("upgrade", "failed-upgrade", "abort-install", "abort-upgrade"):
    check(postrm(arg) == [], "postrm %s: nothing deleted" % arg)
calls = postrm("remove")
check(any(c.startswith("find /etc/enigma2") and "userbouquet.vavoo_" in c for c in calls)
      and any(c.startswith("rm -f /etc/enigma2/vavoo_epg_cache.json") for c in calls),
      "postrm remove: the bouquets and caches go (%d calls)" % len(calls))
check(not any("vavoo_favourites" in c or "vavoo_parental" in c for c in calls), "...never the favourites / PIN")
check(postrm() != [], "no argument (opkg's old ones): removes too")
PREINST = os.path.join(harness.REPO, "CONTROL", "preinst")
runs = [line for line in open(PREINST).read().splitlines()
        if not line.strip().startswith("#") and ("opkg update" in line or "opkg install" in line)]
check(subprocess.call(["sh", "-n", PREINST]) == 0 and not runs,
      "preinst: valid, no opkg run inside opkg")

print("== the background copied without a shell")
src = harness.plugin_source()
check("os_system" not in src and "shutil.copyfile(baknew" in src, "add_skin_back(): shutil")
back = os.path.join(TMP, "back")
os.makedirs(back)
open(os.path.join(back, "my back.png"), "wb").write(b"PNG")
real_back = plugin.BackPath
plugin.BackPath = back
plugin.add_skin_back("my back.png")
check(open(os.path.join(back, "default.png"), "rb").read() == b"PNG", "a name with a space: copied")
plugin.add_skin_back("missing.png")
check(True, "a missing one: nothing, no error")
plugin.BackPath = real_back

shutil.rmtree(TMP, ignore_errors=True)
finish()
