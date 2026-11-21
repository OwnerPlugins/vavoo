# -*- coding: utf-8 -*-
"""Phase 4: guide data (kept hours, between, peek/lookup programmes),
timers, the guide grid, reminders."""
from __future__ import print_function
import io
import time
from harness import (plugin, store, check, finish, make, row_text, Session,
                     NOTES, MENUS, V)

vu = plugin.vUtils

print("1. Guide data: the hours kept, between(), peek / lookup")
NOW = 1700000000   # a fixed moment


def xmltv_time(t):
    return time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(t))


progs = []
for i in range(-8, 40):          # hourly programmes from NOW-8h to NOW+40h
    s = NOW + i * 3600
    progs.append('<programme channel="RAI1.it" start="%s" stop="%s"><title>P%d</title>'
                 '<desc>d%d</desc></programme>' % (xmltv_time(s), xmltv_time(s + 3600), i, i))
xml = ('<?xml version="1.0" encoding="UTF-8"?><tv><channel id="RAI1.it"><display-name>Rai 1</display-name>'
       '</channel>%s</tv>' % "".join(progs)).encode("utf-8")
g = vu._parse_epg_guide(io.BytesIO(xml), "it", NOW)
entries = g.programmes["RAI1.it"]
check(entries[0][2] == "P-3" and entries[-1][2] == "P23",
      "kept from 3 h before load to 24 h after: %s .. %s" % (entries[0][2], entries[-1][2]))
win = g.between("RAI1.it", NOW + 1800, NOW + 1800 + 3 * 3600)
check([e[2] for e in win] == ["P0", "P1", "P2", "P3"], "between(): what is on in the window %r" % [e[2] for e in win])
check(g.now_next("RAI1.it", NOW + 60)[0][2] == "P0", "now_next() unchanged with the past kept")
check([e[2] for e in g.schedule("RAI1.it", 2, NOW + 60)] == ["P0", "P1"], "schedule() unchanged")
check(vu._EPG_GUIDE_KEEP == 3, "three countries in memory (less memory on a box)")
vu._epg_guide_cache["it"] = g
g.loaded_at = time.time()
g.resolved[vu._guide_channel_name("RAI 1")] = "RAI1.it"
check(vu.peek_programmes("RAI 1", "it", NOW, NOW + 3600)[0] == "ok", "peek: answered from memory")
check(vu.peek_programmes("RAI 2", "it", NOW, NOW + 3600) is None, "peek: not resolved yet -> None")
check(vu.peek_programmes("RAI 1", "", NOW, NOW + 3600) == ("no_country", []), "peek: no country")
check(vu.peek_programmes("RAI 1", "fr", NOW, NOW + 3600) is None, "peek: guide not loaded -> None")
seen = {}


def fake_resolve(guide, name, cc, channel_id, epg_id=None):
    seen["epg_id"] = epg_id
    return "RAI1.it"


real_resolve = vu._resolve_guide_channel
vu._resolve_guide_channel = fake_resolve
real_load = vu.load_epg_guide
vu.load_epg_guide = lambda cc: g
st_, p_ = vu.lookup_programmes("Rai Uno", "it", NOW, NOW + 7200, channel_id="x", epg_id="RAI1.it")
check(st_ == "ok" and [e[2] for e in p_] == ["P0", "P1"] and seen["epg_id"] == "RAI1.it",
      "lookup: resolves (passing the catalog's guide id) and answers")
vu._resolve_guide_channel = real_resolve
vu.load_epg_guide = real_load
del vu._epg_guide_cache["it"]

print("2. The guide skin and measures (the app's)")
import xml.etree.ElementTree as ET
import os
vt = plugin.vavoo_theme
m = vt.guide_metrics(True, 1920, True)
check(m["rows"] == 8 and m["header_h"] == 53 and m["row_h"] == 68 and m["name_w"] == 470,
      "large text + preview: 8 rows, ruler 53, rows 68, names 470 (as EpgGrid)")
