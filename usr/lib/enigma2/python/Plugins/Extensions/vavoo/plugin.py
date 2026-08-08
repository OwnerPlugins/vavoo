#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import codecs
import ssl
import time
import threading
from difflib import SequenceMatcher
from os import listdir, unlink, remove, system as os_system
from os.path import exists as file_exists, join, isfile, getsize
from re import compile, DOTALL, search
from json import loads
from sys import version_info
from enigma import eDVBDB
import xml.etree.ElementTree as ET
import datetime
from twisted.internet import reactor
import select

try:
    import requests
except Exception:
    requests = None

try:
    from urllib.request import Request as UrlRequest, urlopen
except ImportError:
    from urllib2 import Request as UrlRequest, urlopen
try:
    from requests.adapters import HTTPAdapter
except Exception:
    HTTPAdapter = None

try:
    from urllib3.util.retry import Retry
except Exception:
    try:
        from requests.packages.urllib3.util.retry import Retry
    except Exception:
        Retry = None

try:
    from Components.AVSwitch import AVSwitch
except ImportError:
    from Components.AVSwitch import eAVControl as AVSwitch

from Components.ActionMap import ActionMap
from Components.ConfigList import ConfigListScreen
from Components.Label import Label
from Components.ScrollLabel import ScrollLabel
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryPixmapAlphaTest, MultiContentEntryText
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from Components.ServiceEventTracker import ServiceEventTracker, InfoBarBase
from Components.config import (
    ConfigSelection,
    getConfigListEntry,
    ConfigSelectionNumber,
    ConfigClock,
    ConfigText,
    configfile,
    config,
    ConfigYesNo,
    ConfigEnableDisable,
    ConfigSubsection,
    NoSave
)
from enigma import (
    RT_HALIGN_LEFT,
    RT_VALIGN_CENTER,
    eListboxPythonMultiContent,
    ePicLoad,
    eServiceReference,
    eTimer,
    gFont,
    getDesktop,
    iPlayableService,
    loadPNG,
)

from Screens.InfoBarGenerics import (
    InfoBarSubtitleSupport,
    InfoBarMenu,
    InfoBarSeek,
    InfoBarAudioSelection,
    InfoBarNotifications,
)
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Tools.Directories import SCOPE_PLUGINS, SCOPE_CONFIG, resolveFilename
from Tools.NumericalTextInput import NumericalTextInput
from Plugins.Plugin import PluginDescriptor

from .vavoo_stats import (
    record_anonymous_startup, is_stats_enabled, start_heartbeat,
    stop_heartbeat, STATS_DISABLE_FILE
)
from .vavoo_proxy import proxy, run_proxy_in_background, shutdown_proxy
from . import (
    _, __author__, __version__, __license__, export_lock, PORT,
    PLUGIN_ROOT, PROXY_HOST, PROXY_BASE_URL, PROXY_STATUS_URL,
    PROXY_COUNTRIES_URL, PROXY_REFRESH_URL, PROXY_SHUTDOWN_URL,
    FLAG_CACHE_DIR, PRIMARY_BASE_URL, FALLBACK_BASE_URL, EPGIMPORT_CONF
)
from . import PY2, PY3, vUtils
from .bouquet_manager import (
    convert_bouquet,
    _update_favorite_file,
    reorganize_all_bouquets_position,
    remove_bouquets_by_name,
    export_bouquet_async,
    is_bouquet_exported,
    remove_favorite_entry
)
from .vUtils import (
    debug,
    make_print,
    update_epg_sources,
    get_epg_matcher,
    get_proxy_status,
    cleanup_old_temp_files,
    check_remote_installer_version,
    decodeHtml,
    download_flag_online,
    ensure_str,
    fix_cache_format,
    getUrl,
    get_country_code,
    initialize_cache_with_local_flags,
    is_proxy_ready,
    is_proxy_running,
    is_remote_version_newer,
    returnIMDB,
    remove_parentheses,
    ReloadBouquets,
    trace_error
)
from .Console import Console
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
    from .notification_system import init_notification_system, quick_notify
    NOTIFICATION_AVAILABLE = True
except ImportError as e:
    debug("Notification system not available: {}".format(e))
    NOTIFICATION_AVAILABLE = False

    def quick_notify(*args, **kwargs):
        pass

print = make_print("PLUGIN")


try:
    # Python 3
    from urllib.parse import quote as _url_quote, unquote as _url_unquote
except ImportError:
    # Python 2
    from urllib import quote as _url_quote, unquote as _url_unquote

try:
    text_type = unicode
    binary_type = str
except NameError:
    text_type = str
    binary_type = bytes

if version_info >= (2, 7, 9):
    try:
        ssl_context = ssl._create_unverified_context()
    except BaseException:
        ssl_context = None


def to_text(value, encoding="utf-8", errors="ignore"):
    """Return a text string under both Python 2 and Python 3."""
    if value is None:
        return text_type()

    if isinstance(value, text_type):
        return value

    if isinstance(value, binary_type):
        try:
            return value.decode(encoding, errors)
        except Exception:
            return value.decode("latin-1", "ignore")

    try:
        converted = str(value)
    except Exception:
        try:
            return text_type(value)
        except Exception:
            return text_type()

    if isinstance(converted, text_type):
        return converted

    try:
        return converted.decode(encoding, errors)
    except Exception:
        return converted.decode("latin-1", "ignore")


def url_quote(value):
    """Quote URL fragments in a Python 2/3 safe way."""
    if PY2:
        value = to_text(value).encode("utf-8")
    else:
        value = to_text(value)

    return _url_quote(value)


def url_unquote(value):
    """Unquote URL fragments and normalize text in a Python 2/3 safe way."""
    if value is None:
        return text_type()

    if PY2 and isinstance(value, text_type):
        value = value.encode("utf-8")
    elif PY3 and isinstance(value, binary_type):
        value = value.decode("utf-8", "ignore")

    decoded = _url_unquote(value)

    if PY2 and isinstance(decoded, binary_type):
        try:
            return decoded.decode("utf-8")
        except Exception:
            return decoded.decode("latin-1", "ignore")

    return decoded


try:
    aspect_manager = vUtils.AspectManager()
    current_aspect = aspect_manager.get_current_aspect()
except BaseException as e:
    debug("AspectManager init failed: {}".format(e))

try:
    from Components.UsageConfig import defaultMoviePath
    downloadfree = defaultMoviePath()
except BaseException:
    if file_exists("/usr/bin/apt-get"):
        downloadfree = ('/media/hdd/movie/')


def get_enigma2_path():
    barry_active = '/media/ba/active/etc/enigma2'
    if file_exists(barry_active):
        return barry_active.rstrip('/')

    possible_paths = [
        '/autofs/sda1/etc/enigma2',
        '/autofs/sda2/etc/enigma2',
        '/etc/enigma2'
    ]
    for path in possible_paths:
        if file_exists(path):
            return path.rstrip('/')
    return '/etc/enigma2'


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


# set plugin
global HALIGN, BackPath, FNTPath
global search_ok, screen_width
global proxy_instance, proxy_thread

title_plug = 'Vavoo'
desc_plugin = ('..:: Vavoo by Lululla & Qu4k3 v.%s ::..' % __version__)
PLUGIN_PATH = PLUGIN_ROOT
PLUGLOGO = join(PLUGIN_PATH, 'plugin.png')
ENIGMA_PATH = get_enigma2_path()
CONFIG_FILE = resolveFilename(SCOPE_CONFIG, "settings")
regexs = '<a[^>]*href="([^"]+)"[^>]*><img[^>]*src="([^"]+)"[^>]*>'

_session = None
# Guards autostart() itself against re-scheduling delayed_boot_tasks() on
# repeat calls - kept separate from _session, which delayed_boot_tasks()
# uses to detect whether the user has actually opened a plugin screen.
_autostart_scheduled = False
auto_start_timer = None
now = None
proxy_instance = None
proxy_thread = None
search_ok = False
tmlast = None

# Per-country parsed EPG document + channel->programme index, shared
# across Playstream2 instances (module-level, not per-instance) so
# switching channels or reopening the player doesn't re-fetch/re-parse/
# re-index the same country's EPG document within the TTL window - see
# Playstream2.get_current_epg().
# country_code -> (timestamp, root, channel_index, display_name_index)
_epg_xml_cache = {}
_epg_result_cache = {}   # "epg_<name>_<country>" -> (timestamp, result_str)

# Safety-net caps: entries here are only ever added, never removed on
# their own (the 5-minute figure elsewhere is a reuse TTL, not an
# eviction one) - unlike vUtils.py's persistent EPG matcher cache (which
# already has its own size cap), these two are plain in-memory dicts
# that grow for the life of the process, one entry per unique
# channel+country (_epg_result_cache) or country (_epg_xml_cache) ever
# viewed. _epg_xml_cache is naturally small (bounded by distinct
# countries actually browsed), but capped too for consistency/safety.
_EPG_RESULT_CACHE_MAX = 500
_EPG_XML_CACHE_MAX = 50


def _cache_epg_result(cache_key, result):
    _epg_result_cache[cache_key] = (time.time(), result)
    if len(_epg_result_cache) > _EPG_RESULT_CACHE_MAX:
        oldest = sorted(
            _epg_result_cache, key=lambda k: _epg_result_cache[k][0]
        )[:len(_epg_result_cache) - _EPG_RESULT_CACHE_MAX]
        for k in oldest:
            del _epg_result_cache[k]


def _cache_epg_xml(country_code, root, channel_index, display_name_index):
    _epg_xml_cache[country_code] = (
        time.time(), root, channel_index, display_name_index)
    if len(_epg_xml_cache) > _EPG_XML_CACHE_MAX:
        oldest = sorted(
            _epg_xml_cache, key=lambda k: _epg_xml_cache[k][0]
        )[:len(_epg_xml_cache) - _EPG_XML_CACHE_MAX]
        for k in oldest:
            del _epg_xml_cache[k]


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

    _update_thread = threading.Thread(target=_worker)
    _update_thread.setDaemon(True)
    _update_thread.start()


# screen
HALIGN = RT_HALIGN_LEFT
screen_real = getDesktop(0).size()
screen_width = screen_real.width()
BackfPath = join(PLUGIN_PATH, "skin")


if screen_width == 2560:
    OVERLAY_WIDTH = 2560
    OVERLAY_HEIGHT_TOP = 70
    OVERLAY_HEIGHT_EPG = 300
    FONT_SIZE_TOP = 42
    FONT_SIZE_EPG = 36
    OVERLAY_Y_EPG = 80
    BackPath = join(BackfPath, 'images_new')
    skin_path = join(BackfPath, 'wqhd')
elif screen_width >= 1920:
    OVERLAY_WIDTH = 1920
    OVERLAY_HEIGHT_TOP = 60
    OVERLAY_HEIGHT_EPG = 250
    FONT_SIZE_TOP = 36
    FONT_SIZE_EPG = 32
    OVERLAY_Y_EPG = 70
    BackPath = join(BackfPath, 'images_new')
    skin_path = join(BackfPath, 'fhd')
else:
    OVERLAY_WIDTH = 1280
    OVERLAY_HEIGHT_TOP = 50
    OVERLAY_HEIGHT_EPG = 150
    FONT_SIZE_TOP = 28
    FONT_SIZE_EPG = 24
    OVERLAY_Y_EPG = 55
    BackPath = join(BackfPath, 'images')
    skin_path = join(BackfPath, 'hd')

print('folder back: ', BackPath)


# system
stripurl = 'aHR0cHM6Ly92YXZvby50by9jaGFubmVscw=='
# If vavoo.to returns HTTP 451 (Unavailable For Legal Reasons),
# fall back to this mirror.
HTTP_451_SENTINEL = "__HTTP451__"
keyurl = 'aHR0cDovL3BhdGJ1d2ViLmNvbS92YXZvby92YXZvb2tleQ=='
myser = [(PRIMARY_BASE_URL, "vavoo"), ("https://oha.tooha-tv", "oha"),
         (FALLBACK_BASE_URL, "kool"), ("https://huhu.to", "huhu")]
modemovie = [("4097", "4097")]
if file_exists("/usr/bin/gstplayer"):
    modemovie.append(("5001", "5001"))
if file_exists("/usr/bin/exteplayer3"):
    modemovie.append(("5002", "5002"))
if file_exists('/var/lib/dpkg/info'):
    modemovie.append(("8193", "8193"))


BakP = []
try:
    if file_exists(BackPath):
        for back_name in listdir(BackPath):
            back_name_path = join(BackPath, back_name)
            if back_name.endswith(".png"):
                if back_name.startswith("default"):
                    continue
                back_name = back_name[:-4]
                BakP.append((back_name, back_name))
