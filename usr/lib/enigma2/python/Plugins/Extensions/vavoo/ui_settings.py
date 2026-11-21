#!/usr/bin/python
# -*- coding: utf-8 -*-
"""The Settings screen, backup / restore, licences and About."""
from __future__ import absolute_import, print_function

import codecs
import threading
from os import listdir, remove
from os.path import (
    basename,
    dirname,
    join,
    isfile
)
from json import loads
from twisted.internet import reactor
from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.config import (
    getConfigListEntry,
    configfile,
    config,
    ConfigSubsection
)
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from .vavoo_stats import stop_heartbeat, STATS_DISABLE_FILE
from .vavoo_proxy import run_proxy_in_background, restart_proxy_in_background
from . import (
    _,
    __author__,
    __version__,
    __license__,
    PORT,
    PROXY_HOST,
    PROXY_BASE_URL,
    PROXY_COUNTRIES_URL,
    LOG_FILE,
    literals_for
)
from . import vavoo_store
from . import vavoo_record
from .bouquet_manager import reorganize_all_bouquets_position, get_local_ip
from .vUtils import (
    debug,
    make_print,
    update_epg_sources,
    ensure_vavoo_epg_sources_enabled,
    decodeHtml,
    ensure_str,
    getUrl,
    is_proxy_ready,
    is_proxy_running,
    remove_parentheses,
    strip_control_chars,
    trace_error
)
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
    ENIGMA_PATH, PLUGIN_PATH, VavooLogViewer, add_skin_back, cfg, clock_24,
    current_theme, downloadfree, list_keys, load_screen_skin, named,
    open_action_menu, open_log_viewer, show_keys, to_string, to_text,
    url_quote)
from .ui_pick import (
    VavooCountries, VavooParental, ask_pin)
from .ui_record import (
    RECORDINGS, VavooRecordings, record_folder_choices, recordings_folder,
    size_text)


def basic_rows():
    """The settings shown first (the rest behind "All settings"): the
    ones people change - the look, the player, the lists, the
    countries, the PIN, recordings, backup and About."""
    return (cfg.theme, cfg.back, cfg.text_size, cfg.clock_format,
            cfg.preview_window, cfg.start_last, cfg.timeshift, cfg.list_epg,
            cfg.logos, cfg.choose_countries, cfg.parental, cfg.recordings,
            cfg.backup, cfg.restore, cfg.about)


