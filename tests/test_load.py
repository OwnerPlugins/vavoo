# -*- coding: utf-8 -*-
"""The box-load changes: the guide parse rests (same result), the
guide is reused for 6 hours, thread names, slow-match log, ffmpeg at a
lower priority."""
from __future__ import print_function
import builtins
import gzip
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
import vavoo.vavoo_record as vr                 # noqa: E402
vu = harness.plugin.vUtils
plugin = harness.plugin

# Real guides (epgshare01's fr and pl, 14 MB) are not in the repository:
# put epg_fr.xml.gz / epg_pl.xml.gz in tests/epgdl (or $VAVOO_EPG_SAMPLES)
# to run these checks.
SAMPLES = os.environ.get("VAVOO_EPG_SAMPLES") or os.path.join(HERE, "epgdl")
HAVE_SAMPLES = all(
    os.path.exists(
        os.path.join(
            SAMPLES,
            "epg_%s.xml.gz" %
            cc)) for cc in (
                "fr",
        "pl"))
# (a shared CI machine pauses threads for its own reasons)
GAP_LIMIT = 0.3 if os.environ.get("CI") else 0.09
if not HAVE_SAMPLES:
    print("== the guide parse rests: skipped (no sample guides in %s)" % SAMPLES)
else:
    print("== the guide parse rests, with the same result")

    def parse(cc, now, rest=True):
        real = vu._BREATHE_WORK
        if not rest:
            vu._BREATHE_WORK = 1e9
        try:
            with gzip.open(os.path.join(SAMPLES, "epg_%s.xml.gz" % cc), "rb") as f:
                return vu._parse_epg_guide(f, cc, now)
        finally:
            vu._BREATHE_WORK = real

    now = time.mktime((2026, 11, 15, 20, 0, 0, 0, 0, -1))
    for cc in ("pl", "fr"):
        out = {}

        def worker(rest):
            t0, c0 = time.time(), time.process_time()
            out[rest] = (parse(cc, now, rest), time.time() - t0)

        for rest in (False, True):
            t = threading.Thread(target=worker, args=(rest,))
            t.start()
            t.join()
        a, b = out[False][0], out[True][0]
        check(
            a.programmes == b.programmes and a.feed_ids == b.feed_ids and a.name_index == b.name_index,
            "%s: exactly the same programmes and channels (%d)" %
            (cc,
             b.programme_count))
        print(
            "        %s: %.2f s without rests, %.2f s with" %
            (cc, out[False][1], out[True][1]))

    # another thread's delays while a guide is read in a background thread
    gaps = []
    stop = threading.Event()

    def ticker():
        last = time.time()
        while not stop.is_set():
            time.sleep(0.005)
            t = time.time()
            gaps.append(t - last)
            last = t

    tk = threading.Thread(target=ticker)
    tk.start()
    bg = threading.Thread(target=lambda: parse("pl", now, True))
    bg.start()
    bg.join()
    stop.set()
    tk.join()
    worst = max(gaps) if gaps else 0
    check(
        worst < GAP_LIMIT,
        "another thread never waits long while a guide is read (worst %.0f ms)" %
        (worst *
         1000))
    import json
    pl = parse("pl", now, True)
    names = list(
        json.load(
            open(
                os.path.join(
                    harness.REPO,
                    "epg-channel-db",
                    "vavoo_channels_pl.json"))))[
        :120]
    matcher = vu.get_epg_matcher()
    res = {}

    def match_all(rest):
        real = vu._BREATHE_WORK
        if not rest:
            vu._BREATHE_WORK = 1e9
        res[rest] = [
            vu._find_feed_id_by_name(
                n,
                matcher,
                pl.name_index) for n in names]
        vu._BREATHE_WORK = real

    for rest in (False, True):
        t = threading.Thread(target=match_all, args=(rest,))
        t.start()
        t.join()
    check(
        res[False] == res[True] and any(
            res[True]),
        "name comparison: the same answers with rests (%d of %d found)" %
        (sum(
            1 for x in res[True] if x),
         len(names)))
    b = vu._Breather()
    main_active = b.active
    check(not main_active, "never rests on the main (GUI) thread")

print("== reused for 6 hours")
check(
    vu._EPG_GUIDE_TTL == 6 *
    3600 and vu._EPG_GUIDE_STALE_MAX == 12 *
    3600,
    "TTL 6 h, stale up to 12 h")
loads = []
real_download = vu._download_epg_guide


def fake_download(cc):
    loads.append(cc)
    g = vu.EpgGuide(cc, time.time())
    g.feed_ids.add("x")
    return g


