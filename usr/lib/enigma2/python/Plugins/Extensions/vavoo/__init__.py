# -*- coding: utf-8 -*-

from __future__ import absolute_import
__author__ = "Lululla & Qu4k3"
__email__ = "ekekaz@gmail.com"
__copyright__ = 'Copyright (c) 2024 Lululla'
__license__ = "CC BY-NC-SA 4.0"
__version__ = "1.91"

from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
import gettext
import os
from sys import version_info
import threading

# Lock to serialize exports (prevents concurrent executions)
export_lock = threading.Lock()

PORT = 4323
PLUGIN_ID = 'vavoo'
PLUGIN_ROOT = resolveFilename(SCOPE_PLUGINS, "Extensions/{}".format(PLUGIN_ID))

PROXY_HOST = "127.0.0.1"
PROXY_BASE_URL = "http://{}:{}".format(PROXY_HOST, PORT)
PROXY_STATUS_URL = PROXY_BASE_URL + "/status"
PROXY_COUNTRIES_URL = PROXY_BASE_URL + "/countries"
PROXY_REFRESH_URL = PROXY_BASE_URL + "/refresh_token"

HOST_MAIN = 'https://raw.githubusercontent.com/Belfagor2005/vavoo/main'
HOST_GIT = "https://raw.githubusercontent.com/Belfagor2005"
# Where updates come from: the version check reads installer.sh's
# version= here, and that installer downloads this repository's main
# branch. (Programme guides and the curated channel database still come
# from HOST_MAIN / HOST_GIT, as before.)
UPDATE_HOST = 'https://raw.githubusercontent.com/OwnerPlugins/vavoo/main'
# Programme guides, as the Android app reads them: each country's daily
# XMLTV files from epgshare01.online first (updated every day, several
# days ahead; the Balkans from three countries' files together), and
# the copy on GitHub when those fail or are out of date - that copy
# stopped being updated for days at a time. A country without daily
# files has only the copy.
EPG_DAILY_URL = "https://epgshare01.online/epgshare01/epg_ripper_%s.xml.gz"
EPG_COPY_URL = HOST_GIT + "/vavoo-player/master/epg_%s.xml"
EPG_DAILY_SOURCES = {
    "al": ("AL1",), "bg": ("BG1",), "bk": ("BA1", "HR1", "RS1"),
    "ch": ("CH1",), "de": ("DE1",), "es": ("ES1",), "fr": ("FR1",),
    "gb": ("UK1",), "hr": ("HR1",), "it": ("IT1",), "nl": ("NL1",),
    "pl": ("PL1",), "pt": ("PT1",), "ro": ("RO1",), "tr": ("TR1",),
    "sa": ("AE1",),
}
INSTALLER_URL = UPDATE_HOST + "/installer.sh"
FLAG_CACHE_DIR = "/tmp/vavoo_flags"
PICON_CACHE_DIR = "/tmp/vavoo_picons"
LOG_FILE = "/tmp/vavoo.log"
PRIMARY_BASE_URL = "https://vavoo.to"
FALLBACK_BASE_URL = "https://kool.to"
BASE_SITES = [PRIMARY_BASE_URL, FALLBACK_BASE_URL]
# geil.to (and its mirrors - the same service) serves the same kind of
# IPTV catalog with no addonSig/token step at all - tried first since
# it needs no token, with BASE_SITES above as the fallback catalog
# source when it's unreachable. Same approach the companion Android
# app (pQu4k3r/vavoo_android) already ships.
GEIL_SITES = ["https://geil.to", "https://geil.app", "https://geil.win"]
GEIL_LIVE_PATH = "/live"
# Separators geil.to's and Vavoo's own catalogs both use to join a
# channel's country and category into one "group"/bouquet-name string
# (e.g. "Italy ➾ Sport"). One shared constant here, imported by every
# module that needs to split a group/bouquet name back into its
# country part, instead of several independently-maintained literal
# copies - those had already drifted out of sync with each other (two
# different 4-item subsets of this same 6-item list, in different
# files, missing "»"/"›").
GROUP_NAME_SEPARATORS = ("➾", "⟾", "->", "→", "»", "›")
PY2 = version_info[0] == 2
PY3 = version_info[0] == 3
_TEXT_TYPE = type(u"")


