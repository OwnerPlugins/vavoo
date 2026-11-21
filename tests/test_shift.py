# -*- coding: utf-8 -*-
"""The player's Record and Pause Live TV (Playstream2), with a real
pause buffer recorded from the fake live channel and played back
through the proxy's real /file."""
from __future__ import print_function
import os
import shutil
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, V, NOTES, FakeLabel, MENUS  # noqa: E402
import fakehls                                  # noqa: E402
import vavoo.vavoo_record as vr                 # noqa: E402
plugin = harness.plugin
vp = plugin.vavoo_proxy
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
os.environ["no_proxy"] = "127.0.0.1,localhost"

TMP = tempfile.mkdtemp(prefix="vavoo_shift_")
channel = fakehls.FakeChannel()
plugin.cfg.timeshift = V(True)
plugin.cfg.services = V("4097")
plugin.cfg.record_path = V(TMP)
plugin.PROXY_BASE_URL = "http://127.0.0.1:%d" % channel.port
REAL_PAUSE_FOLDER = plugin.pause_folder
plugin.pause_folder = lambda: TMP
PLAY, PAUSE = (0, 0, 0, ">"), (1, 0, 0, "||")
plugin.Playstream2.SEEK_STATE_PLAY = PLAY
plugin.Playstream2.SEEK_STATE_PAUSE = PAUSE
seek_calls = []
plugin.InfoBarSeek.pauseService = lambda self: (seek_calls.append("pause"), setattr(self, "seekstate", PAUSE))
plugin.InfoBarSeek.unPauseService = lambda self: (seek_calls.append("unpause"), setattr(self, "seekstate", PLAY))
plugin.InfoBarSeek.seekFwd = lambda self: seek_calls.append("ff")
plugin.InfoBarSeek.seekBack = lambda self: seek_calls.append("rew")
plugin.TvInfoBarShowHide.OkPressed = lambda self: None


class SRef(object):
    def __init__(self, ref):
        self.ref = ref

    def setName(self, name):
        self.name = name


plugin.eServiceReference = SRef


class Nav(object):
    def __init__(self):
        self.calls = []

    def stopService(self):
        self.calls.append("stop")

    def playService(self, sref):
        self.calls.append(("play", getattr(sref, "ref", sref)))
        if getattr(self, "owner", None) is not None:
            self.owner.seekstate = PLAY    # (InfoBarSeek, on evStart)


class FakeProxy(object):
    def __init__(self):
        self.failures = []

    def report_stream_failure(self, cid):
        self.failures.append(cid)

    def get_group_sources(self, gid):
        return {}


plugin.vavoo_proxy.proxy = FakeProxy()
URL = "http://127.0.0.1:4323/vavoo?channel=abc123"


def player(themed=True):
    ps = plugin.Playstream2.__new__(plugin.Playstream2)
    ps.widgets = {}
    ps.session = harness.Session()
    ps.session.nav = Nav()
    ps.session.nav.owner = ps
    ps._closed = False
    ps._bar_themed = themed
    for w in plugin.PLAYER_BAR_LABELS:
        ps.widgets[w] = FakeLabel()
    ps.name, ps.url = "RAI 1", URL
    ps.country_code, ps.country_name, ps.country_names, ps.country_codes = "it", "Italy", None, None
    ps.sref = SRef("LIVE")
    ps.stream_running = True
    ps.hand_back = False
    ps.seekstate = PLAY
    ps._typed = 0
    ps._bar_sel = -1
    ps.list = [[("RAI 1", URL)], [("RAI 2", URL.replace("abc123", "def456"))]]
    ps.itemscount = 2
    ps.currentindex = 0
    for name in ("_shift_tick", "_shift_seek"):
        setattr(ps, name, harness.FakeTimer())
    ps._shift, ps._shift_state, ps._shift_pos, ps._shift_clock, ps._shift_waits = None, None, 0.0, None, 0
    ps._shift_why = None
    ps._show_bar_now = lambda: None
    ps._fill_bar = lambda: None
    return ps


print("== Record in the player")
started = []


class FakeRec(object):
    def __init__(self):
        self.running = True
        self.duration = 65
        self.stopped = False
        self.info = {"url": URL}

    def stop(self):
        self.stopped = True
        self.running = False


fake_rec = FakeRec()
current = [None]
real_start, real_of = plugin.RECORDINGS.start, plugin.RECORDINGS.recording_of


def fake_start(ch, title=None, stop_at=0, quiet=False):
    started.append((ch, title, stop_at))
    current[0] = FakeRec()
    return current[0]