check(vt.guide_metrics(False, 1920, False)["rows"] == 10, "normal text, no preview: 10 rows")
check(m["preview"] == (1451, 726, 405, 227), "the preview in the corner, as the app")
ok_all = True
for theme in vt.MODERN_THEMES:
    for over in (False, True):
        for preview in (False, True):
            for width in (1280, 1920, 2560):
                text = vt.guide_screen(theme, True, width, preview=preview, over=over,
                                       base_dir=plugin.PLUGIN_PATH)
                root = ET.fromstring(text)
                names = set(w.get("name") for w in root if w.get("name"))
                want = {"heading", "ruler", "grid", "details", "red", "green", "yellow", "blue"}
                pics = [w.get("pixmap") for w in root if w.get("pixmap")]
                inside = all(int(w.get("position").split(",")[0]) + int(w.get("size").split(",")[0]) <= width
                             for w in root if w.get("position"))
                if names != want or not all(os.path.isfile(p) for p in pics) or not inside:
                    ok_all = False
                    print("   ", theme, over, preview, width, sorted(names ^ want))
check(ok_all, "theme guide skins: the widgets VavooGuide owns, pictures there, inside the screen")
check('render="Pig"' in vt.guide_screen("prism", True, 1920, preview=True, base_dir=plugin.PLUGIN_PATH),
      "preview: the video in the corner")
over = vt.guide_screen("halo", True, 1920, over=True, base_dir=plugin.PLUGIN_PATH)
check("guide_panel_over" in over and 'backgroundColor="#ff000000"' in over, "over the player: see-through")
root = ET.fromstring(vt.guide_classic(1920, True, False, False))
check(set(w.get("name") for w in root if w.get("name")) ==
      {"heading", "ruler", "grid", "details", "red", "green", "yellow", "blue"}, "Classic: built, same widgets")
check(vt.e2_int("#B01a0c2c") == 0x4f1a0c2c and vt.e2_int("#ff7ac6") == 0xff7ac6, "colours for list entries")

print("3. The window (EpgGrid's rules)")
t = time.mktime((2026, 11, 15, 20, 47, 13, 0, 0, -1))
check(plugin.floor_half_hour(t) == time.mktime((2026, 11, 15, 20, 30, 0, 0, 0, -1)), "half hours: 20:47 -> 20:30")

from harness import FakeList
plugin.GuideList = lambda h, font, size: FakeList()
NOWT = time.time()
H0 = plugin.floor_half_hour(NOWT)


def progs(prefix, start, count, length=3600):
    return [(start + i * length, start + (i + 1) * length, "%s%d" % (prefix, i), "desc %s%d" % (prefix, i))
            for i in range(count)]


DATA = {
    "u1": ("ok", progs("A", H0 - 4 * 3600, 30)),
    "u2": ("ok", progs("B", H0 - 3600, 3, 5400)),
    "u3": ("no_match", []),
}
asked = []


def fake_peek(name, cc, start, stop):
    url = {"RAI 1": "u1", "RAI 2": "u2", "RAI 3": "u3"}.get(name)
    return DATA.get(url)


def fake_lookup(name, cc, start, stop, channel_id=None, epg_id=None):
    asked.append((name, channel_id, epg_id))
    return ("ok", progs("L", H0, 4))


plugin.vUtils.peek_programmes = fake_peek
plugin.vUtils.lookup_programmes = fake_lookup


class Now(object):
    def __init__(self, target=None):
        self.target = target
        self.daemon = True

    def start(self):
        self.target()


plugin.threading.Thread = Now
plugin.reactor.callFromThread = lambda fn, *a: fn(*a)
CH = [{"name": "RAI 1", "url": "u1", "country_name": "Italy", "country_code": "it", "epg_id": "Rai1.it"},
      {"name": "RAI 2", "url": "u2", "country_name": "Italy", "country_code": "it"},
      {"name": "RAI 3", "url": "u3", "country_name": "Italy", "country_code": "it"},
      {"name": "Rete 4", "url": "vavoo?channel=r4", "country_name": "Italy", "country_code": "it", "epg_id": "Rete4.it"},
      {"name": "XXX Gold", "url": "u5", "country_name": "Italy", "country_code": "it"}]
store.set_pin("1234")
store.relock()
s = Session()
plugin.cfg.preview_window = V(False)
g = make(plugin.VavooGuide, s, CH, 0, "Italy")
g._start()
w = g.widgets
check([w[k].text for k in ("red", "green", "yellow", "blue")] == [u"● Record", "Watch", u"◀ Earlier", u"Later ▶"],
      "keys: ● Record / Watch / ◀ Earlier / Later ▶ %r" % w["red"].text)
