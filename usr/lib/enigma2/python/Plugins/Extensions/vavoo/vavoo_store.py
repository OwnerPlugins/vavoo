# -*- coding: utf-8 -*-
"""The plugin's lists and data, as in the Android app
(pQu4k3r/vavoo_android: Repository, Parental, Backup, Monogram,
SearchText): favourites with folders and their order, hidden countries,
parental control (PIN, adult channels, the pause after wrong PINs),
backup / restore, a channel's initials and colour, the search rules,
and the small pictures drawn for them (initials tiles, padlock).

No Enigma2 imports (like vavoo_theme.py): plugin.py and vUtils.py use
it on the box, the tests import it off the box. Everything is kept
under the data folder (/etc/enigma2), which a plugin update does not
touch - the plugin folder is deleted by every update (installer.sh,
CONTROL/preinst).
"""
from __future__ import absolute_import, division, print_function

import binascii
import hashlib
import json
import os
import re
import struct
import sys
import threading
import time
import unicodedata
import zlib

PY2 = sys.version_info[0] == 2
if PY2:
    text_type = unicode  # noqa: F821
else:
    text_type = str

# ------------------------------------------------------------------ paths

DATA_DIR = "/etc/enigma2"
PLUGIN_DIR = None
TILE_DIR = "/tmp/vavoo_tiles"


def set_paths(data_dir=None, plugin_dir=None, tile_dir=None):
    """Where the files live (plugin.py: ENIGMA_PATH / PLUGIN_ROOT; the
    tests: a temporary folder)."""
    global DATA_DIR, PLUGIN_DIR, TILE_DIR
    if data_dir:
        DATA_DIR = data_dir
    if plugin_dir:
        PLUGIN_DIR = plugin_dir
    if tile_dir:
        TILE_DIR = tile_dir
    _fav_cache[0] = None


def data_file(name):
    return os.path.join(DATA_DIR, name)


def favourites_file():
    return data_file("vavoo_favourites.json")


def recent_file():
    return data_file("vavoo_recent.json")


def source_prefs_file():
    return data_file("vavoo_source_prefs.json")


def hidden_countries_file():
    return data_file("vavoo_hidden_countries.json")


def parental_file():
    return data_file("vavoo_parental.json")


def timers_file():
    return data_file("vavoo_timers.json")


def bouquet_list_file():
    """The exported bouquets that "Scheduled List" re-exports (one
    `name|url|flat or hierarchical|time` per line) - Favorite.txt in
    the plugin folder before."""
    return data_file("vavoo_bouquet_list.txt")


def _old_plugin_file(name):
    return os.path.join(PLUGIN_DIR, name) if PLUGIN_DIR else None


# ---------------------------------------------------------------- helpers

def to_text(value):
    if value is None:
        return u""
    if isinstance(value, text_type):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "ignore")
    return text_type(value)


def _read_json(path, default):
    try:
        if not path or not os.path.isfile(path):
            return default
        with open(path, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except Exception as e:
        print("[vavoo_store] Cannot read {}: {}".format(path, e))
        return default


def _write_json(path, data, indent=1):
    """Atomic: a temporary file, then a rename."""
    try:
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        temp = path + ".tmp"
        text = json.dumps(data, indent=indent, ensure_ascii=False,
                          sort_keys=False)
        with open(temp, "wb") as f:
            f.write(to_text(text).encode("utf-8"))
        os.rename(temp, path)
        return True
    except Exception as e:
        print("[vavoo_store] Cannot write {}: {}".format(path, e))
        return False


def _now_text():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def uptime():
    """Seconds since the box started (the app's elapsedRealtime): the
    unlock time and the PIN pause do not follow the clock when it is
    set (NTP at start)."""
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except Exception:
        return time.time()


def boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip()
    except Exception:
        return ""


def lower_key(text):
    return to_text(text).strip().lower()


# ------------------------------------------------------------- favourites
#
# The file: {"format": "vavoo_favourites", "version": 2,
#            "favourites": [{name, url, country_name, country_code,
#                            logo, folder, timestamp}, ...]}
# in the order the user chose (new ones at the end, as in the app).
# A channel is its address (the proxy's /vavoo?channel=<id>), as
# before. "folder" is missing for a favourite in no folder.

FAVOURITES_FORMAT = "vavoo_favourites"
_fav_lock = threading.RLock()
# [(mtime, size), entries] - read again only when the file changed
_fav_cache = [None, None]

ENTRY_KEYS = ("name", "url", "country_name", "country_code", "logo",
              "folder", "timestamp")


def _clean_entry(entry):
    if not isinstance(entry, dict):
        return None
    name = to_text(entry.get("name")).strip()
    url = to_text(entry.get("url")).strip()
    if not name or not url:
        return None
    out = {"name": name, "url": url}
    for key in ("country_name", "country_code", "logo", "timestamp"):
        value = entry.get(key)
        out[key] = to_text(value) if value else u""
    folder = to_text(entry.get("folder")).strip()
    if folder:
        out["folder"] = folder
    return out


def _entries_from(data):
    """The favourites of a file, old format or new: the old one was a
    dict {"name###url": entry} written sorted by key, so its order
    is gone - the time each was added gives it back."""
    if isinstance(data, dict) and isinstance(data.get("favourites"), list):
        raw = data["favourites"]
    elif isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = sorted(
            [value for value in data.values() if isinstance(value, dict)],
            key=lambda e: (to_text(e.get("timestamp")),
                           lower_key(e.get("name"))))
    else:
        raw = []
    seen = set()
    out = []
    for entry in raw:
        entry = _clean_entry(entry)
        if entry is None or entry["url"] in seen:
            continue
        seen.add(entry["url"])
        out.append(entry)
    return out


def migrate_old_files():
    """Moves the favourites and the bouquet list out of the plugin
    folder (an update deletes it). Only when the new file is not there
    yet; the old one is removed once the new one is written."""
    moved = []
    with _fav_lock:
        old = _old_plugin_file("vavoo_favourites.json")
        new = favourites_file()
        if old and os.path.isfile(old) and not os.path.isfile(new):
            entries = _entries_from(_read_json(old, {}))
            if _save_favourites(entries):
                moved.append(new)
                try:
                    os.remove(old)
                except Exception:
                    pass
    old = _old_plugin_file("Favorite.txt")
    new = bouquet_list_file()
    if old and os.path.isfile(old) and not os.path.isfile(new):
        try:
            with open(old, "rb") as f:
                data = f.read()
            temp = new + ".tmp"
            with open(temp, "wb") as f:
                f.write(data)
            os.rename(temp, new)
            os.remove(old)
            moved.append(new)
        except Exception as e:
            print("[vavoo_store] Cannot move {}: {}".format(old, e))
    return moved


def _file_stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime, st.st_size)
    except Exception:
        return None


