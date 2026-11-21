# -*- coding: utf-8 -*-
"""Phase 2: the preview window, the hand-over to the full-screen
player and back, "Recently watched", the mini guide, and the player's
own logic (keys, channel numbers, recall, favourites, sleep timer,
info bar), with Enigma2 faked. Run via run_player_tests.sh."""
from __future__ import print_function
import json
import os
import sys
import time as real_time
import types
import xml.etree.ElementTree as ET

import e2env                                    # noqa: E402
PLUGIN_DIR = e2env.PLUGIN_DIR
PREFS = e2env.DATA
import vavoo.vavoo_store as vstore              # noqa: E402,F401
plugin = e2env.load_plugin()
import vavoo.vUtils as vu                       # noqa: E402
import vavoo.vavoo_theme as vt                  # noqa: E402

FAILS = 0
CHECKS = 0


def check(cond, what):
    global FAILS, CHECKS
    CHECKS += 1
    if not cond:
        FAILS += 1
        print("  FAIL: " + what)
    else:
        print("  ok:   " + what)


# ---------------------------------------------------------------- fakes
class Nav(object):
    def __init__(self, current="TV:RTP1"):
        self.calls = []
        self.current = current

    def stopService(self):
        self.calls.append("stop")

    def playService(self, sref):
        self.calls.append(("play", getattr(sref, "ref", sref)))

    def getCurrentlyPlayingServiceReference(self):
        return self.current


class Session(object):
    def __init__(self):
        self.nav = Nav()
        self.opened = []

    def open(self, *a, **k):
        self.opened.append((None, a, k))

    def openWithCallback(self, cb, *a, **k):
        self.opened.append((cb, a, k))


class SRef(object):
    def __init__(self, ref):
        self.ref = ref

    def setName(self, name):
        self.name = name


class FakeProxy(object):
    def __init__(self):
        self.active_streams = 0
        self.failures = []

    def stream_started(self):
        self.active_streams += 1

    def stream_ended(self):
        self.active_streams = max(0, self.active_streams - 1)

    def report_stream_failure(self, cid):
        self.failures.append(cid)

    def get_group_sources(self, gid):
        return {"members": [{"id": "A", "label": "SIC .b"}, {"id": "B", "label": "SIC HD .s"}],
                "current": "B"}


class V(object):
    def __init__(self, value):
        self.value = value


class FakeLabel(object):
    def __init__(self, text=""):
        self.text = text
        self.visible = True

    def setText(self, t):
        self.text = t

    def getText(self):
        return self.text

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def setValue(self, v):
        self.value = v


class FakeTimer(object):
    def __init__(self):
        self.callback = []
        self.running = None

    def start(self, ms, single=False):
        self.running = ms

    def stop(self):
        self.running = None

    def isActive(self):
        return self.running is not None


plugin.eServiceReference = SRef
plugin.Label = FakeLabel
plugin.eTimer = FakeTimer
plugin._ = lambda s: s
notes = []
plugin.quick_notify = lambda msg, secs=3: notes.append(msg)
plugin.NOTIFICATION_AVAILABLE = True
proxy = FakeProxy()
plugin.vavoo_proxy.proxy = proxy
plugin.cfg.services = V("4097")
plugin.cfg.preview_window = V(True)
plugin.cfg.list_epg = V(True)
plugin.cfg.theme = V("prism")
plugin.cfg.text_size = V("large")
plugin.cfg.clock_format = V("24")
plugin.cfg.parental_pin = V("")
plugin.cfg.parental_countries = V("")
recent_file = os.path.join(PREFS, "vavoo_recent.json")
if not os.path.isdir(os.path.dirname(recent_file)):
    os.makedirs(os.path.dirname(recent_file))
if os.path.exists(recent_file):
    os.unlink(recent_file)
vu.RECENT_FILE = recent_file
fav_file = os.path.join(PREFS, "vavoo_favourites.json")
if os.path.exists(fav_file):
    os.unlink(fav_file)
vu.FAVOURITES_FILE = fav_file
plugin.vavoo_store.set_paths(os.path.dirname(fav_file))


class SyncThread(object):
    """remember_recent()'s background write, done at once."""
    def __init__(self, target=None):
        self.target = target
        self.daemon = True

    def start(self):
        self.target()