vu._download_epg_guide = fake_download
vu._epg_guide_cache.clear()
vu._epg_guide_failed.clear()
g1 = vu.load_epg_guide("pt")
g1.loaded_at -= 2 * 3600
check(vu.load_epg_guide("pt") is g1 and loads == ["pt"], "2 hours old: reused")
g1.loaded_at -= 5 * 3600
g2 = vu.load_epg_guide("pt")
check(g2 is not g1 and loads == ["pt", "pt"], "7 hours old: read again")
g2.loaded_at -= 7 * 3600
vu._download_epg_guide = lambda cc: None
check(vu.load_epg_guide("pt") is g2,
      "a failed read: the 7-hour-old one still answers")
check(vu.peek_epg_guide("pt") is g2, "peek: the same")
g2.loaded_at -= 6 * 3600
vu._epg_guide_failed.clear()
check(vu.load_epg_guide("pt") is None, "13 hours old and no new one: none")
vu._download_epg_guide = real_download
vu._epg_guide_cache.clear()
vu._epg_guide_failed.clear()

print("== slow matches in the log")
logged = []
real_print = vu.print
vu.print = lambda *a, **k: logged.append(" ".join(str(x) for x in a))
m = vu.get_epg_matcher()
real_untimed = m._find_match_untimed
m._find_match_untimed = lambda *a, **k: (
    time.sleep(1.05), ("X.pl", "sref", "live"))[1]
check(
    m.find_match(
        "Polsat",
        "pl") == (
            "X.pl",
            "sref",
            "live"),
    "find_match: the same answer")
check(any("slow match: Polsat (pl)" in line for line in logged),
      "a slow one goes in the log: %r" % logged[-1:])
m._find_match_untimed = lambda *a, **k: (None, None, None)
del logged[:]
m.find_match("TVP 1", "pl")
check(not logged, "a quick one does not")
m._find_match_untimed = real_untimed
vu.print = real_print

print("== thread names")
seen = {}


def named_work():
    tid = getattr(threading, "get_native_id", lambda: None)()
    try:
        seen["comm"] = open("/proc/self/task/%d/comm" % tid).read().strip()
    except Exception as e:
        seen["comm"] = str(e)


t = threading.Thread(target=plugin.named(named_work, "vv-guide"))
t.start()
t.join()
check(seen.get("comm") == "vv-guide",
      "a plugin thread shows as 'vv-guide': %r" % seen.get("comm"))
t = threading.Thread(
    target=plugin.named(
        named_work,
        "vv-a-very-long-thread-name"))
t.start()
t.join()
check(
    seen.get("comm") == "vv-a-very-long-",
    "cut to 15 characters: %r" %
    seen.get("comm"))
saved = vr._prctl[0]
vr._prctl[0] = False
vr.name_this_thread("vv-x")
check(True, "no prctl (no ctypes): nothing, no error")
vr._prctl[0] = None
real_import = builtins.__import__


def no_ctypes(name, *a, **k):
    if name == "ctypes":
        raise ImportError("no ctypes")
    return real_import(name, *a, **k)


builtins.__import__ = no_ctypes
try:
    vr.name_this_thread("vv-y")
finally:
    builtins.__import__ = real_import
check(vr._prctl[0] is False, "ctypes missing: switched off quietly")
vr._prctl[0] = saved

print("== ffmpeg at a lower priority, the recorder's log")
rec = vr.Recorder(lambda f: "/dev/null", "/tmp/x.ts", ffmpeg="/usr/bin/ffmpeg")
cmd = rec._command("/dev/null")
check(cmd[:3] == [vr.find_nice(), "-n", "10"] and cmd[3] ==
      "/usr/bin/ffmpeg", "nice -n 10 ffmpeg ...: %r" % cmd[:4])
real_find = vr.find_nice
vr.find_nice = lambda: None
check(
    rec._command("/dev/null")[0] == "/usr/bin/ffmpeg",
    "no nice on the box: ffmpeg as before")
vr.find_nice = real_find
got = []
vr.set_logger(got.append)
vr._log("hello")
check(got == ["[vavoo_record] hello"], "messages go to the plugin's log")
vr.set_logger(None)
check(rec.thread_name == "vv-rec", "a recording's thread: vv-rec")
src = harness.plugin_source()
check(
    'thread_name="vv-pause"' in src and "vavoo_record.set_logger(print)" in src,
    "pause buffer: vv-pause; recorder log into vavoo.log")

finish()