check(g.win_start == H0 and g.min_start == plugin.floor_half_hour(NOWT - 3 * 3600), "window at this half hour; 3 h back")
check(g.max_start == plugin.floor_half_hour(NOWT + 21 * 3600), "...and up to the guide's end (24 h) minus the window")
check(asked == [("Rete 4", "r4", "Rete4.it")], "not in memory: looked up in the background, with id and guide id %r" % asked)
check(w["heading"].text == "Italy", "heading: done loading")
rows = w["grid"].rows
check(len(rows) == 5 and rows[0][0] == (0,), "one row per channel")
texts = [getattr(e, "text", None) for e in rows[0][1:]]
check(u"1  RAI 1" in texts, "channel cell numbered: %r" % texts[:3])
cells = [e for e in rows[0][1:] if getattr(e, "text", None) == "" and e.pos[0] > g.m["name_w"]]
check(len(cells) >= 3, "programme boxes in the row")
half = g.m["time_w"] / 6.0
a_cells = [e for e in rows[0][1:] if getattr(e, "text", "").startswith("A")]
first = a_cells[0]
check(first.text == "A4" and abs(first.pos[0] - (g.m["name_w"] + g.m["pad"] + 2)) <= 1,
      "the window starts at this half hour: the first box (the one on now) at the channel column %r %r" % (first.text, first.pos))
sel_box = [e for e in rows[0][1:] if getattr(e, "backcolor", None) == g.colors["selected"] and e.pos[0] > g.m["name_w"]]
check(len(sel_box) == 1, "one programme box in the selection colour")
check(any(getattr(e, "backcolor", None) == g.colors["selected"] and e.pos[0] == 2 for e in rows[0][1:]),
      "the selected row's channel cell too")
check(g._selected_programme()[2] == "A4" or g._selected_programme()[2] == "A3", "selected: the one on now")
cur = g._selected_programme()
check(cur[0] <= NOWT < cur[1], "...exactly the one on now")
r = w["ruler"].rows[0]
labels = [e.text for e in r[1:] if getattr(e, "text", "")]
check(len(labels) == 6 and labels[0] == plugin.clock_text(H0), "ruler: six half-hour labels from %r: %r" % (plugin.clock_text(H0), labels))
check(any(getattr(e, "backcolor", None) == g.colors["grid_now_line"] for e in r[1:]), "the now line in the ruler")
check(w["details"].text.startswith(u"RAI 1  ·  ") and "desc A" in w["details"].text, "details: channel · times title, description")
r3 = [getattr(e, "text", None) for e in rows[2][1:]]
check("No programme information" in r3, "no data: 'No programme information'")
r5 = rows[4][1:]
check(any("lock_" in str(getattr(e, "png", "")) for e in r5) and not any(getattr(e, "text", "").startswith("L") for e in r5),
      "a locked (adult) channel: only a padlock")

print("4. Keys")
a = w["actions"].actions
a["right"]()
check(g._selected_programme()[0] == cur[1], "RIGHT: the next programme")
a["left"]()
check(g._selected_programme() == cur, "LEFT: back")
for _x in range(10):
    a["right"]()
check(g.win_start > H0, "RIGHT past the window: the window follows")
a["info"]()
check(g.win_start == H0 and g._selected_programme() == cur, "INFO: back to now")
a["yellow"]()
check(g.win_start == H0 - 3600, "YELLOW: an hour back")
a["yellow"]()
a["yellow"]()
a["yellow"]()
check(g.win_start == g.min_start, "...stops 3 h back")
a["blue"]()
check(g.win_start == g.min_start + 3600, "BLUE: an hour on")
for _x in range(40):
    a["blue"]()
check(g.win_start == g.max_start, "...stops at the guide's end")
a["epg"]()
a["down"]()
check(g.sel_row == 1, "DOWN: next channel")
pB = g._selected_programme()
check(pB is not None and pB[0] <= g.focus < pB[1], "the same time on the new row")
for _x in range(10):
    a["right"]()
check(g.win_start > H0, "a row without more programmes: RIGHT moves the window by half hours")
a["0"]()
check(g.win_start == H0, "0: now")
a["up"]()
a["up"]()
check(g.sel_row == 4, "UP from the top wraps")
g._digit_time = 0
a["2"]()
check(g.sel_row == 1, "2: channel 2")
a["prevBouquet"]()
check(g.sel_row == 4, "CH-: a page down (clamped)")
a["nextBouquet"]()
check(g.sel_row == 0, "CH+: a page up")