plugin.RECORDINGS.start = fake_start
plugin.RECORDINGS.recording_of = lambda url: current[0] if (current[0] and current[0].running and url == URL) else None
ps = player()
now = time.time()
plugin.vUtils.peek_now_next = lambda name, cc: ("ok", (now - 600, now + 1800, "Telegiornale", ""), None)
del NOTES[:]
ps.toggle_record()
ch, title, stop_at = started[-1]
check(ch["url"] == URL and ch["country_name"] == "Italy" and title == "Telegiornale",
      "the channel and the programme on now")
check(abs(stop_at - (now + 1800 + 120)) < 2, "until its end plus 2 minutes")
check(NOTES[-1].startswith("Recording: Telegiornale  →  "), "said: %r" % NOTES[-1])
check(ps._status_text().startswith(u"● REC"), "'● REC' in the bar's status")
del MENUS[:]
ps._source_count = lambda: 1
ps._is_favourite = lambda: False
ps.open_options()
labels = [e[0] for e in MENUS[-1][1]]
check(u"Record: ● 1:05" in labels, "options: 'Record: ● 1:05' %r" % labels)
rec_now = current[0]
ps.toggle_record()
check(rec_now.stopped and NOTES[-1] == "Recording stopped", "again: stopped")
check(not ps._status_text().startswith(u"●"), "no REC any more")
ps.open_options()
check("Record" in [e[0] for e in MENUS[-1][1]], "options: 'Record' again")
plugin.vUtils.peek_now_next = lambda name, cc: ("ok", (now - 600, now + 300, "Short", ""), None)
ps.toggle_record()
check(started[-1][1:] == ("Short", 0), "ends within 10 minutes: until stopped")
current[0].stop()
plugin.vUtils.peek_now_next = lambda name, cc: None
ps.toggle_record()
check(started[-1][1:] == ("RAI 1", 0), "no guide: the channel's name, until stopped")
src = harness.plugin_source()
check('"instantRecord": self.toggle_record' in src and "'InfobarInstantRecord'" in src, "REC key")
plugin.RECORDINGS.start, plugin.RECORDINGS.recording_of = real_start, real_of

print("== Pause Live TV")
ps = player()
ps.pauseService()
buf = ps._shift
check(ps._shift_state == "paused" and buf is not None and buf.running, "PAUSE: paused, the channel recorded")
check(seek_calls[-1] == "pause" and ps.seekstate == PAUSE, "the picture paused")
check(os.path.dirname(buf.path) == TMP and os.path.basename(buf.path).startswith("vavoo_pause_"), "buffer on the disk")
check(ps._status_text() == u"❚❚ Paused  ·  recording - press play to go on",
      "status: %r" % ps._status_text())
ps.pauseService()
check(ps._shift is buf and seek_calls.count("pause") == 1, "PAUSE again: nothing more")
time.sleep(6)
ps.unPauseService()
check(ps._shift_state == "behind", "PLAY: from the buffer")
call = ps.session.nav.calls[-1]
check(ps.session.nav.calls[-2] == "stop" and call[0] == "play" and
      ("/file%3f" in call[1] or "/file?" in call[1]), "live stopped, the buffer played")
check(("id=" + buf.file_id) in call[1] and "follow=1" in call[1] and call[1].startswith("4097:0:1:"),
      "the buffer's id, followed, the live player type: %s" % call[1][:80])
time.sleep(2)
text = ps._status_text()
check(text.startswith(u"◀◀ -0:") and "EXIT: live" in text, "status: %r" % text)
# the real /file, as the box's player reads it
server = vp.ThreadedHTTPServer(("127.0.0.1", 0), vp.VavooHTTPHandler)
proxy_before = vp.proxy
vp.proxy = type("P", (), {"is_stopped": lambda self: False})()
threading.Thread(target=server.serve_forever).start()
address = call[1].split(":", 10)[10].rsplit(":", 1)[0].replace("%3a", ":").split("#")[0]
address = address.replace(plugin.PROXY_BASE_URL, "http://127.0.0.1:%d" % server.server_address[1])
got = bytearray()


def read():
    from urllib.request import Request, build_opener, ProxyHandler
    r = build_opener(ProxyHandler({})).open(Request(address), timeout=10)
    end = time.time() + 4
    while time.time() < end:
        chunk = r.read(4096)
        if not chunk:
            break
        got.extend(chunk)


reader = threading.Thread(target=read)
reader.start()
reader.join(8)
out = os.path.join(TMP, "played.ts")
open(out, "wb").write(bytes(got))
check(len(got) > 50000 and fakehls.probe_duration(out) > 3,
      "the box's player gets a playable stream (%d bytes, %.1f s)" % (len(got), fakehls.probe_duration(out)))
server.shutdown()
vp.proxy = proxy_before

pos = ps._shift_position()
ps.key_left()
check(ps._shift_state == "behind" and ps._shift_clock is None and
      abs(ps._shift_pos - max(0, pos - 10)) < 1.5, "LEFT: 10 s back (waits for the keys to rest)")
