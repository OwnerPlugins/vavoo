#!/usr/bin/python
# -*- coding: utf-8 -*-
"""The full-screen player (Playstream2), its channel list over the
video, the sleep timer and the info bar."""
from __future__ import absolute_import, print_function

import time
import threading
from os import remove
from os.path import (
    exists as file_exists,
    join,
    isfile,
    getsize
)
from twisted.internet import reactor
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from Components.ServiceEventTracker import ServiceEventTracker, InfoBarBase
from enigma import (
    ePicLoad,
    eTimer,
    iPlayableService,
    iServiceInformation
)
from Screens.InfoBarGenerics import (
    InfoBarSubtitleSupport,
    InfoBarMenu,
    InfoBarSeek,
    InfoBarAudioSelection,
    InfoBarNotifications
)
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from . import vavoo_proxy
from .vavoo_proxy import GROUP_ID_PREFIX
from . import (
    _,
    PORT,
    PROXY_HOST,
    PROXY_BASE_URL
)
from . import vUtils
from . import vavoo_theme
from . import vavoo_store
from . import vavoo_record
from .vUtils import (
    debug,
    make_print,
    get_proxy_status,
    get_picon_cache_path,
    returnIMDB,
    trace_error
)
try:
    from Components.AVSwitch import AVSwitch
except ImportError:
    from Components.AVSwitch import eAVControl as AVSwitch
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
    ACTIVE, FONT_SIZE_EPG, FONT_SIZE_TOP, IS_DREAMOS, NOW_PLAYING,
    OVERLAY_HEIGHT_EPG, OVERLAY_HEIGHT_TOP, OVERLAY_PICON_H,
    OVERLAY_PICON_W, OVERLAY_PICON_X, OVERLAY_PICON_Y, OVERLAY_WIDTH,
    OVERLAY_Y_EPG, PLAYER_BAR_LABELS, PLAYER_KEYS_PRIO, PLUGIN_PATH,
    PROXY_MONITOR_INTERVAL_MS, PROXY_WATCHDOG_INTERVAL_MS, THEME_WIDTH,
    _epg_channel_id, aspect_manager, build_stream_sref, build_theme_skin,
    cfg, clock_24, favourite_channels, file_stream_sref, info_page_keys,
    list_keys, m2list, named, open_action_menu, player_keys,
    programme_time, remember_recent, show_keys, show_list,
    stream_channel_id, to_string, to_text, url_quote)
from .ui_pick import (
    ask_pin)
from .ui_record import (
    RECORDINGS, RECORD_LOG, SHIFT_WHY, pause_folder, record_channel)
from .ui_guide import (
    VavooGuide)


# The bar's buttons are captions of the remote's keys, the same in
# every theme and in Classic (whose top line lists them): no button is
# ever highlighted or walked to - every function has a key of its own.
# Enigma2's aspect ratio settings (AVSwitch.setAspectRatio()).
PLAYER_ASPECTS = (
    (0, "4:3 Letterbox"), (1, "4:3 PanScan"), (2, "16:9"),
    (3, "16:9 Always"), (4, "16:10 Letterbox"), (5, "16:10 PanScan"),
    (6, "16:9 Letterbox"))
SLEEP_CHOICES = (15, 30, 60, 90, 120)
# iServiceInformation.sVideoType values (the common ones).
VIDEO_CODECS = {0: "MPEG-2", 1: "H.264", 2: "MPEG-1", 3: "MPEG-4",
                4: "VC-1", 5: "VC-1", 6: "H.265", 7: "AVS", 8: "VP8",
                9: "VP9"}


class _SleepTimer(object):
    """The player's sleep timer (Options -> Sleep timer): when it runs
    out the box goes to standby; a message comes a minute before. Lives
    outside the player, so zapping or going back to the list keeps it."""

    def __init__(self):
        self.ends_at = 0
        self.warned = False
        self.session = None
        self.timer = None

    def set(self, session, minutes):
        self.session = session
        self.ends_at = time.time() + minutes * 60 if minutes else 0
        self.warned = False
        if self.timer is None:
            self.timer = eTimer()
            try:
                self.timer.callback.append(self._tick)
            except Exception:
                self.timer.timeout.connect(self._tick)
        self.timer.stop()
        if minutes:
            self.timer.start(15000, False)

    def minutes_left(self):
        """Minutes left (at least 1), or None when off."""
        if not self.ends_at:
            return None
        return max(1, int((self.ends_at - time.time() + 59) // 60))

    def _tick(self):
        if not self.ends_at:
            self.timer.stop()
            return
        left = self.ends_at - time.time()
        if left <= 0:
            self.ends_at = 0
            self.timer.stop()
            try:
                from Screens.Standby import Standby
                import Screens.Standby
                if not Screens.Standby.inStandby and self.session:
                    self.session.open(Standby)
            except Exception as e:
                print("[Sleep] Standby failed: {}".format(e))
        elif left <= 60 and not self.warned:
            self.warned = True
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Sleep timer: standby in 1 minute"), 6)


SLEEP_TIMER = _SleepTimer()


class VavooPlayerList(Screen):
    """The channel list over the video, with the mini guide of the
    highlighted channel beside it (the app's player list). Closes with
    the chosen index, or None. GREEN adds / removes a favourite."""

    GUIDE_SETTLE_MS = 300

    def __init__(self, session, channels, index, country_codes, logos,
                 country_names=None):
        Screen.__init__(self, session)
        skin = build_theme_skin("player_list")
        self._themed = skin is not None
        self.skin = skin or vavoo_theme.player_list_classic(THEME_WIDTH)
        self.channels = channels
        self.country_codes = country_codes
        # kept with a favourite added here (parental control's
        # locked countries match on the name)
        self.country_names = country_names or []
        self.logos = logos
        self.start_index = index
        self._closed = False
        self.onClose.append(self._mark_closed)
        self._favourite_keys = set()
        self["menulist"] = m2list([], themed=self._themed)
        self["guide"] = Label("")
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions",
             "InfobarChannelSelection"],
            {
                "ok": self.ok,
                "cancel": self.cancel,
                "red": self.cancel,
                "green": self.toggle_favourite,
                "up": self.move_up,
                "down": self.move_down,
                "left": self.page_up,
                "right": self.page_down,
            }, -1)
        self["list_keys"] = list_keys({"help": self.show_help,
                                       "back": self.cancel})
        self._guide_lock = threading.Lock()
        self._guide_wanted = None
        self._guide_working = False
        self._guide_timer = eTimer()
        try:
            self._guide_timer.callback.append(self._guide_tick)
        except Exception:
            self._guide_timer.timeout.connect(self._guide_tick)
        self["menulist"].onSelectionChanged.append(self._selection_changed)
        self.onLayoutFinish.append(self._fill)

    def _mark_closed(self):
        self._closed = True
        try:
            self._guide_timer.stop()
        except Exception:
            pass

    def show_help(self):
        show_keys(self.session, [
            ("OK", _("Play the channel")),
            (_("UP / DOWN"), _("Channel")),
            (_("LEFT / RIGHT"), _("Page up / down")),
            (_("GREEN"), _("Add / remove favourite")),
            (_("RED / EXIT"), _("Close")),
        ])

    def _row(self, i):
        name, url = self.channels[i]
        digits = len(str(len(self.channels)))
        text = u"{}  {}".format(str(i + 1).rjust(digits), to_text(name))
        if to_text(url) in self._favourite_keys:
            text += u"  \u2605"
        logo = self.logos[i] if i < len(self.logos) else None
        return show_list(name, url, is_channel=True, logo_url=logo,
                         display=to_string(text), themed=self._themed)

    def _fill(self):
        self._favourite_keys = vUtils.favourite_urls()
        self.rows = [self._row(i) for i in range(len(self.channels))]
        self["menulist"].l.setList(self.rows)
        if 0 <= self.start_index < len(self.rows):
            self["menulist"].moveToIndex(self.start_index)
        self._selection_changed()

    def _index(self):
        index = self["menulist"].getSelectedIndex()
        if index is None or not 0 <= index < len(self.channels):
            return None
        return index

    def ok(self):
        self.close(self._index())

    def cancel(self):
        self.close(None)

    def move_up(self):
        if self.channels:
            self["menulist"].moveToIndex(
                ((self._index() or 0) - 1) % len(self.channels))

    def move_down(self):
        if self.channels:
            self["menulist"].moveToIndex(
                ((self._index() or 0) + 1) % len(self.channels))

    def page_up(self):
        self["menulist"].pageUp()

    def page_down(self):
        self["menulist"].pageDown()

    def toggle_favourite(self):
        index = self._index()
        if index is None:
            return
        name, url = self.channels[index]
        code = self.country_codes[index] if index < len(self.country_codes) else None
        country = (self.country_names[index]
                   if index < len(self.country_names) else None)
        logo = self.logos[index] if index < len(self.logos) else None
        now_favourite = vUtils.toggle_favourite(
            name, url, country_name=country, country_code=code,
            logo=logo or None)
        if now_favourite is None:
            return
        key = to_text(url)
        if now_favourite:
            self._favourite_keys.add(key)
        else:
            self._favourite_keys.discard(key)
        self.rows[index] = self._row(index)
        self["menulist"].l.setList(self.rows)
        self["menulist"].moveToIndex(index)
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Added to favourites") if now_favourite
                         else _("Removed from favourites"), 2)

    # ---- the mini guide (the app's updateMiniGuide())

    def _request(self, index):
        name, url = self.channels[index]
        code = self.country_codes[index] if index < len(self.country_codes) else None
        return (index, name, url, code)

    def _selection_changed(self):
        index = self._index()
        if index is None:
            self["guide"].setText("")
            return
        request = self._request(index)
        if not cfg.list_epg.value or not request[3]:
            self._draw_guide(request, ("off", []))
            return
        answer = vUtils.peek_schedule(request[1], request[3])
        if answer is not None:
            self._draw_guide(request, answer)
            return
        self._draw_guide(request, None)
        self._guide_timer.stop()
        self._guide_timer.start(self.GUIDE_SETTLE_MS, True)

    def _guide_tick(self):
        index = self._index()
        if self._closed or index is None:
            return
        request = self._request(index)
        with self._guide_lock:
            self._guide_wanted = request
            start = not self._guide_working
            if start:
                self._guide_working = True
        if start:
            worker = threading.Thread(
                target=named(self._guide_work, "vv-miniguide"))
            worker.daemon = True
            worker.start()

    def _guide_work(self):
        while True:
            with self._guide_lock:
                request = self._guide_wanted
                self._guide_wanted = None
                if request is None or self._closed:
                    self._guide_working = False
                    return
            try:
                answer = vUtils.lookup_schedule(
                    request[1], request[3],
                    channel_id=_epg_channel_id(request[2]))
            except Exception as e:
                debug("Mini guide lookup failed: {}".format(e))
                answer = ("no_guide", [])
            if not self._closed:
                reactor.callFromThread(self._guide_arrived, request, answer)

    def _guide_arrived(self, request, answer):
        index = self._index()
        if self._closed or index is None or self._request(index) != request:
            return
        self._draw_guide(request, answer)

    def _draw_guide(self, request, answer):
        self["guide"].setText(to_string(mini_guide_text(request[1], answer)))