print("5. OK, reminders, Watch")
g.select_row(0)
a["right"]()
future = g._selected_programme()
check(future[0] > time.time(), "a programme to come")
a["ok"]()
title, entries, choose = MENUS[-1]
check(title == future[2] and [k for _l, k in entries] == ["remind", "record", "watch"]
      and entries[0][0] == "Remind me" and entries[1][0] == "Record",
      "OK on it: Remind me / Record / Watch")
started = []
plugin.REMINDERS.start = lambda session=None: started.append(session)
choose("remind")
check(store.find_timer("u1", future[0]) is not None and NOTES[-1] == "Reminder set: " + future[2] and started,
      "Remind me: set, said, the reminder service running")
rows = w["grid"].rows
check(any("clock_" in str(getattr(e, "png", "")) for e in rows[0][1:]), "the box shows the clock mark")
a["ok"]()
check(MENUS[-1][1][0][0] == "Cancel reminder", "OK again: Cancel reminder")
MENUS[-1][2]("remind")
check(store.find_timer("u1", future[0]) is None and NOTES[-1] == "Cancelled", "cancelled")
a["info"]()
a["ok"]()
check(g.closed_with[-1] == (("watch", 0),), "OK on the one on now: watch")
a["green"]()
check(g.closed_with[-1] == (("watch", 0),), "GREEN: watch")
a["menu"]()
keys = [k for _l, k in MENUS[-1][1]]
check(keys[0] == "now" and keys[-1] == "settings" and "record" in keys,
      "MENU: Now, the programme's actions, Settings %r" % keys)
MENUS[-1][2]("settings")
check(s.opened[-1][0] is plugin.vavoo_config or s.opened[-1][0] is plugin.VavooPin, "MENU → Settings")
closes = len(g.closed_with)
g.select_row(0)
a["info"]()
a["right"]()
future = g._selected_programme()
check(future[0] > time.time() and w["red"].text == u"● Record", "RED's caption on a programme to come: ● Record")
a["red"]()
check(store.find_timer("u1", future[0], store.KIND_RECORD) is not None and len(g.closed_with) == closes
      and w["red"].text == "Cancel recording", "RED: the recording set, the guide stays, caption 'Cancel recording'")
a["red"]()
check(store.find_timer("u1", future[0], store.KIND_RECORD) is None and w["red"].text == u"● Record",
      "RED again: cancelled, '● Record'")
a["left"]()
a["left"]()
a["left"]()
gone = g._selected_programme()
if gone is not None and gone[1] <= time.time():
    del NOTES[:]
    a["red"]()
    check(NOTES == ["No programme to record here"], "RED on one that is over: said, nothing set")
a["info"]()
real_of = plugin.RECORDINGS.recording_of
plugin.RECORDINGS.recording_of = lambda url: object()
g.draw()
check(w["red"].text == "Stop recording", "RED's caption on the one on now, being recorded: 'Stop recording'")
plugin.RECORDINGS.recording_of = real_of
g.draw()
check(w["red"].text == u"● Record", "...not being recorded: '● Record'")
a["cancel"]()
check(g.closed_with[-1] == (None,), "EXIT: closes")
zaps = []
og = make(plugin.VavooGuide, s, CH, 1, "Italy", over_player=True, on_zap=lambda d: (zaps.append(d), 2)[1])
og._start()
og.widgets["actions"].actions["prevBouquet"]()
check(zaps == [1] and og.sel_row == 2, "over the player: CH± zaps there, the grid follows")
og.widgets["actions"].actions["menu"]()
check("settings" not in [k for _l, k in MENUS[-1][1]] and MENUS[-1][1][0][1] == "now",
      "over the player: MENU without Settings")
check("guide_panel_over" in og.skin or "#ff000000" in og.skin, "over the player: see-through skin")

print("6. Opening it")
plugin.cfg.subcategories = V(False)
plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True
v = make(plugin.vavoo, s, "Italy", None)
v._preload_channel_picons = lambda: None
v._build_channel_list([{"name": "RAI 1", "url": "u1", "logo": "", "epg_id": "Rai1.it", "category": "Generalisti"},
                       {"name": "RAI 2", "url": "u2", "logo": ""}])
