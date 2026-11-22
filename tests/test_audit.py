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
check(vp.is_loopback("127.0.0.1") and vp.is_loopback("127.1.2.3") and vp.is_loopback(
    "::1") and vp.is_loopback("::ffff:127.0.0.1"), "loopback addresses")
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
        r = build_opener(
            ProxyHandler(
                {})).open(
            Request(
                base +
                path),
            timeout=10)
        return r.getcode(), r.read()
    except HTTPError as e:
        return e.code, b""


code, body = get("/refresh_token")
check(
    code == 200 and fake.refreshed == 1,
    "/refresh_token from 127.0.0.1: done (%s)" %
    code)
real_loopback = vp.is_loopback
vp.is_loopback = lambda address: False         # as if from 192.168.1.20
code, body = get("/refresh_token")
check(
    code == 403 and fake.refreshed == 1,
    "...from the network: 403, nothing done (%s)" %
    code)
code, body = get("/shutdown")
check(
    code == 403 and not fake._stop_event.is_set() and not vp.STOP_EVENT.is_set(),
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
check(
    plugin.media_mounts(
        network=True) == [
            "/media/autofs/sdb1",
            "/media/cifs",
            "/media/hdd",
            "/media/net/nas"],
    "with the network shares (by their file system): %r" %
    plugin.media_mounts(
        network=True))
plugin.os.path.isdir = real_isdir
vr.mount_points = real_points
check(vr._unescape_mount("/media/My\\040Disk") ==
      "/media/My Disk", "a space in a mount point")
here = vr.mount_points()
check(
    here and any(
        point == "/" for point,
        _fs in here),
    "this machine's /proc/mounts read (%d)" %
    len(here))
check(vr.mount_of("/")[0] == "/" and vr.mount_of("/")[1],
      "mount_of() still works: %r" % (vr.mount_of("/"),))

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
check(
    not any(
        "vavoo_favourites" in c or "vavoo_parental" in c for c in calls),
    "...never the favourites / PIN")
check(postrm() != [], "no argument (opkg's old ones): removes too")
PREINST = os.path.join(harness.REPO, "CONTROL", "preinst")
runs = [line for line in open(PREINST).read().splitlines() if not line.strip(
).startswith("#") and ("opkg update" in line or "opkg install" in line)]
check(subprocess.call(["sh", "-n", PREINST]) == 0 and not runs,
      "preinst: valid, no opkg run inside opkg")

print("== the background copied without a shell")
src = harness.plugin_source()
check(
    "os_system" not in src and "shutil.copyfile(baknew" in src,
    "add_skin_back(): shutil")
back = os.path.join(TMP, "back")
os.makedirs(back)
open(os.path.join(back, "my back.png"), "wb").write(b"PNG")
real_back = plugin.BackPath
plugin.BackPath = back
harness.REAL_ADD_SKIN_BACK("my back.png")
check(
    open(
        os.path.join(
            back,
            "default.png"),
        "rb").read() == b"PNG",
    "a name with a space: copied")
harness.REAL_ADD_SKIN_BACK("missing.png")
check(True, "a missing one: nothing, no error")
plugin.BackPath = real_back

print("== no screen attribute hides a dict method (Enigma2's Screen is a dict)")
import re                                       # noqa: E402
hiding = []
for module in harness.ui_modules():
    path = module.__file__[
        :-1] if module.__file__.endswith(".pyc") else module.__file__
    for number, line in enumerate(open(path).read().splitlines(), 1):
        if re.search(
                r"\bself\.(%s)\s*=[^=]" %
                "|".join(
                    harness.DICT_NAMES),
                line):
            hiding.append(
                "%s:%d: %s" %
                (os.path.basename(
                    module.__file__),
                    number,
                    line.strip()))
for line in hiding:
    print("  " + line)
check(
    not hiding,
    "self.items / self.keys / self.get ... = never set (%d)" %
    len(hiding))

print("== what the fake Enigma2 cannot show")
import ast                                      # noqa: E402
import glob                                     # noqa: E402
PLUGIN = harness.PLUGIN_DIR
store = harness.store
UI_FILES = [os.path.join(PLUGIN, "plugin.py")] + \
    sorted(glob.glob(os.path.join(PLUGIN, "ui_*.py")))
CODE_FILES = UI_FILES + [os.path.join(PLUGIN,
                                      n) for n in ("vUtils.py",
                                                   "bouquet_manager.py",
                                                   "vavoo_proxy.py",
                                                   "notification_system.py",
                                                   "vavoo_store.py",
                                                   "vavoo_record.py",
                                                   "vavoo_stats.py",
                                                   "__init__.py")]


def read(path):
    with open(path) as f:
        return f.read()


# every setting used is declared (the fake makes an undeclared one up; a
# box raises AttributeError)
base = read(os.path.join(PLUGIN, "ui_base.py"))
declared = set(re.findall(r"^cfg\.([a-z_0-9]+)\s*=", base, re.M))
undeclared = []
for path in CODE_FILES:
    for number, line in enumerate(read(path).splitlines(), 1):
        code = line.split("#", 1)[0]
        for name in re.findall(r"\bcfg\.([a-z_0-9]+)\b", code):
            if name not in declared and name not in ("dict",):
                undeclared.append(
                    "%s:%d cfg.%s" %
                    (os.path.basename(path), number, name))
check(not undeclared,
      "every cfg.<setting> used is declared in ui_base.py (%s)" % undeclared[:5])


def is_text(node):
    if hasattr(ast, "Constant") and isinstance(node, ast.Constant):
        return isinstance(node.value, (type(u""), type("")))
    if hasattr(ast, "Str") and not hasattr(ast, "Constant"):
        return isinstance(node, ast.Str)
    return False


def plain(node):
    """A literal text (or literals joined with +): what xgettext finds."""
    if is_text(node):
        return True
    return isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and \
        plain(node.left) and plain(node.right)


not_found = []
for path in UI_FILES + [os.path.join(PLUGIN, n)
                        for n in ("vUtils.py", "bouquet_manager.py")]:
    tree = ast.parse(read(path), path)
    for node in ast.walk(tree):
        if isinstance(
                node,
                ast.Call) and isinstance(
                node.func,
                ast.Name) and node.func.id == "_":
            if len(node.args) != 1 or not plain(node.args[0]):
                not_found.append("%s:%d" %
                                 (os.path.basename(path), node.lineno))
check(
    not not_found,
    "_() only on literal texts - the translations find them (%s)" %
    not_found)

# every data file of the plugin is deleted by a factory reset
names = set()
for path in CODE_FILES:
    text = read(path)
    names.update(re.findall(r"data_file\(\s*[\"']([^\"']+)[\"']", text))
    names.update(
        re.findall(
            r"join\(\s*ENIGMA_PATH\s*,\s*[\"']([^\"']+)[\"']", text))
names.discard("epgimport.conf")             # EPGImport's own, shared
names = sorted(n for n in names if not n.startswith("bouquets."))
not_reset = [n for n in names if n not in store.RESET_FILES]
check(
    names and not not_reset,
    "every data file is in vavoo_store.RESET_FILES (%d; missing %s)" %
    (len(names),
     not_reset))
check(not any(n.startswith(store.BACKUP_PREFIX) for n in store.RESET_FILES) and
      "disable_vavoo_stats" not in store.RESET_FILES,
      "...and not the backups nor the statistics choice")

print("== the release: one version everywhere, the installer from this repository")
REPO = harness.REPO
version = re.search(
    r'__version__ = "([^"]+)"',
    read(
        os.path.join(
            PLUGIN,
            "__init__.py"))).group(1)
installer = read(os.path.join(REPO, "installer.sh"))
spots = {
    "CONTROL/control": re.search(
        r"^Version: (\S+)",
        read(
            os.path.join(
                REPO,
                "CONTROL",
                "control")),
        re.M).group(1),
    "installer.sh": re.search(
        r"^version='([^']+)'",
        installer,
        re.M).group(1),
    "the .bb VER": re.search(
        r'^VER = "([^"]+)"',
        read(
            os.path.join(
                REPO,
                "enigma2-plugin-extensions-vavoo.bb")),
        re.M).group(1),
    "README badge": re.search(
        r"badge/Version-([0-9.]+)-",
        read(
            os.path.join(
                REPO,
                "README.md"))).group(1),
}
check(all(v == version for v in spots.values()),
      "version %s in every place %r" % (version, spots))
check(
    read(
        os.path.join(
            REPO,
            "README.md")) == read(
                os.path.join(
                    PLUGIN,
                    "readme.md")),
    "README.md and the plugin's readme.md are the same")
check(
    plugin.vUtils.is_remote_version_newer(
        "1.89",
        version),
    "%s is newer than 1.89 for the update check" %
    version)
check(
    "github.com/OwnerPlugins/vavoo/archive/refs/heads/main.tar.gz" in installer,
    "installer.sh downloads OwnerPlugins/vavoo")
check(
    "/etc/enigma2/vavoo_favourites.json" in installer and "/etc/enigma2/vavoo_bouquet_list.txt" in installer,
    "...and keeps an old install's favourites / bouquet list in /etc/enigma2")
check(subprocess.call(["sh", "-n", os.path.join(REPO,
      "installer.sh")]) == 0, "installer.sh: valid shell")

print(
    "== the installer's compile check (this Python: %d)" %
    sys.version_info[0])
check("py_compile" not in installer.split("COMPILE_CHECK=", 1)[1],
      "it does not need py_compile (missing on OpenATV 8.1's Python 3)")
code = re.search(r"^COMPILE_CHECK='(.*?)'$", installer, re.S | re.M).group(1)
tools = re.findall(r'"([a-z_]+\.py)"', code.split("try:", 1)[0])


def compile_check(folder):
    process = subprocess.Popen([sys.executable,
                                "-c",
                                code,
                                folder],
                               stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
    out = process.communicate()[0].decode("utf-8", "replace")
    return process.returncode, out


rc, out = compile_check(PLUGIN)
check(
    rc == 0, "the plugin's own .py files all compile (exit %s: %s)" %
     (rc, out.strip()))
broken = os.path.join(TMP, "broken")
os.makedirs(broken)
with open(os.path.join(broken, "ok.py"), "w") as f:
    f.write("x = 1\n")
with open(os.path.join(broken, "bad.py"), "w") as f:
    f.write("x = (\n")
with open(os.path.join(broken, "update_translations.py"), "w") as f:
    f.write("x = (\n")
rc, out = compile_check(broken)
check(
    rc == 1 and "bad.py" in out and "update_translations" not in out,
    "a broken file: exit 1, named; the repository tools not checked (%s: %s)" %
    (rc,
     out.strip()))
rc, out = compile_check(os.path.join(TMP, "missing"))
check(rc == 2, "no folder: exit 2, 'not run' - not 'does not compile' (%s)" % rc)
imported = []
for path in CODE_FILES:
    for tool in tools:
        name = tool[:-3]
        if re.search(r"(import|from)\s+\.?%s\b" % name, read(path)):
            imported.append("%s imports %s" % (os.path.basename(path), name))
check(
    tools and not imported,
    "the tools it skips are never imported by the plugin (%s)" %
    imported)

shutil.rmtree(TMP, ignore_errors=True)
finish()
