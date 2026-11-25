# -*- coding: utf-8 -*-
"""Favourites by country: the Favourites list shows a title per country
with its channels under it (MENU → Move this country), and the
favourites bouquet ("Vavoo ★ Favourites" in the channel list) has a
marker per country, follows the list and is kept by the scheduled
update. A country's EPG channels file is shared by every bouquet that
plays its channels."""
from __future__ import print_function
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import (check, finish, make, row_text, Session, MENUS, NOTES,
                     V)                         # noqa: E402
plugin = harness.plugin
store = harness.store
vu = plugin.vUtils
bm = sys.modules["vavoo.bouquet_manager"]
EXPORT_LOCK = sys.modules["vavoo"].export_lock

TMP = tempfile.mkdtemp(prefix="vavoo_favcc_")
E2 = os.path.join(TMP, "e2")
os.makedirs(E2)
bm.ENIGMA_PATH = E2
vu.ENIGMA_PATH = E2
vu.EPGIMPORT_DIR = os.path.join(TMP, "epgimport")
vu.CACHE_FILE = os.path.join(TMP, "cache.json")
vu.UNMATCHED_FILE = os.path.join(TMP, "unmatched.json")
vu._get_epg_feed_index = lambda cc: (None, {})
plugin.cfg.services = V("4097")
plugin.cfg.list_position = V("bottom")


def url(channel_id):
    return "http://127.0.0.1:4323/vavoo?channel=" + channel_id


def urls():
    return [e["url"] for e in store.load_favourites()]


def texts(screen):
    return [plugin.to_text(row_text(r))
            for r in screen.widgets["menulist"].rows]


def status():
    return plugin.to_text(fv.widgets["proxy_status"].text)


print("== favourites_by_country()")
groups = store.favourites_by_country([
    {"name": "A", "country_name": "Portugal"},
    {"name": "B", "country_name": "Italy"},
    {"name": "C", "country_name": ""},
    {"name": "D", "country_name": "portugal"}])
check([(c, [e["name"] for e in m]) for c, m in groups] ==
      [(u"Portugal", ["A", "D"]), (u"Italy", ["B"]), (u"", ["C"])],
      "countries by their first favourite, any case together, none last: %r"
      % groups)

for name, cid, cc, country in (("SIC", "sic", "pt", "Portugal"),
                               ("RAI 1", "rai1", "it", "Italy"),
                               ("TF1", "tf1", "fr", "France"),
                               ("RTP 1", "rtp1", "pt", "Portugal")):
    store.add_favourite(name, url(cid), country, cc)
ORIGINAL = urls()

print("== the list: a title per country, the channels under it")
plugin.cfg.fav_by_country = V(True)
s = Session()
fv = make(plugin.VavooFavourites, s)
fv._build_list()
w = fv.widgets
a = w["actions"].actions
check(texts(fv) == [u"Portugal (2)", u"1  SIC", u"2  RTP 1", u"Italy (1)",
                    u"3  RAI 1", u"France (1)", u"4  TF1"],
      "rows: %r" % texts(fv))
check(w["menulist"].index == 1 and status() == u"★ Favourites · 1/4",
      "opens on the first channel, counted in channels: %r" % status())
a["down"]()
a["down"]()
check(w["menulist"].index == 4, "DOWN steps over Italy's title")
a["up"]()
check(w["menulist"].index == 2, "UP over it again")
w["menulist"].moveToIndex(1)
a["up"]()
check(w["menulist"].index == 6, "UP from the first channel: round to the "
      "last (not Portugal's title)")
a["down"]()
check(w["menulist"].index == 1, "DOWN from the last: round to the first")
fv._digit_time = 0
a["3"]()
check(w["menulist"].index == 4 and status() == u"★ Favourites · 3/4",
      "3 = the third channel (RAI 1)")
check(fv._epg_panel_selection() == (u"RAI 1", url("rai1"), u"it"),
      "the Now/Next panel: RAI 1 of Italy")

played = []
real_require = plugin._require_parental_pin
plugin._require_parental_pin = lambda session, screen, country, fn, **k: fn()
fv.full_screen()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.Playstream2 and args[0] == "RAI 1" and args[2] == 2 and
      len(args[4]) == 4 and [r[0][0] for r in args[4]] ==
      ["SIC", "RTP 1", "RAI 1", "TF1"] and kw["country_codes"] ==
      [u"pt", u"pt", u"it", u"fr"],
      "the player: the 4 channels alone, in this order, RAI 1 = 2")
