#!/usr/bin/python
# -*- coding: utf-8 -*-
"""The screens' shared ground: settings (cfg), keys, skins and themes,
list rows, the MENU popup, the Now/Next panel, the stream shared by
the preview window and the player (NOW_PLAYING), small helpers."""
from __future__ import absolute_import, print_function

import codecs
import re
import time
import threading
from os import listdir, unlink
import shutil
from os.path import (
    exists as file_exists,
    join,
    isfile,
    getsize
)
from twisted.internet import reactor
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.MenuList import MenuList
from Components.MultiContent import MultiContentEntryPixmapAlphaTest, MultiContentEntryText
from Components.ServiceEventTracker import ServiceEventTracker
from Components.config import (
    ConfigSelection,
    ConfigSelectionNumber,
    ConfigClock,
    ConfigText,
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
    loadPNG
)
from Screens.Screen import Screen
from . import vavoo_proxy
from . import (
    _,
    __version__,
    PORT,
    PLUGIN_ROOT,
    PROXY_HOST,
    FLAG_CACHE_DIR,
    LOG_FILE,
    literals_for
)
from . import PY2, PY3, vUtils
from . import vavoo_theme
from . import vavoo_store
from . import vavoo_record
from .vUtils import (
    debug,
    make_print,
    get_country_code,
    get_picon_cache_path
)
from .Console import Console
try:
    from Components.AVSwitch import AVSwitch
except ImportError:
    from Components.AVSwitch import eAVControl as AVSwitch
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
vavoo_record.set_logger(print)


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


# set plugin
global HALIGN, BackPath
global screen_width

title_plug = 'Vavoo'
desc_plugin = ('..:: Vavoo by Lululla & Qu4k3 v.%s ::..' % __version__)
PLUGIN_PATH = PLUGIN_ROOT
PLUGLOGO = join(PLUGIN_PATH, 'plugin.png')

# The players' keys (keymap.xml, context PLAYER_KEYS): the image's own
# names for a key differ (OpenATV 7: MENU = "showMenu" in
# "InfoBarMenuActions", Enigma2's main menu; OpenPLi: PLAY only resumes)
# and Enigma2 turns its pause / seek keys off for a stream it cannot seek
# - a live one. With the plugin's own keymap a key means the same on
# every image. A screen maps it at PLAYER_KEYS_PRIO, above Enigma2's own
# handlers (seek -1, menu 0, show/hide 0-1), and keeps its image-context
# maps one step lower (still above Enigma2's) as the fallback for a box
# where the keymap cannot be loaded.
KEYMAP_FILE = join(PLUGIN_PATH, 'keymap.xml')
PLAYER_KEYS = "VavooPlayerActions"
PLAYER_KEYS_PRIO = -3


def load_keymap(path=KEYMAP_FILE):
    """Load the plugin's keymap.xml into Enigma2 (once per run: loaded
    again, it is unloaded first). True when it is in."""
    try:
        from keymapparser import readKeymap
    except ImportError:
        try:
            from Components.ActionMap import loadKeymap as readKeymap
        except ImportError:
            print("[Vavoo] Own keys not loaded: no keymap parser")
            return False
    try:
        try:
            from keymapparser import removeKeymap
            removeKeymap(path)
        except Exception:
            pass
        readKeymap(path)
        print("[Vavoo] Own keys loaded ({})".format(path))
        return True
    except Exception as e:
        print("[Vavoo] Own keys not loaded: {}".format(e))
        return False


KEYMAP_LOADED = load_keymap()


INFO_PAGE_ACTIONS = ("info", "epg", "nextBouquet", "prevBouquet")


def info_page_keys(actions, prio=-1):
    """A list screen's INFO / EPG and CH± page keys, on a key list of
    their own (EPGSelectActions, ChannelSelectBaseActions) holding only
    those: OpenATV / OpenViX map RED / YELLOW / BLUE in EPGSelectActions
    on the press while ColorActions has them on the release, so in one
    key list a colour key ran twice (the guide's YELLOW moved 2 hours,
    Move in Favourites went on and off, Reload List reloaded twice);
    here the colours find no action. ChannelSelectBaseActions has CH±
    as nextBouquet / prevBouquet on every image (OpenATV / OpenViX have
    them nowhere else a list screen looks)."""
    return ActionMap(["EPGSelectActions", "ChannelSelectBaseActions"],
                     dict((k, v) for k, v in actions.items()
                          if k in INFO_PAGE_ACTIONS), prio)