def _load_entries():
    """The cached list itself - callers copy before handing it out."""
    path = favourites_file()
    stamp = _file_stamp(path)
    if stamp is not None and _fav_cache[0] == stamp:
        return _fav_cache[1]
    entries = _entries_from(_read_json(path, []))
    _fav_cache[0] = stamp
    _fav_cache[1] = entries
    return entries


def _save_favourites(entries):
    path = favourites_file()
    ok = _write_json(path, {"format": FAVOURITES_FORMAT, "version": 2,
                            "favourites": entries})
    if ok:
        _fav_cache[0] = _file_stamp(path)
        _fav_cache[1] = entries
    return ok


def load_favourites():
    """[entry] in the user's order (copies: change them freely)."""
    with _fav_lock:
        return [dict(entry) for entry in _load_entries()]


def favourite_urls():
    with _fav_lock:
        return set(entry["url"] for entry in _load_entries())


def is_favourite(url):
    return to_text(url) in favourite_urls()


def find_favourite(url):
    url = to_text(url)
    with _fav_lock:
        for entry in _load_entries():
            if entry["url"] == url:
                return dict(entry)
    return None


def add_favourite(name, url, country_name=None, country_code=None,
                  logo=None):
    """At the end, as in the app. False if it was one already."""
    with _fav_lock:
        entries = list(_load_entries())
        url = to_text(url)
        if any(entry["url"] == url for entry in entries):
            return False
        entry = _clean_entry({"name": name, "url": url,
                              "country_name": country_name,
                              "country_code": country_code,
                              "logo": logo, "timestamp": _now_text()})
        if entry is None:
            return None
        entries.append(entry)
        return True if _save_favourites(entries) else None


def remove_favourite(url):
    """Removed with its folder (added again, it starts in none)."""
    with _fav_lock:
        url = to_text(url)
        entries = [entry for entry in _load_entries()
                   if entry["url"] != url]
        if len(entries) == len(_load_entries()):
            return False
        return True if _save_favourites(entries) else None


def toggle_favourite(name, url, country_name=None, country_code=None,
                     logo=None):
    """True = a favourite now, False = not any more, None = error."""
    with _fav_lock:
        if is_favourite(url):
            result = remove_favourite(url)
            return None if result is None else False
        return add_favourite(name, url, country_name, country_code, logo)


def clear_favourites():
    with _fav_lock:
        return _save_favourites([])


def set_folder(url, folder):
    """Puts a favourite in a folder (None / "" = in none)."""
    folder = to_text(folder).strip()
    url = to_text(url)
    with _fav_lock:
        entries = [dict(entry) for entry in _load_entries()]
        changed = False
        for entry in entries:
            if entry["url"] != url:
                continue
            if folder and entry.get("folder") != folder:
                entry["folder"] = folder
                changed = True
            elif not folder and "folder" in entry:
                del entry["folder"]
                changed = True
        if not changed:
            return False
        return _save_favourites(entries)


def folder_of(url):
    entry = find_favourite(url)
    return entry.get("folder") if entry else None


def folders():
    """Folders holding at least one favourite (an empty folder does not
    exist), A-Z whatever the case."""
    with _fav_lock:
        names = set(entry["folder"] for entry in _load_entries()
                    if entry.get("folder"))
    return sorted(names, key=lambda n: (n.lower(), n))


def rename_folder(old, new):
    """Renamed; given another folder's name, the two become one."""
    old = to_text(old)
    new = to_text(new).strip()
    if not new or new == old:
        return False
    with _fav_lock:
        entries = [dict(entry) for entry in _load_entries()]
        changed = False
        for entry in entries:
            if entry.get("folder") == old:
                entry["folder"] = new
                changed = True
        return _save_favourites(entries) if changed else False