URL_SIC = "http://192.168.1.2:4323/vavoo?channel=grp%3Aportugal%3Asic"
URL_RTP = "http://192.168.1.2:4323/vavoo?channel=rtp1"
SREF_SIC = ("4097:0:1:0:0:0:0:0:0:0:http%3a//127.0.0.1%3a4323/vavoo?"
            "channel=grp%3Aportugal%3Asic#User-Agent=VAVOO/2.6:SIC")

# ---------------------------------------------------------------- 1
print("1. One stream: preview window -> full screen -> back")
real_thread = plugin.threading.Thread
plugin.threading.Thread = SyncThread
check(plugin.stream_channel_id(URL_SIC) == "grp:portugal:sic", "channel id decoded")
check(plugin.build_stream_sref("SIC", URL_SIC).ref == SREF_SIC,
      "the preview plays the same plain proxy address the player always used")
check(plugin.build_stream_sref("X", "http://example.com/x.ts") is None, "not a proxy address: nothing")

NP = plugin._NowPlaying()
plugin.NOW_PLAYING = NP
session = Session()
NP.begin(session)
check(NP.original == "TV:RTP1", "what the box played is remembered when the plugin opens")
sic = {"name": "SIC", "url": URL_SIC, "country_name": "Portugal", "country_code": "pt", "logo": ""}
rtp = {"name": "RTP 1", "url": URL_RTP, "country_name": "Portugal", "country_code": "pt", "logo": ""}
check(NP.preview_play(session, sic) and NP.preview_plays(URL_SIC), "OK: SIC plays in the preview window")
check(session.nav.calls == ["stop", ("play", SREF_SIC)] and proxy.active_streams == 1,
      "one service started, proxy count 1")
check(vu.load_recent()[0]["name"] == "SIC", "...and it is at the top of Recently watched")
NP.preview_play(session, rtp)
check(proxy.active_streams == 1 and NP.channel["name"] == "RTP 1", "another channel in the preview: still one stream counted")
NP.preview_play(session, sic)
calls_before = len(session.nav.calls)

# the full-screen player takes over without restarting
ps = plugin.Playstream2.__new__(plugin.Playstream2)
ps.session = session
ps._closed = False
ps.execing = True
ps.stream_running = False
ps.is_streaming = False
ps.name, ps.url = "SIC", URL_SIC
ps.srefInit = None
ps._eof_restart_call = None
ps._inherit_pending = True
ps.hand_back = False
ps.country_name, ps.country_code = "Portugal", "pt"
ps.current_logo_url = None
ps.country_names = None
ps.country_codes = None
ps.logo_urls = None
shown = []
ps.serviceStarted = lambda: shown.append(True)
ps.startStream()
check(len(session.nav.calls) == calls_before and NP.owner == NP.PLAYER,
      "OK again: the player carries on with the same stream - no stop, no new start")
check(ps.stream_running and ps.hand_back and proxy.active_streams == 1 and shown,
      "the player owns it now (count unchanged) and shows its bar")
# zap inside the player
ps.list = [[("SIC", URL_SIC)], [("RTP 1", URL_RTP)]]
ps.itemscount = 2
ps.currentindex = 0
ps._previous_index = None
ps._unlocked = set(["portugal"])
ps._typed = 0
ps._bar_themed = False
ps.eof_recovery_timer = FakeTimer()
ps.nextitem()
check(ps.name == "RTP 1" and proxy.active_streams == 1 and session.nav.calls[-1][0] == "play",
      "CH+: next channel, still one stream counted")
check(vu.load_recent()[0]["name"] == "RTP 1", "the channel zapped to goes to the top of Recently watched")
ps.recall()
check(ps.name == "SIC" and ps._previous_index == 1, "RECALL / 0: back to the channel before")
# close: hand back
calls_before = len(session.nav.calls)
ps.close = lambda *a: setattr(ps, "closed_with", a)
ps.proxy_update_timer = FakeTimer()
ps.hideTimer = FakeTimer()
ps.delayed_start_timer = FakeTimer()
ps.retry_start_timer = FakeTimer()
ps.cancel()
check(len(session.nav.calls) == calls_before and NP.owner == NP.PREVIEW and NP.channel["name"] == "SIC",
      "closing full screen: the channel keeps playing in the preview window")
check(proxy.active_streams == 1 and ps.closed_with == ((0, "SIC", URL_SIC),),
      "count unchanged; the list is told which channel was watched last")
