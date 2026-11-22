#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
from .ui_player import (
    Playstream2)
from .ui_guide import (
    REMINDERS, VavooGuide)
from .ui_settings import (
    ask_factory_reset, open_settings, show_about)
from .ui_record import (
    RECORDINGS,
    VavooRecordings,
    clean_pause_leftovers,
    logo_folder,
    record_channel,
    recordings_folder)
from .ui_pick import (
    _require_parental_pin, run_welcome, welcome_needed)
from .ui_base import (
    ACTIVE, CHANNEL_FETCH_ATTEMPTS, FAVOURITES_ROW, LIST_KEYS_PRIO,
    MAIN_KEYS, NO_CHANNELS_ROW, NOW_PLAYING, NowNextPanel, PLUGIN_PATH,
    PLUGLOGO,
    PROXY_MONITOR_INTERVAL_MS, PROXY_WATCHDOG_INTERVAL_MS, PreviewWindow,
    RECENT_ROW, REMINDERS_ROW, _no_answer, add_epg_panel_labels,
    add_key_hint_labels, cfg, clock_24, favourite_channels, info_page_keys,
    info_text, list_keys, list_page_rows, load_screen_skin, m2list, named,
    open_action_menu, open_log_viewer, row_number, set_notification_theme,
    show_keys, show_list, stop_preview, title_plug, to_string, to_text,
    url_quote)

import codecs
import time
import threading
from os import remove
from os.path import join, isfile
from json import loads
from enigma import eDVBDB
from twisted.internet import reactor
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from enigma import ePicLoad, eTimer
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Tools.Directories import SCOPE_PLUGINS, resolveFilename
from Tools.NumericalTextInput import NumericalTextInput
from Plugins.Plugin import PluginDescriptor
from .vavoo_stats import (
    record_anonymous_startup,
    is_stats_enabled,
    start_heartbeat,
    stop_heartbeat
)
from . import vavoo_proxy
from .vavoo_proxy import (
    is_proxy_booting, restart_proxy_in_background, run_proxy_in_background,
    serving_here)
from . import (
    _,
    __version__,
    export_lock,
    PROXY_BASE_URL,
    PROXY_COUNTRIES_URL,
    PROXY_REFRESH_URL,
    EPGIMPORT_CONF,
    group_separators
)
from . import vUtils
from . import vavoo_theme
from . import vavoo_store
from . import vavoo_record
from .bouquet_manager import (
    convert_bouquet,
    _update_favorite_file,
    remove_bouquets_by_name,
    export_bouquet_async,
    is_bouquet_exported,
    remove_favorite_entry
)
from .vUtils import (
    debug,
    make_print,
    cleanup_old_temp_files,
    check_remote_installer_version,
    download_picon_online,
    ensure_str,
    fix_cache_format,
    getUrl,
    get_proxy_status,
    get_country_code,
    initialize_cache_with_local_flags,
    is_proxy_ready,
    is_proxy_running,
    is_remote_version_newer,
    ReloadBouquets,
    trace_error
)
from .Console import Console
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


def _is_vavoo_already_open(session):
    try:
        # dialog_stack entries are usually tuples like (dialog, ...)
        for entry in getattr(session, "dialog_stack", []):
            dlg = entry[0] if isinstance(
                entry, (list, tuple)) and entry else entry
            if dlg is None:
                continue
            name = dlg.__class__.__name__
            if name in ("startVavoo", "MainVavoo", "vavoo"):
                return True
    except Exception as e:
        debug("_is_vavoo_already_open check failed: {}".format(e))
    return False


_session = None
# Guards autostart() itself against re-scheduling delayed_boot_tasks() on
# repeat calls - kept separate from _session, which delayed_boot_tasks()
# uses to detect whether the user has actually opened a plugin screen.
_autostart_scheduled = False
auto_start_timer = None

# Auto-update check state, shared between startVavoo (kicks off the
# background check) and MainVavoo (shows the popup once, after the main
# menu is open). See _start_update_check() /
# MainVavoo._check_update_popup_tick().
_update_check_started = False
_update_check_done = False
_update_check_result = None
_update_popup_shown = False


def _start_update_check():
    """Check installer.sh on GitHub for a newer plugin version, in the
    background, every time the plugin is launched (i.e. every time the
    splash screen runs, not just once per Enigma2 GUI process).

    Called from startVavoo so the check overlaps with the splash screen
    instead of adding to perceived load time. The result is only surfaced
    as a popup once MainVavoo (the main menu) is actually open - see
    MainVavoo._check_update_popup_tick(). Resets the shared state on
    every call so a closed-and-reopened plugin gets a fresh check and
    can show the popup again, instead of only ever on the first launch.
    """
    global _update_check_started, _update_check_done, _update_check_result, _update_popup_shown
    _update_check_started = True
    _update_check_done = False
    _update_check_result = None
    _update_popup_shown = False
    print("[Update] Starting background version check (local v{})".format(__version__))

    def _worker():
        global _update_check_result, _update_check_done
        _update_check_result = check_remote_installer_version()
        version, changelog, content = _update_check_result
        print("[Update] Check finished: remote_version={} changelog_len={} content_len={}".format(
            version, len(changelog) if changelog else 0, len(content) if content else 0))
        _update_check_done = True

    _update_thread = threading.Thread(target=named(_worker, "vv-update"))
    _update_thread.daemon = True
    _update_thread.start()


class startVavoo(Screen):
    # ── animated splash configuration ────────────────────────────────────────
    # These messages are cosmetic progress flavor only; the screen does not
    # actually close until the proxy reports itself ready (or the
    # configured startup timeout elapses) - see _check_ready()/_finish().
    STATUS_STEPS = [
        (0, "Connecting to 127.0.0.1:4323 ..."),
        (18, "Loading channel catalog ..."),
        (42, "Authenticating Vavoo servers ..."),
        (68, "Renewing stream tokens ..."),
        (86, "Finalizing startup ..."),
    ]
    TOTAL_MS = 1200   # time for the cosmetic bar to reach SOFT_CAP
    TICK_MS = 30     # timer interval in ms
    HOLD_MS = 250    # pause at 100 % before closing
    POLL_MS = 400    # how often we check real proxy readiness
    # Cosmetic progress never claims 100% on its own - only once the proxy
    # actually reports "initialized" (or we give up after the timeout) do
    # we jump to 100% and close.
    SOFT_CAP = 92

    def __init__(self, session):

        global _session, first
        self.session = session
        _session = session
        first = True
        Screen.__init__(self, session)
        self.skin, self._themed = load_screen_skin(
            "splash", 'Plgnstrt.xml', background=False)

        # existing widgets (kept for skin compatibility)
        self["poster"] = Pixmap()
        self["version"] = Label()

        # new animated-splash widgets
        self["title"] = Label("VAVOO STREAM LIVE")
        self["subtitle"] = Label("ENIGMA2 PLUGIN")
        self["progress_label"] = Label("INITIALIZING PROXY")
        self["progress_pct"] = Label("0 %")
        self["progress"] = ProgressBar()
        self["status"] = Label(self.STATUS_STEPS[0][1])
        self["author"] = Label("by Lululla & Qu4k3")
        self["skip_hint"] = Label("Press OK or EXIT to skip")

        self['actions'] = ActionMap(
            ['OkCancelActions'], {
                'ok': self.clsgo, 'cancel': self.clsgo}, -1)

        # animation state
        self._pct = 0
        self._msg_idx = 0
        self._steps = max(1, int(self.TOTAL_MS / self.TICK_MS))
        self._tick_no = 0

        # real-readiness state
        self._elapsed_ms = 0
        self._channels_count = 0
        max_wait_secs = 30
        try:
            max_wait_secs = int(cfg.proxy_startup_timeout.value)
        except Exception as e:
            debug(
                "Invalid proxy_startup_timeout config value, using default: {}".format(e))
        self._max_wait_ms = max(1000, max_wait_secs * 1000)

        self.onLayoutFinish.append(self.loadDefaultImage)

    # ── image decode (DreamOS-compatible, unchanged logic) ──────────────────
    def decodeImage(self):
        try:
            pixmapx = self.fldpng
            if isfile(pixmapx):
                size = self['poster'].instance.size()
                self.picload = ePicLoad()
                self.scale = AVSwitch().getFramebufferScale()
                self.picload.setPara(
                    [size.width(), size.height(),
                     self.scale[0], self.scale[1], 0, 1, '#00000000'])
                if isfile("/var/lib/dpkg/status"):
                    self.picload.startDecode(pixmapx, False)
                else:
                    self.picload.startDecode(pixmapx, 0, 0, False)
                ptr = self.picload.getData()
                if ptr is not None:
                    self['poster'].instance.setPixmap(ptr)
                    self['poster'].show()
        except Exception as e:
            print("[startVavoo] decodeImage error: " + str(e))
        try:
            self["version"].setText(to_string("V." + __version__))
        except Exception:
            pass

    # ── smoothstep progress tick (cosmetic only, capped at SOFT_CAP) ────────
    def _tick(self):
        self._tick_no += 1
        t = min(1.0, self._tick_no / float(self._steps))
        smooth = t * t * (3.0 - 2.0 * t)          # ease-in-out curve
        self._pct = min(self.SOFT_CAP, int(round(smooth * self.SOFT_CAP)))

        # ProgressBar.setValue() already no-ops safely if its instance
        # isn't bound yet - going through it (instead of the raw
        # .instance.setValue() + silent try/except used before) means a
        # real failure here can't silently freeze the bar while the
        # percentage/status text next to it keeps advancing.
        self["progress"].setValue(self._pct)
        self["progress_pct"].setText("%d %%" % self._pct)

        # advance status messages
        while self._msg_idx < len(self.STATUS_STEPS):
            threshold, msg = self.STATUS_STEPS[self._msg_idx]
            if self._pct >= threshold:
                self["status"].setText(msg)
                self._msg_idx += 1
            else:
                break
        # Completion is decided by _check_ready(), not by this cosmetic
        # timer - it just stops advancing once it hits SOFT_CAP.

    # ── real readiness check (drives when the splash actually closes) ──────
    def _check_ready(self):
        self._elapsed_ms += self.POLL_MS

        # Read in this process (no HTTP): ready = listening with its
        # catalog.
        data = get_proxy_status()

        if data and data.get("ready"):
            self._channels_count = data.get("channels_count", 0) or 0
            self._finish()
            return

        if self._elapsed_ms >= self._max_wait_ms:
            print(
                "[startVavoo] Proxy not ready after {}s, continuing anyway".format(
                    self._max_wait_ms // 1000))
            self._finish(timed_out=True)

    def _finish(self, timed_out=False):
        try:
            self._ready_timer.stop()
        except Exception:
            pass
        try:
            self._anim_timer.stop()
        except Exception:
            pass

        self._pct = 100
        self["progress"].setValue(100)
        self["progress_pct"].setText("100 %")

        if timed_out:
            msg = _("Continuing, proxy still syncing...")
        elif self._channels_count:
            msg = _("Proxy online - {} channels  ✓").format(
                self._channels_count)
        else:
            msg = "Proxy online  ✓"
        self["status"].setText(msg)

        self._hold_timer.start(self.HOLD_MS, True)   # single-shot hold

    # ── proxy kickoff (non-blocking - see run_proxy_in_background) ──────────
    def _start_proxy_if_needed(self):
        try:
            if is_proxy_running() and is_proxy_ready(timeout=0.5):
                return
            run_proxy_in_background()
        except Exception as e:
            print("[startVavoo] proxy start error: " + str(e))

    # ── timer setup (called once layout is ready) ───────────────────────────
    def loadDefaultImage(self):
        self.fldpng = resolveFilename(
            SCOPE_PLUGINS,
            "Extensions/{}/skin/pics/presplash.png".format('vavoo'))

        self._start_proxy_if_needed()
        _start_update_check()

        # image-decode timer (unchanged, fires once at 500 ms)
        self.timer = eTimer()
        if isfile('/var/lib/dpkg/status'):
            self.timer.timeout.connect(self.decodeImage)
        else:
            self.timer.callback.append(self.decodeImage)
        self.timer.start(500, True)

        # animation tick timer (repeating, 30 ms interval, cosmetic only)
        self["progress"].setValue(0)
        self._anim_timer = eTimer()
        if isfile('/var/lib/dpkg/status'):
            self._anim_timer.timeout.connect(self._tick)
        else:
            self._anim_timer.callback.append(self._tick)
        self._anim_timer.start(self.TICK_MS, False)

        # readiness-poll timer – repeating, decides when we actually finish
        self._ready_timer = eTimer()
        if isfile('/var/lib/dpkg/status'):
            self._ready_timer.timeout.connect(self._check_ready)
        else:
            self._ready_timer.callback.append(self._check_ready)
        self._ready_timer.start(self.POLL_MS, False)

        # hold timer – single-shot, started by _finish() once actually ready
        self._hold_timer = eTimer()
        if isfile('/var/lib/dpkg/status'):
            self._hold_timer.timeout.connect(self.clsgo)
        else:
            self._hold_timer.callback.append(self.clsgo)

    def clsgo(self):
        global first
        # stop any running timers safely
        try:
            self.timer.stop()
        except Exception:
            pass
        try:
            self._anim_timer.stop()
        except Exception:
            pass
        try:
            self._ready_timer.stop()
        except Exception:
            pass
        try:
            self._hold_timer.stop()
        except Exception:
            pass
        if first is True:
            first = False
            if welcome_needed():
                # a new install: the look, the countries, a PIN - then
                # the main list (in the chosen look)
                run_welcome(self.session, self._open_main)
                return
            self.session.open(MainVavoo)
        self.close()

    def _open_main(self):
        self.session.open(MainVavoo)
        self.close()


class UpdatePopup(Screen):
    """Yes/No dialog for a newly-found plugin update, skinned to match
    the splash screen (Plgnstrt.xml) instead of a generic MessageBox."""

    def __init__(self, session, remote_version, changelog):
        Screen.__init__(self, session)
        self.skin, self._themed = load_screen_skin(
            "update", 'UpdatePopup.xml', background=False)

        self["title"] = Label(_("Update Available"))
        self["subtitle"] = Label(
            _("v{} -> v{}").format(__version__, remote_version))
        # Plain Label, not ScrollLabel: two different ScrollLabel setups
        # (setText() deferred to onLayoutFinish, then constructing it
        # with the real text directly) both rendered a completely empty
        # box on real hardware (confirmed on OpenATV 7.6), even though
        # every other widget on this same screen - including this one's
        # own changelog_label right above it - renders fine. Label is
        # the one widget type known to actually work here (it's what
        # showed the changelog, truncated, before scrolling was added).
        # Do our own manual pagination instead of relying on a
        # component that isn't reliably rendering anything.
        self._changelog_text = changelog or _("No changelog provided.")
        changelog_lines = self._changelog_text.split('\n')
        lines_per_page = 8
        self._changelog_pages = [
            '\n'.join(changelog_lines[i:i + lines_per_page])
            for i in range(0, len(changelog_lines), lines_per_page)
        ] or ['']
        self._changelog_page_index = 0
        self["changelog_label"] = Label(self._changelogLabelText())
        self["changelog"] = Label(self._changelog_pages[0])
        self["key_red"] = Label(_("Cancel"))
        self["key_green"] = Label(_("Yes, update now"))

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "ok": self.confirm,
                "green": self.confirm,
                "cancel": self.deny,
                "red": self.deny,
                "up": self._changelogPageUp,
                "down": self._changelogPageDown,
                "left": self._changelogPageUp,
                "right": self._changelogPageDown,
            }, -1
        )

    def _changelogLabelText(self):
        if len(self._changelog_pages) > 1:
            return _("Changelog: ({}/{}, use up/down)").format(
                self._changelog_page_index + 1, len(self._changelog_pages))
        return _("Changelog:")

    def _changelogPageUp(self):
        if self._changelog_page_index > 0:
            self._changelog_page_index -= 1
            self["changelog"].setText(
                self._changelog_pages[self._changelog_page_index])
            self["changelog_label"].setText(self._changelogLabelText())

    def _changelogPageDown(self):
        if self._changelog_page_index < len(self._changelog_pages) - 1:
            self._changelog_page_index += 1
            self["changelog"].setText(
                self._changelog_pages[self._changelog_page_index])
            self["changelog_label"].setText(self._changelogLabelText())

    def confirm(self):
        self.close(True)

    def deny(self):
        self.close(False)


def proxy_status_text(state, channel_total=None):
    """The app's status line for the proxy's state (vUtils.
    get_proxy_status(), read in this process): "✓ Geil OK · 9818 ch",
    "Loading channels..." while it starts, else what is wrong.
    channel_total: the number the main list adds up to (sources of a
    channel counted once), else the proxy's own count. Never "OK" with
    no channels: then why ("✗ No channels - Vavoo: HTTP 500"); another
    source's list lent while the chosen one does not answer says so
    ("Geil (Vavoo not answering) · 9612 ch")."""
    if not state:
        return _("? Proxy Unknown")
    if not state.get("ready"):
        if state.get("booting") or (state.get("listening")
                                    and not state.get("initialized")):
            return _("Loading channels...")
        return _("✗ Proxy Offline")
    if not state.get("channels_count"):
        why = state.get("catalog_error")
        if why:
            return _("✗ No channels") + " - " + to_string(why)
        return _("✗ No channels")
    # Geil (the default catalog source) needs no addonSig token at all,
    # so addon_sig_valid is always False on it - not a problem there.
    token_required = state.get("token_required", True)
    source = "Vavoo" if token_required else "Geil"
    channels = channel_total or state.get("channels_count", 0)
    if token_required and not state.get("addon_sig_valid", False):
        return _("✗ Proxy Error")
    waited = state.get("catalog_fallback")
    if waited:
        return "{} ({}) · {} ch".format(
            source, _("{} not answering").format(
                vavoo_proxy.SOURCE_NAMES.get(waited, waited)), channels)
    if token_required and state.get("addon_sig_age", 0) >= 540:
        return "{} {} · {} ch".format(source, _("(token expiring)"), channels)
    return "✓ {} OK · {} ch".format(source, channels)


def no_channels_text(state, setting):
    """The main list's row when there are no countries at all: why, and
    what OK does there - the settings when the catalog source is pinned
    to one service (Auto then tries the other), else Reload List."""
    why = (state or {}).get("catalog_error") or ""
    if why:
        head = _("No channels: {}").format(to_string(why))
    else:
        head = _("No channels")
    if setting in ("geil", "vavoo"):
        return head + " - " + _(
            "OK: Settings (Catalog/Stream Source: Auto)")
    return head + " - " + _("OK: Reload List")


def _shared_update_proxy_status_display(screen):
    """Update the 'proxy_status' widget on screen (MainVavoo / vavoo
    share it). Reads the proxy in this process - no HTTP request, so
    the GUI thread never waits on it (it runs every 10 s)."""
    try:
        screen['proxy_status'].setText(to_string(proxy_status_text(
            get_proxy_status(), getattr(screen, '_channel_total', None))))
    except Exception as e:
        print("[ProxyStatus] Error updating proxy status: " + str(e))
        screen['proxy_status'].setText(_("✗ Error"))


def _shared_reload_bouquets_with_popup(screen):
    """Reload bouquets with confirmation popup (MainVavoo/vavoo share
    this verbatim)."""
    debug("reload_bouquets_with_popup called")
    screen.session.openWithCallback(
        screen._confirm_reload_bouquets,
        MessageBox,
        _("Reload bouquets and service list?"),
        MessageBox.TYPE_YESNO,
        timeout=10,
        default=True
    )


