# -*- coding: utf-8 -*-

from __future__ import absolute_import
__author__ = "Lululla"
__email__ = "ekekaz@gmail.com"
__copyright__ = 'Copyright (c) 2024 Lululla'
__license__ = "CC BY-NC-SA 4.0"
__version__ = "1.70"

from Components.Language import language
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
import gettext
import os
import subprocess
from sys import version_info
import threading

# Lock to serialize exports (prevents concurrent executions)
export_lock = threading.Lock()

EXPORT_IN_PROGRESS = False
PROXY_ACTIVE = False
PORT = 4323
PLUGIN_ID = 'vavoo'
PLUGIN_ROOT = resolveFilename(SCOPE_PLUGINS, "Extensions/{}".format(PLUGIN_ID))

PROXY_HOST = "127.0.0.1"
PROXY_BASE_URL = "http://{}:{}".format(PROXY_HOST, PORT)
PROXY_STATUS_URL = PROXY_BASE_URL + "/status"
PROXY_HEALTH_URL = PROXY_BASE_URL + "/health"
PROXY_COUNTRIES_URL = PROXY_BASE_URL + "/countries"
PROXY_REFRESH_URL = PROXY_BASE_URL + "/refresh_token"
PROXY_SHUTDOWN_URL = PROXY_BASE_URL + "/shutdown"

HOST_MAIN = 'https://raw.githubusercontent.com/Belfagor2005/vavoo/main'
HOST_GIT = "https://raw.githubusercontent.com/Belfagor2005"
FLAG_CACHE_DIR = "/tmp/vavoo_flags"
LOG_FILE = "/tmp/vavoo.log"
PRIMARY_BASE_URL = "https://vavoo.to"
FALLBACK_BASE_URL = "https://kool.to"
BASE_SITES = [PRIMARY_BASE_URL, FALLBACK_BASE_URL]
START_PROXY_SCRIPT = os.path.join(PLUGIN_ROOT, "start_proxy.sh")
PY2 = version_info[0] == 2
PY3 = version_info[0] == 3

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
SREF_MAP_FILE = os.path.join(ENIGMA_PATH, "vavoo_sref_map.json")
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

try:
    subprocess.run(["chmod", "+x", START_PROXY_SCRIPT])
except AttributeError:
    subprocess.call(["chmod", "+x", START_PROXY_SCRIPT])
except Exception:
    pass

country_codes = {
    "Albania": "al",
    "Arabia": "sa",
    "Balkans": "bk",
    "Bulgaria": "bg",
    "Croatia": "hr",
    "France": "fr",
    "Germany": "de",
    "Italy": "it",
    "Netherlands": "nl",
    "Poland": "pl",
    "Portugal": "pt",
    "Romania": "ro",
    "Russia": "ru",
    "Spain": "es",
    "Turkey": "tr",
    "United Kingdom": "gb"
}