except Exception as e:
    print(e)

print('final folder back: ', BackPath)


# Helper function for string conversion
def to_string(text):
    """Convert any input to proper string format for Enigma2 widgets"""
    if text is None:
        return ""

    # If it's already a unicode string (Python 2) or str (Python 3)
    if isinstance(text, text_type):
        return text.encode('utf-8', 'ignore') if PY2 else text

    # If it's bytes/binary
    if isinstance(text, binary_type):
        return text.decode('utf-8', 'ignore') if PY3 else text

    # For other types, convert to string
    return str(text)


# config section
# --- Live search input field integrated in plugin config ---
class ConfigSearchText(ConfigText):
    def __init__(self, default=""):
        ConfigText.__init__(self, default=default)


config.plugins.vavoo = ConfigSubsection()
cfg = config.plugins.vavoo
cfg.proxy_enabled = ConfigEnableDisable(default=True)
cfg.autobouquetupdate = ConfigEnableDisable(default=False)
cfg.genm3u = NoSave(ConfigYesNo(default=False))
cfg.server = ConfigSelection(default=PRIMARY_BASE_URL, choices=myser)
cfg.services = ConfigSelection(default='4097', choices=modemovie)
cfg.epg_enabled = ConfigEnableDisable(default=False)
cfg.epg_auto_update = ConfigEnableDisable(default=False)
cfg.similarity_threshold = ConfigSelectionNumber(
    default=75, min=50, max=100, stepwidth=5)
cfg.epg_update_interval = ConfigSelectionNumber(
    default=6, min=1, max=24, stepwidth=1)
cfg.timerupdate = ConfigSelectionNumber(default=5, min=1, max=60, stepwidth=1)
cfg.timetype = ConfigSelection(
    default="interval", choices=[
        ("interval", _("interval")), ("fixed time", _("fixed time"))])
cfg.updateinterval = ConfigSelectionNumber(
    default=5, min=5, max=3600, stepwidth=5)
cfg.fixedtime = ConfigClock(default=46800)
cfg.last_update = ConfigText(default="Never")
cfg.stmain = ConfigYesNo(default=True)
cfg.stats_enabled = ConfigYesNo(default=True)
cfg.debug_logging = ConfigYesNo(default=False)
cfg.debug_logging.addNotifier(
    lambda cfgelement: vUtils.set_debug_enabled(cfgelement.value),
    initial_call=True
)
# cfg.ipv6 = ConfigEnableDisable(default=False)
cfg.back = ConfigSelection(default='oktus', choices=BakP)
"""
cfg.default_view = ConfigSelection(
    default="countries",
    choices=[("countries", _("Countries")), ("categories", _("Categories"))]
)
"""
cfg.default_view = ConfigSelection(
    default="countries",
    choices=[("countries", _("Countries"))]
)
cfg.list_position = ConfigSelection(
    default="bottom",
    choices=[("bottom", _("Bottom")), ("top", _("Top"))]
)
cfg.search_text = ConfigSearchText(default="")
cfg.proxy_startup_timeout = ConfigSelectionNumber(
    default=120, min=15, max=300, stepwidth=5)

# MainVavoo's proxy_monitor_timer/proxy_watchdog_timer are created and
# restarted from three different places (initial open, returning from
# config, returning from Playstream2) - use one shared constant per
# timer everywhere instead of separate literals, which had drifted out
# of sync with each other (and with their own "every N seconds"
# comments) at two of those six call sites.
PROXY_MONITOR_INTERVAL_MS = 10000
PROXY_WATCHDOG_INTERVAL_MS = 60000


def normalize_language_code(language):
    """Normalize Enigma2 language identifiers to a comparable short code."""
    if not language:
        return "en"

    language = to_text(language).strip().lower()
    if "_" in language:
        language = language.split("_", 1)[0]
    elif "-" in language:
        language = language.split("-", 1)[0]

    return language or "en"


try:
    from Components.config import config
    lng = normalize_language_code(config.osd.language.value)
except BaseException:
    lng = 'en'
    pass


# menulist
class m2list(MenuList):
    def __init__(self, items):
        super(m2list, self).__init__(items, False, eListboxPythonMultiContent)
        if screen_width == 2560:
            item_height = 60
            text_font_size = 38
        elif screen_width == 1920:
            item_height = 50
            text_font_size = 34
        else:
            item_height = 50
            text_font_size = 22
        self.l.setItemHeight(item_height)
        self.l.setFont(0, gFont('Regular', text_font_size))

    def buildEntry(self, entry):
        """Build list entry - entry should be [ (name, link), icon, text ]"""
        return entry


def show_list(name, link, is_category=False, is_channel=False):
    """Build a MultiContent entry with icon and text."""

    safe_name = to_string(name)
    safe_link = to_string(link)

    res = [(safe_name, safe_link)]

    # Default icon
    default_icon = join(PLUGIN_PATH, 'skin/pics/vavoo_ico.png')
    icon_path = default_icon

    if not is_channel and not is_category:
        country_name = safe_name.split('➾')[0].split(
            '⟾')[0].split('→')[0].split('->')[0].strip()
        if country_name:
            try:
                country_code = get_country_code(country_name)
                if country_code:
                    cache_file = "%s/%s.png" % (FLAG_CACHE_DIR,
                                                country_code.lower())

                    # Use cache if exists and valid
                    if file_exists(cache_file):
                        try:
                            if getsize(cache_file) > 100:
                                icon_path = cache_file
                            else:
                                unlink(cache_file)
                        except Exception as e:
                            debug("Flag cache check failed for {}: {}".format(
                                cache_file, e))

                    # If not in cache, use default icon (don't download here - use preloading)
                    # Download will happen in
                    # preload_flags_for_visible_countries()

            except Exception as e:
                debug("Flag icon resolution failed for {}: {}".format(
                    country_name, e))

    if screen_width >= 2560:
        icon_size = (60, 40)
        icon_pos = (10, 10)
        text_size = (750, 60)
        text_pos = (icon_size[0] + 20, 0)
    elif screen_width >= 1920:
        icon_size = (60, 40)
        icon_pos = (10, 5)
        text_size = (540, 50)
        text_pos = (icon_size[0] + 20, 0)
    else:
        icon_size = (60, 40)
        icon_pos = (10, 5)
        text_size = (380, 50)
        text_pos = (icon_size[0] + 20, 0)

    # Load PNG
    try:
        png_data = loadPNG(icon_path)
    except Exception:
        try:
            png_data = loadPNG(default_icon)
        except Exception:
            png_data = None

    if png_data:
        res.append(MultiContentEntryPixmapAlphaTest(
            pos=icon_pos,
            size=icon_size,
            png=png_data
        ))

    res.append(MultiContentEntryText(
        pos=text_pos,
        size=text_size,
        font=0,
        text=safe_name,
        flags=HALIGN | RT_VALIGN_CENTER
    ))

    return list(res)


