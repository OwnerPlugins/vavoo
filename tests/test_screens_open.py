# -*- coding: utf-8 -*-
"""Every screen opens, in every theme, resolution and text size, by the
rules a real Enigma2 applies when it opens one:
- each <widget name="X"> of its skin is a component the screen created
  (else SkinError: "component with name X was not found" - a crash);
- each <widget source="X"> is session.* / global.* or the screen's own;
- its onLayoutFinish entries are bound methods (else exec() - a crash,
  the Recordings one) and run without an error."""
from __future__ import print_function
import os
import sys
import traceback
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, V, run_layout   # noqa: E402
plugin = harness.plugin
vt = harness.vt
store = harness.store
import vavoo.vavoo_record as vr                 # noqa: E402
import vavoo.notification_system as ns          # noqa: E402

PLUGIN_DIR = harness.PLUGIN_DIR


class _Signal(object):
    def __init__(self, timer):
        self.timer = timer

    def connect(self, fn):
        self.timer.callback.append(fn)
        return fn


# eTimer on DreamOS: timeout.connect() (the code picks it by the file
# /var/lib/dpkg/status, which this machine has)
harness.FakeTimer.timeout = property(lambda self: _Signal(self))


class FakeConfigList(object):
    def __init__(self, entries):
        self.list = entries
        self.l = self
        self.instance = None
        self.onSelectionChanged = []

    def setList(self, entries):
        self.list = entries

    def getCurrent(self):
        return self.list[0] if self.list else None

    def isChanged(self):
        return False


def _config_list_screen(self, entries, session=None, on_change=None):
    """ConfigListScreen.__init__: creates self["config"], as Enigma2's."""
    self["config"] = FakeConfigList(entries)


plugin.ConfigListScreen.__init__ = _config_list_screen
RESOLUTIONS = (("hd", 1280), ("fhd", 1920), ("wqhd", 2560))
THEMES = ("classic", "prism", "halo", "orbit")
SIZES = ("normal", "large")

plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True
plugin.cfg.subcategories = V(False)
CH = [{"name": "RAI 1",
       "url": "http://127.0.0.1:4323/vavoo?channel=r1",
       "country_name": "Italy",
       "country_code": "it",
       "epg_id": "Rai1.it",
       "logo": ""}]


class Nav(object):
    def getCurrentlyPlayingServiceReference(self):
        return None

    def getCurrentService(self):
        return None

    def stopService(self):
        pass

    def playService(self, sref):
        pass


def session():
    s = Session()
    s.nav = Nav()
    s.dialog_stack = []
    return s


def recording_data():
    return {"path": "/media/hdd/movie/x.ts", "title": "Show", "name": "RAI 1",
            "duration": 60, "start": 0, "country": "Italy"}


SCREENS = [
    ("MainVavoo", lambda s: make(plugin.MainVavoo, s)),
    ("channel list", lambda s: make(plugin.vavoo, s, "Italy", None)),
    ("Favourites", lambda s: make(plugin.VavooFavourites, s)),
    ("Recently watched", lambda s: make(plugin.VavooFavourites, s, "recent")),
    ("guide", lambda s: make(plugin.VavooGuide, s, CH, 0, "Italy")),
    ("guide over the player", lambda s: make(plugin.VavooGuide, s, CH, 0, "Italy", over_player=True,
                                             on_zap=lambda d: None)),
    ("Recordings", lambda s: make(plugin.VavooRecordings, s)),
    ("Choose countries", lambda s: make(plugin.VavooCountries, s, ["Albania", "Italy"])),
    ("first run countries", lambda s: make(plugin.VavooCountries, s, ["Albania", "Italy"], True)),
    ("Parental Control", lambda s: make(plugin.VavooParental, s, ["Italy", "Albania"])),
    ("PIN pad", lambda s: make(plugin.VavooPin, s, "Enter the PIN", 4, lambda pin: True)),
    ("Search", lambda s: make(plugin.VavooSearch, s, None, [], scope="all channels")),
    ("menu", lambda s: make(plugin.VavooMenu, s, "Options", [("Settings", "s")])),
    ("player menu", lambda s: make(plugin.VavooMenu, s, "Options", [("Audio", "a")], layout="player_menu")),
    ("Settings", lambda s: make(plugin.vavoo_config, s)),
    ("splash", lambda s: make(plugin.startVavoo, s)),
    ("update popup", lambda s: make(plugin.UpdatePopup, s, "9.9", "changes")),
    ("log viewer", lambda s: make(plugin.VavooLogViewer, s, "Log", "/nonexistent.log")),
    ("player channel list", lambda s: make(plugin.VavooPlayerList, s, [("RAI 1", CH[0]["url"])], 0,
                                           ["it"], [""], ["Italy"])),
    ("player", lambda s: make(plugin.Playstream2, s, "RAI 1", CH[0]["url"], 0, None,
                              [("RAI 1", CH[0]["url"])], "it")),
    ("recording player", lambda s: make(plugin.VavooRecordingPlayer, s, recording_data())),
    ("notification", lambda s: (plugin.set_notification_theme(),
                                make(ns.SimpleNotifyWidget, s))[1]),
    ("console", lambda s: make(plugin.Console, s, "Command", ["true"], allow_restart=False)),
]
# Classic: the players borrow the image's own MoviePlayer skin (nothing
# here to check them against); MENU is Enigma2's ChoiceBox there, so
# VavooMenu never opens in Classic.
NO_OWN_SKIN_CLASSIC = ("player", "recording player", "menu", "player menu")


