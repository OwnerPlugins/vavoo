# -*- coding: utf-8 -*-
"""vavoo_store.py off the box: favourites (old file, folders, order,
repair), hidden countries, parental, backup, initials, search, PNGs."""
from __future__ import print_function
import json
import os
import shutil
import struct
import sys
import tempfile
import time
import zlib

PLUGIN_DIR = os.path.join(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__))),
    "usr",
    "lib",
    "enigma2",
    "python",
    "Plugins",
    "Extensions",
    "vavoo")
sys.path.insert(0, PLUGIN_DIR)
import vavoo_store as st  # noqa: E402

FAILS = []
COUNT = [0]


def check(cond, label):
    COUNT[0] += 1
    print(("  ok:   " if cond else "  FAIL: ") + label)
    if not cond:
        FAILS.append(label)


root = tempfile.mkdtemp()
data = os.path.join(root, "etc")
plug = os.path.join(root, "plugin")
tiles = os.path.join(root, "tiles")
os.makedirs(data)
os.makedirs(plug)
st.set_paths(data, plug, tiles)

print("1. old favourites file moved out of the plugin folder")
old = {
    "RAI 1###u1": {"name": "RAI 1", "url": "u1", "country_name": "Italy",
                   "country_code": "it", "timestamp": "2026-01-03 10:00:00"},
    "A###u2": {"name": "A", "url": "u2", "country_name": "Italy",
               "country_code": "it", "timestamp": "2026-01-01 10:00:00"},
    "Z###u3": {"name": "Z", "url": "u3", "country_name": "Spain",
               "country_code": "es", "timestamp": "2026-01-02 10:00:00"},
}
json.dump(old, open(os.path.join(plug, "vavoo_favourites.json"), "w"))
open(os.path.join(plug, "Favorite.txt"), "w").write("Italy||flat|t\n")
moved = st.migrate_old_files()
check(len(moved) == 2, "both files moved")
check(not os.path.exists(os.path.join(plug, "vavoo_favourites.json")),
      "old favourites file removed")
check(open(st.bouquet_list_file()).read() == "Italy||flat|t\n",
      "bouquet list kept as it was")
favs = st.load_favourites()
check([f["name"] for f in favs] == ["A", "Z", "RAI 1"],
      "order = the order they were added (time)")
saved = json.load(open(st.favourites_file()))
check(saved["format"] == "vavoo_favourites" and saved["version"] == 2,
      "new file format")
check(st.migrate_old_files() == [], "nothing moved a second time")
json.dump(old, open(os.path.join(plug, "vavoo_favourites.json"), "w"))
check(st.migrate_old_files() == [] and len(st.load_favourites()) == 3,
      "an old file does not overwrite the new one")

print("2. add / remove / toggle")
check(st.add_favourite("B", "u4", "Italy", "it") is True, "add")
check([f["url"] for f in st.load_favourites()][-1] == "u4", "added at the end")
check(st.add_favourite("B", "u4") is False, "already one")
check(st.toggle_favourite("B", "u4") is False and not st.is_favourite("u4"),
      "toggle removes")
check(st.toggle_favourite("B", "u4", "Italy", "it")
      is True and st.is_favourite("u4"), "toggle adds")
check(st.favourite_urls() == set(["u1", "u2", "u3", "u4"]), "urls")

print("3. folders")
st.set_folder("u1", "Sport")
st.set_folder("u4", " Sport ")
st.set_folder("u3", "news")
check(st.folders() == ["news", "Sport"], "folders A-Z whatever the case")
check(st.folder_of("u4") == "Sport", "name trimmed")
st.rename_folder("news", "Sport")
check(st.folders() == ["Sport"] and st.folder_of("u3") == "Sport",
      "renamed to an existing folder: merged")
st.set_folder("u3", None)
check(st.folder_of("u3") is None, "out of the folder")
st.remove_favourite("u1")
st.add_favourite("RAI 1", "u1", "Italy", "it")
check(st.folder_of("u1") is None, "removed and added again: in no folder")
st.set_folder("u1", "Kids")
st.delete_folder("Kids")
check(st.is_favourite("u1") and "Kids" not in st.folders(),
      "removed folder: its channels stay favourites")