class vavoo_config(Screen, ConfigListScreen):
    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session
        skin = join(skin_path, 'vavoo_config.xml')
        if isfile('/var/lib/dpkg/status'):
            skin = skin.replace('.xml', '_cvs.xml')
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = apply_selected_background(f.read())
        self.setup_title = ('Vavoo Config')

        self.old_proxy_enabled = cfg.proxy_enabled.value
        self.old_back = cfg.back.value

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
        self.update_status()
        ConfigListScreen.__init__(
            self,
            self.list,
            session=self.session,
            on_change=self.changedEntry)
        self.createSetup()
        self.showhide()
        self.onLayoutFinish.append(self.layoutFinished)

    def update_status(self):
        if cfg.autobouquetupdate:
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
        self.list.append(
            getConfigListEntry(
                _("Generate .m3u files (Ok for Exec)"),
                cfg.genm3u,
                _("Generate .m3u files and save to device %s.") %
                downloadfree))

        self.list.append(
            getConfigListEntry(
                _("Proxy Enabled"),
                cfg.proxy_enabled,
                _("Enable or disable proxy.")
            )
        )

        self.list.append(
            getConfigListEntry(
                _("Default View"),
                cfg.default_view,
                _("Default view when opening the plugin")))

        self.list.append(getConfigListEntry(
            _("Proxy startup timeout (seconds)"),
            cfg.proxy_startup_timeout,
            _("Increase if proxy takes long due to VPN or slow connection.")))

        help_text = _("Server for player.") + "\n" + \
            _("Now %s") % cfg.server.value

        self.list.append(
            getConfigListEntry(
                _("Server for Player Used"),
                cfg.server,
                help_text
            )
        )
        self.list.append(getConfigListEntry(
            _("Enable Vavoo EPG"),
            cfg.epg_enabled,
            _("Create EPG source for EPGImport with Vavoo program data")
        ))

        if cfg.epg_enabled.value:
            self.list.append(getConfigListEntry(
                _("Auto-update EPG"),
                cfg.epg_auto_update,
                _("Automatically trigger EPG update after source creation")
            ))
            self.list.append(
                getConfigListEntry(
                    _("EPG Similarity Threshold (%)"),
                    cfg.similarity_threshold,
                    _("Minimum similarity for matching channels (higher = stricter).")))
            if cfg.epg_auto_update.value:
                self.list.append(
                    getConfigListEntry(
                        _("Update interval (hours)"),
                        cfg.epg_update_interval,
                        _("How often to auto-update the EPG (requires EPGImport scheduler)")))

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

        help_line1 = _("Refresh stream every X minutes (1-15)")
        help_line2 = _("Recommended: 5-8 minutes")
        help_line3 = _("Lower = less interruption but more refreshes")
        help_text = help_line1 + "\n" + help_line2 + "\n" + help_line3
        self.list.append(
            getConfigListEntry(
                _("Refresh stream (minutes):"),
                cfg.timerupdate,
                help_text
            )
        )
        self.list.append(
            getConfigListEntry(
                _("Select Background"),
                cfg.back,
                _("Configure Main Background Image.")))

        self.list.append(
            getConfigListEntry(
                _("Scheduled List:"),
                cfg.autobouquetupdate,
                _("Active Automatic Bouquet Update")))
        if cfg.autobouquetupdate.value is True:
            self.list.append(
                getConfigListEntry(
                    indent + _("Schedule type:"),
                    cfg.timetype,
                    _("At an interval hours or fixed time")))
            if cfg.timetype.value == "interval":
                self.list.append(
                    getConfigListEntry(
                        2 * indent + _("Update interval (minutes):"),
                        cfg.updateinterval,
                        _("Configure interval minutes from now")))
            if cfg.timetype.value == "fixed time":
                self.list.append(
                    getConfigListEntry(
                        2 * indent + _("Time to start update:"),
                        cfg.fixedtime,
                        _("Configure at a fixed time")))

        self.list.append(
            getConfigListEntry(
                _('Link in Main Menu'),
                cfg.stmain,
                _("Link in Main Menu")))
        self.list.append(getConfigListEntry(_("Send Anonymous Statistics"), cfg.stats_enabled, _(
            "Anonymous startup/heartbeat ping only (session id, version, timestamp - no personal data). Disable to opt out.")))
        self.list.append(getConfigListEntry(_("Debug logging"), cfg.debug_logging, _(
            "Show verbose DEBUG-level messages in vavoo.log (UI lifecycle, per-request detail). Takes effect immediately - leave off unless troubleshooting.")))
        self["config"].list = self.list
        self["config"].l.setList(self.list)
        self.setInfo()

    def gnm3u(self):
        sel = self["config"].getCurrent()[1]
        if sel and sel == cfg.genm3u:
            self.session.openWithCallback(
                self.generate_m3u,
                MessageBox,
                _("Generate .m3u files and save to device %s?") %
                downloadfree,
                MessageBox.TYPE_YESNO,
                timeout=10,
                default=True)

    def generate_m3u(self, result):
        if result:
            # 1. Check if the proxy is active
            if not self.check_and_start_proxy():
                self.session.open(
                    MessageBox,
                    _("Proxy not active. Unable to generate M3U file."),
                    MessageBox.TYPE_ERROR,
                    timeout=5
                )
                cfg.genm3u.setValue(0)
                cfg.genm3u.save()
                return

            # 2. Get country list from proxy
            try:
                countries = self.get_countries_from_proxy()
                if not countries:
                    raise Exception("No countries available")

                # 3. ASK MODE: single country or all?
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

                cfg.genm3u.setValue(0)
                cfg.genm3u.save()

    def on_m3u_mode_selected(self, result):
        """Callback for M3U mode selection"""
        if result is None or result[1] == "cancel":
            cfg.genm3u.setValue(0)
            cfg.genm3u.save()
            return

        mode = result[1]

        try:
            countries = self.get_countries_from_proxy()
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

            cfg.genm3u.setValue(0)
            cfg.genm3u.save()

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
            cfg.genm3u.setValue(0)
            cfg.genm3u.save()
            return

        selected_country = result[1]

        # Get channels for the selected country
        channels = self.get_channels_for_country(selected_country)

        if not channels or len(channels) == 0:
            self.session.open(
                MessageBox,
                _("No channels found for: %s") % selected_country,
                MessageBox.TYPE_WARNING,
                timeout=5
            )
            cfg.genm3u.setValue(0)
            cfg.genm3u.save()
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
            cfg.genm3u.setValue(0)
            cfg.genm3u.save()
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

        cfg.genm3u.setValue(0)
        cfg.genm3u.save()

    def generate_all_m3u_files(self, confirm, countries):
        """Generate .m3u files for all countries"""
        if not confirm:
            cfg.genm3u.setValue(0)
            cfg.genm3u.save()
            return

        try:
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

            # Show detailed result
            msg = _("M3U generation completed!")
            msg += ""
            msg += _("Countries: %(generated)d/%(total)d") % {
                'generated': generated, 'total': len(countries)}
            msg += ""
            msg += _("Failed: %(failed)d") % {'failed': failed}
            msg += ""
            msg += _("Total channels: %(total_channels)d") % {
                'total_channels': total_channels}
            msg += ""
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

        cfg.genm3u.setValue(0)
        cfg.genm3u.save()

    def generate_single_m3u(self, country_name, channels):
        """Generate a single .m3u file for a country"""
        try:
            # Sanitize filename
            safe_name = country_name.lower()
            safe_name = safe_name.replace(' ', '_')
            safe_name = safe_name.replace('➾', '_').replace('⟾', '_')
            safe_name = safe_name.replace('->', '_').replace('→', '_')

            m3u_filename = "vavoo_%s.m3u" % safe_name
            m3u_path = join(downloadfree, m3u_filename)

            # M3U header
            m3u_content = "#EXTM3U\n"

            channel_count = 0
            for channel in channels:
                try:
                    if isinstance(channel, dict):
                        channel_name = channel.get('name', 'Unknown')
                        channel_url = channel.get('url', '')

                        # Clean channel name
                        channel_name = decodeHtml(channel_name)
                        channel_name = remove_parentheses(channel_name)

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
            try:
                with codecs.open(m3u_path, 'w', encoding='utf-8') as f:
                    f.write(m3u_content)
                print(
                    "[M3U] File created: %s (%d channels)" %
                    (m3u_path, channel_count))
            except Exception as e:
                print("[M3U] Error writing file: %s" % str(e))
                with open(m3u_path, 'w') as f:
                    f.write(m3u_content)

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

            channels = loads(response)
            return channels

        except Exception as e:
            print("[M3U] Error getting channels: %s" % str(e))
            return []

    def check_and_start_proxy(self):
        """Check and start the proxy if needed"""
        try:
            if not is_proxy_running():
                print("[M3U Export] Starting proxy...")
                if not run_proxy_in_background():
                    return False

            # Wait until the proxy is ready
            for i in range(10):
                if is_proxy_ready():
                    return True
                select.select([], [], [], 1)

            return False

        except Exception as e:
            print(
                "[M3U Export][check_and_start_proxy] Proxy error: %s" %
                str(e))
            return False

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
        for x in self.onChangedEntry:
            x()
        self['green'].instance.setText(
            _('Save') if self['config'].isChanged() else '- - - -')

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
        """Schedule automatic EPG updates using EPGImport's own scheduler"""
        try:
            # EPGImport's own scheduler picks up whatever sources the user
            # has enabled in ITS config screen - we used to try to enable
            # our source here by opening EPGIMPORT_CONF in text mode and
            # appending a "sources=..." line to it, but that file is
            # actually a binary serialized blob (not the plain-text format
            # this assumed), so every append corrupted EPGImport's own
            # config. Enabling the Vavoo source is left to the user via
            # EPGImport's settings screen instead.
            if cfg.epg_auto_update.value:
                pass

        except Exception as e:
            print("[Vavoo] Error scheduling EPG update:", str(e))

    def save(self):
        if self["config"].isChanged():
            old_position = getattr(cfg, 'list_position', None)
            if old_position:
                old_position = old_position.value

            for x in self["config"].list:
                x[1].save()

            if self.old_proxy_enabled != cfg.proxy_enabled.value:
                if cfg.proxy_enabled.value:
                    run_proxy_in_background(
                        startup_timeout=cfg.proxy_startup_timeout.value)
                    # Schedule a non‑blocking status check after 1 second
                    reactor.callLater(1, self._check_proxy_started)
                else:
                    shutdown_proxy()
                self.old_proxy_enabled = cfg.proxy_enabled.value

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

            # Manage EPG source
            if cfg.epg_enabled.value and not is_proxy_running():
                run_proxy_in_background(
                    startup_timeout=cfg.proxy_startup_timeout.value)
                # No sleep here – the proxy will become ready asynchronously

            # If auto‑update is enabled, schedule the EPG update
            if cfg.epg_enabled.value and cfg.epg_auto_update.value:
                self.schedule_epg_update()

            if old_position and old_position != cfg.list_position.value:
                self._reorganize_bouquets_position()

            configfile.save()

            try:
                config.loadFromFile(configfile.CONFIG_FILE)
            except Exception as e:
                print("Config reload error (safe mode): " + str(e))
                self._safe_config_reload()

            back_changed = self.old_back != cfg.back.value
            bakk = str(cfg.back.getValue()) + '.png'
            add_skin_back(bakk)

            message = _("Configuration saved successfully!")
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

    def _check_proxy_started(self):
        """Callback to verify proxy has started (non‑blocking)."""
        if cfg.proxy_enabled.value and not is_proxy_running():
            print("[Config] Proxy not yet ready, will check later")
            # Optionally schedule another check after 2 seconds
            reactor.callLater(2, self._check_proxy_started)
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
            if self['config'].isChanged():
                self.session.openWithCallback(
                    self.extnok, MessageBox, _("Really close without saving settings?"))
            else:
                self.close()
        elif answer:
            for x in self["config"].list:
                x[1].cancel()
            self.close()
        else:
            return


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
        skin = join(skin_path, 'Plgnstrt.xml')
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = f.read()

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

        if not cfg.proxy_enabled.value:
            # Nothing to wait for - proceed right away.
            self._finish()
            return

        # The proxy's HTTP port only opens once the whole catalog has
        # loaded, so every connection is refused until then. Check the
        # port cheaply first (near-instant) and only pay for the HTTP
        # round trip - with a single attempt, no retry/backoff - once it
        # is actually listening. Skipping this would make every poll
        # block for seconds at a time via getUrl()'s retry logic, on the
        # reactor thread, for the entire catalog-load duration.
        data = None
        if is_proxy_running():
            try:
                response = getUrl(PROXY_STATUS_URL, timeout=0.5, retries=1)
                data = loads(response) if response else None
            except Exception:
                data = None

        if data and data.get("initialized"):
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
            if not cfg.proxy_enabled.value:
                return
            if is_proxy_running() and is_proxy_ready(timeout=0.5):
                return
            run_proxy_in_background(
                startup_timeout=cfg.proxy_startup_timeout.value)
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
            self.session.open(MainVavoo)
        self.close()


class UpdatePopup(Screen):
    """Yes/No dialog for a newly-found plugin update, skinned to match
    the splash screen (Plgnstrt.xml) instead of a generic MessageBox."""

    def __init__(self, session, remote_version, changelog):
        Screen.__init__(self, session)
        skin = join(skin_path, 'UpdatePopup.xml')
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = f.read()

        self["title"] = Label(_("Update Available"))
        self["subtitle"] = Label(
            _("v{} -> v{}").format(__version__, remote_version))
        self["changelog_label"] = Label(_("Changelog:"))
        # ScrollLabel, not a plain Label: the changelog can run well
        # past what the fixed-height box fits (confirmed - a 9-entry
        # changelog overflowed a plain Label with no way to see the
        # rest). Construct it WITH the real text (same pattern
        # EPGImport's own log screen uses successfully) so something is
        # always visible even on images where pageHeight never comes
        # out right - a previous attempt here that constructed with ""
        # and deferred setText() entirely to onLayoutFinish left the box
        # completely blank on at least OpenATV 7.6, not just
        # mis-paginated. Still re-set it in onLayoutFinish too, once the
        # widget's bound size is actually established, so pagination
        # (pageUp/pageDown) is correct on images where the constructor
        # call alone gets a wrong/zero pageHeight.
        self._changelog_text = changelog or _("No changelog provided.")
        self["changelog"] = ScrollLabel(self._changelog_text)
        self.onLayoutFinish.append(self._setChangelogText)
        self["key_red"] = Label(_("Cancel"))
        self["key_green"] = Label(_("Yes, update now"))

        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions"],
            {
                "ok": self.confirm,
                "green": self.confirm,
                "cancel": self.deny,
                "red": self.deny,
                "up": self["changelog"].pageUp,
                "down": self["changelog"].pageDown,
                "left": self["changelog"].pageUp,
                "right": self["changelog"].pageDown,
            }, -1
        )

    def _setChangelogText(self):
        self["changelog"].setText(self._changelog_text)

    def confirm(self):
        self.close(True)

    def deny(self):
        self.close(False)


