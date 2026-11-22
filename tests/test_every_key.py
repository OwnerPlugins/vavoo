# -*- coding: utf-8 -*-
"""The audit's sweep: every screen, in Classic and a theme, with its lists
filled; every action of every ActionMap it creates, every entry of every
menu that opens, and "cancel" (None) on every dialog that opens - each
from a fresh screen. Any exception is a failure. On Python 2 a widget
given unicode (Enigma2 there takes bytes only) is one too."""
from __future__ import print_function
import json
import os
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, V, MENUS, run_layout   # noqa: E402
plugin = harness.plugin
store = harness.store
vt = harness.vt
PY2 = sys.version_info[0] == 2
TMP = tempfile.mkdtemp(prefix="vavoo_sweep_")
import vavoo.bouquet_manager as bm             # noqa: E402
for module in (plugin.vUtils, bm):
    if hasattr(module, "ENIGMA_PATH"):
        module.ENIGMA_PATH = TMP
plugin.vUtils.CACHE_FILE = os.path.join(TMP, "cache.json")
plugin.vUtils.UNMATCHED_FILE = os.path.join(TMP, "unmatched.json")
plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True
plugin.is_proxy_booting = lambda *a, **k: False
# (no real proxy: "Reload List" would start one, stuck on the blocked
# network - every request to it after that waits for its timeout)
for module in (plugin, bm, plugin.vavoo_proxy):
    for name in (
        "restart_proxy_in_background",
        "run_proxy_in_background",
            "start_proxy"):
        if hasattr(module, name):
            setattr(module, name, lambda *a, **k: True)
plugin.cfg.subcategories = V(False)
plugin.vUtils.RECENT_FILE = store.recent_file()
# MENU → Factory reset answered Yes: recorded, its on_done run - the real
# reset would empty the data the next passes use (test_factory_reset.py)
RESETS = []


def _fake_reset(on_done=None):
    RESETS.append(on_done)
    if on_done:
        on_done()


plugin.factory_reset = _fake_reset


class _Signal(object):
    def __init__(self, timer):
        self.timer = timer

    def connect(self, fn):
        self.timer.callback.append(fn)
        return fn


harness.FakeTimer.timeout = property(lambda self: _Signal(self))


class FakeListbox(object):
    moveUp, moveDown, pageUp, pageDown = 0, 1, 2, 3

    def moveSelection(self, how):
        pass


class FakeConfigList(object):
    def __init__(self, entries):
        self.list = entries
        self.l = self
        self.instance = FakeListbox()     # (Enigma2 makes it at layout)
        self.onSelectionChanged = []

    def setList(self, entries):
        self.list = entries

    def getCurrent(self):
        return self.list[0] if self.list else None

    def getCurrentIndex(self):
        return 0

    def isChanged(self):
        return False


plugin.ConfigListScreen.__init__ = lambda self, entries, session=None, on_change=None: \
    self.__setitem__("config", FakeConfigList(entries))

# ---- Python 2: widgets take bytes only
BAD_TEXT = []
if PY2:
    real_set = harness.FakeLabel.setText

    def checked_set(self, text):
        if isinstance(text, unicode):                    # noqa: F821
            BAD_TEXT.append(
                ("setText", text, "".join(
                    traceback.format_stack(
                        limit=4)[
                        :-1])))
        real_set(self, text)
    harness.FakeLabel.setText = checked_set
    real_entry = harness.Entry.__init__

    def checked_entry(self, **k):
        if isinstance(k.get("text"), unicode):           # noqa: F821
            BAD_TEXT.append(("MultiContentEntryText", k["text"],
                             "".join(traceback.format_stack(limit=4)[:-1])))
        real_entry(self, **k)
    harness.Entry.__init__ = checked_entry


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
    s.current_dialog = None
    return s


URL1 = "http://127.0.0.1:4323/vavoo?channel=r1"
URL2 = "http://127.0.0.1:4323/vavoo?channel=c5"
CHANNELS = [{"name": u"RAI 1",
             "url": URL1,
             "logo": "",
             "epg_id": "Rai.1.it",
             "category": u"Generale"},
            {"name": u"Canale 5 Más",
             "url": URL2,
             "logo": "",
             "epg_id": "",
             "category": u"Generale"}]
GUIDE_CH = [dict(c, country_name="Italy", country_code="it") for c in CHANNELS]
store.add_favourite(u"RAI 1", URL1, "Italy", "it")
store.add_favourite(
    u"Télé Monte",
    "http://127.0.0.1:4323/vavoo?channel=tm",
    "France",
    "fr")