def delete_folder(name):
    """The folder goes, its channels stay favourites (in no folder)."""
    name = to_text(name)
    with _fav_lock:
        entries = [dict(entry) for entry in _load_entries()]
        changed = False
        for entry in entries:
            if entry.get("folder") == name:
                del entry["folder"]
                changed = True
        return _save_favourites(entries) if changed else False


def reorder_favourites(urls):
    """Puts the favourites listed in `urls` in that order, in the
    places those favourites already held (Repository.
    reorderFavourites): a folder's channels only change places among
    themselves, the others keep theirs. One write."""
    with _fav_lock:
        entries = list(_load_entries())
        wanted = set(to_text(url) for url in urls)
        by_url = dict((entry["url"], entry) for entry in entries)
        order = []
        seen = set()
        for url in urls:
            url = to_text(url)
            if url in by_url and url not in seen:
                seen.add(url)
                order.append(by_url[url])
        order = iter(order)
        result = []
        changed = False
        for entry in entries:
            if entry["url"] in wanted:
                nxt = next(order, None)
                if nxt is not None:
                    if nxt["url"] != entry["url"]:
                        changed = True
                    result.append(nxt)
                    continue
            result.append(entry)
        if not changed:
            return False
        return _save_favourites(result)


def repair_favourites(country_name, rows):
    """A country's channel list just came in: a favourite of that
    country whose address is not in it any more (a new id in the
    catalog) takes the address of the channel with the same name
    (Repository.repairFavourites). rows: [{name, url, logo}]. Returns
    how many changed."""
    country = lower_key(country_name)
    if not country or not rows:
        return 0
    urls = set()
    by_name = {}
    for row in rows:
        url = to_text(row.get("url"))
        urls.add(url)
        key = lower_key(row.get("name"))
        if key and key not in by_name:
            by_name[key] = row
    with _fav_lock:
        entries = [dict(entry) for entry in _load_entries()]
        taken = set(entry["url"] for entry in entries)
        changed = 0
        for entry in entries:
            if lower_key(entry.get("country_name")) != country:
                continue
            if entry["url"] in urls:
                continue
            row = by_name.get(lower_key(entry["name"]))
            if row is None:
                continue
            new_url = to_text(row.get("url"))
            if not new_url or new_url in taken:
                continue
            taken.discard(entry["url"])
            taken.add(new_url)
            entry["url"] = new_url
            if row.get("logo"):
                entry["logo"] = to_text(row.get("logo"))
            changed += 1
        if changed:
            _save_favourites(entries)
        return changed


# -------------------------------------------------------- hidden countries

def hidden_countries():
    data = _read_json(hidden_countries_file(), [])
    if not isinstance(data, list):
        return set()
    return set(to_text(name) for name in data if name)


def set_hidden_countries(names):
    if not isinstance(names, (list, tuple, set)):
        names = []
    return _write_json(hidden_countries_file(),
                       sorted(set(to_text(n) for n in names if n),
                              key=lambda n: n.lower()))


def visible_countries(countries):
    hidden = hidden_countries()
    if not hidden:
        return list(countries)
    return [c for c in countries if to_text(c) not in hidden]


# --------------------------------------------------------------- parental
#
# vavoo_parental.json: {"pin": sha256(salt + pin) hex, "salt": 8 random
# bytes hex, "pin_len": 4, "pin_digits": true, "countries": [...],
# "adult": true, "settings": false, "wrong": 0, "blocks": 0,
# "blocked_until": epoch s, "blocked_until_up": uptime s, "boot": id}

UNLOCK_SECONDS = 15 * 60
PIN_TRIES = 5
PIN_BLOCK_SECONDS = 30
PIN_BLOCK_MAX = 10 * 60
_parental_lock = threading.RLock()
_unlocked_at = [0.0]

# Whole words; "Adult Swim" is a cartoon channel (Parental.ADULT).
# (?<![^\W_]) = not after a letter or digit.
ADULT_RE = re.compile(
    u"(?<![^\\W_])(xxx|adult(?!\\s*swim)[eoi]?s?|18\\+|porn\\w*|"
    u"erot(?:ic|ik|ique|ica|ico|yk)\\w*|playboy|hustler|brazzers|"
    u"redlight|dorcel|private\\s?tv|penthouse)(?![^\\W_])",
    re.I | re.U)


def _parental():
    data = _read_json(parental_file(), {})
    return data if isinstance(data, dict) else {}