class MainVavoo(Screen):
    def __init__(self, session):
        self.session = session
        global _session
        _session = session

        Screen.__init__(self, session)
        init_notification_system(session)
        if NOTIFICATION_AVAILABLE:
            print('notify started')
            quick_notify(_("Welcome to Vavoo Proxy with EPG support"), 5)

        skin = join(skin_path, 'defaultListScreen.xml')
        if isfile('/var/lib/dpkg/status'):
            skin = skin.replace('.xml', '_cvs.xml')
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = apply_selected_background(f.read())

        if is_stats_enabled():
            record_anonymous_startup()
            start_heartbeat()

        self._initialize_labels()
        self._initialize_actions()
        self["menulist"].onSelectionChanged.append(self._update_selection_name)
        self.url = vUtils.b64decoder(stripurl)
        self.currentList = 'menulist'
        self.loading_ok = False
        self.count = 0
        self.loading = 0
        self.current_view = "categories"
        self.flag_refresh_timer = eTimer()
        try:
            self.flag_refresh_timer.callback.append(
                self.refresh_list_with_flags)
        except Exception:
            # Fallback in case the callback attribute does not exist
            self.flag_refresh_timer.timeout.connect(
                self.refresh_list_with_flags)

        if cfg.proxy_enabled.value:
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

        else:
            print("[MainVavoo] Proxy disabled by configuration")

            # Optional: stop proxy if it is running
            shutdown_proxy()

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
        global search_ok
        search_ok = False
        self['menulist'] = m2list([])
        self['red'] = Label(_('Exit'))
        self['green'] = Label(_('Remove') + ' Fav')
        self['yellow'] = Label()
        if cfg.epg_enabled.value:
            self['yellow'].setText(_("Fix Cache"))
        self["blue"] = Label(_('Reload Bouqet'))
        self['name'] = Label('Loading...')
        self['version'] = Label()
        self['proxy_status'] = Label('Wait...')

    def _initialize_actions(self):
        """Initialize the actions for buttons."""
        actions = {
            'prevBouquet': self.chDown,
            'nextBouquet': self.chUp,
            'ok': self.ok,
            'mainMenu': self.goConfig,
            'menu': self.goConfig,
            'green': self.msgdeleteBouquets,
            'blue': self.reload_bouquets_with_popup,
            'cancel': self.closex,
            'red': self.closex,
            'epg': self.manual_epg_update,
            'info': self.info,
            'InfoPressed': self.info,
            'infoLong': self._fix_cache_format,
            'yellow': self._fix_cache_format,
            'text': self.refresh_proxy,
        }
        actions_list = [
            'MenuActions',
            'OkCancelActions',
            'ButtonSetupActions',
            'InfobarEPGActions',
            'EPGSelectActions',
            'ColorActions'
        ]
        self['actions'] = ActionMap(actions_list, actions, -1)

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
        if not export_lock.acquire(blocking=False):
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
        debug("reload_bouquets_with_popup called")
        self.session.openWithCallback(
            self._confirm_reload_bouquets,
            MessageBox,
            _("Reload bouquets and service list?"),
            MessageBox.TYPE_YESNO,
            timeout=10,
            default=True
        )

    def _confirm_reload_bouquets(self, result):
        """Callback after user confirmation"""
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
                self.session.open(
                    MessageBox,
                    _("Bouquets reload scheduled."),
                    MessageBox.TYPE_INFO,
                    timeout=2
                )
            except Exception as e:
                print("[MessageBox] Error:", e)
        else:
            debug("User cancelled reload")

    def closex(self):
        debug("Exit from plugin. Cleaning up plugin timers...")
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
        except Exception as e:
            print("[Close] Error stopping timers: %s" % str(e))

        try:
            cleaned = cleanup_old_temp_files(max_age_hours=1)
            print("[Cleanup] Removed %d temporary files" % cleaned)
        except Exception as e:
            print("[Cleanup] Error: %s" % str(e))

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

    def preload_flags_for_visible_countries(self):
        """Preload flags for visible countries"""
        try:
            if not hasattr(self, 'all_data'):
                return

            countries = set()
            for entry in self.all_data:
                country = url_unquote(entry["country"]).strip("\r\n")
                if "➾" not in country:
                    countries.add(country)

            countries_list = sorted(list(countries))

            print(
                "[MainVavoo] Preloading flags for %d countries" %
                len(countries_list))

            # Preload first 8 flags SYNCHRONOUSLY
            downloaded = 0
            for i, country in enumerate(countries_list[:8]):  # First 8
                try:
                    success, _ = download_flag_online(
                        country, screen_width=screen_width)
                    if success:
                        downloaded += 1
                        print("[Preload] OK: %s" % country)
                except Exception as e:
                    print("[Preload] Error %s: %s" % (country, str(e)))

            print("[MainVavoo] Downloaded %d flags synchronously" % downloaded)

            # Start timer for refresh after 1 second
            if downloaded > 0:
                self.flag_refresh_timer.start(1000, True)

            # Download remaining in background
            if len(countries_list) > 8:

                def download_rest():
                    downloaded_rest = 0
                    for country in countries_list[8:]:
                        try:
                            success, _ = download_flag_online(
                                country, screen_width=screen_width)
                            if success:
                                downloaded_rest += 1
                        except BaseException as e:
                            debug(
                                "Background flag download failed for {}: {}".format(
                                    country, e))

                    print("[Background] Finished downloading remaining flags")
                    # The single-shot refresh above only covers the first
                    # 8 countries - without this, flags for every country
                    # after that silently never appear until something
                    # else happens to rebuild the list.
                    if downloaded_rest > 0:
                        reactor.callFromThread(
                            self.flag_refresh_timer.start, 1000, True)
                thread = threading.Thread(target=download_rest)
                thread.setDaemon(True)
                thread.start()

        except Exception as e:
            print("[MainVavoo] Error preloading flags: %s" % str(e))

    def refresh_list_with_flags(self):
        """Refresh list to show downloaded flags (Python 2/3 compatible)"""
        try:
            print("[MainVavoo] Refreshing list to show downloaded flags")

            # Recreate the list
            if cfg.default_view.value == "countries":
                self.show_countries_view()
            else:
                self.show_categories_view()

            self._update_ui()

            # Stop the timer
            self.flag_refresh_timer.stop()

        except Exception as e:
            print("[MainVavoo] Error refreshing list: %s" % str(e))

    def _proxy_watchdog_check(self):
        """Watchdog to check if the proxy is still alive"""
        try:
            if not cfg.proxy_enabled.value:
                return
            if not is_proxy_running():
                print("[Watchdog] Proxy not running, attempting restart...")
                self['proxy_status'].setText(_(" Restarting..."))

                # Try restart
                timeout = cfg.proxy_startup_timeout.value
                success = run_proxy_in_background(startup_timeout=timeout)

                if success:
                    print("[Watchdog] Proxy restarted successfully")
                    self['proxy_status'].setText(_("✓ Restarted"))
                else:
                    print("[Watchdog] Proxy restart failed")
                    self['proxy_status'].setText(_("✗ Restart Failed"))

        except Exception as e:
            print("[Watchdog] Error: " + str(e))

    def _check_and_update_proxy_status(self):
        """Check and update the proxy status periodically"""
        if not cfg.proxy_enabled.value:
            self['proxy_status'].setText(_("Proxy Disabled"))
            return
        try:
            if not is_proxy_ready(timeout=2):
                self.proxy_needs_attention = True
                print("[MainVavoo] Proxy needs attention")
            else:
                self.proxy_needs_attention = False

            self._update_proxy_status_display()
            # self.update_proxy_status_display()
        except Exception as e:
            print(
                "[MainVavoo][_check_and_update_proxy_status] Error in proxy monitor: " +
                str(e))
            self['proxy_status'].setText(_("✗ Proxy Error"))

    def update_proxy_status(self):
        """Public method to update proxy status (can be called manually)"""
        self._update_proxy_status_display()

    def _update_proxy_status_display(self):
        """Internal method to update proxy status display"""
        try:
            if not cfg.proxy_enabled.value:
                self['proxy_status'].setText(_("Proxy Disabled"))
                return
            if is_proxy_running():
                try:
                    response = getUrl(
                        PROXY_STATUS_URL, timeout=5)
                    if response:
                        status_data = loads(response)

                        if status_data.get(
                                "initialized", False) and status_data.get(
                                "addon_sig_valid", False):
                            token_age = status_data.get("addon_sig_age", 0)

                            if token_age < 300:
                                status_text = "✓ Proxy OK"
                            elif token_age < 540:
                                ttl = 600 - token_age
                                status_text = "✓ Proxy (" + \
                                    str(int(ttl)) + "s)"
                            else:
                                status_text = "Proxy (expiring)"
                        else:
                            status_text = "✗ Proxy Error"
                    else:
                        status_text = "? Proxy Unknown"
                except Exception:
                    status_text = "✓ Proxy Running"
            else:
                status_text = "✗ Proxy Offline"

            self['proxy_status'].setText(status_text)

        except Exception as e:
            print("[MainVavoo] Error updating proxy status: " + str(e))
            self['proxy_status'].setText(_("✗ Error"))

    def refresh_proxy(self):
        """Force proxy refresh"""
        if not cfg.proxy_enabled.value:
            self['name'].setText(_("Proxy disabled"))
            return
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
        """Callback for proxy refresh"""
        if result:
            try:
                # Try to refresh the token
                response = getUrl(
                    PROXY_REFRESH_URL, timeout=5)
                if response:
                    data = loads(response)
                    if data.get("status") == "success":
                        self.session.open(
                            MessageBox,
                            _("Proxy token refreshed successfully"),
                            MessageBox.TYPE_INFO,
                            timeout=3
                        )
                        self._update_proxy_status_display()
                    else:
                        self.session.open(
                            MessageBox,
                            _("Failed to refresh proxy token"),
                            MessageBox.TYPE_ERROR,
                            timeout=3
                        )
            except Exception as e:
                print("[Refresh Proxy] Error: " + str(e))
                self.session.open(
                    MessageBox,
                    _("Failed to refresh proxy: ") + str(e),
                    MessageBox.TYPE_ERROR,
                    timeout=3
                )

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
        if not cfg.proxy_enabled.value:
            return False

        # If the proxy is already active and working, do nothing
        if is_proxy_running() and is_proxy_ready(timeout=1):
            print("[MainVavoo] Proxy already ready")
            self._update_proxy_status_display()
            return True

        # If it is running but not ready, let it stabilize
        if is_proxy_running():
            print("[MainVavoo] Proxy running but not ready, waiting...")
            self._wait_for_proxy()
            return True

        print("[MainVavoo] Starting proxy...")
        timeout = cfg.proxy_startup_timeout.value
        success = run_proxy_in_background(startup_timeout=timeout)
        if success:
            self._wait_for_proxy()
        return success

    def _wait_for_proxy(self, attempts=0):
        timeout_secs = cfg.proxy_startup_timeout.value
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

    def _check_proxy_ready_async(self, attempts=0):
        if attempts > 20:
            print("[MainVavoo] Proxy not ready after timeout")
            return
        if is_proxy_ready(timeout=0.5):
            print("[MainVavoo] Proxy ready")
            self._update_proxy_status_display()
        else:
            reactor.callLater(
                0.5, lambda: self._check_proxy_ready_async(
                    attempts + 1))

    def _check_proxy_ready(self):
        if is_proxy_ready(timeout=0.5):
            print("[MainVavoo] Proxy ready")
            self._update_proxy_status_display()
            return
        self._proxy_ready_attempts += 1
        if self._proxy_ready_attempts < 20:      # 20 * 0.5 = 10 seconds max
            reactor.callLater(0.5, self._check_proxy_ready)
        else:
            print("[MainVavoo] Proxy not ready after timeout")

    def _restart_proxy(self):
        """Restart the proxy asynchronously."""
        try:
            # 1. Try to shut down existing proxy (non‑blocking request)
            try:
                if requests is not None:
                    requests.get(PROXY_SHUTDOWN_URL, timeout=2)
                else:
                    req = UrlRequest(
                        PROXY_SHUTDOWN_URL, headers={
                            'User-Agent': vUtils.RequestAgent()})
                    urlopen(req, timeout=2)
            except Exception as e:
                debug("Graceful proxy shutdown request failed, "
                      "falling back to pkill: {}".format(e))

            # 2. Kill any remaining python processes
            os_system("pkill -f 'python.*vavoo_proxy' 2>/dev/null")

            # 3. Wait 2 seconds without blocking, then do the restart
            reactor.callLater(2, self._do_restart_proxy)
        except Exception as e:
            print("[Restart] Error: {0}".format(e))

    def _do_restart_proxy(self):
        """Actually start the proxy after the delay."""
        timeout = cfg.proxy_startup_timeout.value
        run_proxy_in_background(startup_timeout=timeout)

    def cat(self):
        """
        Load and display the country list.
        Uses the local proxy if available, otherwise waits and retries.
        """
        if not cfg.proxy_enabled.value:
            self['name'].setText(_("Proxy disabled"))
            return

        self.cat_list = []
        self.items_tmp = []

        # If proxy is not ready yet, schedule a quick retry
        if not is_proxy_ready(timeout=0.5):
            print("[MainVavoo] Proxy not ready, will retry shortly")
            if not hasattr(self, '_country_retry_timer'):
                self._country_retry_timer = eTimer()
                try:
                    self._country_retry_timer.callback.append(self.cat)
                except Exception:
                    # Fallback in case the callback attribute does not exist
                    self._country_retry_timer.timeout.connect(self.cat)
            self._country_retry_timer.start(500, True)
            return

        try:
            # Fetch countries from the proxy
            response = getUrl(PROXY_COUNTRIES_URL, timeout=10)
            if response:
                countries = loads(response)
                print(
                    "[MainVavoo] Got {} countries from proxy".format(
                        len(countries)))
                for country in sorted(countries):
                    self.cat_list.append(show_list(country, country))
                self._update_ui()
                self["version"].setText(to_string("V." + __version__))
                # Clear the retry timer if it exists
                if hasattr(self, '_country_retry_timer'):
                    self._country_retry_timer.stop()
                    del self._country_retry_timer
                return
            else:
                print("[MainVavoo] Proxy countries request failed")
                # Fallback to original method (may fail, but we try)
                self._load_countries_from_original_source()
        except Exception as e:
            print("[MainVavoo] Error in cat(): %s" % str(e))
            trace_error()
            self["name"].setText(to_string("Error loading data"))

    def _load_countries_from_original_source(self):
        """Fallback: load countries from the original source (may fail if blocked)."""
        try:
            content = self._get_content()
            if PY3:
                content = vUtils.ensure_str(content)
            if not content:
                self["name"].setText(to_string("Error: No data received"))
                return
            data = self._parse_json(content)
            if data is None:
                self["name"].setText(to_string("Error: Invalid data format"))
                return
            self.all_data = data
            countries = set()
            for entry in self.all_data:
                country = url_unquote(entry["country"]).strip("\r\n")
                if "➾" not in country and country.lower() != "default" and len(country) > 1:
                    countries.add(country)
            for country in sorted(countries):
                self.cat_list.append(show_list(country, country))
            self._update_ui()
            self["version"].setText(to_string("V." + __version__))
        except Exception as e:
            print("[MainVavoo] Fallback error: %s" % str(e))
            self["name"].setText(to_string("Error loading data"))

    def _parse_select_options(self, html_content):
        """Parses options from the HTML select menu"""
        options = []

        # Regex to find the select menu and its options
        select_pattern = r'<select[^>]*>(.*?)</select>'
        option_pattern = r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)</option>'

        select_match = compile(select_pattern, DOTALL).search(html_content)
        if select_match:
            select_content = select_match.group(1)
            option_matches = compile(
                option_pattern, DOTALL).findall(select_content)
            for value, text in option_matches:
                if value and text and text != "All countries":
                    options.append((text.strip(), value))

        return options

    def _get_content(self):
        """Get catalog content with 451-aware fallback to kool.to"""

        def _try(url):
            data = getUrl(url)
            if PY3:
                data = ensure_str(data)
            return data

        content = _try(self.url)

        # Detect 451 or empty payload and try mirror
        if (not content) or (content == HTTP_451_SENTINEL):
            try:
                if "vavoo.to" in self.url:
                    fallback_url = self.url.replace(
                        PRIMARY_BASE_URL, FALLBACK_BASE_URL)
                else:
                    # If self.url was altered somewhere, still try mirror
                    fallback_url = FALLBACK_BASE_URL.rstrip("/") + "/channels"

                print(
                    "[PROXY] Primary source blocked/empty, trying mirror: {0}".format(fallback_url))
                content2 = _try(fallback_url)
                if content2 and content2 != HTTP_451_SENTINEL:
                    return content2
            except Exception as e:
                print("[PROXY] Mirror fallback failed: %s" % str(e))

        # If still blocked, return empty so UI shows the existing error
        if content == HTTP_451_SENTINEL:
            return ""
        return content

    def _parse_json(self, content):
        try:
            return loads(content)
        except ValueError:
            print("Error parsing JSON data")
            self["name"].setText(_("Error parsing data"))
            return None

    def show_categories_view(self):
        """Show only categories (without main countries) - SINGLE FILE EXPORT"""
        if not cfg.proxy_enabled.value:
            self.session.open(
                MessageBox,
                _("Proxy is disabled. Please enable it in the configuration."),
                MessageBox.TYPE_WARNING,
                timeout=5
            )
            return

        self.current_view = "categories"
        self.cat_list = []

        if not hasattr(self, 'all_data'):
            return

        categories = set()
        for entry in self.all_data:
            country = url_unquote(entry["country"]).strip("\r\n")
            if "➾" in country:
                categories.add(country)

        categories_list = sorted(list(categories))

        for category in categories_list:
            self.cat_list.append(show_list(category, self.url, True))

        self._update_ui()

    def show_countries_view(self):
        """Show only main countries"""
        self.current_view = "countries"
        self.cat_list = []

        if not hasattr(self, 'all_data'):
            return

        countries = set()
        for entry in self.all_data:
            country = url_unquote(entry["country"]).strip("\r\n")
            if "➾" not in country:
                countries.add(country)

        countries_list = sorted(list(countries))

        for country in countries_list:
            self.cat_list.append(show_list(country, self.url))

        self._update_ui()

    def ok(self):
        try:
            current_item = self['menulist'].getCurrent()
            if not current_item or len(current_item) == 0:
                print("DEBUG: No current item selected or item is empty")
                return

            name = current_item[0][0]  # Country name (e.g., "Italy")
            print("[MainVavoo] Selected: " + str(name))

            # Pass ONLY the country name to the vavoo class
            # The vavoo class will handle the proxy internally
            try:
                if not cfg.proxy_enabled.value:
                    self.session.open(
                        MessageBox,
                        _("Proxy is disabled. Please Set Proxy On first. -- Menu Config --"),
                        MessageBox.TYPE_WARNING,
                        timeout=5)
                    return

                if not is_proxy_running():
                    self.session.open(
                        MessageBox,
                        _("Proxy is not running. Please start the proxy first.") +
                        "\n" +
                        _("You can start it from the menu or by pressing the TEXT button."),
                        MessageBox.TYPE_WARNING,
                        timeout=5)
                    return

                # Pass ONLY the country name to the vavoo class
                self.session.open(vavoo, name, None)
            except Exception as e:
                print("Error opening vavoo screen: " + str(e))
                trace_error()

        except Exception as e:
            print("Error in ok method: " + str(e))
            trace_error()

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
            cfg = EPGConfig.loadUserSettings()
            sources = list(
                EPGConfig.enumSources(CONFIG_PATH, filter=cfg["sources"]))
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
            try:
                removed_count = remove_bouquets_by_name()

                # Remove Favorite.txt
                favorite_path = join(PLUGIN_PATH, 'Favorite.txt')
                if isfile(favorite_path):
                    remove(favorite_path)
                    print("✓ Removed Favorite.txt")

                # Build message safely for translation
                message = _("Vavoo bouquets removed successfully!")
                message += ""
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

    def goConfig(self):
        self.session.openWithCallback(self._on_config_closed, vavoo_config)

    def _on_config_closed(self, *args, **kwargs):
        # called when user exits config
        self._apply_proxy_setting_and_refresh_ui()

    def _apply_proxy_setting_and_refresh_ui(self):
        try:
            if cfg.proxy_enabled.value:
                # Start proxy (already also done in config.save, but safe)
                self.start_vavoo_proxy()

                # Start timers if they don't exist or were stopped
                if not hasattr(self, "proxy_watchdog_timer"):
                    self.proxy_watchdog_timer = eTimer()
                    try:
                        self.proxy_watchdog_timer.timeout.connect(
                            self._proxy_watchdog_check)
                    except BaseException:
                        self.proxy_watchdog_timer.callback.append(
                            self._proxy_watchdog_check)

                if not hasattr(self, "proxy_monitor_timer"):
                    self.proxy_monitor_timer = eTimer()
                    try:
                        self.proxy_monitor_timer.timeout.connect(
                            self._check_and_update_proxy_status)
                    except BaseException:
                        self.proxy_monitor_timer.callback.append(
                            self._check_and_update_proxy_status)

                # (Re)start them
                self.proxy_watchdog_timer.start(PROXY_WATCHDOG_INTERVAL_MS)
                self.proxy_monitor_timer.start(PROXY_MONITOR_INTERVAL_MS)

                # Refresh labels + list
                self["proxy_status"].setText(_("Checking proxy..."))
                try:
                    self._update_proxy_status_display()
                except Exception as e:
                    debug("_update_proxy_status_display failed, label may "
                          "stay stuck on 'Checking proxy...': {}".format(e))

                # If previously proxy disabled, cat() would have returned early.
                # Rebuild list now that proxy is enabled.
                self.cat()

            else:
                # Stop timers if running
                for tname in ("proxy_watchdog_timer", "proxy_monitor_timer"):
                    if hasattr(self, tname):
                        try:
                            getattr(self, tname).stop()
                        except Exception:
                            pass

                # Stop proxy process
                shutdown_proxy()

                # Update UI immediately
                self["proxy_status"].setText(_("Proxy Disabled"))
                self["name"].setText(_("Proxy disabled"))
                self.cat_list = []
                self._update_ui()

        except Exception as e:
            print("[MainVavoo] Error applying proxy setting: " + str(e))

    def info(self):
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

        aboutbox = self.session.open(
            MessageBox,
            info_text,
            MessageBox.TYPE_INFO
        )
        aboutbox.setTitle(_('Vavoo Stream Live - Information'))

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