plugin.vUtils.add_recent(
    u"RAI 1",
    URL1,
    "Italy",
    "it") if hasattr(
        plugin.vUtils,
    "add_recent") else None
time.sleep(0.5)


def recording_data():
    return {
        "path": os.path.join(
            TMP,
            "x.ts"),
        "title": u"Show é",
        "name": u"RAI 1",
        "duration": 60,
        "start": 0,
        "country": "Italy"}


def fill_main(scr):
    scr._on_countries_response(json.dumps(["Italy", "France"]), None, {"Italy": 2, "France": 1},
                               favourite_count=2, recent=[{"name": u"RAI 1", "url": URL1}], reminders=1)


def fill_channels(scr):
    scr._preload_channel_picons = lambda: None
    scr._build_channel_list(CHANNELS)


def fill_favourites(scr):
    scr._build_list()


SCREENS = [
    ("MainVavoo", lambda s: make(plugin.MainVavoo, s), fill_main),
    ("channel list", lambda s: make(plugin.vavoo, s, "Italy", None), fill_channels),
    ("Favourites", lambda s: make(plugin.VavooFavourites, s), fill_favourites),
    ("Recently watched", lambda s: make(plugin.VavooFavourites, s, "recent"), fill_favourites),
    ("guide", lambda s: make(plugin.VavooGuide, s, GUIDE_CH, 0, "Italy"), None),
    ("guide over the player", lambda s: make(plugin.VavooGuide, s, GUIDE_CH, 0, "Italy", over_player=True,
                                             on_zap=lambda d: None), None),
    ("Recordings", lambda s: make(plugin.VavooRecordings, s), None),
    ("Choose countries", lambda s: make(plugin.VavooCountries, s, ["Albania", "Italy"]), None),
    ("Parental Control", lambda s: make(plugin.VavooParental, s, ["Italy", "Albania"]), None),
    ("PIN pad", lambda s: make(plugin.VavooPin, s, "Enter the PIN", 4, lambda pin: True), None),
    ("Search", lambda s: make(plugin.VavooSearch, s, None,
                              [u"RAI 1###" + URL1 + "###Italy", u"Canale 5 Más###" + URL2 + "###Italy"],
                              scope="all channels"), None),
    ("menu", lambda s: make(plugin.VavooMenu, s, "Options", [("Settings", "s"), ("About", "a")]), None),
    ("Settings", lambda s: make(plugin.vavoo_config, s), None),
    ("update popup", lambda s: make(plugin.UpdatePopup, s, "9.9", "changes"), None),
    ("log viewer", lambda s: make(plugin.VavooLogViewer, s, "Log", "/nonexistent.log"), None),
    ("player channel list", lambda s: make(plugin.VavooPlayerList, s, [("RAI 1", URL1), ("Canale 5", URL2)], 0,
                                           ["it", "it"], ["", ""], ["Italy", "Italy"]), None),
    ("player", lambda s: make(plugin.Playstream2, s, "RAI 1", URL1, 0, None,
                              [("RAI 1", URL1), ("Canale 5", URL2)], "it"), None),
    ("recording player", lambda s: make(plugin.VavooRecordingPlayer, s, recording_data()), None),
]


def actions_of(scr):
    out = []
    for name, widget in sorted(scr.widgets.items()):
        if isinstance(widget, harness.FakeActionMap):
            for action in sorted(widget.actions):
                out.append((name, action))
    return out


def fresh(build, fill):
    scr = build(session())
    run_layout(scr)
    if fill is not None:
        fill(scr)
    return scr


FAILS = []


def attempt(what, fn, *args):
    try:
        fn(*args)
        return True
    except Exception as e:
        FAILS.append(
            "%s: %s: %s\n%s" %
            (what,
             e.__class__.__name__,
             e,
             traceback.format_exc(
                 limit=6)))
        return False


def cancel_dialogs(what, scr, start):
    for cls, _a, _k, cb in list(scr.session.opened[start:]):
        if cb is None:
            continue
        name = getattr(cls, "__name__", str(cls))
        attempt("%s -> %s cancelled" % (what, name), cb, None)
        if "MessageBox" in name:
            # (each answer from where it was asked: the dialog again)
            for answer in (True, False):
                attempt(
                    "%s -> %s answered %r" %
                    (what, name, answer), cb, answer)
                count["answers"] += 1


count = {"actions": 0, "menus": 0, "dialogs": 0, "answers": 0}
PASSES = [(theme, filled) for theme in ("classic", "prism")
          for filled in (True, False)]