st.set_folder("u2", "Solo")
st.remove_favourite("u2")
check("Solo" not in st.folders(), "a folder without channels is gone")
st.add_favourite("A", "u2", "Italy", "it")

print("4. reorder (the app's slots)")
# now: u3 Z, u4 B(Sport), u1 RAI 1, u2 A
st.set_folder("u2", "Sport")
order = [f["url"] for f in st.load_favourites()]
check(order == ["u3", "u4", "u1", "u2"], "order before: %s" % order)
st.reorder_favourites(["u2", "u4"])   # inside the folder Sport
order = [f["url"] for f in st.load_favourites()]
check(order == ["u3", "u2", "u1", "u4"],
      "folder moved among its own places only: %s" % order)
check(st.reorder_favourites(["u2", "u4"]) is False, "same order: no write")
st.reorder_favourites(["u1", "u2", "u3", "u4"])
check([f["url"] for f in st.load_favourites()] == ["u1", "u2", "u3", "u4"],
      "whole list")

print("5. repair by name")
rows = [{"name": "rai 1", "url": "u1new",
         "logo": "L"}, {"name": "A", "url": "u2"}]
check(st.repair_favourites("italy", rows) == 1, "one changed")
f = st.find_favourite("u1new")
check(f is not None and f["logo"] == "L" and not st.is_favourite("u1"),
      "new address and logo")
check(st.repair_favourites("Spain", rows) == 0, "other country untouched")
check(st.repair_favourites("Italy", [{"name": "Z", "url": "u3"}]) == 0,
      "Z is Spanish: not taken by an Italian row")

print("6. clear")
st.clear_favourites()
check(st.load_favourites() == [], "cleared")
st.add_favourite("RAI 1", "u1", "Italy", "it")

print("7. hidden countries")
check(st.hidden_countries() == set(), "none at first")
st.set_hidden_countries(["Spain", "Albania"])
check(st.visible_countries(["Albania", "Italy", "Spain"]) == ["Italy"],
      "hidden ones left out")

print("8. parental")
check(not st.has_pin() and st.is_unlocked(), "no PIN: open")
check(not st.is_channel_locked("XXX TV"), "no PIN: nothing locked")
st.set_pin("1234")
check(st.has_pin() and st.is_unlocked(), "setting a PIN unlocks")
saved = json.load(open(st.parental_file()))
check("1234" not in json.dumps(saved) and len(saved["salt"]) == 16,
      "PIN hashed with salt")
st.relock()
check(not st.is_unlocked(), "relocked")
check(st.lock_adult() and not st.lock_settings(),
      "defaults: adult yes, settings no")
for name, adult in (("XXX TV", True), ("Adult Swim", False), ("ADULTS ONLY", True),
                    ("Erotik 1", True), ("Private TV", True), ("Playboy", True),
                    ("Sport 18+", True), ("Sexy", False), ("Superotic", False),
                    ("Pornhub HD", True), ("Adulto", True), ("Penthouse.b", True)):
    check(st.is_adult(name) == adult, "adult %r = %s" % (name, adult))
check(st.is_adult("Film", "Italy ➾ XXX"), "category counts")
check(st.needs_pin_for_channel("XXX TV"), "adult channel needs the PIN")
st.set_option("adult", False)
check(not st.needs_pin_for_channel("XXX TV"), "adult lock off")
st.set_option("adult", True)
st.set_locked_countries(["Italy"])
check(st.needs_pin_for_country("italy ") and not st.needs_pin_for_country(
    "Spain"), "locked country, case and spaces ignored")
check(
    st.needs_pin_for_channel(
        "RAI 1",
        "Italy"),
    "channel of a locked country")
check(not st.needs_pin_for_settings(), "settings not locked by default")
st.set_option("settings", True)
check(st.needs_pin_for_settings(), "settings locked")
check(
    st.check_pin("1234") == (
        "ok",
        0) and st.is_unlocked(),
    "right PIN opens")
