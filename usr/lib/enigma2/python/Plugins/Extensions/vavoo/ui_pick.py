#!/usr/bin/python
# -*- coding: utf-8 -*-
"""The settings-wide pick lists (Choose countries, Parental Control)
and the PIN pad."""
from __future__ import absolute_import, print_function

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.config import configfile
from enigma import eTimer
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from . import _, __version__
from . import vavoo_store
from .vUtils import debug, make_print
"""
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin                             #
#  Created by Lululla (https://github.com/Belfagor2005) #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0    #
#  Last Modified: 202600503                              #
#                                                       #
#  Credits:                                             #
#  - Original concept by Lululla                        #
#  - Background images by @oktus                        #
#  - Additional contributions by Qu4k3                  #
#  - Linuxsat-support.com & Corvoboys communities       #
#                                                       #
#  Usage of this code without proper attribution        #
#  is strictly prohibited.                              #
#  For modifications and redistribution,                #
#  please maintain this credit header.                  #
#########################################################
"""
# Import notification system
try:
    from .notification_system import (
        init_notification_system, quick_notify, set_notify_skin)
    NOTIFICATION_AVAILABLE = True
except ImportError as e:
    debug("Notification system not available: {}".format(e))
    NOTIFICATION_AVAILABLE = False

    def quick_notify(*args, **kwargs):
        pass

    def init_notification_system(*args, **kwargs):
        pass

    def set_notify_skin(*args, **kwargs):
        pass

print = make_print("PLUGIN")


from .ui_base import (
    cfg, clock_24, info_page_keys, list_keys, list_page_rows,
    load_screen_skin, m2list, proxy_countries, show_keys, show_list,
    to_string, to_text)


class VavooPickScreen(Screen):
    """The settings-wide list screen of Choose countries / Parental
    Control (vavoo_pick.xml, vavoo_theme.pick_screen()): a list of
    rows with a value at their right end, a description under it, the
    status line and the four colour keys. Subclasses fill the rows
    (refresh()) and say what the keys do (key_actions())."""

    def __init__(self, session, description, keys):
        self.session = session
        Screen.__init__(self, session)
        used = tuple(name for name, label in
                     zip(("red", "green", "yellow", "blue"), keys) if label)
        self.skin, self._themed = load_screen_skin(
            "pick", 'vavoo_pick.xml', clock_24=clock_24(), keys=used)
        self['menulist'] = m2list([], kind="big", themed=self._themed)
        self['description'] = Label(description)
        self['statusbar'] = Label("")
        self['version'] = Label(to_string("V." + __version__))
        for name, label in zip(("red", "green", "yellow", "blue"), keys):
            self[name] = Label(label)
        actions = {
            "up": self.move_up,
            "down": self.move_down,
            "prevBouquet": self.page_down,
            "nextBouquet": self.page_up,
            "cancel": self.back,
            "red": self.back,
        }
        actions.update(self.key_actions())
        self['actions'] = ActionMap(
            ['OkCancelActions', 'ColorActions', 'DirectionActions'],
            actions, -1)
        self['epg_keys'] = info_page_keys(actions)
        # The direct keys (keymap.xml): HELP, BACK and the subclass's
        direct = {"help": self.show_help, "back": self.back}
        direct.update(self.direct_keys())
        self['list_keys'] = list_keys(direct)
        self.rows = []
        # (a method: Enigma2 exec()s an onLayoutFinish entry that is
        # not one - a lambda here crashed the box on open)
        self.onLayoutFinish.append(self._first_refresh)

    def _first_refresh(self):
        self.refresh(0)

    def key_actions(self):
        return {}

    def direct_keys(self):
        """keymap.xml's VavooListActions names this screen takes."""
        return {}

    def help_rows(self):
        return [(_("RED / EXIT"), _("Back"))]

    def show_help(self):
        show_keys(self.session, self.help_rows())

    def refresh(self, select=None):
        pass

    def _index(self):
        return self['menulist'].getSelectedIndex() or 0

    def _show(self, rows, select=None):
        self.rows = rows
        if select is None:
            select = self._index()
        self['menulist'].l.setList(rows)
        if rows:
            self['menulist'].moveToIndex(max(0, min(select, len(rows) - 1)))

    def move_up(self):
        if self.rows:
            self['menulist'].moveToIndex((self._index() - 1) % len(self.rows))

    def move_down(self):
        if self.rows:
            self['menulist'].moveToIndex((self._index() + 1) % len(self.rows))

    def page_up(self):
        if self.rows:
            self['menulist'].moveToIndex(max(
                0, self._index() - list_page_rows(self['menulist'],
                                                  self._themed)))

    def page_down(self):
        if self.rows:
            self['menulist'].moveToIndex(min(
                len(self.rows) - 1,
                self._index() + list_page_rows(self['menulist'],
                                               self._themed)))

    def back(self):
        self.close()