satellite_positions = {
    # East satellites (positive)
    130: "13.0°E HotBird",      # 0x820000
    192: "19.2°E Astra 1",      # 0xC00000
    235: "23.5°E Astra 3",      # 0xEB0000
    282: "28.2°E Astra 2",      # 0x11A0000? Verify
    160: "16.0°E Eutelsat",     # 0xA00000
    90: "9.0°E Eutelsat",       # 0x5A0000
    70: "7.0°E Eutelsat",       # 0x460000
    48: "4.8°E Astra 4A",       # 0x300000
    42: "4.2°E?",
    39: "3.9°E?",
    36: "3.6°E?",
    33: "3.3°E?",
    31: "3.1°E?",
    28: "2.8°E?",
    26: "2.6°E?",
    23: "2.3°E?",
    21: "2.1°E?",
    19: "1.9°E BulgariaSat",    # 0x130000
    16: "1.6°E?",
    13: "1.3°E?",
    10: "1.0°E?",
    7: "0.7°E?",
    5: "0.5°E?",
    2: "0.2°E?",
    0: "0.0°E?",

    # West satellites (negative)
    -8: "0.8°W Thor",           # 0xFFF80000? Actually 3592 * 65536 = 0xE080000
    -50: "5.0°W Eutelsat",      # 3550 * 65536 = 0xDDE0000
    -125: "12.5°W Eutelsat",    # 3475 * 65536 = 0xD8C0000
    -140: "14.0°W Express",     # 3460 * 65536 = 0xD840000
    -150: "15.0°W Telstar",     # 3450 * 65536 = 0xD7A0000
    -180: "18.0°W Intelsat",    # 3420 * 65536 = 0xD3C0000
    -200: "20.0°W NSS",         # 3400 * 65536 = 0xD240000
    -220: "22.0°W SES",         # 3380 * 65536 = 0xD0C0000
    -245: "24.5°W Intelsat",    # 3355 * 65536 = 0xCEC0000
    -275: "27.5°W Intelsat",    # 3325 * 65536 = 0xCBC0000
    # 3300 * 65536 = 0xC900000? No, 0xCE40000 = 3300*65536? Calculate:
    # 3300*65536=216,268,800=0xCE40000 Yes!
    -300: "30.0°W Hispasat",
    -315: "31.5°W Hylas",       # 3285 * 65536 = 0xCD40000
    -345: "34.5°W Intelsat",    # 3255 * 65536 = 0xCB40000
    -360: "36.0°W Hispasat",    # 3240 * 65536 = 0xCA80000
    -430: "43.0°W Intelsat",    # 3170 * 65536 = 0xC620000
    -450: "45.0°W Intelsat",    # 3150 * 65536 = 0xC4E0000
    -500: "50.0°W Intelsat",    # 3100 * 65536 = 0xC1C0000
    -530: "53.0°W Intelsat",    # 3070 * 65536 = 0xBFC0000
    -555: "55.5°W Intelsat",    # 3045 * 65536 = 0xBE40000
    -580: "58.0°W Intelsat",    # 3020 * 65536 = 0xBCC0000
    -610: "61.0°W Amazonas",    # 2990 * 65536 = 0xBAC0000
    -630: "63.0°W Telstar",     # 2970 * 65536 = 0xB940000
    -650: "65.0°W Eutelsat",    # 2950 * 65536 = 0xB7C0000
    -670: "67.0°W SES",         # 2930 * 65536 = 0xB640000
    -700: "70.0°W Star One",    # 2900 * 65536 = 0xB3C0000
    -718: "71.8°W Arsat",       # 2882 * 65536 = 0xB360000
    -727: "72.7°W Nimiq",       # 2873 * 65536 = 0xB2E0000
    -739: "73.9°W Hispasat",    # 2861 * 65536 = 0xB260000
    -750: "75.0°W Star One",    # 2850 * 65536 = 0xB1E0000
    -770: "77.0°W QuetzSat",    # 2830 * 65536 = 0xB0E0000
    -788: "78.8°W Sky Mexico",  # 2812 * 65536 = 0xAFC0000
    -810: "81.0°W Arsat",       # 2790 * 65536 = 0xAE60000
    -820: "82.0°W Nimiq",       # 2780 * 65536 = 0xADC0000
    -871: "87.1°W SES",         # 2729 * 65536 = 0xAA80000
    -890: "89.0°W Galaxy",      # 2710 * 65536 = 0xA8C0000
    -910: "91.0°W Galaxy",      # 2690 * 65536 = 0xA700000
    -950: "95.0°W Galaxy",      # 2650 * 65536 = 0xA380000
    -970: "97.0°W Galaxy",      # 2630 * 65536 = 0xA1C0000
    # 2608 * 65536 = 0xA000000? 2608*65536=170,917,888=0xA300000? No, calculate:
    # 2608*65536=170,917,888=0xA300000
    -992: "99.2°W Galaxy",
    -1010: "101.0°W SES",       # 2590 * 65536 = 0xA180000
    -1030: "103.0°W SES",       # 2570 * 65536 = 0xA000000? 2570*65536=168,427,520=0xA0A0000
    -1050: "105.0°W AMC",       # 2550 * 65536 = 0x9F60000
    -1073: "107.3°W Anik",      # 2527 * 65536 = 0x9DC0000
    -1100: "110.0°W EchoStar",  # 2500 * 65536 = 0x9C40000
    -1130: "113.0°W Eutelsat",  # 2470 * 65536 = 0x9AC0000
    # 2451 * 65536 = 0x9900000? 2451*65536=160,563,200=0x9920000
    -1149: "114.9°W Eutelsat",
    -1170: "117.0°W Eutelsat",  # 2430 * 65536 = 0x97E0000
    -1190: "119.0°W Anik",      # 2410 * 65536 = 0x96A0000
    -1210: "121.0°W EchoStar",  # 2390 * 65536 = 0x9560000
    -1230: "123.0°W Galaxy",    # 2370 * 65536 = 0x9420000
    -1250: "125.0°W AMC",       # 2350 * 65536 = 0x92E0000
    -1290: "129.0°W Ciel",      # 2310 * 65536 = 0x9060000
    -1330: "133.0°W Galaxy",    # 2270 * 65536 = 0x8DE0000
}