def _shared_confirm_reload_bouquets(screen, result):
    """Callback after user confirmation (MainVavoo/vavoo share this
    verbatim)."""
    if result:
        debug("User confirmed reload")
        try:
            db = eDVBDB.getInstance()
            db.reloadBouquets()
            db.reloadServicelist()
            print("Bouquets reloaded successfully")
        except Exception as e:
            print("Error during service reload: " + str(e))
            ReloadBouquets(500)
        try:
            screen.session.open(
                MessageBox,
                _("Bouquets reload scheduled."),
                MessageBox.TYPE_INFO,
                timeout=2
            )
        except Exception as e:
            print("[MessageBox] Error:", e)
    else:
        debug("User cancelled reload")


def guide_countries():
    """The countries whose guides are worth having ready: the
    favourites' (most favourites first), then the recently watched
    ones'. Country codes, as the favourites keep them."""
    counts = {}
    order = []
    for entry in (vUtils.load_favourites() or []):
        code = (entry.get("country_code") or "").lower()
        if code:
            if code not in counts:
                order.append(code)
            counts[code] = counts.get(code, 0) + 1
    out = sorted(order, key=lambda code: -counts[code])
    for entry in (vUtils.load_recent() or []):
        code = (entry.get("country_code") or "").lower()
        if code and code not in out:
            out.append(code)
    return out