def player_keys(actions):
    """The ActionMap of the plugin's own player keys: `actions` (keymap.xml's
    names) plus "ignore", which takes a key's release / repeat / hold."""
    keys = dict(actions)
    keys.setdefault("ignore", lambda: None)
    return ActionMap([PLAYER_KEYS], keys, PLAYER_KEYS_PRIO)


# The list screens' direct keys (keymap.xml, VavooListActions): FAV,
# PVR / FILE / VIDEO / LIST, TEXT, HELP, PLAY, STOP, REC, BACK - above the
# screens' own key lists (-1) and Enigma2's listbox (0).
LIST_KEYS = "VavooListActions"
MAIN_KEYS = "VavooMainActions"
LIST_KEYS_PRIO = -2


def list_keys(actions):
    """The ActionMap of a list screen's direct keys: `actions` (keymap.xml's
    VavooListActions names) plus "ignore" for their release / repeat /
    hold. A name the screen leaves out reaches Enigma2 as before."""
    keys = dict(actions)
    keys.setdefault("ignore", lambda: None)
    return ActionMap([LIST_KEYS], keys, LIST_KEYS_PRIO)


ENIGMA_PATH = get_enigma2_path()


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
                # (shown "Oktus" / "Kiddac"; the value stays the file's
                # name, as saved settings and backups have it)
                BakP.append((back_name, back_name.capitalize()))
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
cfg.recordings = NoSave(ConfigAction())
cfg.record_folder = NoSave(ConfigAction())
cfg.backup = NoSave(ConfigAction())
cfg.restore = NoSave(ConfigAction())
cfg.clear_favourites = NoSave(ConfigAction())
cfg.licences = NoSave(ConfigAction())
cfg.about = NoSave(ConfigAction())
# Settings: the last row, "All settings (n more)" / "Fewer settings"
cfg.more_settings = NoSave(ConfigAction())
# A new install's welcome (ui_pick.run_welcome()) has run, or was not
# needed (an install in use)
cfg.welcome_done = ConfigYesNo(default=False)
# Which catalog/stream source vavoo_proxy.py's initialize_proxy()
# tries - "auto" keeps its default Geil-first/Vavoo-fallback
# order; "geil"/"vavoo" pin it to exactly one source (an explicit
# choice is respected: only its list is loaded and saved - while it
# gives none and none is in use, another list is lent meanwhile,
# vavoo_proxy's _lend_catalog()). Read directly by vavoo_proxy.py via its own e2_config
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
# screen falls back to if a theme cannot be used). The Background row
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
# PAUSE records the channel to go on from there (the app's "Pause Live
# TV"), and where recordings go ("" = Enigma2's movie folder).
cfg.timeshift = ConfigYesNo(default=True)
cfg.record_path = ConfigText(default="")
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
    if PY2:
        # Enigma2's skin parser on Python 2 (cElementTree) takes bytes:
        # a unicode skin with a non-ASCII character (the splash screen's
        # "\u00d7", the update popup's "\u2500") made the screen crash
        text = text.encode("utf-8")
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
# the row that says why there are no countries at all (OK: the settings
# or Reload List - MainVavoo._no_channels_ok())
NO_CHANNELS_ROW = "__vavoo_no_channels__"


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


