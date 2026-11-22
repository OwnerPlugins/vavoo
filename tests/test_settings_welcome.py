# -*- coding: utf-8 -*-
"""Settings in two steps (the 14 rows people change, then "All
settings") without losing a change made in the hidden ones, and the
welcome of a new install (the look, the countries, a PIN) - never on an
install in use."""
from __future__ import print_function
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, MENUS, MENU_CANCELS  # noqa: E402
plugin = harness.plugin
store = harness.store
cfg = plugin.cfg


class El(object):
    """A setting: value, saved value, save / cancel / isChanged."""

    def __init__(self, value):
        self.value = self.saved = value

    def isChanged(self):
        return self.value != self.saved

    def save(self):
        self.saved = self.value

    def cancel(self):
        self.value = self.saved


class FakeConfigList(object):
    def __init__(self, entries):
        self.list = entries
        self.l = self
        self.index = 0

    def setList(self, entries):
        self.list = entries

    def getCurrent(self):
        return self.list[self.index] if self.list else None

    def setCurrentIndex(self, i):
        self.index = i

    def isChanged(self):
        return False


plugin.ConfigListScreen.__init__ = lambda self, entries, session=None, on_change=None: \
    self.__setitem__("config", FakeConfigList(entries))
plugin.getConfigListEntry = lambda *a: a
plugin.cfg.theme = harness.V("prism")
cfg.show_counts = El(True)

print("== Settings: the basic rows first")
scr = make(plugin.vavoo_config, Session())
rows = scr["config"].list
labels = [plugin.to_text(r[0]) for r in rows]
check(len(rows) == 15, "14 rows + the last one (%d)" % len(rows))
check(rows[-1][1] is cfg.more_settings and u"All settings (" in labels[-1]
      and u"more)" in labels[-1], "the last row: %r" % labels[-1])
basic = plugin.basic_rows()
check(all(any(r[1] is b for b in basic)
      for r in rows[:-1]), "only basic rows above it")
check(
    labels[0] == "Theme" and "About" in labels and "Pause Live TV" in labels and "Choose countries" in labels,
    "Theme first; Pause Live TV, Choose countries, About in it")
check(
    "Catalog/Stream Source" not in labels and "Debug logging" not in labels,
    "the advanced ones hidden")
hidden = int(labels[-1].split("(")[1].split()[0])
scr["config"].index = len(rows) - 1
scr.gnm3u()
rows = scr["config"].list
check(
    scr.show_all and len(rows) == 14 +
    hidden +
    1,
    "OK on it: all %d rows" %
    len(rows))
check(scr["config"].index == 14, "...the first one that was hidden selected")
check(u"Fewer settings" in plugin.to_text(
    rows[-1][0]), "the last row now: 'Fewer settings'")

print("== a change in a hidden row is kept")
cfg.show_counts.value = False
scr["config"].index = len(rows) - 1
scr.gnm3u()
check(
    not scr.show_all and not any(
        r[1] is cfg.show_counts for r in scr["config"].list),
    "back to the basic rows: Show Counts hidden")
check(scr._settings_changed(), "the change still counts (GREEN says Save)")
scr.save()
check(cfg.show_counts.saved is False, "GREEN: saved although hidden")
cfg.show_counts.value = True
scr2 = make(plugin.vavoo_config, Session())
scr2.show_all = True
scr2.createSetup()
scr2.show_all = False
scr2.createSetup()
scr2.extnok(True)
check(cfg.show_counts.value is False,
      "leaving without saving: a hidden change is undone too")
check(any("all settings" in plugin.to_text(t).lower()
      for _k, t in scr.help_rows()), "HELP says it")

print("== the welcome: only a new install")
# (the faked Enigma2 config gives the old parental-PIN setting a value,
# which the import moved into a PIN: none here, as on a new box)
store.set_pin("")
cfg.welcome_done = El(False)
cfg.countries_asked = El(False)
store.clear_favourites()
check(plugin.welcome_needed() is True, "nothing on the box: welcome")
store.add_favourite(
    u"RAI 1",
    "http://127.0.0.1:4323/vavoo?channel=r1",
    "Italy",
    "it")