def _number(value, default=0):
    """A number from a file that may have been edited by hand or broken:
    the default when it is not one."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _save_parental(data):
    return _write_json(parental_file(), data)


def _hash_pin(pin, salt):
    return hashlib.sha256(
        (to_text(salt) + to_text(pin)).encode("utf-8")).hexdigest()


def has_pin():
    return bool(_parental().get("pin"))


def pin_length():
    """Digits the PIN pad waits for before it checks (4; an older PIN
    carried over may be another length)."""
    try:
        return int(_parental().get("pin_len") or 4)
    except Exception:
        return 4


def pin_is_digits():
    return bool(_parental().get("pin_digits", True))


def set_pin(pin):
    """A new PIN (None / "" = removed: nothing locked any more, the
    lock choices stay). Setting one also unlocks."""
    with _parental_lock:
        data = _parental()
        pin = to_text(pin)
        if not pin:
            for key in ("pin", "salt", "pin_len", "pin_digits"):
                data.pop(key, None)
            return _save_parental(data)
        salt = binascii.hexlify(os.urandom(8)).decode("ascii")
        data["salt"] = salt
        data["pin"] = _hash_pin(pin, salt)
        data["pin_len"] = len(pin)
        data["pin_digits"] = pin.isdigit()
        ok = _save_parental(data)
        if ok:
            unlock()
        return ok


def unlock():
    _unlocked_at[0] = uptime()


def relock():
    """The plugin was left."""
    _unlocked_at[0] = 0.0


def is_unlocked():
    if not has_pin():
        return True
    at = _unlocked_at[0]
    return bool(at) and 0 <= uptime() - at < UNLOCK_SECONDS


def locked_countries():
    data = _parental().get("countries")
    return set(to_text(c) for c in data) if isinstance(data, list) else set()


def set_locked_countries(names):
    with _parental_lock:
        data = _parental()
        data["countries"] = sorted(set(to_text(n) for n in names if n),
                                   key=lambda n: n.lower())
        return _save_parental(data)


def lock_adult():
    return bool(_parental().get("adult", True))


def lock_settings():
    return bool(_parental().get("settings", False))


def set_option(key, value):
    """"adult" / "settings"."""
    with _parental_lock:
        data = _parental()
        data[key] = bool(value)
        return _save_parental(data)


def is_adult(name, group=None):
    return bool(ADULT_RE.search(to_text(name)) or
                (group and ADULT_RE.search(to_text(group))))


def is_country_locked(country):
    if not has_pin():
        return False
    country = lower_key(country)
    return any(lower_key(c) == country for c in locked_countries())


def is_channel_locked(name, country=None, group=None):
    """Needs the PIN when one is set: its country is locked, or it is
    an adult channel (name or category) and those are locked."""
    if not has_pin():
        return False
    if country and is_country_locked(country):
        return True
    return lock_adult() and is_adult(name, group)


def needs_pin_for_country(country):
    return is_country_locked(country) and not is_unlocked()


def needs_pin_for_channel(name, country=None, group=None):
    return is_channel_locked(name, country, group) and not is_unlocked()


def needs_pin_for_settings():
    return has_pin() and lock_settings() and not is_unlocked()


def pin_wait():
    """Seconds left of the pause after too many wrong PINs (0 = none).
    The clock set back does not end it: the time since start counts
    too, in the same start."""
    with _parental_lock:
        data = _parental()
        if "blocked_until" not in data:
            return 0
        left = _number(data.get("blocked_until")) - time.time()
        wall = 0 if left > PIN_BLOCK_MAX else max(0, left)
        boot_left = 0
        if data.get("boot") and data.get("boot") == boot_id():
            up_left = _number(data.get("blocked_until_up")) - uptime()
            if 0 < up_left <= PIN_BLOCK_MAX:
                boot_left = up_left
        wait = max(wall, boot_left)
        if wait <= 0:
            for key in ("blocked_until", "blocked_until_up", "boot"):
                data.pop(key, None)
            _save_parental(data)
            return 0
        return int(wait + 0.999)


def check_pin(pin):
    """("ok", 0) | ("wrong", 0) | ("blocked", seconds). Five wrong in a
    row: a pause of 30 s, 2 min, 8 min, then 10 min."""
    with _parental_lock:
        wait = pin_wait()
        if wait:
            return "blocked", wait
        data = _parental()
        stored = data.get("pin")
        if stored and _hash_pin(pin, data.get("salt", "")) == stored:
            for key in ("wrong", "blocks", "blocked_until",
                        "blocked_until_up", "boot"):
                data.pop(key, None)
            _save_parental(data)
            unlock()
            return "ok", 0
        wrong = int(_number(data.get("wrong"))) + 1
        if wrong >= PIN_TRIES:
            blocks = int(_number(data.get("blocks")))
            seconds = min(PIN_BLOCK_SECONDS << min(2 * blocks, 6),
                          PIN_BLOCK_MAX)
            data["wrong"] = 0
            data["blocks"] = blocks + 1
            data["blocked_until"] = time.time() + seconds
            data["blocked_until_up"] = uptime() + seconds
            data["boot"] = boot_id()
            _save_parental(data)
            return "blocked", seconds
        data["wrong"] = wrong
        _save_parental(data)
        return "wrong", 0


def migrate_parental(old_pin, old_countries):
    """The PIN and locked countries kept in the settings before (the
    PIN in clear): into vavoo_parental.json, the PIN hashed. Only when
    no PIN is set here yet. Returns True when something moved."""
    old_pin = to_text(old_pin).strip()
    names = [to_text(n).strip() for n in to_text(old_countries).split(",")]
    names = [n for n in names if n]
    if not old_pin and not names:
        return False
    with _parental_lock:
        if has_pin():
            return False
        if names:
            set_locked_countries(set(names) | locked_countries())
        if old_pin:
            set_pin(old_pin)
            relock()
        return True


# ----------------------------------------------------------------- timers
#
# vavoo_timers.json: {"format": "vavoo_timers", "version": 1,
#   "timers": [{"id", "kind": "remind" (phase 5: "record"), "url",
#               "name", "country", "country_code", "logo", "title",
#               "start", "stop"}]}
# (the app's Timers.kt). A reminder goes off at its programme's start;
# one missed by more than a minute (the box was off) is dropped.

TIMERS_FORMAT = "vavoo_timers"
KIND_REMIND = "remind"
KIND_RECORD = "record"
# a recording starts this much before the programme (phase 5)
RECORD_MARGIN = 120
_timer_lock = threading.RLock()
_timer_cache = [None, None]


def _clean_timer(entry):
    if not isinstance(entry, dict):
        return None
    try:
        start = int(float(entry.get("start")))
        stop = int(float(entry.get("stop") or start))
    except Exception:
        return None
    try:
        timer_id = int(entry.get("id") or 0)
    except Exception:
        # (a hand-edited id: a new one - the timer is kept)
        timer_id = start * 1000
    kind = to_text(entry.get("kind")) or KIND_REMIND
    url = to_text(entry.get("url")).strip()
    if not url or kind not in (KIND_REMIND, KIND_RECORD):
        return None
    out = {"id": timer_id, "kind": kind, "url": url,
           "start": start, "stop": max(stop, start)}
    for key in ("name", "country", "country_code", "logo", "title"):
        out[key] = to_text(entry.get(key) or u"")
    return out


def _load_timer_entries():
    path = timers_file()
    stamp = _file_stamp(path)
    if stamp is not None and _timer_cache[0] == stamp:
        return _timer_cache[1]
    data = _read_json(path, {})
    raw = data.get("timers") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        # (not a list of timers: a broken or hand-edited file)
        raw = []
    entries = [t for t in (_clean_timer(e) for e in raw) if t]
    entries.sort(key=lambda t: (t["start"], t["id"]))
    _timer_cache[0] = stamp
    _timer_cache[1] = entries
    return entries


def _save_timers(entries):
    entries = sorted(entries, key=lambda t: (t["start"], t["id"]))
    path = timers_file()
    ok = _write_json(path, {"format": TIMERS_FORMAT, "version": 1,
                            "timers": entries})
    if ok:
        _timer_cache[0] = _file_stamp(path)
        _timer_cache[1] = entries
    return ok


def load_timers(kind=None):
    """[timer] by start time (copies)."""
    with _timer_lock:
        return [dict(t) for t in _load_timer_entries()
                if kind is None or t["kind"] == kind]


def alarm_time(timer):
    """When a timer goes off: a reminder at its start, a recording a
    little before."""
    if timer["kind"] == KIND_RECORD:
        return timer["start"] - RECORD_MARGIN
    return timer["start"]


def find_timer(url, start, kind=KIND_REMIND):
    url = to_text(url)
    with _timer_lock:
        for t in _load_timer_entries():
            if t["url"] == url and t["start"] == int(start) and \
                    t["kind"] == kind:
                return dict(t)
    return None


def add_timer(kind, url, name, title, start, stop, country=None,
              country_code=None, logo=None):
    """A new timer (it replaces one of the same kind, channel and
    start). Returns it, or None."""
    entry = _clean_timer({
        "id": int(time.time() * 1000), "kind": kind, "url": url,
        "name": name, "title": title, "start": start, "stop": stop,
        "country": country, "country_code": country_code, "logo": logo})
    if entry is None:
        return None
    with _timer_lock:
        entries = [t for t in _load_timer_entries()
                   if not (t["kind"] == entry["kind"] and
                           t["url"] == entry["url"] and
                           t["start"] == entry["start"])]
        if any(t["id"] == entry["id"] for t in entries):
            entry["id"] = max(t["id"] for t in entries) + 1
        entries.append(entry)
        return entry if _save_timers(entries) else None


def remove_timer(timer_id):
    with _timer_lock:
        entries = _load_timer_entries()
        kept = [t for t in entries if t["id"] != timer_id]
        if len(kept) == len(entries):
            return False
        return _save_timers(kept)


def prune_timers(now=None):
    """Drops reminders missed by more than a minute and recordings
    that have ended. Returns how many went."""
    now = time.time() if now is None else now
    with _timer_lock:
        entries = _load_timer_entries()
        kept = [t for t in entries
                if (t["kind"] == KIND_REMIND and t["start"] > now - 60) or
                (t["kind"] == KIND_RECORD and
                 t["stop"] + RECORD_MARGIN > now)]
        if len(kept) != len(entries):
            _save_timers(kept)
        return len(entries) - len(kept)


def due_timers(now=None, kind=None):
    """The timers that go off now, taken out of the file (the app's
    take()): each goes off once."""
    now = time.time() if now is None else now
    with _timer_lock:
        entries = _load_timer_entries()
        due = [t for t in entries if alarm_time(t) <= now and
               (kind is None or t["kind"] == kind)]
        if due:
            ids = set(t["id"] for t in due)
            _save_timers([t for t in entries if t["id"] not in ids])
        return [dict(t) for t in due]


def next_alarm(kind=None):
    times = [alarm_time(t) for t in load_timers(kind)]
    return min(times) if times else None


# ----------------------------------------------------------------- backup

BACKUP_FORMAT = "vavoo_e2_backup"
BACKUP_PREFIX = "VavooStream-backup"
# (then the data folder itself, when no disk can be written)
BACKUP_MEDIA = ("/media/hdd", "/media/usb", "/media/mmc")
# Settings that stay with the box (as the app: parental control is not
# carried out by a backup, nor removed by a restore).
BACKUP_SKIP_SETTINGS = ("parental_pin", "parental_countries",
                        "last_update")


def backup_dirs():
    return list(BACKUP_MEDIA) + [DATA_DIR]


def _writable(folder):
    return os.path.isdir(folder) and os.access(folder, os.W_OK)


def build_backup(settings, version=""):
    """settings: {name: saved text} of the plugin's settings."""
    clean = dict((to_text(k), to_text(v)) for k, v in settings.items()
                 if k not in BACKUP_SKIP_SETTINGS)
    recent = _read_json(recent_file(), [])
    prefs = _read_json(source_prefs_file(), {})
    return {
        "format": BACKUP_FORMAT,
        "version": to_text(version),
        "saved": int(time.time() * 1000),
        "settings": clean,
        "favourites": load_favourites(),
        "recent": recent if isinstance(recent, list) else [],
        "source_prefs": prefs if isinstance(prefs, dict) else {},
        "hidden_countries": sorted(hidden_countries()),
        "timers": load_timers(),
    }


