# -*- coding: utf-8 -*-
"""The direct keys (keymap.xml's VavooListActions / VavooMainActions,
FAV and HELP in the players): what each does in each screen on the real
keymaps of OpenATV, OpenPLi and OpenViX, what the new functions do, and
that every screen's HELP lists the keys it takes."""
from __future__ import print_function
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, V, NOTES, MENUS   # noqa: E402
plugin = harness.plugin
store = harness.store
import test_keys_lib as tk                      # noqa: E402

plugin.ActionMap = tk.RAM
OWN = harness.PLUGIN_DIR + "/keymap.xml"
plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True
plugin.cfg.subcategories = V(False)
plugin.cfg.preview_window = V(True)
plugin.vUtils.RECENT_FILE = store.recent_file()
HELPS = []
real_show_keys = plugin.show_keys
plugin.show_keys = lambda session, rows, title=None: HELPS.append(rows)


class Nav(object):
    def __init__(self):
        self.calls = []

    def getCurrentlyPlayingServiceReference(self):
        return "TV:BEFORE"

    def getCurrentService(self):
        return None

    def stopService(self):
        self.calls.append("stop")

    def playService(self, sref):
        self.calls.append(("play", sref))


def session():
    s = Session()
    s.nav = Nav()
    s.dialog_stack = []
    return s


S = session()
CHANNELS = [{"name": u"RAI 1", "url": "http://127.0.0.1:4323/vavoo?channel=r1", "logo": ""},
            {"name": u"XXX Gold", "url": "http://127.0.0.1:4323/vavoo?channel=x1", "logo": ""}]
store.add_favourite(u"TF1", "http://127.0.0.1:4323/vavoo?channel=f1", "France", "fr")
store.add_favourite(u"RAI 1", CHANNELS[0]["url"], "Italy", "it")

MV = plugin.MainVavoo
mv = MV.__new__(MV)
mv.widgets = {}
MV.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
MV.__getitem__ = lambda self, k: self.widgets[k]
mv.session = S
mv._closed = False
mv.cat = lambda *a: None
MV._initialize_actions(mv)

v = make(plugin.vavoo, S, "Italy", None)
v._preload_channel_picons = lambda: None
v._build_channel_list(CHANNELS)
fav = make(plugin.VavooFavourites, S)
fav._build_list()
recent = make(plugin.VavooFavourites, S, "recent")
GUIDE_CH = [dict(c, country_name="Italy", country_code="it") for c in CHANNELS]
guide = make(plugin.VavooGuide, S, GUIDE_CH, 0, "Italy")
over = make(plugin.VavooGuide, S, GUIDE_CH, 0, "Italy", over_player=True, on_zap=lambda d: None)
recs = make(plugin.VavooRecordings, S)
SCREENS = [("main list", mv), ("channel list", v), ("Favourites", fav), ("Recently watched", recent),
           ("guide", guide), ("guide over the player", over), ("Recordings", recs),
           ("Choose countries", make(plugin.VavooCountries, S, ["Albania", "Italy"])),
           ("Parental Control", make(plugin.VavooParental, S, ["Italy"])),
           ("PIN pad", make(plugin.VavooPin, S, "x", 4, lambda p: None)),
           ("Search", make(plugin.VavooSearch, S, None, [], scope="all channels")),
           ("player channel list", make(plugin.VavooPlayerList, S, [("RAI 1", CHANNELS[0]["url"])], 0,
                                        ["it"], [""], ["Italy"])),
           ("log viewer", make(plugin.VavooLogViewer, S, "Log", "/nonexistent.log"))]

print("== the direct keys, on each image's keymap")
WANT = {
    "main list": {"KEY_FAVORITES": "favourites", "KEY_PVR": "recordings", "KEY_FILE": "recordings",
                  "KEY_VIDEO": "recordings", "KEY_LIST": "recordings", "KEY_TEXT": "search",
                  "KEY_HELP": "help", "KEY_PLAY": "play", "KEY_PLAYPAUSE": "play", "KEY_STOP": "stop",
                  "KEY_RECORD": "record", "KEY_BACK": "back", "KEY_EPG": "epg", "KEY_0": "0"},
    "channel list": {"KEY_FAVORITES": "favourites", "KEY_PVR": "recordings", "KEY_TEXT": "search",
                     "KEY_HELP": "help", "KEY_PLAY": "play", "KEY_STOP": "stop", "KEY_RECORD": "record",
                     "KEY_BACK": "back", "KEY_0": "0"},
    "Favourites": {"KEY_PVR": "recordings", "KEY_TEXT": "search", "KEY_HELP": "help", "KEY_PLAY": "play",
                   "KEY_STOP": "stop", "KEY_RECORD": "record", "KEY_BACK": "back", "KEY_0": "0"},
    "guide": {"KEY_PVR": "recordings", "KEY_HELP": "help", "KEY_PLAY": "play", "KEY_RECORD": "record",
              "KEY_BACK": "back"},
    "guide over the player": {"KEY_HELP": "help", "KEY_PLAY": "play", "KEY_RECORD": "record",
                              "KEY_BACK": "back"},
    "Recordings": {"KEY_HELP": "help", "KEY_PLAY": "play", "KEY_STOP": "stop", "KEY_BACK": "back"},
}
for image, folder in sorted(tk.IMAGES.items()):
    keymap = tk.read_keymap(os.path.join(tk.KEYMAPS, folder, "keymap.xml"))
    tk.read_keymap(OWN, keymap)
    for title, scr in SCREENS:
        maps = [m for m in scr.widgets.values() if isinstance(m, tk.RAM)]
        want = dict(WANT.get(title, {}))
        want.setdefault("KEY_HELP", "help")
        bad = []
        for key, action in sorted(want.items()):
            m, got = tk.dispatch(keymap, maps, key, "m")
            if got != action:
                bad.append("%s -> %r (want %r)" % (key, got, action))
            m2, rel = tk.dispatch(keymap, maps, key, "b")
            if key != "KEY_0" and rel not in (None, "ignore"):
                bad.append("%s release -> %r" % (key, rel))
        check(not bad, "%s, %s: the direct keys%s" % (image, title, "" if not bad else " - " + "; ".join(bad)))