class VavooCountries(VavooPickScreen):
    """Settings → Choose countries (the app's CountriesActivity): every
    catalog country with its flag, ✓ shown / ✗ hidden. OK / LEFT /
    RIGHT switch one; Back · Save · Show all · Hide all. The hidden
    ones leave the main list and "Search all" (vavoo_store); never all
    of them. Closes with True when saved."""

    def __init__(self, session, countries=None, first_run=False):
        self.countries = sorted(countries if countries is not None
                                else proxy_countries(),
                                key=lambda c: to_text(c).lower())
        self.hidden = set(vavoo_store.hidden_countries())
        self._changed = False
        self._warned = False
        self.first_run = first_run
        VavooPickScreen.__init__(
            self, session,
            _("Hide the countries you never watch from the main list and "
              "from search."),
            (_("Back"), _("Save"), _("Show all"), _("Hide all")))
        if first_run:
            self.onLayoutFinish.append(self._welcome)

    def key_actions(self):
        return {"ok": self.toggle, "left": self.toggle,
                "right": self.toggle, "green": self.save,
                "yellow": self.show_all, "blue": self.hide_all}

    def help_rows(self):
        return [
            (_("OK / LEFT / RIGHT"), _("Show / hide the country")),
            (_("GREEN"), _("Save")),
            (_("YELLOW"), _("Show all")),
            (_("BLUE"), _("Hide all")),
            (_("RED / EXIT"), _("Back")),
        ]

    def _welcome(self):
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Welcome! Choose the countries for the main list "
                           "(OK shows or hides one), then GREEN saves. "
                           "Settings → Choose countries changes it later."),
                         8)

    def refresh(self, select=None):
        rows = []
        for country in self.countries:
            shown = to_text(country) not in self.hidden
            rows.append(show_list(
                country, country, kind="big", themed=self._themed,
                value=u"✓" if shown else u"✗", dim=not shown))
        self._show(rows, select)
        shown = len([c for c in self.countries
                     if to_text(c) not in self.hidden])
        self['statusbar'].setText(_("{} of {} countries shown").format(
            shown, len(self.countries)))

    def toggle(self):
        if not self.countries:
            return
        country = to_text(self.countries[self._index()])
        if country in self.hidden:
            self.hidden.discard(country)
        else:
            self.hidden.add(country)
        self._changed = True
        self.refresh()

    def show_all(self):
        self.hidden -= set(to_text(c) for c in self.countries)
        self._changed = True
        self.refresh()

    def hide_all(self):
        self.hidden |= set(to_text(c) for c in self.countries)
        self._changed = True
        self.refresh()

    def save(self):
        if self.countries and all(to_text(c) in self.hidden
                                  for c in self.countries):
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Keep at least one country"), 3)
            return
        vavoo_store.set_hidden_countries(self.hidden)
        self.close(True)

    def back(self):
        if self._changed and not self._warned:
            self._warned = True
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Changes not saved: GREEN saves, press again "
                               "to leave without saving"), 4)
            return
        self.close(False)