def literals_for(text, *literals):
    """The plain "..." literals in text's own string type. On Python 2 a
    literal with a non-ASCII character ("➾") is UTF-8 bytes, and `in` /
    split() / replace() between it and unicode raise UnicodeDecodeError
    - whatever text holds: the catalog's group names (JSON, so unicode)
    all failed, and so did get_country_code() on every call."""
    if PY2 and isinstance(text, _TEXT_TYPE):
        return tuple(lit if isinstance(lit, _TEXT_TYPE)
                     else lit.decode("utf-8") for lit in literals)
    return literals


def group_separators(text):
    """GROUP_NAME_SEPARATORS in text's own string type - loop over this,
    never over the tuple itself (see literals_for())."""
    return literals_for(text, *GROUP_NAME_SEPARATORS)


PluginLanguageDomain = PLUGIN_ID
PluginLanguagePath = 'Extensions/{}/locale'.format(PLUGIN_ID)


def get_enigma2_path():
    barry_active = '/media/ba/active/etc/enigma2'
    if os.path.exists(barry_active):
        return barry_active.rstrip('/')

    possible_paths = [
        '/autofs/sda1/etc/enigma2',
        '/autofs/sda2/etc/enigma2',
        '/etc/enigma2'
    ]
    for path in possible_paths:
        if os.path.exists(path):
            return path.rstrip('/')
    return '/etc/enigma2'


ENIGMA_PATH = get_enigma2_path()
CACHE_FILE = os.path.join(ENIGMA_PATH, "vavoo_epg_cache.json")
UNMATCHED_FILE = os.path.join(ENIGMA_PATH, "vavoo_epg_unmatched_cache.json")
# The stream source the user picked (YELLOW in the player) for each
# multi-source channel: {"grp:<country>:<key>": "<catalog id>"} - see
# vavoo_proxy.py's VavooProxy.set_group_source().
SOURCE_PREFS_FILE = os.path.join(ENIGMA_PATH, "vavoo_source_prefs.json")
# The last channel catalog that loaded (vavoo_proxy.save_catalog()): the
# proxy starts with it at once and fetches the new one behind it.
CATALOG_FILE = os.path.join(ENIGMA_PATH, "vavoo_catalog.json.gz")
EPGIMPORT_CONF = os.path.join(ENIGMA_PATH, "epgimport.conf")
ALIAS_FILE = os.path.join(ENIGMA_PATH, "channel_alias.json")


def _init_log(msg, level="INFO"):
    from datetime import datetime
    line = "[{0}] [{1}] [INIT] {2}".format(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), level, msg)
    try:
        print(line)
    except Exception:
        pass
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def paypal():
    conthelp = "If you like what I do you\n"
    conthelp += "can contribute with a coffee\n"
    conthelp += "scan the qr code and donate € 1.00"
    return conthelp


isDreamOS = False
if os.path.exists("/usr/bin/apt-get"):
    isDreamOS = True


def localeInit():
    if isDreamOS:
        lang = language.getLanguage()[:2]
        os.environ["LANGUAGE"] = lang
    gettext.bindtextdomain(
        PluginLanguageDomain,
        resolveFilename(
            SCOPE_PLUGINS,
            PluginLanguagePath))


if isDreamOS:
    def _(txt):
        return gettext.dgettext(PluginLanguageDomain, txt) if txt else ""
else:
    def _(txt):
        translated = gettext.dgettext(PluginLanguageDomain, txt)
        if translated:
            return translated
        else:
            _init_log(
                "fallback to default translation for %s" %
                txt, level="DEBUG")
            return gettext.gettext(txt)

localeInit()
language.addCallback(localeInit)