# the plugin closes
NP.preview_stop(session, restore=True)
check(session.nav.calls[-2:] == ["stop", ("play", "TV:RTP1")] and proxy.active_streams == 0,
      "leaving the plugin: the stream stops, the TV channel from before comes back")
check(NP.owner is None and not NP.has_original, "and the state is clean for next time")

# preview off: the old behaviour
session2 = Session()
NP.begin(session2)
ps2 = plugin.Playstream2.__new__(plugin.Playstream2)
ps2.__dict__.update(dict(ps.__dict__))
ps2.session = session2
ps2._closed = False
ps2.stream_running = False
ps2._inherit_pending = True
ps2.hand_back = False
ps2.srefInit = "TV:RTP1"
ps2.name, ps2.url = "SIC", URL_SIC
ps2.startStream()
check(session2.nav.calls == ["stop", ("play", SREF_SIC)] and proxy.active_streams == 1,
      "player opened directly: starts its own stream as before")
ps2.cancel()
check(session2.nav.calls[-2:] == ["stop", ("play", "TV:RTP1")] and proxy.active_streams == 0 and NP.owner is None,
      "...and on close stops it and puts the TV channel back, as before")

# preview failures
session3 = Session()
NP.begin(session3)
NP.preview_play(session3, sic)
results = [NP.preview_failed(session3) for _ in range(4)]
check(results == [True, True, True, False], "a stream that keeps ending in the preview: retried 3 times a minute, then given up")
check(proxy.failures == ["grp:portugal:sic"] * 4 and proxy.active_streams == 0 and NP.owner is None,
      "each failure reported to the proxy (it moves to another source); given up = count back to 0")
NP.preview_stop(session3)

# ---------------------------------------------------------------- 2
print("2. Recently watched")
vu.clear_recent()
for i in range(25):
    vu.add_recent("Ch%d" % i, "u%d" % i, "Portugal", "pt")
vu.add_recent("Ch3", "u3", "Portugal", "pt")
recent = vu.load_recent()
check(len(recent) == 20 and recent[0]["name"] == "Ch3" and recent[1]["name"] == "Ch24",
      "at most 20, newest first, a channel watched again moves to the top (no duplicates)")
check(sum(1 for r in recent if r["name"] == "Ch3") == 1, "each channel once")
open(recent_file, "w").write("{broken")
check(vu.load_recent() == [], "a damaged file reads as empty, never raises")
vu.clear_recent()
check(vu.load_recent() == [], "clear")

# ---------------------------------------------------------------- 3
print("3. Mini guide")
g = vu.EpgGuide("pt", 0)
T = real_time.mktime(real_time.localtime()[:3] + (20, 50, 0, 0, 0, -1))
g.programmes["SIC.pt"] = [
    (T - 3600, T - 600, "Antes", ""),
    (T - 600, T + 1800, "Jornal da Noite", "Noticias do dia."),
    (T - 300, T + 1500, "Sobreposto", "x"),
    (T + 1800, T + 3600, "Linha Aberta", ""),
    (T + 3600, T + 5400, "Filme", ""),
    (T + 5400, T + 7200, "Mais", ""),
    (T + 7200, T + 9000, "Fim", ""),
]
sched = g.schedule("SIC.pt", 4, now=T)
check([p[2] for p in sched] == ["Sobreposto", "Linha Aberta", "Filme", "Mais"],
      "on now (the one that started last, as now_next()) + the next ones, 4 in all %r" % [p[2] for p in sched])
check(g.schedule("SIC.pt", 4, now=T)[0] == g.now_next("SIC.pt", now=T)[0], "agrees with now_next()")
check(g.schedule("nope") == [], "unknown channel: empty")
plugin.time = types.SimpleNamespace(time=lambda: T, localtime=real_time.localtime,
                                    strftime=real_time.strftime)
text = plugin.mini_guide_text("SIC", ("ok", [(T - 600, T + 1800, "Jornal da Noite", "Noticias do dia."),
                                            (T + 1800, T + 3600, "Linha Aberta", "")]), now=T)
lines = text.split("\n")
check(lines[0] == "SIC" and lines[2].startswith(u"▶ ") and "Jornal da Noite" in lines[2]
      and lines[3].strip() == "30 min left" and lines[4].startswith(u"» ") and lines[-1] == "Noticias do dia.",
      "text: name, ▶ now + minutes left, » next, description %r" % lines)