def write_backup(settings, version="", folders=None):
    """Into the first folder that can be written. Returns the file's
    path, or None."""
    data = build_backup(settings, version)
    name = "{}-{}.json".format(BACKUP_PREFIX,
                               time.strftime("%Y%m%d-%H%M",
                                             time.localtime()))
    for folder in (folders or backup_dirs()):
        if not _writable(folder):
            continue
        path = os.path.join(folder, name)
        if _write_json(path, data):
            return path
    return None


def list_backups(folders=None):
    """[(path, mtime)], newest first."""
    found = []
    for folder in (folders or backup_dirs()):
        try:
            names = os.listdir(folder)
        except Exception:
            continue
        for name in names:
            if name.startswith(BACKUP_PREFIX) and name.endswith(".json"):
                path = os.path.join(folder, name)
                try:
                    found.append((path, os.path.getmtime(path)))
                except Exception:
                    pass
    found.sort(key=lambda item: item[1], reverse=True)
    return found


def read_backup(path):
    """The backup, or None when the file is not one."""
    data = _read_json(path, None)
    if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
        return None
    return data


def restore_backup(data):
    """Replaces the lists with the backup's (it does not merge).
    Returns the settings to apply ({name: saved text}); the caller sets
    them, saves the settings and restarts the proxy."""
    with _fav_lock:
        _save_favourites(_entries_from(data.get("favourites") or []))
    recent = data.get("recent")
    _write_json(recent_file(), recent if isinstance(recent, list) else [])
    prefs = data.get("source_prefs")
    _write_json(source_prefs_file(), prefs if isinstance(prefs, dict) else {})
    set_hidden_countries(data.get("hidden_countries") or [])
    timers = data.get("timers")
    if not isinstance(timers, list):
        timers = []
    with _timer_lock:
        _save_timers([t for t in (_clean_timer(e) for e in timers) if t])
    settings = data.get("settings")
    if not isinstance(settings, dict):
        return {}
    return dict((to_text(k), to_text(v)) for k, v in settings.items()
                if k not in BACKUP_SKIP_SETTINGS)