class vavoo(Screen):
    def __init__(self, session, name, url, option_value=None):
        self.session = session
        global _session
        _session = session

        Screen.__init__(self, session)
        init_notification_system(session)
        self._load_skin()
        self._initialize_labels()
        self._initialize_actions()
        self["menulist"].onSelectionChanged.append(self._update_selection_name)
        self.currentList = 'menulist'

        # Store country name properly
        self.country_name = name
        self.name = name
        self.url = url
        self.option_value = option_value
        self._update_export_button_label()

        self.current_view = "countries"  # default
        try:
            for screen in self.session.dialog_stack:
                if hasattr(screen, 'current_view'):
                    self.current_view = screen.current_view
                    print(
                        "DEBUG: Got current_view from main screen: " +
                        self.current_view)
                    break
        except Exception as e:
            print("DEBUG: Error getting current_view: " + str(e))

        # Do NOT try to initialize proxy here - it should already be running
        # Just verify it's ready
        self._verify_proxy_ready()

        self._initialize_timer()
        self._initialize_proxy_status_timer()

    def _initialize_proxy_status_timer(self):
        """Keep the proxy_status label live while this screen is open.

        Unlike MainVavoo (which refreshes every 10s via
        proxy_monitor_timer), this screen previously only set the label
        once in _verify_proxy_ready() and never again, so it went stale
        the moment the user opened a country.
        """
        self.proxy_status_timer = eTimer()
        try:
            self.proxy_status_timer.timeout.connect(
                self._update_proxy_status_display)
        except BaseException:
            self.proxy_status_timer.callback.append(
                self._update_proxy_status_display)
        self.proxy_status_timer.start(10000)

    def _verify_proxy_ready(self):
        """Verify that the proxy is ready without attempting to start it"""
        try:
            if not is_proxy_ready(timeout=2):
                print(
                    "[vavoo] Warning: Proxy not ready for %s" %
                    self.country_name)
                # Do not start the proxy here – let the cat() method handle the
                # fallback
            self["proxy_status"].setText(_("Checking proxy..."))
            try:
                self._update_proxy_status_display()
            except Exception as e:
                debug("_update_proxy_status_display failed, label may "
                      "stay stuck on 'Checking proxy...': {}".format(e))
        except Exception as e:
            print("[vavoo] Error checking proxy: %s" % str(e))

    def _load_skin(self):
        """Load the skin file."""
        skin = join(skin_path, 'defaultListScreen.xml')
        if isfile('/var/lib/dpkg/status'):
            skin = skin.replace('.xml', '_cvs.xml')
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = apply_selected_background(f.read())

    def _initialize_labels(self):
        """Initialize the labels on the screen."""
        self.menulist = []
        global search_ok
        search_ok = False
        self['menulist'] = m2list([])
        self['red'] = Label(_('Back'))
        self['green'] = Label(_('Export') + ' Fav')
        self['yellow'] = Label(_('Search'))
        self["blue"] = Label(_('Reload Bouqet'))
        self['name'] = Label('Loading ...')
        self['version'] = Label()
        self["version"].setText(to_string("V." + __version__))
        self['proxy_status'] = Label('...')

    def _initialize_actions(self):
        """Initialize the actions for buttons."""
        self["actions"] = ActionMap(
            [
                'MenuActions',
                'OkCancelActions',
                'ButtonSetupActions',
                'InfobarEPGActions',
                'EPGSelectActions',
                'ColorActions'
            ],
            {
                "prevBouquet": self.chDown,
                "nextBouquet": self.chUp,
                "ok": self.ok,
                "green": self.message1,
                "yellow": self.search_vavoo,
                "blue": self._reload_services,
                "cancel": self.backhome,
                "menu": self.goConfig,
                # "info": self.info,
                "red": self.backhome
            },
            -1
        )

    def _initialize_timer(self):
        """Initialize the timer with proper timeout handling"""
        self.timer = eTimer()
        try:
            self.timer.callback.append(self.cat)
        except BaseException:
            self.timer.timeout.connect(self.cat)
        self.timer.start(500, True)

    def cat(self):
        """Load channels for the selected country with proxy verification and fallback"""
        debug("vavoo.cat() called for country: " + str(self.country_name))
        if not cfg.proxy_enabled.value:
            print("[vavoo] Proxy disabled, using fallback directly")
            self._fallback_to_original_method()
            return
        try:
            # 1. TRY THE PROXY FIRST
            try:
                country_encoded = url_quote(self.country_name)
                proxy_url = PROXY_BASE_URL + \
                    "/channels?country={}".format(country_encoded)
                debug("Fetching from proxy: " + proxy_url)

                content = getUrl(proxy_url, timeout=10)

                if content and content.strip() and content != "null":
                    channels_data = loads(content)
                    self._build_channel_list(channels_data)
                    return
                else:
                    debug(
                        "[cat] Proxy returned empty response, trying fallback...")
            except Exception as proxy_error:
                debug("[cat] Proxy error: " + str(proxy_error))

            # 2. FALLBACK: use the original method
            self._fallback_to_original_method()

        except Exception as e:
            print("[ERROR] CRITICAL in cat(): " + str(e))
            trace_error()
            self._handle_cat_error(e)

    def _fallback_to_original_method(self):
        """Fallback to the original method without using the proxy"""
        try:
            print("[Fallback] Using original data source...")

            # Retrieve data directly from vavoo.to
            url = vUtils.b64decoder(stripurl)
            content = getUrl(url, timeout=10)

            # 451-aware mirror fallback
            if (not content) or (content == HTTP_451_SENTINEL):
                fb = url.replace(PRIMARY_BASE_URL, FALLBACK_BASE_URL)
                print(
                    "[Fallback] Primary source blocked/empty, trying mirror: %s" %
                    fb)
                content = getUrl(fb, timeout=10)
                if content == HTTP_451_SENTINEL:
                    content = ""

            if not content:
                self['name'].setText(to_string("Error: No data received"))
                return

            data = loads(content)
            self.cat_list = []

            for entry in data:
                country = url_unquote(entry.get("country", "")).strip("\r\n")
                if self.country_name in country:  # Partial match
                    name = entry.get("name", "")
                    url = entry.get("url", "")

                    if name and url:
                        self.cat_list.append(
                            show_list(name, url, is_channel=True)
                        )

            if not self.cat_list:
                self['name'].setText(
                    to_string("No channels found for " + self.country_name)
                )
                return

            self.itemlist = [
                item[0][0] + "###" + item[0][1]
                for item in self.cat_list
            ]
            self.update_menu()
            print(
                "[Fallback] Loaded " +
                str(len(self.cat_list)) +
                " channels"
            )

        except Exception as e:
            print("[Fallback] Error: " + str(e))
            self['name'].setText(
                to_string("Error loading channels")
            )

    def _build_channel_list(self, channels_data):
        """Build channel list from proxy data"""
        self.cat_list = []

        if not isinstance(channels_data, list):
            print("[vavoo] Invalid channels data type: " +
                  str(type(channels_data)))
            return

        for channel in channels_data:
            if isinstance(channel, dict):
                channel_name = channel.get("name", "Unknown")
                channel_url = channel.get("url", "")

                self.cat_list.append(
                    show_list(channel_name, channel_url, is_channel=True)
                )

        if not self.cat_list:
            self['name'].setText(to_string("No proxy URLs built."))
            return

        self.itemlist = [
            item[0][0] + "###" + item[0][1] for item in self.cat_list
        ]
        self.update_menu()
        debug("List built with " + str(len(self.cat_list)) + " items.")

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

    def _update_proxy_status_display(self):
        """Internal method to update proxy status display"""
        try:
            if not cfg.proxy_enabled.value:
                self['proxy_status'].setText(_("Proxy Disabled"))
                return
            if is_proxy_running():
                try:
                    response = getUrl(
                        PROXY_STATUS_URL, timeout=5)
                    if response:
                        status_data = loads(response)

                        if status_data.get(
                                "initialized", False) and status_data.get(
                                "addon_sig_valid", False):
                            token_age = status_data.get("addon_sig_age", 0)

                            if token_age < 300:
                                status_text = "✓ Proxy OK"
                            elif token_age < 540:
                                ttl = 600 - token_age
                                status_text = "✓ Proxy (" + \
                                    str(int(ttl)) + "s)"
                            else:
                                status_text = "Proxy (expiring)"
                        else:
                            status_text = "✗ Proxy Error"
                    else:
                        status_text = "? Proxy Unknown"
                except Exception:
                    status_text = "✓ Proxy Running"
            else:
                status_text = "✗ Proxy Offline"

            self['proxy_status'].setText(status_text)

        except Exception as e:
            print("[MainVavoo] Error updating proxy status: " + str(e))
            self['proxy_status'].setText(_("✗ Error"))

    def _reload_services(self):
        try:
            db = eDVBDB.getInstance()
            db.reloadBouquets()
            db.reloadServicelist()
            print("Bouquets reloaded successfully")
        except Exception as e:
            print("Error during service reload: " + str(e))
            ReloadBouquets(500)

    def ok(self):
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

            self.play_that_shit(
                url,
                name,
                self.currentindex,
                item,
                self.cat_list)
        except Exception as e:
            print('error as:', e)
            trace_error()

    def play_that_shit(self, url, name, index, item, cat_list):
        try:
            country_code = get_country_code(self.country_name)
            self.session.open(
                Playstream2,
                name, url, index, item, cat_list,
                country_code=country_code
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

    def _update_export_button_label(self):
        """Green button reads 'Remove Fav' if this bouquet is already
        exported, 'Export Fav' otherwise."""
        try:
            if is_bouquet_exported(self.name):
                self['green'].setText(_('Remove') + ' Fav')
            else:
                self['green'].setText(_('Export') + ' Fav')
        except Exception as e:
            debug("_update_export_button_label failed: {}".format(e))

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
        try:
            removed = remove_bouquets_by_name(self.name)
            if removed > 0:
                remove_favorite_entry(self.name)
                if NOTIFICATION_AVAILABLE:
                    quick_notify(
                        _("Removed exported bouquet: {}").format(self.name), 3)
                self._reload_services()
            else:
                if NOTIFICATION_AVAILABLE:
                    quick_notify(
                        _("Nothing to remove for: {}").format(
                            self.name), 3)
        except Exception as e:
            print("[vavoo] Error removing favorite: {}".format(e))
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Remove failed: {}").format(str(e)), 4)
        self._update_export_button_label()

    def message2(self, name, url, response):
        if not export_lock.acquire(blocking=False):
            if NOTIFICATION_AVAILABLE:
                quick_notify(
                    _("An export for another country is already in progress. Please wait."), 4)
            return

        self._export_type = "hierarchical" if any(
            sep in name for sep in ["➾", "⟾", "->", "→"]) else "flat"

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
                self._update_export_button_label()
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
            print("[Bouquet] Error in _on_export_complete: %s" % e)

    def search_vavoo(self):
        self.saved_itemlist = self.itemlist
        self.session.openWithCallback(
            self.onSearchResult, VavooSearch, self, self.itemlist)

    def onSearchResult(self, selected_item=None):
        """Callback with the channel selected by the search"""
        if selected_item:
            name, url = selected_item
            self.session.open(
                Playstream2,
                name,
                url,
                0,
                [name, url],
                [[[name, url]]]
            )

    def goConfig(self):
        self.session.open(vavoo_config)

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

    def _update_selection_name(self):
        """Update the name label with current selection"""
        try:
            current = self['menulist'].getCurrent()
            if current and len(current) > 0:
                name = current[0][0]
                self['name'].setText(to_string(name))
                print("vavoo _update_selection_name: " + to_string(name))
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
        return Screen.close(self, *args, **kwargs)

    def backhome(self):
        if search_ok:
            self.cat()
        self.close()


# --- Live search screen ---
class VavooSearch(Screen):
    def __init__(self, session, parentScreen, itemlist):
        self.session = session
        self.parentScreen = parentScreen
        self.itemlist = itemlist
        self.filteredList = []
        self.selectedIndex = 0
        self.search_text = ""
        self.current_input = ""
        skin = join(skin_path, 'vavoo_search.xml')
        if isfile('/var/lib/dpkg/status'):
            skin = skin.replace('.xml', '_cvs.xml')
        with codecs.open(skin, "r", encoding="utf-8") as f:
            self.skin = f.read()
        Screen.__init__(self, session)
        self["search_label"] = Label(_("Search Channels:"))
        self["search_text"] = Label("")
        self['version'] = Label()
        self["input_info"] = Label(
            _("Press GREEN to type, YELLOW to delete"))
        self["channel_list"] = m2list([])
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

        self.searchTimer = eTimer()
        try:
            self.searchTimer.timeout.connect(self.updateFilteredList)
        except BaseException:
            self.searchTimer.callback.append(self.updateFilteredList)

        self.numericalInput = NumericalTextInput(
            nextFunc=self.searchWithString)
        self.input_active = False
        self.upper_case = False
        self.last_key = None
        self.search_text = ""
        self.last_key_time = 0
        self.key_timer = eTimer()
        try:
            self.key_timer.timeout.connect(self.finishKeyInput)
        except BaseException:
            self.key_timer.callback.append(self.finishKeyInput)

        self.updateFilteredList()

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

    def finishKeyInput(self):
        """Reset key state after inactivity"""
        self.last_key = None

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

    def onSearchResult(self, selected_item=None):
        """Callback with the channel selected from the search"""
        if selected_item:
            name, url = selected_item
            self.session.open(
                Playstream2,
                name,
                url,
                0,
                [name, url],
                [[[name, url]]]
            )
        else:
            # Return to the channel list without doing anything
            print("[Search] Search cancelled, returning to channel list")

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
        text = self.search_text.lower().strip()

        if not text:
            self.filteredList = self.itemlist[:]
            self["status"].setText(
                _("Showing all channels: {}").format(len(self.filteredList)))
        else:
            self.filteredList = []
            for item in self.itemlist:
                try:
                    name = item.split('###')[0].lower()
                    if text in name:
                        self.filteredList.append(item)
                except BaseException:
                    continue

            if self.filteredList:
                # Build message parts without embedding quotes in translations
                part1 = _("Search:")
                part2 = _("Found: {} channels").format(len(self.filteredList))

                message = '{} "{}" - {}'.format(
                    part1,
                    self.search_text,
                    part2
                )
                self["status"].setText(message)
            else:
                # Build message parts without embedding quotes in translations
                part1 = _("Search:")
                part2 = _("No channels found")

                message = '{} "{}" - {}'.format(
                    part1,
                    self.search_text,
                    part2
                )
                self["status"].setText(message)

        self.updateChannelList()

        if self.filteredList:
            self.selectedIndex = 0
            self["channel_list"].moveToIndex(self.selectedIndex)
        else:
            self.selectedIndex = -1

        self["version"].setText(to_string("V." + __version__))

    def updateChannelList(self):
        display_list = []
        for item in self.filteredList:
            try:
                name = item.split('###')[0]
                url = item.split('###')[1].replace(
                    '%0a', '').replace(
                    '%0A', '').strip("\r\n")
                display_list.append(show_list(name, url))
            except BaseException:
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
        if self.filteredList and 0 <= self.selectedIndex < len(
                self.filteredList):
            channel_item = self.filteredList[self.selectedIndex]
            name = channel_item.split('###')[0]
            url = channel_item.split('###')[1].replace(
                '%0a', '').replace('%0A', '').strip("\r\n")
            self.close((name, url))
        else:
            self.close(None)

    def onPlayerClosed(self, result=None):
        """Callback called when the player is closed"""
        print("DEBUG: Player closed, returning to Vavoo main screen")
        self.close()

    def onCancel(self):
        """Return to the Vavoo screen without opening the player"""
        print("DEBUG: Search cancelled, returning to Vavoo main screen")
        self.close()

    def close(self, *args, **kwargs):
        """Cleanup when the screen is closed"""
        try:
            # Stop timers
            if hasattr(self, 'searchTimer'):
                self.searchTimer.stop()
                try:
                    if hasattr(self.searchTimer, 'callback'):
                        self.searchTimer.callback.remove(
                            self.updateFilteredList)
                except BaseException:
                    pass

            if hasattr(self, 'key_timer'):
                self.key_timer.stop()

            # Reset input
            if hasattr(self, 'numericalInput'):
                self.numericalInput.nextKey()
        except Exception as e:
            print("[VavooSearch] Error in close: {0}".format(e))

        return Screen.close(self, *args, **kwargs)


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

        # Top overlay: controls + proxy status
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

    def show_help_overlay(self):
        """Show custom overlays and start the auto‑hide timer."""
        debug("show_help_overlay START")
        try:
            # Prepare help overlay text (controls + proxy details)
            if is_proxy_running():
                status = get_proxy_status()
                if status:
                    token_age = status.get("addon_sig_age", 0)
                    channels = status.get("channels_count", 0)

                    if token_age < 300:
                        proxy_msg = _("✓ Proxy OK")
                    elif token_age < 420:
                        ttl = 600 - token_age
                        proxy_msg = _("✓ Proxy ({0}s)").format(int(ttl))
                    else:
                        proxy_msg = _("✗ Proxy Expired")

                    channels_text = _("Channels")
                    proxy_details = "{} | {}: {}".format(
                        proxy_msg, channels_text, channels)
                else:
                    proxy_details = _("? Proxy Unknown")
            else:
                proxy_details = _("✗ Proxy Offline")

            controls = _("CH±=Change | OK=Toggle | INFO=IMDb | STOP=Exit")
            credit = "by Lululla & Qu4k3"
            help_text = "{} | {} | {}".format(controls, proxy_details, credit)
            self["helpOverlay"].setText(help_text)
            self["helpOverlay"].show()
            debug("show_help_overlay helpOverlay shown")

            # Show EPG (initially "Loading...")
            self["epgOverlay"].setText(_("Loading EPG..."))
            self["epgOverlay"].show()
            debug("show_help_overlay epgOverlay shown")

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
                try:
                    epg_text = self.get_current_epg()
                except Exception as e:
                    print("[Show Help] Async EPG fetch error: " + str(e))
                    return
                if self._closed:
                    return

                def _apply_epg_text():
                    try:
                        if not self._closed and self["helpOverlay"].visible:
                            self["epgOverlay"].setText(epg_text)
                            debug("show_help_overlay EPG updated: {}".format(
                                epg_text[:50]))
                    except Exception as e:
                        debug("Applying EPG overlay text failed: {}".format(e))
                reactor.callFromThread(_apply_epg_text)

            _epg_fetch_thread = threading.Thread(target=_fetch_epg_async)
            _epg_fetch_thread.setDaemon(True)
            _epg_fetch_thread.start()

        except Exception as e:
            print("[Show Help] Error: " + str(e))
        debug("show_help_overlay END")

    def update_proxy_status_overlay(self):
        """Update the helpOverlay text with current proxy status."""
        if self["helpOverlay"].visible:
            try:
                current_text = self["helpOverlay"].getText()
                parts = current_text.split("|")
                if len(parts) > 2:
                    controls_part = parts[0].strip()
                    credit_part = parts[-1].strip()

                    if is_proxy_running():
                        status = get_proxy_status()
                        if status:
                            token_age = status.get("addon_sig_age", 0)
                            channels = status.get("channels_count", 0)
                            if token_age < 300:
                                proxy_msg = _("✓ Proxy OK")
                            elif token_age < 420:
                                ttl = 600 - token_age
                                proxy_msg = _(
                                    "✓ Proxy ({0}s)").format(int(ttl))
                            else:
                                proxy_msg = _("✗ Proxy Expired")
                            channels_text = _("Channels")
                            proxy_details = "{} | {}: {}".format(
                                proxy_msg, channels_text, channels)
                        else:
                            proxy_details = _("? Proxy Unknown")
                    else:
                        proxy_details = _("✗ Proxy Offline")

                    new_text = "{} | {} | {}".format(
                        controls_part, proxy_details, credit_part)
                    self["helpOverlay"].setText(new_text)
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
            country_code=None):
        Screen.__init__(self, session)
        self.session = session
        init_notification_system(session)
        self.skinName = 'MoviePlayer'

        self.stream_running = False
        self.is_streaming = False
        # Set once cancel() starts closing this screen, so a background
        # EPG fetch already in flight from a channel the user has since
        # left (show_help_overlay's _fetch_epg_async) can notice and
        # stop touching self instead of running against a torn-down
        # screen.
        self._closed = False
        self.currentindex = index
        self.item = item
        self.itemscount = len(cat_list)
        self.list = cat_list
        self.country_code = country_code
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

        self['actions'] = ActionMap(
            [
                'MoviePlayerActions',
                'MovieSelectionActions',
                'MediaPlayerActions',
                'EPGSelectActions',
                'OkCancelActions',
                'InfobarShowHideActions',
                'InfobarActions',
                'DirectionActions',
                'InfobarSeekActions'
            ],
            {
                "stop": self.leavePlayer,
                "cancel": self.cancel,
                "channelDown": self.previousitem,
                "channelUp": self.nextitem,
                "down": self.previousitem,
                "up": self.nextitem,
                "back": self.cancel,
                'epg': self.showIMDB,
                "info": self.showIMDB,
            },
            -1
        )

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

        def _openForEpgText(epg_text):
            try:
                if epg_text and epg_text not in [
                        "EPG not available", "No programme found", ""]:
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
            try:
                epg_text = self.get_current_epg()
            except Exception as e:
                print('[Playstream2] Error fetching EPG for IMDb: %s' % e)
                epg_text = ""
            reactor.callFromThread(_openForEpgText, epg_text)

        epg_thread = threading.Thread(target=_fetchEpgThenOpen)
        epg_thread.setDaemon(True)
        epg_thread.start()

    def nextitem(self):
        """Switch to next channel"""
        self.stopStream(restore_original=False)
        currentindex = int(self.currentindex) + 1
        if currentindex == self.itemscount:
            currentindex = 0
        self.currentindex = currentindex
        i = self.currentindex
        item = self.list[i][0]
        self.name = item[0]
        self.url = item[1]
        self.startStream()

    def previousitem(self):
        """Switch to previous channel"""
        self.stopStream(restore_original=False)
        currentindex = int(self.currentindex) - 1
        if currentindex < 0:
            currentindex = self.itemscount - 1
        self.currentindex = currentindex
        i = self.currentindex
        item = self.list[i][0]
        self.name = item[0]
        self.url = item[1]
        self.startStream()

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
        self.end = True
        self._handleEofEvent("__evEOF")

    def _handleEofEvent(self, source):
        """Shared EOF bookkeeping/restart logic for doEofInternal() and
        __evEOF(), which both fire for the same underlying event."""
        current_time = time.time()

        if not hasattr(self, 'eof_count'):
            self.eof_count = 0
            self.last_eof_time = 0

        time_since_last_eof = current_time - self.last_eof_time

        # doEofInternal() and __evEOF() both fire for the same real EOF,
        # typically within the same event-loop tick - a gap this short
        # means this is the other handler for the event just processed,
        # not a second, genuinely separate EOF.
        if 0 < time_since_last_eof < 1.5:
            print(
                "[Playstream2] Ignoring duplicate EOF signal from " +
                source)
            return

        self.last_eof_time = current_time

        if time_since_last_eof < 10:  # Less than 10 seconds between EOFs
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

        # Restart based on EOF frequency
        if self.eof_count <= 3:  # Allow up to 3 quick retries
            delay = 2 + (self.eof_count * 2)  # 2, 4, 6 seconds
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

    def startStream(self, force=False):
        """Start the stream - proxy handles authentication"""
        if self.stream_running and not force:
            return

        print("[Playstream2] Starting stream: " + str(self.name))
        print("[Playstream2] URL: " + str(self.url))

        self.stream_running = True
        self.is_streaming = True

        if not force:
            # Fresh channel selection - start its EOF/retry tracking clean.
            # A force=True call is an EOF-triggered restart of the SAME
            # channel (see restartAfterEOF); eof_count must survive that,
            # or the "give up after N quick retries" limit never engages
            # since every retry would reset its own counter to 0 first.
            self.eof_count = 0
            self.last_eof_time = 0

        # Clean up URL
        if "/live2/play/" in self.url and self.url.endswith(".ts"):
            print("[Playstream2] Converting to proxy format")
            channel_id = self.url.split("/live2/play/")[1].replace(".ts", "")
            self.url = PROXY_BASE_URL + "/vavoo?channel=" + channel_id

        # Determine playback method - FIXED LOGIC
        print("[Playstream2] DEBUG URL: " + self.url)

        # Check if it's ANY proxy URL (localhost or network IP)
        if ":{}/vavoo".format(PORT) in self.url or ":{}/resolve".format(PORT) in self.url:
            print("[Playstream2] Proxy URL detected")
            self.playProxyStream(force_refresh=force)
        else:
            print("[Playstream2] Non-proxy URL, using old system")
            self.playOldSystem()

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
        """Callback to restart stream after EOF (non‑blocking)."""
        print("[Playstream2] Restarting stream after EOF")
        self.stopStream(restore_original=False)
        reactor.callLater(0.5, lambda: self.startStream(force=True))

    def get_current_epg(self):
        """
        Get current EPG program for the playing channel.
        Results are cached for 5 minutes to avoid repeated lookups.
        """
        start_time = time.time()

        try:
            if not self.country_code:
                return "EPG not available (no country code)"

            # Clean channel name for better matching
            clean_name = decodeHtml(self.name)
            clean_name = remove_parentheses(clean_name)

            # Create cache key
            cache_key = "epg_{}_{}".format(clean_name, self.country_code)

            # Check if we have cached result (5 minutes TTL)
            if cache_key in _epg_result_cache:
                cached_time, cached_result = _epg_result_cache[cache_key]
                if time.time() - cached_time < 300:  # 5 minutes
                    elapsed = time.time() - start_time
                    if elapsed > 0.05:
                        print(
                            "[EPG] Cache HIT for {} (took {:.3f}s)".format(
                                clean_name, elapsed))
                    return cached_result

            # Get matcher (singleton, already loaded)
            matcher = get_epg_matcher()

            # Find Rytec ID - this is the expensive part
            match_start = time.time()
            rytec_id, _ = matcher.find_match(
                clean_name, country_code=self.country_code)
            match_time = time.time() - match_start

            if match_time > 0.1:
                print(
                    "[EPG] Slow match for {}: {:.3f}s".format(
                        clean_name, match_time))

            if not rytec_id:
                result = "EPG not available (ID not found)"
                _cache_epg_result(cache_key, result)
                return result

            # The whole country's EPG document (all channels, potentially
            # thousands of <programme> entries across all channels/days)
            # is what's slow to fetch, parse, and scan - not any single
            # channel's lookup. Reuse a recently parsed copy, and a
            # channel->programmes index built alongside it, across
            # channels in the same country instead of re-downloading,
            # re-parsing, and re-scanning the whole thing from scratch on
            # every single channel view.
            xml_cached = _epg_xml_cache.get(self.country_code)
            if xml_cached and (time.time() - xml_cached[0] < 300):
                root, channel_index, display_name_index = (
                    xml_cached[1], xml_cached[2], xml_cached[3])
            else:
                # Build EPG URL
                epg_url = "http://{}:{}/epg/{}.xml".format(
                    PROXY_HOST, PORT, self.country_code or "")

                # Fetch XML data
                fetch_start = time.time()
                # Reduced timeout to 3 seconds
                xml_data = getUrl(epg_url, timeout=3)
                fetch_time = time.time() - fetch_start

                if fetch_time > 0.5:
                    print(
                        "[EPG] Slow fetch from {}: {:.3f}s".format(
                            epg_url, fetch_time))

                if not xml_data:
                    result = "EPG not available"
                    _cache_epg_result(cache_key, result)
                    return result

                try:
                    root = ET.fromstring(xml_data)
                except Exception as e:
                    print("[EPG] XML parsing error: {}".format(e))
                    result = "EPG parsing error"
                    _cache_epg_result(cache_key, result)
                    return result

                # Index once per document: channel id (dots stripped, to
                # match id_match()'s old comparison) -> its own programme
                # entries, so a single channel's lookup only ever scans
                # that channel's handful of entries instead of every
                # <programme> in the whole country.
                index_start = time.time()
                channel_index = {}
                for prog in root.findall('programme'):
                    prog_channel = prog.get('channel')
                    if not prog_channel:
                        continue
                    channel_index.setdefault(
                        prog_channel.replace('.', ''), []).append(prog)
                index_time = time.time() - index_start
                if index_time > 0.1:
                    print(
                        "[EPG] Slow index build: {:.3f}s ({} channels)".format(
                            index_time, len(channel_index)))

                # Secondary, display-only index: cleaned <display-name>
                # text -> channel id, used as a fallback (see below) when
                # the primary rytec_id lookup finds nothing - some
                # country feeds use their own id convention (e.g.
                # "Canal.Hollywood.HD.pt", "RTP.1.HD.pt") that diverges
                # from the separate Rytec matching database's ids for
                # the same real channel, even though this feed has
                # perfectly good programme data under its own id.
                display_name_index = {}
                for chan in root.findall('channel'):
                    chan_id = chan.get('id')
                    if not chan_id:
                        continue
                    for dn in chan.findall('display-name'):
                        dn_text = (dn.text or '').strip()
                        if not dn_text:
                            continue
                        clean_dn = matcher._clean_name_for_similarity(
                            dn_text)
                        if clean_dn:
                            display_name_index[clean_dn] = chan_id

                _cache_epg_xml(
                    self.country_code, root, channel_index,
                    display_name_index)

            # Find current programme
            parse_start = time.time()
            try:
                import calendar
                now = time.time()

                def _current_in(programmes):
                    for prog in programmes:
                        start_str = prog.get('start')
                        stop_str = prog.get('stop')
                        if not start_str or not stop_str:
                            continue
                        try:
                            # Parse dates without timezone for speed
                            start_clean = start_str.split(' ')[0]
                            stop_clean = stop_str.split(' ')[0]
                            start_dt = datetime.datetime.strptime(
                                start_clean, "%Y%m%d%H%M%S")
                            stop_dt = datetime.datetime.strptime(
                                stop_clean, "%Y%m%d%H%M%S")
                            start_ts = calendar.timegm(start_dt.timetuple())
                            stop_ts = calendar.timegm(stop_dt.timetuple())
                            if start_ts <= now <= stop_ts:
                                return prog
                        except Exception:
                            continue
                    return None

                rid_key = rytec_id.replace('.', '')
                current_prog = _current_in(channel_index.get(rid_key, []))

                # Fallback: the matched rytec_id has no coverage in this
                # feed (a different id scheme for the same real channel,
                # e.g. matcher assigns "rtp1.pt" but this feed uses
                # "RTP.1.HD.pt") - try matching this channel's own name
                # directly against the feed's <display-name> tags
                # instead. Display-only: never touches matcher.cache,
                # dvb_ref, or anything bouquet-export/satellite-EPG
                # relies on - purely a better answer for this overlay.
                if current_prog is None and display_name_index:
                    clean_for_fallback = matcher._clean_name_for_similarity(
                        clean_name)
                    if clean_for_fallback:
                        best_score = 0.0
                        best_id = None
                        sm = SequenceMatcher(None, clean_for_fallback)
                        for dn_key, dn_id in display_name_index.items():
                            sm.set_seq2(dn_key)
                            score = sm.ratio()
                            if score > best_score:
                                best_score = score
                                best_id = dn_id
                        if best_id and best_score >= matcher.similarity_threshold:
                            fallback_key = best_id.replace('.', '')
                            current_prog = _current_in(
                                channel_index.get(fallback_key, []))
                            if current_prog is not None:
                                print(
                                    "[EPG] Fallback name match: '{}' -> {} "
                                    "(score={:.2f})".format(
                                        clean_name, best_id, best_score))

                parse_time = time.time() - parse_start
                if parse_time > 0.1:
                    print("[EPG] Slow parse: {:.3f}s".format(parse_time))

                if current_prog is not None:
                    title = current_prog.findtext('title', '')
                    desc = current_prog.findtext('desc', '')

                    # Extract start/stop times for display
                    start_str = current_prog.get('start')
                    stop_str = current_prog.get('stop')

                    try:
                        start_dt = datetime.datetime.strptime(
                            start_str.split(' ')[0], "%Y%m%d%H%M%S")
                        stop_dt = datetime.datetime.strptime(
                            stop_str.split(' ')[0], "%Y%m%d%H%M%S")

                        start_local = start_dt.strftime('%H:%M')
                        end_local = stop_dt.strftime('%H:%M')

                        result = "{}-{} {} - {}".format(
                            start_local, end_local, title, desc)
                    except Exception:
                        result = "{} - {}".format(title, desc)
                else:
                    result = "No programme found"

                # Cache the result
                _cache_epg_result(cache_key, result)
                return result

            except Exception as e:
                print("[EPG] Programme matching error: {}".format(e))
                result = "EPG parsing error"
                _cache_epg_result(cache_key, result)
                return result

        except Exception as e:
            print("[EPG] Exception in get_current_epg: {}".format(e))
            trace_error()
            return "EPG error"

    def playProxyStream(self, force_refresh=False):
        """Play via proxy - token management is handled by proxy.

        force_refresh=True (an EOF-triggered retry, see restartAfterEOF)
        tells the proxy to bypass its resolve cache - reusing the same
        cached URL that just failed for up to resolve_cache_ttl would
        otherwise make every quick retry fail the exact same way.
        """
        try:
            # Extract channel ID from URL
            channel_id = None

            if "vavoo?channel=" in self.url:
                channel_id = self.url.split("vavoo?channel=")[1]

            # Clean up any extra parameters
            if channel_id and '?' in channel_id:
                channel_id = channel_id.split('?')[0]

            if not channel_id:
                print("[Playstream2] Could not extract channel ID")
                self.playOldSystem()
                return

            # Get proxy host from URL or use default
            proxy_host = "{}:{}".format(PROXY_HOST, PORT)
            if "://" in self.url:
                match = search(r'://([^/]+)', self.url)
                if match:
                    proxy_host = match.group(1)

            # Build proxy URL WITHOUT extra parameters
            proxy_url = "http://" + str(proxy_host) + \
                "/vavoo?channel=" + str(channel_id)
            if force_refresh:
                proxy_url += "&force=1"
            print("[Playstream2] Clean proxy URL: " + proxy_url)

            # Add User-Agent as fragment
            stream_url_with_ua = proxy_url + "#User-Agent=VAVOO/2.6"

            # Encode for Enigma2
            encoded_url = stream_url_with_ua.replace(":", "%3a")
            encoded_name = self.name.replace(":", "%3a")

            # Use the configured player service type ("Server for Player
            # Used" in settings - 4097/5001/5002/8193) instead of always
            # hardcoding 4097 - bouquet export already respects this
            # setting (see cfg.services.value usage there), but this
            # in-plugin player was silently ignoring it, always using
            # 4097's backend regardless of what the user picked.
            ref = (
                cfg.services.value + ":0:1:0:0:0:0:0:0:0:" +
                encoded_url +
                ":" +
                encoded_name
            )
            print("[Playstream2] Service reference: " + ref)
            sref = eServiceReference(ref)
            sref.setName(self.name)
            self.sref = sref

            try:
                proxy.stream_started()
                print("[Playstream2] Notified proxy: stream started")
            except Exception as e:
                print("[Playstream2] Failed to notify proxy: {}".format(e))

            # Play the stream
            self.session.nav.stopService()
            self.session.nav.playService(self.sref)
            print("[Playstream2] Proxy stream started successfully")

        except Exception as e:
            print("[Playstream2] playProxyStream error: " + str(e))
            # self.playOldSystem()
            # Fallback to old system
            trace_error()

    def playOldSystem(self):
        """Fallback to old playback system"""
        try:
            sig = vUtils.getAuthSignature()
            app = '?n=1&b=5&vavoo_auth=' + str(sig) + '#User-Agent=VAVOO/2.6'
            url = self.url
            if not url.startswith("http"):
                url = "http://" + url

            full_url = url + app
            ref = "{0}:0:1:0:0:0:0:0:0:0:{1}:{2}".format(
                cfg.services.value,
                full_url.replace(":", "%3a"),
                self.name.replace(":", "%3a")
            )

            print("[Playstream2] Old system ref: " + ref)

            sref = eServiceReference(ref)
            sref.setName(self.name)
            self.sref = sref
            self.session.nav.stopService()
            self.session.nav.playService(self.sref)

        except Exception as e:
            print("[Playstream2] playOldSystem error: " + str(e))
            trace_error()

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
                proxy.stream_ended()
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

    def cancel(self):
        """Close the player"""
        print("[Playstream2] Closing player...")
        self._closed = True
        self.stopStream()
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

        self.close()

    def leavePlayer(self):
        """Alternative close method"""
        self._closed = True
        self.stopStream()
        self.close()


