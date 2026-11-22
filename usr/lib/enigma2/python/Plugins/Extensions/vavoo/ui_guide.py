#!/usr/bin/python
# -*- coding: utf-8 -*-
"""The programme guide (the app's EPG grid) and the reminders service."""
from __future__ import absolute_import, print_function
from .ui_settings import (
    open_settings)
from .ui_record import (
    MEMORY_WATCH, RECORDINGS, VavooRecordings, recording_text)
from .ui_pick import (
    ask_pin)
from .ui_base import (
    ACTIVE, THEME_WIDTH, _epg_channel_id, _in_standby, build_theme_skin,
    cfg, clock_text, current_theme, floor_half_hour, info_page_keys,
    large_text, list_keys, named, open_action_menu, programme_time,
    row_number, scaled_icon, show_keys, to_string, to_text)

import time
import threading
from twisted.internet import reactor
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryPixmapAlphaTest, MultiContentEntryText
from enigma import (
    RT_HALIGN_LEFT,
    RT_VALIGN_CENTER,
    eListboxPythonMultiContent,
    eTimer,
    gFont
)
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from . import _
from . import vUtils
from . import vavoo_theme
from . import vavoo_store
from .vUtils import debug, make_print
try:
    # blends a picture's soft edges (the initials tiles' round corners)
    from Components.MultiContent import MultiContentEntryPixmapAlphaBlend
except ImportError:
    MultiContentEntryPixmapAlphaBlend = MultiContentEntryPixmapAlphaTest
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


def play_reminder(session, timer):
    """A reminder's "watch it": in the player if it is open (zapping
    there, the channel added to its list if needed), else from the
    main list, else the plugin opens and plays it once its list is
    in. The PIN is asked where needed, as for any channel."""
    channel = {"name": timer.get("name"), "url": timer.get("url"),
               "country_name": timer.get("country") or None,
               "country_code": timer.get("country_code") or None,
               "logo": timer.get("logo") or ""}
    player = ACTIVE.get("player")
    if player is not None and not getattr(player, "_closed", True):
        player.play_channel(channel)
        return
    main_screen = ACTIVE.get("main")
    if main_screen is not None and not getattr(main_screen, "_closed", True):
        main_screen._open_channel(channel)
        return
    ACTIVE["pending"] = channel
    from .plugin import main                # (plugin.py imports this module)
    main(session)


class _ReminderService(object):
    """The reminders going off at their programme's start (the app:
    0 minutes before), also with the plugin closed: started at session
    start (autostart()) and by the plugin, a 15-second eTimer like the
    sleep timer's. A window asks "watch it?" (30 s); in standby the
    reminder passes without a word."""

    TICK_MS = 15000
    ANSWER_SECONDS = 30

    def __init__(self):
        self.session = None
        self.timer = None

    def start(self, session=None):
        if session is not None:
            self.session = session
        if self.timer is None:
            self.timer = eTimer()
            try:
                self.timer.callback.append(self.tick)
            except Exception:
                self.timer.timeout.connect(self.tick)
        try:
            vavoo_store.prune_timers()
        except Exception as e:
            debug("Reminders not pruned: {}".format(e))
        if not self.timer.isActive():
            self.timer.start(self.TICK_MS, False)

    def tick(self):
        try:
            MEMORY_WATCH.tick()
        except Exception as e:
            debug("Memory watch: {}".format(e))
        try:
            due = vavoo_store.due_timers(kind=vavoo_store.KIND_REMIND)
            records = vavoo_store.due_timers(kind=vavoo_store.KIND_RECORD)
        except Exception as e:
            debug("Reminders not read: {}".format(e))
            return
        for timer in due:
            self.fire(timer)
        for timer in records:
            self.record(timer)

    def record(self, timer):
        """A recording set in the guide: starts 2 minutes before its
        programme (vavoo_store.alarm_time()), also in standby and with
        the plugin closed, until its end plus the same margin."""
        stop_at = (timer.get("stop") or 0) + vavoo_store.RECORD_MARGIN
        if stop_at <= time.time():
            return
        channel = {"name": timer.get("name"), "url": timer.get("url"),
                   "country_name": timer.get("country") or None,
                   "country_code": timer.get("country_code") or None,
                   "logo": timer.get("logo") or ""}
        recorder = RECORDINGS.start(channel, timer.get("title"), stop_at,
                                    quiet=True)
        if not NOTIFICATION_AVAILABLE:
            return
        if recorder is None:
            quick_notify(_("Scheduled recording not started: {}").format(
                to_string(timer.get("title"))), 6)
        elif not _in_standby():
            quick_notify(recording_text(timer.get("title"), stop_at), 4)

    def fire(self, timer):
        if self.session is None or _in_standby():
            return
        text = u"{}\n{}".format(
            to_text(_("Starting now: {}")).format(to_text(timer.get("title"))),
            to_text(_("On {} - watch it?")).format(to_text(timer.get("name"))))

        def answered(answer=None):
            if answer:
                play_reminder(self.session, timer)

        try:
            from Tools.Notifications import AddNotificationWithCallback
            AddNotificationWithCallback(
                answered, MessageBox, to_string(text), MessageBox.TYPE_YESNO,
                timeout=self.ANSWER_SECONDS, default=False)
        except Exception as e:
            debug("Reminder window not shown: {}".format(e))
            try:
                self.session.openWithCallback(
                    answered, MessageBox, to_string(text),
                    MessageBox.TYPE_YESNO, timeout=self.ANSWER_SECONDS,
                    default=False)
            except Exception:
                pass