def row_number(number, digits, fill=u" "):
    """A row's number padded to `digits` ("  7"), as text. (A str padded
    with a unicode fill is a TypeError on Python 2: the numbered lists
    did not open there.)"""
    return to_text(str(number)).rjust(digits, fill)


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
        country_name = safe_name
        for sep in literals_for(safe_name, '➾', '⟾', '→', '->'):
            country_name = country_name.split(sep)[0]
        country_name = country_name.strip()
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
        # the value's column at the right end: three row heights, or
        # as wide as its text needs (a date), at most half the row
        if themed:
            font_size = theme_metrics(kind)["font_size"]
        else:
            font_size = 38 if screen_width >= 2560 else (
                34 if screen_width >= 1920 else 22)
        value_w = min(max(text_size[1] * 3,
                          int(len(to_text(value)) * font_size * 0.58)),
                      text_size[0] // 2)
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


def open_action_menu(
        session,
        title,
        entries,
        on_choice,
        layout="menu",
        on_cancel=None):
    """The MENU key's actions: `entries` = [(label, key)], on_choice(key)
    once one is picked (on_cancel() on EXIT, when given). The theme's
    own popup in a modern theme (`layout` "player_menu": the player's
    left panel), Enigma2's ChoiceBox in Classic."""
    def _picked(key):
        if key is not None:
            on_choice(key)
        elif on_cancel is not None:
            on_cancel()

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


# CLOSED_UNTIL_OPEN - Enigma2's Screen.doClose() ends with
# `self.__dict__.clear()`: every attribute of a closed screen is gone. A
# thread or a reactor.callFromThread() / callLater() of the screen that
# comes back afterwards (a download, a lookup) then reads attributes that
# are not there - in a thread an error in the log, on the GUI thread one
# that can take Enigma2 down (OpenATV 8). So every screen with such work
# has `_closed = True` as a CLASS attribute and sets `self._closed =
# False` first thing in __init__: after the close, self._closed reads
# the class's True. That work checks self._closed before anything else
# of the screen (and keeps what it needs in locals).
# Also: Screen is a dict and doClose() calls self.items() - no attribute
# of a screen is named like a dict method (items, keys, values, get,
# update, pop, clear, copy...): "'list' object is not callable" there
# was the Recordings crash.


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

    # (see CLOSED_UNTIL_OPEN)
    _closed = True

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
        if self._closed:
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
        if self._closed:
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
        if self._closed:
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
            worker = threading.Thread(
                target=named(self._epg_panel_work, "vv-nownext"))
            worker.daemon = True
            worker.start()

    def _epg_panel_work(self):
        """Background thread: answer the latest row asked for, until
        there is none left."""
        if self._closed:
            return
        lock = self._epg_panel_lock
        while True:
            with lock:
                if self._closed:
                    return
                request = self._epg_panel_wanted
                self._epg_panel_wanted = None
                if request is None:
                    self._epg_panel_working = False
                    return
            try:
                answer = vUtils.lookup_now_next(
                    request[0], request[2],
                    channel_id=_epg_channel_id(request[1]))
            except Exception as e:
                debug("Now/Next: lookup failed: {}".format(e))
                answer = ("no_guide", None, None)
            if not self._closed:
                reactor.callFromThread(
                    self._epg_panel_arrived, request, answer)

    def _epg_panel_arrived(self, request, answer):
        """Back on the GUI thread with the background thread's answer."""
        if self._closed or request != self._epg_panel_row:
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
                        to_text(
                            programme_time(
                                current[0])), to_text(
                            current[2]))
                else:
                    now_title = _("No programme information")
                if following is not None:
                    next_title = u"» {}  {}".format(
                        to_text(
                            programme_time(
                                following[0])), to_text(
                            following[2]))
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


def named(target, name):
    """`target` for a thread, that first gives the thread its name in
    the system ("top -H" shows which of the plugin's threads loads the
    box: vv-guide, vv-nownext, vv-bar, vv-rec...)."""
    def run(*args, **kwargs):
        vavoo_record.name_this_thread(name)
        return target(*args, **kwargs)
    return run