class AutoStartTimer:
    def __init__(self):
        print("*** AutoStartTimer Vavoo ***")

        # Check if there are bouquets to update
        favorite_channel = join(PLUGIN_PATH, 'Favorite.txt')

        if not isfile(favorite_channel):
            print("[AutoStartTimer] No Favorite.txt - nothing to update")
            return  # Exit, timer not needed

        print("[AutoStartTimer] Favorite.txt found, starting timer...")

        self.timer = eTimer()
        try:
            self.timer.callback.append(self.on_timer)
        except BaseException:
            self.timer.timeout.connect(self.on_timer)

        self.timer.start(100, True)
        self.update()

    def on_timer(self):
        """Timer callback - triggered when timer expires"""
        print("[AutoStartTimer] Timer triggered")
        self.timer.stop()

        now = int(time.time())
        wake = now
        constant = 0

        if cfg.timetype.value == "fixed time":
            wake = self.get_wake_time()

        if abs(wake - now) < 60:
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
        else:
            return -1

    def update(self, constant=0):
        self.timer.stop()
        wake = self.get_wake_time()
        nowt = time.time()
        if wake > 0:
            if wake < nowt + constant:
                if cfg.timetype.value == "interval":
                    interval = int(cfg.updateinterval.value)
                    wake += interval * 60
                elif cfg.timetype.value == "fixed time":
                    wake += 86400
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
        favorite_channel = join(PLUGIN_PATH, 'Favorite.txt')
        if not isfile(favorite_channel):
            print("Favorite.txt not found - no bouquets to update")
            return

        try:
            # 1. Read bouquets
            bouquets_to_update = []
            with open(favorite_channel, 'r') as f:
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
                if not run_proxy_in_background(
                        startup_timeout=cfg.proxy_startup_timeout.value):
                    print("[AutoStartTimer] Failed to start proxy")
                    return

            # 3. Wait for proxy to be ready (max 10s total; non-blocking via
            # select)
            for i in range(10):
                if is_proxy_ready(timeout=3):
                    break
                print("[AutoStartTimer] Waiting for proxy (" + str(i + 1) + "/10)")
                select.select([], [], [], 1)

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
                    cfg.server.value,
                    cfg.list_position.value
                )

                if ch > 0:
                    successful_updates += 1
                    print("[AutoStartTimer] ✓ Updated: " +
                          name + " (" + str(ch) + " channels)")
                    _update_favorite_file(name, url, export_type)
                else:
                    print("[AutoStartTimer] ✗ Failed: " + name)

            # 5. Update timestamp and show MessageBox
            if successful_updates > 0:
                localtime = time.asctime(time.localtime(time.time()))
                cfg.last_update.value = localtime
                cfg.last_update.save()
                print("[AutoStartTimer] Updated " +
                      str(successful_updates) +
                      "/" +
                      str(len(bouquets_to_update)) +
                      " bouquets")

        except Exception as e:
            print("[AutoStartTimer] Error: " + str(e))
            import traceback
            traceback.print_exc()