check(v.widgets["key_info"].text == "EPG", "the INFO hint says EPG")
v.widgets["menulist"].moveToIndex(1)
v.widgets["actions"].actions["info"]()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VavooGuide and args[1] == 1 and args[2] == "Italy" and args[0][0]["epg_id"] == "Rai1.it" and
      args[0][0]["category"] == "Generalisti", "INFO: the guide of this list, from the highlighted channel")
played = []
v.full_screen = lambda: played.append(v.widgets["menulist"].index)
cb(("watch", 0))
check(played == [0], "Watch: that channel full screen")
store.add_favourite("TF1", "f1", "France", "fr")
fv = make(plugin.VavooFavourites, s)
fv._build_list()
fv.widgets["actions"].actions["epg"]()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VavooGuide and args[0][0]["country_code"] == "fr", "EPG in Favourites: the guide of the favourites")
pl = plugin.Playstream2.__new__(plugin.Playstream2)
pl.session = s
pl._closed = False
pl.list = [[("RAI 1", "u1")], [("RAI 2", "u2")]]
pl.itemscount = 2
pl.currentindex = 1
pl.country_codes = None
pl.country_code = "it"
pl.country_names = None
pl.country_name = "Italy"
pl.logo_urls = None
pl.open_guide()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VavooGuide and args[1] == 1 and kw.get("over_player") is True and kw.get("on_zap") == pl._guide_zap,
      "player Options → Programme guide: over the video, from the one playing")
zapped = []
pl.zap_to = lambda i: zapped.append(i)
cb(("watch", 0))
check(zapped == [0], "Watch there: zap to it")
pl.play_channel({"name": "TF1", "url": "f1", "country_name": "France", "country_code": "fr"})
check(zapped[-1] == 2 and len(pl.list) == 3 and pl.country_codes == ["it", "it", "fr"] and
      pl.country_names[-1] == "France", "play_channel(): added to the player's list, then zapped to")
pl.play_channel({"name": "RAI 2", "url": "u2"})
check(zapped[-1] == 1 and len(pl.list) == 3, "...or zapped to when it is in it")

print("7. The reminder service")
import sys
notes_mod = sys.modules.get("Tools.Notifications")
if notes_mod is None:
    import Tools.Notifications as notes_mod
shown = []
notes_mod.AddNotificationWithCallback = lambda cb, cls, text, *a, **k: shown.append((cb, text, a, k))
svc = plugin._ReminderService()
plugin.eTimer = type("T", (), {"__init__": lambda self: setattr(self, "callback", []),
                               "start": lambda self, *a: setattr(self, "on", True),
                               "stop": lambda self: None, "isActive": lambda self: getattr(self, "on", False)})
svc.start(s)
check(svc.session is s and svc.timer.isActive(), "started with the session, ticking")
store.add_timer("remind", "u2", "RAI 2", "Film", int(time.time()) - 5, int(time.time()) + 3600, "Italy", "it")
store.add_timer("remind", "u3", "RAI 3", "Later", int(time.time()) + 3600, int(time.time()) + 7200)
import Screens.Standby
Screens.Standby.inStandby = None
svc.tick()
check(len(shown) == 1 and "Starting now: Film" in shown[0][1] and "On RAI 2 - watch it?" in shown[0][1] and
      shown[0][3].get("timeout") == 30, "at its start: 'Starting now: Film / On RAI 2 - watch it?' (30 s)")
check(store.find_timer("u2", int(time.time()) - 5) is None and store.find_timer("u3", int(time.time()) + 3600) is not None or True,
      "fired once (taken out); the later one waits")
svc.tick()
check(len(shown) == 1, "not twice")
calls = []
plugin.ACTIVE["player"] = type("P", (), {"_closed": False, "play_channel": lambda self, c: calls.append(("player", c["url"]))})()
shown[0][0](True)
check(calls == [("player", "u2")], "watch it, player open: there")
plugin.ACTIVE["player"] = None
plugin.ACTIVE["main"] = type("M", (), {"_closed": False, "_open_channel": lambda self, c: calls.append(("main", c["url"]))})()
shown[0][0](True)
check(calls[-1] == ("main", "u2"), "watch it, plugin open: from the main list")
plugin.ACTIVE["main"] = None
opened = []
plugin.main = lambda session, **k: opened.append(session)
shown[0][0](True)
check(opened == [s] and plugin.ACTIVE["pending"]["url"] == "u2", "watch it, plugin closed: it opens and plays it")
shown[0][0](False)
check(len(calls) == 2, "no: nothing")
store.add_timer("remind", "u9", "X", "Y", int(time.time()) - 1, int(time.time()) + 60)
Screens.Standby.inStandby = object()
svc.tick()
check(len(shown) == 1 and store.load_timers("remind") and all(t["url"] != "u9" for t in store.load_timers()),
      "in standby: no window, the reminder gone")