check(plugin.mini_guide_text("SIC", None).endswith("Loading..."), "while looking up: Loading...")
check(plugin.mini_guide_text("SIC", ("no_match", [])).endswith("No programme information"), "nothing found")
real_peek = vu.peek_epg_guide
vu.peek_epg_guide = lambda cc: g if cc == "pt" else None
g.resolved[vu._guide_channel_name("SIC")] = "SIC.pt"
check(vu.peek_schedule("SIC", "pt") is not None and vu.peek_schedule("SIC", "es") is None,
      "peek_schedule(): from memory, None when a download would be needed")
vu.peek_epg_guide = real_peek

# ---------------------------------------------------------------- 4
print("4. The player's keys, numbers and bar")
ps = plugin.Playstream2.__new__(plugin.Playstream2)
ps.widgets = {}
plugin.Playstream2.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
plugin.Playstream2.__getitem__ = lambda self, k: self.widgets[k]
ps.session = Session()
ps._closed = False
ps.list = [[("Ch%d" % i, "http://h/vavoo?channel=c%d" % i)] for i in range(1, 176)]
ps.itemscount = 175
ps.currentindex = 6
ps.name, ps.url = ps.list[6][0]
ps._typed = 0
ps._previous_index = None
ps._digit_timer = FakeTimer()
zaps = []
ps.zap_to = lambda i: zaps.append(i)
ps._show_bar_now = lambda: None
ps._fill_bar = lambda: None
ps.key_digit(1)
check(ps._typed == 1 and ps._digit_timer.running == 1500, "1: typed, waits 1.5 s for more")
ps.key_digit(2)
check(ps._typed == 12 and zaps == [] and ps._digit_timer.running == 1500, "12: still could become 120-129, waits")
ps.key_digit(5)
check(zaps == [124] and ps._typed == 0, "125: no larger number possible (175 channels) - goes at once")
ps.key_digit(9)
ps._commit_digits()
check(zaps[-1] == 8, "9 then the wait ends: channel 9")
ps.key_digit(0)
check(ps._typed == 0, "0 first: recall, not a number")
ps._typed = 999
ps._commit_digits()
check(zaps[-1] == 8 and ps._typed == 0, "a number with no channel: nothing happens")
del ps.zap_to

# keys map
real_am = plugin.ActionMap


class AM(object):
    def __init__(self, contexts, actions, prio=0):
        self.contexts, self.actions = contexts, actions


src = e2env.plugin_source()
block = e2env.source_of("Playstream2").split("class Playstream2(")[1].split("self.__event_tracker")[0]
for key, method in (('"info": self.open_guide', "INFO: the guide (as in the lists)"),
                    ('"epg": self.open_guide', "EPG: the guide (no more IMDb on EPG)"),
                    ('"red": self.back', "RED back"),
                    ('"green": self.toggle_favourite', "GREEN favourite"),
                    ('"yellow": self.chooseStreamSource', "YELLOW: Source, as before"),
                    ('"blue": self.list_key', "BLUE: the channel list"),
                    ('"channelUp": self.nextitem', "CH+ / UP zap"),
                    ('"down": self.previousitem', "CH- / DOWN zap"),
                    ('"0": lambda: self.key_digit(0)', "digits"),
                    ("'NumberActions'", "number keys reach the player")):
    check(key in block, "player key: " + method)
check("def mainMenu(self):" in src and "self.open_options()" in src, "MENU opens the player's options (not Enigma2's menu)")

# the bar
ps = plugin.Playstream2.__new__(plugin.Playstream2)
ps.widgets = {}
ps.session = Session()
ps._closed = False
ps._bar_themed = True
for w in plugin.PLAYER_BAR_LABELS:
    ps.widgets[w] = FakeLabel()
for w in ("logo", "info_box", "progress_track", "progress"):
    ps.widgets[w] = FakeLabel()
ps.list = [[("SIC", URL_SIC)], [("RTP 1", URL_RTP)]]
ps.itemscount = 2
ps.currentindex = 0
ps.name, ps.url = "SIC", URL_SIC
ps.country_code, ps.country_name = "pt", "Portugal"
ps.current_logo_url = None
ps._typed = 0
ps._bar_epg_for = None
ps._set_logo = lambda: None
vu.peek_now_next = lambda name, cc: ("ok", (T - 600, T + 1800, "Jornal da Noite", ""), (T + 1800, T + 3600, "Linha Aberta", ""))
ps._fill_bar()
W = ps.widgets
check(W["number"].text == "1/2" and W["name"].text == "SIC", "number and name: '1/2', 'SIC'")
check(W["now"].text == u"▶ 20:40  Jornal da Noite" and W["next"].text == u"» 21:20  Linha Aberta",
      "programme lines the app's way %r" % W["now"].text)