def skin_widgets(text):
    # (cElementTree on Python 2, as Enigma2 there: it takes no unicode
    # with non-ASCII characters - the splash screen's crash)
    try:
        import xml.etree.cElementTree as CET
    except ImportError:
        CET = ET
    root = CET.fromstring(text)
    screens = [root] if root.tag == "screen" else root.findall(".//screen")
    names, sources = set(), set()
    for scr in screens:
        for w in scr.iter("widget"):
            if w.get("name"):
                names.add(w.get("name"))
            if w.get("source"):
                sources.add(w.get("source"))
    return names, sources


def try_open(title, build, classic):
    """(screen or None, problems)"""
    problems = []
    try:
        scr = build(session())
    except Exception as e:
        return None, ["could not be built: %s: %s\n%s" %
                      (e.__class__.__name__, e, traceback.format_exc(limit=4))]
    text = getattr(scr, "skin", None)
    if not text and not (classic and title in NO_OWN_SKIN_CLASSIC):
        problems.append("no skin of its own")
    if text:
        try:
            names, sources = skin_widgets(text)
        except Exception as e:
            return scr, ["skin is not valid XML: %s" % e]
        have = set(scr.widgets)
        missing = sorted(n for n in names if n not in have)
        if missing:
            problems.append(
                "skin names widgets the screen does not create: %s" %
                ", ".join(missing))
        bad = sorted(src for src in sources if not (src.startswith(
            "session.") or src.startswith("global.") or src.split(".")[0] in have))
        if bad:
            problems.append(
                "skin uses sources the screen does not have: %s" %
                ", ".join(bad))
    try:
        run_layout(scr)
    except Exception as e:
        problems.append("onLayoutFinish: %s: %s\n%s" %
                        (e.__class__.__name__, e, traceback.format_exc(limit=5)))
    return scr, problems


print("== the test itself finds what crashes a box")


class Broken(object):
    skin = '<screen name="Broken"><widget name="menulist"/><widget name="nope"/><widget source="Event"/></screen>'

    def __init__(self, session):
        self["menulist"] = object()
        self.onLayoutFinish.append(lambda: None)


_scr, _problems = try_open("broken", lambda s: make(Broken, s), False)
check(
    _scr is None and (
        "exec() arg 1 must be" in _problems[0] or "exec: arg 1 must be" in _problems[0]),
    "a lambda in onLayoutFinish: the box's error (%s)" %
    _problems[0].splitlines()[0][
        :80])
Broken.__init__ = lambda self, session: self.__setitem__("menulist", object())
_scr, _problems = try_open("broken", lambda s: make(Broken, s), False)
check(any("nope" in p for p in _problems) and any("Event" in p for p in _problems),
      "a widget / source the screen lacks: found (%s)" % "; ".join(_problems))

for dreamos, folder, width in [(d, f, w)
                               for d in (False, True) for f, w in RESOLUTIONS]:
    plugin.IS_DREAMOS = dreamos
    plugin.screen_width = width
    plugin.THEME_WIDTH = width
    plugin.skin_path = os.path.join(PLUGIN_DIR, "skin", folder)
    for theme in THEMES:
        for size in SIZES if theme != "classic" else ("normal",):
            plugin.cfg.theme = V(theme)
            plugin.cfg.text_size = V(size)
            plugin._theme_skin_cache.clear()
            what = "%s%s %s%s" % ("DreamOS " if dreamos else "", folder, theme,
                                  "" if theme == "classic" else " " + size)
            print("==", what)
            if theme != "classic":
                check(
                    plugin.theme_active(),
                    "%s: the theme is in use (all its files there)" %
                    what)
            for title, build in SCREENS:
                scr, problems = try_open(title, build, theme == "classic")
                check(
                    not problems,
                    "%s: %s opens%s" %
                    (what,
                     title,
                     "" if not problems else "\n      " +
                     "\n      ".join(problems)))
finish()