# ---------------------------------------------------------------------
# Parental control (vavoo_store: the PIN, what it locks, the pause
# after wrong PINs, the 15 minutes it stays open)
# ---------------------------------------------------------------------
class VavooPin(Screen):
    """The PIN pad (the app's PinPopup): the remote's number keys fill
    the dots, LEFT deletes one, EXIT cancels. Once `length` digits are
    in, checker(pin) decides: True closes with the PIN, False says
    "Wrong PIN - try again" and empties the dots, None closes with
    nothing (the pause after too many wrong PINs). Without a checker
    the PIN is handed back as typed. OK checks what is typed so far
    (an older PIN of another length)."""

    SUBMIT_MS = 150

    def __init__(self, session, title, length=4, checker=None):
        Screen.__init__(self, session)
        self.skin, self._themed = load_screen_skin(
            "pin", 'vavoo_pin.xml', background=False)
        self.length = max(1, int(length or 4))
        self.checker = checker
        self.digits = ""
        self['title'] = Label(title)
        self['dots'] = Label("")
        self['message'] = Label("")
        self['hint'] = Label(_("0-9: the PIN  ·  ◄ delete  "
                               "·  EXIT cancel"))
        actions = {"ok": self.submit, "cancel": self.cancel,
                   "left": self.delete, "red": self.cancel}
        for digit in range(10):
            actions[str(digit)] = (lambda d: lambda: self.key(d))(digit)
        self['actions'] = ActionMap(
            ['OkCancelActions', 'DirectionActions', 'NumberActions',
             'ColorActions'], actions, -1)
        self['list_keys'] = list_keys({"help": self.show_help,
                                       "back": self.cancel})
        self._submit_timer = eTimer()
        try:
            self._submit_timer.callback.append(self.submit)
        except Exception:
            self._submit_timer.timeout.connect(self.submit)
        self._draw()

    def _draw(self):
        shown = max(self.length, len(self.digits))
        self['dots'].setText(to_string(u" ".join(
            u"●" if i < len(self.digits) else u"○"
            for i in range(shown))))

    def show_help(self):
        show_keys(self.session, [
            ("0-9", _("The PIN")),
            (_("LEFT"), _("Delete a digit")),
            ("OK", _("Check it")),
            (_("RED / EXIT"), _("Cancel")),
        ])

    def key(self, digit):
        if len(self.digits) >= self.length:
            return
        self.digits += str(digit)
        self['message'].setText("")
        self._draw()
        if len(self.digits) == self.length:
            # (a moment to see the last dot, as in the app)
            self._submit_timer.start(self.SUBMIT_MS, True)

    def delete(self):
        self.digits = self.digits[:-1]
        self._draw()

    def submit(self):
        self._submit_timer.stop()
        if not self.digits:
            return
        pin, self.digits = self.digits, ""
        result = self.checker(pin) if self.checker else True
        if result is True:
            self.close(pin)
        elif result is None:
            self.close(None)
        else:
            self['message'].setText(_("Wrong PIN - try again"))
            self._draw()

    def cancel(self):
        self._submit_timer.stop()
        self.close(None)


def _pin_wait_note(seconds):
    if NOTIFICATION_AVAILABLE:
        quick_notify(_("Too many wrong PINs - try again in {} s").format(
            seconds), 3)


def ask_pin(session, screen, on_success, on_cancel=None):
    """The app's askPin(): open (no PIN, or entered in the last 15
    minutes) - on_success() at once; in the pause after too many wrong
    PINs - a note; else the PIN pad. `screen` is checked for `_closed`
    before acting: the pad can outlive a screen the user has left."""
    if vavoo_store.is_unlocked():
        on_success()
        return
    wait = vavoo_store.pin_wait()
    if wait:
        _pin_wait_note(wait)
        if on_cancel:
            on_cancel()
        return

    def checker(pin):
        state, seconds = vavoo_store.check_pin(pin)
        if state == "ok":
            return True
        if state == "blocked":
            _pin_wait_note(seconds)
            return None
        return False

    def done(pin=None):
        if getattr(screen, '_closed', False):
            return
        if pin is not None and vavoo_store.is_unlocked():
            on_success()
        elif on_cancel:
            on_cancel()

    if not vavoo_store.pin_is_digits():
        # an older PIN with letters (carried over from the settings):
        # typed on the keyboard until a new one is set
        def typed(text=None):
            if text is None:
                done(None)
            elif checker(to_text(text)) is True:
                done(text)
            else:
                if NOTIFICATION_AVAILABLE:
                    quick_notify(_("Wrong PIN - try again"), 2)
                done(None)
        session.openWithCallback(typed, VirtualKeyBoard,
                                 title=_("Enter the PIN"))
        return
    session.openWithCallback(done, VavooPin, _("Enter the PIN"),
                             vavoo_store.pin_length(), checker)


def ask_new_pin(session, on_done):
    """A new PIN, typed twice (4 digits)."""
    def second(first):
        if first is None:
            return

        def check(again=None):
            if again is None:
                return
            if again == first:
                on_done(first)
            elif NOTIFICATION_AVAILABLE:
                quick_notify(_("The two PINs differ - not changed"), 3)
        session.openWithCallback(check, VavooPin, _("The same PIN again"), 4)
    session.openWithCallback(second, VavooPin, _("New PIN (4 digits)"), 4)


def _require_parental_pin(session, screen, country_name, on_success,
                          channel_name=None, group=None):
    """on_success() at once, unless it needs the PIN: a locked country
    - or, given a channel, its country is locked or it is an adult
    channel (name or category) - and the PIN was not entered in the
    last 15 minutes. Then the PIN pad first (ask_pin())."""
    if channel_name is not None:
        needed = vavoo_store.needs_pin_for_channel(
            channel_name, country_name, group)
    else:
        needed = vavoo_store.needs_pin_for_country(country_name)
    if not needed:
        on_success()
        return
    ask_pin(session, screen, on_success)