country_codes = {
    # Africa
    "Africa": "africa",
    "Algeria": "dz",
    "Egypt": "eg",
    "Ethiopia": "et",
    "Ghana": "gh",
    "Kenya": "ke",
    "Libya": "ly",
    "Morocco": "ma",
    "Nigeria": "ng",
    "South Africa": "za",
    "Sudan": "sd",
    "Tanzania": "tz",
    "Tunisia": "tn",
    "Uganda": "ug",

    # Americas
    "America": "us",
    "Argentina": "ar",
    "Bolivia": "bo",
    "Brazil": "br",
    "Canada": "ca",
    "Chile": "cl",
    "Colombia": "co",
    "Costa Rica": "cr",
    "Cuba": "cu",
    "Dominican Republic": "do",
    "Ecuador": "ec",
    "Guatemala": "gt",
    "Honduras": "hn",
    "Jamaica": "jm",
    "Mexico": "mx",
    "Nicaragua": "ni",
    "Panama": "pa",
    "Paraguay": "py",
    "Peru": "pe",
    "Puerto Rico": "pr",
    "Salvador": "sv",
    "El Salvador": "sv",
    "Uruguay": "uy",
    "USA": "us",
    "United States": "us",
    "Venezuela": "ve",

    # Asia
    "Afghanistan": "af",
    "Arabia": "sa",
    "Azerbaijan": "az",
    "Bangladesh": "bd",
    "China": "cn",
    "Georgia": "ge",
    "Hong Kong": "hk",
    "India": "in",
    "Indonesia": "id",
    "Iran": "ir",
    "Iraq": "iq",
    "Israel": "il",
    "Japan": "jp",
    "Jordan": "jo",
    "Kazakhstan": "kz",
    "Kuwait": "kw",
    "Lebanon": "lb",
    "Malaysia": "my",
    "Mongolia": "mn",
    "Myanmar": "mm",
    "Nepal": "np",
    "North Korea": "kp",
    "Oman": "om",
    "Pakistan": "pk",
    "Palestine": "ps",
    "Philippines": "ph",
    "Qatar": "qa",
    "Saudi Arabia": "sa",
    "Singapore": "sg",
    "South Korea": "kr",
    "Sri Lanka": "lk",
    "Syria": "sy",
    "Taiwan": "tw",
    "Thailand": "th",
    "UAE": "ae",
    "United Arab Emirates": "ae",
    "Uzbekistan": "uz",
    "Vietnam": "vn",
    "Yemen": "ye",

    # Europe
    "Albania": "al",
    "Andorra": "ad",
    "Austria": "at",
    "Balkans": "bk",
    "Baltic": "baltic",
    "Belarus": "by",
    "Belgium": "be",
    "Bosnia": "ba",
    "Bosnia Herzegovina": "ba",
    "Bulgaria": "bg",
    "Croatia": "hr",
    "Cyprus": "cy",
    "Czech": "cz",
    "Czech Republic": "cz",
    "Denmark": "dk",
    "Estonia": "ee",
    "Finland": "fi",
    "France": "fr",
    "Germany": "de",
    "Greece": "gr",
    "Holy See": "va",
    "Hungary": "hu",
    "Iceland": "is",
    "Ireland": "ie",
    "Italy": "it",
    "Kosovo": "xk",
    "Latvia": "lv",
    "Liechtenstein": "li",
    "Lithuania": "lt",
    "Luxembourg": "lu",
    "Malta": "mt",
    "Moldova": "md",
    "Monaco": "mc",
    "Montenegro": "me",
    "Netherlands": "nl",
    "North Macedonia": "mk",
    "Norway": "no",
    "Poland": "pl",
    "Portugal": "pt",
    "Romania": "ro",
    "Russia": "ru",
    "Russian Federation": "ru",
    "San Marino": "sm",
    "Scandinavia": "scandinavia",
    "Serbia": "rs",
    "Slovak Republic": "sk",
    "Slovakia": "sk",
    "Slovenia": "si",
    "Spain": "es",
    "Sweden": "se",
    "Switzerland": "ch",
    "Turkey": "tr",
    "UK": "gb",
    "Ukraine": "ua",
    "United Kingdom": "gb",
    "Vatican City": "va",

    # International / Catch-all
    "Global": "internat",
    "Great Britain": "gb",
    "Internat": "internat",
    "International": "internat",
    "Internaz": "internat",
    "World": "internat",

    # Oceania
    "Australia": "au",
    "New Zealand": "nz",
}