delayed_start_timer = None


def delayed_boot_tasks():
    global auto_start_timer
    try:
        if cfg.proxy_enabled.value:
            # If the plugin has already been opened, do not start the proxy
            # here
            if _session is not None:
                print("[Vavoo] Plugin already opened, boot tasks skipped")
                return
            if not is_proxy_running():
                print("[Vavoo] Starting proxy at boot...")
                run_proxy_in_background(
                    startup_timeout=cfg.proxy_startup_timeout.value)
            else:
                print("[Vavoo] Proxy already running at boot")

        if cfg.autobouquetupdate.value and cfg.proxy_enabled.value:
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

        delayed_start_timer = eTimer()
        try:
            delayed_start_timer.callback.append(delayed_boot_tasks)
        except BaseException:
            delayed_start_timer.timeout.connect(delayed_boot_tasks)

        delayed_start_timer.startLongTimer(30)   # run 30 seconds after boot


def check_configuring():
    """Check for new config values for auto start"""
    if cfg.autobouquetupdate.value is True:
        if auto_start_timer is not None:
            auto_start_timer.update()
        return


def get_next_wakeup():
    return -1


def add_skin_back(bakk):
    if isfile(join(BackPath, str(bakk))):
        baknew = join(BackPath, str(bakk))
        cmd = 'cp -f ' + str(baknew) + ' ' + BackPath + '/default.png'
        os_system(cmd)
        os_system('sync')


