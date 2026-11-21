# -*- coding: utf-8 -*-
"""Shared set-up for the screen tests: the tests' Enigma2 (e2env.py),
fake widgets, the real plugin imported, a check(). `plugin` is
e2env's view of the plugin's screen modules."""
from __future__ import print_function
import shutil
import sys

import e2env                                    # noqa: E402
from e2env import (                             # noqa: E402,F401
    HERE, REPO, EXTENSIONS, PLUGIN_DIR, DATA, store, patch, module_of,
    source_of, plugin_source, ui_modules)
import vavoo.vavoo_theme as vt                  # noqa: E402


# ---- fake widgets, put into Enigma2's (faked) modules before the plugin
# is imported, so every plugin module gets them whatever it imports
class FakeLabel(object):
    def __init__(self, text=""):
        self.text = text
        self.visible = True

    def setText(self, text):
        self.text = text

    def getText(self):
        return self.text

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False


class FakeActionMap(object):
    def __init__(self, contexts, actions, prio=0):
        self.contexts, self.actions = contexts, actions


class _TimerSignal(object):
    """eTimer.timeout (DreamOS): connect() adds to the callbacks."""
    def __init__(self, timer):
        self.timer = timer

    def connect(self, fn):
        self.timer.callback.append(fn)
        return fn


class FakeTimer(object):
    def __init__(self):
        self.callback = []

    def start(self, *a):
        pass

    def stop(self):
        pass

    def isActive(self):
        return False

    @property
    def timeout(self):
        return _TimerSignal(self)


class Entry(object):
    """A list row's entry, keeping what it was given."""
    def __init__(self, **k):
        self.__dict__.update(k)


import Components.Label as _label               # noqa: E402
import Components.ActionMap as _actionmap       # noqa: E402
import Components.MultiContent as _multicontent  # noqa: E402
import enigma as _enigma                        # noqa: E402
_label.Label = FakeLabel
_actionmap.ActionMap = FakeActionMap
_enigma.eTimer = FakeTimer
_multicontent.MultiContentEntryText = Entry
_multicontent.MultiContentEntryPixmapAlphaTest = Entry
_multicontent.MultiContentEntryPixmapAlphaBlend = Entry

plugin = e2env.load_plugin()
plugin.vUtils.RECENT_FILE = store.recent_file()
# No real proxy from the screens: opening MainVavoo / the settings would
# start one (a server and a catalog download in the test process).
# The proxy's own tests start it themselves (test_proxy_start.py).
plugin.run_proxy_in_background = lambda *a, **k: True
plugin.restart_proxy_in_background = lambda *a, **k: True
import vavoo.bouquet_manager as _bm             # noqa: E402
for _name in ("run_proxy_in_background", "restart_proxy_in_background"):
    if hasattr(_bm, _name):
        setattr(_bm, _name, lambda *a, **k: True)

STATE = {"fails": 0, "checks": 0}


def check(cond, what):
    STATE["checks"] += 1
    if not cond:
        STATE["fails"] += 1
        print("  FAIL: " + what)
    else:
        print("  ok:   " + what)


def finish():
    shutil.rmtree(DATA, ignore_errors=True)
    print("\n%d checks, %d failed" % (STATE["checks"], STATE["fails"]))
    e2env.exit_now(1 if STATE["fails"] else 0)


class V(object):
    """A setting (Components.config) with a fixed value."""
    def __init__(self, value):
        self.value = value

    def save(self):
        pass

    def cancel(self):
        pass

    def isChanged(self):
        return False

    def getValue(self):
        return self.value


class FakeList(object):
    def __init__(self, *a, **k):
        self.rows = []
        self.index = 0
        self.onSelectionChanged = []
        self.l = self
        self.item_height = 50

    def setList(self, rows):
        self.rows = rows
        if self.index >= len(rows):
            self.index = max(0, len(rows) - 1)

    def getCurrent(self):
        return self.rows[self.index] if self.rows else None

    def getSelectedIndex(self):
        return self.index

    def getCurrentSelection(self):
        return self.getCurrent()

    def moveToIndex(self, i):
        self.index = i
        for fn in self.onSelectionChanged:
            fn()

    def pageUp(self):
        self.moveToIndex(max(0, self.index - 5))

    def pageDown(self):
        self.moveToIndex(min(len(self.rows) - 1, self.index + 5))


class Session(object):
    def __init__(self):
        self.opened = []

    def open(self, cls, *a, **k):
        self.opened.append((cls, a, k, None))

    def openWithCallback(self, cb, cls, *a, **k):
        self.opened.append((cls, a, k, cb))


plugin.Label = FakeLabel
plugin.m2list = FakeList
plugin.ActionMap = FakeActionMap
plugin.eTimer = FakeTimer
plugin._ = lambda s: s
NOTES = []
plugin.quick_notify = lambda msg, sec=3: NOTES.append(msg)
plugin.NOTIFICATION_AVAILABLE = True
MENUS = []
MENU_CANCELS = []        # on_cancel of each menu in MENUS (or None)


def _fake_menu(session, title, entries, on_choice, layout="menu", on_cancel=None):
    MENUS.append((title, entries, on_choice))
    MENU_CANCELS.append(on_cancel)


plugin.open_action_menu = _fake_menu
plugin.MultiContentEntryText = Entry
plugin.MultiContentEntryPixmapAlphaTest = Entry
plugin.MultiContentEntryPixmapAlphaBlend = Entry
plugin.scaled_icon = lambda path, w, h: path
plugin.Screen.__init__ = lambda self, session: None
plugin.init_notification_system = lambda session: None
plugin.cfg.theme = V("prism")
plugin.cfg.text_size = V("large")
plugin.cfg.clock_format = V("24")
plugin.cfg.show_counts = V(True)
plugin.cfg.back = V("oktus")
plugin.cfg.preview_window = V(True)
plugin.cfg.list_epg = V(False)
plugin._theme_skin_cache.clear()


def make(cls, *args, **kw):
    """A screen built by its real __init__, widgets in a dict."""
    cls.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
    cls.__getitem__ = lambda self, k: self.widgets[k]
    obj = cls.__new__(cls)
    obj.widgets = {}
    obj.onClose = []
    obj.onExecBegin = []
    obj.onLayoutFinish = []
    obj.closed_with = []
    obj.close = lambda *a: obj.closed_with.append(a)
    obj.execing = True
    cls.__init__(obj, *args, **kw)
    check_layout_entries(obj)
    return obj


def check_layout_entries(screen):
    """Enigma2's rule (Screen.createGUIScreen on OpenATV / OpenPLi): an
    onLayoutFinish entry that is not a bound method is exec()'d - a
    lambda or function there crashes the box when the screen opens."""
    import types
    for entry in getattr(screen, "onLayoutFinish", []):
        if not isinstance(entry, types.MethodType):
            exec(entry, {}, {})


def run_layout(screen):
    """What Enigma2 does once the skin is applied: each onLayoutFinish
    entry, by its rule."""
    import types
    for entry in list(screen.onLayoutFinish):
        if not isinstance(entry, types.MethodType):
            exec(entry, {}, {})
        else:
            entry()


def texts(screen, name="menulist"):
    out = []
    for row in screen.widgets[name].rows:
        last = [e for e in row[1:] if hasattr(e, "text") or (isinstance(e, tuple) and False)]
        out.append(row_text(row))
    return out


def row_text(row):
    """The text a show_list() row shows (its last MultiContentEntryText)."""
    for entry in reversed(row[1:]):
        text = getattr(entry, "text", None)
        if text is not None:
            return text
    return None