def file_stream_sref(url, name):
    """The service reference for a /file address of the proxy (a
    recording or the pause buffer), with the same player service
    type as the channels (cfg.services)."""
    encoded_url = (url + "#User-Agent=VAVOO/2.6").replace(":", "%3a")
    safe_name = to_string(name)
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
        # STOP stopped the window: the service before the plugin is
        # still to be put back when it closes
        self.halted = False

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
        self.halted = False
        # heavy background work gives way from now on (the proxy keeps
        # it up on every playlist refresh) - vUtils.stream_playing()
        vUtils.note_stream()
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
        vUtils.note_stream()
        if self.preview_plays(url):
            self.owner = self.PLAYER
            return True
        self.release_preview()
        return False

    def player_give_back(self, channel, sref):
        """The player closes and leaves its stream playing for the
        preview window (its count goes with it)."""
        vUtils.note_stream()
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

    def preview_halt(self, session):
        """STOP in a list: the window's stream stops and the box plays
        nothing; what played before the plugin opened is still put back
        when it closes (preview_stop()). False when nothing played."""
        if self.owner != self.PREVIEW:
            return False
        self.release_preview()
        self.halted = True
        try:
            session.nav.stopService()
        except Exception as e:
            print("[Preview] Could not stop: {}".format(e))
        return True

    def preview_stop(self, session, restore=True):
        """Stop the preview's stream and put back what the box played
        before the plugin opened (the plugin closes)."""
        had_stream = self.owner == self.PREVIEW or self.halted
        self.release_preview()
        self.halted = False
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

    # (see CLOSED_UNTIL_OPEN)
    _closed = True

    def _preview_init(self):
        self._preview_tracker = ServiceEventTracker(
            screen=self, eventmap={iPlayableService.evEOF: self._preview_eof})

    def _preview_eof(self):
        if self._closed or not getattr(self, 'execing', True):
            return
        if NOW_PLAYING.owner != NOW_PLAYING.PREVIEW:
            return
        # Not at once: the service is still tearing itself down.
        reactor.callLater(1, self._preview_retry)

    def _preview_retry(self):
        if self._closed:
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
    _closed = True          # (see CLOSED_UNTIL_OPEN)

    def __init__(self, session, title, file_path, tail_lines=200):
        self._closed = False
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
        self['list_keys'] = list_keys({"help": self.show_help,
                                       "back": self.close})
        self.onLayoutFinish.append(self._render)

    def show_help(self):
        show_keys(self.session, [
            (_("UP / DOWN"), _("Scroll")),
            (_("LEFT / RIGHT"), _("Page up / down")),
            (_("OK / RED / EXIT"), _("Close")),
        ])

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


def _no_answer(*args, **kwargs):
    return None


def favourite_channels():
    """The favourites as the guide takes its channels."""
    return [{"name": e.get("name"), "url": e.get("url"),
             "logo": e.get("logo"), "country_name": e.get("country_name"),
             "country_code": e.get("country_code")}
            for e in (vUtils.load_favourites() or []) if e.get("url")]


def show_keys(session, rows, title=None):
    """HELP: a screen's keys and what they do ([(key, what)]), in the
    theme's popup (ChoiceBox in Classic); picking a row only closes it."""
    entries = [(to_string(u"{}   ·   {}".format(to_text(key), to_text(what))),
                "close") for key, what in rows]
    open_action_menu(session, title or _("Keys"), entries, _no_answer)


def stop_preview(session):
    """STOP in a list: the preview window stops."""
    if not NOW_PLAYING.preview_halt(session) and NOTIFICATION_AVAILABLE:
        quick_notify(_("Nothing is playing in the window"), 2)


# ---------------------------------------------------------------------
# Player helpers
# ---------------------------------------------------------------------
# The labels of the theme's player bar (vavoo_theme.player_bar()).
PLAYER_BAR_LABELS = (
    "number", "name", "now", "left", "next", "status", "stream_info",
    "key_options", "key_list",
    "key_red", "key_green", "key_yellow", "key_blue")


def add_skin_back(bakk):
    """The chosen background copied onto default.png (in Python: no
    shell with an unquoted path, no `sync` holding up the GUI)."""
    baknew = join(BackPath, str(bakk))
    if isfile(baknew):
        try:
            shutil.copyfile(baknew, join(BackPath, "default.png"))
        except Exception as e:
            print("[vavoo] Background not copied: {}".format(e))


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