check(W["progress"].value == 25 and W["left"].text == "+30 min" and W["progress"].visible,
      "progress 25% and '+30 min'")
check(W["key_red"].text == "Back" and W["key_green"].text == u"☆ Fav" and W["key_yellow"].text == "Source"
      and W["key_blue"].text == "List",
      "colour keys: Back / ☆ Fav / Source / List (the keys' own jobs)")
check([W[k].text for k in ("key_list", "key_options")] == ["EPG Guide", "MENU Options"]
      and "key_audio" not in W and "key_recall" not in W,
      "small keys: EPG Guide, MENU Options - no AUDIO / 0 Recall %r" % [W[k].text for k in ("key_list",
                                                                                           "key_options")])
check(W["status"].text == "Source: SIC HD .s", "status: the source in use of a multi-source channel %r" % W["status"].text)
ps._typed = 2
ps._fill_bar()
check(W["number"].text == "2-" and W["name"].text == u"→ RTP 1", "typing a number: '2-' and '→ RTP 1'")
ps._typed = 0
vu.peek_now_next = lambda name, cc: ("no_match", None, None)
ps._fill_bar()
check(W["now"].text == "Portugal" and not W["progress"].visible and not W["progress_track"].visible,
      "no programme: the country, no empty progress bar")
plugin.vUtils.toggle_favourite("SIC", URL_SIC, country_code="pt")
ps._fill_bar()
check(W["key_green"].text == u"★ Fav", "favourite: ★ Fav")

# sleep timer
st = plugin._SleepTimer()
plugin.time = types.SimpleNamespace(time=lambda: 1000.0, localtime=real_time.localtime, strftime=real_time.strftime)
st.set(Session(), 30)
check(st.minutes_left() == 30 and st.timer.running == 15000, "sleep 30 min: counting")
plugin.time = types.SimpleNamespace(time=lambda: 1000.0 + 29 * 60 + 10, localtime=real_time.localtime, strftime=real_time.strftime)
del notes[:]
st._tick()
check(st.warned and notes and "1 minute" in notes[-1], "a minute before: a message")
st.set(Session(), 0)
check(st.minutes_left() is None and st.timer.running is None, "off")

# options
ps.chooseStreamSource = lambda: None
menus = []
plugin.open_action_menu = lambda session, title, entries, cb, **kw: menus.append((title, entries, cb, kw))
ps._current_group_channel_id = lambda: "grp:portugal:sic"
ps.open_options()
keys = [k for _l, k in menus[-1][1]]
check(menus[-1][3].get("layout") == "player_menu", "options in the left panel, as the app shows them")
check(keys == ["fav", "audio", "subtitles", "source", "aspect", "sleep", "record", "info", "guide", "imdb"],
      "options: favourite, audio, subtitles, source, aspect, sleep, stream info, guide, IMDb %r" % keys)
info = ps.stream_info_text()
check("Source: SIC HD .s" in info and "127.0.0.1:4323" in info, "stream info: source and proxy")

# ---------------------------------------------------------------- 5
print("5. Skins and lists")
for theme in vt.MODERN_THEMES:
    for width in (1280, 1920, 2560):
        ET.fromstring(vt.player_bar(theme, True, width))
        ET.fromstring(vt.player_list(theme, False, width))
classic = vt.player_list_classic(1920)
root = ET.fromstring(classic)
names = set(el.get("name") for el in root if el.get("name"))
check(names == {"menulist", "guide"} and "pixmap" not in classic, "Classic player list: same widgets, no pictures")
check(all(int(el.get("position").split(",")[0]) + int(el.get("size").split(",")[0]) <= 1920
          for el in root), "Classic player list inside the screen")
labels = set(plugin.PLAYER_BAR_LABELS) | {"logo", "info_box", "progress_track", "progress"}
bar_names = set(el.get("name") for el in ET.fromstring(vt.player_bar("prism", True, 1920)) if el.get("name"))
check(bar_names == labels, "the player creates exactly the bar's widgets %r" % sorted(bar_names ^ labels))
check("MoviePlayer" in e2env.source_of("Playstream2").split("class Playstream2(")[1].split("def showIMDB")[0], "Classic keeps the MoviePlayer bar")

