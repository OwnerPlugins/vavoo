# -*- coding: utf-8 -*-
"""The memory watch: the 30-minute [MEM] line, the low-memory report
(kept in /etc/enigma2), its spacing and size cap, the release."""
from __future__ import print_function
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, store        # noqa: E402
vu = harness.plugin.vUtils
plugin = harness.plugin
TMP = tempfile.mkdtemp(prefix="vavoo_mw_")
store.set_paths(TMP, None, os.path.join(TMP, "tiles"))

print("== reading the box's memory")
info = vu.read_meminfo()
check(
    info.get(
        "MemTotal",
        0) > 0 and "MemAvailable" in info,
    "/proc/meminfo read (%d fields)" %
    len(info))
rows = vu.process_memory()
check(rows and rows == sorted(rows, reverse=True) and all(
    r[0] > 0 for r in rows), "processes by memory, biggest first: %r" % rows[:2])
fake_proc = os.path.join(TMP, "proc")
for pid, name, rss in (("1", "init", 108), ("801",
                       "zerotier-one", 6872), ("20260", "enigma2", 703608)):
    os.makedirs(os.path.join(fake_proc, pid))
    with open(os.path.join(fake_proc, pid, "status"), "w") as f:
        f.write("Name:\t%s\nState:\tS\nVmRSS:\t%d kB\n" % (name, rss))
os.makedirs(os.path.join(fake_proc, "self"))
meminfo = os.path.join(TMP, "meminfo")
with open(meminfo, "w") as f:
    f.write("MemTotal:  948736 kB\nMemFree: 1000 kB\nMemAvailable: 32768 kB\nShmem: 56384 kB\nSlab: 30796 kB\n")
report = vu.memory_report(fake_proc, meminfo)
lines = report.splitlines()
check(
    "free 32 MB of 926 MB, Shmem (/tmp) 55 MB, Slab 30 MB" in lines[0],
    "first line: %r" %
    lines[0])
check(
    "687 MB  enigma2 (20260)" in lines[1] and "zerotier-one" in lines[2] and "init" in lines[3],
    "then who holds it, biggest first: %r" %
    lines[1])

print("== the watch")
plugin.read_meminfo_real = vu.read_meminfo
avail = {"kb": 400 * 1024}
vu.read_meminfo = lambda path="/proc/meminfo": {
    "MemAvailable": avail["kb"], "MemTotal": 948736}
logged = []
real_print = plugin.print
plugin.print = lambda *a, **k: logged.append(" ".join(str(x) for x in a))
reports = []
vu.memory_report = lambda proc="/proc", meminfo="/proc/meminfo": "REPORT %d\n" % len(
    reports.append(1) or reports)
w = plugin._MemoryWatch()
t0 = 1000000.0
w.tick(t0)
check(any(line.startswith("[MEM] ") for line in logged),
      "first tick: a [MEM] line %r" % logged[-1:])
n = len(logged)
w.tick(t0 + 30)
check(len(logged) == n, "not read again within a minute")
for minute in range(1, 30):
    w.tick(t0 + minute * 60)
check(len(logged) == n and not reports,
      "plenty free: nothing more for 30 minutes, no report")
w.tick(t0 + 1800)
check(len(logged) == n + 1, "after 30 minutes: the next [MEM] line")
path = plugin.memory_log_file()
check(path == os.path.join(TMP, "vavoo_memory.log")
      and not os.path.exists(path), "no report file while all is well")

released = []
real_release = vu.release_guides
vu.release_guides = lambda keep=None: (released.append(keep), 2)[1]
trimmed = []
vu.trim_picon_cache = lambda max_bytes=0, **k: trimmed.append(max_bytes)
plugin._icon_cache.update({("a", 1, 1): object(), ("b", 1, 1): object()})
plugin.ACTIVE["player"] = type("P", (), {"country_code": "pt"})()
avail["kb"] = 60 * 1024
w.tick(t0 + 1900)
check(reports == [1] and open(path).read() == "REPORT 1\n",
      "below 100 MB: the report written to /etc/enigma2")
check(released == ["pt"] and not plugin._icon_cache and trimmed == [4 * 1024 * 1024],
      "released: the guides but the one watched, the icons, the logos down to 4 MB")
check(any("Low memory" in line for line in logged) and any(
    "Released 2 guides, 2 icons" in line for line in logged), "said in the log")
w.tick(t0 + 1900 + 120)
check(reports == [1], "not again within 10 minutes")
w.tick(t0 + 1900 + 601)
check(reports == [1, 1] or len(reports) == 2,
      "after 10 minutes, still low: a second report")
plugin.ACTIVE["player"] = None

print("== the report file stays small")
with open(path, "w") as f:
    f.write(("x" * 99 + "\n") * 700)          # 70 KB
plugin.write_memory_log("LAST REPORT\n")
data = open(path).read()
check(len(data) <= plugin.MEMORY_LOG_MAX and data.endswith("LAST REPORT\n")
      and data.startswith("x"), "cut to the newest part, whole lines (%d bytes)" % len(data))

print("== guides: three kept, released but the one watched")
vu.release_guides = real_release


class FakeGuide(object):
    def __init__(self, code):
        self.code = code
        self.last_used = time.time()

    def age(self):
        return 0


vu._download_epg_guide = lambda code: FakeGuide(code)
vu._epg_guide_cache.clear()
vu._epg_guide_failed.clear()
for i, code in enumerate(("fr", "pt", "it")):
    vu.load_epg_guide(code).last_used = 1000 + i
check(
    vu._EPG_GUIDE_KEEP == 3 and sorted(
        vu._epg_guide_cache) == [
            "fr",
            "it",
            "pt"],
    "three in memory")
# fr used again: pt is now the oldest
vu.peek_epg_guide("fr")
vu.load_epg_guide("de")
check(
    sorted(
        vu._epg_guide_cache) == [
            "de",
            "fr",
            "it"],
    "a fourth: the least used (pt) went")
check(vu.release_guides("IT") == 2 and list(vu._epg_guide_cache)
      == ["it"], "released: only the watched one left")
check(
    vu.release_guides() == 1 and not vu._epg_guide_cache,
    "nothing watched: all go")
plugin.print = real_print
vu.read_meminfo = plugin.read_meminfo_real
shutil.rmtree(TMP, ignore_errors=True)
finish()
