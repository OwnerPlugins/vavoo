# -*- coding: utf-8 -*-
"""Phase 5 screens: Record in the guide (OK / MENU, the "● " mark),
the Recordings list (timers + recordings, OK, delete twice, PIN) and
the recording player."""
from __future__ import print_function
import os
import shutil
import tempfile
import time

from harness import (plugin, store, check, finish, make, row_text, Session,
                     NOTES, MENUS, V, FakeList)
import vavoo.vavoo_record as vr

TMP = tempfile.mkdtemp(prefix="vavoo_recl_")
plugin.cfg.record_path = V(TMP)
plugin.cfg.services = V("4097")
plugin.GuideList = lambda h, font, size: FakeList()
NOWT = time.time()
H0 = plugin.floor_half_hour(NOWT)
URL1 = "http://127.0.0.1:4323/vavoo?channel=rai1"
URL5 = "http://127.0.0.1:4323/vavoo?channel=xxx"


def progs(prefix, start, count, length=3600):
    return [(start + i * length, start + (i + 1) * length, "%s%d" % (prefix, i), "")
            for i in range(count)]


DATA = {"RAI 1": ("ok", progs("A", H0 - 3600, 12)),
        "XXX Gold": ("ok", progs("X", H0 - 3600, 12))}
plugin.vUtils.peek_programmes = lambda name, cc, a, b: DATA.get(name)
plugin.vUtils.lookup_programmes = lambda *a, **k: ("ok", [])


class Now(object):
    def __init__(self, target=None):
        self.target = target
        self.daemon = True

    def start(self):
        self.target()


real_thread = plugin.threading.Thread
plugin.threading.Thread = Now
plugin.reactor.callFromThread = lambda fn, *a: fn(*a)
started = []
plugin.REMINDERS.start = lambda session=None: started.append(1)
recs = []


class FakeRec(object):
    def __init__(self, path=None, duration=0):
        self.running = True
        self.finished = False
        self.stopped = False
        self.path = path
        self.duration = duration
        self.info = {"url": URL1}
        self.file_id = "f00d"

    def stop(self):
        self.stopped = True
        self.running = False

    def join(self, timeout=None):
        pass

    def offset_for(self, seconds):
        return int(seconds) * 188 * 100

    def time_at(self, offset):
        return offset / (188 * 100.0)


real_start = plugin.RECORDINGS.start


def fake_start(channel, title=None, stop_at=0, quiet=False):
    rec = FakeRec()
    rec.info = {"url": channel["url"], "title": title}
    recs.append((channel, title, stop_at, rec))
    plugin.RECORDINGS.active[str(len(recs))] = rec
    return rec


plugin.RECORDINGS.start = fake_start
CH = [{"name": "RAI 1", "url": URL1, "country_name": "Italy", "country_code": "it", "logo": ""},
      {"name": "XXX Gold", "url": URL5, "country_name": "Italy", "country_code": "it", "logo": ""}]
store.set_pin("1234")
store.relock()
s = Session()
plugin.cfg.preview_window = V(False)
g = make(plugin.VavooGuide, s, CH, 0, "Italy")
g._start()
a = g.widgets["actions"].actions

print("1. Record in the guide")
g.select_row(0)
a["right"]()
future = g._selected_programme()
check(future[0] > time.time(), "a programme to come: " + future[2])
a["ok"]()
title, entries, choose = MENUS[-1]
check([k for _l, k in entries] == ["remind", "record", "watch"], "OK: Remind me / Record / Watch")
choose("record")
timer = store.find_timer(URL1, future[0], store.KIND_RECORD)
check(timer is not None and timer["stop"] == int(future[1]) and timer["country"] == "Italy",
      "Record: a recording timer set (channel, country, end)")
check(NOTES[-1] == "Recording set: " + future[2] and started, "said, the timer service running")


def box_titles(row=0):
    return [e.text for e in g.widgets["grid"].rows[row][1:] if getattr(e, "text", None)]


check(u"● " + future[2] in box_titles(), "its box: '● %s'" % future[2])
a["ok"]()
check(MENUS[-1][1][1] == ("Cancel recording", "record"), "OK again: Cancel recording")
MENUS[-1][2]("record")
check(store.find_timer(URL1, future[0], store.KIND_RECORD) is None and NOTES[-1] == "Cancelled", "cancelled")
check(future[2] in box_titles() and u"● " + future[2] not in box_titles(), "the mark goes")
a["info"]()
on_now = g._selected_programme()
check(on_now[0] <= time.time() < on_now[1], "the one on now: " + on_now[2])
a["menu"]()
keys = [k for _l, k in MENUS[-1][1]]
check(keys == ["now", "record", "settings"], "MENU on it: Now / Record / Settings %r" % keys)
MENUS[-1][2]("record")
channel, title, stop_at, rec = recs[-1]
check(channel["url"] == URL1 and title == on_now[2] and stop_at == on_now[1] + store.RECORD_MARGIN,
      "Record: at once, until its end plus 2 minutes")