a["info"]()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VavooGuide and args[1] == 2 and
      [c["name"] for c in args[0]] == ["SIC", "RTP 1", "RAI 1", "TF1"],
      "the guide: the same order, on RAI 1")
real_record = plugin.record_channel
plugin.record_channel = lambda channel: played.append(channel["name"])
a["record"]() if "record" in a else fv.record_highlighted()
check(played == ["RAI 1"], "REC: the highlighted channel %r" % played)
plugin.record_channel = real_record
plugin._require_parental_pin = real_require
check(plugin.favourite_channels()[1]["name"] == "RTP 1",
      "favourite_channels() (the main list's EPG) in the same order")

print("== Move: only within the country")
w["menulist"].moveToIndex(2)            # RTP 1
a["yellow"]()
check(fv.moving and not fv._moving_country, "moving RTP 1")
a["up"]()
check(texts(fv)[:3] == [u"Portugal (2)", u"1  RTP 1", u"2  SIC"] and
      w["menulist"].index == 1, "UP: above SIC %r" % texts(fv)[:3])
a["up"]()
a["up"]()
check(w["menulist"].index == 1 and texts(fv)[1] == u"1  RTP 1",
      "UP again: stays in Portugal")
fv._digit_time = 0
a["4"]()
check(texts(fv)[2] == u"2  RTP 1", "a number: as far as Portugal goes")
a["up"]()
check(urls() == ORIGINAL, "not saved yet")
a["ok"]()
check(not fv.moving and urls() == [url("rtp1"), url("rai1"), url("tf1"),
                                   url("sic")],
      "saved: only Portugal's two places swapped %r" % urls())

print("== MENU → Move this country")
w["menulist"].moveToIndex(4)            # RAI 1
a["menu"]()
title, entries, choose = MENUS[-1]
keys = [k for _label, k in entries]
check("move_country" in keys and "fav_bq" in keys, "MENU: %r" % keys)
choose("move_country")
check(fv.moving and fv._moving_country and status() == u"⇅  Italy",
      "moving Italy")
check(fv.help_rows()[0][1] == "Move the country", "HELP says so")
a["up"]()
check(texts(fv)[:2] == [u"Italy (1)", u"1  RAI 1"] and
      w["menulist"].index == 1, "UP: Italy first %r" % texts(fv))
a["up"]()
check(texts(fv)[0] == u"Italy (1)", "...and no further")
a["yellow"]()
check(not fv.moving and urls() == [url("rai1"), url("rtp1"), url("sic"),
                                   url("tf1")],
      "saved: the order shown %r" % urls())

print("== every key with the titles on (moving too)")
pending = harness.Pending().hold()
plugin._require_parental_pin = lambda session, screen, country, fn, **k: fn()
broken = []
SWEEP_FAVOURITES = store.load_favourites()


def reset_favourites():
    store.clear_favourites()
    for e in SWEEP_FAVOURITES:
        store.add_favourite(e["name"], e["url"], e["country_name"],
                            e["country_code"])


for moving in (False, True, "country"):
    for key in sorted(a):
        reset_favourites()
        screen = make(plugin.VavooFavourites, Session())
        screen._build_list()
        screen.widgets["menulist"].moveToIndex(4)
        if moving:
            screen._set_moving(True, country=moving == "country")
        try:
            screen.widgets["actions"].actions[key]()
            screen._update_selection()
            screen.help_rows()
        except Exception as e:
            broken.append((moving, key, repr(e)))
        screen.moving = False
        screen._moved = False
# on a country's title (a list that starts there, say)
reset_favourites()
screen = make(plugin.VavooFavourites, Session())
screen._build_list()
screen.widgets["menulist"].moveToIndex(0)
for key in sorted(a):
    try:
        screen.widgets["actions"].actions[key]()
        screen._set_moving(True, country=True)
        screen._set_moving(True)
        screen.moving = False
    except Exception as e:
        broken.append(("title", key, repr(e)))
    screen.widgets["menulist"].moveToIndex(0)
check(not screen._channel_rows or screen._current_selection()[0] is None,
      "a title row is no channel")
reset_favourites()
pending.clear()
pending.release()
plugin._require_parental_pin = real_require
check(not broken, "no key fails: %r" % broken[:5])
check(urls() == [url("rai1"), url("rtp1"), url("sic"), url("tf1")],
      "(nothing saved by the sweep)")