print("== what they do")


def press(scr, action, mapname="list_keys"):
    return scr.widgets[mapname].actions[action]()


# STOP: the window stops, what played before the plugin still comes back
np = plugin.NOW_PLAYING
np.owner, np.channel, np.original, np.has_original = np.PREVIEW, dict(CHANNELS[0]), "TV:BEFORE", True
plugin.vavoo_proxy.proxy = type("P", (), {"stream_ended": lambda self: None, "stream_started": lambda self: None,
                                          "drop_own_signature": lambda self, s: None})()
s2 = session()
plugin.stop_preview(s2)
check(s2.nav.calls == ["stop"] and np.owner is None and np.original == "TV:BEFORE",
      "STOP: the window stops; the service before the plugin is kept for its close")
np.preview_stop(s2)
check(s2.nav.calls[-1] == ("play", "TV:BEFORE"), "...and put back when the plugin closes")
del NOTES[:]
plugin.stop_preview(s2)
check(NOTES == ["Nothing is playing in the window"], "STOP with nothing in the window: said")

# 0: the channel watched last
del NOTES[:]
s3 = session()
plugin.play_last_watched(s3, v)
check(NOTES == ["Nothing watched yet"] and not s3.opened, "0 with nothing watched: said")
plugin.vUtils.add_recent(u"TF1", "http://127.0.0.1:4323/vavoo?channel=f1", "France", "fr")
plugin.vUtils.add_recent(u"RAI 1", CHANNELS[0]["url"], "Italy", "it")
pins = []
real_pin = plugin._require_parental_pin
plugin._require_parental_pin = lambda session, screen, country, ok, **k: (pins.append(country), ok())
plugin.play_last_watched(s3, v)
cls, args, kw, cb = s3.opened[-1]
check(cls is plugin.Playstream2 and args[0] == "RAI 1" and [r[0][0] for r in args[4]] == ["RAI 1", "TF1"],
      "0: RAI 1 (watched last) full screen, the recently watched as the player's list")
check(pins == ["Italy"], "through the parental check of its country")
v.widgets["number_actions"].actions["0"]()
check(S.opened and S.opened[-1][0] is plugin.Playstream2, "0 in the channel list (no number begun)")
v._digits, v._digit_time = "1", time.time()
before = len(S.opened)
v.number(0)
check(len(S.opened) == before and v._digits == "10", "0 after a 1: row 10, not the last channel")

# REC
started, stopped = [], []


class FakeRec(object):
    def stop(self):
        stopped.append(1)


real_rec = plugin.RECORDINGS
plugin.RECORDINGS = type("R", (), {
    "recording_of": lambda self, url: FakeRec() if url in [c["url"] for c in started] else None,
    "start": lambda self, ch, title=None, stop_at=0, **k: started.append(ch) or object(),
    "running": lambda self: []})()
plugin.vUtils.peek_now_next = lambda *a, **k: None
v.widgets["menulist"].moveToIndex(0)
press(v, "record")
check(started and started[0]["name"] == "RAI 1" and started[0]["country_name"] == "Italy",
      "REC in the channel list: the highlighted channel recorded")
press(v, "record")
check(stopped == [1], "again: stopped")
fav.widgets["menulist"].moveToIndex(0)
press(fav, "record")
check(started[-1]["name"] == fav.favourite_entries[0]["name"], "REC in Favourites: the highlighted favourite")
del started[:]
np.owner, np.channel = np.PREVIEW, dict(CHANNELS[0], country_name="Italy", country_code="it")
press(mv, "record")
check(started and started[0]["url"] == CHANNELS[0]["url"], "REC in the main list: the window's channel")
np.owner, np.channel = None, None
del NOTES[:]
press(mv, "record")
check(NOTES == ["Nothing is playing in the window"], "...nothing there: said")