check(NOTES[-1].startswith("Recording: " + on_now[2]), "said: " + NOTES[-1])
check(u"● " + on_now[2] in box_titles(), "the one being recorded is marked")
a["menu"]()
check(MENUS[-1][1][1] == ("Stop recording", "record"), "MENU again: Stop recording")
MENUS[-1][2]("record")
check(rec.stopped and NOTES[-1] == "Recording stopped", "stopped")
plugin.RECORDINGS.active.clear()
pins = []
real_ask = plugin.ask_pin
plugin.ask_pin = lambda session, screen, ok: pins.append(ok)
g.select_row(1)
a["menu"]()
check([k for _l, k in MENUS[-1][1]] == ["now", "settings"], "a locked channel (padlock, no programmes): no Record")
MENUS[-1][2]("record")
check(len(recs) == 1, "...and nothing recorded")
g.toggle_record(CH[1], DATA["XXX Gold"][1][1])
check(pins and len(recs) == 1, "asked for one anyway: the PIN first")
pins[-1]()
check(len(recs) == 2 and recs[-1][0]["name"] == "XXX Gold", "after the PIN: recorded")
plugin.RECORDINGS.active.clear()
a["red"]()

print("2. The Recordings list")
for t in store.load_timers():
    store.remove_timer(t["id"])
base = int(time.time()) + 86400
store.add_timer(store.KIND_RECORD, URL1, "RAI 1", "Film", base + 3600, base + 7200, "Italy", "it")
store.add_timer(store.KIND_REMIND, "u2", "SIC", "Jornal", base, base + 1800, "Portugal", "pt")


def recording(name, title, start, duration, country="Italy"):
    path = vr.new_path(TMP, name, title, start)
    with open(path, "wb") as f:
        f.write(b"\x47" + b"\x00" * 187)
    vr.write_info(path, {"format": vr.INFO_FORMAT, "name": name, "title": title, "start": start,
                         "duration": duration, "country": country, "url": URL1})
    return path


old = time.mktime((2026, 11, 17, 20, 0, 0, 0, 0, -1))
p_old = recording("RAI 1", "Telegiornale", old, 45 * 60)
p_new = recording("Canale 5", "Canale 5", old + 3600, 30 * 60)
p_adult = recording("XXX Gold", "Night", old - 3600, 600)
rl = make(plugin.VavooRecordings, s)
rl.refresh(0)
w = rl.widgets
texts = [row_text(r) for r in w["menulist"].rows]
check(texts == [u"Jornal  ·  SIC", u"● Film  ·  RAI 1", u"Canale 5",
                u"Telegiornale  ·  RAI 1", u"Night  ·  XXX Gold"],
      "timers by time (● a recording), then recordings, newest first: %r" % texts)


def value(index):
    return [e.text for e in w["menulist"].rows[index][1:] if hasattr(e, "text")][0]


check(value(3) == u"17/11 20:00 · 45 min", "start and length on the right: %r" % value(3))
check(value(0) == plugin.timer_when(base), "a timer's day and time")
check(w["statusbar"].text.startswith(u"3 recordings · 2 timers · ") and "free" in w["statusbar"].text,
      "status: %r" % w["statusbar"].text)
check([w[k].text for k in ("red", "green")] == ["Back", "Delete"], "keys Back / Delete")
live = FakeRec(p_new, 12 * 60 + 5)
plugin.RECORDINGS.active["live"] = live
rl.refresh()
check(value(2) == u"● REC · 12 min", "being recorded: '● REC · 12 min'")
check(rl._timer.__class__.__name__ == "FakeTimer", "(refreshed while recording)")
rl.widgets["menulist"].moveToIndex(1)
w["actions"].actions["ok"]()
check(MENUS[-1][1] == [("Cancel recording", "cancel")], "OK on a recording timer: Cancel recording")
MENUS[-1][2]("cancel")
check(len(store.load_timers()) == 1 and NOTES[-1] == "Cancelled", "cancelled")
texts = [row_text(r) for r in w["menulist"].rows]
check(texts[1] == u"Canale 5" and w["menulist"].getSelectedIndex() == 1, "the list follows")
w["menulist"].moveToIndex(2)
w["actions"].actions["ok"]()
check(s.opened[-1][0] is plugin.VavooRecordingPlayer and s.opened[-1][1][0]["path"] == p_old,
      "OK on a recording: played")
w["menulist"].moveToIndex(3)
store.relock()
w["actions"].actions["ok"]()
check(pins and not s.opened[-1][1][0]["path"] == p_adult, "an adult channel's recording: the PIN first")
pins[-1]()
check(s.opened[-1][0] is plugin.VavooRecordingPlayer and s.opened[-1][1][0]["path"] == p_adult,
      "after the PIN: played")
w["menulist"].moveToIndex(2)
w["actions"].actions["green"]()
check(os.path.exists(p_old) and NOTES[-1] == "Press again to delete", "Delete: press again")
w["actions"].actions["green"]()
check(not os.path.exists(p_old) and not os.path.exists(p_old + vr.INFO_SUFFIX) and NOTES[-1] == "Deleted",
      "deleted with its record")