calls = len(ps.session.nav.calls)
ps._shift_seek_now()
check(len(ps.session.nav.calls) == calls + 2 and ps._shift_clock is not None, "then opened there")
off = int(ps.session.nav.calls[-1][1].split("offset=")[1].split("&")[0])
check(off % 188 == 0 and off == (buf.offset_for(ps._shift_pos) if ps._shift_pos > 0 else 0),
      "at a packet boundary of the index, the very start at 0 (%d)" % off)
ps.key_right()
ps.key_right()
ps.key_right()
check(ps._shift_pos <= buf.duration - 2 + 0.01, "RIGHT: never past live (%.1f / %.1f)" % (ps._shift_pos, buf.duration))
ps._shift_seek_now()
ps.seekBack()
check(ps._shift_clock is None and "rew" not in seek_calls, "<<: 30 s back in the buffer")
ps._shift_seek_now()
ps.pauseService()
check(ps._shift_state == "behind_paused" and seek_calls[-1] == "pause", "PAUSE behind live: paused there")
held = ps._shift_pos
time.sleep(1.2)
check(ps._shift_position() == held, "the place stays while paused")
ps.OkPressed()
check(ps._shift_state == "behind" and abs(ps._shift_pos - held) < 1.0, "OK: goes on from there")
del NOTES[:]
calls = len(ps.session.nav.calls)
ps.back()
check(ps._shift_state is None and ps._shift is None, "EXIT: back to live")
check(ps.session.nav.calls[calls:] == ["stop", ("play", "LIVE")] and NOTES == ["Live"],
      "the live channel again, 'Live'")
time.sleep(1)
check(not os.path.exists(buf.path) and vr.file_entry(buf.file_id) is None, "buffer deleted")
check(not ps._closed, "EXIT went to live, the player stays")

print("== zap, EOF, close, no disk")
ps.pauseService()
buf = ps._shift
ps.stopStream = lambda restore_original=True: ps.session.nav.calls.append("stopStream")
ps.startStream = lambda is_retry=False: ps.session.nav.calls.append("startStream")
ps._update_country_code_for_index = lambda i: None
ps._update_logo_url_for_index = lambda i: None
calls = len(ps.session.nav.calls)
ps.zap_to(1)
check(ps._shift is None and ps.session.nav.calls[calls:] == ["stopStream", "startStream"],
      "a zap: the buffer goes, no live replay in between")
time.sleep(1)
check(not buf.running, "its recording stopped")
ps = player()
ps.pauseService()
ps._shift.duration = 30
ps._shift_play_at(0)
ps._handleEofEvent("test")
check(ps._shift_state is None and ps.session.nav.calls[-1] == ("play", "LIVE"), "the end of the buffer: live")
ps = player()
ps.pauseService()
buf = ps._shift
buf.stop()
buf.join(5)
buf.duration = 0
for i in range(16):
    ps.unPauseService() if i == 0 else ps._shift_seek_now()
check(ps._shift is None and ps.session.nav.calls[-1] == ("play", "LIVE"), "nothing recorded: just live")
plugin.pause_folder = lambda: None
ps = player()
ps.pauseService()
check(ps._shift is None and ps.seekstate == PAUSE and ps._shift_why == "disk",
      "no disk: PAUSE only pauses")
check(ps._status_text() == u"❚❚ Paused  ·  not recorded (no disk) - PLAY returns to live",
      "...and says so: %r" % ps._status_text())
ps.OkPressed()
check(ps.seekstate == PLAY and seek_calls[-1] == "unpause" and ps._shift_why is None,
      "OK: plays on (live), the reason gone")
ps = player(themed=False)
del NOTES[:]
ps.pauseService()
check(NOTES and "not recorded (no disk)" in NOTES[-1], "Classic: the reason in a message too: %r" % NOTES)
ps.playpauseService()
check(seek_calls[-1] == "unpause", "PLAY: plays on")
plugin.pause_folder = lambda: TMP
real_ffmpeg = plugin.vavoo_record.find_ffmpeg
plugin.vavoo_record.find_ffmpeg = lambda: None
ps = player()
ps.pauseService()
check(ps._shift is None and ps._shift_why == "ffmpeg" and "no ffmpeg" in ps._status_text(), "no ffmpeg: said")
plugin.vavoo_record.find_ffmpeg = real_ffmpeg
plugin.cfg.timeshift = V(False)
plugin.pause_folder = lambda: TMP
ps = player()
ps.pauseService()
check(ps._shift is None and ps._shift_why is None and ps._status_text() == u"❚❚ Paused",
      "Pause Live TV off: only pauses (the user's choice: nothing to explain)")