# ---------------------------------------------------------- factory reset

# Every file the plugin keeps in the data folder (/etc/enigma2) - all of
# them go in a factory reset. A new data file goes in here too
# (tests/test_audit.py checks every vavoo_* name the plugin writes is).
# Not here: the backups (VavooStream-backup-*.json, the user's own) and
# disable_vavoo_stats (the statistics choice is kept).
RESET_FILES = (
    "vavoo_favourites.json", "vavoo_recent.json", "vavoo_timers.json",
    "vavoo_parental.json", "vavoo_hidden_countries.json",
    "vavoo_source_prefs.json", "vavoo_bouquet_list.txt", "vavoo_memory.log",
    "vavoo_epg_cache.json", "vavoo_epg_unmatched_cache.json",
    "vavoo_catalog.json.gz", "vavoo_catalog.json.gz.tmp",
    # older versions'
    "vavoo_sref_map.json", "channel_alias.json",
)
# what older versions kept in the plugin folder
RESET_OLD_PLUGIN_FILES = ("vavoo_favourites.json", "Favorite.txt")


def factory_reset():
    """The data files deleted (RESET_FILES, and the old ones in the
    plugin folder), the lists' memory forgotten and the PIN locked
    again. Returns the paths deleted."""
    removed = []
    paths = [data_file(name) for name in RESET_FILES]
    paths += [p for p in (_old_plugin_file(n)
                          for n in RESET_OLD_PLUGIN_FILES) if p]
    with _fav_lock:
        with _timer_lock:
            for path in paths:
                for each in (path, path + ".tmp"):
                    try:
                        if os.path.isfile(each):
                            os.remove(each)
                            removed.append(each)
                    except Exception as e:
                        print(
                            "[vavoo_store] Not deleted {}: {}".format(
                                each, e))
            _fav_cache[0] = _fav_cache[1] = None
            _timer_cache[0] = _timer_cache[1] = None
    relock()
    return removed