class MainVavoo(Screen, PreviewWindow):
    _closed = True          # (ui_base's CLOSED_UNTIL_OPEN)

    def __init__(self, session):
        # So a background flag-download thread still in flight when the
        # user exits (closex()) can notice and skip re-arming timers /
        # touching UI on a screen that's no longer executing.
        self._closed = False
        self.session = session
        global _session
        _session = session
        ACTIVE["main"] = self
        REMINDERS.start(session)

        Screen.__init__(self, session)
        self.skin, self._themed = load_screen_skin(
            "list", 'defaultListScreen.xml', cvs=True, clock_24=clock_24())
        # What the box was playing: back on when the plugin closes.
        NOW_PLAYING.begin(session)
        set_notification_theme()
        init_notification_system(session)
        if NOTIFICATION_AVAILABLE:
            print('notify started')
            quick_notify(_("Welcome to Vavoo Proxy with EPG support"), 5)
        # Filled by cat(): the countries, the channels the list adds up
        # to, and whether a "Reload List" is waiting for its answer.
        self.countries = []
        self._channel_total = None
        self._reloading = False
        self._search_loading = False
        # "Start with last channel" is done once, on the first list.
        self._start_last_done = not cfg.start_last.value

        if is_stats_enabled():
            record_anonymous_startup()
            start_heartbeat()

        self._initialize_labels()
        self._initialize_actions()
        self._preview_init()
        self["menulist"].onSelectionChanged.append(self._update_selection_name)
        self.currentList = 'menulist'
        # How many times in a row the country list came back empty -
        # see _on_countries_response().
        self._country_load_failures = 0
        # cat() waiting for the proxy: since when, last log line, last
        # start asked (_note_proxy_wait())
        self._wait_since = None
        self._wait_logged = self._wait_kicked = 0

        self.start_vavoo_proxy()

        # Watchdog timer - check every 60 seconds
        self.proxy_watchdog_timer = eTimer()
        try:
            self.proxy_watchdog_timer.timeout.connect(
                self._proxy_watchdog_check
            )
        except BaseException:
            self.proxy_watchdog_timer.callback.append(
                self._proxy_watchdog_check
            )

        self.proxy_watchdog_timer.start(PROXY_WATCHDOG_INTERVAL_MS)

        # Monitor timer - check proxy status every 10 seconds
        self.proxy_monitor_timer = eTimer()
        try:
            self.proxy_monitor_timer.timeout.connect(
                self._check_and_update_proxy_status
            )
        except BaseException:
            self.proxy_monitor_timer.callback.append(
                self._check_and_update_proxy_status
            )

        self.proxy_monitor_timer.start(PROXY_MONITOR_INTERVAL_MS)

        # proxy_monitor_timer's first tick is still PROXY_MONITOR_INTERVAL_MS
        # (10s) away, so without this the label would sit on "Checking
        # proxy..." for up to 10 seconds even though the splash screen
        # already confirmed (or gave up on) proxy readiness moments ago -
        # refresh it immediately instead of leaving that stale placeholder.
        self['proxy_status'].setText(_("Checking proxy..."))
        self._update_proxy_status_display()
        self.cat()

        # Poll for the update check started during the splash screen to
        # finish, then show the popup (if a newer version was found) now
        # that the main menu is actually open - see _check_update_popup_tick().
        self._update_popup_timer = eTimer()
        if isfile('/var/lib/dpkg/status'):
            self._update_popup_timer.timeout.connect(
                self._check_update_popup_tick)
        else:
            self._update_popup_timer.callback.append(
                self._check_update_popup_tick)
        self._update_popup_timer.start(1000, False)

    def _initialize_labels(self):
        """Initialize the labels on the screen."""
        self.menulist = []
        self['menulist'] = m2list([], themed=self._themed)
        # The app's keys. What used to sit on them here (remove all
        # bouquets, fix the EPG cache, reload bouquets) is in the MENU
        # key's list now - see open_menu().
        self['red'] = Label(_('Exit'))
        self['green'] = Label(_('Favourites'))
        self['yellow'] = Label(_('Search'))
        self["blue"] = Label(_('Reload List'))
        add_key_hint_labels(self)
        self['name'] = Label('Loading...')
        self['version'] = Label()
        self['proxy_status'] = Label('Wait...')
        # Declared by the skin this screen shares with the channel
        # list; unused here (a country has no programme).
        add_epg_panel_labels(self)

    def _initialize_actions(self):
        """Initialize the actions for buttons."""
        actions = {
            'prevBouquet': self.chDown,
            'nextBouquet': self.chUp,
            'up': self.moveUp,
            'down': self.moveDown,
            'ok': self.ok,
            'menu': self.open_menu,
            'green': self.open_favourites,
            'yellow': self.search_all,
            'blue': self.reload_list,
            'cancel': self.closex,
            'red': self.closex,
            # EPG: the favourites' guide (the EPG import is in MENU)
            'epg': self.favourites_guide,
            'EPGPressed': self.favourites_guide,
            'info': self.info_toast,
            'InfoPressed': self.info_toast,
            'infoLong': self.info,
        }
        actions_list = [
            'MenuActions',
            'OkCancelActions',
            'ButtonSetupActions',
            'InfobarEPGActions',
            'ColorActions',
            'DirectionActions'
        ]
        self['actions'] = ActionMap(actions_list, actions, -1)
        self['epg_keys'] = info_page_keys(actions)
        # The direct keys (keymap.xml): FAV, PVR, TEXT, HELP, PLAY /
        # STOP / REC on the window's channel, 0 the channel watched last
        self['list_keys'] = list_keys({
            "favourites": self.open_favourites,
            "recordings": self.open_recordings,
            "search": self.search_all,
            "help": self.show_help,
            "play": self.play_window,
            "stop": lambda: stop_preview(self.session),
            "record": self.record_window,
            "back": self.closex,
        })
        self['main_keys'] = ActionMap(
            [MAIN_KEYS], {"epg": self.favourites_guide,
                          "ignore": lambda: None}, LIST_KEYS_PRIO)
        self['number_keys'] = ActionMap(
            ['NumberActions'], {"0": lambda: play_last_watched(
                self.session, self, self._on_child_closed)}, -1)

    def favourites_guide(self):
        open_favourites_guide(self.session, self, self._on_child_closed)

    def open_recordings(self):
        """PVR / the "Recordings (n)" row."""
        self.session.openWithCallback(self._on_child_closed, VavooRecordings)

    def _window_channel(self):
        if NOW_PLAYING.owner == NOW_PLAYING.PREVIEW and NOW_PLAYING.channel:
            return NOW_PLAYING.channel
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Nothing is playing in the window"), 2)
        return None

    def play_window(self):
        """PLAY: the channel of the preview window full screen."""
        channel = self._window_channel()
        if channel:
            play_entries(self.session, self, [channel], 0,
                         self._on_child_closed)

    def record_window(self):
        """REC: record the channel of the preview window."""
        channel = self._window_channel()
        if channel:
            record_channel(channel)

    def help_rows(self):
        return [
            ("OK", _("Open the country / list")),
            (_("RED / EXIT"), _("Exit")),
            (_("GREEN / FAV"), _("Favourites")),
            (_("YELLOW / TEXT"), _("Search all channels")),
            (_("BLUE"), _("Reload List")),
            ("MENU", _("Settings and tools")),
            ("INFO", _("Version and channels")),
            ("EPG", _("Programme guide of the favourites")),
            (_("PVR / FILE"), _("Recordings")),
            ("0", _("The channel watched last")),
            ("PLAY / STOP / REC", _("The window's channel: full screen / stop / record")),
            ("CH+ / CH-", _("Page up / down")),
        ]

    def show_help(self):
        show_keys(self.session, self.help_rows())

    def _fix_cache_format(self, result=None):
        if result is None:
            message_lines = []
            message_lines.append(_("Do you want to fix the cache format?"))
            message_lines.append(_("This will:"))
            message_lines.append(_("  - Add missing fields to all entries"))
            message_lines.append(_("  - Remove duplicate entries"))
            message_lines.append(_("  - Clean up the cache file"))
            message = "\n".join(message_lines)

            self.session.openWithCallback(
                self._fix_cache_format,
                MessageBox,
                message,
                MessageBox.TYPE_YESNO
            )
            return

        if not result:
            debug("fix_cache_format cancelled by user")
            return

        # An in-progress export's EPG-matching phase writes the same
        # cache file (see bouquet_manager.process_epg_matching_background)
        # with no lock of its own - share export_lock so the two can't
        # interleave and corrupt/clobber each other's write.
        # threading.Lock.acquire() only accepts blocking as a
        # positional argument on Python 2 (the C implementation there
        # doesn't support keyword arguments at all) - acquire(False)
        # works identically on both Python 2 and 3.
        if not export_lock.acquire(False):
            if NOTIFICATION_AVAILABLE:
                quick_notify(
                    _("An export is in progress. Please wait before fixing the cache."), 4)
            return

        try:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Fixing cache format..."), 2)

            # fixed, removed = fix_cache_format(remove_duplicates=True, remove_unmatched=True)
            fixed, removed = fix_cache_format(
                remove_duplicates=True, remove_unmatched=True, remove_invalid=True)

            if fixed == 0 and removed == 0:
                message = _(
                    "Cache is already in correct format. No changes needed.")
            else:
                message_lines = []
                message_lines.append(_("Cache format fix completed:"))
                if fixed > 0:
                    message_lines.append(
                        _("  - {} entries updated").format(fixed))
                if removed > 0:
                    message_lines.append(
                        _("  - {} duplicate entries removed").format(removed))
                message = "\n".join(message_lines)

            self.session.open(
                MessageBox,
                message,
                MessageBox.TYPE_INFO,
                timeout=5
            )
            debug(
                "fix_cache_format completed: fixed={}, removed={}".format(
                    fixed, removed))

        except Exception as e:
            debug("Error in fix_cache_format: {}".format(e))
            self.session.open(
                MessageBox,
                _("Error fixing cache: {}").format(str(e)),
                MessageBox.TYPE_ERROR,
                timeout=5
            )
        finally:
            export_lock.release()

    def reload_bouquets_with_popup(self):
        """Reload bouquets with confirmation popup"""
        _shared_reload_bouquets_with_popup(self)

    def _confirm_reload_bouquets(self, result):
        """Callback after user confirmation"""
        _shared_confirm_reload_bouquets(self, result)

    def closex(self):
        debug("Exit from plugin. Cleaning up plugin timers...")
        self._closed = True
        if ACTIVE.get("main") is self:
            ACTIVE["main"] = None
        # the PIN is asked again next time (the app: relock())
        vavoo_store.relock()
        if is_stats_enabled():
            stop_heartbeat()
            print("[Stats] Heartbeat fermato")

        try:
            if hasattr(self, 'proxy_monitor_timer'):
                self.proxy_monitor_timer.stop()
            if hasattr(self, 'proxy_watchdog_timer'):
                self.proxy_watchdog_timer.stop()
            if hasattr(self, '_update_popup_timer'):
                self._update_popup_timer.stop()
            if hasattr(self, '_country_retry_timer'):
                self._country_retry_timer.stop()
            if hasattr(self, '_guide_preload_timer'):
                self._guide_preload_timer.stop()
        except Exception as e:
            print("[Close] Error stopping timers: %s" % str(e))

        try:
            cleaned = cleanup_old_temp_files(max_age_hours=1)
            print("[Cleanup] Removed %d temporary files" % cleaned)
        except Exception as e:
            print("[Cleanup] Error: %s" % str(e))

        # A channel left playing in the preview window stops, and what
        # the box played before the plugin opened comes back.
        try:
            NOW_PLAYING.preview_stop(self.session, restore=True)
        except Exception as e:
            print("[Close] Error restoring the service: %s" % str(e))

        # Reload bouquets in background without popup
        try:
            db = eDVBDB.getInstance()
            db.reloadBouquets()
            db.reloadServicelist()
            print("Bouquets reloaded successfully")
        except Exception as e:
            print("Error during service reload: " + str(e))
            ReloadBouquets(500)

        self.close()

    def _proxy_watchdog_check(self):
        """Watchdog to check if the proxy is still alive"""
        try:
            if is_proxy_running() and not serving_here() and \
                    not is_proxy_booting():
                # the port answers, but another copy's proxy (the list
                # reads this copy's): run_proxy_in_background() takes
                # the port over
                print("[Watchdog] The port answers, but not this copy's "
                      "proxy - taking over")
                self['proxy_status'].setText(_("Starting the proxy..."))
                run_proxy_in_background()
                return
            # (the port itself: the real proof that the server answers)
            if not is_proxy_running():
                if is_proxy_booting():
                    # starting: nothing to restart, it opens when its
                    # catalog is in
                    self['proxy_status'].setText(_("Loading channels..."))
                    return
                print("[Watchdog] Proxy not running, attempting restart...")
                if run_proxy_in_background():
                    print("[Watchdog] Proxy start requested")
                    self['proxy_status'].setText(_("Starting the proxy..."))
                else:
                    print("[Watchdog] Proxy restart failed")
                    self['proxy_status'].setText(_("✗ Restart Failed"))

        except Exception as e:
            print("[Watchdog] Error: " + str(e))

    def _check_and_update_proxy_status(self):
        """Check and update the proxy status periodically"""
        try:
            self._update_proxy_status_display()
            self._follow_catalog()
        except Exception as e:
            print(
                "[MainVavoo][_check_and_update_proxy_status] Error in proxy monitor: " +
                str(e))
            self['proxy_status'].setText(_("✗ Proxy Error"))

    def _update_proxy_status_display(self):
        """Internal method to update proxy status display"""
        _shared_update_proxy_status_display(self)

    GUIDE_PRELOAD_AFTER_MS = 15000

    def _schedule_guide_preload(self):
        """Once per opening, 15 s after the list is up: the guides of the
        favourites' countries (then the recently watched ones) loaded
        in the background, so their Now / Next and the guide open at
        once (vUtils.preload_epg_guides(): at most 2, never with little
        memory, never while the player is open)."""
        if getattr(
            self,
            "_guide_preload_done",
                False) or not cfg.list_epg.value:
            return
        self._guide_preload_done = True
        timer = self._guide_preload_timer = eTimer()
        try:
            timer.callback.append(self._preload_guides)
        except Exception:
            timer.timeout.connect(self._preload_guides)
        timer.start(self.GUIDE_PRELOAD_AFTER_MS, True)

    def _preload_go_on(self):
        # never while a stream plays - the preview, the player, or a
        # bouquet channel outside the plugin (vUtils.stream_playing():
        # the proxy was asked for one lately): the guides then load
        # when they are needed, and give way to it (_Breather)
        return not self._closed and not vUtils.stream_playing() and \
            NOW_PLAYING.owner != NOW_PLAYING.PLAYER and \
            ACTIVE.get("player") is None

    def _preload_guides(self):
        if not self._preload_go_on():
            return

        def _work():
            try:
                vUtils.preload_epg_guides(
                    guide_countries(), go_on=self._preload_go_on)
            except Exception as e:
                print("[MainVavoo] Guides not loaded ahead: {}".format(e))

        worker = threading.Thread(target=named(_work, "vv-preload"))
        worker.daemon = True
        worker.start()

    def _follow_catalog(self):
        """The list was made from the saved catalog and the new one has
        come in behind it (the proxy's catalog_version moved): the
        countries and counts again, quietly - _on_countries_response()
        keeps the highlighted row."""
        state = get_proxy_status() or {}
        version = state.get("catalog_version")
        seen = getattr(self, "_catalog_seen", None)
        if not state.get(
                "ready") or version is None or seen is None or version == seen:
            return
        if getattr(
                self,
                "_reloading",
                False) or not getattr(
                self,
                "cat_list",
                None):
            return
        print(
            "[MainVavoo] New catalog in (version %s): list updated" %
            version)
        self.cat()

    def refresh_proxy(self):
        """Force proxy refresh"""
        try:
            self.session.openWithCallback(
                self._refresh_proxy_callback,
                MessageBox,
                _("Force proxy refresh?") + "\n" +
                _("This will refresh the authentication token."),
                MessageBox.TYPE_YESNO)
        except Exception as e:
            print("[MainVavoo][refresh_proxy] Refresh proxy error: " + str(e))

    def _refresh_proxy_callback(self, result):
        """Yes: the proxy asks for a new token - in a thread (the
        request goes on to Vavoo: seconds; on the GUI thread the box
        froze meanwhile), the answer back in _on_token_refreshed()."""
        if not result or self._closed:
            return

        def _work():
            ok, error = False, None
            try:
                response = getUrl(PROXY_REFRESH_URL, timeout=5, retries=1)
                if response:
                    data = loads(ensure_str(response))
                    ok = data.get("status") == "success"
            except Exception as e:
                error = e
            reactor.callFromThread(self._on_token_refreshed, ok, error)

        worker = threading.Thread(target=named(_work, "vv-token"))
        worker.daemon = True
        worker.start()

    def _on_token_refreshed(self, ok, error=None):
        if self._closed:
            return
        if error is not None:
            print("[Refresh Proxy] Error: " + str(error))
            self.session.open(
                MessageBox, _("Failed to refresh proxy: ") + str(error),
                MessageBox.TYPE_ERROR, timeout=3)
        elif ok:
            self.session.open(
                MessageBox, _("Proxy token refreshed successfully"),
                MessageBox.TYPE_INFO, timeout=3)
            self._update_proxy_status_display()
        else:
            self.session.open(
                MessageBox, _("Failed to refresh proxy token"),
                MessageBox.TYPE_ERROR, timeout=3)

    def _check_update_popup_tick(self):
        """Poll for the background update check (kicked off during the
        splash screen by _start_update_check()) to finish, then show the
        popup - once per launch, and only if an actual update is found -
        now that the main menu is open. Silent otherwise: no "already
        latest" / "check failed" noise on every plugin start.
        """
        global _update_popup_shown
        if not _update_check_done:
            return
        self._update_popup_timer.stop()
        if _update_popup_shown:
            print("[Update] Popup tick fired but popup already shown - skipping")
            return
        _update_popup_shown = True

        remote_version, changelog, content = _update_check_result or (
            None, None, None)
        newer = bool(remote_version) and is_remote_version_newer(
            __version__, remote_version)
        print("[Update] Popup tick: local=v{} remote={} newer={}".format(
            __version__, remote_version, newer))
        if not newer:
            return
        print("[Update] Opening update popup")

        # Stashed for _on_update_confirmed() so a Yes doesn't need a
        # second fetch of the same file.
        self._pending_installer_content = content
        try:
            self.session.openWithCallback(
                self._on_update_confirmed,
                UpdatePopup,
                remote_version,
                changelog
            )
        except Exception as e:
            # UpdatePopup's skin file may be missing/corrupt on this
            # install (e.g. a manually-deployed copy that skipped the
            # skin/ folder) - fall back to a plain MessageBox rather than
            # taking down the main menu over a cosmetic dialog.
            print(
                "[Update] UpdatePopup failed to open ({}), falling back to MessageBox".format(e))
            message = _("New version available: v{}").format(remote_version)
            message += "\n" + _("(you have v{})").format(__version__)
            if changelog:
                message += "\n\n" + _("Changelog:") + "\n" + changelog
            message += "\n\n" + _("Update now?")
            self.session.openWithCallback(
                self._on_update_confirmed,
                MessageBox,
                message,
                MessageBox.TYPE_YESNO,
                default=False
            )

    def _on_update_confirmed(self, result):
        content = getattr(self, '_pending_installer_content', None)
        self._pending_installer_content = None
        if not result or not content:
            return

        installer_path = "/tmp/vavoo_installer_update.sh"
        try:
            with open(installer_path, 'w') as f:
                f.write(content)
        except Exception as e:
            print("[MainVavoo] Error writing installer script: " + str(e))
            self.session.open(
                MessageBox,
                _("Could not save the installer script."),
                MessageBox.TYPE_ERROR,
                timeout=5
            )
            return

        self.session.open(
            Console,
            title=_("Updating Vavoo Stream Live..."),
            cmdlist=["chmod +x '{0}' && '{0}'".format(installer_path)]
        )

    def start_vavoo_proxy(self):
        # If the proxy is already active and working, do nothing
        if is_proxy_running() and is_proxy_ready(timeout=1):
            print("[MainVavoo] Proxy already ready")
            self._update_proxy_status_display()
            return True

        # If it is running but not ready, let it stabilize - this
        # copy's own proxy, or a start in progress (another copy's on
        # the port is taken over below: the list reads this one's)
        if is_proxy_running() and (serving_here() or is_proxy_booting()):
            print("[MainVavoo] Proxy running but not ready, waiting...")
            self._wait_for_proxy()
            return True

        print("[MainVavoo] Starting proxy...")
        success = run_proxy_in_background()
        if success:
            self._wait_for_proxy()
        return success

    def _wait_for_proxy(self, attempts=0):
        if self._closed:
            return
        # ConfigSelectionNumber.value has been confirmed (via a user log)
        # to come back as a str rather than an int on at least some
        # images/Python versions - "str" * 2 doesn't raise, it silently
        # repeats the string ("30" -> "3030"), which then compares
        # against attempts (always an int) in a way that never behaves
        # as the intended numeric timeout.
        try:
            timeout_secs = int(cfg.proxy_startup_timeout.value)
        except (TypeError, ValueError):
            timeout_secs = 30
        max_attempts = timeout_secs * 2   # ogni 0.5 sec
        if attempts > max_attempts:
            print(
                "[MainVavoo] Proxy not ready after {} seconds".format(timeout_secs))
            return
        if is_proxy_ready(timeout=0.5):
            print("[MainVavoo] Proxy ready")
            self._update_proxy_status_display()
        else:
            reactor.callLater(0.5, lambda: self._wait_for_proxy(attempts + 1))

    def cat(self):
        """
        Load and display the country list.
        Uses the local proxy if available, otherwise waits and retries.
        """
        self.cat_list = []
        self.items_tmp = []

        # If proxy is not ready yet, schedule a quick retry. "Booting"
        # counts as not ready even while the port still answers: right
        # after a restart was requested (e.g. a changed catalog source
        # in the settings), the old proxy keeps serving its old
        # catalog for a moment before it goes down.
        if is_proxy_booting() or not is_proxy_ready(timeout=0.5):
            self._note_proxy_wait()
            self._retry_cat_later()
            return
        self._wait_since = None
        # the catalog these counts come from (_follow_catalog())
        self._catalog_seen = (get_proxy_status() or {}).get("catalog_version")

        # getUrl() below can block for tens of seconds (default
        # retries=3 with backoff) on a slow/unresponsive proxy -
        # fetch it off the GUI/reactor thread (same pattern
        # _fetch_countries_async() already proves out for the M3U
        # wizard) so a flaky proxy can't freeze the whole box while
        # the main menu is loading, same as every other screen opening
        # for the first time.
        def _task():
            if self._closed:
                return
            exc = None
            response = None
            try:
                response = getUrl(PROXY_COUNTRIES_URL, timeout=10)
            except Exception as e:
                exc = e
            if self._closed:
                return
            # The main list's extras, worked out here and not on the
            # GUI thread: channels per country (sources of a channel
            # counted once, as the country's own list shows them) and
            # how many favourites there are.
            counts = {}
            if response:
                try:
                    counts = vavoo_proxy.proxy.country_counts(
                        cfg.group_sources.value)
                except Exception as e:
                    debug("Channel counts not available: {}".format(e))
            favourite_count = len(vUtils.load_favourites())
            recent = vUtils.load_recent()
            try:
                # the timers and the recordings on the disk (this is a
                # background thread: the disk may be slow to wake)
                reminders = len(vavoo_store.load_timers()) + len(
                    vavoo_record.list_recordings(
                        recordings_folder(), RECORDINGS.active_paths()))
            except Exception:
                reminders = 0
            reactor.callFromThread(
                self._on_countries_response, response, exc, counts,
                favourite_count, recent, reminders)

        t = threading.Thread(target=_task)
        t.daemon = True
        t.start()

    def _note_proxy_wait(self):
        """cat() waits for the proxy (every 0.5 s): one log line when it
        starts waiting and one every 30 s with why, not two a second;
        every 15 s run_proxy_in_background() (nothing when a start is in
        progress or this copy's proxy serves - it starts one that
        died, and takes the port over from another copy's)."""
        now = time.time()
        if self._wait_since is None:
            self._wait_since = self._wait_logged = self._wait_kicked = now
            print("[MainVavoo] Proxy not ready, waiting ({})".format(
                self._proxy_wait_reason()))
            return
        if now - self._wait_logged >= 30:
            self._wait_logged = now
            print("[MainVavoo] Still waiting for the proxy ({} s, {})".format(
                int(now - self._wait_since), self._proxy_wait_reason()))
        if now - self._wait_kicked >= 15:
            self._wait_kicked = now
            try:
                run_proxy_in_background()
            except Exception as e:
                print("[MainVavoo] Proxy start failed: {}".format(e))

    def _proxy_wait_reason(self):
        if is_proxy_booting():
            return "starting"
        if not is_proxy_running():
            return "no proxy on the port"
        if not serving_here():
            return "the port is another copy's proxy"
        return "no catalog yet"

    def _retry_cat_later(self):
        """Run cat() again in 500ms (single shot)."""
        if not hasattr(self, '_country_retry_timer'):
            self._country_retry_timer = eTimer()
            try:
                self._country_retry_timer.callback.append(self.cat)
            except Exception:
                # Fallback in case the callback attribute does not exist
                self._country_retry_timer.timeout.connect(self.cat)
        self._country_retry_timer.start(500, True)

    def _on_countries_response(self, response, exc, counts=None,
                               favourite_count=0, recent=None, reminders=0):
        if self._closed:
            return
        try:
            if exc is not None:
                raise exc
            if response:
                countries = loads(ensure_str(response))
                print(
                    "[MainVavoo] Got {} countries from proxy".format(
                        len(countries)))
                # Keep the highlight where it was (back from a country,
                # the settings, a reload) instead of jumping to the top.
                selected_link = None
                try:
                    current = self['menulist'].getCurrent()
                    selected_link = current[0][1] if current else None
                except Exception:
                    pass
                counts = counts or {}
                show_counts = cfg.show_counts.value
                self.countries = sorted(countries)
                self.cat_list = []
                if favourite_count:
                    # The app's first row: the favourites.
                    label = _("★ Favourites")
                    self.cat_list.append(show_list(
                        label, FAVOURITES_ROW, is_category=True,
                        display="{} ({})".format(label, favourite_count)
                        if show_counts else label,
                        themed=self._themed))
                if recent:
                    # The app's second row: the recently watched.
                    label = _("Recently watched")
                    self.cat_list.append(show_list(
                        label, RECENT_ROW, is_category=True,
                        display="{} ({})".format(label, len(recent))
                        if show_counts else label,
                        themed=self._themed))
                if reminders:
                    # The app's third row: Recordings (timers and
                    # recordings), while there are any.
                    label = _("Recordings")
                    self.cat_list.append(show_list(
                        label, REMINDERS_ROW, is_category=True,
                        display="{} ({})".format(label, reminders)
                        if show_counts else label,
                        themed=self._themed))
                # (the hidden ones out: Choose countries)
                for country in vavoo_store.visible_countries(self.countries):
                    count = counts.get(to_text(country).lower())
                    self.cat_list.append(show_list(
                        country, country,
                        display="{} ({})".format(to_string(country), count)
                        if show_counts and count else None,
                        themed=self._themed,
                        # a padlock on a locked country (the app's 🔒)
                        value_icon=vavoo_store.is_country_locked(country)))
                if not self.countries:
                    # no list at all (the catalog source not answering):
                    # say why, and OK does something about it
                    self.cat_list.append(show_list(
                        no_channels_text(get_proxy_status(),
                                         cfg.catalog_source.value),
                        NO_CHANNELS_ROW, is_category=True,
                        themed=self._themed))
                self._channel_total = sum(counts.values()) if counts else None
                self._update_ui()
                if selected_link:
                    for index, row in enumerate(self.cat_list):
                        if row[0][1] == selected_link:
                            self['menulist'].moveToIndex(index)
                            break
                self["version"].setText(to_string("V." + __version__))
                if self._reloading:
                    self._reloading = False
                    if NOTIFICATION_AVAILABLE and self._channel_total:
                        quick_notify(
                            _("Channel list updated: {} channels").format(
                                self._channel_total), 4)
                    elif NOTIFICATION_AVAILABLE:
                        # (why: "✗ No channels - Vavoo: HTTP 500")
                        quick_notify(to_string(proxy_status_text(
                            get_proxy_status())), 6)
                    self._update_proxy_status_display()
                if not self._start_last_done:
                    self._start_last_done = True
                    if recent:
                        self._open_channel(recent[0])
                pending = ACTIVE.get("pending")
                if pending:
                    # a reminder's "watch it" opened the plugin
                    ACTIVE["pending"] = None
                    self._open_channel(pending)
                self._schedule_guide_preload()
                self._country_load_failures = 0
                # Clear the retry timer if it exists
                retry_timer = self.__dict__.pop('_country_retry_timer', None)
                if retry_timer is not None:
                    retry_timer.stop()
                return
            else:
                # The proxy is the only source of the country list -
                # ask it again a few times before giving up. (This
                # used to fall back to vavoo.to/kool.to's old
                # "/channels" listing, which no longer exists - both
                # answer 404 - so all it did was add ~10 seconds
                # before showing nothing.)
                self._country_load_failures += 1
                print("[MainVavoo] Proxy countries request failed "
                      "(attempt {})".format(self._country_load_failures))
                if self._country_load_failures < 5:
                    self._retry_cat_later()
                else:
                    self._country_load_failures = 0
                    self["name"].setText(
                        _("Could not load the country list from the proxy"))
        except Exception as e:
            print("[MainVavoo] Error in cat(): %s" % str(e))
            trace_error()
            self["name"].setText(to_string("Error loading data"))

    def ok(self):
        try:
            current_item = self['menulist'].getCurrent()
            if not current_item or len(current_item) == 0:
                print("DEBUG: No current item selected or item is empty")
                return

            name = current_item[0][0]  # Country name (e.g., "Italy")
            if current_item[0][1] == FAVOURITES_ROW:
                self.open_favourites()
                return
            if current_item[0][1] == RECENT_ROW:
                self.session.openWithCallback(
                    self._on_child_closed, VavooFavourites,
                    VavooFavourites.MODE_RECENT)
                return
            if current_item[0][1] == REMINDERS_ROW:
                self.open_recordings()
                return
            if current_item[0][1] == NO_CHANNELS_ROW:
                self._no_channels_ok()
                return
            print("[MainVavoo] Selected: " + str(name))

            _require_parental_pin(
                self.session, self, name,
                lambda: self._open_country(name))

        except Exception as e:
            print("Error in ok method: " + str(e))
            trace_error()

    def _open_country(self, name):
        # Pass ONLY the country name to the vavoo class
        # The vavoo class will handle the proxy internally
        try:
            if not is_proxy_running():
                self.session.open(
                    MessageBox,
                    _("Proxy is not running. Please start the proxy first.") +
                    "\n" +
                    _("You can start it from the menu or by pressing the TEXT button."),
                    MessageBox.TYPE_WARNING,
                    timeout=5)
                return

            # Pass ONLY the country name to the vavoo class. Filled
            # again on return: favourites may have been added there.
            self.session.openWithCallback(
                self._on_child_closed, vavoo, name, None)
        except Exception as e:
            print("Error opening vavoo screen: " + str(e))
            trace_error()

    def _on_child_closed(self, *args, **kwargs):
        """Back from a country, the Favourites or a search: the
        favourites row may have changed."""
        if not self._closed:
            self.cat()

    # ---- the app's colour keys and MENU / INFO

    def open_favourites(self):
        """GREEN / the "★ Favourites" row."""
        if not vUtils.load_favourites():
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("No favourites yet. Open a country and press "
                               "GREEN on a channel."), 4)
            return
        self.session.openWithCallback(self._on_child_closed, VavooFavourites)

    def search_all(self):
        """YELLOW: search every shown country's channels (the app's
        search from its main screen) - read in-process from the proxy
        (VavooProxy.channel_rows()), in the background, then the search
        opens. Hidden countries are left out (Choose countries)."""
        countries = vavoo_store.visible_countries(self.countries)
        if not countries:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("The channel list is still loading..."), 3)
            return
        if self._search_loading:
            return
        self._search_loading = True
        grouped = cfg.group_sources.value

        def _task():
            items = []
            for country in countries:
                if self._closed:
                    return
                try:
                    channels = vavoo_proxy.proxy.channel_rows(
                        country, grouped)
                except Exception as e:
                    debug("Search: no channels for {}: {}".format(country, e))
                    continue
                for channel in channels or []:
                    name, url = channel.get("name"), channel.get("url")
                    if name and url:
                        # VavooSearch's "name###url" plus the country,
                        # for the PIN and the programme guide.
                        items.append("###".join((
                            to_string(name), to_string(url),
                            to_string(country))))
            if not self._closed:
                reactor.callFromThread(self._open_search_all, items)

        worker = threading.Thread(target=named(_task, "vv-search"))
        worker.daemon = True
        worker.start()

    def _open_search_all(self, items):
        self._search_loading = False
        if self._closed:
            return
        if not items:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("The channel list is still loading..."), 4)
            return
        self.session.openWithCallback(
            self._on_search_all_result, VavooSearch, self, items,
            scope=_("all channels"))

    def _on_search_all_result(self, selected_item=None):
        if not selected_item or self._closed:
            return
        play_search_result(self.session, self, selected_item,
                           self._on_child_closed)

    def _open_channel(self, channel):
        """One channel full screen from the main menu (a search result,
        "Start with last channel"). A channel of a locked country asks
        for the PIN, as opening that country would."""
        name, url = channel.get('name'), channel.get('url')
        if not name or not url:
            return

        def _play():
            self.session.openWithCallback(
                self._on_child_closed,
                Playstream2, name, url, 0, [name, url], [[[name, url]]],
                country_code=channel.get('country_code'),
                logo_url=channel.get('logo') or None,
                country_name=channel.get('country_name'),
                hand_back=cfg.preview_window.value)
        _require_parental_pin(
            self.session, self, channel.get('country_name'), _play,
            channel_name=name)

    def _no_channels_ok(self):
        """OK on the "No channels" row: the settings when the catalog
        source is pinned to one service (Auto then tries the other),
        else Reload List at once (the row said so - no question)."""
        if cfg.catalog_source.value in ("geil", "vavoo"):
            self.goConfig()
        else:
            self.reload_list(True)

    def reload_list(self, answer=None):
        """BLUE: download the channel list again (the app's Reload List).
        The proxy loads its catalog once, when it starts - so this
        restarts it; the list is filled again once it is back."""
        if answer is None:
            self.session.openWithCallback(
                self.reload_list,
                MessageBox,
                _("Reload the channel list?") + "\n" +
                _("The proxy restarts and downloads the list again. A channel "
                  "playing now stops for a moment."),
                MessageBox.TYPE_YESNO,
                default=True)
            return
        if not answer or self._closed:
            return
        self._reloading = True
        self['proxy_status'].setText(_("Reloading channel list..."))
        try:
            # a new catalog from the network, not the saved one
            restart_proxy_in_background(fresh=True)
        except Exception as e:
            print("[MainVavoo] Reload failed: {}".format(e))
            self._reloading = False
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Reload failed: {}").format(str(e)), 4)
            return
        # cat() waits while the proxy is restarting (is_proxy_booting()).
        self._retry_cat_later()

    def info_toast(self):
        """INFO: version, channels and countries (the app's INFO)."""
        if NOTIFICATION_AVAILABLE:
            quick_notify(
                info_text(
                    self._channel_total, len(
                        self.countries)), 5)

    def open_menu(self):
        """MENU: the settings and the Enigma2 tools that used to be on
        the colour keys."""
        entries = [
            (_("Settings"), "settings"),
            (_("Reload bouquets"), "reload_bouquets"),
            (_("Remove all Vavoo bouquets"), "remove_all"),
            (_("Import EPG now"), "epg_import"),
            (_("Fix EPG cache"), "fix_cache"),
            (_("Refresh token"), "refresh_token"),
            (_("Show Log"), "log"),
            (_("Factory reset"), "factory_reset"),
            (_("About"), "about"),
        ]
        actions = {
            "settings": self.goConfig,
            "reload_bouquets": self.reload_bouquets_with_popup,
            "remove_all": self.msgdeleteBouquets,
            "epg_import": self.manual_epg_update,
            "fix_cache": self._fix_cache_format,
            "refresh_token": self.refresh_proxy,
            "log": lambda: open_log_viewer(self.session),
            "factory_reset": self.factory_reset,
            "about": self.info,
        }
        open_action_menu(
            self.session, _("Menu"), entries,
            lambda key: actions[key]() if key in actions else None)

    def factory_reset(self):
        """MENU → Factory reset (ui_settings.ask_factory_reset()): then
        the plugin closes and opens again, at the welcome."""
        ask_factory_reset(self.session, self, self._after_factory_reset)

    def _after_factory_reset(self):
        if self._closed:
            # (left meanwhile: the welcome comes when it is opened)
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Factory reset done"), 4)
            return
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Factory reset done - starting again"), 4)
        session = self.session
        # opened again once this screen has really gone (Enigma2 closes
        # it after closex() returns)
        self.onClose.append(lambda: reactor.callLater(1.0, main, session))
        self.closex()

    def manual_epg_update(self):
        """Manually trigger EPG update"""
        if not cfg.epg_enabled.value:
            self.session.open(
                MessageBox,
                _("EPG is disabled. Please enable it in Vavoo settings first."),
                MessageBox.TYPE_INFO)
            return

        # Check if Vavoo EPG source file exists
        vavoo_sources = "/etc/epgimport/vavoo.sources.xml"
        if not isfile(vavoo_sources):
            self.session.open(
                MessageBox,
                _("Vavoo EPG source not found. Please export at least one bouquet first."),
                MessageBox.TYPE_INFO)
            return

        # Check if the source is enabled in EPGImport config. EPGIMPORT_CONF
        # is a binary serialized blob (EPGImport's own internal format, not
        # plain text), so it can't be read line-by-line, and it never
        # contains the source's filename ("vavoo.sources.xml") - EPGImport
        # records each enabled source by its <description> text instead,
        # which for every Vavoo-generated source starts with "Vavoo "
        # (write_epg_mapping_file() / update_epg_sources() in vUtils.py).
        # A raw substring search for that prefix is format-agnostic and
        # works regardless of the underlying serialization.
        source_enabled = False
        if isfile(EPGIMPORT_CONF):
            try:
                with open(EPGIMPORT_CONF, 'rb') as f:
                    source_enabled = b'Vavoo' in f.read()
            except Exception as e:
                print("[EPG] Error reading epgimport.conf: {}".format(e))

        if not source_enabled:
            self.session.open(
                MessageBox,
                _("Vavoo EPG source is not enabled in EPGImport. Please enable it in EPGImport settings."),
                MessageBox.TYPE_WARNING,
                timeout=5)
            return

        self.session.openWithCallback(
            self._epg_update_callback,
            MessageBox,
            _("Start EPG update now?"),
            MessageBox.TYPE_YESNO
        )

    def _epg_update_callback(self, answer):
        if not answer:
            return
        # There is no "epgimport" CLI binary on a normal Enigma2 image -
        # EPGImport is a GUI plugin, not a command-line tool, and
        # EPGImport.EPGImport itself isn't a Screen either - it's a plain
        # importer class. Plugins/Extensions/EPGImport/plugin.py (every
        # Enigma2 plugin has a lowercase plugin.py as its required entry
        # point) keeps a module-level startImport() that's the exact same
        # function EPGImport's own UI button calls, using a
        # already-constructed singleton importer - calling it directly
        # runs a real import with no screen/dialog of ours or theirs
        # involved. It kicks off its own async work (threads/reactor)
        # internally, same as EPGImport's own button does, so this can be
        # called directly from here without our own threading.
        try:
            from Plugins.Extensions.EPGImport.plugin import (
                epgimport, startImport, CONFIG_PATH)
            from Plugins.Extensions.EPGImport import EPGConfig
            if epgimport.isImportRunning():
                if NOTIFICATION_AVAILABLE:
                    quick_notify(_("EPG import already running"), 3)
                return
            # epgimport.beginImport() (called by startImport()) requires
            # epgimport.sources to already be populated - its own
            # docstring says so ("Set self.sources before calling
            # this"). EPGImport's own UI only ever calls startImport()
            # from EPGImportConfig.doimport(), which builds that list
            # from the user's enabled-sources settings first; calling
            # startImport() directly skips that step, so with an empty
            # source list nextImport() just closes the import right
            # away - "0 events imported" with no error, since nothing
            # was actually queued to import in the first place.
            epg_user_cfg = EPGConfig.loadUserSettings()
            sources = list(
                EPGConfig.enumSources(
                    CONFIG_PATH, filter=epg_user_cfg["sources"]))
            if not sources:
                self.session.open(
                    MessageBox,
                    _("No active EPG sources found in EPGImport. "
                      "Please enable the Vavoo source in EPGImport settings."),
                    MessageBox.TYPE_INFO,
                    timeout=5)
                return
            sources.reverse()
            epgimport.sources = sources
            startImport()
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("EPG import started"), 3)
        except ImportError as e:
            print("[Vavoo] EPG update error:", str(e))
            self.session.open(
                MessageBox,
                _("EPGImport plugin not found: {}").format(str(e)),
                MessageBox.TYPE_ERROR)
        except Exception as e:
            print("[Vavoo] EPG update error:", str(e))
            self.session.open(
                MessageBox, _("Error starting EPG update: {}").format(
                    str(e)), MessageBox.TYPE_ERROR)

    def msgdeleteBouquets(self):
        message_parts = []
        message_parts.append(_("Remove ALL Vavoo bouquets?"))
        message_parts.append(_("This will remove:"))
        message_parts.append(_("- Country bouquets"))
        message_parts.append(_("- Category bouquets"))
        message_parts.append(_("- Container bouquets"))
        message = "\n".join(message_parts)

        self.session.openWithCallback(
            self.deleteBouquets,
            MessageBox,
            message,
            MessageBox.TYPE_YESNO,
            timeout=10,
            default=True)

    def deleteBouquets(self, result):
        """Delete all Vavoo bouquets"""
        if result:
            # Same lock message2()'s export uses - deleting every bouquet
            # while an export's background thread is still writing one of
            # them can corrupt it.
            if not export_lock.acquire(False):
                if NOTIFICATION_AVAILABLE:
                    quick_notify(
                        _("An export for another country is already in progress. Please wait."), 4)
                return
            try:
                removed_count = remove_bouquets_by_name()

                # Remove the bouquet list (Favorite.txt before)
                favorite_path = vavoo_store.bouquet_list_file()
                if isfile(favorite_path):
                    remove(favorite_path)
                    print("✓ Removed the bouquet list")

                # Build message safely for translation
                message = _("Vavoo bouquets removed successfully!")
                message += "\n"
                message += _("(%s files deleted)") % removed_count

                self.session.open(
                    MessageBox,
                    message,
                    MessageBox.TYPE_INFO,
                    timeout=5
                )
                try:
                    db = eDVBDB.getInstance()
                    db.reloadBouquets()
                    db.reloadServicelist()
                    print("Bouquets reloaded successfully")
                except Exception as e:
                    print("Error during service reload: " + str(e))
                    ReloadBouquets(500)

            except Exception as e:
                print("Error in deleteBouquets: " + str(e))
            finally:
                export_lock.release()

    def goConfig(self):
        open_settings(self.session, self._on_config_closed)

    def _on_config_closed(self, *args, **kwargs):
        """Back from the settings screen: make sure the proxy is up,
        restart the status timers and reload the country list (the
        catalog source may have changed)."""
        try:
            self.start_vavoo_proxy()
            self.proxy_watchdog_timer.start(PROXY_WATCHDOG_INTERVAL_MS)
            self.proxy_monitor_timer.start(PROXY_MONITOR_INTERVAL_MS)

            self["proxy_status"].setText(_("Checking proxy..."))
            try:
                self._update_proxy_status_display()
            except Exception as e:
                debug("_update_proxy_status_display failed, label may "
                      "stay stuck on 'Checking proxy...': {}".format(e))

            self.cat()
        except Exception as e:
            print("[MainVavoo] Error refreshing after settings: " + str(e))

    def info(self):
        """Display plugin information"""
        show_about(self.session)

    def chUp(self):
        """Handle page up and update name"""
        try:
            if self.cat_list:
                self['menulist'].pageUp()
                print("DEBUG chUp: " + self['name'].getText())
        except Exception as e:
            print("Error in chUp:", e)

    def chDown(self):
        """Handle page down and update name"""
        try:
            if self.cat_list:
                self['menulist'].pageDown()
                print("DEBUG chDown: " + self['name'].getText())
        except Exception as e:
            print("Error in chDown:", e)

    def moveUp(self):
        """Move selection up, wrapping from the first entry to the last."""
        if not self.cat_list:
            return
        idx = self['menulist'].getSelectedIndex()
        self['menulist'].moveToIndex((idx - 1) % len(self.cat_list))

    def moveDown(self):
        """Move selection down, wrapping from the last entry to the first."""
        if not self.cat_list:
            return
        idx = self['menulist'].getSelectedIndex()
        self['menulist'].moveToIndex((idx + 1) % len(self.cat_list))

    def _update_ui(self):
        """Update the UI with current list"""
        try:
            if self.cat_list and len(self.cat_list) > 0:
                self["menulist"].l.setList(self.cat_list)
                self._update_selection_name()
            else:
                self["name"].setText(_("No items available"))
                self.cat_list = []
        except Exception as e:
            print("Error updating UI:", e)
            self["name"].setText(_("Error"))
            self.cat_list = []

    def _update_selection_name(self):
        """Update the name label with current selection"""
        try:
            current = self['menulist'].getCurrent()
            if current and len(current) > 0:
                name = current[0][0]
                self['name'].setText(to_string(name))
                print("MainVavoo _update_selection_name: " + to_string(name))
            else:
                self['name'].setText(_("No selection"))  # fallback
        except Exception as e:
            print("Error in MainVavoo _update_selection_name:", e)
            self['name'].setText(_("Error"))