w["menulist"].moveToIndex(1)
w["actions"].actions["green"]()
w["actions"].actions["green"]()
check(live.stopped and not os.path.exists(p_new), "a running one: stopped, then deleted")
plugin.RECORDINGS.active.clear()
for t in store.load_timers():
    store.remove_timer(t["id"])
vr.delete_recording(p_adult)
rl.refresh()
check(w["menulist"].rows == [] and w["statusbar"].text.startswith("Nothing yet"), "empty: what to do")
plugin.ask_pin = real_ask

print("3. The recording player")


class SRef(object):
    def __init__(self, *args):
        self.args = args
        self.ref = args[0] if len(args) == 1 else args

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

    def getCurrentlyPlayingServiceReference(self):
        return "TV:BEFORE"

    def getCurrentService(self):
        return None


s.nav = Nav()
path = recording("RAI 1", "Telegiornale", old, 45 * 60)
data = [r for r in vr.list_recordings(TMP) if r["path"] == path][0]
plugin.NOW_PLAYING.owner = None
rp = make(plugin.VavooRecordingPlayer, s, data)
check(rp.skinName == "VavooPlayer" and "progress" in rp.widgets and all(
    k in rp.widgets for k in plugin.PLAYER_BAR_LABELS), "the theme's player bar, its widgets")
rp._start()
check(s.nav.calls[-2:] == ["stop", ("play", (4097, 0, path))], "a finished one: its file, the player type")
moved = []
rp.doSeekRelative = lambda pts: moved.append(pts)
rp.widgets["actions"].actions["right"]()
rp.widgets["actions"].actions["blue"]()
rp.widgets["actions"].actions["left"]()
check(moved == [900000, 2700000, -900000], "RIGHT 10 s, BLUE 30 s, LEFT -10 s (Enigma2's own seek)")
check(rp.isSeekable(), "seekable")
check(rp.widgets["name"].text == "Telegiornale" and rp.widgets["key_red"].text == "Back"
      and rp.widgets["next"].text.endswith("/ 45:00"), "bar: title, Back, '0:00 / 45:00'")
check(rp.widgets["key_options"].text == "MENU Options" and rp.widgets["key_list"].text == u"\u25c0 10 s \u25b6"
      and "key_audio" not in rp.widgets, "small keys: 'MENU Options', '\u25c0 10 s \u25b6' (LEFT / RIGHT)")
check(not any(k.startswith("sel_") for k in rp.widgets), "no bar highlights")
rp.widgets["actions"].actions["menu"]()
check(MENUS[-1][0] == "Options" and [k for _l, k in MENUS[-1][1]] == ["audioSelection", "subtitleSelection"],
      "MENU: the options (Audio track, Subtitles), as in the live player")
rp._on_close()
check(s.nav.calls[-2:] == ["stop", ("play", "TV:BEFORE")], "closed: what played before")

live = FakeRec(path, 600)
plugin.RECORDINGS.active["live"] = live
s.nav = Nav()
rp = make(plugin.VavooRecordingPlayer, s, data)
rp._start()
url = s.nav.calls[-1][1]
check("/file%3f" in url or "/file?" in url, "being recorded: through /file")
check("id=f00d" in url and "offset=0" in url and "follow=1" in url, "from its start, followed")
check(not rp.isSeekable() and rp.widgets["number"].text == u"● REC", "'● REC' on the bar")
rp._clock = time.time() - 20
rp.widgets["actions"].actions["left"]()
check(abs(rp._pos - 10) < 1.5 and rp._clock is None, "LEFT: 10 s back, opened once the keys rest")
rp._seek_now()
check("offset=%d" % (10 * 188 * 100) in s.nav.calls[-1][1] or "offset=1880" in s.nav.calls[-1][1],
      "opened there: %s" % s.nav.calls[-1][1].split("offset=")[1][:10])
rp.widgets["actions"].actions["ok"]()
check(rp._paused, "OK: paused")
rp.widgets["actions"].actions["ok"]()
check(not rp._paused and s.nav.calls[-2] == "stop", "OK: on from there")
plugin.cfg.theme = V("classic")
plugin._theme_skin_cache.clear()
del NOTES[:]
s.nav = Nav()
cp = make(plugin.VavooRecordingPlayer, s, data)
cp._start()
check(cp.skinName == "MoviePlayer" and NOTES and NOTES[-1].startswith("LEFT / RIGHT 10 s"),
      "Classic: Enigma2's bar, and the keys said once: %r" % NOTES[-1:])
cp._on_close()
plugin.cfg.theme = V("prism")
plugin._theme_skin_cache.clear()
plugin.NOW_PLAYING.owner = plugin.NOW_PLAYING.PREVIEW
released = []
plugin.NOW_PLAYING.release_preview = lambda: released.append(1)
s.nav = Nav()
rp = make(plugin.VavooRecordingPlayer, s, data)
rp._start()
rp._on_close()
check(released and s.nav.calls[-1] == "stop", "over a preview: it is let go, nothing put back")
plugin.RECORDINGS.active.clear()

plugin.threading.Thread = real_thread
plugin.RECORDINGS.start = real_start
shutil.rmtree(TMP, ignore_errors=True)
finish()