def mini_guide_text(name, answer, now=None):
    """The mini guide's text: the name, the programme on now with its
    start and minutes left, the next three, the description. `answer`
    is lookup_schedule()'s (status, programmes), or None while it is
    being looked up."""
    lines = [to_text(name)]
    if answer is None:
        lines += [u"", to_text(_("Loading..."))]
        return u"\n".join(lines)
    status, programmes = answer
    if status == "off":
        return u"\n".join(lines)
    if not programmes:
        lines += [u"", to_text(_("No programme information"))]
        return u"\n".join(lines)
    if now is None:
        now = time.time()
    rest = programmes
    current = programmes[0] if programmes[0][0] <= now < programmes[0][1] else None
    if current is not None:
        lines += [u"", u"\u25b6 {}  {}".format(
            to_text(programme_time(current[0])), to_text(current[2])),
            u"   " + to_text(_("{} min left")).format(
                max(0, int((current[1] - now) // 60)))]
        rest = programmes[1:]
    elif rest:
        lines.append(u"")
    for programme in rest[:3]:
        lines.append(u"\u00bb {}  {}".format(
            to_text(programme_time(programme[0])), to_text(programme[2])))
    if current is not None and current[3]:
        description = to_text(current[3]).strip()
        if len(description) > 400:
            description = description[:399].rstrip() + u"\u2026"
        lines += [u"", description]
    return u"\n".join(lines)


def classic_help_line(problem=u""):
    """Classic's top line in the player: the keys (the same as the
    themes' bar captions), then the proxy's state only when it is not
    right."""
    keys = to_text(_(
        "OK bar · CH± zap · GREEN fav · YELLOW source · BLUE list · "
        "EPG guide · MENU options · HELP keys"))
    if problem:
        keys += u"  |  " + to_text(problem)
    return to_string(keys)


def classic_proxy_problem():
    """"" while the proxy answers (and, on the Vavoo catalog, its token
    is fresh), else what is wrong - read in this process
    (get_proxy_status(), no HTTP)."""
    try:
        status = get_proxy_status()
        if not status:
            return _("? Proxy Unknown")
        if not status.get("listening", True):
            if status.get("booting"):
                return _("Loading channels...")
            return _("✗ Proxy Offline")
        if status.get("token_required", True) and \
                status.get("addon_sig_age", 0) >= 420:
            return _("✗ Proxy Expired")
    except Exception as e:
        debug("Proxy state not read: {}".format(e))
    return u""


class TvInfoBarShowHide():
    """
    InfoBar show/hide control – toggles both the standard Enigma2 infobar
    and the custom overlays (help + EPG) simultaneously on OK press.
    At stream start, both are shown; custom overlays auto‑hide after 5s,
    but the standard infobar stays until toggled off.
    """
    STATE_HIDDEN = 0
    STATE_HIDING = 1
    STATE_SHOWING = 2
    STATE_SHOWN = 3
    # FLAG_CENTER_DVB_SUBS = 2048
    skipToggleShow = False

    def __init__(self):
        debug("TvInfoBarShowHide.__init__ START")
        self["ShowHideActions"] = ActionMap(
            ["InfobarShowHideActions"],
            {
                "toggleShow": self.OkPressed,
                "hide": self.hide
            },
            0
        )
        self.__event_tracker = ServiceEventTracker(
            screen=self, eventmap={
                iPlayableService.evStart: self.serviceStarted})

        self.__state = self.STATE_SHOWN
        self.__locked = 0
        debug("TvInfoBarShowHide.__init__ state={}")

        # Current channel's picon, bottom-left of the screen (see
        # OVERLAY_PICON_W/H/X/Y's own comment) - populated read-only
        # from the on-disk picon cache by show_help_overlay(), same
        # "only ever read the cache, never download here" rule
        # show_list() follows for the channel list. Only
        # vavoo.ok()/play_that_shit() passes a logo_url into
        # Playstream2 today, so this stays empty/hidden for
        # Favourites/Search playback. zPosition=99 draws it above the
        # stock MoviePlayer skin's own placeholder icon in that
        # corner.
        self.channelPicon = Pixmap()
        self.channelPicon.skinAttributes = [
            ("position", "{},{}".format(OVERLAY_PICON_X, OVERLAY_PICON_Y)),
            ("size", "{},{}".format(OVERLAY_PICON_W, OVERLAY_PICON_H)),
            ("zPosition", "99"),
        ]
        self["channelPicon"] = self.channelPicon
        self["channelPicon"].hide()

        # Top overlay: controls + proxy status - full width, the
        # picon above no longer shares this bar.
        self.helpOverlay = Label("")
        self.helpOverlay.skinAttributes = [
            ("position", "0,0"),
            ("size", "{},{}".format(OVERLAY_WIDTH, OVERLAY_HEIGHT_TOP)),
            ("font", "Regular;{}".format(FONT_SIZE_TOP)),
            ("halign", "center"),
            ("valign", "center"),
            ("foregroundColor", "#00ffffff"),
            ("backgroundColor", "#80000000"),
            ("transparent", "0"),
            ("zPosition", "99")
        ]
        self["helpOverlay"] = self.helpOverlay
        self["helpOverlay"].hide()

        # EPG overlay (below the help overlay)
        self.epgOverlay = Label("")
        self.epgOverlay.skinAttributes = [
            ("position", "0,{}".format(OVERLAY_Y_EPG)),
            ("size", "{},{}".format(OVERLAY_WIDTH, OVERLAY_HEIGHT_EPG)),
            ("font", "Regular;{}".format(FONT_SIZE_EPG)),
            ("halign", "center"),
            ("valign", "center"),
            ("foregroundColor", "#00ffffff"),
            ("backgroundColor", "#80000000"),
            ("transparent", "0"),
            ("zPosition", "99")
        ]
        self["epgOverlay"] = self.epgOverlay
        self["epgOverlay"].hide()

        # Timer to update proxy status every 30s while overlays are visible
        self.proxy_update_timer = eTimer()
        try:
            self.proxy_update_timer.timeout.connect(
                self.update_proxy_status_overlay)
        except BaseException:
            self.proxy_update_timer.callback.append(
                self.update_proxy_status_overlay)

        # Timer to auto‑hide custom overlays after 5 seconds
        self.hideTimer = eTimer()
        try:
            self.hideTimer.timeout.connect(self.doTimerHide)
        except BaseException:
            self.hideTimer.callback.append(self.doTimerHide)

        # Timer for delayed start (to ensure infobar is rendered)
        self.delayed_start_timer = eTimer()
        try:
            self.delayed_start_timer.timeout.connect(self._delayed_start)
        except BaseException:
            self.delayed_start_timer.callback.append(self._delayed_start)

        # Timer to retry serviceStarted if execing is False
        self.retry_start_timer = eTimer()
        try:
            self.retry_start_timer.timeout.connect(self._retry_start)
        except BaseException:
            self.retry_start_timer.callback.append(self._retry_start)
        self.onShow.append(self.__onShow)
        self.onHide.append(self.__onHide)
        debug("TvInfoBarShowHide.__init__ END")

    def get_current_epg(self):
        """Method to be overridden by child class (Playstream2)."""
        return "EPG not available"

    def _update_overlay_picon(self):
        """Show the current channel's picon on the help overlay, if
        one is already cached - read-only, same rule show_list()
        follows for the channel list: never download synchronously
        here. Relies on the channel-list screen's own background
        preload (_preload_channel_picons()) having already fetched it
        while the user was browsing; if it hasn't yet, this channel's
        overlay just shows no picon for this viewing - no retry/
        refresh is attempted here.

        Uses ePicLoad to decode AND scale/letterbox the picon to this
        widget's own size in one step - the same mechanism
        startVavoo.decodeImage() already uses for the splash image in
        this exact file. loadPNG() (used by show_list() for the
        channel list) decodes a PNG at its own native pixel size with
        no scaling at all; that's fine there because
        MultiContentEntryPixmapAlphaTest's own size= argument scales
        list-cell content into its box, but a standalone Pixmap
        widget's setPixmap() has no such behavior - it just paints
        the pixmap's native pixels, so a picon larger than the box
        was only ever showing its clipped top-left corner, and a
        smaller one sat un-scaled instead of filling it.
        """
        try:
            logo_url = getattr(self, 'current_logo_url', None)
            if not logo_url or not cfg.logos.value:
                self["channelPicon"].hide()
                return

            cache_file = get_picon_cache_path(logo_url)
            if not cache_file or not file_exists(cache_file) \
                    or getsize(cache_file) <= 100:
                self["channelPicon"].hide()
                return

            size = self["channelPicon"].instance.size()
            picload = ePicLoad()
            scale = AVSwitch().getFramebufferScale()
            # Same setPara()/startDecode() shape as
            # startVavoo.decodeImage() - width, height, the display's
            # own aspect-correction factors, and resize_mode=1 (scale
            # to fit, preserving the image's own aspect ratio, padded
            # with the given transparent background) rather than
            # mode=0 (plain stretch).
            picload.setPara([
                size.width(), size.height(),
                scale[0], scale[1], 0, 1, '#00000000'])
            if isfile("/var/lib/dpkg/status"):
                picload.startDecode(cache_file, False)
            else:
                picload.startDecode(cache_file, 0, 0, False)
            ptr = picload.getData()
            if ptr is None:
                self["channelPicon"].hide()
                return

            self["channelPicon"].instance.setPixmap(ptr)
            self["channelPicon"].show()
            # Keep the ePicLoad instance alive for as long as its
            # decoded pixmap is on screen - same reason
            # startVavoo.decodeImage() keeps self.picload around
            # rather than letting it go out of scope right after this
            # call returns.
            self._channel_picload = picload
        except Exception as e:
            debug("Overlay picon update failed: {}".format(e))
            try:
                self["channelPicon"].hide()
            except Exception:
                pass

    def show_help_overlay(self):
        """Show custom overlays and start the auto‑hide timer."""
        debug("show_help_overlay START")
        try:
            self["helpOverlay"].setText(
                classic_help_line(classic_proxy_problem()))
            self["helpOverlay"].show()
            debug("show_help_overlay helpOverlay shown")

            # Show EPG (initially "Loading...")
            self["epgOverlay"].setText(_("Loading EPG..."))
            self["epgOverlay"].show()
            debug("show_help_overlay epgOverlay shown")

            self._update_overlay_picon()

            # Start timer to update proxy status every 30s
            if not self.proxy_update_timer.isActive():
                self.proxy_update_timer.start(30000, True)
                debug("show_help_overlay proxy_update_timer started")

            def _fetch_epg_async():
                # The fetch below can take a long time on a slow/flaky
                # network. If the user has already left this channel by
                # the time it finishes, self is a torn-down screen -
                # don't touch it any further.
                if self._closed:
                    return
                # Snapshot which channel this fetch is actually for -
                # nextitem()/previousitem() can switch channels while
                # this fetch is still in flight (a surfed-past
                # channel's slow cache-miss fetch can finish AFTER a
                # later, faster one started after it), so without
                # this, the overlay could show stale programme info
                # for whichever fetch happens to finish last instead
                # of the channel actually playing.
                fetch_url = self.url
                try:
                    epg_text = self.get_current_epg()
                except Exception as e:
                    print("[Show Help] Async EPG fetch error: " + str(e))
                    return
                if self._closed:
                    return

                def _apply_epg_text():
                    try:
                        if (not self._closed and self["helpOverlay"].visible
                                and self.url == fetch_url):
                            self["epgOverlay"].setText(epg_text)
                            debug("show_help_overlay EPG updated: {}".format(
                                epg_text[:50]))
                    except Exception as e:
                        debug("Applying EPG overlay text failed: {}".format(e))
                reactor.callFromThread(_apply_epg_text)

            _epg_fetch_thread = threading.Thread(
                target=named(_fetch_epg_async, "vv-bar"))
            _epg_fetch_thread.daemon = True
            _epg_fetch_thread.start()

        except Exception as e:
            print("[Show Help] Error: " + str(e))
        debug("show_help_overlay END")

    def update_proxy_status_overlay(self):
        """The top line again, with the proxy's state now."""
        if self["helpOverlay"].visible:
            try:
                self["helpOverlay"].setText(
                    classic_help_line(classic_proxy_problem()))
            except Exception as e:
                print("[Update Proxy Overlay] Error: " + str(e))

    def hide_help_overlay(self):
        """Hide both overlays and stop timer"""
        debug("hide_help_overlay START")
        self.hideTimer.stop()
        self.proxy_update_timer.stop()
        if self["helpOverlay"].visible:
            self["helpOverlay"].hide()
            self["epgOverlay"].hide()
            self["channelPicon"].hide()
            debug("hide_help_overlay overlays hidden")
        debug("hide_help_overlay END")

    def __onShow(self):
        debug("__onShow called, old state={}".format(self.__state))
        self.__state = self.STATE_SHOWN
        debug("__onShow new state={}".format(self.__state))

    def __onHide(self):
        debug("__onHide called, old state={}".format(self.__state))
        self.__state = self.STATE_HIDDEN
        debug("__onHide new state={}".format(self.__state))

    def doShow(self):
        debug("doShow START, state={}".format(self.__state))
        self.hideTimer.stop()
        self.show()
        self.startHideTimer()
        debug("doShow END")

    def doHide(self):
        debug("doHide START, state={}".format(self.__state))
        self.hideTimer.stop()
        self.hide()
        self.hide_help_overlay()
        self.startHideTimer()
        debug("doHide END")

    def startHideTimer(self):
        debug(
            "startHideTimer START, state={}, locked={}".format(
                self.__state,
                self.__locked))
        if self.__state == self.STATE_SHOWN and not self.__locked:
            self.hideTimer.stop()
            self.hideTimer.start(10000, True)
            debug("startHideTimer timer started (5s)")
        else:
            debug(
                "startHideTimer NOT starting: state={}, locked={}".format(
                    self.__state, self.__locked))
        debug("startHideTimer END")

    def doTimerHide(self):
        if self._closed:
            return
        debug("doTimerHide START, state={}".format(self.__state))
        self.hideTimer.stop()
        if self.__state == self.STATE_SHOWN:
            debug("doTimerHide hiding infobar and overlays")
            self.hide()
            self.hide_help_overlay()
        else:
            debug("doTimerHide state is HIDDEN, not hiding")
        debug("doTimerHide END")

    def toggleShow(self):
        debug(
            "toggleShow START, state={}, skipToggleShow={}".format(
                self.__state,
                self.skipToggleShow))
        if not self.skipToggleShow:
            if self.__state == self.STATE_HIDDEN:
                debug("toggleShow calling doShow()")
                self.doShow()
            else:
                debug("toggleShow calling doHide()")
                self.doHide()
        else:
            debug("toggleShow skipToggleShow is True, resetting")
            self.skipToggleShow = False
        debug("toggleShow END")

    def lockShow(self):
        debug("lockShow START")
        try:
            self.__locked += 1
        except BaseException:
            self.__locked = 0
        if self.execing:
            self.show()
            self.hideTimer.stop()
            self.skipToggleShow = False
        debug("lockShow END, locked={}".format(self.__locked))

    def unlockShow(self):
        debug("unlockShow START")
        try:
            self.__locked -= 1
        except BaseException:
            self.__locked = 0
        if self.__locked < 0:
            self.__locked = 0
        if self.execing:
            self.startHideTimer()
        debug("unlockShow END, locked={}".format(self.__locked))

    def _do_show_all(self):
        """Show infobar and overlays, start hide timer"""
        debug("_do_show_all CALLED")
        self.doShow()                  # Shows infobar
        self.show_help_overlay()       # Shows overlays
        self.delayed_start_timer.start(
            500, True)  # Start hide timer after 500ms
        debug("_do_show_all END")

    def _retry_start(self):
        """Retry serviceStarted if execing is False"""
        debug("_retry_start CALLED")
        self.retry_start_timer.stop()
        if self.execing:
            debug("_retry_start execing is now True, calling _do_show_all()")
            self._do_show_all()
        else:
            debug("_retry_start execing still False, will retry in 500ms")
            self.retry_start_timer.start(500, True)

    def _delayed_start(self):
        """Delayed start callback - starts the hide timer after infobar is rendered"""
        debug("_delayed_start CALLED")
        self.delayed_start_timer.stop()
        debug("_delayed_start starting hideTimer (5s)")
        self.hideTimer.start(5000, True)
        debug("_delayed_start END")

    def serviceStarted(self):
        debug("========== serviceStarted CALLED ==========")
        debug("serviceStarted execing={}".format(self.execing))
        if self.execing:
            debug("serviceStarted execing is True, calling _do_show_all()")
            self._do_show_all()
        else:
            debug("serviceStarted execing is False, will retry in 500ms")
            self.retry_start_timer.start(500, True)
        debug("========== serviceStarted END ==========")

    def OkPressed(self):
        """Toggle both infobar and overlays together"""
        debug("========== OkPressed CALLED ==========")
        debug(
            "OkPressed helpOverlay.visible={}".format(
                self["helpOverlay"].visible))
        if self["helpOverlay"].visible:
            debug("OkPressed hiding overlays")
            self.hide_help_overlay()
        else:
            debug("OkPressed showing overlays")
            self.show_help_overlay()
        debug("OkPressed calling toggleShow()")
        self.toggleShow()
        debug("========== OkPressed END ==========")


class Playstream2(
        InfoBarBase,
        InfoBarMenu,
        InfoBarSeek,
        InfoBarAudioSelection,
        InfoBarSubtitleSupport,
        InfoBarNotifications,
        TvInfoBarShowHide,
        Screen):
    STATE_IDLE = 0
    STATE_PLAYING = 1
    STATE_PAUSED = 2
    ENABLE_RESUME_SUPPORT = True
    ALLOW_SUSPEND = True
    screen_timeout = 5000

    def __init__(
            self,
            session,
            name,
            url,
            index,
            item,
            cat_list,
            country_code=None,
            country_codes=None,
            logo_url=None,
            logo_urls=None,
            country_name=None,
            country_names=None,
            hand_back=False):
        Screen.__init__(self, session)
        self.session = session
        init_notification_system(session)
        self.skinName = 'MoviePlayer'
        # Opened from a screen with a preview window: carry on with the
        # stream already playing there (if it is this channel) and,
        # when closing, leave the channel playing for that window
        # instead of stopping it - see _NowPlaying.
        self.hand_back = hand_back
        self._inherit_pending = True
        self.country_name = country_name
        # Parallel to cat_list like country_codes (Favourites / Recent
        # mix countries) - for "Recently watched" and parental control.
        self.country_names = country_names
        # The app's info bar in a modern theme (vavoo_theme.player_bar);
        # Classic keeps the MoviePlayer bar and the overlays at the top.
        bar_skin = build_theme_skin("player", clock_24=clock_24())
        self._bar_themed = bar_skin is not None
        if self._bar_themed:
            self.skin = bar_skin
            self.skinName = "VavooPlayer"
            for widget in PLAYER_BAR_LABELS:
                self[widget] = Label("")
            self["logo"] = Pixmap()
            self["info_box"] = Pixmap()
            self["progress_track"] = Pixmap()
            self["progress"] = ProgressBar()
            self.onLayoutFinish.append(self._bar_layout_finished)
        # A channel number being typed (0 = none), the channel before
        # the current one (RECALL / 0).
        self._typed = 0
        self._previous_index = None
        self._digit_timer = eTimer()
        try:
            self._digit_timer.callback.append(self._commit_digits)
        except Exception:
            self._digit_timer.timeout.connect(self._commit_digits)
        self._info_shown = False
        self._bar_epg_for = None
        self._channel_logo_picload = None
        # Pause Live TV (the app's timeshift): the buffer being
        # recorded, the state (None = live, "paused" = live paused and
        # recording, "behind" / "behind_paused" = playing the buffer)
        # and where in it (seconds; it moves on from _shift_clock).
        self._shift = None
        self._shift_state = None
        self._shift_pos = 0.0
        self._shift_clock = None
        self._shift_waits = 0
        # Why a PAUSE is not recorded (SHIFT_WHY), None when it is or
        # Pause Live TV is off: then PLAY goes on live, and it is said.
        self._shift_why = None
        self._shift_tick = eTimer()
        self._shift_seek = eTimer()
        for timer, function in ((self._shift_tick, self._on_shift_tick),
                                (self._shift_seek, self._shift_seek_now)):
            try:
                timer.callback.append(function)
            except Exception:
                timer.timeout.connect(function)

        self.stream_running = False
        self.is_streaming = False
        # Set once cancel() starts closing this screen, so a background
        # EPG fetch already in flight from a channel the user has since
        # left (show_help_overlay's _fetch_epg_async) can notice and
        # stop touching self instead of running against a torn-down
        # screen.
        self._closed = False
        ACTIVE["player"] = self
        self.currentindex = index
        self.item = item
        self.itemscount = len(cat_list)
        self.list = cat_list
        self.country_code = country_code
        # Parallel to cat_list, one country_code per entry - only
        # VavooFavourites passes this (its list can mix channels from
        # several countries, unlike every other caller's single-
        # country list). nextitem()/previousitem() use it to keep
        # self.country_code correct as the user channel-surfs, so EPG
        # lookups (get_current_epg()) stay matched to the right
        # country instead of staying stuck on whichever country the
        # very first channel happened to belong to.
        self.country_codes = country_codes
        self.current_logo_url = logo_url
        # Parallel to cat_list, like country_codes above - only
        # vavoo.ok()/play_that_shit() passes this today (the main
        # channel-list playback path). Favourites/Search leave it
        # None, so self.current_logo_url simply stays None for those
        # and the overlay picon area just stays empty for them.
        self.logo_urls = logo_urls
        self.name = name
        self.url = url.replace('%0a', '').replace('%0A', '')
        self.state = self.STATE_PLAYING
        self.srefInit = self.session.nav.getCurrentlyPlayingServiceReference()

        for x in (
            InfoBarBase,
            InfoBarMenu,
            InfoBarSeek,
            InfoBarAudioSelection,
            InfoBarSubtitleSupport,
            InfoBarNotifications,
            TvInfoBarShowHide
        ):
            x.__init__(self)

        # Every function on a key of its own, the same in every theme
        # and on every image (keymap.xml; the bar shows these captions,
        # Classic's top line lists them): OK the bar, EXIT / BACK / RED
        # back (behind live: to live first), UP / DOWN / CH± zap, LEFT /
        # RIGHT 10 s behind live, GREEN favourite, YELLOW source, BLUE
        # the channel list, MENU the options, INFO / EPG the guide,
        # PLAY / PAUSE pause live, << >> 30 s, REC record, digits.
        own_keys = dict((str(d), (lambda n: lambda: self.key_digit(n))(d))
                        for d in range(10))
        own_keys.update({
            "ok": self.OkPressed,
            "exit": self.back,
            "red": self.back,
            "stop": self.leavePlayer,
            "up": self.nextitem,
            "down": self.previousitem,
            "channelUp": self.nextitem,
            "channelDown": self.previousitem,
            "left": self.key_left,
            "right": self.key_right,
            "green": self.toggle_favourite,
            "yellow": self.chooseStreamSource,
            "blue": self.list_key,
            "menu": self.mainMenu,
            "info": self.open_guide,
            "epg": self.open_guide,
            "audio": lambda: self._call_infobar("audioSelection"),
            "subtitle": lambda: self._call_infobar("subtitleSelection"),
            "record": self.toggle_record,
            "playpause": self.playpauseService,
            "forward": self.seekFwd,
            "rewind": self.seekBack,
            "favourites": self.favourites_key,
            "help": self.show_help,
        })
        self['vavoo_keys'] = player_keys(own_keys)

        # The image's own key names: only used where keymap.xml could
        # not be loaded, or for a key it does not name. Includes the
        # names images gave MENU and PAUSE / PLAY (OpenATV 7: showMenu,
        # playpauseService), which before reached Enigma2's main menu or
        # its seek keys - off while a live stream plays.
        fallback = {
                "showMenu": self.mainMenu,
                "mainMenu": self.mainMenu,
                "menu": self.mainMenu,
                "stop": self.leavePlayer,
                # REC: record this channel / stop (the app's Record)
                "instantRecord": self.toggle_record,
                "cancel": self.back,
                "channelDown": self.previousitem,
                "channelUp": self.nextitem,
                "down": self.previousitem,
                "up": self.nextitem,
                "back": self.back,
                "epg": self.open_guide,
                "info": self.open_guide,
                "red": self.back,
                "green": self.toggle_favourite,
                "yellow": self.chooseStreamSource,
                "blue": self.list_key,
                "historyBack": self.recall,
                # behind live (Pause Live TV): 10 s back / on
                "left": self.key_left,
                "right": self.key_right,
                "1": lambda: self.key_digit(1),
                "2": lambda: self.key_digit(2),
                "3": lambda: self.key_digit(3),
                "4": lambda: self.key_digit(4),
                "5": lambda: self.key_digit(5),
                "6": lambda: self.key_digit(6),
                "7": lambda: self.key_digit(7),
                "8": lambda: self.key_digit(8),
                "9": lambda: self.key_digit(9),
                "0": lambda: self.key_digit(0),
        }
        self['actions'] = ActionMap(
            [
                'ColorActions',
                'InfoBarMenuActions',
                'InfobarMenuActions',
                'MenuActions',
                'MoviePlayerActions',
                'MovieSelectionActions',
                'MediaPlayerActions',
                'OkCancelActions',
                'InfobarShowHideActions',
                'InfobarActions',
                'DirectionActions',
                'NumberActions',
                'InfobarChannelSelection',
                'InfobarInstantRecord'
            ], fallback, PLAYER_KEYS_PRIO + 1)
        # (key lists of their own, so that their colours, arrows and
        # digits find no action: OpenATV has RED / YELLOW / BLUE on the
        # press in EPGSelectActions, ColorActions on the release - one
        # press ran twice; LEFT / RIGHT on the release in the seek
        # lists moved again after DirectionActions had moved)
        self['epg_keys'] = info_page_keys(fallback, PLAYER_KEYS_PRIO + 1)

        def nothing():
            return None

        seek_keys = {
            "pauseService": self.pauseService,
            "playpauseService": self.playpauseService,
            # (OpenPLi's PLAY; OpenATV's OK press too)
            "unPauseService": self._resume_if_paused,
            "seekFwd": self.seekFwd,
            "seekBack": self.seekBack,
            "left": nothing, "right": nothing,
            "up": nothing, "down": nothing,
        }
        for digit in (1, 3, 4, 6, 7, 9):
            seek_keys["seekdef:%d" % digit] = \
                (lambda d: lambda: self.key_digit(d))(digit)
        self['seek_keys'] = ActionMap(
            ['InfobarSeekActions', 'InfobarArrowSeekActions'], seek_keys,
            PLAYER_KEYS_PRIO + 1)

        self.__event_tracker = ServiceEventTracker(
            screen=self,
            eventmap={
                iPlayableService.evEOF: self.__evEOF,
                # iPlayableService.evStart: self.__serviceStarted,
                # iPlayableService.evStopped: self.__evStopped,
            }
        )

        try:
            for screen in self.session.dialog_stack:
                if hasattr(screen[0], 'proxy_monitor_timer'):
                    screen[0].proxy_monitor_timer.stop()
                    print("[Playstream2] Stopped proxy monitor timer")
                if hasattr(screen[0], 'proxy_watchdog_timer'):
                    screen[0].proxy_watchdog_timer.stop()
                    print("[Playstream2] Stopped proxy watchdog timer")
        except Exception as e:
            print("[Playstream2] Error stopping timers: {}".format(e))

        self.eof_recovery_timer = eTimer()
        # Handle for restartAfterEOF()'s second-stage reactor.callLater -
        # see _do_restart_after_eof()/cancel() for why this needs to be
        # cancellable too, not just eof_recovery_timer itself.
        self._eof_restart_call = None

        self.onFirstExecBegin.append(lambda: self.startStream())
        self.onClose.append(self.cancel)

    def showIMDB(self):
        # get_current_epg() can block for well over a minute when the
        # EPG feed fetch stalls (e.g. flaky DNS) - the getUrl() timeout
        # passed to it only bounds the socket connect/read, not name
        # resolution. Run it off the main/reactor thread so a stall
        # here doesn't freeze the whole GUI, and marshal the actual
        # IMDb-opening (touches self.session) back onto the reactor.
        if not cfg.epg_enabled.value:
            print("[IMDB] No EPG available for current channel")
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("No programme info available"), 3)
            return

        def _openForEpgText(epg_text, fetch_url):
            if self._closed or self.url != fetch_url:
                # Either torn down, or the user has already changed
                # channel since INFO was pressed - this fetch's result
                # belongs to a channel that isn't playing any more,
                # opening IMDb/TMDB for it would search the wrong
                # programme.
                return
            try:
                # get_current_epg() returns several distinct "EPG ..."
                # error strings ("EPG not available (no country code)",
                # "EPG not available (ID not found)", "EPG parsing
                # error", "EPG error", ...), not just "EPG not
                # available" - matching only that one exact string let
                # every other error variant fall through and get passed
                # to returnIMDB() as a search title instead of showing
                # "No programme info available".
                if epg_text and not epg_text.startswith(
                        "EPG ") and epg_text != "No programme found":
                    if " - " in epg_text:
                        title = epg_text.split(" - ")[0].strip()
                        if " " in title and title[2] == ":":
                            parts = title.split(" ", 1)
                            if len(parts) > 1:
                                title = parts[1].strip()
                    else:
                        title = epg_text

                    print("[IMDB] Searching for: %s" % title)

                    if returnIMDB(title, self.session):
                        print(
                            '[Playstream2] TMDB/IMDb opened for programme: %s' %
                            title)
                    else:
                        print('[Playstream2] No TMDB/IMDb plugin found')
                        if NOTIFICATION_AVAILABLE:
                            print('notify started')
                            quick_notify(_("No IMDb/TMDB plugin found"), 4)
                else:
                    print("[IMDB] No EPG available for current channel")
                    if NOTIFICATION_AVAILABLE:
                        print('notify started')
                        quick_notify(_("No programme info available"), 3)

            except Exception as e:
                print('[Playstream2] Error opening IMDb/TMDB: %s' % e)

        def _fetchEpgThenOpen():
            # Mirrors _fetch_epg_async()'s _closed check above - the
            # user may have already left this channel by the time this
            # slow fetch finishes.
            if self._closed:
                return
            fetch_url = self.url
            try:
                epg_text = self.get_current_epg()
            except Exception as e:
                print('[Playstream2] Error fetching EPG for IMDb: %s' % e)
                epg_text = ""
            if self._closed:
                return
            reactor.callFromThread(_openForEpgText, epg_text, fetch_url)

        epg_thread = threading.Thread(
            target=named(_fetchEpgThenOpen, "vv-imdb"))
        epg_thread.daemon = True
        epg_thread.start()

    def _update_country_code_for_index(self, i):
        if self.country_codes is not None and 0 <= i < len(self.country_codes):
            self.country_code = self.country_codes[i]
        if self.country_names is not None and 0 <= i < len(self.country_names):
            self.country_name = self.country_names[i]

    def _update_logo_url_for_index(self, i):
        if self.logo_urls is not None and 0 <= i < len(self.logo_urls):
            self.current_logo_url = self.logo_urls[i]

    def nextitem(self):
        """Switch to next channel"""
        if self.itemscount:
            self._zap_dir = 1
            self.zap_to((int(self.currentindex) + 1) % self.itemscount)

    def previousitem(self):
        """Switch to previous channel"""
        if self.itemscount:
            self._zap_dir = -1
            self.zap_to((int(self.currentindex) - 1) % self.itemscount)

    def _country_name_at(self, i):
        if self.country_names is not None and 0 <= i < len(self.country_names):
            return self.country_names[i]
        return self.country_name

    def play_channel(self, channel):
        """Go to `channel` (a reminder's "watch it"): zap to it if it is
        in this player's list, else add it at the end first."""
        url = channel.get("url")
        for index, row in enumerate(self.list):
            if row[0][1] == url:
                self.zap_to(index)
                return
        count = len(self.list)
        if self.country_codes is None:
            self.country_codes = [self.country_code] * count
        if self.country_names is None:
            self.country_names = [self.country_name] * count
        if self.logo_urls is None:
            self.logo_urls = [None] * count
        self.list.append([(to_string(channel.get("name")), to_string(url))])
        self.country_codes.append(channel.get("country_code"))
        self.country_names.append(channel.get("country_name"))
        self.logo_urls.append(channel.get("logo") or None)
        self.itemscount = len(self.list)
        self.zap_to(count)

    def zap_to(self, i):
        """Play the channel at index `i` of the list (a locked
        country's channel after its PIN, once per player)."""
        if not 0 <= i < self.itemscount or i == int(self.currentindex):
            return
        country = self._country_name_at(i)
        name = self.list[i][0][0]
        if vavoo_store.needs_pin_for_channel(name, country):
            # a locked country's or an adult channel: the PIN first
            # (then open for 15 minutes, vavoo_store)
            ask_pin(self.session, self, lambda: self.zap_to(i))
            return
        self._previous_index = int(self.currentindex)
        self._shift_end(replay=False)
        self.stopStream(restore_original=False)
        self.currentindex = i
        item = self.list[i][0]
        self.name = item[0]
        self.url = item[1]
        self._update_country_code_for_index(i)
        self._update_logo_url_for_index(i)
        self.startStream()
        self._schedule_prefetch(getattr(self, "_zap_dir", 1))
        self._zap_dir = 1                 # (numbers, RECALL, the lists: +1)

    PREFETCH_AFTER_MS = 3000

    def _schedule_prefetch(self, direction):
        """3 s after a zap (the viewer has stopped on this channel for a
        moment), the proxy resolves the next channel in the same
        direction (VavooProxy.prefetch(): Geil only), so CH+ / CH-
        again starts it without waiting for the network."""
        self._prefetch_dir = direction
        timer = getattr(self, "_prefetch_timer", None)
        if timer is None:
            timer = self._prefetch_timer = eTimer()
            try:
                timer.callback.append(self._prefetch_next)
            except Exception:
                timer.timeout.connect(self._prefetch_next)
        timer.stop()
        timer.start(self.PREFETCH_AFTER_MS, True)

    def _prefetch_next(self):
        if getattr(self, "_closed", False) or not self.itemscount or \
                getattr(self, "_shift_state", None) is not None:
            return
        index = (int(self.currentindex) + getattr(self, "_prefetch_dir", 1)) % self.itemscount
        channel_id = stream_channel_id(self.list[index][0][1])
        if not channel_id:
            return

        def _work():
            try:
                vavoo_proxy.proxy.prefetch(channel_id)
            except Exception as e:
                debug("Prefetch not done: {}".format(e))

        worker = threading.Thread(target=named(_work, "vv-prefetch"))
        worker.daemon = True
        worker.start()

    def recall(self):
        """RECALL / 0: back to the channel before (the app's Recall)."""
        if self._previous_index is not None:
            self.zap_to(self._previous_index)

    # ---- channel numbers (the app's onDigitKey)

    def key_digit(self, digit):
        if not self._typed and digit == 0:
            # 0 first: the channel before, as on a receiver's remote
            self.recall()
            return
        self._typed = min(self._typed * 10 + digit, 99999)
        self._show_bar_now()
        self._digit_timer.stop()
        if self._typed * 10 > self.itemscount:
            # no further digit can make a channel number: no waiting
            self._commit_digits()
        else:
            self._digit_timer.start(1500, True)

    def _commit_digits(self):
        self._digit_timer.stop()
        number, self._typed = self._typed, 0
        if 1 <= number <= self.itemscount and number - 1 != int(self.currentindex):
            self.zap_to(number - 1)
        else:
            self._fill_bar()

    # ---- favourites

    def _is_favourite(self):
        try:
            return vUtils.is_favourite(self.name, self.url)
        except Exception:
            return False

    def toggle_favourite(self):
        """GREEN: the playing channel in / out of the favourites."""
        now_favourite = vUtils.toggle_favourite(
            self.name, self.url, country_name=self.country_name,
            country_code=self.country_code,
            logo=getattr(self, "current_logo_url", None) or None)
        if now_favourite is None:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Could not update favourites"), 3)
            return
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Added to favourites") if now_favourite
                         else _("Removed from favourites"), 2)
        self._fill_bar()

    # ---- the info bar (modern themes) and OK / INFO

    def _bar_layout_finished(self):
        hidden = ["info_box", "stream_info", "progress_track", "progress",
                  "logo"]
        for widget in hidden:
            try:
                self[widget].hide()
            except Exception:
                pass

    def _bar_visible(self):
        if self._bar_themed:
            return bool(getattr(self, 'shown', False))
        try:
            return self["helpOverlay"].visible
        except Exception:
            return False

    def OkPressed(self):
        """OK: show / hide the bar (Classic: the infobar and the top
        line), as everywhere in Enigma2. Paused: play on. A channel
        number being typed: go there."""
        if self._typed:
            self._commit_digits()
            return
        if self._shift_state in ("paused", "behind_paused") or \
                getattr(self, "seekstate", None) == self.SEEK_STATE_PAUSE:
            self.unPauseService()
            return
        TvInfoBarShowHide.OkPressed(self)

    def key_left(self):
        """LEFT: behind live, 10 seconds back (live: nothing to move)."""
        if self._shift_behind():
            self.shift_seek(-10)

    def key_right(self):
        if self._shift_behind():
            self.shift_seek(10)

    def list_key(self):
        """BLUE: the channel list over the video (with the mini guide)."""
        if self._closed:
            return
        if self._bar_visible():
            self.hide_help_overlay()
            self.doHide()
        self.open_channel_list()

    def _show_bar_now(self):
        if self._bar_visible():
            self._fill_bar()
        else:
            TvInfoBarShowHide.OkPressed(self)

    def show_help_overlay(self):
        if not self._bar_themed:
            return TvInfoBarShowHide.show_help_overlay(self)
        self._fill_bar()

    def hide_help_overlay(self):
        TvInfoBarShowHide.hide_help_overlay(self)
        if self._bar_themed and self._info_shown:
            self._info_shown = False
            for widget in ("info_box", "stream_info"):
                try:
                    self[widget].hide()
                except Exception:
                    pass

    def _fill_bar(self):
        """The bar's texts for the channel playing (or the one a typed
        number goes to): the app's updateInfo()."""
        if not self._bar_themed or self._closed:
            return
        try:
            count = self.itemscount
            index = int(self.currentindex)
            if self._typed:
                number = u"{}-".format(self._typed)
                target = self._typed - 1
                name = (u"\u2192 " + to_text(self.list[target][0][0])
                        if 0 <= target < count else u"\u2014")
            else:
                number = (u"{}/{}".format(index + 1, count) if count <= 9999
                          else u"{}".format(index + 1))
                name = to_text(self.name)
            self["number"].setText(to_string(number))
            self["name"].setText(to_string(name))
            favourite = self._is_favourite()
            keys = {
                "key_red": to_text(_("Back")),
                "key_green": (u"\u2605 " if favourite else u"\u2606 ") +
                to_text(_("Fav")),
                "key_yellow": to_text(_("Source")),
                "key_blue": to_text(_("List")),
                # (the remote's key, then what it does; AUDIO and 0
                # recall work too - HELP lists them, the bar does not)
                "key_options": u"MENU " + to_text(_("Options")),
                "key_list": u"EPG " + to_text(_("Guide")),
            }
            for widget, text in keys.items():
                self[widget].setText(to_string(text))
            self["status"].setText(to_string(self._status_text()))
            self._set_logo()
            self._bar_epg()
        except Exception as e:
            debug("Player bar not filled: {}".format(e))

    def _status_text(self):
        parts = []
        if RECORDINGS.recording_of(self.url) is not None:
            parts.append(u"\u25cf REC")
        shift = self._shift_text()
        if shift:
            parts.append(shift)
        group_id = self._current_group_channel_id()
        if group_id:
            try:
                data = vavoo_proxy.proxy.get_group_sources(group_id) or {}
                members = data.get("members") or []
                current = data.get("current")
                if len(members) > 1:
                    label = next((m.get("label") for m in members
                                  if m.get("id") == current), None)
                    parts.append(to_text(_("Source: {}")).format(
                        to_text(label)) if label else
                        to_text(_("{} sources")).format(len(members)))
            except Exception as e:
                debug("Player bar: sources not read: {}".format(e))
        left = SLEEP_TIMER.minutes_left()
        if left is not None:
            parts.append(u"\u263e " + to_text(_("{} min")).format(left))
        return u"  \u00b7  ".join(parts)

    def _set_logo(self):
        """The channel's picon when it is cached, else its country's
        flag - scaled into the logo box (as _update_overlay_picon())."""
        path = None
        logo_url = getattr(self, 'current_logo_url', None)
        if logo_url and cfg.logos.value:
            cache_file = get_picon_cache_path(logo_url)
            if cache_file and file_exists(cache_file) and getsize(cache_file) > 100:
                path = cache_file
        if path is None and self.country_code:
            flag = join(PLUGIN_PATH, "skin", "cowntry",
                        "%s.png" % to_text(self.country_code).lower())
            if isfile(flag):
                path = flag
        if path is None:
            self["logo"].hide()
            return
        try:
            size = self["logo"].instance.size()
            picload = ePicLoad()
            scale = AVSwitch().getFramebufferScale()
            picload.setPara([size.width(), size.height(), scale[0], scale[1],
                             0, 1, '#00000000'])
            if IS_DREAMOS:
                picload.startDecode(path, False)
            else:
                picload.startDecode(path, 0, 0, False)
            ptr = picload.getData()
            if ptr is None:
                self["logo"].hide()
                return
            self["logo"].instance.setPixmap(ptr)
            self["logo"].show()
            self._channel_logo_picload = picload
        except Exception as e:
            debug("Player logo not shown: {}".format(e))

    def _bar_epg(self):
        """The programme lines, progress and minutes left - from memory
        when the guide is there, else looked up in the background (the
        bar shows the country meanwhile)."""
        if not self.country_code:
            self._draw_bar_epg(("no_country", None, None))
            return
        answer = vUtils.peek_now_next(self.name, self.country_code)
        if answer is not None:
            self._draw_bar_epg(answer)
            return
        self._draw_bar_epg(("loading", None, None))
        wanted = self.url
        if self._bar_epg_for == wanted:
            return
        self._bar_epg_for = wanted
        name, country_code = self.name, self.country_code
        channel_id = _epg_channel_id(self.url)

        def _work():
            try:
                found = vUtils.lookup_now_next(
                    name, country_code, channel_id=channel_id)
            except Exception as e:
                debug("Player bar EPG lookup failed: {}".format(e))
                found = ("no_guide", None, None)

            def _apply():
                self._bar_epg_for = None
                if not self._closed and self.url == wanted:
                    self._draw_bar_epg(found)
            reactor.callFromThread(_apply)

        worker = threading.Thread(target=named(_work, "vv-bar"))
        worker.daemon = True
        worker.start()

    def _draw_bar_epg(self, answer):
        status, current, following = answer
        now = time.time()
        fallback = to_text(self.country_name or "")
        if status == "loading":
            fallback = to_text(_("Loading programme guide..."))
        now_text, next_text, left, pct = fallback, u"", u"", None
        if current is not None:
            now_text = u"\u25b6 {}  {}".format(
                to_text(programme_time(current[0])), to_text(current[2]))
            start, stop = current[0], current[1]
            if stop > start and start <= now < stop:
                pct = max(1, min(100, int(100 * (now - start) / (stop - start))))
                left = u"+" + to_text(_("{} min")).format(
                    int((stop - now + 59) // 60))
        if following is not None:
            next_text = u"\u00bb {}  {}".format(
                to_text(programme_time(following[0])), to_text(following[2]))
        self["now"].setText(to_string(now_text))
        self["next"].setText(to_string(next_text))
        self["left"].setText(to_string(left))
        if pct is None:
            self["progress"].hide()
            self["progress_track"].hide()
        else:
            self["progress"].setValue(pct)
            self["progress"].show()
            self["progress_track"].show()

    # ---- options (MENU)

    def mainMenu(self):
        """MENU: the player's options (InfoBarMenu would open Enigma2's
        main menu here)."""
        self.open_options()

    def showMainMenu(self):
        """InfoBarMenu's MENU on OpenATV 7 (mainMenu() elsewhere): the
        options too, should its key list ever get MENU first."""
        self.open_options()

    def _source_count(self):
        group_id = self._current_group_channel_id()
        if not group_id:
            return 1
        try:
            data = vavoo_proxy.proxy.get_group_sources(group_id) or {}
            return len(data.get("members") or [])
        except Exception:
            return 1

    def open_options(self):
        entries = [
            (_("Remove from favourites") if self._is_favourite()
             else _("Add to favourites"), "fav"),
            (_("Audio track"), "audio"),
            (_("Subtitles"), "subtitles"),
        ]
        if self._source_count() > 1:
            entries.append((_("Source"), "source"))
        entries.append((_("Aspect ratio"), "aspect"))
        left = SLEEP_TIMER.minutes_left()
        entries.append((
            _("Sleep timer") if left is None
            else "{}: {}".format(_("Sleep timer"), _("{} min").format(left)),
            "sleep"))
        recording = RECORDINGS.recording_of(self.url)
        if recording is not None:
            seconds = int(recording.duration)
            entries.append((to_string(u"{}: \u25cf {}:{:02d}".format(
                to_text(_("Record")), seconds // 60, seconds % 60)), "record"))
        else:
            entries.append((_("Record"), "record"))
        entries.append((_("Stream Info"), "info"))
        entries.append((_("Programme guide"), "guide"))
        # (short: the panel is the channel list's width)
        entries.append((_("IMDb / TMDB"), "imdb"))
        open_action_menu(self.session, _("Options"), entries, self._on_option,
                         layout="player_menu")

    def _on_option(self, key):
        if self._closed:
            return
        if key == "fav":
            self.toggle_favourite()
        elif key == "audio":
            self._call_infobar("audioSelection")
        elif key == "subtitles":
            self._call_infobar("subtitleSelection")
        elif key == "source":
            self.chooseStreamSource()
        elif key == "aspect":
            self._choose_aspect()
        elif key == "sleep":
            self._choose_sleep()
        elif key == "info":
            self.show_stream_info()
        elif key == "imdb":
            self.showIMDB()
        elif key == "guide":
            self.open_guide()
        elif key == "record":
            self.toggle_record()

    def open_guide(self):
        """Options → Programme guide: the grid over the video, of this
        player's channels, from the one playing."""
        channels = []
        codes = self.country_codes
        for index, row in enumerate(self.list):
            channels.append({
                "name": row[0][0], "url": row[0][1],
                "country_name": self._country_name_at(index),
                "country_code": codes[index] if codes and index < len(codes)
                else self.country_code})
        self.session.openWithCallback(
            self._on_guide_closed, VavooGuide, channels,
            int(self.currentindex), self.country_name or "",
            over_player=True, on_zap=self._guide_zap)

    def _guide_zap(self, direction):
        """CH± in the guide over the video: zap here, tell it where."""
        if direction > 0:
            self.nextitem()
        else:
            self.previousitem()
        return int(self.currentindex)

    def _on_guide_closed(self, result=None):
        if self._closed or not result or result[0] != "watch":
            return
        if result[1] != int(self.currentindex):
            self.zap_to(result[1])

    def _call_infobar(self, method):
        """Enigma2's own audio / subtitle selection (from the InfoBar
        classes this player is built from)."""
        function = getattr(self, method, None)
        try:
            if function is None:
                raise AttributeError(method)
            function()
        except Exception as e:
            print("[Playstream2] {} not available: {}".format(method, e))
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Not available on this receiver"), 3)

    def _choose_aspect(self):
        try:
            current = AVSwitch().getAspectRatioSetting()
        except Exception:
            current = None
        entries = []
        for value, label in PLAYER_ASPECTS:
            text = label
            try:
                if current is not None and int(current) == value:
                    text = "{} {}".format(label, _("(current)"))
            except (TypeError, ValueError):
                pass
            entries.append((text, value))

        def _picked(value):
            try:
                AVSwitch().setAspectRatio(value)
            except Exception as e:
                print("[Playstream2] Aspect ratio not set: {}".format(e))
                if NOTIFICATION_AVAILABLE:
                    quick_notify(_("Not available on this receiver"), 3)
        open_action_menu(self.session, _("Aspect ratio"), entries, _picked,
                         layout="player_menu")

    def _choose_sleep(self):
        entries = [(_("Off"), 0)] + [
            (_("{} min").format(minutes), minutes)
            for minutes in SLEEP_CHOICES]

        def _picked(minutes):
            SLEEP_TIMER.set(self.session, minutes)
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Sleep timer: {} min").format(minutes)
                             if minutes else _("Sleep timer off"), 3)
            self._fill_bar()
        open_action_menu(self.session, _("Sleep timer"), entries, _picked,
                         layout="player_menu")

    def stream_info_text(self):
        """Picture and source of the stream playing (the app's Stream
        Info): resolution, frame rate, codec, source, proxy."""
        lines = []
        try:
            service = self.session.nav.getCurrentService()
            info = service and service.info()
            if info:
                width = info.getInfo(iServiceInformation.sVideoWidth)
                height = info.getInfo(iServiceInformation.sVideoHeight)
                fps = info.getInfo(iServiceInformation.sFrameRate)
                codec = info.getInfo(iServiceInformation.sVideoType)
                picture = []
                if width and height and width > 0 and height > 0:
                    picture.append(u"{}\u00d7{}".format(width, height))
                if fps and fps > 0:
                    picture.append(u"{:g} fps".format(
                        round((fps / 1000.0 if fps > 1000 else fps), 2)))
                if codec in VIDEO_CODECS:
                    picture.append(VIDEO_CODECS[codec])
                if picture:
                    lines.append(u"  \u00b7  ".join(picture))
        except Exception as e:
            debug("Stream info not read: {}".format(e))
        if not lines:
            lines.append(to_text(_("Picture: not known yet")))
        status = self._status_text()
        if status:
            lines.append(status)
        lines.append(u"{}  \u00b7  {}:{}".format(
            to_text(self.name), PROXY_HOST, PORT))
        return u"\n".join(lines)

    def show_stream_info(self):
        text = self.stream_info_text()
        if not self._bar_themed:
            self.session.open(MessageBox, to_string(text),
                              MessageBox.TYPE_INFO, timeout=10)
            return
        self["stream_info"].setText(to_string(text))
        self["info_box"].show()
        self["stream_info"].show()
        self._info_shown = True
        if not self._bar_visible():
            TvInfoBarShowHide.OkPressed(self)

    # ---- the channel list over the video

    def open_channel_list(self):
        if not self.itemscount:
            return
        channels = [(row[0][0], row[0][1]) for row in self.list]
        codes = (list(self.country_codes) if self.country_codes is not None
                 else [self.country_code] * len(channels))
        logos = (list(self.logo_urls) if self.logo_urls is not None
                 else [None] * len(channels))
        names = [self._country_name_at(i) for i in range(len(channels))]
        self.session.openWithCallback(
            self._on_channel_list_closed, VavooPlayerList,
            channels, int(self.currentindex), codes, logos, names)

    def favourites_key(self):
        """FAV: the favourites over the video (as BLUE's channel list);
        the one chosen plays (added to this player's list)."""
        if self._closed:
            return
        favourites = favourite_channels()
        if not favourites:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("No favourites yet"), 3)
            return
        if self._bar_visible():
            self.hide_help_overlay()
            self.doHide()
        index = next((i for i, f in enumerate(favourites)
                      if f["url"] == self.url), 0)

        def chosen(i=None):
            if not self._closed and i is not None and \
                    0 <= i < len(favourites):
                self.play_channel(favourites[i])
        self.session.openWithCallback(
            chosen, VavooPlayerList,
            [(to_string(f["name"]), to_string(f["url"])) for f in favourites],
            index, [f.get("country_code") for f in favourites],
            [f.get("logo") or None for f in favourites],
            [f.get("country_name") for f in favourites])

    def help_rows(self):
        return [
            ("OK", _("Show / hide the bar")),
            (_("UP / DOWN, CH+ / CH-"), _("Next / previous channel")),
            (_("RED / EXIT / BACK"), _("Back (paused: to live first)")),
            (_("GREEN"), _("Add / remove favourite")),
            (_("YELLOW"), _("Source")),
            (_("BLUE"), _("The channel list")),
            ("FAV", _("The favourites")),
            ("INFO / EPG", _("Programme guide")),
            ("MENU", _("Options")),
            ("AUDIO / SUBTITLE", _("Audio track / subtitles")),
            ("PAUSE / PLAY", _("Pause live / play on")),
            ("<< / >>", _("30 seconds back / on (paused)")),
            (_("LEFT / RIGHT"), _("10 seconds back / on (paused)")),
            ("REC", _("Record (again: stop)")),
            ("STOP", _("Close the player")),
            ("1-9", _("Go to that channel")),
            ("0", _("The channel before")),
        ]

    def show_help(self):
        show_keys(self.session, self.help_rows())

    def _on_channel_list_closed(self, index=None):
        if self._closed or index is None:
            return
        if index == int(self.currentindex):
            if not self.stream_running:
                # chosen again after it stopped: start it again
                self.startStream()
            return
        self.zap_to(index)

    # ---- Record (the app's Opt.RECORD)

    def toggle_record(self):
        """Records this channel until the end of the programme on now
        plus 2 minutes (a receiver's instant recording) - or, with no
        guide or a programme ending within 10 minutes, until stopped (4
        hours at most). Again: stops it."""
        if self._closed:
            return
        record_channel(self._channel_info())
        self._refresh_status()

    def _refresh_status(self):
        if self._bar_themed and not self._closed:
            try:
                self["status"].setText(to_string(self._status_text()))
            except Exception:
                pass

    # ---- Pause Live TV (the app's pauseLive / startShift / seekShift)

    def _shift_behind(self):
        return self._shift_state in ("behind", "behind_paused")

    def _shift_position(self):
        position = self._shift_pos
        if self._shift_state == "behind" and self._shift_clock is not None:
            position += time.time() - self._shift_clock
        if self._shift is not None:
            position = min(position, self._shift.duration)
        return max(0.0, position)

    def _shift_text(self):
        if self._shift_state in ("paused", "behind_paused") or (
                self._shift_state is None and
                getattr(self, "seekstate", None) == self.SEEK_STATE_PAUSE):
            text = u"❚❚ " + to_text(_("Paused"))
            if self._shift is not None:
                text += u"  ·  " + to_text(
                    _("recording - press play to go on")
                    if self._shift.running else _("press play to go on"))
            elif self._shift_why in SHIFT_WHY:
                text += u"  ·  " + to_text(SHIFT_WHY[self._shift_why]())
            return text
        if self._shift_state == "behind":
            behind = 0
            if self._shift is not None:
                behind = int(max(0, self._shift.duration -
                                 self._shift_position()))
            return u"◀◀ -{}:{:02d}  {}".format(
                behind // 60, behind % 60,
                to_text(_("LEFT / RIGHT move · EXIT: live")))
        return None

    def pauseService(self):
        """PAUSE: the picture stops, and (Settings → Pause Live TV) the
        channel starts being recorded, to go on from here."""
        if self._closed:
            return
        if self._shift_state == "behind":
            self._shift_pos = self._shift_position()
            self._shift_clock = None
            self._shift_seek.stop()
            self._shift_state = "behind_paused"
            InfoBarSeek.pauseService(self)
        elif self._shift_state is None:
            if getattr(self, "seekstate", None) == self.SEEK_STATE_PAUSE:
                return
            InfoBarSeek.pauseService(self)
            self._start_shift()
        self._shift_changed()

    def unPauseService(self):
        """PLAY: on from where it was paused (out of the buffer)."""
        if self._closed:
            return
        if self._shift_state == "paused":
            self._shift_resume()
        elif self._shift_state == "behind_paused":
            self._shift_play_at(self._shift_pos)
        else:
            self._shift_why = None
            InfoBarSeek.unPauseService(self)
        self._shift_changed()

    def _resume_if_paused(self):
        """unPauseService by the image's key names (OpenPLi's PLAY,
        OpenATV's OK press): plays on what is paused, else nothing (OK
        shows the bar on its release, as always)."""
        if self._shift_state in ("paused", "behind_paused") or (
                self._shift_state is None and
                getattr(self, "seekstate", None) == self.SEEK_STATE_PAUSE):
            self.unPauseService()

    def playpauseService(self):
        if self._shift_state in ("paused", "behind_paused") or (
                self._shift_state is None and
                getattr(self, "seekstate", None) == self.SEEK_STATE_PAUSE):
            self.unPauseService()
        else:
            self.pauseService()

    def seekFwd(self):
        """>> : 30 seconds on in the buffer (live: nothing to seek)."""
        if self._shift_behind():
            self.shift_seek(30)
        else:
            InfoBarSeek.seekFwd(self)

    def seekBack(self):
        if self._shift_behind():
            self.shift_seek(-30)
        else:
            InfoBarSeek.seekBack(self)

    def _start_shift(self):
        self._shift_why = None
        if self._shift is not None or not cfg.timeshift.value:
            return
        channel_id = stream_channel_id(self.url)
        if not channel_id:
            return
        folder = pause_folder()
        ffmpeg = vavoo_record.find_ffmpeg()
        if not folder or not ffmpeg:
            # (no disk, no ffmpeg: PAUSE only pauses, and says so)
            self._shift_why = "disk" if not folder else "ffmpeg"
            print("[Pause] not recorded: no {} - PLAY goes on live".format(
                "disk with room for it" if not folder else "ffmpeg"))
            return
        address = PROXY_BASE_URL + "/vavoo?channel=" + \
            url_quote(channel_id, safe='')

        def source(force):
            # the address the player had (the shared token: the player
            # is paused, and stops once the buffer plays)
            if force:
                try:
                    vavoo_proxy.proxy.report_stream_failure(channel_id)
                except Exception:
                    pass
            return address

        recorder = vavoo_record.Recorder(
            source, vavoo_record.shift_path(folder),
            max_seconds=vavoo_record.SHIFT_MAX, ffmpeg=ffmpeg,
            log_path=RECORD_LOG, tag="Pause live", thread_name="vv-pause",
            max_bytes=vavoo_record.file_size_limit(folder))
        if not recorder.start():
            self._shift_why = "start"
            print("[Pause] not recorded: the recording did not start "
                  "({})".format(recorder.failure))
            return
        self._shift = recorder
        self._shift_state = "paused"
        self._shift_pos = 0.0
        self._shift_clock = None
        self._shift_waits = 0
        self._shift_tick.start(1000, False)
        print("[Pause] recording to " + recorder.path)

    def _shift_resume(self):
        """PLAY after a pause: the buffer from its start (it began a
        few seconds behind live, where the picture stopped). Its first
        part is waited for, a few seconds at most."""
        recorder = self._shift
        if recorder is None:
            return
        if recorder.duration < 2.0:
            if recorder.running and self._shift_waits < 15:
                self._shift_waits += 1
                self._shift_seek.start(1000, True)
                return
            # nothing recorded: just live
            print("[Pause] nothing was recorded ({}) - live".format(
                recorder.failure or "no data"))
            self._shift_end(replay=True)
            return
        self._shift_waits = 0
        self._shift_play_at(0.0)

    def _shift_play_at(self, position):
        recorder = self._shift
        if recorder is None or self._closed:
            return
        position = max(0.0, min(position, recorder.duration - 2))
        # (its very start from byte 0: the stream's tables come before
        # the first picture the index points at)
        offset = recorder.offset_for(position) if position > 0 else 0
        url = "{}/file?id={}&offset={}&follow=1".format(
            PROXY_BASE_URL, recorder.file_id, offset)
        self._shift_pos = recorder.time_at(offset)
        self._shift_clock = time.time()
        self._shift_state = "behind"
        behind = int(max(0, recorder.duration - self._shift_pos))
        print("[Pause] playing the buffer from -{}:{:02d}{}".format(
            behind // 60, behind % 60,
            "" if recorder.running else " (no longer recording)"))
        try:
            self.session.nav.stopService()
            self.session.nav.playService(file_stream_sref(url, self.name))
        except Exception as e:
            print("[Playstream2] Pause buffer not played: {}".format(e))
        self._seek_state_play()
        self._shift_changed()

    def shift_seek(self, seconds):
        """LEFT / RIGHT (10 s), << / >> (30 s) behind live: the place
        moves at once, the buffer is opened there once the keys rest."""
        if not self._shift_behind() or self._shift is None:
            return
        end = max(0.0, self._shift.duration - 2)
        self._shift_pos = max(0.0, min(self._shift_position() + seconds, end))
        self._shift_clock = None
        self._shift_state = "behind"
        self._shift_seek.start(800, True)
        self._shift_changed()

    def _shift_seek_now(self):
        if self._shift_state == "paused":
            self._shift_resume()
        elif self._shift_behind():
            self._shift_play_at(self._shift_pos)

    def _shift_end(self, replay=True, say=False):
        """Back to live (EXIT, the buffer's end) or leaving the channel
        (a zap, closing): the buffer stops and is deleted. replay: the
        live channel played again (the stream's proxy count was never
        given up - the buffer is not a stream of the player's)."""
        self._shift_why = None
        recorder, state = self._shift, self._shift_state
        if recorder is None and state is None:
            return
        self._shift = None
        self._shift_state = None
        self._shift_clock = None
        self._shift_tick.stop()
        self._shift_seek.stop()
        if recorder is not None:
            recorder.discard()
        if replay and getattr(self, 'sref', None) is not None:
            try:
                self.session.nav.stopService()
                self.session.nav.playService(self.sref)
            except Exception as e:
                print("[Playstream2] Live not played again: {}".format(e))
            self._seek_state_play()
        if say and NOTIFICATION_AVAILABLE:
            quick_notify(_("Live"), 2)
        self._shift_changed()

    def _seek_state_play(self):
        """A service just started plays (InfoBarSeek does the same on
        its start event - set at once, so a PAUSE right after it is
        not taken for an "already paused")."""
        play = getattr(self, "SEEK_STATE_PLAY", None)
        if play is not None:
            self.seekstate = play

    def _on_shift_tick(self):
        recorder = self._shift
        if recorder is not None and not recorder.running and \
                self._shift_state == "paused":
            # The buffer stopped before PLAY (gave up, the disk full,
            # its 2 hours): what it holds is kept - PLAY plays it and
            # its end goes live. Nothing in it: PAUSE only pauses now.
            self._shift_tick.stop()
            seconds = int(recorder.duration)
            print("[Pause] buffer stopped ({}) after {}:{:02d}".format(
                recorder.failure or "ended", seconds // 60, seconds % 60))
            if recorder.duration < 2.0:
                self._shift_end(replay=False)
                self._shift_why = "stopped"
            self._shift_changed()
            return
        self._refresh_status()

    def _shift_changed(self):
        """The bar's status line, or (Classic) a short message."""
        if self._bar_themed:
            self._refresh_status()
            if (self._shift_state is not None or self._shift_why) and \
                    not self._closed:
                self._show_bar_now()
        elif NOTIFICATION_AVAILABLE and (
                self._shift_state is not None or self._shift_why):
            text = self._shift_text()
            if text:
                quick_notify(to_string(text), 5 if self._shift_why else 3)

    def isSeekable(self):
        """Live TV is never seekable - InfoBarSeek (a base class of
        this screen, for its EOF/evUpdatedInfo plumbing, not because
        this content is actually seekable) binds LEFT/RIGHT to
        seekBack()/seekFwd() by default and only guards them with
        this exact check. Without overriding it, pressing LEFT/RIGHT
        during live playback tried to seek a stream with no real
        duration/seek support - the backend stalls audio attempting
        it, and needs a second press (itself swallowed by the same
        broken seek attempt, which is what actually clears the
        stall) to recover. Returning False here makes InfoBarSeek's
        own seek methods no-ops instead, exactly as intended for a
        continuous live stream."""
        return False

    def doEofInternal(self, playing):
        """Handle end of file (stream ended).

        InfoBarSeek (a base class of this screen) independently listens
        for iPlayableService.evEOF and calls this as its own extension
        hook - and __evEOF() below is ALSO explicitly wired to that same
        raw event. Both fire for a single real EOF, so the actual
        counting/restart logic lives in _handleEofEvent(), which
        debounces near-simultaneous calls so one real EOF is only
        counted once.
        """
        print('[Playstream2] doEofInternal, playing:', playing)
        if self.execing and playing:
            self._handleEofEvent("doEofInternal")

    def __evEOF(self):
        """Event: End of file reached (see doEofInternal for why this
        duplicates that hook)."""
        print('[Playstream2] __evEOF')
        self._handleEofEvent("__evEOF")

    def _handleEofEvent(self, source):
        """Shared EOF bookkeeping/restart logic for doEofInternal() and
        __evEOF(), which both fire for the same underlying event."""
        if self._shift_state in ("behind", "behind_paused"):
            # the end of the pause buffer (it stopped growing): live
            print("[Pause] end of the buffer - live")
            self._shift_end(replay=True, say=True)
            return
        if self._shift_state == "paused":
            # the paused live stream ran dry meanwhile: PLAY goes on
            # from the buffer anyway
            return
        current_time = time.time()

        if not hasattr(self, 'eof_count'):
            self.eof_count = 0
            self.last_eof_time = 0

        time_since_last_eof = current_time - self.last_eof_time

        # doEofInternal() and __evEOF() both fire for the same real EOF,
        # typically within the same event-loop tick - a gap this short
        # means this is the other handler for the event just processed,
        # not a second, genuinely separate EOF. (0 <=, not 0 <: two
        # calls landing on the very same clock reading are exactly
        # that duplicate, and last_eof_time's initial 0 can never
        # produce a gap this small.)
        if 0 <= time_since_last_eof < 1.5:
            print(
                "[Playstream2] Ignoring duplicate EOF signal from " +
                source)
            return

        self.last_eof_time = current_time

        # The retry backoff below waits 0-4s ((eof_count-1) * 2, capped
        # at eof_count==3) before the next restart attempt, plus
        # whatever the resolve+reconnect itself takes (typically a
        # couple more seconds) - a 10s "frequent" window was shorter
        # than that combined delay could easily run, so a stream that
        # kept failing immediately on every restart still measured each
        # EOF as more than 10s after the previous one and reset
        # eof_count back to 1 every time. That meant the "give up after
        # 3 quick retries" safety net below could never actually
        # trigger - a persistently broken stream would retry forever
        # instead of eventually returning to the channel list. 45s
        # comfortably covers the worst-case backoff+resolve time with
        # margin, while still resetting correctly for a stream that
        # played fine for a real stretch before an unrelated one-off
        # EOF.
        if time_since_last_eof < 45:
            self.eof_count += 1
            print(
                "[Playstream2] Frequent EOF #" +
                str(self.eof_count) +
                " (" + source + "), time: " +
                "%.1f" % time_since_last_eof +
                "s"
            )
        else:
            self.eof_count = 1

        # Whatever the proxy was answering with for this channel just
        # ended - have it drop that address (and, for a multi-source
        # channel, decide whether to stay on the same source) before
        # the restart below asks it again. Reported here, once per
        # real EOF - never as a parameter on the stream address,
        # which the player would repeat on every playlist refresh
        # (see playProxyStream()'s own docstring).
        self._report_stream_failure()

        # Restart based on EOF frequency. The first retry is
        # immediate - a fresh address usually fixes it, and waiting
        # on general backoff principle only makes the common case
        # slower. The escalating delay only kicks in for a 2nd/3rd
        # retry, i.e. when the fresh address ALSO failed fast.
        if self.eof_count <= 3:  # Allow up to 3 quick retries
            delay = (self.eof_count - 1) * 2  # 0, 2, 4 seconds
            print(
                "[Playstream2] Restarting stream in " +
                str(delay) +
                " seconds (EOF #" +
                str(self.eof_count) +
                ")"
            )
            self.restartStreamDelayed(delay * 1000)
        else:
            print("[Playstream2] Too many EOFs, stopping auto-restart")
            error_msg = _("Stream ended. Too many connection issues.") + \
                "\n" + _("Returning to channel list.")
            # Giving up on auto-restart used to just show this message
            # and leave the player screen sitting dead (no video, no
            # further retries) once it closed on its own after the
            # timeout - the user had to notice and press cancel/back
            # themselves to get back to the channel list. Close the
            # player automatically instead.
            self.session.openWithCallback(
                lambda result=None: self.cancel(),
                MessageBox,
                error_msg,
                MessageBox.TYPE_ERROR,
                timeout=5
            )

    def __serviceStarted(self):
        """Service started playing"""
        print("Playback started successfully")
        self.state = self.STATE_PLAYING

    def startStream(self, is_retry=False):
        """Start the stream - proxy handles authentication.

        is_retry=True is a restart of the channel that is already
        selected (after an EOF or a source pick - see
        restartAfterEOF()): it goes ahead even though a stream is
        marked as running, and keeps the EOF/retry counters."""
        if self.stream_running and not is_retry:
            return

        print("[Playstream2] Starting stream: " + str(self.name))
        print("[Playstream2] URL: " + str(self.url))

        self.stream_running = True
        self.is_streaming = True

        if not is_retry:
            # Fresh channel selection - start its EOF/retry tracking clean.
            # A retry is a restart of the SAME channel (see
            # restartAfterEOF); eof_count must survive that, or the
            # "give up after N quick retries" limit never engages
            # since every retry would reset its own counter to 0 first.
            self.eof_count = 0
            self.last_eof_time = 0

        # Clean up URL
        if "/live2/play/" in self.url and self.url.endswith(".ts"):
            print("[Playstream2] Converting to proxy format")
            channel_id = self.url.split("/live2/play/")[1].replace(".ts", "")
            self.url = PROXY_BASE_URL + "/vavoo?channel=" + channel_id

        if not is_retry:
            remember_recent(self._channel_info())
            if self._inherit_pending:
                self._inherit_pending = False
                if NOW_PLAYING.player_take(self.url):
                    # The preview window is playing this very channel:
                    # the same stream simply goes full screen. No
                    # service start event comes for it - show the bar
                    # the way a start would.
                    self.sref = NOW_PLAYING.sref
                    self.hand_back = True
                    print("[Playstream2] Carrying on with the preview's stream")
                    self.serviceStarted()
                    return

        self.playProxyStream()

    def _channel_info(self):
        """The playing channel as the preview / "Recently watched"
        keep it."""
        return {
            "name": self.name, "url": self.url,
            "country_name": self.country_name,
            "country_code": self.country_code,
            "logo": self.current_logo_url or "",
        }

    def restartStreamDelayed(self, delay_ms):
        """Restart stream after a delay"""
        try:
            # Stop any existing timer
            if hasattr(self, 'eof_recovery_timer'):
                self.eof_recovery_timer.stop()

            self.eof_recovery_timer = eTimer()
            try:
                self.eof_recovery_timer.callback.append(self.restartAfterEOF)
            except BaseException:
                self.eof_recovery_timer.timeout.connect(self.restartAfterEOF)

            self.eof_recovery_timer.start(delay_ms, True)
        except Exception as e:
            print('[Playstream2] Error setting up restart timer:', e)
            # Immediate restart as fallback
            self.restartAfterEOF()

    def restartAfterEOF(self):
        """Stop and (after a short, cancellable delay) restart the
        current stream - despite the name, not EOF-specific: also
        reused by _onStreamSourceChosen() for a manual source pick,
        which needs the exact same deferred-restart safety this
        already has."""
        print("[Playstream2] Restarting stream (non-blocking)")
        self.stopStream(restore_original=False)
        # Stored so cancel() can cancel it - previously this handle was
        # discarded, so a STOP/BACK press during this 0.5s window closed
        # the screen but couldn't stop the pending restart, which then
        # fired startStream() on a torn-down screen, silently hijacking
        # whatever the user navigated back to.
        self._eof_restart_call = reactor.callLater(
            0.5, self._do_restart_after_eof)

    def _do_restart_after_eof(self):
        if self._closed:
            return
        self.startStream(is_retry=True)

    def get_current_epg(self):
        """The playing channel's current programme as the one line
        the OK overlay shows: "HH:MM-HH:MM Title - Description"
        (showIMDB() takes the title back out of exactly this shape),
        or one of the "EPG ..." / "No programme found" texts when
        there is none.

        Can block on a guide download: background threads only (see
        show_help_overlay() and showIMDB()). The guide itself, its
        caching and the channel matching are vUtils.lookup_now_next()
        - the same lookup the channel list's Now/Next panel uses, so
        the two always agree.
        """
        try:
            if not self.country_code:
                return "EPG not available (no country code)"

            status, current, _following = vUtils.lookup_now_next(
                self.name, self.country_code,
                channel_id=_epg_channel_id(self.url))
            if status == "no_guide":
                return "EPG not available"
            if status == "no_match":
                return "EPG not available (ID not found)"
            if current is None:
                return "No programme found"

            start, stop, title, description = current
            return "{}-{} {} - {}".format(
                vUtils.epg_clock(start), vUtils.epg_clock(stop),
                to_string(title), to_string(description))

        except Exception as e:
            print("[EPG] Exception in get_current_epg: {}".format(e))
            trace_error()
            return "EPG error"

    def _current_channel_id(self):
        """The catalog id (or "grp:<country>:<key>" group id - see
        vavoo_proxy.py's make_group_id()) this screen is playing,
        taken from self.url's "vavoo?channel=<id>", or None if
        self.url isn't a proxy stream address at all.

        Decoded: self.url carries the id URL-quoted (/channels'
        own response already quotes it - "grp%3Aitaly%3A...", not
        "grp:italy:..."), and everything this is handed to
        (report_stream_failure(), get_group_sources(),
        set_group_source()) takes the real id."""
        return stream_channel_id(self.url)

    def _current_group_channel_id(self):
        """_current_channel_id() if it is a grouped (multi-source)
        channel, else None."""
        channel_id = self._current_channel_id()
        if channel_id and channel_id.startswith(GROUP_ID_PREFIX):
            return channel_id
        return None

    def playProxyStream(self):
        """Play self.url's channel through the local proxy.

        The address handed to the player is always the plain
        http://127.0.0.1:<PORT>/vavoo?channel=<id> and nothing else.
        The player does not request it once: /vavoo answers with a
        302, so it comes back to this same address on every playlist
        refresh, about every 10 seconds, for as long as the channel
        is watched. Earlier versions put one-off instructions into
        it ("&force=1" after an EOF, "&keep=1", "&source=<id>" after
        a source pick), and every one of them was then repeated on
        every refresh - a fresh upstream address every few seconds,
        and on a multi-source channel a different source every other
        time, which is what kept ending streams. A failed stream or
        a source pick is now reported to the proxy once, directly
        (_handleEofEvent(), _onStreamSourceChosen()), and the proxy
        keeps answering with the same address in between.
        """
        try:
            # build_stream_sref(): the plain proxy address with the
            # configured player service type ("Movie Services
            # Reference" - 4097/5001/5002/8193), shared with the
            # preview window so both play exactly the same thing.
            sref = build_stream_sref(self.name, self.url)
            if sref is None:
                print("[Playstream2] Could not extract channel ID")
                self._notify_cannot_play()
                return
            print("[Playstream2] Playing through the proxy: " +
                  to_string(self.name))
            self.sref = sref

            try:
                # Read through the module, not a plain `from .vavoo_proxy
                # import proxy` value binding - vavoo_proxy.start_proxy()
                # reassigns its own module-level `proxy` on every restart,
                # which a one-time value import would never see, silently
                # accounting this stream against a dead, orphaned instance.
                vavoo_proxy.proxy.stream_started()
                print("[Playstream2] Notified proxy: stream started")
            except Exception as e:
                print("[Playstream2] Failed to notify proxy: {}".format(e))

            # Play the stream
            self.session.nav.stopService()
            self.session.nav.playService(self.sref)
            print("[Playstream2] Proxy stream started successfully")

        except Exception as e:
            print("[Playstream2] playProxyStream error: " + str(e))
            trace_error()

    def _notify_cannot_play(self):
        """self.url isn't something the proxy can play (a damaged
        favourite, say) - tell the user instead of sitting on a black
        screen. Every channel list in this plugin comes from the
        proxy, so there is no other playback path to fall back to."""
        self.stream_running = False
        self.is_streaming = False
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("This channel cannot be played"), 4)

    def _report_stream_failure(self):
        """Tell the proxy the stream it gave us for this channel just
        ended - see VavooProxy.report_stream_failure() for what it
        does with that. Called once per real EOF, right before the
        restart that follows it."""
        channel_id = self._current_channel_id()
        if not channel_id:
            return
        try:
            vavoo_proxy.proxy.report_stream_failure(channel_id)
        except Exception as e:
            print("[Playstream2] Failed to report stream failure: {}".format(e))

    def chooseStreamSource(self):
        """YELLOW (also MENU -> Source): let the user manually pick
        which physical source (Vavoo/Geil's ".b"/".c"/".s" convention - see
        vavoo_proxy.py's _group_key()/_strip_source_suffix()) plays a
        channel that has more than one, instead of leaving the choice
        to automatic selection/failure-recovery - the companion
        Android app offers the same choice in its own player menu.
        Only meaningful for a grouped channel; a single-source one has
        nothing to choose between.
        """
        group_id = self._current_group_channel_id()
        data = None
        if group_id:
            try:
                # In-process (the proxy is a thread of this same
                # Enigma2, like stream_started() above) - a couple of
                # dict lookups, no network, so the menu opens at once.
                data = vavoo_proxy.proxy.get_group_sources(group_id)
            except Exception as e:
                print(
                    "[Playstream2] Error reading stream sources: {}".format(e))

        members = (data or {}).get("members") or []
        if len(members) < 2:
            if NOTIFICATION_AVAILABLE:
                quick_notify(
                    _("Only one source available for this channel"), 3)
            return

        current = data.get("current")
        entries = []
        for member in members:
            # to_text(): the label is the source's catalog name (unicode
            # on Python 2). ✓ the one playing, ✗ one that failed a
            # moment ago (the app's marks).
            label = to_text(member.get("label", ""))
            if member.get("id") == current:
                label += u"  \u2713"
            elif member.get("failed"):
                label += u"  \u2717"
            entries.append((to_string(label), member.get("id")))

        open_action_menu(
            self.session, _("Source"), entries,
            lambda member_id: self._onStreamSourceChosen((None, member_id)),
            layout="player_menu")

    def _onStreamSourceChosen(self, choice):
        if self._closed or not choice or not choice[1]:
            return
        group_id = self._current_group_channel_id()
        if not group_id:
            return
        print("[Playstream2] Source chosen: " + str(choice[1]))
        try:
            if not vavoo_proxy.proxy.set_group_source(group_id, choice[1]):
                return
        except Exception as e:
            print("[Playstream2] Error setting stream source: {}".format(e))
            return
        # restartAfterEOF() stops the current stream and defers the
        # actual restart by 0.5s rather than doing it synchronously -
        # not EOF-specific despite the name, and needed here too: this
        # runs as the ChoiceBox's own close callback, while the screen
        # stack is still settling back from that dialog closing.
        # Tearing down and recreating the service right then was
        # observed to leave self.execing False for several seconds
        # instead of the usual well under one, stalling
        # serviceStarted()'s 500ms retry loop
        # (TvInfoBarShowHide._retry_start()) and the overlay/EPG
        # refresh that depends on it - the stream looked frozen even
        # though it likely wasn't. Reusing this also means a STOP/
        # BACK press in that 0.5s window correctly cancels the
        # pending restart (see cancel()'s own handling of
        # self._eof_restart_call), exactly as it already does for a
        # real EOF.
        self.restartAfterEOF()

    def stopStream(self, restore_original=True):
        """Stop the stream and cleanup.

        restore_original=False is used when this is a transient stop
        (switching to another Vavoo channel, or an EOF auto-restart) that
        will immediately start a new stream - restoring srefInit (the
        channel that was playing before this player opened) here would
        otherwise briefly flash back to it on every channel change/retry.
        """
        if self.stream_running:
            self.stream_running = False
            self.is_streaming = False
            print("[Playstream2] Stream stopped")

            try:
                vavoo_proxy.proxy.stream_ended()
                print("[Playstream2] Notified proxy: stream ended")
            except Exception as e:
                print("[Playstream2] Failed to notify proxy: {}".format(e))
        # Stop recovery timer
        if hasattr(self, 'eof_recovery_timer'):
            self.eof_recovery_timer.stop()

        # Stop current service
        try:
            self.session.nav.stopService()
            if restore_original and self.srefInit:
                self.session.nav.playService(self.srefInit)
        except BaseException as e:
            print("[Playstream2] Failed to stop/restore service: {}".format(e))

    def back(self):
        """EXIT / BACK / RED: behind live or paused, back to live first
        (the app's); else close."""
        if self._shift_state is not None and not self._closed:
            self._shift_end(replay=True, say=True)
            return
        self.cancel()

    def cancel(self):
        """Close the player"""
        # Reachable both from the cancel/back action bindings and from
        # onClose (added below in __init__), which both fire on a normal
        # user-initiated close - guard against running the cleanup twice.
        if self._closed:
            return
        print("[Playstream2] Closing player...")
        self._closed = True
        if ACTIVE.get("player") is self:
            ACTIVE["player"] = None

        # Stop this screen's own timers - previously only stopped by whichever
        # timer's own callback happened to run first; a screen closed before
        # that could leave one re-arming itself against a torn-down instance.
        for timer_name in ("proxy_update_timer", "hideTimer",
                           "delayed_start_timer", "retry_start_timer",
                           "eof_recovery_timer", "_prefetch_timer"):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception as e:
                    print("[Playstream2] Error stopping {}: {}".format(
                        timer_name, e))

        # restartAfterEOF()'s second-stage reactor.callLater isn't an
        # eTimer, so it needs its own cancellation - previously left
        # running, so a STOP press during its 0.5s window still fired
        # startStream() on this now-closed screen.
        if self._eof_restart_call is not None:
            try:
                if self._eof_restart_call.active():
                    self._eof_restart_call.cancel()
            except Exception as e:
                print("[Playstream2] Error cancelling EOF restart: {}".format(e))

        self._shift_end(replay=self.hand_back and self.stream_running)
        for timer in (self._shift_tick, self._shift_seek):
            timer.stop()
        if self.hand_back and self.stream_running and \
                getattr(self, 'sref', None) is not None:
            # Back to the list: the channel keeps playing in its
            # preview window (with its proxy count) instead of
            # stopping - the app's handBackToPreview.
            self.stream_running = False
            self.is_streaming = False
            if hasattr(self, 'eof_recovery_timer'):
                self.eof_recovery_timer.stop()
            NOW_PLAYING.player_give_back(self._channel_info(), self.sref)
        else:
            self.stopStream()
            NOW_PLAYING.player_closed()
        try:
            for screen in self.session.dialog_stack:
                if hasattr(screen[0], 'proxy_monitor_timer'):
                    screen[0].proxy_monitor_timer.start(
                        PROXY_MONITOR_INTERVAL_MS)
                    print("[Playstream2] Restarted proxy monitor timer")
                if hasattr(screen[0], 'proxy_watchdog_timer'):
                    screen[0].proxy_watchdog_timer.start(
                        PROXY_WATCHDOG_INTERVAL_MS)
                    print("[Playstream2] Restarted proxy watchdog timer")
        except Exception as e:
            print("[Playstream2] Error restarting timers: {}".format(e))

        # Reset EOF counter
        if hasattr(self, 'eof_count'):
            self.eof_count = 0

        # Cleanup temp files
        if isfile("/tmp/hls.avi"):
            remove("/tmp/hls.avi")

        # Restore aspect ratio
        try:
            aspect_manager.restore_aspect()
        except BaseException as e:
            debug("aspect_manager.restore_aspect() failed: {}".format(e))

        # The list it came from moves its highlight to the channel
        # watched last (the user may have zapped).
        self.close((self.currentindex, self.name, self.url))

    def leavePlayer(self):
        """Alternative close method (STOP button) - runs the exact same
        cleanup as cancel() instead of skipping it (previously set
        _closed early, which made cancel()'s own dedupe guard skip its
        entire cleanup body when it ran via onClose)."""
        self.cancel()