for theme, filled in PASSES:
    plugin.cfg.theme = V(theme)
    plugin._theme_skin_cache.clear()
    for title, build, fill in SCREENS:
        if not filled:
            if fill is None:
                continue          # (the same as the filled pass)
            fill = None
            title += " (empty)"
        if theme == "classic" and title in ("menu",):
            continue
        where = "%s %s" % (theme, title)
        probe = None
        if not attempt(where + " (open)", lambda: None) or True:
            try:
                probe = fresh(build, fill)
            except Exception as e:
                FAILS.append("%s: could not be built: %s\n%s" %
                             (where, e, traceback.format_exc(limit=6)))
                continue
        for widget, action in actions_of(probe):
            if action == "ignore":
                continue
            scr = fresh(build, fill)
            fn = scr.widgets[widget].actions[action]
            del MENUS[:]
            start = len(scr.session.opened)
            what = "%s [%s.%s]" % (where, widget, action)
            count["actions"] += 1
            ok = attempt(what, fn)
            if not ok:
                continue
            count["dialogs"] += len(scr.session.opened) - start
            cancel_dialogs(what, scr, start)
            menus = list(MENUS)
            for m_title, entries, on_choice in menus:
                for label, key in entries:
                    scr2 = fresh(build, fill)
                    del MENUS[:]
                    if not attempt(
                            what + " (again)",
                            scr2.widgets[widget].actions[action]) or not MENUS:
                        continue
                    _t, _e, choose = MENUS[-1]
                    start2 = len(scr2.session.opened)
                    count["menus"] += 1
                    if attempt(
                        "%s menu '%s' -> %r" %
                            (what, label, key), choose, key):
                        cancel_dialogs(
                            "%s menu '%s'" %
                            (what, label), scr2, start2)

print("== %d actions, %d menu entries, %d dialogs cancelled, %d confirmations answered (Python %d)"
      % (count["actions"], count["menus"], count["dialogs"], count["answers"], sys.version_info[0]))

# ---- closed as on the box: Enigma2's doClose() clears the screen's
# __dict__; what the screen left to come back later (reactor calls, its
# threads) then runs against a closed screen - and must touch nothing
pending = harness.Pending()
closed = 0
# (no network for what runs after the close)
real_get_url = plugin.getUrl


def _no_network(*a, **k):
    raise IOError("no network in the closed-screen pass")


plugin.getUrl = _no_network


def close_and_run(where, build, fill, action=None):
    """A fresh screen (its key `action` pressed first), closed as on the
    box, then what it left running: no exception."""
    pending.hold()
    pending.clear()
    try:
        try:
            scr = fresh(build, fill)
        except Exception as e:
            FAILS.append("%s: could not be built: %s\n%s" %
                         (where, e, traceback.format_exc(limit=6)))
            return False
        if action is not None:
            widget, name = action
            del MENUS[:]
            if not attempt(where, scr.widgets[widget].actions[name]):
                return False
        if not (
            attempt(
                where +
                " own close",
                harness.own_close,
                scr) and attempt(
                where +
                " Enigma2's doClose()",
                harness.enigma2_close,
                scr)):
            return False
        for failure in pending.run():
            FAILS.append("%s: after the close: %s" % (where, failure))
        return True
    finally:
        pending.release()


for theme in ("classic", "prism"):
    plugin.cfg.theme = V(theme)
    plugin._theme_skin_cache.clear()
    for title, build, fill in SCREENS:
        if theme == "classic" and title in ("menu",):
            continue
        where = "%s %s (closed)" % (theme, title)
        if not close_and_run(where, build, fill):
            continue
        closed += 1
        try:
            probe = fresh(build, fill)
        except Exception:
            continue
        for widget, action in actions_of(probe):
            if action != "ignore":
                if close_and_run("%s [%s.%s] (then closed)" % (
                        where[:-9], widget, action), build, fill, (widget, action)):
                    closed += 1
plugin.getUrl = real_get_url
print(
    "== %d screens closed as Enigma2 does (fresh, and after each key), then their pending work run" %
    closed)
seen = set()
for fail in FAILS:
    head = fail.splitlines()[0]
    key = head.split(": ", 1)[-1][:200]
    if key in seen:
        continue
    seen.add(key)
    print("-" * 70)
    print(fail)
check(
    not FAILS,
    "every key, menu entry and cancel: no exception (%d failures, %d distinct)" %
    (len(FAILS),
     len(seen)))
if PY2:
    for kind, text, stack in BAD_TEXT[:15]:
        print("-" * 70)
        print("unicode to %s: %r\n%s" % (kind, text, stack))
    check(
        not BAD_TEXT,
        "Python 2: widgets only got bytes (%d unicode)" %
        len(BAD_TEXT))
finish()