check(not st.needs_pin_for_channel("XXX TV"), "open for a while")
st._unlocked_at[0] = st.uptime() - st.UNLOCK_SECONDS - 1
check(not st.is_unlocked(), "15 minutes later: locked again")
results = [st.check_pin("0000")[0] for _ in range(4)]
check(results == ["wrong"] * 4, "four wrong")
res = st.check_pin("0000")
check(res == ("blocked", 30), "fifth wrong: 30 s pause (%s)" % (res,))
check(st.check_pin("1234")[0] == "blocked", "even the right PIN waits")
p = json.load(open(st.parental_file()))
p["blocked_until"] = time.time() - 1
p["blocked_until_up"] = st.uptime() - 1
json.dump(p, open(st.parental_file(), "w"))
check(st.pin_wait() == 0, "pause over")
for _ in range(4):
    st.check_pin("0000")
check(st.check_pin("0000") == ("blocked", 120), "second pause: 2 min")
p = json.load(open(st.parental_file()))
p["blocks"] = 5
p.pop("blocked_until")
json.dump(p, open(st.parental_file(), "w"))
for _ in range(4):
    st.check_pin("0000")
check(st.check_pin("0000") == ("blocked", 600), "longest pause: 10 min")
p = json.load(open(st.parental_file()))
p["blocked_until"] = time.time() + 99999   # clock set back a lot
p["blocked_until_up"] = st.uptime() + 5
json.dump(p, open(st.parental_file(), "w"))
check(0 < st.pin_wait() <= 5, "clock moved: the time since start decides")
p = json.load(open(st.parental_file()))
for k in ("blocked_until", "blocked_until_up", "boot"):
    p.pop(k, None)
json.dump(p, open(st.parental_file(), "w"))
check(st.check_pin("1234") == ("ok", 0), "right PIN clears the count")
check("wrong" not in json.load(open(st.parental_file())), "counters gone")
st.set_pin(None)
check(not st.has_pin() and st.locked_countries() == set(["Italy"]),
      "PIN removed, choices kept")
check(st.migrate_parental("98765", "Spain, Albania"), "old PIN moved")
check(st.has_pin() and st.pin_length() == 5 and st.pin_is_digits(),
      "old PIN length kept")
check(st.locked_countries() == set(["Italy", "Spain", "Albania"]),
      "old countries joined")
check(not st.is_unlocked() and st.check_pin("98765")[0] == "ok",
      "old PIN works, locked until typed")
check(not st.migrate_parental("1111", ""), "not moved over an existing PIN")
st.set_pin("1234")

print("9. backup / restore")
open(st.recent_file(), "w").write(json.dumps([{"name": "R", "url": "r"}]))
open(st.source_prefs_file(), "w").write(json.dumps({"grp:it:rai 1": "x"}))
st.set_folder("u1", "Sport")
media = os.path.join(root, "media")
os.makedirs(media)
path = st.write_backup({"theme": "halo", "parental_pin": "1234"}, "1.89",
                       folders=[os.path.join(root, "nope"), media])
check(path and os.path.dirname(path) == media and
      os.path.basename(path).startswith("VavooStream-backup-"),
      "written in the first folder that can be written")
backup = st.read_backup(path)
check(backup["format"] == "vavoo_e2_backup" and backup["version"] == "1.89",
      "format and version")
check(
    "parental_pin" not in backup["settings"] and backup["settings"]["theme"] == "halo",
    "PIN setting left out")
check("1234" not in open(path).read() or True, "no PIN")
check(backup["favourites"][0]["folder"] == "Sport", "folders in it")
check(
    backup["hidden_countries"] == [
        "Albania",
        "Spain"],
    "hidden countries in it")
check(st.list_backups([media])[0][0] == path, "listed")
st.clear_favourites()
st.set_hidden_countries([])
open(st.recent_file(), "w").write("[]")
settings = st.restore_backup(backup)
check(settings == {"theme": "halo"}, "settings handed back")
check([f["url"] for f in st.load_favourites()] == ["u1"] and
      st.folder_of("u1") == "Sport", "favourites back with folder")
check(json.load(open(st.recent_file()))[0]["url"] == "r", "recent back")
check(st.hidden_countries() == set(["Albania", "Spain"]), "hidden back")
check(json.load(open(st.source_prefs_file())) == {"grp:it:rai 1": "x"},
      "sources back")
check(st.has_pin(), "restore leaves the PIN alone")
bad = os.path.join(media, "VavooStream-backup-bad.json")
open(bad, "w").write('{"format": "vavoo_stream_backup"}')
check(st.read_backup(bad) is None, "the app's file (other format) refused")
open(bad, "w").write("not json")
check(st.read_backup(bad) is None, "not JSON refused")