print("== the setting off: one list, as before")
plugin.cfg.fav_by_country = V(False)
fv._build_list()
check(texts(fv) == [u"1  RAI 1", u"2  RTP 1", u"3  SIC", u"4  TF1"],
      "no titles: %r" % texts(fv))
a["menu"]()
check("move_country" not in [k for _l, k in MENUS[-1][1]],
      "no Move this country")
plugin.cfg.fav_by_country = V(True)
fv._build_list()

print("== the favourites bouquet")
lines, count, skipped, channels = bm.favourites_bouquet_lines(
    u"Vavoo ★ Favourites", store.load_favourites(), "4097", u"Other")


def ref(cid): return (bm.unique_fallback_sref("4097", cid) +
                      "http%3a//127.0.0.1%3a4323/vavoo?channel=" + cid)


check(lines == [
    u"#NAME Vavoo ★ Favourites",
    u"#SERVICE 1:64:1:0:0:0:0:0:0:0::Italy", u"#DESCRIPTION Italy",
    u"#SERVICE " + ref("rai1"), u"#DESCRIPTION RAI 1",
    u"#SERVICE 1:64:2:0:0:0:0:0:0:0::Portugal", u"#DESCRIPTION Portugal",
    u"#SERVICE " + ref("rtp1"), u"#DESCRIPTION RTP 1",
    u"#SERVICE " + ref("sic"), u"#DESCRIPTION SIC",
    u"#SERVICE 1:64:3:0:0:0:0:0:0:0::France", u"#DESCRIPTION France",
    u"#SERVICE " + ref("tf1"), u"#DESCRIPTION TF1"] and count == 4 and
    not skipped, "#NAME, a marker per country, its channels:\n%s" %
    u"\n".join(lines))
store.set_pin("1234")
store.set_locked_countries(["France"])
lines, count, skipped, channels = bm.favourites_bouquet_lines(
    u"T", store.load_favourites(), "4097")
check(count == 3 and skipped == 1 and not any("France" in x for x in lines),
      "with a PIN: France (locked) left out, and its marker")
store.set_locked_countries([])
store.set_pin("")

pending = harness.Pending().hold()
check(not bm.favourites_bouquet_exported(), "not exported yet")
w["menulist"].moveToIndex(1)
a["menu"]()
labels = dict((k, l) for l, k in MENUS[-1][1])
check(labels.get("fav_bq") == "Export favourites as a bouquet" and
      "fav_rm" not in labels, "MENU: Export favourites as a bouquet")
MENUS[-1][2]("fav_bq")
check(len(pending.threads) == 1, "exported in a background thread")
failures = pending.run()
check(not failures, "it ran: %r" % failures)
path = os.path.join(E2, bm.FAVOURITES_BOUQUET)
text = open(path, "rb").read().decode("utf-8") if os.path.exists(path) else ""
check(u"#NAME Vavoo ★ Favourites" in text and text.count("1:64:") == 3,
      "the bouquet written, 3 markers")
check(NOTES and plugin.to_text(NOTES[-1]) ==
      u"Favourites bouquet: 4 channels",
      "told: %r" % NOTES[-1:])
main = open(os.path.join(E2, "bouquets.tv")).read()
check('FROM BOUQUET "userbouquet.vavoo_favourites.tv"' in main,
      "in bouquets.tv")
listed = open(store.bouquet_list_file()).read()
check("Favourites||favourites|" in listed,
      "in the bouquet list, for the scheduled update: %r" % listed)
check(not EXPORT_LOCK.locked() if hasattr(EXPORT_LOCK, "locked") else
      EXPORT_LOCK.acquire(False) and (EXPORT_LOCK.release() or True),
      "export_lock free again")

print("== it follows the favourites")
pending.clear()
store.add_favourite("RTL", url("rtl"), "Germany", "de")
check(pending.calls, "a change: the update scheduled")
pending.run()
text = open(path, "rb").read().decode("utf-8")
check(u"#DESCRIPTION RTL" in text and u"::Germany" in text,
      "the bouquet has the new channel under Germany")
check(plugin.to_text(NOTES[-1]) == u"Favourites bouquet: 4 channels",
      "quietly (no new message)")

