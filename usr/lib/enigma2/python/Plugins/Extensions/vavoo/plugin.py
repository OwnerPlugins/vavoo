#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function

import codecs
import re
import ssl
import time
import threading
from os import listdir, unlink, remove, system as os_system
from os.path import basename, dirname, exists as file_exists, join, isfile, getsize
from json import loads
from sys import version_info
from enigma import eDVBDB
from twisted.internet import reactor

try:
    import requests
except Exception:
    requests = None

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
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryPixmapAlphaTest, MultiContentEntryText
try:
    # blends a picture's soft edges (the initials tiles' round corners)
    from Components.MultiContent import MultiContentEntryPixmapAlphaBlend
except ImportError:
    MultiContentEntryPixmapAlphaBlend = MultiContentEntryPixmapAlphaTest
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
    RT_HALIGN_CENTER,
    RT_HALIGN_LEFT,
    RT_HALIGN_RIGHT,
    RT_VALIGN_CENTER,
    eListboxPythonMultiContent,
    ePicLoad,
    eServiceReference,
    eTimer,
    gFont,
    getDesktop,
    iPlayableService,
    iServiceInformation,
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
from . import vavoo_proxy
from .vavoo_proxy import (
    run_proxy_in_background, restart_proxy_in_background, is_proxy_booting,
    GROUP_ID_PREFIX
)
from . import (
    _, __author__, __version__, __license__, export_lock, PORT,
    PLUGIN_ROOT, PROXY_HOST, PROXY_BASE_URL, PROXY_STATUS_URL,
    PROXY_COUNTRIES_URL, PROXY_REFRESH_URL, FLAG_CACHE_DIR,
    EPGIMPORT_CONF, LOG_FILE, GROUP_NAME_SEPARATORS
)
from . import PY2, PY3, vUtils
from . import vavoo_theme
from . import vavoo_store
from .bouquet_manager import (
    convert_bouquet,
    _update_favorite_file,
    reorganize_all_bouquets_position,
    remove_bouquets_by_name,
    export_bouquet_async,
    is_bouquet_exported,
    remove_favorite_entry,
    get_local_ip
)
from .vUtils import (
    debug,
    make_print,
    update_epg_sources,
    ensure_vavoo_epg_sources_enabled,
    get_proxy_status,
    cleanup_old_temp_files,
    check_remote_installer_version,
    decodeHtml,
    download_picon_online,
    ensure_str,
    fix_cache_format,
    getUrl,
    get_country_code,
    get_picon_cache_path,
    initialize_cache_with_local_flags,
    is_proxy_ready,
    is_proxy_running,
    is_remote_version_newer,
    returnIMDB,
    remove_parentheses,
    ReloadBouquets,
    strip_control_chars,
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


def url_quote(value, safe='/'):
    """Quote URL fragments in a Python 2/3 safe way. `safe` is passed
    straight through to urllib's quote() (characters left as-is)."""
    if PY2:
        value = to_text(value).encode("utf-8")
    else:
        value = to_text(value)

    return _url_quote(value, safe)


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
global HALIGN, BackPath
global screen_width

title_plug = 'Vavoo'
desc_plugin = ('..:: Vavoo by Lululla & Qu4k3 v.%s ::..' % __version__)
PLUGIN_PATH = PLUGIN_ROOT
PLUGLOGO = join(PLUGIN_PATH, 'plugin.png')
ENIGMA_PATH = get_enigma2_path()
CONFIG_FILE = resolveFilename(SCOPE_CONFIG, "settings")

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

    _update_thread = threading.Thread(target=_worker)
    _update_thread.daemon = True
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

# Box for the current channel's picon, bottom-left of the screen -
# over the stock MoviePlayer skin's own "cover" placeholder icon in
# that corner (self.skinName = 'MoviePlayer' reuses the box's own
# built-in skin section for that seek-bar/title strip, not one this
# plugin defines, so the placeholder itself can't be removed - this
# widget just draws on top of it at a higher zPosition). Width keeps
# the 3:2 aspect ratio used everywhere else in this plugin for icon
# boxes, sized up from a plain OVERLAY_HEIGHT_TOP-based box (too
# small next to the stock icon) to stand out as the main icon there.
OVERLAY_PICON_H = int(OVERLAY_HEIGHT_TOP * 1.8)
OVERLAY_PICON_W = int(OVERLAY_PICON_H * 1.5)
SCREEN_HEIGHT = screen_real.height()
OVERLAY_PICON_X = 10
# Position is a best-effort estimate (proportional to the real screen
# height so it scales across resolutions), calibrated from an
# on-screen photo: the first attempt (plain SCREEN_HEIGHT * 0.78, no
# extra offset) rendered about one icon-height too high - visibly
# stacked above the stock placeholder icon instead of over it -
# shifted down by that same amount (OVERLAY_HEIGHT_TOP, the old,
# smaller icon's own height) to compensate. Still an estimate, not a
# measurement - nudge it further if it's still not aligned.
OVERLAY_PICON_Y = int(SCREEN_HEIGHT * 0.78) + OVERLAY_HEIGHT_TOP

print('folder back: ', BackPath)

# Desktop width the theme skins are built for (vavoo_theme.py): the
# same three sizes as the Classic skins picked above, so that the
# pictures drawn for them (make_theme_assets.py) fit to the pixel.
if screen_width == 2560:
    THEME_WIDTH = 2560
elif screen_width >= 1920:
    THEME_WIDTH = 1920
else:
    THEME_WIDTH = 1280
IS_DREAMOS = isfile('/var/lib/dpkg/status')


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
class ConfigAction(ConfigSelection):
    """A config-list entry with a single, fixed choice, so left/right
    can't cycle it - used purely as a "press OK to trigger an action"
    row (gnm3u()'s dispatch below only checks which row is
    highlighted, never this value) instead of a Yes/No toggle that
    looks like a real setting but never actually gates anything.

    The choice's description is a plain, non-empty "OK" rather than an
    empty string - an earlier version used choices=[""] specifically
    to show a blank value column, but an empty-text list cell can fail
    to fully repaint over whatever the previous row (or a prior state
    of this one) had drawn there, visibly leaving old text showing
    through on real hardware. A short, fixed, always-the-same-length
    label repaints cleanly and still doesn't look like an actual
    setting."""

    def __init__(self):
        ConfigSelection.__init__(self, choices=[("ok", _("OK"))])


config.plugins.vavoo = ConfigSubsection()
cfg = config.plugins.vavoo
cfg.autobouquetupdate = ConfigEnableDisable(default=False)
cfg.genm3u = NoSave(ConfigAction())
cfg.show_log = NoSave(ConfigAction())
cfg.view_favourites = NoSave(ConfigAction())
cfg.choose_countries = NoSave(ConfigAction())
cfg.parental = NoSave(ConfigAction())
cfg.reminders = NoSave(ConfigAction())
cfg.backup = NoSave(ConfigAction())
cfg.restore = NoSave(ConfigAction())
cfg.clear_favourites = NoSave(ConfigAction())
cfg.licences = NoSave(ConfigAction())
cfg.about = NoSave(ConfigAction())
# Which catalog/stream source vavoo_proxy.py's initialize_proxy()
# tries - "auto" keeps its default Geil-first/Vavoo-fallback
# order; "geil"/"vavoo" pin it to exactly one source, with no
# fallback to the other if it fails (an explicit choice is respected
# as-is). Read directly by vavoo_proxy.py via its own e2_config
# import, not this cfg reference (that would be a circular import).
cfg.catalog_source = ConfigSelection(
    default="auto",
    choices=[
        # (short: the description says what Auto does - a long value
        # runs into the option's name in the settings list)
        ("auto", _("Auto")),
        ("geil", _("Geil only")),
        ("vavoo", _("Vavoo/Kool only")),
    ])
cfg.services = ConfigSelection(default='4097', choices=modemovie)
cfg.epg_enabled = ConfigEnableDisable(default=False)
# The Now/Next panel beside the channel list - see NowNextPanel.
cfg.list_epg = ConfigYesNo(default=True)
cfg.timetype = ConfigSelection(
    default="interval", choices=[
        ("interval", _("interval")), ("fixed time", _("fixed time"))])
cfg.updateinterval = ConfigSelectionNumber(
    default=360, min=5, max=3600, stepwidth=5)
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
# The look of the plugin's screens (vavoo_theme.py): Prism, Halo and
# Orbit are the Android app's own themes, Classic is this plugin's
# original skin (skin/{hd,fhd,wqhd}/*.xml, unchanged - and what every
# screen falls back to if a theme cannot be used). "Select Background"
# (cfg.back) only applies to Classic: each theme has its own.
cfg.theme = ConfigSelection(
    default=vavoo_theme.DEFAULT_THEME,
    choices=[
        ("prism", "Prism"),
        ("halo", "Halo"),
        ("orbit", "Orbit"),
        ("classic", _("Classic")),
    ])
cfg.text_size = ConfigSelection(
    default="large",
    choices=[("large", _("Large")), ("normal", _("Normal"))])
cfg.show_counts = ConfigYesNo(default=True)
cfg.clock_format = ConfigSelection(
    default="24",
    choices=[("24", _("24 hours")), ("12", _("12 hours"))])
# OK on a channel plays it in the list's small window first (OK again:
# full screen), as in the app - see _NowPlaying.
cfg.preview_window = ConfigYesNo(default=True)
# Open the last watched channel when the plugin starts (the app's
# "Start with last channel").
cfg.start_last = ConfigYesNo(default=False)
cfg.list_position = ConfigSelection(
    default="bottom",
    choices=[("bottom", _("Bottom")), ("top", _("Top"))]
)
cfg.playlist_key = ConfigText(default="")
# The app's list settings: several sources of one channel in one row;
# a country's catalog categories ("Italy ➾ Sport") as rows first.
cfg.group_sources = ConfigYesNo(default=True)
# The channels' logos in the lists and the player (the app's "Channel
# Logos", off): off, a theme shows each channel's initials on a tile of
# its own colour, and no logo is downloaded.
cfg.logos = ConfigYesNo(default=False)
cfg.subcategories = ConfigYesNo(default=True)
# "Choose countries" opened by itself once, on a first start (see
# MainVavoo._maybe_first_run()).
cfg.countries_asked = ConfigYesNo(default=False)
cfg.parental_pin = ConfigText(default="")
cfg.parental_countries = ConfigText(default="")
cfg.proxy_startup_timeout = ConfigSelectionNumber(
    default=120, min=15, max=300, stepwidth=5)


def _move_data_out_of_plugin_folder():
    """The favourites and the bouquet list used to live in the plugin
    folder, which every update deletes: moved to ENIGMA_PATH once
    (vavoo_store.migrate_old_files(); installer.sh and CONTROL/preinst
    copy them there too, before they delete the folder)."""
    try:
        for path in vavoo_store.migrate_old_files():
            print("[vavoo] Moved to {}".format(path))
    except Exception as e:
        print("[vavoo] Data not moved: {}".format(e))


_move_data_out_of_plugin_folder()

# MainVavoo's proxy_monitor_timer/proxy_watchdog_timer are created and
# restarted from three different places (initial open, returning from
# config, returning from Playstream2) - use one shared constant per
# timer everywhere instead of separate literals, which had drifted out
# of sync with each other (and with their own "every N seconds"
# comments) at two of those six call sites.
PROXY_MONITOR_INTERVAL_MS = 10000
PROXY_WATCHDOG_INTERVAL_MS = 60000

# How many times vavoo.cat() asks the proxy for a country's channel
# list before reporting failure - see its own docstring.
CHANNEL_FETCH_ATTEMPTS = 3


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


# ---------------------------------------------------------------------
# Themes (vavoo_theme.py)
# ---------------------------------------------------------------------
def current_theme():
    return vavoo_theme.normalize_theme(cfg.theme.value)


def large_text():
    return cfg.text_size.value != "normal"


def clock_24():
    return cfg.clock_format.value != "12"


def read_classic_skin(filename, cvs=False, background=True):
    """One of the Classic skin files for this resolution (the DreamOS
    "_cvs" twin when `cvs` and running on DreamOS), with the chosen
    background put in when `background`."""
    path = join(skin_path, filename)
    if cvs and IS_DREAMOS:
        path = path.replace('.xml', '_cvs.xml')
    with codecs.open(path, "r", encoding="utf-8") as f:
        text = f.read()
    return apply_selected_background(text) if background else text


# Every file a built skin points at: if one is missing (a copy of the
# plugin without skin/themes/, say), the theme is not used at all.
_SKIN_FILE_RE = re.compile(r'(?:pixmap|selectionPixmap)="([^"]+)"')
_theme_skin_cache = {}


def _theme_font_files(theme):
    look = vavoo_theme.LOOKS[theme]
    return [join(PLUGIN_PATH, "fonts", look[key][1])
            for key in ("font", "font_bold")]


def _build_skin(kind, theme, kwargs):
    try:
        text = vavoo_theme.BUILDERS[kind](
            theme, large_text(), THEME_WIDTH, base_dir=PLUGIN_PATH, **kwargs)
    except Exception as e:
        print("[Theme] Building the {} screen of {} failed: {}".format(
            kind, theme, e))
        return None
    if not text:
        return None
    missing = [path for path in _SKIN_FILE_RE.findall(text)
               if not isfile(path)]
    missing.extend(path for path in _theme_font_files(theme)
                   if not isfile(path))
    if missing:
        print("[Theme] {} not used for the {} screen, missing: {}".format(
            theme, kind, ", ".join(missing[:3])))
        return None
    return text


def build_theme_skin(kind, **kwargs):
    """The skin of a `kind` of screen (vavoo_theme.BUILDERS) in the
    chosen theme, or None: Classic chosen, or the theme cannot be used
    - then the caller loads its Classic XML.

    All or nothing: if the list screen's skin cannot be built, no
    screen uses the theme, so a themed list never ends up inside a
    Classic screen or the other way round. Built once per set of
    settings (theme, text size, clock...) and kept."""
    theme = current_theme()
    if not vavoo_theme.is_modern(theme):
        return None
    key = (kind, theme, large_text(), tuple(sorted(kwargs.items())))
    if key not in _theme_skin_cache:
        text = None
        if kind == "list" or build_theme_skin("list") is not None:
            text = _build_skin(kind, theme, kwargs)
        _theme_skin_cache[key] = text
    return _theme_skin_cache[key]


def theme_active():
    """True when the screens are drawn by a modern theme (chosen, and
    all its files there)."""
    return build_theme_skin("list") is not None


def load_screen_skin(kind, classic_file, cvs=False, background=True,
                     **kwargs):
    """(skin text, themed) for a screen: the theme's, or the Classic
    file when there is no theme (themed = False)."""
    text = build_theme_skin(kind, **kwargs)
    if text:
        return text, True
    return read_classic_skin(classic_file, cvs, background), False


# Icons of the rows, already scaled to the theme's icon box. Flags and
# picons come in all sizes and MultiContentEntryPixmapAlphaTest does not
# scale - so each is decoded to size once and kept, instead of once
# per row every time a list is drawn again.
_icon_cache = {}
_ICON_CACHE_MAX = 300


def scaled_icon(path, width, height):
    """The picture at `path` scaled to fit width x height (aspect
    kept, transparent around it), or None."""
    key = (path, width, height)
    pixmap = _icon_cache.get(key)
    if pixmap is not None:
        return pixmap
    try:
        picload = ePicLoad()
        av_scale = AVSwitch().getFramebufferScale()
        picload.setPara([width, height, av_scale[0], av_scale[1], 0, 1,
                         '#00000000'])
        if IS_DREAMOS:
            picload.startDecode(path, False)
        else:
            picload.startDecode(path, 0, 0, False)
        pixmap = picload.getData()
    except Exception as e:
        debug("Icon decode failed for {}: {}".format(path, e))
        pixmap = None
    if pixmap is not None:
        if len(_icon_cache) >= _ICON_CACHE_MAX:
            _icon_cache.clear()
        _icon_cache[key] = pixmap
    return pixmap


def theme_metrics(kind="list"):
    """vavoo_theme.list_metrics() for the chosen theme and settings."""
    return vavoo_theme.list_metrics(
        current_theme(), large_text(), THEME_WIDTH, kind)


def programme_time(timestamp):
    """A programme's start the app's way: "20:30" or "8:30 PM" (the
    clock setting), with the weekday in front when it is not today."""
    moment = time.localtime(timestamp)
    if clock_24():
        text = time.strftime("%H:%M", moment)
    else:
        text = time.strftime("%I:%M %p", moment).lstrip("0")
    today = time.localtime()
    if (moment.tm_yday, moment.tm_year) != (today.tm_yday, today.tm_year):
        text = time.strftime("%a ", moment) + text
    return text


# What the rows of the main list that open the Favourites and the
# recently watched channels link to (a country row links to its
# country name).
FAVOURITES_ROW = "__vavoo_favourites__"
RECENT_ROW = "__vavoo_recent__"
REMINDERS_ROW = "__vavoo_reminders__"


def info_text(channels=None, countries=None):
    """The app's INFO message: version, channels and countries."""
    parts = ["Vavoo Stream Live · V.{}".format(__version__)]
    if channels:
        parts.append(_("{} channels").format(channels))
    if countries:
        parts.append(_("{} countries").format(countries))
    return " · ".join(parts)


# menulist
class m2list(MenuList):
    def __init__(self, items, kind="list", themed=None):
        super(m2list, self).__init__(items, False, eListboxPythonMultiContent)
        if themed is None:
            themed = theme_active()
        if themed:
            # The theme's rows: as many whole rows as the list holds
            # (vavoo_theme.list_metrics()).
            metrics = theme_metrics(kind)
            item_height = metrics["row_h"]
            font_name = metrics["font"]
            text_font_size = metrics["font_size"]
            # the initials on a channel's tile (show_list()): two
            # letters / one letter, as the app's Monogram sizes them
            side = metrics["icon_h"]
            self.l.setFont(1, gFont(metrics["font_bold"],
                                    max(8, int(side * 0.42))))
            self.l.setFont(2, gFont(metrics["font_bold"],
                                    max(8, int(side * 0.55))))
        elif screen_width == 2560:
            item_height = 60
            text_font_size = 38
            font_name = 'Regular'
        elif screen_width == 1920:
            item_height = 50
            text_font_size = 34
            font_name = 'Regular'
        else:
            item_height = 50
            text_font_size = 22
            font_name = 'Regular'
        self.item_height = item_height
        self.l.setItemHeight(item_height)
        self.l.setFont(0, gFont(font_name, text_font_size))

    def buildEntry(self, entry):
        """Build list entry - entry should be [ (name, link), icon, text ]"""
        return entry


def list_page_rows(widget, themed):
    """Rows a list shows at once (a page): the theme's whole rows, or
    the Classic list's height shared by its row height."""
    if themed:
        return max(1, theme_metrics("list")["rows"])
    try:
        height = widget.instance.size().height()
        return max(1, int(height // widget.item_height))
    except Exception:
        return 10


def show_list(name, link, is_category=False, is_channel=False, logo_url=None,
              display=None, kind="list", themed=None, value=None, dim=False,
              value_icon=False, no_icon=False):
    """Build a MultiContent entry with icon and text.

    The entry's first item is always (name, link); `display` is what
    the row shows instead of the name, when it differs (a country with
    its channel count). `kind` / `themed`: the list it goes into (see
    m2list). `value`: a short text at the row's right end (✓ / ✗ in
    Choose countries); `dim`: greyed out (a hidden country);
    `value_icon`: a padlock at the row's right end (a locked country);
    `no_icon`: text only (an option row of Parental Control)."""

    safe_name = to_string(name)
    safe_link = to_string(link)
    if themed is None:
        themed = theme_active()

    res = [(safe_name, safe_link)]

    # Default icon
    default_icon = join(PLUGIN_PATH, 'skin/pics/vavoo_ico.png')
    icon_path = default_icon

    using_channel_picon = False
    if is_channel and logo_url and cfg.logos.value:
        # Same convention as the flag icon below: only ever read the
        # cache here, never download synchronously inside this
        # function (called once per row while building a possibly
        # large list) - a channel's picon shows up once
        # _preload_channel_picons() has actually fetched it and
        # rebuilt the list, same lag the flag icons already have for
        # countries.
        try:
            cache_file = get_picon_cache_path(logo_url)
            if cache_file and file_exists(cache_file):
                if getsize(cache_file) > 100:
                    icon_path = cache_file
                    using_channel_picon = True
                else:
                    unlink(cache_file)
        except Exception as e:
            debug("Picon cache check failed for {}: {}".format(
                logo_url, e))

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

    # icon_size used to be a flat (60, 40) at every resolution tier,
    # regardless of each tier's own item_height (m2list.__init__) -
    # 80% of the row height on the fhd/hd tiers, 66.7% on wqhd, and
    # visually dominant enough that channel/flag icons looked like the
    # main content instead of a small marker next to the name. A
    # follow-up pass pushed this down further to ~40% of item_height,
    # which went too far the other way: at that size even the plain
    # default icon (not just a detailed channel logo) rendered as an
    # indistinct blob, confirmed from an on-screen photo - a real
    # channel logo (unlike the bundled flags, simple bold national
    # flag art that stays legible even very small) needs more pixels
    # than that to read as anything at all. Settled at ~60% of
    # item_height instead - the one size in this box's history that
    # hasn't actually been shown broken - keeping the same 3:2 aspect
    # ratio the bundled flag PNGs (skin/cowntry/*.png, all exactly
    # 60x40) are already hand-cropped to, so they keep scaling
    # uniformly with zero distortion, and vertically centered in the
    # row ((item_height - icon_height) // 2) rather than the old
    # fixed y-offsets, which were tuned for the original, taller box.
    if themed:
        # The app's rows (SkinList): the icon 4/5 of the row high, 3:2,
        # vertically centred; the text after it.
        metrics = theme_metrics(kind)
        icon_size = (metrics["icon_w"], metrics["icon_h"])
        icon_pos = (metrics["icon_x"], metrics["icon_y"])
        text_size = (metrics["text_w"], metrics["row_h"])
        text_pos = (metrics["text_x"], 0)
    elif screen_width >= 2560:
        icon_size = (54, 36)
        icon_pos = (10, 12)
        text_size = (750, 60)
        text_pos = (icon_size[0] + 20, 0)
    elif screen_width >= 1920:
        icon_size = (45, 30)
        icon_pos = (10, 10)
        text_size = (540, 50)
        text_pos = (icon_size[0] + 20, 0)
    else:
        icon_size = (45, 30)
        icon_pos = (10, 10)
        text_size = (380, 50)
        text_pos = (icon_size[0] + 20, 0)

    # Load the icon pixmap, already sized correctly for icon_size.
    #
    # Channel picons are cached at whatever native resolution the
    # third-party catalog serves them - unlike the default icon and
    # the bundled flags (both pre-sized to match icon_size exactly),
    # MultiContentEntryPixmapAlphaTest does NOT scale a mismatched
    # source to fit its size= box - it blits the image at its own
    # native resolution, clipped to that box. A same-size-or-larger
    # picon therefore only ever showed a small corner fragment of
    # itself (confirmed from an on-screen photo: mostly blank, with a
    # sliver of the real logo in one corner) - the earlier fix here
    # that computed a smaller pos/size never actually fixed anything,
    # since nothing was scaling the pixel data to match it either way.
    # ePicLoad actually resamples the source to the target size
    # (letterboxed, aspect-preserving - see setPara()'s own comment
    # below) before handing back a pixmap that's already the right
    # size - the same mechanism this file's own splash screen
    # (startVavoo.decodeImage()) and the playback overlay
    # (_update_overlay_picon()) already use for exactly this reason.
    png_data = None
    if themed:
        # Every icon scaled to the theme's box (the flags and the
        # default icon too - they are drawn for Classic's smaller box),
        # each decoded once (scaled_icon()'s cache).
        png_data = scaled_icon(icon_path, icon_size[0], icon_size[1])
        if png_data is None and icon_path != default_icon:
            png_data = scaled_icon(default_icon, icon_size[0], icon_size[1])
    elif using_channel_picon:
        try:
            picload = ePicLoad()
            av_scale = AVSwitch().getFramebufferScale()
            # Same setPara()/startDecode() shape as
            # startVavoo.decodeImage()/_update_overlay_picon() -
            # resize_mode=1 scales to fit while preserving aspect
            # ratio, padded with the given transparent background,
            # rather than mode=0 (plain stretch).
            picload.setPara([
                icon_size[0], icon_size[1],
                av_scale[0], av_scale[1], 0, 1, '#00000000'])
            if isfile("/var/lib/dpkg/status"):
                picload.startDecode(icon_path, False)
            else:
                picload.startDecode(icon_path, 0, 0, False)
            png_data = picload.getData()
        except Exception as e:
            debug("Picon decode failed for {}: {}".format(icon_path, e))
            png_data = None

    if not png_data and not themed:
        # Either not a channel picon (default icon / country flag,
        # both already pre-sized to exactly icon_size - no scaling
        # needed) or the decode above failed - either way, fall back
        # to a plain, un-scaled load of whichever asset is safe to
        # load natively at this size (never the oversized picon file
        # itself, which would reintroduce the clipping problem above).
        fallback_path = default_icon if using_channel_picon else icon_path
        try:
            png_data = loadPNG(fallback_path)
        except Exception:
            try:
                png_data = loadPNG(default_icon)
            except Exception:
                png_data = None

    if themed and is_channel and not using_channel_picon:
        # No logo (or Channel Logos off): the channel's initials on a
        # rounded tile of its own colour, square in the icon box (the
        # app's Monogram; vavoo_store draws the tile once per colour).
        side = icon_size[1]
        tile = None
        try:
            tile = vavoo_store.tile_path(safe_name, side)
        except Exception as e:
            debug("Initials tile not drawn: {}".format(e))
        tile_png = scaled_icon(tile, side, side) if tile else None
        if tile_png is not None:
            png_data = None
            tile_pos = (icon_pos[0] + (icon_size[0] - side) // 2, icon_pos[1])
            letters = vavoo_store.initials(safe_name)
            res.append(MultiContentEntryPixmapAlphaBlend(
                pos=tile_pos, size=(side, side), png=tile_png))
            res.append(MultiContentEntryText(
                pos=tile_pos, size=(side, side),
                font=1 if len(letters) > 1 else 2,
                text=to_string(letters),
                flags=RT_HALIGN_CENTER | RT_VALIGN_CENTER,
                color=0xffffff, color_sel=0xffffff))

    if no_icon:
        png_data = None
        if themed:
            metrics = theme_metrics(kind)
            right = text_pos[0] + text_size[0]
            text_pos = (metrics["plain_x"], 0)
            text_size = (right - metrics["plain_x"], text_size[1])

    if png_data:
        res.append(MultiContentEntryPixmapAlphaTest(
            pos=icon_pos,
            size=icon_size,
            png=png_data
        ))

    colours = {}
    if dim:
        colours = {"color": 0x7a7a86, "color_sel": 0xb0b0b8}
    if value_icon:
        # the padlock, white, a little over half the row high, at the
        # right end (drawn once by vavoo_store)
        lock_h = max(8, int(text_size[1] * 0.56))
        lock_w = max(6, int(round(lock_h * 0.75)))
        lock_png = None
        try:
            lock = vavoo_store.lock_path(lock_h)
            if lock:
                lock_png = scaled_icon(lock, lock_w, lock_h) if themed \
                    else loadPNG(lock)
        except Exception as e:
            debug("Padlock not drawn: {}".format(e))
        if lock_png is not None:
            res.append(MultiContentEntryPixmapAlphaBlend(
                pos=(text_pos[0] + text_size[0] - lock_w,
                     text_pos[1] + (text_size[1] - lock_h) // 2),
                size=(lock_w, lock_h), png=lock_png))
            if value is None:
                text_size = (text_size[0] - lock_w - 10, text_size[1])
    if value is not None:
        # the value's column: three row heights at the right end
        value_w = min(text_size[1] * 3, text_size[0] // 2)
        res.append(MultiContentEntryText(
            pos=(text_pos[0] + text_size[0] - value_w, text_pos[1]),
            size=(value_w, text_size[1]),
            font=0,
            text=to_string(value),
            flags=RT_HALIGN_RIGHT | RT_VALIGN_CENTER, **colours))
        text_size = (text_size[0] - value_w - 10, text_size[1])
    res.append(MultiContentEntryText(
        pos=text_pos,
        size=text_size,
        font=0,
        text=to_string(display) if display is not None else safe_name,
        flags=HALIGN | RT_VALIGN_CENTER, **colours
    ))

    return list(res)


def menu_row(label, kind="menu"):
    """A row of a theme's action menu (VavooMenu): text only."""
    metrics = theme_metrics(kind)
    text = to_string(label)
    return [
        (text, None),
        MultiContentEntryText(
            pos=(metrics["plain_x"], 0),
            size=(metrics["plain_w"], metrics["row_h"]),
            font=0, text=text, flags=RT_HALIGN_LEFT | RT_VALIGN_CENTER),
    ]


class VavooMenu(Screen):
    """The MENU key's list of actions in a modern theme - the app's
    PickerPopup. Closes with the chosen entry's key, or None."""

    def __init__(self, session, title, entries, layout="menu"):
        Screen.__init__(self, session)
        # "menu": the popup in the middle; "player_menu": the player's
        # options in the left panel over the video, as in the app
        # (its rows are the channel list's).
        self.skin = build_theme_skin(layout) or build_theme_skin("menu")
        self._row_kind = "list" if layout == "player_menu" else "menu"
        self.entries = list(entries)
        self["title"] = Label(to_string(title))
        self["menulist"] = m2list([], kind=self._row_kind, themed=True)
        self["actions"] = ActionMap(
            ["OkCancelActions", "DirectionActions"],
            {
                "ok": self.ok,
                "cancel": self.cancel,
                "up": self.move_up,
                "down": self.move_down,
                "left": self.page_up,
                "right": self.page_down,
            }, -1)
        self.onLayoutFinish.append(self._fill)

    def _fill(self):
        self["menulist"].l.setList(
            [menu_row(label, self._row_kind) for label, _key in self.entries])

    def ok(self):
        index = self["menulist"].getSelectedIndex()
        if index is not None and 0 <= index < len(self.entries):
            self.close(self.entries[index][1])
        else:
            self.close(None)

    def cancel(self):
        self.close(None)

    def move_up(self):
        if self.entries:
            index = self["menulist"].getSelectedIndex() or 0
            self["menulist"].moveToIndex((index - 1) % len(self.entries))

    def move_down(self):
        if self.entries:
            index = self["menulist"].getSelectedIndex() or 0
            self["menulist"].moveToIndex((index + 1) % len(self.entries))

    def page_up(self):
        self["menulist"].pageUp()

    def page_down(self):
        self["menulist"].pageDown()


def open_action_menu(session, title, entries, on_choice, layout="menu"):
    """The MENU key's actions: `entries` = [(label, key)], on_choice(key)
    once one is picked. The theme's own popup in a modern theme
    (`layout` "player_menu": the player's left panel), Enigma2's
    ChoiceBox in Classic."""
    def _picked(key):
        if key is not None:
            on_choice(key)

    if build_theme_skin("menu") is not None:
        session.openWithCallback(_picked, VavooMenu, title, entries, layout)
        return
    from Screens.ChoiceBox import ChoiceBox
    session.openWithCallback(
        lambda result: _picked(result[1] if result else None),
        ChoiceBox, title=to_string(title),
        list=[(to_string(label), key) for label, key in entries])


# ---------------------------------------------------------------------
# Now / Next panel (channel list, Favourites)
# ---------------------------------------------------------------------
# The four labels defaultListScreen.xml declares to the right of the
# preview window. Every screen that loads that skin file has to own
# all four, used or not: a <widget name="..."> with no matching
# self["..."] is a skin error on current images and a crash
# ("component with name ... was not found in skin of screen") on
# older ones.
EPG_PANEL_WIDGETS = (
    "epg_now_time", "epg_now_title", "epg_next_time", "epg_next_title")
# How long the highlight has to rest on a row before its programme is
# looked up - holding UP/DOWN runs through rows much faster than this,
# and none of those should cost a lookup.
EPG_PANEL_SETTLE_MS = 350
# How often a filled panel is looked at again, so that it moves on
# when the programme ends. Answered from memory, no network.
EPG_PANEL_REFRESH_MS = 60000


def add_epg_panel_labels(screen):
    """Give `screen` the (empty) Now/Next labels its skin declares."""
    for widget in EPG_PANEL_WIDGETS:
        screen[widget] = Label("")


def add_key_hint_labels(screen):
    """The MENU and INFO key hints a theme's list skin draws (Classic's
    backgrounds have them painted in). Every screen that loads the
    list skin owns both, as with the Now/Next labels."""
    screen['key_menu'] = Label("MENU")
    screen['key_info'] = Label("i")


def set_notification_theme():
    """Messages at the top of the screen in the chosen theme (None:
    the notification bar's own Classic look)."""
    try:
        set_notify_skin(build_theme_skin("notify"))
    except Exception as e:
        debug("Notification theme not applied: {}".format(e))


def _epg_channel_id(url):
    """The channel id in a proxy stream address, the way the player
    overlay has always handed it to find_match() (still URL-quoted:
    there it only goes into a service reference nobody keeps), or
    None if `url` is not such an address."""
    if not url or "vavoo?channel=" not in url:
        return None
    channel_id = url.split("vavoo?channel=")[1]
    if '?' in channel_id:
        channel_id = channel_id.split('?')[0]
    return channel_id or None


class NowNextPanel(object):
    """Mixed into a list screen: shows what is on the highlighted
    channel now and what follows, in the EPG_PANEL_WIDGETS labels.

    The screen supplies _epg_panel_selection(), calls
    _epg_panel_init() once while building its widgets,
    _epg_panel_changed() whenever the highlighted row may have
    changed and _epg_panel_stop() when it closes, and sets
    self._closed on closing.

    Nothing here makes the GUI thread wait. A row whose answer is
    already in memory (vUtils.peek_now_next()) is drawn at once.
    Anything else waits EPG_PANEL_SETTLE_MS for the highlight to stop
    moving, then goes to one background thread - never more than one
    per screen, and it only ever works on the latest row asked for,
    so scrolling through a list while a guide is still downloading
    cannot pile up threads or downloads. An answer is only drawn if
    its row is still the highlighted one.
    """

    def _epg_panel_init(self):
        add_epg_panel_labels(self)
        # The row the panel is about: (name, url, country code), drawn
        # or still being looked up. None = nothing to show.
        self._epg_panel_row = None
        self._epg_panel_lock = threading.Lock()
        # Next row for the background thread (latest wins).
        self._epg_panel_wanted = None
        self._epg_panel_working = False
        self._epg_panel_timer = eTimer()
        try:
            self._epg_panel_timer.callback.append(self._epg_panel_tick)
        except Exception:
            self._epg_panel_timer.timeout.connect(self._epg_panel_tick)
        try:
            self.onExecBegin.append(self._epg_panel_resume)
        except Exception as e:
            debug("Now/Next: no onExecBegin hook: {}".format(e))

    def _epg_panel_selection(self):
        """(channel name, stream url, country code) of the highlighted
        row, or None when there is nothing to look up. Supplied by the
        screen."""
        return None

    def _epg_panel_country(self):
        """The highlighted channel's country (for parental control)."""
        return getattr(self, 'country_name', None)

    def _epg_panel_changed(self):
        """The highlighted row may have changed."""
        if getattr(self, '_closed', False):
            return
        request = None
        if cfg.list_epg.value:
            try:
                request = self._epg_panel_selection()
            except Exception as e:
                debug("Now/Next: reading the selection failed: {}".format(e))
        if request is not None and request == self._epg_panel_row:
            # Same row announced again (the list was rebuilt once its
            # picons arrived): whatever is shown or under way stands.
            return
        self._epg_panel_row = request
        self._epg_panel_timer.stop()
        if request is None:
            self._epg_panel_show("", "", "", "")
            return
        try:
            locked = vavoo_store.needs_pin_for_channel(
                request[0], self._epg_panel_country())
        except Exception:
            locked = False
        if locked:
            # a channel that needs the PIN shows no programme (the app)
            self._epg_panel_show("", _("Locked"), "", "")
            return
        answer = self._epg_panel_peek(request)
        if answer is not None:
            self._epg_panel_draw(answer)
            self._epg_panel_timer.start(EPG_PANEL_REFRESH_MS, True)
            return
        # Never leave the previous channel's programme standing under
        # a different channel's name while this one is looked up.
        self._epg_panel_show("", "", "", "")
        self._epg_panel_timer.start(EPG_PANEL_SETTLE_MS, True)

    def _epg_panel_resume(self):
        """This screen is on top again (first shown, or back from the
        player, the settings or a message box)."""
        if getattr(self, '_closed', False):
            return
        if self._epg_panel_row is None:
            # e.g. the setting was just switched on in the settings.
            self._epg_panel_changed()
        elif not self._epg_panel_timer.isActive():
            self._epg_panel_timer.start(EPG_PANEL_SETTLE_MS, True)

    def _epg_panel_peek(self, request):
        try:
            return vUtils.peek_now_next(request[0], request[2])
        except Exception as e:
            debug("Now/Next: peek failed: {}".format(e))
            return None

    def _epg_panel_tick(self):
        """The highlight has rested long enough on a row that still
        needs looking up - or it is time to look again at a row
        already shown."""
        if getattr(self, '_closed', False):
            return
        request = self._epg_panel_row
        if request is None:
            return
        if not cfg.list_epg.value:
            self._epg_panel_row = None
            self._epg_panel_show("", "", "", "")
            return
        if not getattr(self, 'execing', True):
            # Another screen is on top (the player, a message box).
            # Nothing is looked up for a list nobody is looking at -
            # above all, no guide download while a stream is playing.
            # _epg_panel_resume() picks this up again.
            return
        answer = self._epg_panel_peek(request)
        if answer is not None:
            self._epg_panel_draw(answer)
            self._epg_panel_timer.start(EPG_PANEL_REFRESH_MS, True)
            return
        if vUtils.peek_epg_guide(request[2]) is None:
            # The slow case: this country's guide has to be downloaded
            # first. Matching one more channel against a guide already
            # in memory takes a moment at most - no message for that.
            self._epg_panel_show(
                "", _("Loading programme guide..."), "", "")
        with self._epg_panel_lock:
            self._epg_panel_wanted = request
            start_worker = not self._epg_panel_working
            if start_worker:
                self._epg_panel_working = True
        if start_worker:
            worker = threading.Thread(target=self._epg_panel_work)
            worker.daemon = True
            worker.start()

    def _epg_panel_work(self):
        """Background thread: answer the latest row asked for, until
        there is none left."""
        while True:
            with self._epg_panel_lock:
                request = self._epg_panel_wanted
                self._epg_panel_wanted = None
                if request is None or getattr(self, '_closed', False):
                    self._epg_panel_working = False
                    return
            try:
                answer = vUtils.lookup_now_next(
                    request[0], request[2],
                    channel_id=_epg_channel_id(request[1]))
            except Exception as e:
                debug("Now/Next: lookup failed: {}".format(e))
                answer = ("no_guide", None, None)
            if not getattr(self, '_closed', False):
                reactor.callFromThread(
                    self._epg_panel_arrived, request, answer)

    def _epg_panel_arrived(self, request, answer):
        """Back on the GUI thread with the background thread's answer."""
        if getattr(self, '_closed', False) or request != self._epg_panel_row:
            # Closed meanwhile, or the highlight has moved on (that
            # row has its own lookup under way).
            return
        self._epg_panel_draw(answer)
        self._epg_panel_timer.start(EPG_PANEL_REFRESH_MS, True)

    def _epg_panel_draw(self, answer):
        status, current, following = answer
        now_time = now_title = next_time = next_title = ""
        if getattr(self, '_themed', False):
            # The app's two lines under the preview window (its
            # epgText()): "▶ 20:00  Title" and "» 21:00  Title". The
            # theme skin keeps the two time labels one pixel big.
            if status != "no_country":
                if current is not None:
                    now_title = u"▶ {}  {}".format(
                        to_text(programme_time(current[0])), to_text(current[2]))
                else:
                    now_title = _("No programme information")
                if following is not None:
                    next_title = u"» {}  {}".format(
                        to_text(programme_time(following[0])), to_text(following[2]))
            self._epg_panel_show("", now_title, "", next_title)
            return
        if status != "no_country":
            if current is not None:
                now_time = "{}  {} - {}".format(
                    _("Now"), vUtils.epg_clock(current[0]),
                    vUtils.epg_clock(current[1]))
                now_title = current[2]
            else:
                now_title = _("No programme information")
            if following is not None:
                next_time = "{}  {} - {}".format(
                    _("Next"), vUtils.epg_clock(following[0]),
                    vUtils.epg_clock(following[1]))
                next_title = following[2]
        self._epg_panel_show(now_time, now_title, next_time, next_title)

    def _epg_panel_show(self, *texts):
        try:
            for widget, text in zip(EPG_PANEL_WIDGETS, texts):
                self[widget].setText(to_string(text))
        except Exception as e:
            debug("Now/Next: updating the labels failed: {}".format(e))

    def _epg_panel_stop(self):
        try:
            self._epg_panel_timer.stop()
        except Exception:
            pass
        try:
            with self._epg_panel_lock:
                self._epg_panel_wanted = None
        except Exception:
            pass


# ---------------------------------------------------------------------
# What is playing: the preview window and the full-screen player share
# one stream (the app's PreviewPlayer)
# ---------------------------------------------------------------------
def stream_channel_id(url):
    """The catalog id (or "grp:<country>:<key>" group id) in a proxy
    stream address "...vavoo?channel=<id>", decoded, or None."""
    if not url or "vavoo?channel=" not in url:
        return None
    channel_id = url.split("vavoo?channel=")[1]
    for separator in ('&', '?', '#'):
        if separator in channel_id:
            channel_id = channel_id.split(separator)[0]
    if not channel_id:
        return None
    return url_unquote(channel_id)


def build_stream_sref(name, url):
    """The service reference a proxy channel is played with, or None
    when `url` is not a proxy stream address.

    Always the plain http://127.0.0.1:<PORT>/vavoo?channel=<id> and
    nothing else: the player comes back to that address on every
    playlist refresh (see Playstream2.playProxyStream()), so it must
    never carry anything one-off."""
    channel_id = stream_channel_id(url)
    if not channel_id:
        return None
    proxy_url = "http://{}:{}/vavoo?channel={}".format(
        PROXY_HOST, PORT, url_quote(channel_id, safe=''))
    # Add User-Agent as fragment, encode for Enigma2
    encoded_url = (proxy_url + "#User-Agent=VAVOO/2.6").replace(":", "%3a")
    safe_name = to_string(name)
    # Use the configured player service type ("Movie Services
    # Reference" - 4097/5001/5002/8193), as bouquet export does.
    ref = (cfg.services.value + ":0:1:0:0:0:0:0:0:0:" + encoded_url + ":" +
           safe_name.replace(":", "%3a"))
    sref = eServiceReference(ref)
    sref.setName(safe_name)
    return sref


def remember_recent(channel):
    """A channel was just watched: to the top of "Recently watched"
    (a small file write - in the background, never on a zap's way)."""
    if not channel or not channel.get('name') or not channel.get('url'):
        return

    def _write():
        vUtils.add_recent(
            channel.get('name'), channel.get('url'),
            country_name=channel.get('country_name'),
            country_code=channel.get('country_code'),
            logo=channel.get('logo'))

    worker = threading.Thread(target=_write)
    worker.daemon = True
    worker.start()


class _NowPlaying(object):
    """The one stream the plugin plays, and who has it: the list
    screens' preview window ("preview") or the full-screen player
    ("player"). OK on a channel plays it in the preview; OK again (or
    BLUE) hands that same stream to the player, which gives it back to
    the preview when it closes - never a second stream, never a
    restart in between (the app's PreviewPlayer / handBackToPreview).

    The proxy's stream_started() / stream_ended() count is kept here
    while the preview owns the stream, and moves with the stream to
    the player and back. `original` is what played before the plugin
    opened: put back when the plugin closes (MainVavoo.closex())."""

    PREVIEW = "preview"
    PLAYER = "player"
    # A preview stream that keeps ending: tried again this often within
    # a minute, then given up (the player does the same).
    MAX_QUICK_RETRIES = 3

    def __init__(self):
        self.owner = None
        self.channel = None
        self.sref = None
        self.original = None
        self.has_original = False
        self._failures = []

    def begin(self, session):
        """The plugin opens: remember what the box was playing."""
        if self.owner is None and not self.has_original:
            try:
                self.original = session.nav.getCurrentlyPlayingServiceReference()
            except Exception as e:
                debug("NowPlaying: no current service: {}".format(e))
                self.original = None
            self.has_original = True

    def preview_plays(self, url):
        return (self.owner == self.PREVIEW and self.channel is not None and
                self.channel.get('url') == url)

    def preview_play(self, session, channel):
        """Play `channel` ({name, url, country_name, country_code,
        logo}) in the preview window. False when it cannot be played
        (not a proxy address)."""
        sref = build_stream_sref(channel.get('name'), channel.get('url'))
        if sref is None:
            return False
        self.release_preview()
        try:
            vavoo_proxy.proxy.stream_started()
        except Exception as e:
            debug("NowPlaying: stream_started failed: {}".format(e))
        try:
            session.nav.stopService()
            session.nav.playService(sref)
        except Exception as e:
            print("[Preview] Could not play {}: {}".format(
                channel.get('name'), e))
            self._ended()
            return False
        self.owner = self.PREVIEW
        self.channel = dict(channel)
        self.sref = sref
        self._failures = []
        remember_recent(self.channel)
        return True

    def _ended(self):
        try:
            vavoo_proxy.proxy.stream_ended()
        except Exception as e:
            debug("NowPlaying: stream_ended failed: {}".format(e))

    def release_preview(self):
        """Forget the preview's stream (its count ends); the caller
        stops or replaces the service itself."""
        if self.owner == self.PREVIEW:
            self._ended()
        if self.owner != self.PLAYER:
            self.owner = None
            self.channel = None
            self.sref = None

    def player_take(self, url):
        """The full-screen player opens on `url`: True when the preview
        is playing exactly that - the player then carries on with it
        (and its count) instead of starting it again."""
        if self.preview_plays(url):
            self.owner = self.PLAYER
            return True
        self.release_preview()
        return False

    def player_give_back(self, channel, sref):
        """The player closes and leaves its stream playing for the
        preview window (its count goes with it)."""
        self.owner = self.PREVIEW
        self.channel = dict(channel)
        self.sref = sref
        self._failures = []

    def player_closed(self):
        """The player closed and stopped its stream itself."""
        if self.owner == self.PLAYER:
            self.owner = None
            self.channel = None
            self.sref = None

    def preview_stop(self, session, restore=True):
        """Stop the preview's stream and put back what the box played
        before the plugin opened (the plugin closes)."""
        had_stream = self.owner == self.PREVIEW
        self.release_preview()
        if had_stream:
            try:
                session.nav.stopService()
                if restore and self.original is not None:
                    session.nav.playService(self.original)
            except Exception as e:
                print("[Preview] Could not restore the service: {}".format(e))
        self.original = None
        self.has_original = False

    def preview_failed(self, session):
        """The preview's stream ended by itself: tell the proxy (it
        moves to another source after repeated failures) and play it
        again - up to MAX_QUICK_RETRIES times a minute. Returns False
        when it gave up."""
        if self.owner != self.PREVIEW or not self.channel:
            return False
        now = time.time()
        self._failures = [t for t in self._failures if now - t < 60]
        self._failures.append(now)
        channel_id = stream_channel_id(self.channel.get('url'))
        if channel_id:
            try:
                vavoo_proxy.proxy.report_stream_failure(channel_id)
            except Exception as e:
                debug("NowPlaying: report_stream_failure failed: {}".format(e))
        if len(self._failures) > self.MAX_QUICK_RETRIES:
            channel = self.channel
            self.release_preview()
            try:
                session.nav.stopService()
            except Exception:
                pass
            print("[Preview] Giving up on {}".format(channel.get('name')))
            return False
        try:
            session.nav.stopService()
            session.nav.playService(self.sref)
        except Exception as e:
            print("[Preview] Retry failed: {}".format(e))
        return True


NOW_PLAYING = _NowPlaying()


class PreviewWindow(object):
    """Mixed into the screens with a preview window (the list screens):
    a stream that ends while it plays in the window is tried again
    (_NowPlaying.preview_failed()). The screen calls
    _preview_init() while building itself."""

    def _preview_init(self):
        self._preview_tracker = ServiceEventTracker(
            screen=self, eventmap={iPlayableService.evEOF: self._preview_eof})

    def _preview_eof(self):
        if getattr(self, '_closed', False) or not getattr(self, 'execing', True):
            return
        if NOW_PLAYING.owner != NOW_PLAYING.PREVIEW:
            return
        # Not at once: the service is still tearing itself down.
        reactor.callLater(1, self._preview_retry)

    def _preview_retry(self):
        if getattr(self, '_closed', False):
            return
        if not NOW_PLAYING.preview_failed(self.session):
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("This channel cannot be played"), 4)

    def _preview_or_play(self, channel, open_player):
        """OK on a channel: into the preview window - or, when it is
        already playing there (or the preview is switched off), the
        full-screen player (`open_player()`)."""
        if cfg.preview_window.value and \
                not NOW_PLAYING.preview_plays(channel.get('url')):
            if NOW_PLAYING.preview_play(self.session, channel):
                return
        open_player()


class vavoo_config(Screen, ConfigListScreen):
    def __init__(self, session):
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

        # So background M3U-fetch threads (_fetch_countries_async/
        # _fetch_channels_async) can notice this screen was left and
        # stop trying to pop dialogs on top of whatever the user has
        # since navigated to.
        self._closed = False
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
        self.update_status()
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
        if current_theme() == "classic":
            self.list.append(
                getConfigListEntry(
                    _("Select Background"),
                    cfg.back,
                    _("Configure Main Background Image.")))
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
        # AutoStartTimer._update_bouquets() does Rytec matching, EPG
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
            _("Reminders"),
            cfg.reminders,
            _("The reminders set in the programme guide (OK on a programme "
              "still to come).")))
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
        self["config"].list = self.list
        self["config"].l.setList(self.list)
        self.setInfo()

    def backup(self):
        path = vavoo_store.write_backup(plugin_settings(), __version__)
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Saved: {}").format(path) if path
                         else _("The backup could not be saved"), 5)

    def restore(self):
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
        elif sel and sel == cfg.show_log:
            open_log_viewer(self.session)
        elif sel and sel == cfg.choose_countries:
            self.session.open(VavooCountries)
        elif sel and sel == cfg.parental:
            ask_pin(self.session, self,
                    lambda: self.session.open(VavooParental))
        elif sel and sel == cfg.reminders:
            self.session.open(VavooReminders)
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

        t = threading.Thread(target=task)
        t.daemon = True
        t.start()

    def _on_all_m3u_files_done(
            self, generated, failed, total_channels, total_countries):
        """Runs back on the GUI thread once generate_all_m3u_files()'s
        background loop finishes."""
        if getattr(self, "_closed", False):
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
            safe_name = safe_name.replace('➾', '_').replace('⟾', '_')
            safe_name = safe_name.replace('->', '_').replace('→', '_')

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
        t = threading.Thread(target=task)
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
        t = threading.Thread(target=task)
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
        if self["config"].isChanged():
            for x in self["config"].list:
                x[1].save()

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
                data = loads(ensure_str(response)) if response else None
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


def _shared_update_proxy_status_display(screen):
    """Update the 'proxy_status' widget on screen (MainVavoo/vavoo share
    this verbatim - kept in one place instead of two independently
    maintained copies, which already drifted out of sync once before
    for a sibling pair of constants, see PROXY_MONITOR_INTERVAL_MS
    above)."""
    try:
        if is_proxy_running():
            try:
                # retries=1: this runs synchronously on the GUI/reactor
                # thread from a repeating 10s eTimer (MainVavoo and
                # vavoo both have one) - getUrl()'s default retries=3
                # with backoff could block the ENTIRE UI for up to
                # ~18s on a slow/unresponsive proxy, out of every 10s
                # window. is_proxy_ready() right next to this call's
                # own callers already caps itself at a single attempt
                # for exactly this reason - this call just hadn't
                # matched it.
                response = getUrl(
                    PROXY_STATUS_URL, timeout=5, retries=1)
                if response:
                    status_data = loads(ensure_str(response))

                    # Geil (the default catalog source - see
                    # vavoo_proxy.py's catalog_source) needs no
                    # addonSig token at all, so addon_sig_valid is
                    # always False while running on it - requiring it
                    # unconditionally here showed "Proxy Error" on an
                    # otherwise perfectly healthy Geil proxy.
                    token_required = status_data.get(
                        "catalog_source", "vavoo") != "geil"
                    # The app's status line: "✓ Vavoo OK · 1234 ch" -
                    # the number the main list adds up to when it
                    # knows it (sources of a channel counted once),
                    # else the proxy's own count.
                    source = "Vavoo" if token_required else "Geil"
                    channels = getattr(screen, '_channel_total', None) or \
                        status_data.get("channels_count", 0)
                    if status_data.get("initialized", False) and (
                            not token_required or status_data.get(
                                "addon_sig_valid", False)):
                        token_age = status_data.get("addon_sig_age", 0)
                        if token_required and token_age >= 540:
                            status_text = "{} {} · {} ch".format(
                                source, _("(token expiring)"), channels)
                        else:
                            status_text = "✓ {} OK · {} ch".format(
                                source, channels)
                    else:
                        status_text = "✗ Proxy Error"
                else:
                    status_text = "? Proxy Unknown"
            except Exception:
                status_text = "✓ Proxy Running"
        else:
            status_text = "✗ Proxy Offline"

        screen['proxy_status'].setText(status_text)

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


class MainVavoo(Screen, PreviewWindow):
    def __init__(self, session):
        self.session = session
        global _session
        _session = session

        # So a background flag-download thread still in flight when the
        # user exits (closex()) can notice and skip re-arming timers /
        # touching UI on a screen that's no longer executing.
        self._closed = False
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
            'mainMenu': self.open_menu,
            'menu': self.open_menu,
            'green': self.open_favourites,
            'yellow': self.search_all,
            'blue': self.reload_list,
            'cancel': self.closex,
            'red': self.closex,
            'epg': self.manual_epg_update,
            'info': self.info_toast,
            'InfoPressed': self.info_toast,
            'infoLong': self.info,
            'text': self.refresh_proxy,
        }
        actions_list = [
            'MenuActions',
            'OkCancelActions',
            'ButtonSetupActions',
            'InfobarEPGActions',
            'EPGSelectActions',
            'ColorActions',
            'DirectionActions'
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
            if not is_proxy_running():
                print("[Watchdog] Proxy not running, attempting restart...")
                self['proxy_status'].setText(_(" Restarting..."))

                # Try restart
                success = run_proxy_in_background()

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
        _shared_update_proxy_status_display(self)

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
        """Callback for proxy refresh"""
        if result:
            try:
                # Try to refresh the token
                response = getUrl(
                    PROXY_REFRESH_URL, timeout=5)
                if response:
                    data = loads(ensure_str(response))
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

    def _restart_proxy(self):
        """Restart the proxy without blocking the GUI - stopping the
        old one, waiting for its port and starting the new one all
        happen in vavoo_proxy's own helper thread."""
        try:
            restart_proxy_in_background()
        except Exception as e:
            print("[Restart] Error: {0}".format(e))

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
            print("[MainVavoo] Proxy not ready, will retry shortly")
            self._retry_cat_later()
            return

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
                reminders = len(vavoo_store.load_timers(
                    vavoo_store.KIND_REMIND))
            except Exception:
                reminders = 0
            reactor.callFromThread(
                self._on_countries_response, response, exc, counts,
                favourite_count, recent, reminders)

        t = threading.Thread(target=_task)
        t.daemon = True
        t.start()

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
                    # The app's third row (its "Recordings"): the
                    # reminders set, while there are any.
                    label = _("Reminders")
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
                    if NOTIFICATION_AVAILABLE:
                        quick_notify(_("Channel list updated: {} channels").format(
                            self._channel_total or 0), 4)
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
                self._maybe_first_run(favourite_count, recent)
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
                self.session.openWithCallback(
                    self._on_child_closed, VavooReminders)
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

    def _maybe_first_run(self, favourite_count, recent):
        """On the very first start (no favourites, nothing watched, no
        country hidden, more than one country) Choose countries opens
        by itself, once, as in the app."""
        if cfg.countries_asked.value:
            return
        cfg.countries_asked.value = True
        cfg.countries_asked.save()
        try:
            configfile.save()
        except Exception:
            pass
        if favourite_count or recent or vavoo_store.hidden_countries() or \
                len(self.countries) < 2:
            return
        self.session.openWithCallback(
            self._on_countries_chosen, VavooCountries, self.countries,
            first_run=True)

    def _on_countries_chosen(self, saved=False):
        if saved and not self._closed:
            self.cat()

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

        worker = threading.Thread(target=_task)
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
            restart_proxy_in_background()
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
            quick_notify(info_text(self._channel_total, len(self.countries)), 5)

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
            "about": self.info,
        }
        open_action_menu(
            self.session, _("Menu"), entries,
            lambda key: actions[key]() if key in actions else None)

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

    def __init__(self, session, name, url, option_value=None,
                 category=None, channels=None):
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

        # So a bouquet-export background thread still running when the
        # user exits this screen (Screen.close() doesn't clear
        # self.session, so that alone can't be used to detect this) can
        # notice and skip touching this screen's UI/state afterward.
        self._closed = False

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
            self['green'].setText(_('Remove Fav') if favourite else _('Add Fav'))
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
        self["actions"] = ActionMap(
            [
                'MenuActions',
                'OkCancelActions',
                'ButtonSetupActions',
                'InfobarEPGActions',
                'EPGSelectActions',
                'ColorActions',
                'DirectionActions'
            ],
            {
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
            },
            -1
        )
        # The number keys go to that row (the app's numbered rows).
        self["number_actions"] = ActionMap(
            ['NumberActions'],
            dict((str(d), (lambda n: lambda: self.number(n))(d))
                 for d in range(10)),
            -1)

    def number(self, digit):
        """Typed within 1.5 s the digits add up (1, 2 = row 12)."""
        if not self.cat_list or self.showing_categories:
            return
        now = time.time()
        if now - self._digit_time > 1.5:
            self._digits = ""
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
                          str(i + 1).rjust(digits, u"\u2007"),
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

        t = threading.Thread(target=_worker)
        t.daemon = True
        t.start()

    def _refresh_channel_list_with_picons(self):
        """Rebuild the channel list from the already-fetched channel
        data (no new network fetch) so rows whose picon finished
        downloading since the list was first built pick it up."""
        self.picon_refresh_timer.stop()
        if self._closed or not self._channel_entries:
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
            sep in name for sep in GROUP_NAME_SEPARATORS) else "flat"

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

    def __init__(self, session, mode="favourites", folder=None):
        self.session = session
        self.mode = mode
        self.folder = folder
        Screen.__init__(self, session)
        self.skin, self._themed = load_screen_skin(
            "list", 'defaultListScreen.xml', cvs=True, clock_24=clock_24())

        init_notification_system(session)
        self._closed = False
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
             'MenuActions', 'EPGSelectActions', 'InfobarEPGActions',
             'NumberActions'], actions, -1)
        self.onLayoutFinish.append(self._build_list)
        self.onExecBegin.append(self._back_on_top)

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
        text = u"{}  {}".format(str(index + 1).rjust(digits, u" "),
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
        moving); typed within 1.5 s they add up (1, 2 = row 12)."""
        if not self.cat_list or self.showing_folders:
            return
        now = time.time()
        if now - self._digit_time > 1.5:
            self._digits = ""
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
                quick_notify((_("Added to favourites: {}") if now_favourite
                              else _("Removed from favourites: {}")).format(name), 3)
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


def proxy_countries():
    """The catalog's countries, A-Z (the proxy's list, in-process)."""
    try:
        return list(getattr(vavoo_proxy.proxy, 'countries_list', None) or [])
    except Exception:
        return []


# ---------------------------------------------------------------------
# Reminders (vavoo_store timers of kind "remind", the app's Timers)
# ---------------------------------------------------------------------
# The plugin's main screen and player while they are open, and a
# channel to play once the plugin has opened (a reminder's "watch it").
ACTIVE = {"main": None, "player": None, "pending": None}


def _in_standby():
    try:
        import Screens.Standby
        return Screens.Standby.inStandby is not None
    except Exception:
        return False


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
            due = vavoo_store.due_timers(kind=vavoo_store.KIND_REMIND)
        except Exception as e:
            debug("Reminders not read: {}".format(e))
            return
        for timer in due:
            self.fire(timer)

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


def floor_half_hour(timestamp):
    """`timestamp` down to a whole local half hour."""
    moment = time.localtime(timestamp)
    return int(timestamp) - (moment.tm_min % 30) * 60 - moment.tm_sec


def clock_text(timestamp):
    """"20:30" or "8:30 PM" (the clock setting)."""
    moment = time.localtime(timestamp)
    if clock_24():
        return time.strftime("%H:%M", moment)
    return time.strftime("%I:%M %p", moment).lstrip("0")


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

    def __init__(self, session, channels, start_index=0, title="",
                 over_player=False, on_zap=None):
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
        self['red'] = Label(_("Back"))
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
        self._closed = False
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
            "red": self.close_guide, "green": self.watch,
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
             'MenuActions', 'EPGSelectActions', 'InfobarEPGActions',
             'NumberActions'], actions, -1)
        self.onLayoutFinish.append(self._start)
        self.onClose.append(self._mark_closed)

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
            worker = threading.Thread(target=self._work)
            worker.daemon = True
            worker.start()
        self._draw_heading()

    def _work(self):
        start, stop = self._range()
        while True:
            with self._lock:
                if not self._wanted or self._closed:
                    self._working = False
                    break
                index = self._wanted.pop(0)
            channel = self.channels[index]
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
            u"{}  {}".format(str(index + 1).rjust(digits, u" "),
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
            entry.append(self._text(left, 0, x1 - pad - left, height,
                                    programme[2], text_color))
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
        """A programme still to come: Remind me / Watch; anything else:
        watch the channel."""
        programme = self._selected_programme()
        if programme is None or programme[0] <= time.time():
            self.watch()
            return
        channel = self.channels[self.sel_row]
        reminder = vavoo_store.find_timer(channel.get("url"), programme[0])
        entries = [(_("Cancel reminder") if reminder else _("Remind me"),
                    "remind"), (_("Watch"), "watch")]

        def chosen(key):
            if self._closed:
                return
            if key == "watch":
                self.watch()
            elif key == "remind":
                self.toggle_reminder(channel, programme)

        open_action_menu(self.session, to_string(programme[2]), entries,
                         chosen)

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
        if self.over:
            self.close(None)
        else:
            open_settings(self.session)

    def close_guide(self):
        self.close(None)


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
            ['OkCancelActions', 'ColorActions', 'DirectionActions',
             'EPGSelectActions'], actions, -1)
        self.rows = []
        self.onLayoutFinish.append(lambda: self.refresh(0))

    def key_actions(self):
        return {}

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


def _is_country_locked(country_name):
    """True if `country_name` is a locked country and a PIN is set
    (vavoo_store)."""
    return vavoo_store.is_country_locked(country_name)


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


def timer_when(timestamp):
    """"Sat 16 Nov 20:00" (the app's list of timers)."""
    moment = time.localtime(timestamp)
    return to_text(time.strftime("%a %d %b ", moment)) + \
        to_text(clock_text(timestamp))


class VavooReminders(VavooPickScreen):
    """The reminders set (the app's RecordingsActivity, timers part;
    phase 5 adds the recordings): "Title  ·  Channel" with the day and
    time. OK → Cancel reminder; GREEN Delete (press twice); RED Back."""

    REFRESH_MS = 30000

    def __init__(self, session):
        self.timers = []
        self._delete_armed = None
        VavooPickScreen.__init__(
            self, session,
            _("Set with OK on a programme still to come in the programme "
              "guide (INFO in a channel list). At the programme's start a "
              "window offers to watch it."),
            (_("Back"), _("Delete"), "", ""))
        self._timer = eTimer()
        try:
            self._timer.callback.append(self._tick)
        except Exception:
            self._timer.timeout.connect(self._tick)
        self.onLayoutFinish.append(
            lambda: self._timer.start(self.REFRESH_MS, True))
        self.onClose.append(self._timer.stop)

    def key_actions(self):
        return {"ok": self.ok, "green": self.delete}

    def _tick(self):
        # (one that went off meanwhile has left the file)
        self.refresh()
        self._timer.start(self.REFRESH_MS, True)

    def refresh(self, select=None):
        self.timers = vavoo_store.load_timers(vavoo_store.KIND_REMIND)
        rows = []
        for timer in self.timers:
            rows.append(show_list(
                to_string(u"{}  ·  {}".format(
                    to_text(timer.get("title")), to_text(timer.get("name")))),
                str(timer["id"]), is_category=True, kind="big",
                themed=self._themed, value=timer_when(timer["start"]),
                no_icon=True))
        self._show(rows, select)
        self['statusbar'].setText(
            _("{} reminders").format(len(self.timers)) if self.timers
            else _("No reminders"))

    def _selected(self):
        index = self._index()
        if 0 <= index < len(self.timers):
            return self.timers[index]
        return None

    def _remove(self, timer):
        vavoo_store.remove_timer(timer["id"])
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Cancelled"), 2)
        self.refresh()

    def ok(self):
        timer = self._selected()
        if timer is None:
            return
        open_action_menu(
            self.session, to_string(timer.get("title")),
            [(_("Cancel reminder"), "cancel")],
            lambda key: self._remove(timer) if key == "cancel" else None)

    def delete(self):
        timer = self._selected()
        if timer is None:
            return
        if self._delete_armed != timer["id"]:
            self._delete_armed = timer["id"]
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Press again to delete"), 3)
            return
        self._delete_armed = None
        self._remove(timer)


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


def open_log_viewer(session):
    """The last 200 lines of the plugin's log."""
    session.open(
        VavooLogViewer,
        title=_("Vavoo Log"),
        file_path=LOG_FILE,
        tail_lines=200)


class VavooLogViewer(Screen):
    """Dedicated log-tail viewer with real up/down/page scrolling -
    Console.py (used for this previously) has none at all: its text
    widget is a plain Label that always shows just the last ~13 lines
    of whatever's been printed, by design (built for live
    install-script output, where only the latest line matters - fine
    there, useless for browsing a static multi-hundred-line log file
    where most of it is further back than that).

    Reuses Console's own skin (the exact same inline XML, picked for
    the current resolution once at Console's class-definition time -
    no new skin file to keep in sync across hd/fhd/wqhd) but not
    Console's class or ActionMap: this reads the file directly in
    Python (no eConsoleAppContainer/shell command needed for a plain
    file read) and binds OkCancelActions - the convention every other
    screen in this file actually uses - instead of Console's
    WizardActions/"exit", which nothing else here relies on."""

    VISIBLE_LINES = Console.VISIBLE_LINES

    def __init__(self, session, title, file_path, tail_lines=200):
        Screen.__init__(self, session)
        # The theme's box (the same 13 lines), or Console's skin minus
        # the two things that don't apply to a read-only log view: the
        # static "Command execution..." header and the green "Restart
        # GUI" caption (no green key bound here at all - same
        # reasoning as Console.py's own allow_restart=False path).
        self.skin = build_theme_skin("log", title=to_string(title)) or \
            Console.skin.replace(
                'Command execution...', title
            ).replace('text="Restart GUI"', 'text=""')
        self._closed = False
        self.onClose.append(self._mark_closed)

        try:
            with codecs.open(
                    file_path, 'r', encoding='utf-8',
                    errors='replace') as f:
                self.lines = [
                    line.rstrip('\n') for line in f.readlines()[-tail_lines:]]
        except Exception as e:
            self.lines = ["Could not read {}: {}".format(file_path, e)]

        # Start scrolled to the most recent lines (what "tail" means),
        # same as the command this replaced - up/page-up reach
        # earlier ones.
        self.offset = max(0, len(self.lines) - self.VISIBLE_LINES)

        self['text'] = Label('')
        self['key_red'] = Label(_('Close'))
        self['actions'] = ActionMap(
            ['OkCancelActions', 'ColorActions', 'DirectionActions'],
            {
                "ok": self.close,
                "cancel": self.close,
                "red": self.close,
                "up": self.moveUp,
                "down": self.moveDown,
                "left": self.pageUp,
                "right": self.pageDown,
            },
            -1
        )
        self.onLayoutFinish.append(self._render)

    def _mark_closed(self):
        self._closed = True

    def _max_offset(self):
        return max(0, len(self.lines) - self.VISIBLE_LINES)

    def _render(self):
        window = self.lines[self.offset:self.offset + self.VISIBLE_LINES]
        self['text'].setText('\n'.join(window))

    def moveUp(self):
        if self.offset > 0:
            self.offset -= 1
            self._render()

    def moveDown(self):
        if self.offset < self._max_offset():
            self.offset += 1
            self._render()

    def pageUp(self):
        self.offset = max(0, self.offset - self.VISIBLE_LINES)
        self._render()

    def pageDown(self):
        self.offset = min(self._max_offset(), self.offset + self.VISIBLE_LINES)
        self._render()


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

        self.numericalInput = NumericalTextInput(
            nextFunc=self.searchWithString)
        self.input_active = False
        self.upper_case = False
        self.last_key = None
        self.search_text = ""
        self.last_key_time = 0

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


# ---------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------
# The labels of the theme's player bar (vavoo_theme.player_bar()).
PLAYER_BAR_LABELS = (
    "number", "name", "now", "left", "next", "status", "stream_info",
    "key_options", "key_audio", "key_list", "key_recall",
    "key_red", "key_green", "key_yellow", "key_blue")
# The bar's buttons in LEFT / RIGHT order (the app's: the colour ones,
# then the small ones) and the Playstream2 method each one runs.
PLAYER_BAR_BUTTONS = (
    ("key_red", "cancel"), ("key_green", "toggle_favourite"),
    ("key_yellow", "previousitem"), ("key_blue", "nextitem"),
    ("key_options", "open_options"), ("key_audio", "_bar_audio"),
    ("key_list", "_bar_list"), ("key_recall", "recall"))
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
            worker = threading.Thread(target=self._guide_work)
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

            controls = _(
                "CH±=Change | OK=Toggle | INFO=IMDb | YELLOW=Source | STOP=Exit")
            credit = "by Lululla & Qu4k3"
            help_text = "{} | {} | {}".format(controls, proxy_details, credit)
            self["helpOverlay"].setText(help_text)
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

            _epg_fetch_thread = threading.Thread(target=_fetch_epg_async)
            _epg_fetch_thread.daemon = True
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
            for widget, _action in PLAYER_BAR_BUTTONS:
                self["sel_" + widget] = Pixmap()
            self.onLayoutFinish.append(self._bar_layout_finished)
        # The bar button highlighted with LEFT / RIGHT (-1: none).
        self._bar_sel = -1
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
                'InfobarSeekActions',
                'ColorActions',
                'NumberActions',
                'InfobarChannelSelection'
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
                # The app's keys: INFO shows / hides the bar, RED back,
                # GREEN favourite, YELLOW / BLUE channel down / up. The
                # stream source (YELLOW before) is in the options
                # (MENU - see mainMenu()).
                "info": self.toggle_bar,
                "red": self.cancel,
                "green": self.toggle_favourite,
                "yellow": self.previousitem,
                "blue": self.nextitem,
                "historyBack": self.recall,
                # LEFT / RIGHT go along the bar's buttons, OK presses
                # the highlighted one (the app's barButtons)
                "left": self.bar_left,
                "right": self.bar_right,
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

        epg_thread = threading.Thread(target=_fetchEpgThenOpen)
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
            self.zap_to((int(self.currentindex) + 1) % self.itemscount)

    def previousitem(self):
        """Switch to previous channel"""
        if self.itemscount:
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
        self.stopStream(restore_original=False)
        self.currentindex = i
        item = self.list[i][0]
        self.name = item[0]
        self.url = item[1]
        self._update_country_code_for_index(i)
        self._update_logo_url_for_index(i)
        self.startStream()

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
                  "logo"] + ["sel_" + widget for widget, _a in PLAYER_BAR_BUTTONS]
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
        """OK: the bar; OK with the bar showing: the channel list (the
        app's player). A channel number being typed: go there."""
        if self._typed:
            self._commit_digits()
            return
        if self._bar_sel >= 0 and self._bar_visible():
            self._bar_press()
            return
        if self._bar_visible():
            self.hide_help_overlay()
            self.doHide()
            self.open_channel_list()
            return
        TvInfoBarShowHide.OkPressed(self)

    # ---- the bar's buttons with LEFT / RIGHT (the app's selectBarButton)

    def bar_left(self):
        self._bar_move(-1)

    def bar_right(self):
        self._bar_move(1)

    def _bar_move(self, step):
        """Highlight the next / previous bar button (round the end);
        with the bar hidden, show it with the first (RIGHT) or last
        (LEFT) one highlighted. Classic's bar has no buttons."""
        if not self._bar_themed or self._closed:
            return
        count = len(PLAYER_BAR_BUTTONS)
        if not self._bar_visible():
            TvInfoBarShowHide.OkPressed(self)
            index = 0 if step > 0 else count - 1
        elif self._bar_sel < 0:
            index = 0 if step > 0 else count - 1
        else:
            index = (self._bar_sel + step) % count
        self._bar_select(index)
        self.startHideTimer()

    def _bar_select(self, index):
        self._bar_clear()
        try:
            self["sel_" + PLAYER_BAR_BUTTONS[index][0]].show()
        except Exception as e:
            debug("Bar highlight not shown: {}".format(e))
        self._bar_sel = index

    def _bar_clear(self):
        if self._bar_sel >= 0:
            try:
                self["sel_" + PLAYER_BAR_BUTTONS[self._bar_sel][0]].hide()
            except Exception:
                pass
        self._bar_sel = -1

    def _bar_press(self):
        """OK on the highlighted button: what it says. The bar stays
        (CH- / CH+ can be pressed again and again), except for List,
        which opens the channel list in its place."""
        widget, action = PLAYER_BAR_BUTTONS[self._bar_sel]
        if action == "_bar_list":
            self.hide_help_overlay()
            self.doHide()
            self.open_channel_list()
            return
        getattr(self, action)()
        if not self._closed and self._bar_visible():
            self.startHideTimer()

    def _bar_audio(self):
        self._call_infobar("audioSelection")

    def toggle_bar(self):
        """INFO: show / hide the bar."""
        TvInfoBarShowHide.OkPressed(self)

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
        # the bar goes: so does its highlight
        if self._bar_themed:
            self._bar_clear()
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
                "key_yellow": u"\u25bc " + to_text(_("CH-")),
                "key_blue": to_text(_("CH+")) + u" \u25b2",
                "key_options": to_text(_("Options")),
                "key_audio": to_text(_("Audio")),
                "key_list": to_text(_("List")),
                "key_recall": to_text(_("Recall")),
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

        worker = threading.Thread(target=_work)
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

    def _on_channel_list_closed(self, index=None):
        if self._closed or index is None:
            return
        if index == int(self.currentindex):
            if not self.stream_running:
                # chosen again after it stopped: start it again
                self.startStream()
            return
        self.zap_to(index)

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
        """YELLOW: let the user manually pick which physical source
        (Vavoo/Geil's ".b"/".c"/".s" convention - see
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
                           "eof_recovery_timer"):
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
            # _update_bouquets() does the real work: Rytec matching, EPG
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
        if not is_proxy_running():
            print("[Vavoo] Starting proxy at boot...")
            run_proxy_in_background()
        else:
            print("[Vavoo] Proxy already running at boot")

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


def checkInternet():
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.settimeout(0.5)
            s.connect(('8.8.8.8', 53))
            return True
        finally:
            s.close()
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
