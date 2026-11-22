# -*- coding: utf-8 -*-
"""A box's channels stuttered and its menus dragged after 1.90, which
reads the countries' guides (13 to 47 MB each) inside Enigma2's own
process: while a stream plays the plugin's heavy loops give way (a
fifth of a core), the guides are not loaded ahead, and the player bar
fetches a guide only once the channel has played a while. The log
says what loads the box: "[CPU]" every 30 minutes, "[PERF] GUI held
up" when the GUI thread was stuck."""
from __future__ import print_function
import os
import socket
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, FakeLabel  # noqa: E402
plugin = harness.plugin
vu = plugin.vUtils
vp = plugin.vavoo_proxy
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
try:
    from urllib.request import urlopen
    from urllib.error import HTTPError
except ImportError:
    from urllib2 import urlopen, HTTPError

print("== a stream plays")
vu._stream_seen[0] = 0.0
check(not vu.stream_playing(), "nothing noted: no stream")
vu.note_stream()
check(vu.stream_playing(), "note_stream(): a stream plays")
check(not vu.stream_playing(now=time.time() + vu.STREAM_WINDOW + 1),
      "...for %d s after the last note" % vu.STREAM_WINDOW)

print("== heavy loops give way while it plays")


def work_between_rests(playing):
    """The work done between two rests of a busy loop (the rests
    themselves not taken: a fake sleep)."""
    vu._stream_seen[0] = time.time() if playing else 0.0
    rests = []
    real_sleep = vu.sleep
    vu.sleep = lambda seconds: rests.append((time.time(), seconds))

    def loop():
        b = vu._Breather()
        end = time.time() + 0.4
        while time.time() < end:
            b.tick()
    t = threading.Thread(target=loop)
    t.start()
    t.join()
    vu.sleep = real_sleep
    gaps = sorted(b[0] - a[0] for a, b in zip(rests, rests[1:]))
    return (gaps[len(gaps) // 2] if gaps else None,
            set(seconds for _when, seconds in rests))


gap, rest = work_between_rests(False)
check(gap is not None and gap >= 0.045 and rest == set([vu._BREATHE_REST]),
      "no stream: rests %s s after ~%.3f s of work (two thirds of a core)" %
      (sorted(rest), gap or 0))
gap, rest = work_between_rests(True)
check(gap is not None and gap < 0.03 and
      rest == set([vu._BREATHE_REST_PLAYING]),
      "a stream: rests %s s after ~%.3f s of work (a fifth of a core)" %
      (sorted(rest), gap or 0))
vu._stream_seen[0] = 0.0
check(not vu._Breather().active, "never rests on the GUI thread")

print("== the proxy notes the player's requests")


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
vp.VavooProxy._download_catalog = lambda self, setting: ([
    {"id": u"%d" % i, "name": u"Canal %d" % i, "url": u"http://x/%d" % i,
     "country": u"Portugal", "logo": u"", "group": u"Portugal ➾ Geral",
     "epg_id": u""} for i in range(150)], "geil")
vp.VavooProxy.refresh_addon_sig_if_needed = lambda self, force=False: None
if os.path.exists(vp.CATALOG_FILE):
    os.remove(vp.CATALOG_FILE)
vp.proxy = vp.VavooProxy()
server = threading.Thread(target=vp._proxy_thread_main)
server.daemon = True
server.start()
for _i in range(200):
    if vp.proxy_state().get("ready"):
        break
    time.sleep(0.05)
check(vp.proxy_state().get("ready"), "a proxy up on a free port")
for path in ("/vavoo?channel=nope", "/file?id=nope&offset=0"):
    vu._stream_seen[0] = 0.0
    try:
        urlopen("http://127.0.0.1:%d%s" % (PORT, path), timeout=5).read()
    except HTTPError:
        pass
    check(vu.stream_playing(), "%s marks a stream" % path.split("?")[0])
vu._stream_seen[0] = 0.0
urlopen("http://127.0.0.1:%d/status" % PORT, timeout=5).read()
check(not vu.stream_playing(), "/status does not")
vp.shutdown_proxy()

print("== the guides are not loaded ahead while it plays")
main = make(plugin.MainVavoo, Session())
plugin.NOW_PLAYING.owner = None
plugin.ACTIVE["player"] = None
vu._stream_seen[0] = 0.0
check(main._preload_go_on(), "nothing playing: the guides load ahead")
vu.note_stream()
check(not main._preload_go_on(),
      "a stream plays (the preview, a bouquet channel): not loaded ahead")
vu._stream_seen[0] = 0.0
plugin.NOW_PLAYING.preview_plays = lambda url: False
plugin.NOW_PLAYING.player_take("http://127.0.0.1:4323/vavoo?channel=1")
check(vu.stream_playing(), "the player starting notes it too")
vu._stream_seen[0] = 0.0
plugin.NOW_PLAYING.player_give_back({"name": "x", "url": "u"}, None)
check(vu.stream_playing(), "...and the preview taking it back")
plugin.NOW_PLAYING.owner = None

print("== the player bar fetches a guide once the channel has played")


class RecTimer(harness.FakeTimer):
    def __init__(self):
        harness.FakeTimer.__init__(self)
        self.starts = []

    def start(self, ms, single=False):
        self.starts.append(ms)


pending = harness.Pending().hold()
ps = plugin.Playstream2.__new__(plugin.Playstream2)
ps.widgets = {}
ps._closed = False
ps._bar_themed = True
for w in plugin.PLAYER_BAR_LABELS + ("logo", "info_box", "progress_track",
                                     "progress"):
    ps.widgets[w] = FakeLabel()
plugin.Playstream2.__setitem__ = lambda self, k, v: self.widgets.__setitem__(
    k, v)
plugin.Playstream2.__getitem__ = lambda self, k: self.widgets[k]
ps.name, ps.url = "SIC", "http://127.0.0.1:4323/vavoo?channel=sic"
ps.country_code, ps.country_name = "pt", "Portugal"
ps._bar_epg_for = None
ps._bar_epg_timer = RecTimer()
ps._stream_since = time.time()
real_peek = vu.peek_now_next
vu.peek_now_next = lambda name, cc: None
ps._bar_epg()
check(not pending.threads and ps._bar_epg_timer.starts and
      9000 <= ps._bar_epg_timer.starts[-1] <= 10200,
      "just zapped, no guide in memory: no download yet, again in ~10 s (%r)" %
      ps._bar_epg_timer.starts)
check(ps.widgets["now"].text == "Portugal",
      "the bar shows the country meanwhile")
ps.url = "http://127.0.0.1:4323/vavoo?channel=rtp"
ps._stream_since = time.time()
ps._bar_epg()
check(not pending.threads and len(ps._bar_epg_timer.starts) == 2,
      "zapped on: the wait starts again, still no download")
ps._stream_since = time.time() - 11
ps._bar_epg_due()
check(len(pending.threads) == 1,
      "played 10 s: the guide is fetched (one thread)")
ps._bar_epg_due()
check(len(pending.threads) == 1, "...once")
vu.peek_now_next = lambda name, cc: ("ok", None, None)
del pending.threads[:]
ps._bar_epg_for = None
ps._stream_since = time.time()
ps._bar_epg()
check(not pending.threads, "a guide in memory: shown at once, no fetch")
ps._closed = True
ps._bar_epg_due()
check(not pending.threads, "closed: nothing")
vu.peek_now_next = real_peek
pending.release()

print("== what each thread spent ([CPU])")
TMP = tempfile.mkdtemp(prefix="vavoo_perf_")


def fake_task(tid, name, utime, stime):
    os.makedirs(os.path.join(TMP, "task", tid))
    fields = ["S"] + ["0"] * 10 + [str(utime), str(stime)] + ["0"] * 30
    with open(os.path.join(TMP, "task", tid, "stat"), "w") as f:
        f.write("%s (%s) %s\n" % (tid, name, " ".join(fields)))


tick = float(os.sysconf("SC_CLK_TCK"))
fake_task("100", "enigma2", int(30 * tick), int(10 * tick))
fake_task("101", "vv-guide", int(4 * tick), 0)
fake_task("102", "odd (name) x", int(1 * tick), 0)
before = vu.thread_cpu(os.path.join(TMP, "task"))
check(before.get("100") == ("enigma2", 40.0) and
      before.get("102") == ("odd (name) x", 1.0),
      "thread_cpu(): name and seconds per thread %r" % sorted(before.items()))
after = dict(before)
after["100"] = ("enigma2", 70.0)
after["101"] = ("vv-guide", 52.0)
after["103"] = ("vv-http", 3.0)
used = vu.cpu_by_name(before, after)
check(used[0] == ("vv-guide", 48.0) and dict(used)["enigma2"] == 30.0 and
      dict(used)["vv-http"] == 3.0 and "odd (name) x" not in dict(used),
      "cpu_by_name(): what each spent between the samples %r" % used)
text = vu.cpu_report(before, after, 1800)
check(text == "4 % of a core (30 min) - vv-guide 48.0 s, enigma2 30.0 s, "
      "vv-http 3.0 s", "cpu_report(): %r" % text)
check(vu.cpu_report(before, {}, 1800) == "" and
      vu.thread_cpu(os.path.join(TMP, "none")) == {},
      "nothing to read: nothing said")
real = vu.thread_cpu()
check(real and all(isinstance(s, float) for _n, s in real.values()),
      "this process's own threads read (%d)" % len(real))

print("== the GUI held up ([PERF])")
logged = []
real_print = plugin.print
plugin.print = lambda *a, **k: logged.append(" ".join(str(x) for x in a))
lag = plugin._LagWatch()
t0 = 5000.0
s0 = {"100": ("enigma2", 10.0), "101": ("vv-guide", 2.0)}
check(lag.tick(t0, s0) is False, "first tick: the start")
check(lag.tick(t0 + 1.3, s0) is False and not logged,
      "0.3 s late: nothing said")
s1 = {"100": ("enigma2", 10.4), "101": ("vv-guide", 3.2)}
check(lag.tick(t0 + 4.1, s1) is True and logged and
      logged[-1] == "[PERF] GUI held up 1.8 s - busy: vv-guide 1.2 s, "
      "enigma2 0.4 s", "1.8 s late: who was busy %r" % logged[-1:])
check(lag.tick(t0 + 8.0, s1) is False and len(logged) == 1,
      "again within a minute: not said twice")
check(lag.tick(t0 + 70.0, s1) is True and len(logged) == 2 and
      logged[-1] == "[PERF] GUI held up 61.0 s",
      "a minute on: said again (nothing busy: no list) %r" % logged[-1:])
plugin.print = real_print
check(plugin._ReminderService and "LAG_WATCH.start()" in
      harness.e2env.source_of("_ReminderService"),
      "started with the reminder service (session start, plugin closed too)")
finish()