REMINDERS = _ReminderService()


# ---------------------------------------------------------------------
# The programme guide grid (the app's EpgGuideActivity / EpgGrid)
# ---------------------------------------------------------------------
GUIDE_STEP = 1800          # the window moves by half hours
GUIDE_BACK = 3 * 3600      # and reaches this far back
GUIDE_SETTLE_MS = 300
GUIDE_REFRESH_MS = 60000


class GuideList(MenuList):
    """A MultiContent list whose rows VavooGuide draws whole (the time
    ruler, the grid): one font, a fixed row height, no selection."""

    def __init__(self, item_height, font_name, font_size):
        MenuList.__init__(self, [], False, eListboxPythonMultiContent)
        self.item_height = item_height
        self.l.setItemHeight(item_height)
        self.l.setFont(0, gFont(font_name, font_size))


class VavooGuide(Screen):
    """The programme guide (the app's EpgGuideActivity): the channels
    of the list it was opened from down, three hours across, a box per
    programme. Closes with ("watch", index) when a channel is to be
    watched, else None.

    `channels`: [{"name", "url", "country_name", "country_code",
    "logo", "category", "epg_id"}]. `over_player`: drawn over the
    video (MENU closes it, CH± zaps the player through on_zap(delta),
    which returns the index now playing)."""

    _closed = True          # (ui_base's CLOSED_UNTIL_OPEN)

    def __init__(self, session, channels, start_index=0, title="",
                 over_player=False, on_zap=None):
        self._closed = False
        self.session = session
        Screen.__init__(self, session)
        self.channels = list(channels)
        self.title_text = to_text(title)
        self.over = over_player
        self.on_zap = on_zap
        preview = bool(cfg.preview_window.value) and not over_player
        skin = build_theme_skin("guide", preview=preview, over=over_player)
        self._themed = skin is not None
        self.skin = skin or vavoo_theme.guide_classic(
            THEME_WIDTH, large_text(), preview, over_player)
        self.m = vavoo_theme.guide_metrics(large_text(), THEME_WIDTH,
                                           preview)
        colors = vavoo_theme.guide_colors(
            current_theme() if self._themed else "classic")
        self.colors = dict((key, vavoo_theme.e2_int(value))
                           for key, value in colors.items()
                           if key not in ("font", "font_bold"))
        self.rows = max(1, min(self.m["rows"], len(self.channels)))
        self['heading'] = Label("")
        self['details'] = Label("")
        self['ruler'] = GuideList(self.m["header_h"], colors["font"],
                                  max(8, int(self.m["header_h"] * 0.42)))
        self['grid'] = GuideList(self.m["row_h"], colors["font"],
                                 self.m["font_size"])
        # RED records the highlighted programme (its caption follows it:
        # _update_record_key()); EXIT / BACK close
        self['red'] = Label(to_string(u"\u25cf " + to_text(_("Record"))))
        self['green'] = Label(_("Watch"))
        self['yellow'] = Label(u"◀ " + to_text(_("Earlier")))
        self['blue'] = Label(to_text(_("Later")) + u" ▶")

        now = time.time()
        self.min_start = floor_half_hour(now - GUIDE_BACK)
        self.max_start = max(self.min_start, floor_half_hour(
            now + vUtils._EPG_GUIDE_AHEAD - vavoo_theme.GUIDE_WINDOW))
        self.win_start = floor_half_hour(now)
        self.focus = now
        self.sel_row = max(0, min(int(start_index or 0),
                                  len(self.channels) - 1))
        self.first_row = max(0, min(self.sel_row - self.rows // 2,
                                    len(self.channels) - self.rows))
        # url -> (status, programmes); status "ok", "no_match",
        # "no_programme", "no_guide", "no_country"
        self.data = {}
        self._digits = ""
        self._digit_time = 0
        self._lock = threading.Lock()
        self._wanted = []
        self._working = False
        self._settle_timer = eTimer()
        self._refresh_timer = eTimer()
        for timer, fn in ((self._settle_timer, self._load_visible),
                          (self._refresh_timer, self._refresh)):
            try:
                timer.callback.append(fn)
            except Exception:
                timer.timeout.connect(fn)

        actions = {
            "ok": self.ok, "cancel": self.close_guide,
            "red": self.record_selected, "green": self.watch,
            "yellow": lambda: self.shift(-3600),
            "blue": lambda: self.shift(3600),
            "up": lambda: self.move_row(-1, wrap=True),
            "down": lambda: self.move_row(1, wrap=True),
            "left": self.previous_programme,
            "right": self.next_programme,
            "nextBouquet": lambda: self.page(-1),
            "prevBouquet": lambda: self.page(1),
            "menu": self.menu, "info": self.go_now, "epg": self.go_now,
        }
        for digit in range(10):
            actions[str(digit)] = (lambda d: lambda: self.number(d))(digit)
        self['actions'] = ActionMap(
            ['OkCancelActions', 'ColorActions', 'DirectionActions',
             'MenuActions', 'InfobarEPGActions', 'NumberActions'],
            actions, -1)
        self['epg_keys'] = info_page_keys(actions)
        # The direct keys (keymap.xml): REC the highlighted programme,
        # PLAY watch it, PVR the recordings (not over the player), HELP
        keys = {"record": self.record_selected, "play": self.watch,
                "help": self.show_help, "back": self.close_guide}
        if not over_player:
            keys["recordings"] = lambda: self.session.open(VavooRecordings)
        self['list_keys'] = list_keys(keys)
        self.onLayoutFinish.append(self._start)
        self.onClose.append(self._mark_closed)

    def record_selected(self):
        """REC: record the highlighted programme (on now: from now; to
        come: a timer) - again: cancel / stop. As OK -> Record."""
        if not self.channels or not 0 <= self.sel_row < len(self.channels):
            return
        programme = self._selected_programme()
        if programme is None or programme[1] <= time.time():
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("No programme to record here"), 2)
            return
        self.toggle_record(self.channels[self.sel_row], programme)

    def help_rows(self):
        rows = [
            ("OK", _("A programme to come: remind / record / watch")),
            (_("RED / REC"), _("Record the programme (again: cancel / stop)")),
            (_("GREEN / PLAY"), _("Watch the channel")),
            (_("UP / DOWN"), _("Channel")),
            (_("LEFT / RIGHT"), _("Programme")),
            (_("YELLOW / BLUE"), _("An hour back / on")),
            ("INFO / EPG", _("Now")),
            ("MENU", _("Now, the programme's actions")),
            ("CH+ / CH-", _("Page up / down")),
            ("1-9", _("Go to that channel")),
            (_("EXIT / BACK"), _("Close")),
        ]
        if not self.over:
            rows.insert(9, (_("PVR / FILE"), _("Recordings")))
        return rows

    def show_help(self):
        show_keys(self.session, self.help_rows())

    # ---- state

    def _mark_closed(self):
        self._closed = True
        for timer in (self._settle_timer, self._refresh_timer):
            try:
                timer.stop()
            except Exception:
                pass
        with self._lock:
            self._wanted = []

    def _start(self):
        self._load_visible()
        self.draw()
        self._refresh_timer.start(GUIDE_REFRESH_MS, True)

    def _refresh(self):
        """Once a minute: the now line moves."""
        if self._closed:
            return
        self.draw()
        self._refresh_timer.start(GUIDE_REFRESH_MS, True)

    def _range(self):
        return self.min_start, self.max_start + vavoo_theme.GUIDE_WINDOW

    def _visible(self):
        return range(self.first_row,
                     min(len(self.channels), self.first_row + self.rows))

    def _locked(self, channel):
        try:
            return vavoo_store.needs_pin_for_channel(
                channel.get("name"), channel.get("country_name"),
                channel.get("category"))
        except Exception:
            return False

    def _status(self, index):
        """("locked" | "loading" | status word, programmes)."""
        channel = self.channels[index]
        if self._locked(channel):
            return "locked", []
        answer = self.data.get(channel.get("url"))
        if answer is None:
            return "loading", []
        return answer

    def _programmes(self, index):
        status, programmes = self._status(index)
        return programmes if status == "ok" else []

    # ---- loading (the visible rows only; the latest page wins)

    def _load_visible(self):
        if self._closed:
            return
        start, stop = self._range()
        wanted = []
        rows = sorted(self._visible(), key=lambda i: abs(i - self.sel_row))
        for index in rows:
            channel = self.channels[index]
            url = channel.get("url")
            if url in self.data or self._locked(channel):
                continue
            try:
                answer = vUtils.peek_programmes(
                    channel.get("name"), channel.get("country_code"),
                    start, stop)
            except Exception:
                answer = None
            if answer is not None:
                self.data[url] = answer
            else:
                wanted.append(index)
        if not wanted:
            return
        with self._lock:
            self._wanted = wanted
            start_worker = not self._working
            if start_worker:
                self._working = True
        if start_worker:
            worker = threading.Thread(target=named(self._work, "vv-guide"))
            worker.daemon = True
            worker.start()
        self._draw_heading()

    def _work(self):
        # (what it needs kept here: the screen's attributes are gone
        # once it has closed - CLOSED_UNTIL_OPEN)
        if self._closed:
            return
        start, stop = self._range()
        lock, channels = self._lock, self.channels
        while True:
            with lock:
                if self._closed:
                    return
                if not self._wanted:
                    self._working = False
                    break
                index = self._wanted.pop(0)
            channel = channels[index]
            try:
                answer = vUtils.lookup_programmes(
                    channel.get("name"), channel.get("country_code"),
                    start, stop, channel_id=_epg_channel_id(
                        channel.get("url")),
                    epg_id=channel.get("epg_id"))
            except Exception as e:
                debug("Guide: lookup failed: {}".format(e))
                answer = ("no_guide", [])
            if not self._closed:
                reactor.callFromThread(self._arrived, channel.get("url"),
                                       answer)
        if not self._closed:
            reactor.callFromThread(self._draw_heading)

    def _arrived(self, url, answer):
        if self._closed:
            return
        self.data[url] = answer
        if any(self.channels[i].get("url") == url for i in self._visible()):
            self.draw()

    # ---- drawing

    def _x(self, timestamp):
        return int(self.m["name_w"] + (timestamp - self.win_start) *
                   self.m["time_w"] / float(vavoo_theme.GUIDE_WINDOW))

    def _rect(self, x, y, w, h, color):
        return MultiContentEntryText(
            pos=(int(x), int(y)), size=(max(1, int(w)), max(1, int(h))),
            font=0, text="", backcolor=color, backcolor_sel=color)

    def _text(self, x, y, w, h, text, color, halign=RT_HALIGN_LEFT):
        return MultiContentEntryText(
            pos=(int(x), int(y)), size=(max(1, int(w)), max(1, int(h))),
            font=0, text=to_string(text), flags=halign | RT_VALIGN_CENTER,
            color=color, color_sel=color)

    def draw(self):
        if self._closed:
            return
        self['ruler'].l.setList([self._ruler_entry()])
        self['grid'].l.setList([self._row_entry(i) for i in self._visible()])
        self._draw_heading()
        self._draw_details()
        self._update_record_key()

    def _update_record_key(self):
        """RED's caption for the highlighted programme: what pressing it
        would do (record_selected() / toggle_record())."""
        text = u"\u25cf " + to_text(_("Record"))
        try:
            programme = self._selected_programme()
            if programme is not None and programme[1] > time.time() and \
                    0 <= self.sel_row < len(self.channels):
                channel = self.channels[self.sel_row]
                if vavoo_store.find_timer(channel.get("url"), programme[0],
                                          vavoo_store.KIND_RECORD):
                    text = to_text(_("Cancel recording"))
                elif self._recording_now(channel, programme):
                    text = to_text(_("Stop recording"))
        except Exception as e:
            debug("Guide: record key not updated: {}".format(e))
        self['red'].setText(to_string(text))

    def _draw_heading(self):
        if self._closed:
            return
        text = self.title_text
        with self._lock:
            loading = self._working
        if loading:
            text += u"  ·  " + to_text(_("Loading…"))
        self['heading'].setText(to_string(text))

    def _ruler_entry(self):
        """The time ruler: a half-hour label and tick every half hour,
        the now line with its dot (EpgGrid's header)."""
        m, c = self.m, self.colors
        height = m["header_h"]
        half = m["time_w"] / 6.0
        entry = [(None,), self._rect(0, 0, m["grid_w"], height,
                                     c["grid_header"])]
        tick_top = int(height * 0.75)
        for step in range(6):
            moment = self.win_start + step * GUIDE_STEP
            x = m["name_w"] + step * half
            local = time.localtime(moment)
            label = to_text(clock_text(moment))
            if local.tm_hour == 0 and local.tm_min == 0:
                label = to_text(time.strftime("%a ", local)) + label
            entry.append(self._text(x + m["pad"], 0, half - m["pad"],
                                    tick_top, label, c["tick_text"]))
            entry.append(self._rect(x, tick_top, 2, height - tick_top,
                                    c["tick_line"]))
        x_now = self._x(time.time())
        if m["name_w"] <= x_now < m["grid_w"]:
            entry.append(self._rect(x_now - 1, 0, 3, height,
                                    c["grid_now_line"]))
            dot = max(4, int(height * 0.18))
            entry.append(self._rect(x_now - dot // 2, height - dot, dot,
                                    dot, c["grid_now_line"]))
        return entry

    def _row_entry(self, index):
        m, c = self.m, self.colors
        channel = self.channels[index]
        height, width = m["row_h"], m["grid_w"]
        name_w, pad = m["name_w"], m["pad"]
        selected = index == self.sel_row
        now = time.time()
        entry = [(index,)]
        x_now = self._x(now)
        if name_w <= x_now < width:
            # the now line, behind the boxes (seen in their gaps)
            entry.append(self._rect(x_now - 1, 0, 3, height,
                                    c["grid_now_line"]))
        digits = len(str(len(self.channels)))
        entry.append(self._rect(2, 2, name_w - 4, height - 4,
                                c["selected"] if selected else c["grid_name"]))
        entry.append(self._text(
            2 + pad, 0, name_w - 4 - 2 * pad, height,
            u"{}  {}".format(row_number(index + 1, digits, u" "),
                             to_text(channel.get("name"))), 0xffffff))
        status, programmes = self._status(index)
        win_end = self.win_start + vavoo_theme.GUIDE_WINDOW
        shown = [p for p in programmes
                 if p[1] > self.win_start and p[0] < win_end]
        if not shown:
            entry.append(self._rect(name_w + 2, 2, width - name_w - 4,
                                    height - 4, c["none"]))
            if status == "locked":
                lock_h = max(8, int(height * 0.5))
                lock = vavoo_store.lock_path(lock_h)
                png = scaled_icon(lock, int(lock_h * 0.75), lock_h) \
                    if lock else None
                if png is not None:
                    entry.append(MultiContentEntryPixmapAlphaBlend(
                        pos=(name_w + 2 + pad, (height - lock_h) // 2),
                        size=(int(lock_h * 0.75), lock_h), png=png))
            else:
                entry.append(self._text(
                    name_w + 2 + pad, 0, width - name_w - 4 - 2 * pad, height,
                    _("Loading…") if status == "loading"
                    else _("No programme information"), c["no_info"]))
            return entry
        chosen = self._selected_programme() if selected else None
        recording = RECORDINGS.recording_of(channel.get("url")) is not None
        for programme in shown:
            x0 = max(name_w, self._x(programme[0])) + 2
            x1 = min(width, self._x(programme[1])) - 2
            if x1 <= x0:
                continue
            if chosen is not None and programme == chosen:
                color, text_color = c["selected"], 0xffffff
            elif programme[0] <= now < programme[1]:
                color, text_color = c["grid_now"], c["text"]
            else:
                color, text_color = c["grid_prog"], c["text"]
            entry.append(self._rect(x0, 2, x1 - x0, height - 4, color))
            if x1 - x0 - 2 * pad <= height * 0.5:
                continue
            left = x0 + pad
            if vavoo_store.find_timer(channel.get("url"), programme[0]):
                # a reminder is set: the app's ⏰ before the title
                side = max(8, int(height * 0.4))
                mark = vavoo_store.clock_path(side)
                png = scaled_icon(mark, side, side) if mark else None
                if png is not None:
                    entry.append(MultiContentEntryPixmapAlphaBlend(
                        pos=(left, (height - side) // 2), size=(side, side),
                        png=png))
                    left += side + pad // 2
            title = programme[2]
            if vavoo_store.find_timer(channel.get("url"), programme[0],
                                      vavoo_store.KIND_RECORD) or (
                    recording and programme[0] <= now < programme[1]):
                # a recording set (or running): the app's "● "
                title = u"● " + to_text(title)
            entry.append(self._text(left, 0, x1 - pad - left, height,
                                    title, text_color))
        return entry

    def _draw_details(self):
        if not self.channels:
            return
        channel = self.channels[self.sel_row]
        name = to_text(channel.get("name"))
        status, _programmes = self._status(self.sel_row)
        programme = self._selected_programme()
        if programme is None:
            text = u"{}\n{}".format(name, to_text(
                _("Loading…") if status == "loading"
                else _("No programme information")))
        else:
            text = u"{}  ·  {}–{}  {}".format(
                name, to_text(programme_time(programme[0])),
                to_text(clock_text(programme[1])), to_text(programme[2]))
            if programme[3]:
                text += u"\n" + to_text(programme[3])
        self['details'].setText(to_string(text))

    # ---- selection and the window (EpgGrid's rules)

    def _selected_programme(self):
        """The programme at the focus time, else the first after it,
        else the last."""
        programmes = self._programmes(self.sel_row)
        if not programmes:
            return None
        for programme in programmes:
            if programme[0] <= self.focus < programme[1]:
                return programme
        for programme in programmes:
            if programme[0] > self.focus:
                return programme
        return programmes[-1]

    def _clamp_start(self, start):
        return max(self.min_start, min(start, self.max_start))

    def focus_on(self, moment):
        last = self.max_start + vavoo_theme.GUIDE_WINDOW - 1
        moment = max(self.min_start, min(moment, last))
        if moment < self.win_start:
            self.win_start = self._clamp_start(floor_half_hour(moment))
        elif moment >= self.win_start + vavoo_theme.GUIDE_WINDOW:
            self.win_start = self._clamp_start(
                floor_half_hour(moment) - vavoo_theme.GUIDE_WINDOW +
                GUIDE_STEP)
        self.focus = moment

    def shift(self, delta):
        """The window `delta` seconds on (it stops at its limits; the
        focus stays inside it)."""
        start = self._clamp_start(self.win_start + delta)
        self.focus = max(start, min(self.focus + delta,
                                    start + vavoo_theme.GUIDE_WINDOW - 1))
        self.win_start = start
        self.draw()

    def go_now(self):
        now = time.time()
        self.win_start = self._clamp_start(floor_half_hour(now))
        self.focus = now
        self.draw()

    def previous_programme(self):
        self._step_programme(-1)

    def next_programme(self):
        self._step_programme(1)

    def _step_programme(self, direction):
        programmes = self._programmes(self.sel_row)
        chosen = self._selected_programme()
        if chosen is not None:
            index = programmes.index(chosen) + direction
            if 0 <= index < len(programmes):
                self.focus_on(max(programmes[index][0], self.min_start) + 1)
                self.draw()
                return
        self.shift(direction * GUIDE_STEP)

    def _show_row(self):
        first = self.first_row
        if self.sel_row < self.first_row:
            self.first_row = self.sel_row
        elif self.sel_row >= self.first_row + self.rows:
            self.first_row = self.sel_row - self.rows + 1
        if first != self.first_row:
            self._settle_timer.start(GUIDE_SETTLE_MS, True)

    def select_row(self, index):
        if not self.channels:
            return
        self.sel_row = max(0, min(index, len(self.channels) - 1))
        self._show_row()
        self.draw()

    def move_row(self, delta, wrap=False):
        if not self.channels:
            return
        index = self.sel_row + delta
        if wrap:
            index %= len(self.channels)
        self.select_row(index)

    def page(self, direction):
        """CH± / PAGE: a page of channels - over the player, CH± zaps
        the player and the grid follows."""
        if self.over and self.on_zap is not None:
            try:
                index = self.on_zap(direction)
            except Exception as e:
                debug("Guide: zap failed: {}".format(e))
                return
            if index is not None:
                self.select_row(int(index))
            return
        self.select_row(self.sel_row + direction * self.rows)

    def number(self, digit):
        """Typed within 1.5 s the digits add up (1, 2 = channel 12); a
        0 on its own goes back to now."""
        now = time.time()
        if now - self._digit_time > 1.5:
            self._digits = ""
        self._digit_time = now
        if not self._digits and digit == 0:
            self.go_now()
            return
        self._digits = (self._digits + str(digit))[-4:]
        target = int(self._digits) - 1
        if 0 <= target < len(self.channels):
            self.select_row(target)

    # ---- actions

    def ok(self):
        """A programme still to come: Remind me / Record / Watch (the
        app's programmeMenu); one on now, or none: watch the channel."""
        programme = self._selected_programme()
        if programme is None or programme[0] <= time.time():
            self.watch()
            return
        channel = self.channels[self.sel_row]
        entries = self._programme_actions(channel, programme) + \
            [(_("Watch"), "watch")]
        open_action_menu(
            self.session, to_string(programme[2]), entries,
            lambda key: self._on_action(key, channel, programme))

    def _programme_actions(self, channel, programme):
        """What can be done with a programme not over yet (the app's
        programmeActions): its reminder (one still to come), its
        recording."""
        now = time.time()
        url = channel.get("url")
        out = []
        reminder = vavoo_store.find_timer(url, programme[0])
        if programme[0] > now or reminder:
            out.append((_("Cancel reminder") if reminder else _("Remind me"),
                        "remind"))
        if programme[1] > now:
            if vavoo_store.find_timer(url, programme[0],
                                      vavoo_store.KIND_RECORD):
                out.append((_("Cancel recording"), "record"))
            elif self._recording_now(channel, programme):
                out.append((_("Stop recording"), "record"))
            else:
                out.append((_("Record"), "record"))
        return out

    def _recording_now(self, channel, programme):
        now = time.time()
        return programme[0] <= now < programme[1] and \
            RECORDINGS.recording_of(channel.get("url")) is not None

    def _on_action(self, key, channel, programme):
        if self._closed or key is None:
            return
        if key in ("remind", "record") and (channel is None or
                                            programme is None):
            return
        if key == "watch":
            self.watch()
        elif key == "remind":
            self.toggle_reminder(channel, programme)
        elif key == "record":
            self.toggle_record(channel, programme)
        elif key == "now":
            self.go_now()
        elif key == "settings":
            open_settings(self.session)

    def toggle_record(self, channel, programme):
        """Record / Cancel recording / Stop recording."""
        url = channel.get("url")
        timer = vavoo_store.find_timer(url, programme[0],
                                       vavoo_store.KIND_RECORD)
        if timer:
            vavoo_store.remove_timer(timer["id"])
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Cancelled"), 2)
            self.draw()
            return
        if self._recording_now(channel, programme):
            RECORDINGS.recording_of(url).stop()
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Recording stopped"), 2)
            self.draw()
            return
        if vavoo_store.needs_pin_for_channel(
                channel.get("name"), channel.get("country_name")):
            # (parental control: a locked channel only with the PIN)
            ask_pin(self.session, self,
                    lambda: self._record(channel, programme))
            return
        self._record(channel, programme)

    def _record(self, channel, programme):
        """One on now (or starting within the margin) is recorded at
        once, until its end plus 2 minutes; one still to come is set
        (vavoo_store timer "record", started by REMINDERS)."""
        now = time.time()
        if self._closed or programme[1] <= now:
            return
        if programme[0] - vavoo_store.RECORD_MARGIN <= now:
            stop_at = programme[1] + vavoo_store.RECORD_MARGIN
            if RECORDINGS.start(channel, programme[2], stop_at) is not None \
                    and NOTIFICATION_AVAILABLE:
                quick_notify(recording_text(programme[2], stop_at), 3)
        else:
            vavoo_store.add_timer(
                vavoo_store.KIND_RECORD, channel.get("url"),
                channel.get("name"), programme[2], programme[0],
                programme[1], channel.get("country_name"),
                channel.get("country_code"), channel.get("logo"))
            REMINDERS.start(self.session)
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Recording set: {}").format(
                    to_string(programme[2])), 3)
        self.draw()

    def toggle_reminder(self, channel, programme):
        existing = vavoo_store.find_timer(channel.get("url"), programme[0])
        if existing:
            vavoo_store.remove_timer(existing["id"])
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Cancelled"), 2)
        else:
            vavoo_store.add_timer(
                vavoo_store.KIND_REMIND, channel.get("url"),
                channel.get("name"), programme[2], programme[0],
                programme[1], channel.get("country_name"),
                channel.get("country_code"), channel.get("logo"))
            REMINDERS.start(self.session)
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Reminder set: {}").format(
                    to_string(programme[2])), 3)
        self.draw()

    def watch(self):
        if self.channels:
            self.close(("watch", self.sel_row))

    def menu(self):
        """MENU: the app's key menu - Now, what can be done with the
        programme highlighted (not over yet: reminder, recording), and
        the settings (not over the player)."""
        channel = self.channels[self.sel_row] if self.channels else None
        programme = self._selected_programme() if channel else None
        entries = [(_("Now"), "now")]
        if programme is not None and programme[1] > time.time():
            entries += self._programme_actions(channel, programme)
        if not self.over:
            entries.append((_("Settings"), "settings"))
        open_action_menu(
            self.session, _("Options"), entries,
            lambda key: self._on_action(key, channel, programme))

    def close_guide(self):
        self.close(None)