def apply_selected_background(skin_text):
    """Point a skin's hardcoded default.png background reference at the
    actually-selected background file instead.

    add_skin_back() copies the selected image's content onto default.png
    on disk, but Enigma2 caches pixmaps by file path - re-showing a
    skin that references that same "default.png" path just returns the
    previously-cached bitmap (e.g. selecting "oktus" still visually
    shows "kiddac") until the whole GUI process restarts and re-reads
    it fresh. Referencing the real, distinctly-named file instead (e.g.
    "oktus.png") means a newly-selected background is a cache miss and
    gets loaded fresh immediately, no restart needed.
    """
    try:
        selected = join(BackPath, str(cfg.back.value) + '.png')
        if isfile(selected):
            default_path = join(BackPath, 'default.png')
            skin_text = skin_text.replace(default_path, selected)
    except Exception as e:
        print("[Background] Error applying selected background: " + str(e))
    return skin_text


def add_skin_font():
    print('**********addFont')
    from enigma import addFont
    FNT_Path = join(PLUGIN_PATH, "fonts")
    addFont(join(FNT_Path, 'Lcdx.ttf'), 'Lcdx', 100, 0)
    addFont(join(FNT_Path, 'MavenPro-Medium.ttf'), 'cvfont', 100, 0)


def cfgmain(menuid, **kwargs):
    if menuid == "mainmenu":
        return [(_('Vavoo Stream Live'), main, 'Vavoo', 11)]
    else:
        return []


def checkInternet():
    try:
        import socket
        socket.setdefaulttimeout(0.5)
        socket.socket(
            socket.AF_INET, socket.SOCK_STREAM).connect(
            ('8.8.8.8', 53))
        return True
    except BaseException:
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
        except Exception as e:
            print("Cache initialization error: %s" % str(e))
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
