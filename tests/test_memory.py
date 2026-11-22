# -*- coding: utf-8 -*-
"""Memory items: the logo cache cap, the FAT32 file limit, memory in
the guide log line, leftover pause buffers cleaned."""
from __future__ import print_function
import builtins
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, V, NOTES     # noqa: E402
import fakehls                                  # noqa: E402
import vavoo.vavoo_record as vr                 # noqa: E402
vu = harness.plugin.vUtils
plugin = harness.plugin
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
os.environ["no_proxy"] = "127.0.0.1,localhost"
TMP = tempfile.mkdtemp(prefix="vavoo_mem_")

print("== the logo cache is kept to 8 MB, the oldest go first")
cache = os.path.join(TMP, "picons")
os.makedirs(cache)
now = time.time()
for i in range(30):                      # 30 x 500 KB = 15 MB, like the box's
    path = os.path.join(cache, "logo%02d.png" % i)
    with open(path, "wb") as f:
        f.write(b"\x89PNG" + b"\x00" * (500 * 1024 - 4))
    os.utime(path, (now - (30 - i) * 60, now - (30 - i) * 60))
removed = vu.trim_picon_cache(cache)
left = sorted(os.listdir(cache))
size = sum(os.path.getsize(os.path.join(cache, n)) for n in left)
check(size <= vu.PICON_CACHE_MAX and removed == 30 - len(left),
      "down to %d KB (%d deleted)" % (size // 1024, removed))
check(left[0] == "logo%02d.png" % removed and left[-1] ==
      "logo29.png", "the oldest went, the newest stayed")
check(vu.trim_picon_cache(cache) == 0, "already small: nothing deleted")
check(
    vu.trim_picon_cache(
        os.path.join(
            TMP,
            "none")) == 0,
    "no cache folder: nothing")
src = harness.plugin_source()
check("vUtils.trim_picon_cache()" in src.split("def main(session")[
      1].split("def Plugins")[0], "trimmed each time the plugin opens")

print("== FAT32: a file stops before 4 GB")
mounts = os.path.join(TMP, "mounts")
real_open = open


def fake_mounts(text):
    def opener(path, *a, **k):
        if path == "/proc/mounts":
            import io
            return io.StringIO(text)
        return real_open(path, *a, **k)
    return opener


builtins.open = fake_mounts("/dev/sdc1 / vfat rw 0 0\n")
try:
    check(vr.file_size_limit("/whatever") ==
          vr.FAT_LIMIT, "vfat: 4 GB - 64 MB")
finally:
    builtins.open = real_open
builtins.open = fake_mounts("/dev/sda1 / ext4 rw 0 0\n")
try:
    check(vr.file_size_limit("/whatever") == 0, "ext4: no limit")
finally:
    builtins.open = real_open
check(vr.FAT_LIMIT == 4 * 1024 ** 3 - 64 * 1024 ** 2, "the limit itself")

channel = fakehls.FakeChannel()
path = os.path.join(TMP, "fat.ts")
ended = []
rec = vr.Recorder(
    lambda force: channel.url(),
    path,
    max_bytes=300 * 188 * 10,
    info=None,
    env=fakehls.no_proxy_env(),
    on_end=ended.append)
rec.start()
rec.join(40)
size = os.path.getsize(path)
check(
    rec.failure == vr.FAILURE_FAT and ended,
    "stopped at the limit: %r" %
    rec.failure)
check(
    size <= 300 *
    188 *
    10 and size %
    188 == 0 and size > 0,
    "the file whole, under the limit (%d bytes)" %
    size)
check(fakehls.probe_duration(path) > 0.5, "what was recorded plays")
check('max_bytes=vavoo_record.file_size_limit(folder)' in src and src.count(
    "file_size_limit(folder)") == 2, "recordings and the pause buffer both get the limit")
plugin.vavoo_proxy.proxy = type(
    "P", (), {"drop_own_signature": lambda self, s: None})()
del NOTES[:]
rec.slot = "x"
rec.info = {"title": "Show"}
plugin.RECORDINGS._ended(rec)
check(
    NOTES == ["Recording stopped: the disk's 4 GB file limit (FAT32)"],
    "said: %r" %
    NOTES)
channel.close()

print("== memory in the guide line")
note = vu.memory_note()
check(" MB, box " in note and note.endswith("MB free"), "'%s'" % note)
src_u = open(harness.PLUGIN_DIR + "/vUtils.py").read()
_line = src_u[src_u.index('"[EPG] Guide {} loaded'):][:400]
check("memory_note()))" in _line and "source," in _line,
      "the '[EPG] Guide ... loaded' line carries it (and the source)")

print("== pause buffers left behind")
plugin.cfg.record_path = V(TMP)
for name in ("vavoo_pause_1.ts", "vavoo_pause_2.ts"):
    open(os.path.join(TMP, name), "wb").close()
keep = os.path.join(TMP, "vavoo_pause_3.ts")
open(keep, "wb").close()
plugin.ACTIVE["player"] = type(
    "Pl", (), {
        "_shift": type(
            "S", (), {
                "path": keep})()})()
plugin.clean_pause_leftovers()
check(not os.path.exists(os.path.join(TMP, "vavoo_pause_1.ts"))
      and os.path.exists(keep), "old ones deleted, the one in use kept")
plugin.ACTIVE["player"] = None
check("clean_pause_leftovers()" in src.split("def main(session")[
      1].split("def Plugins")[0], "cleaned each time the plugin opens")

shutil.rmtree(TMP, ignore_errors=True)
finish()