plugin.cfg.timeshift = V(True)
ps = player(themed=False)
del NOTES[:]
ps.pauseService()
check(NOTES and NOTES[-1].startswith(u"❚❚ Paused"), "Classic: said in a message")
ps._shift_end(replay=False)

print("== a buffer that stops while paused")
ps = player()
ps.pauseService()
buf = ps._shift
for _ in range(100):
    if buf.duration >= 3:
        break
    time.sleep(0.1)
buf.stop()
buf.join(10)
check(not buf.running and buf.duration >= 2, "the buffer stopped with %.1f s in it" % buf.duration)
ps._on_shift_tick()
check(ps._shift is buf and ps._shift_state == "paused" and os.path.exists(buf.path),
      "kept: still paused, the file there")
check(ps._status_text() == u"❚❚ Paused  ·  press play to go on", "status: %r" % ps._status_text())
ps.playpauseService()
call = ps.session.nav.calls[-1]
check(ps._shift_state == "behind" and call[0] == "play" and ("id=" + buf.file_id) in call[1]
      and "offset=0&" in call[1], "PLAY: what it holds, from its start: %r" % (call,))
ps._handleEofEvent("test")
check(ps._shift_state is None and ps.session.nav.calls[-1] == ("play", "LIVE"), "its end: live")
ps = player()
ps.pauseService()
buf = ps._shift
buf.stop()
buf.join(10)
buf.duration = 0.5
ps._on_shift_tick()
check(ps._shift is None and ps._shift_why == "stopped" and ps.seekstate == PAUSE,
      "nothing in it: deleted, still paused")
check("could not be recorded" in ps._status_text(), "...and says so: %r" % ps._status_text())
ps.playpauseService()
check(seek_calls[-1] == "unpause", "PLAY: live")

print("== the pause buffer on any disk")
MEDIA = os.path.join(TMP, "media")
real = {"on_disk": plugin.vavoo_record.on_disk, "free": plugin.vavoo_record.free_bytes,
        "record_path": plugin.cfg.record_path, "points": plugin.vavoo_record.mount_points}
plugin.vavoo_record.mount_points = lambda: [("/", "ubifs"), (MEDIA + "/x", "ext4"), ("/media/usb", "vfat"),
                                            ("/media/net/nas", "nfs")]
check(plugin.media_mounts() == ["/media/usb"] if os.path.isdir("/media/usb") else plugin.media_mounts() == [],
      "mounts from /proc/mounts, under /media only: %r" % plugin.media_mounts())
plugin.vavoo_record.mount_points = real["points"]
disks = {}
for name in ("hdd", "usb", "sdb1"):
    os.makedirs(os.path.join(MEDIA, name))
plugin.media_mounts = lambda network=False: [os.path.join(MEDIA, "usb"), os.path.join(MEDIA, "sdb1")]
plugin.cfg.record_path = V(os.path.join(MEDIA, "hdd", "movie") + "/")
plugin.vavoo_record.on_disk = lambda p: any(p.startswith(d) for d in disks)
plugin.vavoo_record.free_bytes = lambda p: next((free for d, free in disks.items() if p.startswith(d)), None)
GB = 1 << 30
disks = {os.path.join(MEDIA, "usb"): 8 * GB}
check(REAL_PAUSE_FOLDER() == os.path.join(MEDIA, "usb"), "Enigma2's folders on no disk, a USB stick: the stick")
disks = {os.path.join(MEDIA, "usb"): 8 * GB, os.path.join(MEDIA, "sdb1"): 50 * GB}
check(REAL_PAUSE_FOLDER() == os.path.join(MEDIA, "sdb1"), "two disks: the one with more room")
disks = {os.path.join(MEDIA, "usb"): 1024}
check(REAL_PAUSE_FOLDER() is None, "a full one: none")
disks = {os.path.join(MEDIA, "hdd"): 2 * GB, os.path.join(MEDIA, "sdb1"): 50 * GB}
check(REAL_PAUSE_FOLDER() == os.path.join(MEDIA, "hdd", "movie") + "/", "the recordings folder on a disk: first")
disks = {}
check(REAL_PAUSE_FOLDER() is None, "no disk at all (the flash): none")
open(os.path.join(MEDIA, "usb", "vavoo_pause_1700000000000.ts"), "wb").close()
plugin.ACTIVE.pop("player", None)
plugin.clean_pause_leftovers()
check(not os.listdir(os.path.join(MEDIA, "usb")), "a leftover buffer on the stick: deleted")
plugin.vavoo_record.on_disk, plugin.vavoo_record.free_bytes = real["on_disk"], real["free"]
plugin.cfg.record_path = real["record_path"]

channel.close()
time.sleep(1)
shutil.rmtree(TMP, ignore_errors=True)
finish()