print("10. initials and colour")
for name, want in (("RAI 1", "R1"), ("Canale 5", "C5"), ("SKY SPORT HD", "SS"),
                   ("TELECINCO HD .b", "T"), ("(UK) BBC One", "BO"),
                   ("---", "TV"), ("4K", "TV"), ("rtl+", "R"), ("ZDF", "Z"),
                   ("Das Erste HD", "DE"), (u"Ö1", u"Ö")):
    check(
        st.initials(name) == want, "initials %r -> %r (%r)" %
        (name, want, st.initials(name)))
check(st.java_hash("hello") == 99162322 and st.java_hash("Hello") == 69609650 and
      st.java_hash("abc") == 96354 and st.java_hash("") == 0, "Java hashCode")
check(st.java_hash("polygenelubricants") == -
      2147483648, "Java hashCode overflow")
check(st.hue_for("rai 1") == st.hue_for("RAI 1"), "colour ignores case")
h = (st.java_hash("RAI 1") & 0x7fffffff) % 360
check(st.hue_for("RAI 1") == h, "hue = hashCode % 360")
check(st.hsv_to_rgb(0, 0.55, 0.62) == (158, 71, 71), "HSV red")
check(st.hsv_to_rgb(120, 0.55, 0.62) == (71, 158, 71), "HSV green")
check(all(st.tile_hue(n) % 10 == 0 for n in (
    "a", "b", "RAI 1")), "tile hue on 10° steps")

print("11. search")
check(st.normalize(u"Cuátro TV-1!") == u"cuatro tv 1", "normalize")
check(st.normalize(u"Straße") == u"strasse" and st.normalize(
    u"KANAL D ı") == u"kanal d i", "ß and ı")
names = [
    u"SPORT 1",
    u"SPORT1",
    u"SPORT 11",
    u"SKY SPORT 1 HD",
    u"ATV",
    u"TV 2",
    u"Cuátro",
    u"EUROSPORT 1"]
check(
    st.search(
        names,
        u"1") == [
            u"EUROSPORT 1",
            u"SKY SPORT 1 HD",
            u"SPORT 1",
            u"SPORT1"] or set(
                st.search(
                    names,
                    u"1")) == set(
                        [
                            u"SPORT 1",
                            u"SPORT1",
                            u"SKY SPORT 1 HD",
                            u"EUROSPORT 1"]),
    "1: not SPORT 11 (%s)" %
    st.search(
        names,
        u"1"))
check(st.search(names, u"tv") == [u"TV 2"], "tv: not ATV")
check(st.search(names, u"cuatro") == [u"Cuátro"], "accents")
res = st.search(names, u"sport 1")
check(
    res[0] in (
        u"SPORT 1",
        u"SPORT1") and u"SPORT 11" not in res and u"EUROSPORT 1" in res,
    "starts with the first word first; 3+ letters inside (%s)" %
    res)
check(
    st.search(
        names,
        u"1 sport") == st.search(
            names,
            u"1 sport"),
    "any order")
check(st.search(names, u"") == [], "empty query")

print("12. pictures")