print("== the scheduled update keeps it")
store.remove_favourite(url("rtl"))
pending.run()
store.add_favourite("ZDF", url("zdf"), "Germany", "de")
pending.clear()                         # (not the follow: the timer)
converted = []
real_convert = plugin.convert_bouquet
plugin.convert_bouquet = lambda *a, **k: converted.append(a) or 0
timer = plugin.AutoStartTimer.__new__(plugin.AutoStartTimer)
EXPORT_LOCK.acquire()
timer._update_bouquets([(bm.FAVOURITES_NAME, "", bm.FAVOURITES_EXPORT)])
plugin.convert_bouquet = real_convert
text = open(path, "rb").read().decode("utf-8")
check(u"#DESCRIPTION ZDF" in text and not converted,
      "the favourites written again, no country export")
check(EXPORT_LOCK.acquire(False), "export_lock released")
EXPORT_LOCK.release()

print("== MENU with the bouquet: Update / Remove")
a["menu"]()
labels = dict((k, l) for l, k in MENUS[-1][1])
check(labels.get("fav_bq") == "Update the favourites bouquet" and
      labels.get("fav_rm") == "Remove the favourites bouquet",
      "MENU: %r" % labels)
MENUS[-1][2]("fav_rm")
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.MessageBox and kw.get("default") is False,
      "Remove asks, No by default")
cb(False)
check(os.path.exists(path), "No: kept")
cb(True)
check(not os.path.exists(path) and
      "vavoo_favourites" not in open(os.path.join(E2, "bouquets.tv")).read()
      and "favourites" not in (open(store.bouquet_list_file()).read()
                               if os.path.exists(store.bouquet_list_file())
                               else ""),
      "Yes: the file, its bouquets.tv line and its bouquet list line gone")
pending.release()

print("== one EPG file per country, shared by the bouquets")
EPG = os.path.join(vu.EPGIMPORT_DIR, "vavoo_pt.channels.xml")


def write_bouquet(name, refs):
    with open(os.path.join(E2, name), "w") as f:
        f.write("#NAME x\n" + "".join("#SERVICE %s\n" % r for r in refs))


def mapped():
    return sorted(vu._read_epg_channels_file(EPG))


country_ref, fav_ref = ref("sic"), ref("grp:pt:rtp 1")
write_bouquet("userbouquet.vavoo_portugal.tv", [country_ref])
vu.write_epg_mapping_file([("SIC.pt", country_ref, "SIC")], "pt", E2)
write_bouquet(bm.FAVOURITES_BOUQUET,
              ["1:64:1:0:0:0:0:0:0:0::Portugal", fav_ref])
vu.write_epg_mapping_file([("RTP1.pt", fav_ref, "RTP 1")], "pt", E2)
check(mapped() == sorted([country_ref, fav_ref]),
      "the favourites' entry added beside Portugal's")
vu.write_epg_mapping_file([("SIC.pt", country_ref, "SIC")], "pt", E2)
check(mapped() == sorted([country_ref, fav_ref]),
      "Portugal exported again: the favourites' entry stays")
check(u'<channel id="RTP1.pt">' in open(EPG, "rb").read().decode("utf-8"),
      "with its own id")
accent_ref = ref("sicn")
write_bouquet(bm.FAVOURITES_BOUQUET,
              ["1:64:1:0:0:0:0:0:0:0::Portugal", fav_ref, accent_ref])
vu.write_epg_mapping_file([("SICNoticias.pt", accent_ref,
                            u"SIC Notícias")], "pt", E2)
check(u"SIC Notícias" in open(EPG, "rb").read().decode("utf-8") and
      len(mapped()) == 3, "a favourite's own name with an accent "
      "(Python 2: the file was not written)")
write_bouquet("userbouquet.vavoo_portugal.tv", [])
vu.write_epg_mapping_file([("X.pt", ref("x"), "X")], "pt", E2)
check(country_ref not in mapped(), "an entry no bouquet holds: gone")
write_bouquet("userbouquet.vavoo_portugal.tv", [country_ref])
vu.write_epg_mapping_file([("SIC.pt", country_ref, "SIC")], "pt", E2)
check(bm.remove_bouquets_by_name("Portugal") == 1 and
      mapped() == sorted([fav_ref, accent_ref]),
      "Portugal's bouquet removed: the favourites keep their guide")
os.remove(os.path.join(E2, bm.FAVOURITES_BOUQUET))
vu.prune_epg_mapping_files(E2)
check(not os.path.exists(EPG), "no bouquet left: the file deleted")
check(vu.EPGIMPORT_DIR.startswith(TMP), "never /etc/epgimport")
finish()