class vavoo(Screen, NowNextPanel, PreviewWindow):
    """A country's channels (the app's ChannelsActivity). With
    Sub-categories on and two or more catalog categories, the country
    first lists "All channels", its categories A-Z and "General"; OK
    opens one in a new screen of this class (`category`, with the
    country's `channels` already loaded - no second proxy request)."""

    CATEGORY_ALL = "\x00all"
    CATEGORY_GENERAL = "\x00general"
    _closed = True          # (ui_base's CLOSED_UNTIL_OPEN)

    def __init__(self, session, name, url, option_value=None,
                 category=None, channels=None):
        # So a bouquet-export background thread still running when the
        # user exits this screen (Screen.close() doesn't clear
        # self.session, so that alone can't be used to detect this) can
        # notice and skip touching this screen's UI/state afterward.
        self._closed = False
        self.session = session
        self.category = category
        self._preloaded = channels
        # every channel of the country (the proxy's rows), for the
        # categories and the search
        self._all_channels = []
        self.showing_categories = False
        self.category_keys = []
        self._digits = ""
        self._digit_time = 0
        global _session
        _session = session

        Screen.__init__(self, session)
        init_notification_system(session)
        self._load_skin()
        # The favourites' addresses (vUtils.favourite_urls()), for the status
        # line's star and the GREEN key's caption - read again whenever
        # this screen is back on top.
        self._favourite_keys = set()
        self._proxy_down = False
        self._initialize_labels()
        self._initialize_actions()
        self._preview_init()
        self["menulist"].onSelectionChanged.append(self._update_selection_name)
        self["menulist"].onSelectionChanged.append(self._epg_panel_changed)
        self.onExecBegin.append(self._reload_favourite_keys)
        self.currentList = 'menulist'

        # Store country name properly
        self.country_name = name
        # For the Now/Next panel - same lookup play_that_shit() does.
        try:
            self._epg_country_code = get_country_code(name)
        except Exception:
            self._epg_country_code = ""
        self.name = name
        self.url = url
        self.option_value = option_value

        # (name, url, logo_url) per currently-listed channel, parallel
        # to cat_list - lets _refresh_channel_list_with_picons()
        # rebuild the list once more picons have been cached, without
        # re-fetching the channel data over the network.
        self._channel_entries = []
        self.picon_refresh_timer = eTimer()
        try:
            self.picon_refresh_timer.callback.append(
                self._refresh_channel_list_with_picons)
        except Exception:
            self.picon_refresh_timer.timeout.connect(
                self._refresh_channel_list_with_picons)

        # Do NOT try to initialize proxy here - it should already be running
        # Just verify it's ready
        self._verify_proxy_ready()

        self._initialize_timer()
        self._initialize_proxy_status_timer()

    def _initialize_proxy_status_timer(self):
        """Watch the proxy while this screen is open. The status line
        is the app's position line ("Portugal · 12/174") - only if the
        proxy goes away does it say so instead. A port check, no HTTP
        request on the GUI thread every 10 seconds."""
        self.proxy_status_timer = eTimer()
        try:
            self.proxy_status_timer.timeout.connect(self._check_proxy_alive)
        except BaseException:
            self.proxy_status_timer.callback.append(self._check_proxy_alive)
        self.proxy_status_timer.start(10000)

    def _check_proxy_alive(self):
        if self._closed:
            return
        down = not is_proxy_running()
        if down != self._proxy_down:
            self._proxy_down = down
            self._update_status_line()

    def _verify_proxy_ready(self):
        """Verify that the proxy is ready without attempting to start it"""
        try:
            if not is_proxy_ready(timeout=2):
                print(
                    "[vavoo] Warning: Proxy not ready for %s" %
                    self.country_name)
                # Do not start the proxy here – let the cat() method handle the
                # fallback
            self._proxy_down = not is_proxy_running()
            self._update_status_line()
        except Exception as e:
            print("[vavoo] Error checking proxy: %s" % str(e))

    def _load_skin(self):
        """Load the skin file."""
        self.skin, self._themed = load_screen_skin(
            "list", 'defaultListScreen.xml', cvs=True, clock_24=clock_24())

    def _initialize_labels(self):
        """Initialize the labels on the screen."""
        self.menulist = []
        self.cat_list = []
        self['menulist'] = m2list([], themed=self._themed)
        # The app's keys. Exporting / removing this country's bouquet
        # and reloading bouquets are in the MENU key's list now.
        self['red'] = Label(_('Back'))
        self['green'] = Label(_('Add Fav'))
        self['yellow'] = Label(_('Search'))
        self["blue"] = Label(_('Full Screen'))
        add_key_hint_labels(self)
        # INFO opens the programme guide here (as in the app)
        self['key_info'].setText("EPG")
        self['name'] = Label('Loading ...')
        self['version'] = Label()
        self["version"].setText(to_string("V." + __version__))
        self['proxy_status'] = Label('')
        self._epg_panel_init()

    def _reload_favourite_keys(self):
        self._favourite_keys = vUtils.favourite_urls()
        self._update_status_line()

    def _selected_row(self):
        """(index, name, url) of the highlighted channel, or Nones."""
        try:
            index = self['menulist'].getSelectedIndex()
            if index is None or not 0 <= index < len(self.cat_list):
                return None, None, None
            item = self.cat_list[index][0]
            return index, item[0], item[1]
        except Exception:
            return None, None, None

    def _update_status_line(self):
        """The app's status line, "Portugal · 12/174  ★" (the star when
        the highlighted channel is a favourite), and GREEN's caption:
        Add Fav or Remove Fav."""
        if self._closed:
            return
        try:
            if self._proxy_down:
                self['proxy_status'].setText(_("✗ Proxy Offline"))
                return
            index, name, url = self._selected_row()
            title = to_text(self._title())
            if index is None:
                self['proxy_status'].setText(to_string(title))
                return
            text = u"{} · {}/{}".format(title, index + 1, len(self.cat_list))
            if self.showing_categories:
                self['proxy_status'].setText(to_string(text))
                return
            favourite = to_text(url) in self._favourite_keys
            if favourite:
                text += u"  \u2605"
            self['proxy_status'].setText(to_string(text))
            self['green'].setText(
                _('Remove Fav') if favourite else _('Add Fav'))
        except Exception as e:
            debug("Status line not updated: {}".format(e))

    def _title(self):
        """"Italy", or "Italy ➾ Sport" in a category's screen."""
        if self.category is None:
            return self.country_name
        return u"{} \u27be {}".format(to_text(self.country_name),
                                      to_text(self._category_label(
                                          self.category)))

    def _category_label(self, key):
        if key == self.CATEGORY_ALL:
            return _("All channels")
        if key == self.CATEGORY_GENERAL:
            return _("General")
        return key

    def _epg_panel_selection(self):
        """See NowNextPanel."""
        if self.showing_categories:
            return None
        current = self['menulist'].getCurrent()
        if not current:
            return None
        name, url = current[0][0], current[0][1]
        country_code = getattr(self, '_epg_country_code', "")
        if not name or not country_code:
            return None
        return (name, url, country_code)

    def _initialize_actions(self):
        """Initialize the actions for buttons."""
        actions = {
            "prevBouquet": self.chDown,
            "nextBouquet": self.chUp,
            "up": self.moveUp,
            "down": self.moveDown,
            "ok": self.ok,
            "green": self.toggle_favourite,
            "yellow": self.search_vavoo,
            # "Full Screen": the highlighted channel straight into
            # the player (the app's BLUE); OK goes through the
            # preview window first.
            "blue": self.full_screen,
            "cancel": self.backhome,
            "menu": self.open_menu,
            # INFO / EPG: the programme guide (the app's)
            "info": self.info_key,
            "epg": self.info_key,
            "red": self.backhome
        }
        self["actions"] = ActionMap(
            [
                'MenuActions',
                'OkCancelActions',
                'ButtonSetupActions',
                'InfobarEPGActions',
                'ColorActions',
                'DirectionActions'
            ], actions, -1)
        self["epg_keys"] = info_page_keys(actions)
        # The direct keys (keymap.xml): FAV, PVR, TEXT, HELP, and PLAY /
        # STOP / REC on the highlighted channel
        self["list_keys"] = list_keys({
            "favourites": self.open_favourites,
            "recordings": lambda: self.session.open(VavooRecordings),
            "search": self.search_vavoo,
            "help": self.show_help,
            "play": self.full_screen,
            "stop": lambda: stop_preview(self.session),
            "record": self.record_highlighted,
            "back": self.backhome,
        })
        # The number keys go to that row (the app's numbered rows).
        self["number_actions"] = ActionMap(
            ['NumberActions'],
            dict((str(d), (lambda n: lambda: self.number(n))(d))
                 for d in range(10)),
            -1)

    def number(self, digit):
        """Typed within 1.5 s the digits add up (1, 2 = row 12); 0 with
        no number begun: the channel watched last (as in the player)."""
        now = time.time()
        if now - self._digit_time > 1.5:
            self._digits = ""
        if digit == 0 and not self._digits:
            play_last_watched(self.session, self, self._on_player_closed)
            return
        if not self.cat_list or self.showing_categories:
            return
        self._digit_time = now
        self._digits = (self._digits + str(digit))[-4:]
        target = int(self._digits) - 1
        if 0 <= target < len(self.cat_list):
            self['menulist'].moveToIndex(target)

    def _initialize_timer(self):
        """Initialize the timer with proper timeout handling"""
        self.timer = eTimer()
        try:
            self.timer.callback.append(self.cat)
        except BaseException:
            self.timer.timeout.connect(self.cat)
        self.timer.start(500, True)

    def cat(self):
        """Load this country's channels from the proxy.

        The fetch is a blocking getUrl() call and this runs from a
        GUI-thread eTimer every time a country is opened, so it runs
        in a background thread (same pattern _fetch_countries_async()
        already proves out for the M3U wizard) and only the actual
        list-building is marshalled back to the reactor thread.

        The proxy is the only source there is: a slow or empty answer
        is simply asked for again (CHANNEL_FETCH_ATTEMPTS short tries
        instead of one long one - a healthy proxy answers this from
        memory in milliseconds, so a try that hasn't answered within
        a few seconds isn't going to). This used to give up after a
        single 10-second timeout and fall back to vavoo.to/kool.to's
        old "/channels" listing, which no longer exists (both answer
        404) - so one hiccup cost about 20 seconds and ended on an
        empty screen, where simply asking again would have worked.
        """
        debug("vavoo.cat() called for country: " + str(self.country_name))
        if self._preloaded is not None:
            # a category's screen: the country's list came with it
            self._build_channel_list(self._preloaded)
            return

        def _task():
            if self._closed:
                return
            try:
                country_encoded = url_quote(self.country_name)
                proxy_url = PROXY_BASE_URL + \
                    "/channels?country={}".format(country_encoded)
                if not cfg.group_sources.value:
                    # every source its own row (the app's Group
                    # Sources off)
                    proxy_url += "&grouped=0"

                channels_data = None
                for attempt in range(CHANNEL_FETCH_ATTEMPTS):
                    if self._closed:
                        return
                    debug("Fetching from proxy: " + proxy_url)
                    try:
                        content = ensure_str(
                            getUrl(proxy_url, timeout=5, retries=1))
                        if content and content.strip() and content != "null":
                            channels_data = loads(content)
                            break
                    except Exception as proxy_error:
                        debug("[cat] Proxy error: " + str(proxy_error))
                    print("[vavoo] No channel list from proxy (attempt "
                          "{}/{})".format(attempt + 1, CHANNEL_FETCH_ATTEMPTS))
                    if attempt < CHANNEL_FETCH_ATTEMPTS - 1:
                        time.sleep(1)

                if self._closed:
                    return
                if channels_data is None:
                    reactor.callFromThread(self._on_channels_unavailable)
                else:
                    reactor.callFromThread(
                        self._build_channel_list, channels_data)

            except Exception as e:
                print("[ERROR] CRITICAL in cat(): " + str(e))
                trace_error()
                if not self._closed:
                    reactor.callFromThread(self._handle_cat_error, e)

        t = threading.Thread(target=_task)
        t.daemon = True
        t.start()

    def _on_channels_unavailable(self):
        """cat() got nothing from the proxy after all its tries."""
        if self._closed:
            return
        self['name'].setText(
            _("Could not load channels - proxy not responding"))

    def _build_channel_list(self, channels_data):
        """Build the rows from the proxy's list (cat()), or from the
        country's list a category screen was given."""
        # cat()'s background _task() already checks self._closed before
        # scheduling this via reactor.callFromThread, but that only
        # queues the call - the user can still press Back/Cancel (which
        # sets self._closed and tears the screen down) in the gap
        # before the reactor actually runs it.
        if self._closed:
            return
        self.cat_list = []
        self._channel_entries = []

        if not isinstance(channels_data, list):
            print("[vavoo] Invalid channels data type: " +
                  str(type(channels_data)))
            return
        self._all_channels = [
            c for c in channels_data if isinstance(c, dict) and c.get("url")]

        if self.category is None:
            # A favourite whose channel got a new id in the catalog:
            # found again by its name (vavoo_store.repair_favourites()).
            try:
                if vavoo_store.repair_favourites(
                        self.country_name,
                        [{"name": c.get("name"), "url": c.get("url"),
                          "logo": c.get("logo")}
                         for c in self._all_channels]):
                    self._favourite_keys = vUtils.favourite_urls()
            except Exception as e:
                debug("Favourites not repaired: {}".format(e))

        # The search always looks in the whole country (as in the app).
        self.itemlist = [
            "###".join((to_string(c.get("name", "")), to_string(c["url"])))
            for c in self._all_channels]

        categories = self._categories() \
            if self.category is None and cfg.subcategories.value else []
        if categories:
            self._show_categories(categories)
            return

        for channel in self._channels_in(self.category):
            # Already fixed up (Geil/Vavoo) by our own proxy's
            # /channels endpoint - no need to run it through
            # fix_logo_url() again here.
            self._channel_entries.append(
                (channel.get("name", "Unknown"), channel["url"],
                 channel.get("logo", "")))
        self.cat_list = self._channel_rows()

        if not self.cat_list:
            self['name'].setText(to_string("No proxy URLs built."))
            return

        self.update_menu()
        # Filling the list does not reliably announce a selection
        # change by itself - make sure the first row gets its panel
        # (and its status line).
        self._epg_panel_changed()
        self._update_status_line()
        self._preload_channel_picons()
        debug("List built with " + str(len(self.cat_list)) + " items.")

    def _category_of(self, channel):
        return to_text(channel.get("category") or "").strip() or \
            self.CATEGORY_GENERAL

    def _channels_in(self, category):
        if category is None or category == self.CATEGORY_ALL:
            return self._all_channels
        return [c for c in self._all_channels
                if self._category_of(c) == category]

    def _categories(self):
        """[(key, count)]: All channels, the categories A-Z, General
        last - or [] when the country has fewer than two."""
        counts = {}
        for channel in self._all_channels:
            key = self._category_of(channel)
            counts[key] = counts.get(key, 0) + 1
        if len(counts) < 2:
            return []
        keys = sorted(counts, key=lambda k: (k == self.CATEGORY_GENERAL,
                                             k.lower(), k))
        return [(self.CATEGORY_ALL, len(self._all_channels))] + \
            [(k, counts[k]) for k in keys]

    def _show_categories(self, categories):
        """The category rows, each with the country's flag."""
        self.showing_categories = True
        self.category_keys = [key for key, _count in categories]
        rows = []
        for key, count in categories:
            label = to_text(self._category_label(key))
            display = u"{} ({})".format(label, count) \
                if cfg.show_counts.value else label
            rows.append(show_list(to_string(self.country_name),
                                  to_string(key), display=to_string(display),
                                  themed=self._themed))
        self.cat_list = rows
        self.update_menu()
        self._epg_panel_changed()
        self._update_status_line()

    def _channel_rows(self):
        """The channel rows, numbered like a receiver's list."""
        total = len(self._channel_entries)
        digits = len(str(total))
        return [
            show_list(name, url, is_channel=True, logo_url=logo,
                      display=to_string(u"{}  {}".format(
                          row_number(i + 1, digits, u"\u2007"),
                          to_text(name))),
                      themed=self._themed)
            for i, (name, url, logo) in enumerate(self._channel_entries)]

    def _preload_channel_picons(self):
        """Download picons for this country's channel list in the
        background (see show_list()'s logo_url handling), then
        refresh the list once they land.

        Entirely on a background thread, including the first batch -
        this runs right after _build_channel_list() on the
        GUI/reactor thread itself, so a
        synchronous network call here would block the UI exactly the
        way this session's getUrl()-on-the-GUI-thread fixes were
        about avoiding. Downloads a first batch and refreshes the
        list so the visible screenful gets its picons quickly, then
        keeps going through the rest with one final refresh.
        """
        if not cfg.logos.value:
            # Channel Logos off: initials instead, nothing downloaded
            return
        entries = [
            entry for entry in self._channel_entries if entry[2]
        ]
        if not entries:
            return

        first_batch_size = 20

        def _download_batch(batch):
            count = 0
            for name, url, logo in batch:
                if self._closed:
                    break
                try:
                    success, _unused = download_picon_online(logo)
                    if success:
                        count += 1
                except Exception as e:
                    debug("Picon download failed for {}: {}".format(
                        name, e))
            return count

        def _worker():
            first = _download_batch(entries[:first_batch_size])
            if first > 0 and not self._closed:
                reactor.callFromThread(
                    self.picon_refresh_timer.start, 500, True)
            if len(entries) > first_batch_size and not self._closed:
                rest = _download_batch(entries[first_batch_size:])
                if rest > 0 and not self._closed:
                    reactor.callFromThread(
                        self.picon_refresh_timer.start, 500, True)

        t = threading.Thread(target=named(_worker, "vv-logos"))
        t.daemon = True
        t.start()

    def _refresh_channel_list_with_picons(self):
        """Rebuild the channel list from the already-fetched channel
        data (no new network fetch) so rows whose picon finished
        downloading since the list was first built pick it up."""
        if self._closed:
            return
        self.picon_refresh_timer.stop()
        if not self._channel_entries:
            return
        try:
            # setList() below replaces the whole list - preserve
            # wherever the user had scrolled to instead of silently
            # snapping back to the top under them.
            try:
                selected_index = self['menulist'].getSelectedIndex()
            except Exception:
                selected_index = None

            self.cat_list = self._channel_rows()
            self.update_menu()

            if selected_index is not None and self.cat_list:
                try:
                    self['menulist'].moveToIndex(
                        min(selected_index, len(self.cat_list) - 1))
                except Exception:
                    pass
        except Exception as e:
            print("[vavoo] Error refreshing picon list: %s" % str(e))

    def _handle_cat_error(self, e):
        """Handle cat() method errors"""
        print("[vavoo] Handling cat error: " + str(e))
        self['name'].setText(to_string("Error: " + str(e)))

        # Show message to user
        try:
            self.session.open(
                MessageBox,
                "Error loading channels: " + str(e)[:100],
                MessageBox.TYPE_ERROR,
                timeout=5
            )
        except Exception:
            pass

    def reload_bouquets_with_popup(self):
        """Reload bouquets with confirmation popup"""
        _shared_reload_bouquets_with_popup(self)

    def _confirm_reload_bouquets(self, result):
        """Callback after user confirmation"""
        _shared_confirm_reload_bouquets(self, result)

    def info_key(self):
        """INFO / EPG: the programme guide of the channels shown, from
        the highlighted one (on category rows: the info note)."""
        if self.showing_categories or not self._channel_entries:
            self.info_toast()
            return
        by_url = dict((c.get("url"), c) for c in self._all_channels)
        channels = []
        for name, url, logo in self._channel_entries:
            row = by_url.get(url) or {}
            channels.append({
                "name": name, "url": url, "logo": logo,
                "country_name": self.country_name,
                "country_code": getattr(self, '_epg_country_code', None),
                "category": row.get("category"),
                "epg_id": row.get("epg_id")})
        index = self['menulist'].getSelectedIndex() or 0
        self.session.openWithCallback(
            self._on_guide_closed, VavooGuide, channels, index,
            self._title())

    def _on_guide_closed(self, result=None):
        """"Watch" in the guide: that channel full screen."""
        if self._closed or not result or result[0] != "watch":
            return
        self['menulist'].moveToIndex(result[1])
        self.full_screen()

    def open_category(self):
        """OK on a category row: its channels in a new screen."""
        i = self['menulist'].getSelectedIndex()
        if i is None or not 0 <= i < len(self.category_keys):
            return
        self.session.open(vavoo, self.country_name, self.url,
                          self.option_value, category=self.category_keys[i],
                          channels=self._all_channels)

    def ok(self):
        """OK: the channel into the preview window; on the channel
        already playing there, full screen. On a category: open it."""
        if self.showing_categories:
            self.open_category()
            return
        try:
            i, name, url = self._selected_row()
            if i is None:
                return
            logo = (self._channel_entries[i][2]
                    if 0 <= i < len(self._channel_entries) else None)
            channel = {
                "name": name, "url": url,
                "country_name": self.country_name,
                "country_code": getattr(self, '_epg_country_code', None) or
                get_country_code(self.country_name),
                "logo": logo or "",
            }
            # an adult channel asks for the PIN (the country's was
            # asked when it was opened)
            _require_parental_pin(
                self.session, self, self.country_name,
                lambda: self._preview_or_play(channel, self.full_screen),
                channel_name=name, group=self._category_at(i))
        except Exception as e:
            print('error as:', e)
            trace_error()

    def _highlighted_channel(self):
        """(the highlighted channel as the preview / recordings keep it,
        its row) or (None, None) - on a category row too."""
        if self.showing_categories:
            return None, None
        i, name, url = self._selected_row()
        if i is None:
            return None, None
        logo = (self._channel_entries[i][2]
                if 0 <= i < len(self._channel_entries) else None)
        return {
            "name": name, "url": url,
            "country_name": self.country_name,
            "country_code": getattr(self, '_epg_country_code', None) or
            get_country_code(self.country_name),
            "logo": logo or "",
        }, i

    def record_highlighted(self):
        """REC: record the highlighted channel (again: stop) - an adult
        channel's after the PIN."""
        channel, i = self._highlighted_channel()
        if channel is None:
            return
        _require_parental_pin(
            self.session, self, self.country_name,
            lambda: record_channel(channel),
            channel_name=channel["name"], group=self._category_at(i))

    def open_favourites(self):
        """FAV: the favourites."""
        self.session.open(VavooFavourites)

    def help_rows(self):
        if self.showing_categories:
            first = [("OK", _("Open the category"))]
        else:
            first = [("OK", _("Play in the window (again: full screen)"))]
        return first + [
            (_("RED / EXIT"), _("Back")),
            (_("GREEN"), _("Add / remove favourite")),
            (_("YELLOW / TEXT"), _("Search")),
            (_("BLUE / PLAY"), _("Full screen")),
            ("INFO / EPG", _("Programme guide")),
            ("MENU", _("Settings and tools")),
            ("FAV", _("Favourites")),
            (_("PVR / FILE"), _("Recordings")),
            ("REC", _("Record the highlighted channel (again: stop)")),
            ("STOP", _("Stop the window")),
            ("1-9", _("Go to that row")),
            ("0", _("The channel watched last")),
            ("CH+ / CH-", _("Page up / down")),
        ]

    def show_help(self):
        show_keys(self.session, self.help_rows())

    def _category_at(self, i):
        """The catalog category of row i (for the adult lock)."""
        try:
            url = self._channel_entries[i][1]
            for channel in self._all_channels:
                if channel.get("url") == url:
                    return channel.get("category") or None
        except Exception:
            pass
        return None

    def full_screen(self):
        if self.showing_categories:
            self.open_category()
            return
        i, name, _url = self._selected_row()
        if i is None:
            return
        _require_parental_pin(self.session, self, self.country_name,
                              self._full_screen, channel_name=name,
                              group=self._category_at(i))

    def _full_screen(self):
        try:
            i = self['menulist'].getSelectedIndex()
            self.currentindex = i
            selection = self['menulist'].l.getCurrentSelection()
            if selection is not None:
                item = self.cat_list[i][0]
                name = item[0]
                url = item[1]
            else:
                print("No selection available")
                return

            # Parallel to cat_list (see _channel_entries' own
            # declaration comment) - lets Playstream2 show this
            # channel's picon on its playback overlay without a
            # second network fetch, the same way country_codes lets
            # it keep EPG lookups matched to the right country.
            logo_urls = [entry[2] for entry in self._channel_entries]
            logo_url = (
                self._channel_entries[i][2]
                if 0 <= i < len(self._channel_entries) else None)

            self.play_that_shit(
                url,
                name,
                self.currentindex,
                item,
                self.cat_list,
                logo_url,
                logo_urls)
        except Exception as e:
            print('error as:', e)
            trace_error()

    def play_that_shit(
            self, url, name, index, item, cat_list,
            logo_url=None, logo_urls=None):
        try:
            country_code = get_country_code(self.country_name)
            self.session.openWithCallback(
                self._on_player_closed,
                Playstream2,
                name, url, index, item, cat_list,
                country_code=country_code,
                logo_url=logo_url,
                logo_urls=logo_urls,
                country_name=self.country_name,
                hand_back=cfg.preview_window.value
            )
        except Exception as e:
            print("Error in play_that_shit: {}".format(e))
            trace_error()
            self.session.open(
                MessageBox,
                _("Error starting channel"),
                MessageBox.TYPE_ERROR,
                timeout=3
            )

    def toggle_favourite(self):
        """GREEN: star/unstar the highlighted channel (nothing on a
        category row)."""
        if self.showing_categories:
            return
        try:
            i = self['menulist'].getSelectedIndex()
            selection = self['menulist'].l.getCurrentSelection()
            if selection is None:
                return
            item = self.cat_list[i][0]
            name = item[0]
            url = item[1]
        except Exception as e:
            print('[vavoo] toggle_favourite selection error:', e)
            return

        logo = None
        if 0 <= i < len(self._channel_entries):
            logo = self._channel_entries[i][2] or None
        now_favourite = vUtils.toggle_favourite(
            name, url,
            country_name=self.country_name,
            country_code=get_country_code(self.country_name), logo=logo)
        if now_favourite is None:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Could not update favourites"), 3)
            return
        key = to_text(url)
        if now_favourite:
            self._favourite_keys.add(key)
        else:
            self._favourite_keys.discard(key)
        self._update_status_line()
        if NOTIFICATION_AVAILABLE:
            if now_favourite:
                quick_notify(_("Added to favourites: {}").format(name), 3)
            else:
                quick_notify(_("Removed from favourites: {}").format(name), 3)

    def info_toast(self):
        """INFO: version and this country's channels (the app's INFO)."""
        if NOTIFICATION_AVAILABLE:
            quick_notify(info_text(len(self.cat_list) or None), 5)

    def open_menu(self):
        """MENU: the settings and the Enigma2 tools that used to be on
        the colour keys - this country's bouquet above all."""
        try:
            exported = is_bouquet_exported(self.name)
        except Exception as e:
            debug("is_bouquet_exported failed: {}".format(e))
            exported = False
        entries = [
            (_("Settings"), "settings"),
            (_("Remove this country's bouquet") if exported
             else _("Export this country as a bouquet"), "bouquet"),
            (_("Reload bouquets"), "reload_bouquets"),
            (_("Show Log"), "log"),
        ]
        actions = {
            "settings": self.goConfig,
            "bouquet": self.message1,
            "reload_bouquets": self.reload_bouquets_with_popup,
            "log": lambda: open_log_viewer(self.session),
        }
        open_action_menu(
            self.session, to_string(self.country_name), entries,
            lambda key: actions[key]() if key in actions else None)

    def message1(self, answer=None):
        """Green button: export this bouquet, or offer to remove it if
        it's already exported."""
        if is_bouquet_exported(self.name):
            self.session.openWithCallback(
                self._confirm_remove_fav,
                MessageBox,
                _("Remove the exported bouquet for this country/category?") +
                "\n" + self.name,
                MessageBox.TYPE_YESNO
            )
        else:
            # Show confirmation message before export
            self.session.openWithCallback(
                self._confirm_export_fav,
                MessageBox,
                _("Do you want to export this bouquet?") + "\n" + self.name,
                MessageBox.TYPE_YESNO
            )

    def _confirm_export_fav(self, answer):
        if answer is True:
            self.message2(self.name, self.url, True)
        else:
            print("Export cancelled by user")

    def _confirm_remove_fav(self, answer):
        if not answer:
            print("Remove favorite cancelled by user")
            return
        # Same lock message2()'s export uses - removing a bouquet while
        # its own (or another country's) export background thread is
        # still writing the same files/Favorite.txt can corrupt them.
        if not export_lock.acquire(False):
            if NOTIFICATION_AVAILABLE:
                quick_notify(
                    _("An export for another country is already in progress. Please wait."), 4)
            return
        try:
            removed = remove_bouquets_by_name(self.name)
            if removed > 0:
                remove_favorite_entry(self.name)
                if NOTIFICATION_AVAILABLE:
                    quick_notify(
                        _("Removed exported bouquet: {}").format(self.name), 3)
                self._confirm_reload_bouquets(True)
            else:
                if NOTIFICATION_AVAILABLE:
                    quick_notify(
                        _("Nothing to remove for: {}").format(
                            self.name), 3)
        except Exception as e:
            print("[vavoo] Error removing favorite: {}".format(e))
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Remove failed: {}").format(str(e)), 4)
        finally:
            export_lock.release()

    def message2(self, name, url, response):
        # threading.Lock.acquire() only accepts blocking as a
        # positional argument on Python 2 (the C implementation there
        # doesn't support keyword arguments at all) - acquire(False)
        # works identically on both Python 2 and 3.
        if not export_lock.acquire(False):
            if NOTIFICATION_AVAILABLE:
                quick_notify(
                    _("An export for another country is already in progress. Please wait."), 4)
            return

        self._export_type = "hierarchical" if any(
            sep in name for sep in group_separators(name)) else "flat"

        try:
            export_bouquet_async(
                name,
                self._export_type,
                self,
                self._on_export_complete,
                cfg.services.value,
                cfg.list_position.value,
                lock=export_lock)
            if NOTIFICATION_AVAILABLE:
                quick_notify(
                    _("Export started. Bouquet will be available shortly."), 3)

        except Exception as e:
            export_lock.release()
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Bouquet creation error: {}").format(str(e)), 5)

    def _on_export_complete(self, success, ch_count, message):
        """Callback for bouquet export completion"""
        debug(
            "_on_export_complete CALLED - success=%s, ch_count=%s, message='%s'" %
            (success, ch_count, message))

        try:
            if not success:
                # Export failed
                if NOTIFICATION_AVAILABLE:
                    quick_notify(_("Export failed: {}").format(message), 5)
                return

            # Success - two cases:
            if message == "Bouquet created":
                # First callback - base bouquet ready
                debug("Bouquet ready with {} channels".format(ch_count))
                if NOTIFICATION_AVAILABLE:
                    quick_notify(
                        _("Bouquet ready with {} channels").format(ch_count), 3)
                # Register with Favorite.txt so "Scheduled List" auto-update
                # (AutoStartTimer) picks this bouquet up going forward -
                # that feature only ever re-updates bouquets already listed
                # there, it never adds new ones on its own.
                try:
                    _update_favorite_file(
                        self.name, self.url,
                        getattr(self, '_export_type', 'flat'))
                except Exception as e:
                    print("[vavoo] Error updating Favorite.txt: {}".format(e))

            elif message == "EPG processing completed":
                # Second callback - EPG completed
                debug("EPG completed for {} channels".format(ch_count))
                if NOTIFICATION_AVAILABLE:
                    if ch_count > 0:
                        quick_notify(
                            _("EPG processing completed for {} channels").format(ch_count), 4)
                    else:
                        quick_notify(
                            _("EPG processing completed (no matches)"), 3)

            else:
                # Other messages
                debug("Export completed: {}".format(message))
                if NOTIFICATION_AVAILABLE:
                    quick_notify(message, 3)

        except Exception as e:
            # Intentionally swallowed so a failure here can't crash the
            # export callback - but that means it's log-only, with no
            # user-visible indication.
            print("[Bouquet] Error in _on_export_complete: %s" % e)

    def search_vavoo(self):
        """YELLOW: search the whole country (also from a category)."""
        if not getattr(self, 'itemlist', None):
            return
        self.session.openWithCallback(
            self.onSearchResult, VavooSearch, self, self.itemlist,
            scope=self.country_name,
            country_code=getattr(self, '_epg_country_code', None))

    def onSearchResult(self, selected_item=None):
        """The channel chosen in the search, full screen, the results
        as the player's list."""
        if selected_item and not self._closed:
            play_search_result(
                self.session, self, selected_item, self._on_player_closed,
                self.country_name)

    def _on_player_closed(self, result=None):
        """Back from full screen: the highlight goes to the channel
        watched last, if it is in this list."""
        if self._closed or not result:
            return
        url = result[2] if len(result) > 2 else None
        for index, row in enumerate(self.cat_list):
            if row[0][1] == url:
                self['menulist'].moveToIndex(index)
                break

    def goConfig(self):
        open_settings(self.session)

    def chUp(self):
        """Handle page up and update name"""
        try:
            if self.cat_list:
                self['menulist'].pageUp()
                print("vavoo chUp: " + str(self['name'].getText()))
        except Exception as e:
            print("Error in vavoo chUp:", e)

    def chDown(self):
        """Handle page down and update name"""
        try:
            if self.cat_list:
                self['menulist'].pageDown()
                print("vavoo chDown: " + str(self['name'].getText()))
        except Exception as e:
            print("Error in vavoo chDown:", e)

    def moveUp(self):
        """Move selection up, wrapping from the first entry to the last."""
        if not self.cat_list:
            return
        idx = self['menulist'].getSelectedIndex()
        self['menulist'].moveToIndex((idx - 1) % len(self.cat_list))

    def moveDown(self):
        """Move selection down, wrapping from the last entry to the first."""
        if not self.cat_list:
            return
        idx = self['menulist'].getSelectedIndex()
        self['menulist'].moveToIndex((idx + 1) % len(self.cat_list))

    def _update_selection_name(self):
        """Update the name label with current selection"""
        try:
            current = self['menulist'].getCurrent()
            if current and len(current) > 0:
                name = current[0][0]
                self['name'].setText(to_string(name))
                debug("vavoo _update_selection_name: " + to_string(name))
            self._update_status_line()
        except Exception as e:
            print("Error in vavoo _update_selection_name:", e)
            self['name'].setText("")

    def update_menu(self):
        try:
            if self.cat_list:
                self['menulist'].l.setList(self.cat_list)
                # self['menulist'].moveToIndex(0)
            else:
                self['name'].setText(_("No channels found"))
        except Exception as e:
            print("Error updating menu:", e)
            self['name'].setText(_("Error"))

    def close(self, *args, **kwargs):
        self._closed = True
        self._epg_panel_stop()
        try:
            self.timer.stop()
            try:
                if hasattr(self.timer, 'callback'):
                    try:
                        self.timer.callback.remove(self.cat)
                    except ValueError:
                        pass  # already removed or method identity changed
            except AttributeError:
                pass
            try:
                if hasattr(self.timer, 'timeout'):
                    self.timer.timeout.disconnect(self.cat)
            except AttributeError:
                pass
        except Exception as e:
            print("Error stopping timer: " + str(e))
        try:
            if hasattr(self, 'proxy_status_timer'):
                self.proxy_status_timer.stop()
        except Exception as e:
            print("Error stopping proxy_status_timer: " + str(e))
        try:
            if hasattr(self, 'picon_refresh_timer'):
                self.picon_refresh_timer.stop()
        except Exception as e:
            print("Error stopping picon_refresh_timer: " + str(e))
        return Screen.close(self, *args, **kwargs)

    def backhome(self):
        # search_ok (previously gating an alternate self.cat() branch
        # here) was always False and never set True anywhere in this
        # file - VavooSearch now uses a direct openWithCallback/
        # return-value pattern instead. Removed as dead code.
        self.close()