class vavoo_config(Screen, ConfigListScreen):
    _closed = True          # (ui_base's CLOSED_UNTIL_OPEN)

    def __init__(self, session):
        # So background M3U-fetch threads (_fetch_countries_async/
        # _fetch_channels_async) can notice this screen was left and
        # stop trying to pop dialogs on top of whatever the user has
        # since navigated to.
        self._closed = False
        Screen.__init__(self, session)
        self.session = session
        self.skin, self._themed = load_screen_skin(
            "config", 'vavoo_config.xml', cvs=True, clock_24=clock_24())
        self.setup_title = ('Vavoo Config')

        self.old_back = cfg.back.value
        # The settings that change how the screens are built - the
        # screen behind this one keeps the old look until reopened.
        self.old_look = self._look_settings()
        self.old_list_position = cfg.list_position.value
        self.old_catalog_source = cfg.catalog_source.value
        self.onClose.append(self._mark_closed)

        self.list = []
        self.onChangedEntry = []
        self["version"] = Label()
        self['statusbar'] = Label()
        self["description"] = Label("")
        self["red"] = Label(_("Back"))
        self["green"] = Label(_("- - - -"))
        self['actions'] = ActionMap(['OkCancelActions', 'ColorActions', 'DirectionActions'], {
            "cancel": self.extnok,
            "left": self.keyLeft,
            "right": self.keyRight,
            "up": self.keyUp,
            "down": self.keyDown,
            "red": self.extnok,
            "green": self.save,
            "ok": self.gnm3u,
        }, -1)
        self['list_keys'] = list_keys({"help": self.show_help,
                                       "back": self.extnok})
        self.update_status()
        # Basic first: the rows people change (BASIC_ROWS); the last row
        # shows all of them
        self.show_all = False
        self._rows_seen = {}
        ConfigListScreen.__init__(
            self,
            self.list,
            session=self.session,
            on_change=self.changedEntry)
        self.createSetup()
        self.showhide()
        self.onLayoutFinish.append(self.layoutFinished)

    def _mark_closed(self):
        self._closed = True

    def help_rows(self):
        return [
            (_("UP / DOWN"), _("Setting")),
            (_("LEFT / RIGHT"), _("Change it")),
            ("OK", _("Open (a row that opens a list or does something)")),
            ("OK", _("On the last row: all settings / fewer")),
            (_("GREEN"), _("Save")),
            (_("RED / EXIT"), _("Back (without saving)")),
        ]

    def show_help(self):
        show_keys(self.session, self.help_rows())

    @staticmethod
    def _look_settings():
        # (not "Show Counts": the main list is filled again on return)
        return (cfg.theme.value, cfg.text_size.value, cfg.clock_format.value)

    def update_status(self):
        if cfg.autobouquetupdate.value:
            self['statusbar'].setText(
                _("Last channel update: %s") %
                cfg.last_update.value)

    def layoutFinished(self):
        self.setTitle(self.setup_title)
        self['version'].setText('V.' + __version__)

    def createSetup(self):
        self.editListEntry = None
        self.list = []
        indent = "- "
        # The look first, as in the app's settings.
        self.list.append(getConfigListEntry(
            _("Theme"),
            cfg.theme,
            _("Prism: Vavoo's violet. Halo: frosted glass over a blue "
              "aurora. Orbit: a teal cockpit display. Classic: the "
              "plugin's original skin, with its backgrounds. Takes "
              "effect when the plugin is opened again.")))
        # Classic's backgrounds: a sub-option of the theme, only with it
        self._built_theme = cfg.theme.value
        if current_theme() == "classic":
            self.list.append(getConfigListEntry(
                indent + _("Background"),
                cfg.back,
                _("Classic's background (Oktus or Kiddac). Takes effect "
                  "when the plugin is opened again.")))
        self.list.append(getConfigListEntry(
            _("Text Size"),
            cfg.text_size,
            _("Large: bigger lists, names and programme lines, easier to "
              "read from the sofa. Normal: smaller, more rows. Not used "
              "by Classic.")))
        self.list.append(getConfigListEntry(
            _("Show Counts"),
            cfg.show_counts,
            _("Show how many channels each country has, and how many "
              "favourites, in the main list.")))
        self.list.append(getConfigListEntry(
            _("Clock Format"),
            cfg.clock_format,
            _("Clock in the top-right corner and programme times. Not "
              "used by Classic's own clock.")))
        self.list.append(
            getConfigListEntry(
                _("Generate .m3u files (Ok for Exec)"),
                cfg.genm3u,
                _("Generate .m3u files and save to device %s.") %
                downloadfree))

        self.list.append(getConfigListEntry(
            _("Playlist Access Key (optional)"),
            cfg.playlist_key,
            _("If set, the live playlist at /playlist.m3u requires "
              "?key=<this value> - leave empty for no key. "
              "URL: http://%s:%d/playlist.m3u") % (PROXY_HOST, PORT)))

        self.list.append(
            getConfigListEntry(
                _("Catalog/Stream Source"),
                cfg.catalog_source,
                _("Which service to load channels and streams from. "
                  "Auto tries Geil first and falls back to Vavoo "
                  "if it's unavailable; the other two options pin it "
                  "to exactly that one source. Takes effect on save "
                  "(restarts the proxy if it's running).")
            )
        )

        self.list.append(getConfigListEntry(
            _("Proxy startup timeout (seconds)"),
            cfg.proxy_startup_timeout,
            _("Increase if proxy takes long due to VPN or slow connection.")))

        self.list.append(getConfigListEntry(
            _("Enable Vavoo EPG"),
            cfg.epg_enabled,
            _("Create the EPG source for EPGImport with Vavoo program data "
              "and enable it there after each export.")
        ))

        self.list.append(getConfigListEntry(
            _("Preview Window"),
            cfg.preview_window,
            _("OK plays the channel in the small window beside the list; "
              "OK again on it opens full screen (BLUE goes straight to "
              "full screen). Off: OK opens full screen at once.")))
        self.list.append(getConfigListEntry(
            _("Start with last channel"),
            cfg.start_last,
            _("Open the last watched channel when the plugin starts.")))
        self.list.append(getConfigListEntry(
            _("Pause Live TV"),
            cfg.timeshift,
            _("While a channel is paused it is recorded on the disk: play "
              "goes on from where you paused, LEFT / RIGHT move back and "
              "forth, EXIT returns to live (up to 2 hours).")))

        self.list.append(getConfigListEntry(
            _("Now/Next in channel list"),
            cfg.list_epg,
            _("Show the current and the next programme beside the "
              "channel list. The country's programme guide is "
              "downloaded when you open a country.")
        ))
        self.list.append(getConfigListEntry(
            _("Group Sources"),
            cfg.group_sources,
            _("The sources of one channel (.b, .c, .s) in one row; MENU "
              "→ Source in the player picks one. Off: every source in "
              "its own row.")))
        self.list.append(getConfigListEntry(
            _("Channel Logos"),
            cfg.logos,
            _("Show the channels' logos in the lists and the player. "
              "Off: each channel's initials on a tile of its own colour "
              "(Classic: the Vavoo icon), and no logo is downloaded.")))
        self.list.append(getConfigListEntry(
            _("Sub-categories"),
            cfg.subcategories,
            _("A country whose channels come in categories (Sport, "
              "News...) lists them first: All channels, the categories, "
              "General.")))

        # Grouped with "Enable Vavoo EPG" above rather than left down by
        # the other bouquet-related entries below: this schedule drives
        # EPG refresh timing too, not just bouquet regeneration -
        # AutoStartTimer._update_bouquets() does EPG matching, EPG
        # feed downloads, and bouquet file I/O as one combined cycle.
        self.list.append(
            getConfigListEntry(
                _("Scheduled EPG/Bouquet Update:"),
                cfg.autobouquetupdate,
                _("Periodically re-match EPG and refresh bouquets for your "
                  "favorited countries in the background.")))
        if cfg.autobouquetupdate.value is True:
            try:
                self.list.append(
                    getConfigListEntry(
                        indent + _("Schedule type:"),
                        cfg.timetype,
                        _("At an interval hours or fixed time")))
            except Exception as e:
                print("Error building 'Schedule type' config entry:", e)
            # Each sub-entry is wrapped independently: getConfigListEntry()
            # touches Enigma2 core config widgets (ConfigSelectionNumber/
            # ConfigClock) outside this repo, whose behavior can differ by
            # image/build (same class of issue as this session's wraparound-
            # navigation fix). createSetup() has no exception handling
            # anywhere else, and self["config"].l.setList(self.list) only
            # runs once at the very end - previously, a single entry
            # raising here silently aborted the ENTIRE rebuild, freezing
            # the screen on whatever it showed before with no visible
            # error, which is exactly what made "Update interval" (and
            # everything listed after it) appear to have vanished for one
            # user while working fine for another on a different image.
            if cfg.timetype.value == "interval":
                try:
                    self.list.append(
                        getConfigListEntry(
                            2 * indent + _("EPG/Bouquet update interval (minutes):"),
                            cfg.updateinterval,
                            _("How often to re-match EPG and refresh "
                              "bouquets, counting from now.")))
                except Exception as e:
                    print("Error building 'Update interval' config entry:", e)
            if cfg.timetype.value == "fixed time":
                try:
                    self.list.append(
                        getConfigListEntry(
                            2 *
                            indent +
                            _("Time to start EPG/bouquet update:"),
                            cfg.fixedtime,
                            _("Configure at a fixed time")))
                except Exception as e:
                    print(
                        "Error building 'Time to start update' config entry:", e)

        self.list.append(
            getConfigListEntry(
                _("Movie Services Reference"),
                cfg.services,
                _("Configure service Reference Iptv-Gstreamer-Exteplayer3")))

        self.list.append(
            getConfigListEntry(
                _("Bouquet Position in List"),
                cfg.list_position,
                _("Position of Vavoo bouquets in the main list"))
        )

        self.list.append(
            getConfigListEntry(
                _('Link in Main Menu'),
                cfg.stmain,
                _("Link in Main Menu")))
        self.list.append(getConfigListEntry(_("Send Anonymous Statistics"), cfg.stats_enabled, _(
            "Anonymous startup/heartbeat ping only (session id, version, timestamp - no personal data). Disable to opt out.")))
        self.list.append(getConfigListEntry(_("Debug logging"), cfg.debug_logging, _(
            "Show verbose DEBUG-level messages in vavoo.log (UI lifecycle, per-request detail). Takes effect immediately - leave off unless troubleshooting.")))
        self.list.append(getConfigListEntry(
            _("Choose countries"),
            cfg.choose_countries,
            _("Hide the countries you never watch from the main list and "
              "from search.")))
        self.list.append(getConfigListEntry(
            _("Parental Control"),
            cfg.parental,
            _("A 4-digit PIN for adult channels, chosen countries and "
              "(optionally) the settings. Once entered, all is open for "
              "15 minutes or until the plugin is left.")))
        self.list.append(getConfigListEntry(
            _("Recordings"),
            cfg.recordings,
            _("Reminders and recordings set in the guide, and the "
              "recordings on the disk. OK: play (or cancel a timer) - "
              "GREEN: delete.")))
        self.list.append(getConfigListEntry(
            to_string(to_text(_("Recordings folder: {}")).format(
                to_text(recordings_folder()))),
            cfg.record_folder,
            _("Where recordings go: Enigma2's movie folder, or another "
              "disk. They also show in the box's own movie list.")))
        self.list.append(getConfigListEntry(
            _("Backup Settings & Favourites"),
            cfg.backup,
            _("Saves the settings, the favourites (with folders and "
              "order), recently watched, the chosen sources and countries "
              "in /media/hdd, /media/usb or /media/mmc (else %s) - not "
              "parental control.") % ENIGMA_PATH))
        self.list.append(getConfigListEntry(
            _("Restore from Backup"),
            cfg.restore,
            _("Choose a backup: its settings and favourites replace the "
              "ones here.")))
        self.list.append(getConfigListEntry(
            _("Show Log (Ok to view)"),
            cfg.show_log,
            _("View the last 200 lines of %s.") % LOG_FILE))
        self.list.append(getConfigListEntry(
            _("View Favourites (Ok to open)"),
            cfg.view_favourites,
            _("Browse and play your starred channels. Add or remove a "
              "channel with the GREEN key while browsing.")))
        self.list.append(getConfigListEntry(
            _("Clear Favourites"),
            cfg.clear_favourites,
            _("Remove all favourite channels (asks to confirm).")))
        self.list.append(getConfigListEntry(
            _("Licences"),
            cfg.licences,
            _("The plugin's licence and the fonts' (SIL OFL).")))
        self.list.append(getConfigListEntry(
            _("About"),
            cfg.about,
            _("Vavoo Stream Live %s by Lululla & Qu4k3 - License CC "
              "BY-NC-SA 4.0.") % __version__))
        # every row ever shown is saved / cancelled (Enigma2 only does
        # the ones in the list - a change made in "All settings" and
        # then hidden again would be lost)
        for row in self.list:
            self._rows_seen[id(row[1])] = row[1]
        basic = basic_rows()
        hidden = [row for row in self.list if not any(row[1] is b for b in basic)]
        if not self.show_all:
            self.list = [row for row in self.list if any(row[1] is b for b in basic)]
            label = to_text(_("All settings ({} more)")).format(len(hidden)) + u" \u25b6"
            info = _("Show every setting: the channel sources, the proxy, EPG import, "
                     "bouquets, playlists, the log...")
        else:
            label = u"\u25c0 " + to_text(_("Fewer settings"))
            info = _("Back to the settings most people change.")
        self.list.append(getConfigListEntry(to_string(label), cfg.more_settings, info))
        self["config"].list = self.list
        self["config"].l.setList(self.list)
        self.setInfo()

    def backup(self):
        path = vavoo_store.write_backup(plugin_settings(), __version__)
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Saved: {}").format(path) if path
                         else _("The backup could not be saved"), 5)

    def choose_record_folder(self):
        entries = []
        for value, folder in record_folder_choices():
            free = vavoo_record.free_bytes(folder)
            label = to_text(folder)
            if value == "":
                label = to_text(_("Movie folder ({})")).format(label)
            if free is not None:
                label += u"  \u00b7  " + to_text(_("{} free")).format(
                    size_text(free))
            entries.append((to_string(label), value))

        def chosen(value):
            if value is None:
                return
            cfg.record_path.value = value
            cfg.record_path.save()
            configfile.save()
            try:
                self.createSetup()
            except Exception as e:
                debug("Settings list not rebuilt: {}".format(e))

        open_action_menu(self.session, _("Recordings folder"), entries,
                         chosen)

    def restore(self):
        if RECORDINGS.running():
            # (as the app: what a restore replaces is in use)
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Not now: a recording is running"), 4)
            return
        found = vavoo_store.list_backups()
        if not found:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("No backup found"), 4)
            return
        entries = [(to_string(u"{}  ({})".format(
            basename(path), to_text(dirname(path)))), path)
            for path, _mtime in found]
        open_action_menu(self.session, _("Restore from Backup"), entries,
                         self._restore_file)

    def _restore_file(self, path):
        data = vavoo_store.read_backup(path)
        if data is None:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("That file is not a Vavoo Stream backup"), 4)
            return
        apply_settings(vavoo_store.restore_backup(data))
        # the chosen sources are read by the proxy when it starts
        restart_proxy_in_background()
        try:
            self.createSetup()
        except Exception as e:
            debug("Settings list not rebuilt: {}".format(e))
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Restored - the theme and text size change when "
                           "the plugin is opened again"), 5)

    def _clear_favourites(self, answer=None):
        if answer:
            vavoo_store.clear_favourites()
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Favourites cleared"), 3)

    def toggle_all_settings(self):
        """The last row: every setting / only the basic ones. Opening
        all goes to the first row that was hidden."""
        before = len(self.list)
        self.show_all = not self.show_all
        self.createSetup()
        try:
            self["config"].setCurrentIndex(before - 1 if self.show_all else len(self.list) - 1)
        except Exception as e:
            debug("Settings: selection not moved: {}".format(e))

    def _all_entries(self):
        return list(self._rows_seen.values())

    def _settings_changed(self):
        for entry in self._all_entries():
            try:
                if entry.isChanged():
                    return True
            except Exception:
                pass
        return False

    def gnm3u(self):
        sel = self["config"].getCurrent()[1]
        if sel is cfg.more_settings:
            self.toggle_all_settings()
            return
        if sel and sel == cfg.genm3u:
            self.session.openWithCallback(
                self.generate_m3u,
                MessageBox,
                _("Generate .m3u files and save to device %s?") %
                downloadfree,
                MessageBox.TYPE_YESNO,
                timeout=10,
                default=True)
        elif sel and sel == cfg.show_log:
            open_log_viewer(self.session)
        elif sel and sel == cfg.choose_countries:
            self.session.open(VavooCountries)
        elif sel and sel == cfg.parental:
            ask_pin(self.session, self,
                    lambda: self.session.open(VavooParental))
        elif sel and sel == cfg.recordings:
            self.session.open(VavooRecordings)
        elif sel and sel == cfg.record_folder:
            self.choose_record_folder()
        elif sel and sel == cfg.backup:
            ask_pin(self.session, self, self.backup)
        elif sel and sel == cfg.restore:
            ask_pin(self.session, self, self.restore)
        elif sel and sel == cfg.clear_favourites:
            self.session.openWithCallback(
                self._clear_favourites, MessageBox,
                _("Remove all favourite channels?"), MessageBox.TYPE_YESNO,
                default=False)
        elif sel and sel == cfg.licences:
            show_licences(self.session)
        elif sel and sel == cfg.about:
            show_about(self.session)
        elif sel and sel == cfg.view_favourites:
            from .plugin import VavooFavourites   # (plugin.py imports this module)
            self.session.open(VavooFavourites)
        elif sel and sel == cfg.playlist_key:
            # Plain ConfigText entries have nothing else wired to the
            # "ok" key in this screen (gnm3u() is its sole handler) -
            # without this, pressing OK on these did nothing and the
            # field could never actually be set.
            self.session.openWithCallback(
                lambda result: self._on_text_entry_result(sel, result),
                VirtualKeyBoard,
                title=self.getCurrentEntry(),
                text=sel.value)

    def _on_text_entry_result(self, config_element, result):
        if result is not None:
            config_element.setValue(result)
            config_element.save()
            self.createSetup()

    def generate_m3u(self, result):
        if result:
            # 1. Check if the proxy is active (non-blocking - proceeds to
            # step 2 via callback once ready, instead of freezing the GUI
            # thread while polling)
            self.check_and_start_proxy_async(
                self.show_m3u_ip_selection,
                self._m3u_proxy_unavailable)

    def _m3u_proxy_unavailable(self):
        self.session.open(
            MessageBox,
            _("Proxy not active. Unable to generate M3U file."),
            MessageBox.TYPE_ERROR,
            timeout=5
        )

    def show_m3u_ip_selection(self):
        """Ask whether the M3U links should use 127.0.0.1 (playable only
        on this box) or the box's LAN IP (playable from other devices on
        the network)."""
        from Screens.ChoiceBox import ChoiceBox

        network_ip = get_local_ip()

        choices = [
            (_("Local only (127.0.0.1) - this device only"),
             PROXY_HOST),
            (_("Network (%s) - other devices on the LAN") %
             network_ip,
             network_ip),
        ]

        self.session.openWithCallback(
            self.on_m3u_ip_selected,
            ChoiceBox,
            title=_("Select the IP address to use in the M3U links:"),
            list=choices
        )

    def on_m3u_ip_selected(self, result):
        """Callback for M3U host selection"""
        if result is None:
            return

        self._m3u_host = result[1]

        # 3. Get country list from proxy - in a background thread and
        # continue in a callback: get_countries_from_proxy()'s getUrl()
        # call can block for tens of seconds on a slow/unresponsive
        # proxy, and this method runs directly on Enigma2's single GUI
        # thread as a ChoiceBox callback - calling it here synchronously
        # would freeze the whole box for that long.
        self._fetch_countries_async(self._on_countries_for_mode_choice)

    def _on_countries_for_mode_choice(self, countries):
        try:
            if not countries:
                raise Exception("No countries available")

            # 4. ASK MODE: single country or all?
            from Screens.ChoiceBox import ChoiceBox

            choices = [
                (_("All countries (%d)") % len(countries), "all"),
                (_("Only one specific country"), "single"),
                (_("Cancel"), "cancel")
            ]

            self.session.openWithCallback(
                self.on_m3u_mode_selected,
                ChoiceBox,
                title=_("Select M3U export mode:"),
                list=choices
            )

        except Exception as e:
            print("[M3U Export] Error: %s" % str(e))
            self.session.open(
                MessageBox,
                _("Error: %s") % str(e),
                MessageBox.TYPE_ERROR,
                timeout=5
            )

    def on_m3u_mode_selected(self, result):
        """Callback for M3U mode selection"""
        if result is None or result[1] == "cancel":
            return

        mode = result[1]
        self._fetch_countries_async(
            lambda countries: self._on_countries_for_mode(mode, countries))

    def _on_countries_for_mode(self, mode, countries):
        try:
            if not countries:
                raise Exception("No countries available")

            if mode == "all":
                # Generate for all countries
                self.session.openWithCallback(
                    lambda confirm: self.generate_all_m3u_files(
                        confirm,
                        countries),
                    MessageBox,
                    _("Generate .m3u files for ALL %d countries?") %
                    len(countries),
                    MessageBox.TYPE_YESNO)
            elif mode == "single":
                # Show country list for single selection
                self.show_country_selection(countries)

        except Exception as e:
            print("[M3U Export] Error in mode selection: %s" % str(e))
            self.session.open(
                MessageBox,
                _("Error: %s") % str(e),
                MessageBox.TYPE_ERROR,
                timeout=5
            )

    def show_country_selection(self, countries):
        """Show country list for single selection"""
        from Screens.ChoiceBox import ChoiceBox

        # Create choice list
        choices = []
        for country in sorted(countries):
            choices.append((country, country))

        choices.append((_("Cancel"), "cancel"))

        self.session.openWithCallback(
            self.on_country_selected,
            ChoiceBox,
            title=_("Select country to export M3U:"),
            list=choices
        )

    def on_country_selected(self, result):
        """Callback for selected country"""
        if result is None or result[1] == "cancel":
            return

        selected_country = result[1]

        # Get channels for the selected country - in a background
        # thread, same reasoning as _fetch_countries_async().
        self._fetch_channels_async(
            selected_country,
            lambda channels: self._on_channels_for_country(
                selected_country, channels))

    def _on_channels_for_country(self, selected_country, channels):
        if not channels or len(channels) == 0:
            self.session.open(
                MessageBox,
                _("No channels found for: %s") % selected_country,
                MessageBox.TYPE_WARNING,
                timeout=5
            )
            return

        # Ask confirmation for single country
        part1 = _("Generate .m3u file for:")
        part2 = str(selected_country)
        part3 = _("(%d channels)?") % len(channels)
        message = part1 + "\n" + part2 + "\n" + part3
        self.session.openWithCallback(
            lambda confirm: self.generate_single_country_m3u(
                confirm,
                selected_country,
                channels),
            MessageBox,
            message,
            MessageBox.TYPE_YESNO)

    def generate_single_country_m3u(self, confirm, country_name, channels):
        """Generate M3U for a single country"""
        if not confirm:
            return

        try:
            # Generate .m3u file
            m3u_count = self.generate_single_m3u(country_name, channels)

            if m3u_count > 0:
                msg_parts = []
                msg_parts.append(_("M3U file generated successfully!"))
                msg_parts.append("")
                msg_parts.append(_("Country: %s") % country_name)
                msg_parts.append(_("Channels: %d") % m3u_count)
                msg_parts.append(_("Saved in: %s") % downloadfree)
                msg = "\n".join(msg_parts)
                self.session.open(
                    MessageBox,
                    msg,
                    MessageBox.TYPE_INFO,
                    timeout=5
                )
            else:
                self.session.open(
                    MessageBox,
                    _("No valid channels for: %s") % country_name,
                    MessageBox.TYPE_WARNING,
                    timeout=5
                )

        except Exception as e:
            print("[M3U Export] Error for %s: %s" % (country_name, str(e)))
            self.session.open(
                MessageBox,
                _("M3U generation error: %s") % str(e),
                MessageBox.TYPE_ERROR,
                timeout=5
            )

    def generate_all_m3u_files(self, confirm, countries):
        """Generate .m3u files for all countries - the actual work runs
        on a background thread. This is invoked directly as a MessageBox
        confirmation callback, which Enigma2 runs synchronously on the
        GUI thread; looping get_channels_for_country() (a blocking
        getUrl(timeout=15) call) once per country here would freeze the
        whole box for up to countries*15 seconds, exactly what every
        other channel-fetch path in this wizard already avoids via
        _fetch_countries_async()/_fetch_channels_async()."""
        if not confirm:
            return

        def task():
            total_channels = 0
            generated = 0
            failed = 0

            for country in countries:
                try:
                    # Get channels for this country
                    channels = self.get_channels_for_country(country)
                    if not channels:
                        failed += 1
                        continue

                    # Generate .m3u file
                    m3u_count = self.generate_single_m3u(country, channels)

                    if m3u_count > 0:
                        total_channels += m3u_count
                        generated += 1
                        print(
                            "[M3U Export] OK %s: %d channels" %
                            (country, m3u_count))
                    else:
                        failed += 1
                        print("[M3U Export] FAIL %s: no channels" % country)

                except Exception as e:
                    failed += 1
                    print("[M3U Export] Error %s: %s" % (country, str(e)))

            reactor.callFromThread(
                self._on_all_m3u_files_done,
                generated, failed, total_channels, len(countries))

        t = threading.Thread(target=named(task, "vv-export"))
        t.daemon = True
        t.start()

    def _on_all_m3u_files_done(
            self, generated, failed, total_channels, total_countries):
        """Runs back on the GUI thread once generate_all_m3u_files()'s
        background loop finishes."""
        if self._closed:
            return

        try:
            # Show detailed result
            msg = _("M3U generation completed!")
            msg += "\n"
            msg += _("Countries: %(generated)d/%(total)d") % {
                'generated': generated, 'total': total_countries}
            msg += "\n"
            msg += _("Failed: %(failed)d") % {'failed': failed}
            msg += "\n"
            msg += _("Total channels: %(total_channels)d") % {
                'total_channels': total_channels}
            msg += "\n"
            msg += _("Saved in: %(path)s") % {'path': downloadfree}

            self.session.open(
                MessageBox,
                msg,
                MessageBox.TYPE_INFO,
                timeout=7
            )

        except Exception as e:
            print("[M3U Export] General error: %s" % str(e))
            self.session.open(
                MessageBox,
                _("M3U generation error: %s") % str(e),
                MessageBox.TYPE_ERROR,
                timeout=5
            )

    def generate_single_m3u(self, country_name, channels):
        """Generate a single .m3u file for a country"""
        try:
            # Sanitize filename
            safe_name = country_name.lower()
            safe_name = safe_name.replace(' ', '_')
            for sep in literals_for(safe_name, '➾', '⟾', '->', '→'):
                safe_name = safe_name.replace(sep, '_')

            m3u_filename = "vavoo_%s.m3u" % safe_name
            m3u_path = join(downloadfree, m3u_filename)

            # M3U header
            m3u_content = "#EXTM3U\n"

            host = getattr(self, '_m3u_host', None) or PROXY_HOST

            channel_count = 0
            for channel in channels:
                try:
                    if isinstance(channel, dict):
                        channel_name = channel.get('name', 'Unknown')
                        channel_id = channel.get('id', '')
                        if channel_id:
                            # Rebuild the proxy URL with the chosen host
                            # instead of the LAN IP the proxy always
                            # embeds in its /channels response.
                            # channel_id is catalog data too (same
                            # threat model as channel_name below) and
                            # is embedded directly into this line's
                            # URL, not just its text - url_quote()
                            # closes both the newline-injection gap and
                            # a stray "&"/"#"/space corrupting the URL
                            # itself. ensure_str(), not a plain str() -
                            # a grouped channel's id can carry a
                            # non-ASCII base name (clean_name_for_
                            # similarity() only strips punctuation, not
                            # non-ASCII letters), and plain str() on a
                            # Python 2 unicode value raises
                            # UnicodeEncodeError for any of those,
                            # silently dropping the channel (caught by
                            # this loop's own try/except below).
                            channel_url = "http://{}:{}/vavoo?channel={}".format(
                                host, PORT, url_quote(strip_control_chars(ensure_str(channel_id))))
                        else:
                            channel_url = strip_control_chars(
                                channel.get('url', ''))

                        # Clean channel name
                        channel_name = decodeHtml(channel_name)
                        channel_name = remove_parentheses(channel_name)
                        # Catalog-sourced, already treated as
                        # attacker-influenceable elsewhere (bouquet
                        # #NAME/Favorite.txt lines) - an embedded
                        # newline would inject extra lines into the
                        # generated .m3u file.
                        channel_name = strip_control_chars(channel_name)

                        # Write M3U entry
                        m3u_content += "#EXTINF:-1,%s\n" % channel_name
                        m3u_content += "%s\n" % channel_url
                        channel_count += 1

                except Exception as e:
                    print("[M3U] Error processing channel: %s" % str(e))
                    continue

            if channel_count == 0:
                print("[M3U] No valid channels for %s" % country_name)
                return 0

            # Write file
            with codecs.open(m3u_path, 'w', encoding='utf-8') as f:
                f.write(m3u_content)
            print(
                "[M3U] File created: %s (%d channels)" %
                (m3u_path, channel_count))

            return channel_count

        except Exception as e:
            print(
                "[M3U] Error generating M3U for %s: %s" %
                (country_name, str(e)))
            return 0

    def get_channels_for_country(self, country_name):
        """Get channels for a country from the proxy"""
        try:
            encoded_country = url_quote(country_name)
            proxy_url = PROXY_BASE_URL + \
                "/channels?country={}".format(encoded_country)
            response = getUrl(proxy_url, timeout=15)
            if not response:
                print("[M3U] No response for %s" % country_name)
                return []

            channels = loads(ensure_str(response))
            return channels

        except Exception as e:
            print("[M3U] Error getting channels: %s" % str(e))
            return []

    def _fetch_countries_async(self, on_done):
        """Run get_countries_from_proxy() in a background thread and
        deliver the result to on_done() on the reactor/GUI thread.
        get_countries_from_proxy() is a synchronous getUrl() call that
        can block for tens of seconds on a slow/unresponsive proxy -
        every caller here is a ChoiceBox/ MessageBox callback, i.e.
        already running on Enigma2's single GUI thread, so calling it
        directly would freeze the whole box for that long."""
        def task():
            if self._closed:
                return
            countries = self.get_countries_from_proxy()
            if self._closed:
                return
            reactor.callFromThread(on_done, countries)
        t = threading.Thread(target=named(task, "vv-lists"))
        t.daemon = True
        t.start()

    def _fetch_channels_async(self, country_name, on_done):
        """Same as _fetch_countries_async(), for get_channels_for_country()."""
        def task():
            if self._closed:
                return
            channels = self.get_channels_for_country(country_name)
            if self._closed:
                return
            reactor.callFromThread(on_done, channels)
        t = threading.Thread(target=named(task, "vv-lists"))
        t.daemon = True
        t.start()

    def check_and_start_proxy_async(
            self, on_ready, on_failed, attempts_left=10):
        """Check and start the proxy if needed, then call on_ready()/
        on_failed() once known - polls via reactor.callLater instead of
        blocking the GUI thread with select.select()."""
        try:
            if not is_proxy_running():
                print("[M3U Export] Starting proxy...")
                if not run_proxy_in_background():
                    on_failed()
                    return
            self._poll_proxy_ready_for_m3u(on_ready, on_failed, attempts_left)
        except Exception as e:
            print(
                "[M3U Export][check_and_start_proxy] Proxy error: %s" %
                str(e))
            on_failed()

    def _poll_proxy_ready_for_m3u(self, on_ready, on_failed, attempts_left):
        if is_proxy_ready():
            on_ready()
            return
        if attempts_left <= 1:
            on_failed()
            return
        reactor.callLater(
            1,
            self._poll_proxy_ready_for_m3u,
            on_ready,
            on_failed,
            attempts_left - 1)

    def get_countries_from_proxy(self):
        """Get country list from the proxy"""
        try:
            response = getUrl(PROXY_COUNTRIES_URL, timeout=10)
            if response:
                return loads(response)

        except Exception as e:
            print("[M3U Export] Countries error: %s" % str(e))

        return []

    def manage_epg_source(self):
        # Just call the static function from vUtils
        # This will generate EPG from all existing bouquets
        # return generate_epg_files()
        return update_epg_sources()

    def setInfo(self):
        try:
            sel = self['config'].getCurrent()[2]
            if sel:
                self['description'].setText(str(sel))
            else:
                self['description'].setText(_('SELECT YOUR CHOICE'))
            return
        except Exception as e:
            print('error as:', e)
            trace_error()

    def changedEntry(self):
        # The theme changed some other way than LEFT / RIGHT (OK with a
        # list of choices, on some images): Classic's Background row
        # comes or goes now too.
        if getattr(self, "_built_theme", None) is not None and \
                cfg.theme.value != self._built_theme:
            self.createSetup()
        for x in self.onChangedEntry:
            x()
        self['green'].instance.setText(
            _('Save') if self._settings_changed() else '- - - -')

    def getCurrentEntry(self):
        return self["config"].getCurrent()[0]

    def showhide(self):
        pass

    def getCurrentValue(self):
        return str(self["config"].getCurrent()[1].getText())

    def createSummary(self):
        from Screens.Setup import SetupSummary
        return SetupSummary

    def keyLeft(self):
        ConfigListScreen.keyLeft(self)
        self.createSetup()
        self.showhide()

    def keyRight(self):
        ConfigListScreen.keyRight(self)
        self.createSetup()
        self.showhide()

    def keyDown(self):
        self['config'].instance.moveSelection(self['config'].instance.moveDown)
        self.createSetup()
        self.showhide()

    def keyUp(self):
        self['config'].instance.moveSelection(self['config'].instance.moveUp)
        self.createSetup()
        self.showhide()

    def _reorganize_bouquets_position(self):
        """Reorganize all Vavoo bouquets to the new position"""
        if reorganize_all_bouquets_position(cfg.list_position.value):
            self.session.open(
                MessageBox,
                _("Bouquets reorganized successfully!"),
                MessageBox.TYPE_INFO,
                timeout=3)

    def schedule_epg_update(self):
        """Auto-enable Vavoo's EPG source(s) in EPGImport's own settings.

        EPGImport's own scheduler (its "wakeup"/"repeat import" settings,
        configured directly in EPGImport's own screen) is what actually
        runs periodic imports - this doesn't add a second, competing
        schedule. It just removes the friction of having to separately
        go enable the Vavoo source there yourself: an earlier version
        tried to do this by opening EPGIMPORT_CONF in text mode and
        appending a "sources=..." line to it, but that file is actually
        a binary serialized blob (not the plain-text format this
        assumed), so every append corrupted EPGImport's own config.
        ensure_vavoo_epg_sources_enabled() (vUtils.py) uses EPGImport's
        own save API instead, so it's safe to call here.
        """
        try:
            # Checks "Enable Vavoo EPG" itself; there is no separate
            # option for this any more (it used to hide behind a
            # second toggle named "Auto-update EPG", which sounded
            # like it scheduled something - it never did).
            ensure_vavoo_epg_sources_enabled()

        except Exception as e:
            print("[Vavoo] Error scheduling EPG update:", str(e))

    def save(self):
        if self._settings_changed():
            for entry in self._all_entries():
                entry.save()

            # Tracks whether this save() has already restarted the
            # proxy, so the "Manage EPG source" block further down
            # doesn't start it a second time.
            restart_handled = False

            if self.old_catalog_source != cfg.catalog_source.value:
                self.old_catalog_source = cfg.catalog_source.value
                # initialize_proxy() only reads catalog_source once, at
                # startup - restart the proxy so the new choice actually
                # takes effect. Stop + wait for the port + start all
                # happen off the GUI thread; calling shutdown_proxy()
                # and run_proxy_in_background() back to back right
                # here used to find the old server still listening and
                # skip the start altogether.
                restart_proxy_in_background()
                reactor.callLater(1, self._check_proxy_started)
                restart_handled = True

            # Sync the anonymous-stats opt-out file with this toggle -
            # is_stats_enabled() (vavoo_stats.py) checks for this file's
            # existence, but nothing ever created/removed it since there
            # was no actual UI control for it before this config entry.
            try:
                if cfg.stats_enabled.value:
                    if isfile(STATS_DISABLE_FILE):
                        remove(STATS_DISABLE_FILE)
                else:
                    if not isfile(STATS_DISABLE_FILE):
                        with open(STATS_DISABLE_FILE, 'w') as f:
                            f.write('1')
                    # Stop the running heartbeat immediately instead of
                    # letting it keep firing every 5 minutes until the
                    # plugin is next restarted.
                    stop_heartbeat()
            except Exception as e:
                print("[Config] Error syncing stats opt-out: " + str(e))

            # Manage EPG source - skipped if a restart already happened
            # above in this same save() (catalog_source changing).
            if cfg.epg_enabled.value and not is_proxy_running() and not restart_handled:
                run_proxy_in_background()
                # No sleep here – the proxy will become ready asynchronously

            # With the EPG on, make sure its source(s) are enabled in
            # EPGImport too.
            if cfg.epg_enabled.value:
                self.schedule_epg_update()

            # Apply any change to the scheduled bouquet auto-update timer
            # live, instead of requiring a reboot for it to take effect.
            from .plugin import check_configuring   # (plugin.py imports this module)
            check_configuring()

            if self.old_list_position != cfg.list_position.value:
                self._reorganize_bouquets_position()
                self.old_list_position = cfg.list_position.value

            configfile.save()

            try:
                config.loadFromFile(configfile.CONFIG_FILE)
            except Exception as e:
                print("Config reload error (safe mode): " + str(e))
                self._safe_config_reload()

            back_changed = self.old_back != cfg.back.value
            bakk = str(cfg.back.getValue()) + '.png'
            add_skin_back(bakk)

            look_changed = self.old_look != self._look_settings()
            message = _("Configuration saved successfully!")
            if look_changed:
                # Like the background below: the screens already open
                # were built with the old settings.
                message += "\n\n" + \
                    _("Exit and reopen the plugin to see the new look.")
                self.old_look = self._look_settings()
                back_changed = False
            if back_changed:
                # apply_selected_background() makes freshly-opened screens
                # point at the actual selected file, avoiding Enigma2's
                # pixmap cache entirely - but the MainVavoo screen
                # currently open behind this config screen was already
                # loaded before this change, so it still needs to be
                # closed and reopened once to pick up the new skin text.
                message += "\n\n" + \
                    _("Exit and reopen the plugin to see the new background.")
                self.old_back = cfg.back.value

            self.session.open(
                MessageBox,
                message,
                MessageBox.TYPE_INFO,
                timeout=5
            )

            self.close()

    def _check_proxy_started(self, attempts=0):
        """Callback to verify proxy has started (non‑blocking).

        Capped by cfg.proxy_startup_timeout instead of retrying every 2s
        forever - previously, if the proxy never came up (missing
        binary, crash-loop, blocked network), this rescheduled itself
        indefinitely for the life of the Enigma2 process, keeping this
        (by then already-closed, since save() closes the screen right
        after scheduling this) vavoo_config instance alive forever."""
        try:
            timeout_secs = int(cfg.proxy_startup_timeout.value)
        except (TypeError, ValueError):
            timeout_secs = 30
        max_attempts = max(1, timeout_secs // 2)
        if not is_proxy_running():
            if attempts >= max_attempts:
                print(
                    "[Config] Proxy still not ready after {}s, giving up".format(
                        timeout_secs))
                return
            print("[Config] Proxy not yet ready, will check later")
            reactor.callLater(
                2, lambda: self._check_proxy_started(attempts + 1))
        else:
            print("[Config] Proxy is ready")

    def _safe_config_reload(self):
        """Safe configuration reload"""
        try:
            if not hasattr(config.plugins, 'vavoo'):
                config.plugins.vavoo = ConfigSubsection()
                print("Recreated vavoo config section")

            config.loadFromFile(configfile.CONFIG_FILE)
        except Exception as e:
            print("Safe config reload failed: " + str(e))

    def extnok(self, answer=None):
        if answer is None:
            if self._settings_changed():
                self.session.openWithCallback(
                    self.extnok, MessageBox, _("Really close without saving settings?"))
            else:
                self.close()
        elif answer:
            for entry in self._all_entries():
                entry.cancel()
            self.close()
        else:
            return


# ---------------------------------------------------------------------
# Settings → Backup / Restore, Licences, About
# ---------------------------------------------------------------------
# The plugin's settings a backup carries: the ones the user chooses -
# not the action rows, not parental control (as in the app, a backup
# does not carry the PIN out nor a restore remove the one set here).
BACKUP_SETTINGS = (
    "theme", "text_size", "show_counts", "clock_format", "back",
    "catalog_source", "playlist_key", "proxy_startup_timeout",
    "epg_enabled", "preview_window", "start_last", "list_epg",
    "group_sources", "logos", "subcategories", "autobouquetupdate",
    "timetype", "updateinterval", "fixedtime", "services",
    "list_position", "stmain", "stats_enabled", "debug_logging",
    "timeshift", "record_path",
)


def plugin_settings():
    """{name: saved text} of BACKUP_SETTINGS."""
    out = {}
    for name in BACKUP_SETTINGS:
        element = getattr(cfg, name, None)
        if element is None:
            continue
        try:
            out[name] = to_text(element.tostring(element.value))
        except Exception as e:
            debug("Setting {} not saved in the backup: {}".format(name, e))
    return out


def apply_settings(settings):
    """A backup's settings into Enigma2's settings (and saved)."""
    for name, text in settings.items():
        if name not in BACKUP_SETTINGS:
            continue
        element = getattr(cfg, name, None)
        if element is None:
            continue
        try:
            element.saved_value = to_string(text)
            element.load()
            element.save()
        except Exception as e:
            debug("Setting {} not restored: {}".format(name, e))
    try:
        configfile.save()
    except Exception as e:
        print("[vavoo] Settings not saved: {}".format(e))


LICENCES_FILE = "/tmp/vavoo_licences.txt"


def licences_text():
    """The plugin's licence, then the fonts' (fonts/*-OFL.txt), each
    under a header (the app's Licences screen)."""
    parts = [
        u"Vavoo Stream Live V.{} - {}".format(to_text(__version__),
                                             to_text(__author__)),
        u"License: CC BY-NC-SA 4.0 - "
        u"https://creativecommons.org/licenses/by-nc-sa/4.0/",
        to_text(_("Non-commercial use only, with attribution; changes "
                  "shared under the same licence.")),
        u""]
    fonts_dir = join(PLUGIN_PATH, "fonts")
    try:
        names = sorted(n for n in listdir(fonts_dir) if n.endswith("-OFL.txt"))
    except Exception:
        names = []
    for name in names:
        try:
            with codecs.open(join(fonts_dir, name), "r", encoding="utf-8") as f:
                text = f.read()
        except Exception as e:
            text = u"({})".format(to_text(e))
        parts.append(u"━" * 10 + u"  {}  ".format(name[:-8]) +
                     u"━" * 10)
        parts.append(text.rstrip())
        parts.append(u"")
    return u"\n".join(parts)


def show_licences(session):
    try:
        with codecs.open(LICENCES_FILE, "w", encoding="utf-8") as f:
            f.write(licences_text())
    except Exception as e:
        print("[vavoo] Licences not written: {}".format(e))
    session.open(VavooLogViewer, title=_("Licences"),
                 file_path=LICENCES_FILE, tail_lines=100000)


def show_about(session):
    """Display plugin information"""
    message_parts = []
    message_parts.append(_("Vavoo Stream Live Plugin"))
    message_parts.append("=" * 40)

    message_parts.append(_("Version: ") + str(__version__))
    message_parts.append(_("Author: ") + str(__author__))
    message_parts.append(_("License: ") + str(__license__))
    message_parts.append("")

    message_parts.append(_("Technical Features:"))
    message_parts.append(_("- HTTP Live Streaming"))
    message_parts.append(_("- TS/M3U8 formats"))
    message_parts.append(_("- Service references: 4097, 5001, 5002"))
    message_parts.append(_("- Automatic bouquet generation"))
    message_parts.append(
        _("- Automatic Epg generation with Service Reference"))
    message_parts.append(_("- Integrated proxy system"))
    message_parts.append(_("- Auto token refresh every 9 minutes"))
    message_parts.append("")

    message_parts.append(_("Credits:"))
    message_parts.append(_("- Graphics: @oktus"))
    message_parts.append(
        _("- Technical support: Qu4k3, @KiddaC, @giorbak"))
    message_parts.append(
        _("- Community: Linuxsat-support.com, Corvoboys.org Forum"))
    message_parts.append("")

    message_parts.append(_("Important Notes:"))
    message_parts.append(_("- Free content only"))
    message_parts.append(_("- Streams from public sources"))
    message_parts.append(_("- No direct server hosting"))
    message_parts.append("")

    message_parts.append(_("License: CC BY-NC-SA 4.0"))
    message_parts.append(_("- Redistribution must maintain attribution"))
    message_parts.append(_("- Commercial use is strictly prohibited"))

    info_text = "\n".join(message_parts)

    aboutbox = session.open(
        MessageBox,
        info_text,
        MessageBox.TYPE_INFO
    )
    try:
        aboutbox.setTitle(_('Vavoo Stream Live - Information'))
    except Exception:
        pass


def open_settings(session, on_closed=None):
    """The plugin's settings (MENU → Settings everywhere) - after the
    PIN when Parental Control locks them."""
    def _open():
        if on_closed:
            session.openWithCallback(on_closed, vavoo_config)
        else:
            session.open(vavoo_config)
    if vavoo_store.needs_pin_for_settings():
        ask_pin(session, None, _open)
    else:
        _open()