# ---------------------------------------------------------------- 6
print("6. Direct keys: the bar only shows captions (no LEFT / RIGHT walking)")
pb = plugin.Playstream2.__new__(plugin.Playstream2)
pb.widgets = {}
pb.session = Session()
pb._closed = False
pb._bar_themed = True
pb._typed = 0
pb.shown = False
pb._shift_state = None
pb.seekstate = None
pb.SEEK_STATE_PAUSE = ("pause",)
done = []
for name in ("open_channel_list", "shift_seek", "unPauseService"):
    setattr(pb, name, (lambda n: (lambda *a: done.append((n,) + a)))(name))
pb.doHide = lambda: setattr(pb, "shown", False)


def toggle(self_=None):
    pb.shown = not pb.shown


real_ok = plugin.TvInfoBarShowHide.OkPressed
real_hide = plugin.TvInfoBarShowHide.hide_help_overlay
plugin.TvInfoBarShowHide.OkPressed = lambda self: toggle()
plugin.TvInfoBarShowHide.hide_help_overlay = lambda self: None
members = vars(plugin.Playstream2)
check("PLAYER_BAR_BUTTONS" not in vars(plugin) and "bar_left" not in members and
      "_bar_press" not in members and "toggle_bar" not in members, "the bar-button walking is gone")
pb.OkPressed()
check(pb.shown and not done, "OK: shows the bar")
pb.OkPressed()
check(not pb.shown and not done, "OK again: hides it (no channel list on a second OK)")
pb.key_left()
pb.key_right()
check(done == [], "LEFT / RIGHT live: nothing")
pb._shift_state = "behind"
pb.key_left()
pb.key_right()
check(done == [("shift_seek", -10), ("shift_seek", 10)], "behind live: 10 s back / on")
pb._shift_state = None
pb.shown = True
pb.list_key()
check(done[-1] == ("open_channel_list",) and not pb.shown, "BLUE: the bar goes, the channel list opens")
pb.seekstate = pb.SEEK_STATE_PAUSE
pb.OkPressed()
check(done[-1] == ("unPauseService",), "paused: OK plays on")
pb.seekstate = None
pb._typed = 4
pb.zap_to = lambda i: done.append(("zap", i))
pb._digit_timer = FakeTimer()
pb.list = [[("c%d" % i, "u%d" % i)] for i in range(10)]
pb.itemscount = 10
pb.currentindex = 0
pb._fill_bar = lambda: None
pb.OkPressed()
check(done[-1] == ("zap", 3), "a number being typed: OK still goes to that channel first")
plugin.TvInfoBarShowHide.OkPressed = real_ok
plugin.TvInfoBarShowHide.hide_help_overlay = real_hide

print("7. Classic's top line: the same keys")
plugin.get_proxy_status = lambda: {"listening": True, "token_required": False, "addon_sig_age": 99999}
line = plugin.classic_help_line(plugin.classic_proxy_problem())
check(line == u"OK bar · CH± zap · GREEN fav · YELLOW source · BLUE list · EPG guide · MENU options · HELP keys",
      "the keys, nothing else while the proxy is fine: %r" % line)
check("YELLOW=Source" not in line and "INFO=IMDb" not in line and "Lululla" not in line, "the old line is gone")
plugin.get_proxy_status = lambda: {"token_required": True, "addon_sig_age": 500}
check(plugin.classic_help_line(plugin.classic_proxy_problem()).endswith(u"|  ✗ Proxy Expired"),
      "the Vavoo catalog with an old token: said")
plugin.get_proxy_status = lambda: {"listening": False, "booting": False}
check(plugin.classic_help_line(plugin.classic_proxy_problem()).endswith(u"✗ Proxy Offline"), "proxy down: said")
plugin.get_proxy_status = lambda: {"listening": False, "booting": True}
check(plugin.classic_help_line(plugin.classic_proxy_problem()).endswith(u"Loading channels..."),
      "proxy starting: 'Loading channels...', not 'Offline'")
check(len(plugin.classic_help_line()) <= 100, "fits one line (%d characters)" % len(plugin.classic_help_line()))
src = e2env.plugin_source()
check('"left": self.key_left' in src and '"right": self.key_right' in src, "LEFT / RIGHT reach the player")

plugin.threading.Thread = real_thread
print("\n%d checks, %d failed" % (CHECKS, FAILS))
e2env.exit_now(1 if FAILS else 0)