class VavooFavourites(Screen, NowNextPanel, PreviewWindow):
    """The favourites - or, with mode="recent", the recently watched
    channels (vUtils.load_recent(), newest first) - as the app's
    channel list (ChannelsActivity) shows them: no proxy fetching, a
    list built from the file. Reuses defaultListScreen.xml (the skin
    `vavoo` / `MainVavoo` load).

    Favourites in folders (vavoo_store): the top shows "All channels",
    the folders A-Z and "No folder" first; OK opens one (a new screen
    with `folder`). Keys as in the app: Back / Remove Fav / Move (Done)
    / Folder - Recently watched has the country list's: Back / Add Fav
    / Search / Full Screen."""

    MODE_FAVOURITES = "favourites"
    MODE_RECENT = "recent"
    # Folder rows' keys (a folder's own name otherwise)
    FOLDER_ALL = "\x00all"
    FOLDER_NONE = "\x00none"
    _closed = True          # (ui_base's CLOSED_UNTIL_OPEN)

    def __init__(self, session, mode="favourites", folder=None):
        self._closed = False
        self.session = session
        self.mode = mode
        self.folder = folder
        Screen.__init__(self, session)
        self.skin, self._themed = load_screen_skin(
            "list", 'defaultListScreen.xml', cvs=True, clock_24=clock_24())

        init_notification_system(session)
        self.onClose.append(self._mark_closed)

        self.cat_list = []
        self.favourite_entries = []
        # True: the rows are folders (self.folder_keys), not channels
        self.showing_folders = False
        self.folder_keys = []
        self.moving = False
        self._moved = False
        self._digits = ""
        self._digit_time = 0
        self['menulist'] = m2list([], themed=self._themed)
        self['name'] = Label(self._title())
        self['version'] = Label(to_string("V." + __version__))
        self['proxy_status'] = Label('')
        self['red'] = Label(_('Back'))
        if mode == self.MODE_RECENT:
            self['green'] = Label(_('Add Fav'))
            self['yellow'] = Label(_('Search'))
            self['blue'] = Label(_('Full Screen'))
        else:
            self['green'] = Label(_('Remove Fav'))
            self['yellow'] = Label(_('Move'))
            self['blue'] = Label(_('Folder'))
        add_key_hint_labels(self)
        self['key_info'].setText("EPG")
        self._favourite_keys = set()
        self._preview_init()
        self._epg_panel_init()
        self['menulist'].onSelectionChanged.append(self._epg_panel_changed)
        self['menulist'].onSelectionChanged.append(self._update_selection)
        self.onClose.append(self._epg_panel_stop)
        self.onClose.append(self._finish_move)

        actions = {
            "up": self.moveUp,
            "down": self.moveDown,
            "left": self.page_up,
            "right": self.page_down,
            "prevBouquet": self.page_down,
            "nextBouquet": self.page_up,
            "ok": self.ok,
            "green": self.green,
            "yellow": self.yellow,
            "blue": self.blue,
            "cancel": self.cancel,
            "red": self.cancel,
            "menu": self.open_menu,
            # INFO / EPG: the programme guide (the app's)
            "info": self.info_key,
            "epg": self.info_key,
        }
        for digit in range(10):
            actions[str(digit)] = (lambda d: lambda: self.number(d))(digit)
        self['actions'] = ActionMap(
            ['OkCancelActions', 'ColorActions', 'DirectionActions',
             'MenuActions', 'InfobarEPGActions', 'NumberActions'],
            actions, -1)
        self['epg_keys'] = info_page_keys(actions)
        # The direct keys (keymap.xml): PVR, TEXT, HELP, and PLAY / STOP
        # / REC on the highlighted channel (FAV: here already)
        self['list_keys'] = list_keys({
            "favourites": lambda: None,
            "recordings": lambda: self.session.open(VavooRecordings),
            "search": self._key_search,
            "help": self.show_help,
            "play": self._key_play,
            "stop": lambda: stop_preview(self.session),
            "record": self.record_highlighted,
            "back": self.cancel,
        })
        self.onLayoutFinish.append(self._build_list)
        self.onExecBegin.append(self._back_on_top)

    def _key_search(self):
        if not self.moving:
            self.search_list()

    def _key_play(self):
        if not self.moving and not self.showing_folders:
            self.full_screen()

    def record_highlighted(self):
        """REC: record the highlighted channel (again: stop) - a locked
        one's after the PIN."""
        if self.moving:
            return
        i, item, name, url = self._current_selection()
        if name is None:
            return
        entry = self.favourite_entries[i]
        channel = {"name": name, "url": url,
                   "country_name": entry.get('country_name'),
                   "country_code": entry.get('country_code'),
                   "logo": entry.get('logo') or ""}
        _require_parental_pin(
            self.session, self, entry.get('country_name'),
            lambda: record_channel(channel), channel_name=name)

    def help_rows(self):
        if self.moving:
            return [
                (_("UP / DOWN"), _("Move the channel")),
                ("1-9", _("Move it to that place")),
                (_("OK / YELLOW"), _("Done")),
                (_("EXIT"), _("Done")),
            ]
        if self.showing_folders:
            return [
                ("OK", _("Open the folder")),
                (_("BLUE"), _("Rename / delete the folder")),
                (_("RED / EXIT"), _("Back")),
                ("MENU", _("Settings")),
                (_("PVR / FILE"), _("Recordings")),
            ]
        recent = self.mode == self.MODE_RECENT
        return [
            ("OK", _("Play in the window (again: full screen)")),
            (_("RED / EXIT"), _("Back")),
            (_("GREEN"), _("Remove from the list") if recent
             else _("Remove favourite")),
            (_("YELLOW"), _("Search") if recent else _("Move")),
            (_("BLUE"), _("Full screen") if recent else _("Folder")),
            ("TEXT", _("Search")),
            ("PLAY", _("Full screen")),
            ("INFO / EPG", _("Programme guide")),
            ("MENU", _("Settings and tools")),
            (_("PVR / FILE"), _("Recordings")),
            ("REC", _("Record the highlighted channel (again: stop)")),
            ("STOP", _("Stop the window")),
            ("1-9", _("Go to that row")),
            ("0", _("The channel watched last")),
        ]

    def show_help(self):
        show_keys(self.session, self.help_rows())

    def _mark_closed(self):
        self._closed = True

    def _title(self):
        if self.mode == self.MODE_RECENT:
            return _("Recently watched")
        if self.folder is None:
            return _("★ Favourites")
        return u"{} ➾ {}".format(to_text(_("★ Favourites")),
                                 to_text(self._folder_label(self.folder)))

    def _folder_label(self, key):
        if key == self.FOLDER_ALL:
            return _("All channels")
        if key == self.FOLDER_NONE:
            return _("No folder")
        return key

    def _back_on_top(self):
        """A folder screen changed folders, or a player added / removed
        favourites: the rows again (not while moving)."""
        if self.cat_list and not self.moving:
            self._build_list(keep=True)

    # ---- the rows

    def _channels_in_view(self, favourites):
        if self.folder is None or self.folder == self.FOLDER_ALL:
            return favourites
        if self.folder == self.FOLDER_NONE:
            return [e for e in favourites if not e.get('folder')]
        return [e for e in favourites if e.get('folder') == self.folder]

    def _channel_row(self, index, entry, total):
        digits = len(str(total))
        text = u"{}  {}".format(row_number(index + 1, digits, u" "),
                                to_text(entry['name']))
        return show_list(entry['name'], entry['url'], is_channel=True,
                         logo_url=entry.get('logo') or None,
                         display=to_string(text), themed=self._themed)

    def _build_list(self, keep=False):
        selected = None
        if keep:
            selected = self._selected_link()
        favourites = vUtils.load_favourites()
        self._favourite_keys = set(to_text(e['url']) for e in favourites)
        self.showing_folders = False
        self.folder_keys = []
        if self.mode == self.MODE_RECENT:
            self.favourite_entries = vUtils.load_recent()
        else:
            folders = vavoo_store.folders()
            if self.folder is None and folders:
                self._build_folder_rows(favourites, folders)
                self._show_rows(selected)
                return
            # in the user's order (vavoo_store)
            self.favourite_entries = self._channels_in_view(favourites)
        total = len(self.favourite_entries)
        self.cat_list = [self._channel_row(i, entry, total)
                         for i, entry in enumerate(self.favourite_entries)]
        self._show_rows(selected)

    def _build_folder_rows(self, favourites, folders):
        """The app's folder rows: All channels (n), the folders A-Z,
        No folder (n) - a count only with Show Channel Count."""
        self.showing_folders = True
        self.favourite_entries = []
        counts = {}
        for entry in favourites:
            key = entry.get('folder') or self.FOLDER_NONE
            counts[key] = counts.get(key, 0) + 1
        keys = [self.FOLDER_ALL] + list(folders)
        if counts.get(self.FOLDER_NONE):
            keys.append(self.FOLDER_NONE)
        self.folder_keys = keys
        rows = []
        for key in keys:
            count = len(favourites) if key == self.FOLDER_ALL \
                else counts.get(key, 0)
            label = to_text(self._folder_label(key))
            display = u"{} ({})".format(label, count) \
                if cfg.show_counts.value else label
            rows.append(show_list(to_string(label), to_string(key),
                                  is_category=True, display=to_string(display),
                                  themed=self._themed))
        self.cat_list = rows

    def _selected_link(self):
        try:
            current = self['menulist'].getCurrent()
            return current[0][1] if current else None
        except Exception:
            return None

    def _show_rows(self, selected=None):
        self['menulist'].l.setList(self.cat_list)
        if self.cat_list:
            index = 0
            if selected is not None:
                for i, row in enumerate(self.cat_list):
                    if row[0][1] == selected:
                        index = i
                        break
            self['menulist'].moveToIndex(index)
        else:
            self['name'].setText(
                _('No channels watched yet') if self.mode == self.MODE_RECENT
                else _('No favourites'))
        self._epg_panel_changed()
        self._update_selection()

    def _update_selection(self):
        """The highlighted row's name, the app's status line
        ("★ Favourites · 3/12", "⇅  Name" while moving) and GREEN's
        caption in Recently watched."""
        if self._closed:
            return
        try:
            label = to_text(self._title())
            if not self.cat_list:
                self['proxy_status'].setText(to_string(label))
                return
            i = self['menulist'].getSelectedIndex() or 0
            text = u"{} · {}/{}".format(label, i + 1, len(self.cat_list))
            if 0 <= i < len(self.cat_list):
                name, url = self.cat_list[i][0][0], self.cat_list[i][0][1]
                self['name'].setText(to_string(name))
                if self.moving:
                    text = u"⇅  " + to_text(name)
                elif self.mode == self.MODE_RECENT:
                    favourite = to_text(url) in self._favourite_keys
                    self['green'].setText(
                        _('Remove Fav') if favourite else _('Add Fav'))
                    if favourite:
                        text += u"  ★"
            self['proxy_status'].setText(to_string(text))
        except Exception as e:
            debug("Favourites status line not updated: {}".format(e))

    def info_toast(self):
        if NOTIFICATION_AVAILABLE:
            quick_notify(info_text(len(self.favourite_entries) or None), 5)

    def info_key(self):
        """INFO / EPG: the programme guide of these channels (on folder
        rows, or while moving: the info note)."""
        if self.showing_folders or self.moving or not self.favourite_entries:
            self.info_toast()
            return
        channels = [{
            "name": e.get("name"), "url": e.get("url"),
            "logo": e.get("logo"), "country_name": e.get("country_name"),
            "country_code": e.get("country_code")}
            for e in self.favourite_entries]
        self.session.openWithCallback(
            self._on_guide_closed, VavooGuide, channels, self._index(),
            self._title())

    def _on_guide_closed(self, result=None):
        if self._closed or not result or result[0] != "watch":
            return
        self['menulist'].moveToIndex(result[1])
        self.full_screen()

    def open_menu(self):
        if self.moving:
            return
        entries = [(_("Settings"), "settings"), (_("Show Log"), "log")]
        actions = {
            "settings": lambda: open_settings(self.session),
            "log": lambda: open_log_viewer(self.session),
        }
        if self.mode == self.MODE_RECENT:
            entries.insert(1, (_("Clear recently watched"), "clear"))
            actions["clear"] = self.clear_recent
        open_action_menu(
            self.session, self._title(), entries,
            lambda key: actions[key]() if key in actions else None)

    def clear_recent(self):
        vUtils.clear_recent()
        self._build_list()

    def _epg_panel_country(self):
        i = self['menulist'].getSelectedIndex()
        if i is None or not 0 <= i < len(self.favourite_entries):
            return None
        return self.favourite_entries[i].get('country_name')

    def _epg_panel_selection(self):
        """See NowNextPanel. Favourites mix countries: each entry
        carries its own country code."""
        if not self.cat_list or self.showing_folders:
            return None
        i = self['menulist'].getSelectedIndex()
        if i is None or not 0 <= i < len(self.favourite_entries):
            return None
        entry = self.favourite_entries[i]
        name = entry.get('name')
        country_code = entry.get('country_code')
        if not name or not country_code:
            return None
        return (name, entry.get('url', ''), country_code)

    # ---- moving along the list

    def _page_rows(self):
        return list_page_rows(self['menulist'], self._themed)

    def _go(self, index, wrap=False):
        if not self.cat_list:
            return
        if self.moving:
            self._move_to(index)
            return
        if wrap:
            index %= len(self.cat_list)
        index = max(0, min(index, len(self.cat_list) - 1))
        self['menulist'].moveToIndex(index)

    def _index(self):
        return self['menulist'].getSelectedIndex() or 0

    def moveUp(self):
        self._go(self._index() - 1, wrap=not self.moving)

    def moveDown(self):
        self._go(self._index() + 1, wrap=not self.moving)

    def page_up(self):
        self._go(self._index() - self._page_rows())

    def page_down(self):
        self._go(self._index() + self._page_rows())

    def number(self, digit):
        """The number keys go to that row (to that place while
        moving); typed within 1.5 s they add up (1, 2 = row 12). 0 with
        no number begun (not while moving): the channel watched last."""
        now = time.time()
        if now - self._digit_time > 1.5:
            self._digits = ""
        if digit == 0 and not self._digits and not self.moving:
            play_last_watched(self.session, self, self._on_player_closed)
            return
        if not self.cat_list or self.showing_folders:
            return
        self._digit_time = now
        self._digits = (self._digits + str(digit))[-4:]
        target = int(self._digits) - 1
        if 0 <= target < len(self.cat_list):
            self._go(target)

    # ---- favourites: move (the app's YELLOW)

    def _set_moving(self, on):
        if not on:
            self._finish_move()
        self.moving = bool(on and not self.showing_folders and
                           self.mode != self.MODE_RECENT and
                           len(self.cat_list) > 1)
        self['yellow'].setText(_('Done') if self.moving else _('Move'))
        if self.moving and NOTIFICATION_AVAILABLE:
            name = self.cat_list[self._index()][0][0]
            quick_notify(_("Moving {}: ▲▼, ◄► a page, "
                           "a number; OK to finish").format(name), 6)
        self._update_selection()

    def _move_to(self, target):
        """The channel being moved to row `target` (not saved yet:
        once, on Done)."""
        pos = self._index()
        target = max(0, min(target, len(self.cat_list) - 1))
        if target == pos:
            return
        entry = self.favourite_entries.pop(pos)
        self.favourite_entries.insert(target, entry)
        total = len(self.favourite_entries)
        self.cat_list = [self._channel_row(i, e, total)
                         for i, e in enumerate(self.favourite_entries)]
        self._moved = True
        self['menulist'].l.setList(self.cat_list)
        self['menulist'].moveToIndex(target)

    def _finish_move(self):
        if self._moved:
            self._moved = False
            vavoo_store.reorder_favourites(
                [e['url'] for e in self.favourite_entries])

    # ---- keys

    def cancel(self):
        if self.moving:
            self._set_moving(False)
            return
        self.close()

    def green(self):
        if self.moving or self.showing_folders:
            return
        self.remove_selected()

    def yellow(self):
        if self.mode == self.MODE_RECENT:
            self.search_list()
            return
        self._set_moving(not self.moving)

    def blue(self):
        if self.mode == self.MODE_RECENT:
            self.full_screen()
            return
        if self.moving:
            return
        if self.showing_folders:
            i = self._index()
            if 0 <= i < len(self.folder_keys):
                key = self.folder_keys[i]
                if key not in (self.FOLDER_ALL, self.FOLDER_NONE):
                    self.folder_actions(key)
            return
        self.choose_folder()

    def search_list(self):
        """Recently watched's YELLOW: search in this list."""
        if not self.favourite_entries:
            return
        items = ["###".join((to_string(e['name']), to_string(e['url'])))
                 for e in self.favourite_entries]
        self.session.openWithCallback(
            self._on_search_result, VavooSearch, self, items,
            scope=self._title())

    def _on_search_result(self, selected=None):
        if not selected or self._closed:
            return
        for index, row in enumerate(self.cat_list):
            if row[0][1] == selected[1]:
                self['menulist'].moveToIndex(index)
                self._play_selected()
                break

    # ---- favourites: folders (the app's BLUE)

    def choose_folder(self):
        """BLUE on a channel: "Folder for X" - the folders, No folder,
        New folder…"""
        i, _item, name, url = self._current_selection()
        if name is None:
            return
        folders = vavoo_store.folders()
        entries = [(to_string(f), "f:" + to_string(f)) for f in folders]
        entries.append((_("No folder"), "none"))
        entries.append((_("New folder…"), "new"))

        def chosen(key):
            if not key:
                return
            if key == "new":
                self._ask_folder_name(url, name)
            elif key == "none":
                self._set_folder(url, name, None)
            else:
                self._set_folder(url, name, key[2:])

        open_action_menu(self.session,
                         _("Folder for {}").format(to_string(name)),
                         entries, chosen)

    def _ask_folder_name(self, url=None, name=None, renaming=None):
        def done(text=None):
            text = to_text(text).strip() if text else u""
            if not text or self._closed:
                return
            if renaming is not None:
                vavoo_store.rename_folder(renaming, text)
                if NOTIFICATION_AVAILABLE:
                    quick_notify(_("Folder renamed to {}").format(
                        to_string(text)), 3)
                self._build_list()
            else:
                self._set_folder(url, name, text)

        self.session.openWithCallback(
            done, VirtualKeyBoard, title=_("Folder name (e.g. Sport)"),
            text=to_string(renaming or ""))

    def _set_folder(self, url, name, folder):
        vavoo_store.set_folder(url, folder)
        if NOTIFICATION_AVAILABLE:
            quick_notify(u"{} → {}".format(
                to_text(name), to_text(folder or _("No folder"))), 3)
        self._build_list(keep=True)

    def folder_actions(self, folder):
        """BLUE on a folder row: rename or remove it."""
        def chosen(key):
            if key == "rename":
                self._ask_folder_name(renaming=folder)
            elif key == "remove":
                vavoo_store.delete_folder(folder)
                if NOTIFICATION_AVAILABLE:
                    quick_notify(_("Folder {} removed - its channels stay in "
                                   "the favourites").format(
                                       to_string(folder)), 4)
                self._build_list()

        open_action_menu(
            self.session, to_string(folder),
            [(_("Rename folder"), "rename"), (_("Remove folder"), "remove")],
            chosen)

    # ---- playing

    def _current_selection(self):
        """Returns (index, item, name, url) for the highlighted channel
        row, or (None, None, None, None)."""
        if not self.cat_list or self.showing_folders:
            return None, None, None, None
        i = self['menulist'].getSelectedIndex()
        if i is None or not 0 <= i < len(self.favourite_entries):
            return None, None, None, None
        item = self.cat_list[i][0]
        return i, item, item[0], item[1]

    def ok(self):
        """OK: a folder row opens it; a channel goes into the preview
        window (after the PIN of a locked country), and on the channel
        already playing there, full screen. While moving: Done."""
        if self.moving:
            self._set_moving(False)
            return
        if self.showing_folders:
            i = self._index()
            if 0 <= i < len(self.folder_keys):
                self.session.open(VavooFavourites, self.mode,
                                  self.folder_keys[i])
            return
        try:
            i, item, name, url = self._current_selection()
            if name is None:
                return
            entry = self.favourite_entries[i]
            channel = {
                "name": name, "url": url,
                "country_name": entry.get('country_name'),
                "country_code": entry.get('country_code'),
                "logo": entry.get('logo') or "",
            }
            _require_parental_pin(
                self.session, self, entry.get('country_name'),
                lambda: self._preview_or_play(channel, self._play_selected),
                channel_name=name)
        except Exception as e:
            print('[VavooFavourites] Error opening channel:', e)
            trace_error()

    def full_screen(self):
        try:
            i, item, name, url = self._current_selection()
            if name is None:
                return
            entry = self.favourite_entries[i]
            _require_parental_pin(
                self.session, self, entry.get('country_name'),
                self._play_selected, channel_name=name)
        except Exception as e:
            print('[VavooFavourites] Error opening channel:', e)
            trace_error()

    def _play_selected(self):
        try:
            i, item, name, url = self._current_selection()
            if name is None:
                return
            entry = self.favourite_entries[i]
            country_name = entry.get('country_name')
            country_code = entry.get('country_code')

            # Parallel to self.cat_list - favourites can mix channels
            # from several countries (unlike every other Playstream2
            # caller's single-country list), so channel-surfing
            # (nextitem()/previousitem()) needs a country_code per
            # entry to keep EPG lookups matched to the right country
            # instead of staying stuck on this first channel's one.
            country_codes = [
                e.get('country_code') for e in self.favourite_entries]
            # (the PIN was asked by ok() / full_screen(): a favourite
            # from a locked country used to play with no PIN prompt at
            # all - see MainVavoo.ok()'s use of the same helper)
            self.session.openWithCallback(
                self._on_player_closed,
                Playstream2,
                name, url, i, item, self.cat_list,
                country_code=country_code,
                country_codes=country_codes,
                logo_url=entry.get('logo') or None,
                logo_urls=[e.get('logo') or None
                           for e in self.favourite_entries],
                country_name=country_name,
                country_names=[e.get('country_name')
                               for e in self.favourite_entries],
                hand_back=cfg.preview_window.value
            )
        except Exception as e:
            print('[VavooFavourites] Error opening channel:', e)
            trace_error()

    def _on_player_closed(self, result=None):
        if self._closed:
            return
        if self.mode == self.MODE_RECENT:
            # what was watched moved to the top
            self._build_list()
        if not result:
            return
        url = result[2] if len(result) > 2 else None
        for index, row in enumerate(self.cat_list):
            if row[0][1] == url:
                self['menulist'].moveToIndex(index)
                break

    def remove_selected(self):
        i, _item, name, url = self._current_selection()
        if name is None:
            return
        if self.mode == self.MODE_RECENT:
            # GREEN here is the channel list's Add Fav / Remove Fav.
            entry = self.favourite_entries[i]
            now_favourite = vUtils.toggle_favourite(
                name, url, country_name=entry.get('country_name'),
                country_code=entry.get('country_code'),
                logo=entry.get('logo') or None)
            if now_favourite is None:
                if NOTIFICATION_AVAILABLE:
                    quick_notify(_("Could not update favourites"), 3)
                return
            key = to_text(url)
            if now_favourite:
                self._favourite_keys.add(key)
            else:
                self._favourite_keys.discard(key)
            self._update_selection()
            if NOTIFICATION_AVAILABLE:
                quick_notify((_("Added to favourites: {}") if now_favourite else _(
                    "Removed from favourites: {}")).format(name), 3)
            return
        now_favourite = vUtils.toggle_favourite(name, url)
        if now_favourite is None:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Could not update favourites"), 3)
            return
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Removed from favourites: {}").format(name), 3)
        self._build_list()
        # the next channel takes the removed one's place
        if self.cat_list and not self.showing_folders:
            self['menulist'].moveToIndex(min(i, len(self.cat_list) - 1))