def _move_parental_out_of_settings():
    """The PIN (in clear) and the locked countries were settings
    before: into vavoo_store, the PIN hashed - once."""
    try:
        if vavoo_store.migrate_parental(cfg.parental_pin.value,
                                        cfg.parental_countries.value):
            print("[vavoo] Parental control moved to {}".format(
                vavoo_store.parental_file()))
        if cfg.parental_pin.value or cfg.parental_countries.value:
            cfg.parental_pin.value = ""
            cfg.parental_countries.value = ""
            cfg.parental_pin.save()
            cfg.parental_countries.save()
            configfile.save()
    except Exception as e:
        print("[vavoo] Parental control not moved: {}".format(e))


_move_parental_out_of_settings()


class VavooParental(VavooPickScreen):
    """Settings → Parental Control (the app's ParentalActivity): set /
    change / remove the PIN, lock adult channels, lock the settings,
    and the countries it locks (a padlock, or "—"). OK / LEFT / RIGHT
    act on a row; changes are kept at once; RED goes back."""

    ROW_PIN = "pin"
    ROW_REMOVE = "remove"
    ROW_ADULT = "adult"
    ROW_SETTINGS = "settings"

    def __init__(self, session, countries=None):
        self.countries = sorted(countries if countries is not None
                                else proxy_countries(),
                                key=lambda c: to_text(c).lower())
        self.keys = []
        self._remove_armed = False
        VavooPickScreen.__init__(
            self, session,
            _("A 4-digit PIN for adult channels, chosen countries and "
              "(optionally) the settings. Once entered, all is open for "
              "15 minutes or until the plugin is left."),
            (_("Back"), "", "", ""))

    def key_actions(self):
        return {"ok": self.act, "left": self.act, "right": self.act}

    def help_rows(self):
        return [
            (_("OK / LEFT / RIGHT"), _("Change the setting / lock the country")),
            (_("RED / EXIT"), _("Back")),
        ]

    def refresh(self, select=None):
        has_pin = vavoo_store.has_pin()
        yes, no = _("Yes"), _("No")
        rows, keys = [], []

        def setting(key, label, value):
            keys.append(key)
            rows.append(show_list(to_string(label), key, is_category=True,
                                  kind="big", themed=self._themed,
                                  value=value, no_icon=True))

        setting(self.ROW_PIN, _("Change the PIN") if has_pin
                else _("Set a PIN"),
                u"●●●●" if has_pin else u"—")
        if has_pin:
            setting(self.ROW_REMOVE, _("Remove the PIN (unlock everything)"),
                    None)
        setting(self.ROW_ADULT, _("Lock adult channels"), u"‹ {} ›".format(
            to_text(yes if vavoo_store.lock_adult() else no)))
        setting(self.ROW_SETTINGS, _("Lock the settings"), u"‹ {} ›".format(
            to_text(yes if vavoo_store.lock_settings() else no)))
        locked = set(c.lower() for c in vavoo_store.locked_countries())
        for country in self.countries:
            is_locked = to_text(country).lower() in locked
            keys.append(u"c:" + to_text(country))
            rows.append(show_list(
                country, country, kind="big", themed=self._themed,
                value=u"" if is_locked else u"—",
                value_icon=is_locked))
        self.keys = keys
        self._show(rows, select)
        if has_pin:
            self['statusbar'].setText(_("PIN set · {} countries locked").format(
                len(locked)))
        else:
            self['statusbar'].setText(
                _("No PIN yet: nothing is locked until one is set."))

    def act(self):
        if not self.keys:
            return
        key = self.keys[self._index()]
        if key != self.ROW_REMOVE:
            self._remove_armed = False
        if key == self.ROW_PIN:
            ask_new_pin(self.session, self._new_pin)
        elif key == self.ROW_REMOVE:
            if not self._remove_armed:
                self._remove_armed = True
                if NOTIFICATION_AVAILABLE:
                    quick_notify(_("Press again to confirm"), 3)
                return
            self._remove_armed = False
            vavoo_store.set_pin(None)
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("PIN removed"), 3)
            self.refresh(0)
        elif key == self.ROW_ADULT:
            vavoo_store.set_option("adult", not vavoo_store.lock_adult())
            self.refresh()
        elif key == self.ROW_SETTINGS:
            vavoo_store.set_option("settings",
                                   not vavoo_store.lock_settings())
            self.refresh()
        elif key.startswith(u"c:"):
            country = key[2:]
            locked = vavoo_store.locked_countries()
            match = [c for c in locked if c.lower() == country.lower()]
            if match:
                locked -= set(match)
            else:
                locked.add(country)
            vavoo_store.set_locked_countries(locked)
            self.refresh()

    def _new_pin(self, pin):
        if self._closed_flag():
            return
        vavoo_store.set_pin(pin)
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("PIN saved"), 3)
        self.refresh()

    def _closed_flag(self):
        return getattr(self, '_closed', False)