# --------------------------------------------------------------- initials

_BRACKETS = re.compile(u"\\(.*?\\)|\\[.*?\\]", re.U)
_WORD_SEPARATORS = re.compile(u"[\\s._\\-+/|]+", re.U)
_TAGS = set(("HD", "FHD", "UHD", "SD", "4K", "HEVC", "H265", "B", "C", "S",
             "BACKUP"))


def _is_letter_or_digit(ch):
    return ch.isalnum()


def initials(name):
    """First letters of the first two words, or of the word and its
    number ("RAI 1" -> "R1", "Canale 5" -> "C5"); "TV" when nothing is
    left (Monogram.initials)."""
    text = _BRACKETS.sub(u" ", to_text(name))
    words = [w for w in _WORD_SEPARATORS.split(text)
             if any(_is_letter_or_digit(c) for c in w)]
    words = [w for w in words if w.upper() not in _TAGS]
    if not words:
        return u"TV"
    first = next(c for c in words[0] if _is_letter_or_digit(c)).upper()
    second = u""
    if len(words) > 1:
        second = next((c for c in words[1] if _is_letter_or_digit(c)), u"")
        second = second.upper()
    return (first + second)[:2] if second else first[:1]


def java_hash(text):
    """Java's String.hashCode() (over UTF-16 code units), as a signed
    32-bit int."""
    h = 0
    data = bytearray(to_text(text).encode("utf-16-be"))
    for i in range(0, len(data), 2):
        h = (31 * h + (data[i] << 8 | data[i + 1])) & 0xFFFFFFFF
    return h - 0x100000000 if h & 0x80000000 else h


def hue_for(name):
    """0-359, the same as the app's for the same name."""
    return ((java_hash(to_text(name).upper()) & 0x7fffffff) % 360)


def hsv_to_rgb(hue, sat, val):
    """Android's Color.HSVToColor (hue in degrees)."""
    h = (hue % 360) / 60.0
    i = int(h)
    f = h - i
    p = val * (1 - sat)
    q = val * (1 - sat * f)
    t = val * (1 - sat * (1 - f))
    r, g, b = [(val, t, p), (q, val, p), (p, val, t), (p, q, val),
               (t, p, val), (val, p, q)][i % 6]
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))


TILE_HUES = 36