# --- Live search screen ---
def play_search_result(session, screen, selected, on_closed,
                       default_country=None):
    """VavooSearch's answer: the chosen channel full screen, the
    results as the player's list, after the PIN of a locked country."""
    name, url = selected[0], selected[1]
    country = (selected[2] if len(selected) > 2 else None) or default_country
    results = list(selected[3]) if len(selected) > 3 and selected[3] \
        else [(name, url, country)]
    index = selected[4] if len(selected) > 4 else 0
    if not 0 <= index < len(results):
        results, index = [(name, url, country)], 0
    names = [r[2] or default_country for r in results]
    codes = {}
    for country_name in names:
        if country_name not in codes:
            try:
                codes[country_name] = get_country_code(country_name) \
                    if country_name else None
            except Exception:
                codes[country_name] = None
    country_codes = [codes[c] for c in names]
    rows = [[(to_string(r[0]), to_string(r[1]))] for r in results]

    def _play():
        session.openWithCallback(
            on_closed, Playstream2, rows[index][0][0], rows[index][0][1],
            index, rows[index][0], rows,
            country_code=country_codes[index], country_codes=country_codes,
            country_name=names[index], country_names=names,
            hand_back=cfg.preview_window.value)
    _require_parental_pin(session, screen, names[index], _play,
                          channel_name=rows[index][0][0])