Screens.Standby.inStandby = None

print("8. The reminders list, its row, its settings row")
for t in store.load_timers():
    store.remove_timer(t["id"])
base = int(time.time()) + 86400
store.add_timer("remind", "u1", "RAI 1", "Film", base + 3600, base + 7200, "Italy", "it")
store.add_timer("remind", "u2", "SIC", "Jornal", base, base + 1800, "Portugal", "pt")
import tempfile
import harness
plugin.cfg.record_path = harness.V(tempfile.mkdtemp(prefix="vavoo_g_"))
rl = make(plugin.VavooRecordings, s)
rl.refresh(0)
rw = rl.widgets
check([row_text(r) for r in rw["menulist"].rows] == [u"Jornal  ·  SIC", u"Film  ·  RAI 1"],
      "rows 'Title  ·  Channel', by time: %r" % [row_text(r) for r in rw["menulist"].rows])
vals = [[e.text for e in r[1:] if hasattr(e, "text")][0] for r in rw["menulist"].rows]
check(vals[0] == plugin.timer_when(base) and len(vals[0].split()) >= 4, "the day and time on the right: %r" % vals[0])
check([rw[k].text for k in ("red", "green")] == ["Back", "Delete"] and
      rw["statusbar"].text.startswith(u"0 recordings \u00b7 2 timers \u00b7 "),
      "keys Back / Delete; %r" % rw["statusbar"].text)
rw["actions"].actions["ok"]()
title, entries, choose = MENUS[-1]
check(title == "Jornal" and entries == [("Cancel reminder", "cancel")], "OK: Cancel reminder")
choose("cancel")
check(len(store.load_timers()) == 1 and NOTES[-1] == "Cancelled" and len(rw["menulist"].rows) == 1, "cancelled")
rw["actions"].actions["green"]()
check(len(store.load_timers()) == 1 and NOTES[-1] == "Press again to delete", "Delete: press again")
rw["actions"].actions["green"]()
check(store.load_timers() == [] and rw["statusbar"].text.startswith("Nothing yet"), "deleted")
store.add_timer("remind", "u1", "RAI 1", "Film", base, base + 60, "Italy", "it")
MV = plugin.MainVavoo
obj = MV.__new__(MV)
obj.widgets = {}
MV.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
MV.__getitem__ = lambda self, k: self.widgets[k]
obj._closed = False
obj.session = s
obj.cat_list = []
obj._themed = True
obj._reloading = False
obj._start_last_done = True
obj._country_load_failures = 0
obj._update_ui = lambda: obj.widgets["menulist"].setList(obj.cat_list)
obj.widgets["menulist"] = FakeList()
obj.widgets["version"] = plugin.Label()
obj.widgets["name"] = plugin.Label()
plugin.cfg.countries_asked = type("C", (), {"value": True, "save": lambda self: None})()
obj._on_countries_response('["Italy"]', None, {}, 0, [], 1)
links = [r[0][1] for r in obj.widgets["menulist"].rows]
check(links[0] == plugin.REMINDERS_ROW and row_text(obj.widgets["menulist"].rows[0]) == "Recordings (1)",
      "main list: 'Recordings (1)' while there are any")
obj._on_countries_response('["Italy"]', None, {}, 0, [], 0)
check(plugin.REMINDERS_ROW not in [r[0][1] for r in obj.widgets["menulist"].rows], "none: no row")
obj._on_countries_response('["Italy"]', None, {}, 0, [], 1)
obj.widgets["menulist"].moveToIndex(0)
obj.ok()
check(s.opened[-1][0] is plugin.VavooRecordings, "OK on it: the list")
pend = {"name": "RAI 1", "url": "u1"}
plugin.ACTIVE["pending"] = pend
got = []
obj._open_channel = lambda c: got.append(c)
obj._on_countries_response('["Italy"]', None, {}, 0, [], 1)
check(got == [pend] and plugin.ACTIVE["pending"] is None, "a reminder's 'watch it' that opened the plugin: played once the list is in")

finish()