def tile_hue(name):
    """The hue of a channel's tile, rounded to one of TILE_HUES (each
    a picture drawn once)."""
    step = 360 // TILE_HUES
    return (hue_for(name) + step // 2) // step * step % 360


def color_for(name):
    return hsv_to_rgb(hue_for(name), 0.55, 0.62)


# ------------------------------------------------------------------ search

_SEARCH_SEPARATORS = re.compile(u"[\\W_]+", re.U)


def normalize(text):
    """Lower case, accents removed, words separated by single spaces
    (SearchText.normalize)."""
    plain = unicodedata.normalize("NFD", to_text(text))
    plain = u"".join(c for c in plain if unicodedata.category(c) != "Mn")
    folded = plain.lower().replace(u"ı", u"i").replace(u"ß", u"ss")
    return _SEARCH_SEPARATORS.sub(u" ", folded).strip()


def search_words(query):
    return [w for w in normalize(query).split(u" ") if w]


def search_matches(normalized_name, words):
    """Every word of the query is in the name, in any order: at the
    start of one of its words, or (3+ letters) anywhere; a number must
    be a whole number of the name ("1" finds "SPORT 1" and "SPORT1",
    not "SPORT 11")."""
    if not words:
        return False
    name_words = normalized_name.split(u" ")
    for w in words:
        if w.isdigit():
            found = False
            for n in name_words:
                if n == w:
                    found = True
                elif (n.endswith(w) and len(n) > len(w) and
                      not n[len(n) - len(w) - 1].isdigit()):
                    found = True
                if found:
                    break
            if not found:
                return False
        else:
            if not (any(n.startswith(w) for n in name_words) or
                    (len(w) >= 3 and w in normalized_name)):
                return False
    return True


def search(items, query, name_of=lambda item: item):
    """The items whose name matches, names starting with the query's
    first word first, then A-Z (Repository.search)."""
    words = search_words(query)
    if not words:
        return []
    found = []
    for item in items:
        normalized = normalize(name_of(item))
        if search_matches(normalized, words):
            found.append((not normalized.startswith(words[0]), normalized,
                          item))
    found.sort(key=lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in found]


# ------------------------------------------------------------- pictures
#
# A minimal PNG writer (Python only, no Pillow on a box) for the
# pictures that depend on the channel: the initials tile (a rounded
# square in the channel's colour; Enigma2 writes the letters over it)
# and the padlock of a locked country. Drawn once each, in TILE_DIR.

_mask_cache = {}


def _png(width, height, rows):
    """rows: bytes of RGBA per row."""
    def chunk(kind, data):
        body = kind + data
        return (struct.pack(">I", len(data)) + body +
                struct.pack(">I", binascii.crc32(body) & 0xFFFFFFFF))
    raw = b"".join(b"\x00" + row for row in rows)
    return (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6,
                                       0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _coverage(width, height, inside, samples=4):
    """Alpha 0-255 per pixel of a shape (inside(x, y) for points in
    pixel units), sampled samples x samples per pixel."""
    out = []
    step = 1.0 / samples
    total = samples * samples
    for y in range(height):
        row = []
        for x in range(width):
            hits = 0
            for sy in range(samples):
                py = y + (sy + 0.5) * step
                for sx in range(samples):
                    if inside(x + (sx + 0.5) * step, py):
                        hits += 1
            row.append(int(round(255.0 * hits / total)))
        out.append(row)
    return out


def _rounded_rect(x0, y0, x1, y1, radius):
    def inside(x, y):
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        cx = min(max(x, x0 + radius), x1 - radius)
        cy = min(max(y, y0 + radius), y1 - radius)
        return (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius
    return inside


def _tile_mask(side):
    key = ("tile", side)
    if key not in _mask_cache:
        _mask_cache[key] = _coverage(
            side, side, _rounded_rect(0, 0, side, side, side * 0.22))
    return _mask_cache[key]


def _write_picture(path, width, height, mask, rgb):
    r, g, b = rgb
    rows = []
    for line in mask:
        row = bytearray()
        for alpha in line:
            row.extend((r, g, b, alpha))
        rows.append(bytes(row))
    data = _png(width, height, rows)
    try:
        if not os.path.isdir(TILE_DIR):
            os.makedirs(TILE_DIR)
        temp = path + ".tmp"
        with open(temp, "wb") as f:
            f.write(data)
        os.rename(temp, path)
        return path
    except Exception as e:
        print("[vavoo_store] Cannot write {}: {}".format(path, e))
        return None


def tile_path(name, side):
    """The initials tile of a channel at `side` pixels: drawn the first
    time, then reused (one per colour and size)."""
    side = max(8, int(side))
    hue = tile_hue(name)
    path = os.path.join(TILE_DIR, "tile_%d_%03d.png" % (side, hue))
    if os.path.isfile(path):
        return path
    return _write_picture(path, side, side, _tile_mask(side),
                          hsv_to_rgb(hue, 0.55, 0.62))


def _padlock(width, height):
    """A padlock filling width x height: the shackle (a ring's upper
    half and its legs) over a rounded body."""
    body_top = height * 0.45
    body = _rounded_rect(0.08 * width, body_top, 0.92 * width, height,
                         width * 0.14)
    cx = width / 2.0
    outer = width * 0.32
    inner = width * 0.19
    arc_cy = body_top - 0.02 * height
    shackle_top = arc_cy - outer

    def inside(x, y):
        if body(x, y):
            return True
        if y < shackle_top or y > body_top + 1:
            return False
        dx = x - cx
        if y <= arc_cy:
            d = (dx * dx + (y - arc_cy) ** 2) ** 0.5
            return inner <= d <= outer
        return inner <= abs(dx) <= outer
    return inside


def _alarm_clock(size):
    """A small alarm clock filling size x size: a ring with two hands
    and two bells on top (the app's ⏰ mark on a programme)."""
    c = size / 2.0
    cy = size * 0.56
    outer = size * 0.40
    inner = size * 0.29
    bell = size * 0.14

    def inside(x, y):
        dx, dy = x - c, y - cy
        d2 = dx * dx + dy * dy
        if inner * inner <= d2 <= outer * outer:
            return True
        # the hands: 12 o'clock and 3 o'clock
        if abs(dx) <= size * 0.045 and -inner * 0.8 <= dy <= 0:
            return True
        if abs(dy) <= size * 0.045 and 0 <= dx <= inner * 0.7:
            return True
        for bx in (c - size * 0.30, c + size * 0.30):
            if (x - bx) ** 2 + (y - size * 0.16) ** 2 <= bell * bell:
                return True
        return False
    return inside


def clock_path(height, rgb=(255, 255, 255)):
    """The alarm clock mark at `height` pixels (square)."""
    height = max(8, int(height))
    path = os.path.join(TILE_DIR, "clock_%d_%02x%02x%02x.png" % (
        (height,) + tuple(rgb)))
    if os.path.isfile(path):
        return path
    key = ("clock", height)
    if key not in _mask_cache:
        _mask_cache[key] = _coverage(height, height, _alarm_clock(height))
    return _write_picture(path, height, height, _mask_cache[key], rgb)


def lock_path(height, rgb=(255, 255, 255)):
    """The padlock at `height` pixels (width 3/4 of it)."""
    height = max(8, int(height))
    width = max(6, int(round(height * 0.75)))
    path = os.path.join(TILE_DIR, "lock_%d_%02x%02x%02x.png" % (
        (height,) + tuple(rgb)))
    if os.path.isfile(path):
        return path
    key = ("lock", width, height)
    if key not in _mask_cache:
        _mask_cache[key] = _coverage(width, height, _padlock(width, height))
    return _write_picture(path, width, height, _mask_cache[key], rgb)