def play_entries(session, screen, entries, index, on_closed=None):
    """One of the saved channels `entries` ([{name, url, country_name}]:
    favourites, recently watched) full screen, the others as the
    player's list (the PIN for a locked one)."""
    results = [(e.get("name"), e.get("url"), e.get("country_name"))
               for e in entries if e.get("url")]
    if not results:
        return False
    index = max(0, min(index, len(results) - 1))
    name, url, country = results[index]
    play_search_result(session, screen, (name, url, country, results, index),
                       on_closed or _no_answer)
    return True


def play_last_watched(session, screen, on_closed=None):
    """0 in a list (as RECALL in the player): the channel watched last,
    full screen, the recently watched as the player's list."""
    if not play_entries(session, screen, vUtils.load_recent() or [], 0,
                        on_closed):
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Nothing watched yet"), 3)


def open_favourites_guide(session, screen, on_closed=None):
    """EPG in the main list: the programme guide of the favourites;
    "Watch" plays the channel, the favourites as the player's list."""
    channels = favourite_channels()
    if not channels:
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("No favourites yet. Open a country and press "
                           "GREEN on a channel."), 4)
        return

    def watched(result=None):
        if result and result[0] == "watch" and \
                not getattr(screen, "_closed", False):
            play_entries(session, screen, channels, result[1], on_closed)
    session.openWithCallback(watched, VavooGuide, channels, 0,
                             _("★ Favourites"))


class VavooSearch(Screen):
    """Live search. `itemlist`: "name###url" strings, or
    "name###url###country" when searching several countries (each row
    then shows its country, and closing hands it back as a third
    item). `scope`: what is searched, for the title ("Portugal", "all
    channels")."""

    # Programme matches (the app's): from 3 letters, at most this many.
    PROGRAMME_MIN = 3
    PROGRAMME_MAX = 100

    def __init__(self, session, parentScreen, itemlist, scope=None,
                 country_code=None):
        self.session = session
        self.parentScreen = parentScreen
        self.itemlist = itemlist
        # [(name, url, country)] and each name normalized once
        # (vavoo_store.normalize(): no accents, no case)
        self._items = []
        for item in itemlist or []:
            parts = to_string(item).split('###')
            if len(parts) < 2:
                continue
            url = parts[1].replace('%0a', '').replace(
                '%0A', '').strip("\r\n")
            self._items.append((parts[0], url,
                                parts[2] if len(parts) > 2 else None))
        self._norms = [vavoo_store.normalize(item[0]) for item in self._items]
        # one country searched: its code, for the programme matches
        self._country_code = country_code
        self._codes = {}
        self._favourites = vUtils.favourite_urls()
        # [(name, url, country, programme title or None)]
        self.filteredList = []
        self.selectedIndex = 0
        self.search_text = ""
        self.current_input = ""
        self.skin, self._themed = load_screen_skin(
            "search", 'vavoo_search.xml', cvs=True, background=False)
        Screen.__init__(self, session)
        self["search_label"] = Label(
            _("Search {}").format(to_string(scope)) if scope
            else _("Search Channels:"))
        self["search_text"] = Label("")
        self['version'] = Label()
        self["input_info"] = Label(
            _("Press GREEN to type, YELLOW to delete"))
        self["channel_list"] = m2list([], kind="search", themed=self._themed)
        self["status"] = Label(_("Enter text to search..."))
        self["key_red"] = Label(_("Clear All"))
        self["key_green"] = Label(_("Keyboard"))
        self["key_yellow"] = Label(_("Backspace"))
        self["key_blue"] = Label(_("Space"))
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions", "ColorActions", "NumberActions"],
            {
                "ok": self.onOk,
                "cancel": self.onCancel,
                "up": self.moveUp,
                "down": self.moveDown,
                "left": self.moveLeft,
                "right": self.moveRight,
                "red": self.clearSearch,
                "green": self.openKeyboard,
                "yellow": self.deleteChar,
                "blue": self.addSpace,
                "1": lambda: self.keyNumber(1),
                "2": lambda: self.keyNumber(2),
                "3": lambda: self.keyNumber(3),
                "4": lambda: self.keyNumber(4),
                "5": lambda: self.keyNumber(5),
                "6": lambda: self.keyNumber(6),
                "7": lambda: self.keyNumber(7),
                "8": lambda: self.keyNumber(8),
                "9": lambda: self.keyNumber(9),
                "0": lambda: self.keyNumber(0),
            }, -1)
        self["list_keys"] = list_keys({"help": self.show_help,
                                       "search": self.openKeyboard,
                                       "back": self.onCancel})

        self.numericalInput = NumericalTextInput(
            nextFunc=self.searchWithString)
        self.input_active = False
        self.upper_case = False
        self.last_key = None
        self.search_text = ""
        self.last_key_time = 0

        self.updateFilteredList()

    def show_help(self):
        show_keys(self.session, [
            ("0-9", _("Type (as on a phone)")),
            (_("GREEN / TEXT"), _("The keyboard")),
            (_("YELLOW"), _("Delete a letter")),
            (_("BLUE"), _("A space")),
            (_("RED"), _("Clear")),
            ("OK", _("Play the channel")),
            (_("UP / DOWN"), _("Result")),
            (_("EXIT"), _("Back")),
        ])

    def keyNumber(self, number):
        key_chars = {
            2: "abc2", 3: "def3", 4: "ghi4", 5: "jkl5", 6: "mno6",
            7: "pqrs7", 8: "tuv8", 9: "wxyz9", 0: " 0", 1: "1"
        }
        if number in key_chars:
            chars = key_chars[number]
            current_time = time.time()
            if hasattr(
                    self,
                    'last_key') and self.last_key == number and current_time - self.last_key_time < 1.0:
                if self.search_text and self.search_text[-1] in chars:
                    current_index = chars.index(self.search_text[-1])
                    next_index = (current_index + 1) % len(chars)
                    self.search_text = self.search_text[:-
                                                        1] + chars[next_index]
                else:
                    self.search_text += chars[0]
            else:
                self.search_text += chars[0]

            self["search_text"].setText(self.search_text)
            self.updateFilteredList()

            self.last_key = number
            self.last_key_time = current_time

    def searchWithString(self):
        """Callback called by NumericalTextInput - nothing to do"""
        pass

    def deleteChar(self):
        """Delete the last character"""
        if self.search_text:
            self.search_text = self.search_text[:-1]
            self["search_text"].setText(self.search_text)
            self.numericalInput.nextKey()  # Reset NumericalTextInput
            self.updateFilteredList()

    def clearSearch(self):
        """Clear the entire search"""
        self.search_text = ""
        self["search_text"].setText("")
        self.numericalInput.nextKey()
        self.updateFilteredList()

    def addSpace(self):
        """Add a space"""
        self.search_text += " "
        self["search_text"].setText(self.search_text)
        self.updateFilteredList()

    def openKeyboard(self):
        self.session.openWithCallback(
            self.onKeyboardClosed,
            VirtualKeyBoard,
            title=_("Search..."),
            text=self.search_text)

    def onKeyboardClosed(self, result):
        if result is not None:
            self.search_text = result
            self["search_text"].setText(self.search_text)
            self.updateFilteredList()

    def toggleCase(self):
        """Toggle between uppercase and lowercase"""
        self.upper_case = not self.upper_case
        case_text = _("UPPERCASE") if self.upper_case else _("lowercase")
        self["status"].setText(_("Case: {}").format(case_text))

    def updateStatusText(self):
        """Update status text"""
        if self.search_text:
            # Separa in parti senza virgolette
            part1 = _("Search:")
            part2 = _('Found: {} channels').format(len(self.filteredList))
            message = '{0} "{1}" - {2}'.format(part1, self.search_text, part2)
            self["status"].setText(message)
        else:
            self["status"].setText(
                _("Showing all channels: {}").format(len(self.filteredList)))

    def updateFilteredList(self):
        """The app's search (vavoo_store.search_matches()): every word
        at the start of a word of the name, or (3+ letters) anywhere;
        numbers whole. Names starting with the first word first. From
        3 letters, then the channels whose programme on now has the
        text (guides already in memory only)."""
        words = vavoo_store.search_words(self.search_text)
        if not words:
            self.filteredList = [item + (None,) for item in self._items]
            self["status"].setText(
                _("{} channels").format(len(self.filteredList)))
        else:
            found = []
            for index, norm in enumerate(self._norms):
                if vavoo_store.search_matches(norm, words):
                    found.append((not norm.startswith(words[0]), norm, index))
            found.sort()
            self.filteredList = [self._items[i] + (None,)
                                 for _first, _norm, i in found]
            query = u" ".join(words)
            if len(query) >= self.PROGRAMME_MIN:
                self.filteredList += self._programme_matches(
                    query, set(i for _first, _norm, i in found))
            self["status"].setText(
                _("{} found").format(len(self.filteredList)))

        self.updateChannelList()

        if self.filteredList:
            self.selectedIndex = 0
            self["channel_list"].moveToIndex(self.selectedIndex)
        else:
            self.selectedIndex = -1

        self["version"].setText(to_string("V." + __version__))

    def _code_for(self, country):
        if not country:
            return self._country_code
        if country not in self._codes:
            try:
                self._codes[country] = get_country_code(country)
            except Exception:
                self._codes[country] = None
        return self._codes[country]

    def _programme_matches(self, query, skip):
        """Channels whose programme on now holds `query`, from the
        guides in memory (vUtils.peek_now_next(): never a download) -
        locked channels left out."""
        out = []
        loaded = {}
        for index, (name, url, country) in enumerate(self._items):
            if index in skip:
                continue
            code = self._code_for(country)
            if not code:
                continue
            if code not in loaded:
                try:
                    loaded[code] = vUtils.peek_epg_guide(code) is not None
                except Exception:
                    loaded[code] = False
            if not loaded[code]:
                continue
            try:
                if vavoo_store.is_channel_locked(
                        name, country or getattr(self.parentScreen,
                                                 'country_name', None)):
                    continue
                answer = vUtils.peek_now_next(name, code)
            except Exception:
                continue
            if not answer or answer[0] != "ok" or not answer[1]:
                continue
            title = to_text(answer[1][2])
            if query in vavoo_store.normalize(title):
                out.append((name, url, country, title))
                if len(out) >= self.PROGRAMME_MAX:
                    break
        return out

    def updateChannelList(self):
        """Rows as the app's: "Name  ★" (a favourite), "  · Country"
        when several countries are searched, "  ▶ title" for a
        programme match."""
        display_list = []
        for name, url, country, title in self.filteredList:
            try:
                text = to_text(name)
                if to_text(url) in self._favourites:
                    text += u"  \u2605"
                if country:
                    text += u"  \u00b7 " + to_text(country)
                if title:
                    text += u"  \u25b6 " + title[:30]
                # Without is_channel=True, show_list() takes its
                # "this is a country name" branch for every search
                # result - a country lookup (and a disk stat) for each
                # row, on every single keystroke.
                display_list.append(show_list(
                    name, url, is_channel=True, display=to_string(text),
                    kind="search", themed=self._themed))
            except Exception:
                continue
        self["channel_list"].l.setList(display_list)

    def moveUp(self):
        if self.filteredList:
            self.selectedIndex = max(0, self.selectedIndex - 1)
            self["channel_list"].moveToIndex(self.selectedIndex)

    def moveDown(self):
        if self.filteredList:
            self.selectedIndex = min(
                len(self.filteredList) - 1, self.selectedIndex + 1)
            self["channel_list"].moveToIndex(self.selectedIndex)

    def moveLeft(self):
        self.moveUp()

    def moveRight(self):
        self.moveDown()

    def onOk(self):
        """Closes with (name, url, country, results, index): the
        results go to the player as its list (CH± goes along them)."""
        if self.filteredList and 0 <= self.selectedIndex < len(
                self.filteredList):
            name, url, country, _title = self.filteredList[self.selectedIndex]
            results = [(n, u, c) for n, u, c, _t in self.filteredList]
            self.close((name, url, country, results, self.selectedIndex))
        else:
            self.close(None)

    def onCancel(self):
        """Return to the Vavoo screen without opening the player"""
        print("DEBUG: Search cancelled, returning to Vavoo main screen")
        self.close()

    def close(self, *args, **kwargs):
        """Cleanup when the screen is closed"""
        try:
            # Reset input
            if hasattr(self, 'numericalInput'):
                self.numericalInput.nextKey()
        except Exception as e:
            print("[VavooSearch] Error in close: {0}".format(e))

        return Screen.close(self, *args, **kwargs)


