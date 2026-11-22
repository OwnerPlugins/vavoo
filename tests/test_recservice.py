# -*- coding: utf-8 -*-
"""plugin.py's recordings service: RECORDINGS, the record timers in
the reminder tick, get_next_wakeup(), folders, Restore refused."""
from __future__ import print_function
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
plugin = harness.plugin
store = harness.store
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
os.environ["no_proxy"] = "127.0.0.1,localhost"

TMP = tempfile.mkdtemp(prefix="vavoo_recs_")
real_on_disk = vr.on_disk
vr.on_disk = lambda path: True          # (the test folders count as a disk)
plugin.cfg.record_path = V(TMP)
plugin.cfg.timeshift = V(True)
plugin.is_proxy_ready = lambda timeout=2: True
channel = fakehls.FakeChannel()


class FakeProxy(object):
    def __init__(self):
        self.resolved = []
        self.alive = []
        self.dropped = []

    def resolve_own(self, channel_id, slot, force=False):
        self.resolved.append((channel_id, slot, force))
        return channel.url()

    def own_signature(self, slot, force=False):
        self.alive.append(slot)
        return "SIG"

    def drop_own_signature(self, slot):
        self.dropped.append(slot)


fake = FakeProxy()
plugin.vavoo_proxy.proxy = fake
URL = "http://127.0.0.1:4323/vavoo?channel=abc123"
CH = {"name": "RAI 1", "url": URL, "country_name": "Italy",
      "country_code": "it", "logo": ""}

print("== folders")
check(plugin.recordings_folder() == TMP, "the chosen folder")
plugin.cfg.record_path = V("")
check(plugin.recordings_folder() == "/media/hdd/movie/",
      "default: Enigma2's movie folder")
choices = plugin.record_folder_choices()
check(choices[0] == ("", "/media/hdd/movie/"),
      "first choice: the movie folder")
plugin.cfg.record_path = V(TMP)
check((TMP, TMP) in plugin.record_folder_choices(),
      "the current one is always offered")
check(plugin.usable_folder(os.path.join(TMP, "sub"))
      is not None, "made inside an existing folder")
check(plugin.usable_folder("/nonexistent/x/y")
      is None, "not on a disk that is not there")
check(
    plugin.pause_folder() == TMP,
    "pause buffer: the recordings folder (no timeshift folder)")
check(
    u"→" in plugin.recording_text(
        "Show",
        time.time() + 600),
    "'Recording: Show  →  21:02'")

print("== recording now")
rec = plugin.RECORDINGS.start(CH, "Il Commissario", time.time() + 6)
check(rec is not None and rec.running, "started")
check(plugin.RECORDINGS.recording_of(URL) is rec, "recording_of() finds it")
check(plugin.RECORDINGS.start(CH, "Again") is rec,
      "the same channel is not recorded twice")
check(
    rec.max_seconds > 6 + 500,
    "a timed one may run past its end margin (TIMER_EXTRA)")
time.sleep(3)
check(fake.resolved and fake.resolved[0][0] == "abc123" and fake.resolved[0][1].startswith(
    "recording:"), "resolved with its own slot: %r" % (fake.resolved[:1],))
rec.join(30)
time.sleep(0.2)
check(
    not plugin.RECORDINGS.running() and rec.id not in plugin.RECORDINGS.active,
    "ended, out of the active ones")
check(fake.dropped == [rec.slot], "its own token dropped")
check(
    os.path.isfile(
        rec.path) and os.path.getsize(
            rec.path) > 0,
    "file written: " +
    os.path.basename(
        rec.path))
info = vr.read_info(rec.path)
check(info["country"] == "Italy" and info["url"] == URL and info["title"] == "Il Commissario"
      and info["sref"] == "4097:0:1:0:0:0:0:0:0:0::RAI 1", "its record: channel, country, title")
listed = vr.list_recordings(TMP)
check(len(listed) == 1 and listed[0]["path"] == rec.path, "listed")

print("== cannot record")
del NOTES[:]
real_find = vr.find_ffmpeg
vr.find_ffmpeg = lambda: None
check(plugin.RECORDINGS.start(CH)
      is None and NOTES[-1] == "Recording needs ffmpeg", "no ffmpeg: said")