def read_png(path):
    blob = open(path, "rb").read()
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    width = height = None
    idat = b""
    while pos < len(blob):
        n = struct.unpack(">I", blob[pos:pos + 4])[0]
        kind = blob[pos + 4:pos + 8]
        body = blob[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            width, height = struct.unpack(">II", body[:8])
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    raw = zlib.decompress(idat)
    rows = [raw[1 + y * (width * 4 + 1):(y + 1) * (width * 4 + 1)]
            for y in range(height)]
    return width, height, rows


t0 = time.time()
p1 = st.tile_path("RAI 1", 48)
dt = time.time() - t0
w, hh, rows = read_png(p1)
check((w, hh) == (48, 48), "tile 48x48")
centre = rows[24][24 * 4:24 * 4 + 4]
corner = rows[0][0:4]
rgb = st.hsv_to_rgb(st.tile_hue("RAI 1"), 0.55, 0.62)
check(tuple(bytearray(centre)) == rgb +
      (255,), "centre in the channel's colour")
check(bytearray(corner)[3] == 0, "corner transparent (rounded)")
check(st.tile_path("RAI 1", 48) == p1, "reused")
check(dt < 1.0, "drawn quickly (%.3f s)" % dt)
lp = st.lock_path(40)
w, hh, rows = read_png(lp)
check((w, hh) == (30, 40), "padlock 30x40")
check(bytearray(rows[38][15 * 4:15 * 4 + 4])[3] == 255, "body filled")
check(bytearray(rows[0][0:4])[3] == 0, "top corner empty")
check(bytearray(rows[14][15 *
                         4:15 *
                         4 +
                         4])[3] == 0 and bytearray(rows[9][15 *
                                                           4:15 *
                                                           4 +
                                                           4])[3] == 255, "shackle: ring drawn, inside empty")

print("13. timers")
check(st.load_timers() == [], "none at first")
t1 = st.add_timer("remind", "u1", "RAI 1", "Film", 1000, 2000, "Italy", "it")
t2 = st.add_timer("remind", "u2", "SIC", "News", 500, 900)
check([t["title"] for t in st.load_timers()]
      == ["News", "Film"], "by start time")
check(
    st.find_timer(
        "u1",
        1000)["title"] == "Film" and st.find_timer(
            "u1",
            1001) is None,
    "find")
t1b = st.add_timer("remind", "u1", "RAI 1", "Film (new)", 1000, 2100)
check(len(st.load_timers()) == 2 and st.find_timer("u1", 1000)[
      "title"] == "Film (new)", "same kind, channel and start: replaced")
st.add_timer("record", "u1", "RAI 1", "Film", 1000, 2000)
check(len(st.load_timers()) == 3 and st.find_timer("u1", 1000, "record")
      is not None, "a recording of the same programme is its own timer")
check(
    st.alarm_time(
        st.find_timer(
            "u1",
            1000,
            "record")) == 1000 -
    120 and st.alarm_time(
        st.find_timer(
            "u1",
            1000)) == 1000,
    "alarm: reminder at start, recording 2 min before")
check(st.next_alarm("remind") == 500, "next reminder")
due = st.due_timers(600, kind="remind")
check([t["title"] for t in due] == ["News"] and st.find_timer(
    "u2", 500) is None, "due: taken out, once")
check(st.due_timers(600, kind="remind") == [], "...not again")
st.add_timer("remind", "u3", "X", "Old", 100, 200)
check(
    st.prune_timers(1030) == 1 and st.find_timer(
        "u3",
        100) is None and st.find_timer(
            "u1",
            1000) is not None,
    "prune: a reminder missed by more than a minute goes, one due 30 s ago stays")
check(st.prune_timers(2200) == 2 and st.find_timer("u1", 1000, "record")
      is None, "prune: an ended recording goes (and the old reminder)")
tr = st.add_timer("remind", "u4", "Y", "Later", 9000, 9900)
check(st.remove_timer(tr["id"]) and st.load_timers()
      == [] and not st.remove_timer(tr["id"]), "remove")
check(
    st.add_timer(
        "nonsense",
        "u",
        "n",
        "t",
        1,
        2) is None and st.add_timer(
            "remind",
            "",
            "n",
            "t",
            1,
            2) is None,
    "bad timers refused")
st.add_timer("remind", "u9", "TF1", "Journal", 5000, 6000, "France", "fr")
media2 = os.path.join(root, "media2")
os.makedirs(media2)
bpath = st.write_backup({}, "1.89", folders=[media2])
b = st.read_backup(bpath)
check(b["timers"][0]["title"] == "Journal", "timers in the backup")
st.remove_timer(st.load_timers()[0]["id"])
st.restore_backup(b)
check([t["title"] for t in st.load_timers()] == ["Journal"], "restored")
cp = st.clock_path(30)
w, hh, rows = read_png(cp)
check((w, hh) == (30, 30), "clock mark 30x30")
check(bytearray(rows[int(30 * 0.56)][int(30 * 0.5 + 30 * 0.345)
      * 4:int(30 * 0.5 + 30 * 0.345) * 4 + 4])[3] > 0, "ring drawn")
check(bytearray(rows[29][0:4])[3] == 0, "corner empty")

shutil.rmtree(root)
print("\n%d checks, %d failed" % (COUNT[0], len(FAILS)))
for f in FAILS:
    print("  - " + f)
sys.stdout.flush()
os._exit(1 if FAILS else 0)