class AutoStartTimer(object):
    def __init__(self):
        print("*** AutoStartTimer Vavoo ***")

        # self.timer must always exist after __init__ - check_configuring()
        # can call update() on an already-constructed instance later (e.g.
        # after a subsequent, unrelated config Save), and update()/on_timer()
        # unconditionally call self.timer.stop(). Previously this attribute
        # was only set below the early-return, so an instance created before
        # any bouquet was ever exported/favorited would crash the *next*
        # config Save with an AttributeError - silently aborting save()
        # before it persisted the user's settings.
        self.timer = eTimer()
        try:
            self.timer.callback.append(self.on_timer)
        except BaseException:
            self.timer.timeout.connect(self.on_timer)

        # The actual intended fire time, persisted across on_timer()
        # calls instead of recomputed fresh each time - see update()/
        # on_timer() for why: get_wake_time() for "interval" mode
        # always returns now + interval*60 relative to whenever it's
        # called, so calling it fresh at check-time can never look
        # "due" the way it needs to for on_timer() to detect that the
        # real target has actually been reached.
        self.next_wake_time = None

        # Check if there are bouquets to update
        favorite_channel = vavoo_store.bouquet_list_file()

        if not isfile(favorite_channel):
            print("[AutoStartTimer] No bouquet list yet - timer created but idle")
            return

        print("[AutoStartTimer] Bouquet list found, starting timer...")
        self.timer.start(100, True)
        self.update()

    def on_timer(self):
        """Timer callback - triggered when timer expires.

        update()'s eTimer schedule is capped at 3600s even when the
        real target is further out (a safety re-check, e.g. across
        suspend/resume or a clock change) - so this can fire well
        before the actual configured interval/fixed-time target. Must
        check elapsed wall-clock time against the real persisted
        target (self.next_wake_time), not just treat "the timer fired"
        as "it's time" - the previous version did exactly that for
        "interval" mode (never checked at all), which was why it ran
        every ~60 minutes regardless of the configured interval.
        """
        print("[AutoStartTimer] Timer triggered")
        self.timer.stop()

        now = int(time.time())
        wake = self.next_wake_time if self.next_wake_time is not None else now
        constant = 0

        if wake - now < 60:
            try:
                self.startMain()
                constant = 60
                localtime = time.asctime(time.localtime(time.time()))
                cfg.last_update.value = localtime
                cfg.last_update.save()
            except Exception as e:
                print("[AutoStartTimer] Error in startMain:", e)
                trace_error()

        self.update(constant)

    def get_wake_time(self):
        if cfg.autobouquetupdate.value is True:
            if cfg.timetype.value == "interval":
                interval = int(cfg.updateinterval.value)
                nowt = time.time()
                return int(nowt) + interval * 60
            if cfg.timetype.value == "fixed time":
                ftc = cfg.fixedtime.value
                now = time.localtime(time.time())
                fwt = int(time.mktime((
                    now.tm_year,
                    now.tm_mon,
                    now.tm_mday,
                    ftc[0],
                    ftc[1],
                    now.tm_sec,
                    now.tm_wday,
                    now.tm_yday,
                    now.tm_isdst
                )))
                return fwt
            # cfg.timetype only ever offers "interval"/"fixed time"
            # today, but fall back safely instead of implicitly
            # returning None (which would TypeError in update()'s
            # `if wake > 0`) if that ever changes.
            return -1
        else:
            return -1

    def update(self, constant=0):
        """Schedule the next timer wake-up.

        Only computes a fresh target via get_wake_time() when none is
        persisted yet (first run, or scheduling was disabled) -
        otherwise reuses self.next_wake_time so a capped, early
        re-check (see on_timer()) doesn't lose track of the real
        target and reschedule based on a brand new one every time it
        wakes up. When on_timer() just ran because the persisted
        target was actually reached (constant=60), the `wake < nowt +
        constant` branch below is what advances next_wake_time to the
        following cycle - not a separate reset.
        """
        self.timer.stop()
        # Not just "is None": get_wake_time() returns -1 while
        # scheduling is disabled (autobouquetupdate off) - must keep
        # recomputing in that case too, or re-enabling it later would
        # get stuck reusing a stale -1 forever instead of picking up
        # a real target.
        if not self.next_wake_time or self.next_wake_time <= 0:
            self.next_wake_time = self.get_wake_time()
        wake = self.next_wake_time
        nowt = time.time()
        if wake > 0:
            if wake < nowt + constant:
                if cfg.timetype.value == "interval":
                    interval = int(cfg.updateinterval.value)
                    wake += interval * 60
                elif cfg.timetype.value == "fixed time":
                    wake += 86400
                self.next_wake_time = wake
            next_time = wake - int(nowt)
            if next_time > 3600:
                next_time = 3600
            if next_time <= 0:
                next_time = 60
            self.timer.startLongTimer(next_time)
        else:
            wake = -1
        return wake

    def startMain(self):
        favorite_channel = vavoo_store.bouquet_list_file()
        if not isfile(favorite_channel):
            print("Bouquet list not found - no bouquets to update")
            return

        try:
            # 1. Read bouquets
            bouquets_to_update = []
            with codecs.open(favorite_channel, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and '|' in line:
                        parts = line.split('|')
                        if len(parts) >= 3 and parts[0].strip(
                        ) and parts[2].strip():
                            name = parts[0].strip()
                            url = parts[1].strip() if len(
                                parts) > 1 and parts[1].strip() else ""
                            export_type = parts[2].strip()
                            bouquets_to_update.append((name, url, export_type))

            if not bouquets_to_update:
                print("No valid bouquets found in Favorite.txt")
                return

            print("[AutoStartTimer] Updating " +
                  str(len(bouquets_to_update)) + " bouquets")

            # 2. Ensure proxy is running
            if not is_proxy_running():
                print("[AutoStartTimer] Starting proxy...")
                if not run_proxy_in_background():
                    print("[AutoStartTimer] Failed to start proxy")
                    return

            # 3. Wait for proxy to be ready - polls via reactor.callLater
            # instead of blocking this thread with select.select(), which
            # would otherwise freeze the whole Enigma2 GUI (e.g. while the
            # user is watching TV) for up to 10s during this unattended
            # scheduled update.
            self._wait_for_proxy_then_update(bouquets_to_update, 10)

        except Exception as e:
            print("[AutoStartTimer] Error: " + str(e))
            import traceback
            traceback.print_exc()

    def _wait_for_proxy_then_update(self, bouquets_to_update, attempts_left):
        if is_proxy_ready(timeout=3) or attempts_left <= 1:
            # _update_bouquets() does the real work: EPG matching, EPG
            # feed downloads, and bouquet file I/O for every favorited
            # country, all synchronous - easily minutes for a multi-country
            # update. This method runs via reactor.callLater, i.e. on
            # Enigma2's single main/GUI thread (same one this class was
            # already careful about above, for the much shorter proxy
            # wait) - calling it directly here would freeze the whole box,
            # unattended, for however long the update takes. Run it in a
            # background thread instead, same pattern export_bouquet_async()
            # already uses for the manual export path.
            #
            # export_lock: _update_bouquets() ends up writing the same
            # vavoo_epg_cache.json a manual export (message2()) or the
            # cache-fix button (_fix_cache_format()) can also be writing -
            # both of those already hold this lock for their whole run
            # (see _fix_cache_format()'s own comment on why). Before this
            # method ran in the background, that overlap was impossible -
            # a synchronous scheduled update blocked the whole GUI, so the
            # user couldn't trigger a manual export at the same time.
            # Running here now makes that overlap real, so join the same
            # lock: skip this cycle non-blockingly if one's already in
            # progress rather than risk two concurrent read-modify-write
            # cycles silently losing each other's cache updates.
            if not export_lock.acquire(False):
                print(
                    "[AutoStartTimer] Export already in progress, "
                    "skipping this scheduled update")
                return
            t = threading.Thread(
                target=self._update_bouquets, args=(bouquets_to_update,))
            t.daemon = True
            t.start()
            return
        print("[AutoStartTimer] Waiting for proxy (" +
              str(11 - attempts_left) + "/10)")
        reactor.callLater(
            1,
            self._wait_for_proxy_then_update,
            bouquets_to_update,
            attempts_left - 1)

    def _update_bouquets(self, bouquets_to_update):
        try:
            # 4. Update each bouquet
            successful_updates = 0
            for name, url, export_type in bouquets_to_update:
                print("[AutoStartTimer] Updating: " + name)

                # Remove old bouquet
                removed = remove_bouquets_by_name(name)
                if removed > 0:
                    print(
                        "[AutoStartTimer] Removed " +
                        str(removed) +
                        " old bouquet files")

                # Create new bouquet (proxy only)
                ch = convert_bouquet(
                    cfg.services.value,
                    name,
                    url,  # Can be empty
                    export_type,
                    cfg.list_position.value
                )

                if ch > 0:
                    successful_updates += 1
                    print("[AutoStartTimer] ✓ Updated: " +
                          name + " (" + str(ch) + " channels)")
                    _update_favorite_file(name, url, export_type)
                else:
                    print("[AutoStartTimer] ✗ Failed: " + name)

            # 5. Update timestamp
            if successful_updates > 0:
                localtime = time.asctime(time.localtime(time.time()))

                def _save_last_update():
                    cfg.last_update.value = localtime
                    cfg.last_update.save()
                reactor.callFromThread(_save_last_update)
                print("[AutoStartTimer] Updated " +
                      str(successful_updates) +
                      "/" +
                      str(len(bouquets_to_update)) +
                      " bouquets")

        except Exception as e:
            print("[AutoStartTimer] Error: " + str(e))
            import traceback
            traceback.print_exc()
        finally:
            export_lock.release()


delayed_start_timer = None


def delayed_boot_tasks():
    global auto_start_timer
    try:
        # If the plugin has already been opened, do not start the proxy
        # here
        if _session is not None:
            print("[Vavoo] Plugin already opened, boot tasks skipped")
            return
        if serving_here():
            print("[Vavoo] Proxy already running at boot")
        else:
            # nothing on the port, a start in progress, or another
            # copy's proxy on it: run_proxy_in_background() sorts it out
            print("[Vavoo] Starting proxy at boot...")
            run_proxy_in_background()

        if cfg.autobouquetupdate.value:
            if auto_start_timer is None:
                auto_start_timer = AutoStartTimer()

    except Exception as e:
        print("[Vavoo] Delayed boot tasks error: " + str(e))


def autostart(reason, session=None, **kwargs):
    global _autostart_scheduled, delayed_start_timer

    # NOTE: this must NOT set the module-level _session - that's how
    # delayed_boot_tasks() (below) tells whether the user has actually
    # opened a plugin screen since boot. It used to be set here too,
    # which meant delayed_boot_tasks() always saw it as non-None (this
    # function had just set it moments earlier) and always skipped
    # starting the proxy at boot, regardless of whether the plugin was
    # ever opened - the proxy would only exist in a half-initialized
    # state (token monitor thread running, since that starts at module
    # import) with no actual HTTP server listening.
    if reason == 0 and not _autostart_scheduled and session is not None:
        _autostart_scheduled = True
        # reminders go off with the plugin closed too
        try:
            REMINDERS.start(session)
        except Exception as e:
            print("[vavoo] Reminders not started: {}".format(e))

        delayed_start_timer = eTimer()
        try:
            delayed_start_timer.callback.append(delayed_boot_tasks)
        except BaseException:
            delayed_start_timer.timeout.connect(delayed_boot_tasks)

        delayed_start_timer.startLongTimer(30)   # run 30 seconds after boot


def check_configuring():
    """React to a live change of the scheduled auto-update settings,
    instead of requiring a reboot for them to take effect."""
    global auto_start_timer
    if cfg.autobouquetupdate.value is True:
        if auto_start_timer is None:
            auto_start_timer = AutoStartTimer()
        else:
            auto_start_timer.update()
    else:
        timer = getattr(auto_start_timer, 'timer', None)
        if timer is not None:
            timer.stop()
        return


# A recording set in the guide wakes the box from deep standby this
# long before it starts (Enigma2 asks when it shuts down).
WAKE_BEFORE = 300


def get_next_wakeup():
    try:
        alarm = vavoo_store.next_alarm(kind=vavoo_store.KIND_RECORD)
    except Exception as e:
        debug("Next recording not read: {}".format(e))
        alarm = None
    if not alarm or alarm <= time.time():
        return -1
    return int(alarm) - WAKE_BEFORE


def add_skin_font():
    print('**********addFont')
    from enigma import addFont
    FNT_Path = join(PLUGIN_PATH, "fonts")
    # addFont(join(FNT_Path, 'Lcdx.ttf'), 'Lcdx', 100, 0)
    addFont(join(FNT_Path, 'MavenPro-Medium.ttf'), 'cvfont', 100, 0)
    # The themes' fonts (Lexend, Manrope, Sora, Oxanium - the app's,
    # SIL Open Font License, see fonts/*-OFL.txt). A missing file only
    # means its theme is not used (build_theme_skin()).
    for path, name in vavoo_theme.fonts_to_register(PLUGIN_PATH):
        if isfile(path):
            try:
                addFont(path, name, 100, 0)
            except Exception as e:
                print("[Theme] Font {} not registered: {}".format(name, e))


def cfgmain(menuid, **kwargs):
    if menuid == "mainmenu":
        return [(_('Vavoo Stream Live'), main, 'Vavoo', 11)]
    else:
        return []


# Two public DNS servers: a network that blocks one (some providers and
# firewalls block 8.8.8.8) is not taken for no Internet at all.
INTERNET_PROBES = (('8.8.8.8', 53), ('1.1.1.1', 53))


def checkInternet():
    import socket
    for address in INTERNET_PROBES:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.settimeout(0.5)
                s.connect(address)
                return True
            finally:
                s.close()
        except Exception:
            continue
    return False


def main(session, **kwargs):
    try:
        if _is_vavoo_already_open(session):
            session.open(
                MessageBox,
                _("Vavoo is already running."),
                MessageBox.TYPE_INFO,
                timeout=5
            )
            return
        if not checkInternet():
            session.open(
                MessageBox,
                _("No Internet connection detected. Please check your network."),
                MessageBox.TYPE_INFO)
            return
        # if isfile(LOG_FILE):
            # remove(LOG_FILE)
        add_skin_font()
        try:
            initialize_cache_with_local_flags()
            cleanup_old_temp_files()
            # the logos on a flash disk when there is one, else in /tmp
            # (RAM: kept small)
            folder = vUtils.set_picon_cache_dir(logo_folder())
            print("[Picons] Logos in {}".format(folder))
            vUtils.trim_picon_cache()
        except Exception as e:
            print("Cache initialization error: %s" % str(e))
        clean_pause_leftovers()
        session.open(startVavoo)
    except Exception as e:
        print('error as:', e)
        trace_error()


def Plugins(**kwargs):
    plugin_name = title_plug
    plugin_description = _('Vavoo Stream Live')
    plugin_icon = PLUGLOGO

    main_descriptor = PluginDescriptor(
        name=plugin_name,
        description=plugin_description,
        where=PluginDescriptor.WHERE_MENU,
        icon=plugin_icon,
        fnc=cfgmain
    )

    plugin_menu_descriptor = PluginDescriptor(
        name=plugin_name,
        description=plugin_description,
        where=PluginDescriptor.WHERE_PLUGINMENU,
        icon=plugin_icon,
        fnc=main
    )

    autostart_descriptor = PluginDescriptor(
        name=plugin_name,
        description=plugin_description,
        where=[
            PluginDescriptor.WHERE_AUTOSTART,
            PluginDescriptor.WHERE_SESSIONSTART],
        fnc=autostart,
        wakeupfnc=get_next_wakeup)

    result = [plugin_menu_descriptor, autostart_descriptor]

    if cfg.stmain.value:
        result.append(main_descriptor)

    return result