# PLAY, FAV, PVR, TEXT
calls = []
v.full_screen = lambda: calls.append("full")
v.widgets["list_keys"].actions["play"] = v.full_screen
press(v, "play")
check(calls == ["full"], "PLAY in the channel list: full screen")
press(v, "favourites")
check(S.opened[-1][0] is plugin.VavooFavourites, "FAV in the channel list: the favourites")
press(v, "recordings")
check(S.opened[-1][0] is plugin.VavooRecordings, "PVR in the channel list: the recordings")
press(mv, "recordings")
check(S.opened[-1][0] is plugin.VavooRecordings, "PVR in the main list: the recordings")
check("search" not in over.widgets["list_keys"].actions and "recordings" not in over.widgets["list_keys"].actions,
      "over the player, the guide opens no recordings list")

# EPG in the main list: the favourites' guide; Watch plays it
press(mv, "epg", "main_keys")
cls, args, kw, cb = S.opened[-1]
check(cls is plugin.VavooGuide and [c["name"] for c in args[0]] == [e["name"] for e in store.load_favourites()],
      "EPG in the main list: the programme guide of the favourites")
cb(("watch", 1))
cls, args, kw, cb2 = S.opened[-1]
check(cls is plugin.Playstream2 and args[0] == store.load_favourites()[1]["name"] and len(args[4]) == 2,
      "Watch: that favourite full screen, the favourites as the player's list")
for f in store.load_favourites():
    store.remove_favourite(f["url"])
del NOTES[:]
press(mv, "epg", "main_keys")
check(NOTES and NOTES[-1].startswith("No favourites yet"), "no favourites: said")
store.add_favourite(u"RAI 1", CHANNELS[0]["url"], "Italy", "it")

# the guide's REC: the highlighted programme
toggled = []
guide.toggle_record = lambda ch, pr: toggled.append((ch["name"], pr[2]))
now = time.time()
guide._selected_programme = lambda: (now - 60, now + 1800, "Film")
press(guide, "record")
check(toggled == [("RAI 1", "Film")], "REC in the guide: the highlighted programme")
guide._selected_programme = lambda: (now - 3600, now - 60, "Over")
del NOTES[:]
press(guide, "record")
check(len(toggled) == 1 and NOTES == ["No programme to record here"], "a programme that is over: said")

# Recordings: PLAY plays, STOP stops a running one
played = []
recs.ok = lambda: played.append(1)
recs._selected = lambda: ("rec", {"path": "/x.ts"})
press(recs, "play")
check(played == [1], "PLAY in Recordings: the recording plays")
runner = type("Rn", (), {"path": "/x.ts", "stop": lambda self: stopped.append("rec")})()
plugin.RECORDINGS.running = lambda: [runner]
recs.refresh = lambda *a: None
press(recs, "stop")
check(stopped[-1] == "rec", "STOP in Recordings: the running recording stops")
recs._selected = lambda: ("timer", {"id": 1})
press(recs, "play")
check(played == [1], "PLAY on a timer: nothing")
plugin.RECORDINGS = real_rec

# the player: FAV and HELP
player = make(plugin.Playstream2, session(), "TF1", "http://127.0.0.1:4323/vavoo?channel=f1", 0, None,
              [("TF1", "http://127.0.0.1:4323/vavoo?channel=f1")], "fr")
plugin.ACTIVE["player"] = None
player._closed = False
player._bar_visible = lambda: False
zapped = []
player.play_channel = lambda ch: zapped.append(ch["name"])
player.widgets["vavoo_keys"].actions["favourites"]()
cls, args, kw, cb = player.session.opened[-1]
check(cls is plugin.VavooPlayerList and [c[0] for c in args[0]] == ["RAI 1"], "FAV in the player: the favourites over the video")
cb(0)
check(zapped == ["RAI 1"], "the one chosen plays")
check(player.widgets["vavoo_keys"].actions["help"] is not None, "HELP in the player")

print("== HELP lists the keys each screen takes")
LABELS = {"favourites": "FAV", "recordings": "PVR", "search": "TEXT", "play": "PLAY", "stop": "STOP",
          "record": "REC", "red": "RED", "green": "GREEN", "yellow": "YELLOW", "blue": "BLUE",
          "menu": "MENU", "info": "INFO", "epg": "EPG"}
for title, scr in SCREENS + [("player", player)]:
    del HELPS[:]
    keys = scr.widgets.get("list_keys") or scr.widgets.get("vavoo_keys")
    keys.actions["help"]()
    rows = HELPS[-1] if HELPS else []
    text = u" ".join(u"%s %s" % (k, w) for k, w in rows)
    used = set(keys.actions) | set(scr.widgets["actions"].actions if "actions" in scr.widgets else {})
    noop = ("favourites",) if title in ("Favourites", "Recently watched") else ()
    missing = sorted(LABELS[a] for a in used if a in LABELS and a not in noop and LABELS[a] not in text)
    check(rows and not missing, "%s: HELP shows %d keys%s" % (title, len(rows), "" if not missing else
                                                             " - missing " + ", ".join(missing)))
plugin.show_keys = real_show_keys
del MENUS[:]
plugin.show_keys(S, [("OK", "Play")])
check(MENUS and MENUS[-1][0] == "Keys" and MENUS[-1][1][0][0].startswith("OK"), "the keys popup itself")
plugin._require_parental_pin = real_pin
finish()
