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
# Saving the settings copies the chosen background onto the plugin's own
# skin/images/default.png - never from a test (it is in the repository).
REAL_ADD_SKIN_BACK = plugin.add_skin_back
SKIN_BACKS = []
plugin.add_skin_back = lambda bakk: SKIN_BACKS.append(bakk)
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


def _fake_menu(
        session,
        title,
        entries,
        on_choice,
        layout="menu",
        on_cancel=None):
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
    check_dict_names(obj)
    return obj


# Enigma2's Screen is a dict: its doClose() / deleteGUIScreen() call
# self.items(), skin code self.keys() - an attribute of the screen with
# one of these names hides the dict's method ("'list' object is not
# callable" as the screen closes - the Recordings crash on OpenATV 8.1).
DICT_NAMES = (
    "clear",
    "copy",
    "fromkeys",
    "get",
    "has_key",
    "items",
    "iteritems",
    "iterkeys",
    "itervalues",
    "keys",
    "pop",
    "popitem",
    "setdefault",
    "update",
    "values",
    "viewitems",
    "viewkeys",
    "viewvalues")


def dict_shadows(screen):
    """The screen's own attributes that hide a dict method."""
    return sorted(name for name in vars(screen) if name in DICT_NAMES)


def check_dict_names(screen):
    hidden = dict_shadows(screen)
    if hidden:
        raise TypeError(
            "%s: attribute(s) %s hide the dict methods Enigma2's "
            "Screen.doClose() calls ('list' object is not callable)" %
            (type(screen).__name__, ", ".join(hidden)))


def _gone(self, name):
    raise AttributeError(
        "'%s' object has no attribute '%s'" %
        (type(self).__name__, name))


_CLOSED_CLASSES = {}


def enigma2_close(screen):
    """What Enigma2's Screen.doClose() does: the onClose entries, then
    deleteGUIScreen() (self.items() - fails as on the box when an
    attribute hides it), then every component and attribute gone
    (`self.__dict__.clear()`). From then on a missing attribute raises,
    as on the box - not the fake Enigma2's made-up value."""
    for entry in list(getattr(screen, "onClose", [])):
        entry()
    check_dict_names(screen)
    cls = type(screen)
    closed = _CLOSED_CLASSES.get(cls)
    if closed is None:
        closed = _CLOSED_CLASSES[cls] = type(
            cls.__name__, (cls,), {"__getattr__": _gone})
    screen.__dict__.clear()
    screen.__class__ = closed


class _Delayed(object):
    def cancel(self):
        pass

    def active(self):
        return False


class _HeldThread(object):
    """A screen module's threading.Thread: kept, not started."""

    def __init__(
            self,
            pending,
            target=None,
            args=(),
            kwargs=None,
            name=None,
            **_k):
        self._pending = pending
        self.target, self.args, self.kwargs = target, tuple(
            args), dict(kwargs or {})
        self.daemon = False
        self.name = name

    def setDaemon(self, flag):
        self.daemon = flag

    def start(self):
        self._pending.threads.append(self)

    def is_alive(self):
        return False

    isAlive = is_alive

    def join(self, *a):
        pass


class _ThreadingShim(object):
    def __init__(self, pending):
        self._pending = pending

    def Thread(self, *a, **k):
        if a:
            k.setdefault("target", a[1] if len(a) > 1 else None)
        return _HeldThread(self._pending, **k)

    def __getattr__(self, name):
        import threading
        return getattr(threading, name)


class Pending(object):
    """What a screen leaves to run later - reactor.callFromThread() /
    callLater() and the threads its modules start - kept while
    `hold()` is on, run by `run()` (the closed-screen checks: on the box
    these come after the screen has closed)."""

    def __init__(self):
        self.calls = []
        self.threads = []
        self._saved = None

    # the reactor's calls the plugin uses
    def callFromThread(self, fn, *a, **k):
        self.calls.append((fn, a, k))

    def callLater(self, _delay, fn, *a, **k):
        self.calls.append((fn, a, k))
        return _Delayed()

    def hold(self):
        import threading
        self._saved = (plugin.reactor, threading)
        patch("reactor", self)
        patch("threading", _ThreadingShim(self))
        return self

    def release(self):
        if self._saved is not None:
            patch("reactor", self._saved[0])
            patch("threading", self._saved[1])
            self._saved = None

    def clear(self):
        del self.calls[:]
        del self.threads[:]

    def run(self, timeout=10, rounds=5):
        """Every call and thread kept (and what they leave in turn):
        the failures, as text."""
        import threading
        import traceback
        failures = []
        for _round in range(rounds):
            calls, threads = list(self.calls), list(self.threads)
            self.clear()
            if not calls and not threads:
                break
            for fn, a, k in calls:
                try:
                    fn(*a, **k)
                except Exception as e:
                    failures.append("call %s: %s: %s\n%s" % (
                        getattr(fn, "__name__", fn), e.__class__.__name__, e,
                        traceback.format_exc(limit=5)))
            for held in threads:
                box = []

                def body(held=held, box=box):
                    try:
                        held.target(*held.args, **held.kwargs)
                    except Exception as e:
                        box.append(
                            "thread %s: %s: %s\n%s" %
                            (getattr(
                                held.target,
                                "__name__",
                                held.target),
                                e.__class__.__name__,
                                e,
                                traceback.format_exc(
                                limit=5)))
                worker = threading.Thread(target=body)
                worker.daemon = True
                worker.start()
                worker.join(timeout)
                if worker.is_alive():
                    failures.append("thread %s: still running after %ds" % (
                        getattr(held.target, "__name__", held.target), timeout))
                failures.extend(box)
        return failures


def own_close(screen):
    """The screen's own way out (MainVavoo.closex(), a close() of its
    own), as its EXIT would call it - before Enigma2's doClose()."""
    for klass in type(screen).__mro__:
        if klass.__module__.startswith(("vavoo", "Plugins")):
            for name in ("closex", "close"):
                if name in vars(klass):
                    getattr(klass, name)(screen)
                    return name
    return None


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
        last = [e for e in row[1:] if hasattr(
            e, "text") or (isinstance(e, tuple) and False)]
        out.append(row_text(row))
    return out


def row_text(row):
    """The text a show_list() row shows (its last MultiContentEntryText)."""
    for entry in reversed(row[1:]):
        text = getattr(entry, "text", None)
        if text is not None:
            return text
    return None