check(plugin.welcome_needed() is False and cfg.welcome_done.value is True,
      "favourites on the box: no welcome, marked as done")
store.clear_favourites()
cfg.welcome_done = El(False)
cfg.countries_asked = El(True)
check(plugin.welcome_needed() is False, "countries chosen before: no welcome")

print("== the welcome's steps")
cfg.countries_asked = El(False)
cfg.welcome_done = El(False)
cfg.theme = El("prism")
plugin.proxy_countries = lambda: ["Italy", "France"]
done = []
s = Session()
del MENUS[:]
del MENU_CANCELS[:]
plugin.run_welcome(s, lambda: done.append(1))
title, entries, choose = MENUS[-1]
check(
    "Welcome" in plugin.to_text(title) and [
        k for _l,
        k in entries] == [
            "prism",
            "halo",
            "orbit",
            "classic"],
    "first the look: %s" % [
        k for _l,
        k in entries])
check(plugin.to_text(entries[0][0]).startswith(u"✓"), "the one in use ticked")
choose("halo")
check(cfg.theme.value == "halo" and cfg.theme.saved ==
      "halo", "Halo chosen and saved")
cls, _a, _k, cb = s.opened[-1]
check(cls is plugin.VavooCountries and _a == (
    None, True), "then Choose countries (first run)")
cb(True)
cls, a, _k, cb = s.opened[-1]
check(cls.__name__ == "MessageBox" and "PIN" in plugin.to_text(
    a[0]), "then: a PIN for the adult channels?")
cb(True)
cls, _a, _k, cb = s.opened[-1]
check(cls is plugin.VavooPin, "the PIN pad")
cb("4321")
cls, _a, _k, cb = s.opened[-1]
cb("4321")
check(
    store.has_pin() and done == [1] and cfg.welcome_done.value is True and cfg.countries_asked.value is True,
    "PIN set, done, never again")
store.set_pin("")

cfg.welcome_done = El(False)
cfg.theme = El("prism")
done = []
s = Session()
plugin.run_welcome(s, lambda: done.append(1))
MENU_CANCELS[-1]()
check(
    done == [1] and cfg.theme.value == "prism" and cfg.welcome_done.value is True,
    "EXIT on the look: straight to the main list, marked as done")
cfg.welcome_done = El(False)
done = []
s = Session()
plugin.run_welcome(s, lambda: done.append(1))
MENUS[-1][2]("orbit")
s.opened[-1][3](False)              # Choose countries: Back
s.opened[-1][3](False)              # no PIN
check(done == [1] and not store.has_pin(),
      "Back on the countries, No to the PIN: done, no PIN")
plugin.proxy_countries = lambda: []
cfg.welcome_done = El(False)
done = []
s = Session()
plugin.run_welcome(s, lambda: done.append(1))
MENUS[-1][2]("classic")
check(s.opened[-1][0].__name__ == "MessageBox",
      "no countries known yet: straight to the PIN question")

print("== before the main list, in the chosen look")
cfg.welcome_done = El(False)
calls = []
plugin.run_welcome = lambda session, on_done: calls.append(on_done)
plugin.welcome_needed = lambda: True
start = make(plugin.startVavoo, Session())
start.clsgo()
check(
    calls and not any(
        c[0] is plugin.MainVavoo for c in start.session.opened),
    "the start screen runs the welcome first, the main list not open yet")
calls[0]()
check(any(c[0] is plugin.MainVavoo for c in start.session.opened)
      and start.closed_with, "then the main list, and the start screen closes")
plugin.cfg.theme = harness.V("halo")
plugin._theme_skin_cache.clear()
main = make(plugin.MainVavoo, Session())
check(
    "halo" in (
        main.skin or ""),
    "the main list in the look chosen a moment ago (no reopening)")
finish()