vr.find_ffmpeg = real_find
real_free = vr.free_bytes
vr.free_bytes = lambda path: 1000
check(plugin.RECORDINGS.start(
    CH) is None and NOTES[-1] == "Can't record (not enough free space?)", "no room: said")
del NOTES[:]
check(plugin.RECORDINGS.start(CH, quiet=True)
      is None and not NOTES, "quiet: not said")
vr.free_bytes = real_free
plugin.cfg.record_path = V("/nonexistent/disk/movie/")
check(plugin.RECORDINGS.start(CH) is None, "no disk: none")
plugin.cfg.record_path = V(TMP)

vr.on_disk = lambda path: False         # /media/hdd with no disk: the flash
flash = os.path.join(TMP, "nodisk")
os.makedirs(flash)
plugin.cfg.record_path = V(os.path.join(flash, "movie/"))
del NOTES[:]
check(plugin.RECORDINGS.start(CH) is None and NOTES[-1] == "Can't record: no disk (HDD / USB) found",
      "no disk mounted: refused, said")
check(not os.path.exists(os.path.join(flash, "movie")),
      "...and no folder made on the box's flash")
check(plugin.usable_folder(TMP) is None and plugin.pause_folder() is None,
      "not on a disk: no recordings folder, no pause buffer (PAUSE only pauses)")
vr.on_disk = lambda path: True
plugin.cfg.record_path = V(TMP)
check(real_on_disk("/") is False and real_on_disk("/tmp") is False,
      "the root file system (flash) and /tmp are never a disk")
check(vr.mount_of("/proc/self")[1] == "proc",
      "mount_of(): the file system type")

print("== a recording set in the guide")
now = time.time()
store.add_timer(store.KIND_RECORD, URL, "RAI 1", "Telegiornale", int(now + 60),
                int(now + 900), "Italy", "it", "")
store.add_timer(store.KIND_RECORD, URL, "RAI 1", "Later", int(now + 3600),
                int(now + 7200), "Italy", "it", "")
plugin.REMINDERS.session = harness.Session()
plugin._in_standby = lambda: True
del NOTES[:]
plugin.REMINDERS.tick()
rec = plugin.RECORDINGS.recording_of(URL)
check(
    rec is not None and rec.info["title"] == "Telegiornale",
    "started 2 minutes before its programme")
check(abs(rec.stop_at - (int(now + 900) + store.RECORD_MARGIN))
      < 2, "until its end plus the margin")
check(not NOTES, "in standby: started without a word")
check([t["title"] for t in store.load_timers(store.KIND_RECORD)]
      == ["Later"], "taken out of the timers")
wake = plugin.get_next_wakeup()
check(wake == int(now + 3600) - store.RECORD_MARGIN - plugin.WAKE_BEFORE,
      "deep standby: wake 5 minutes before the next one starts (%s)" % wake)
rec.stop()
rec.join(30)
time.sleep(0.2)
check(not rec.running, "stopped by hand")

vr.find_ffmpeg = lambda: None
store.add_timer(store.KIND_RECORD, URL, "RAI 1", "Broken", int(
    time.time() + 60), int(time.time() + 600), "Italy", "it", "")
plugin._in_standby = lambda: False
del NOTES[:]
plugin.REMINDERS.tick()
check(
    NOTES == ["Scheduled recording not started: Broken"],
    "could not start: said (%r)" %
    NOTES)
vr.find_ffmpeg = real_find
for t in store.load_timers():
    store.remove_timer(t["id"])
check(plugin.get_next_wakeup() == -1, "nothing set: -1")

print("== Restore while recording")


class Running(object):
    running = True
    info = {"url": URL}


plugin.RECORDINGS.active["x"] = Running()
cfg_screen = plugin.vavoo_config.__new__(plugin.vavoo_config)
cfg_screen.session = harness.Session()
del NOTES[:]
plugin.vavoo_config.restore(cfg_screen)
check(NOTES == ["Not now: a recording is running"], "refused, as in the app")
plugin.RECORDINGS.active.clear()

channel.close()
shutil.rmtree(TMP, ignore_errors=True)
finish()
