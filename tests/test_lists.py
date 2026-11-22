# -*- coding: utf-8 -*-
"""Phase 3 screens: favourites (folders, move, numbers, keys)."""
from __future__ import print_function
import os
import xml.etree.ElementTree as ET
import vavoo.vavoo_theme as vt
import vavoo.vavoo_proxy as vp
from harness import (plugin, store, check, finish, make, row_text, Session,
                     NOTES, MENUS, V)
REAL_REQUIRE = plugin._require_parental_pin

print("1. Favourites screen: keys, rows numbered in the user's order")
for i, (name, cc, country) in enumerate((("SIC", "pt", "Portugal"), ("RAI 1",
                                                                     "it", "Italy"), ("TF1", "fr", "France"), ("RTP 1", "pt", "Portugal"))):
    store.add_favourite(name, "u%d" % (i + 1), country, cc)
s = Session()
fv = make(plugin.VavooFavourites, s)
fv._build_list()
w = fv.widgets
check([w[k].text for k in ("red", "green", "yellow", "blue")] == [
      "Back", "Remove Fav", "Move", "Folder"], "keys: Back / Remove Fav / Move / Folder")
a = w["actions"].actions
check(all(str(d) in a for d in range(10)) and "left" in a and "nextBouquet" in a,
      "number keys, left/right and CH± bound")
check(
    [
        row_text(r) for r in w["menulist"].rows] == [
            u"1  SIC",
            u"2  RAI 1",
            u"3  TF1",
            u"4  RTP 1"],
    "rows numbered, in the order added: %r" % [
        row_text(r) for r in w["menulist"].rows])
check(w["proxy_status"].text == u"★ Favourites · 1/4", "status line")

print("2. Number keys and wrap")
a["3"]()
check(w["menulist"].index == 2, "3 -> row 3")
a["up"]()
a["up"]()
a["up"]()
check(w["menulist"].index == 3, "UP from the top wraps to the last row")

print("3. Move (YELLOW), saved once on Done")
w["menulist"].moveToIndex(3)   # RTP 1
a["yellow"]()
check(
    fv.moving and w["yellow"].text == "Done" and w["proxy_status"].text == u"⇅  RTP 1",
    "moving: Done, status '⇅  RTP 1'")
check(NOTES and NOTES[-1].startswith("Moving RTP 1"), "the app's hint shown")
a["up"]()
check([r[0][0] for r in w["menulist"].rows] == ["SIC", "RAI 1",
      "RTP 1", "TF1"] and w["menulist"].index == 2, "UP: one place up")
check([e["url"] for e in store.load_favourites()]
      == ["u1", "u2", "u3", "u4"], "not saved yet")
fv._digit_time = 0
a["1"]()
check([r[0][0] for r in w["menulist"].rows][0] ==
      "RTP 1" and w["menulist"].index == 0, "a number: to that place")
a["up"]()
check(w["menulist"].index == 0, "no wrap while moving")
a["right"]()
check([r[0][0] for r in w["menulist"].rows][-1] ==
      "RTP 1", "RIGHT: a page down (stops at the end)")
a["left"]()
check([r[0][0] for r in w["menulist"].rows][0] == "RTP 1", "LEFT: a page up")
a["green"]()
check(len(store.load_favourites()) == 4, "GREEN does nothing while moving")
a["ok"]()
check(not fv.moving and w["yellow"].text == "Move", "OK: Done")
check([e["url"] for e in store.load_favourites()] == [
      "u4", "u1", "u2", "u3"], "saved once: new order")
w["menulist"].moveToIndex(1)
a["yellow"]()
a["down"]()
fv.onClose[-1]()   # leaving the screen while moving saves too
check([e["url"] for e in store.load_favourites()] == [
      "u4", "u2", "u1", "u3"], "leaving while moving saves")
fv.moving = False

print("4. Folders (BLUE)")
fv._build_list()
w["menulist"].moveToIndex(1)   # RAI 1
a["blue"]()
title, entries, choose = MENUS[-1]
check(
    title == "Folder for RAI 1" and [
        k for _l,
        k in entries] == [
            "none",
            "new"],
    "picker: No folder, New folder…")
choose("new")
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VirtualKeyBoard and kw.get("title") ==
      "Folder name (e.g. Sport)", "New folder: keyboard")
cb("Sport")
check(store.folder_of("u2") ==
      "Sport" and NOTES[-1] == u"RAI 1 → Sport", "in Sport, 'RAI 1 → Sport'")
check(fv.showing_folders, "now the top shows folders")
check([row_text(r) for r in w["menulist"].rows] == ["All channels (4)", "Sport (1)", "No folder (3)"],
      "rows: All channels / Sport / No folder: %r" % [row_text(r) for r in w["menulist"].rows])
check(
    w["proxy_status"].text == u"★ Favourites · 1/3",
    "status counts folder rows")
a["green"]()
a["yellow"]()
check(not fv.moving and len(store.load_favourites())
      == 4, "no Remove / Move on folder rows")
w["menulist"].moveToIndex(0)
a["blue"]()
n_menus = len(MENUS)
check(len(MENUS) == n_menus, "BLUE on All channels: nothing")
w["menulist"].moveToIndex(1)
a["blue"]()
title, entries, choose = MENUS[-1]
check(
    title == "Sport" and [
        k for _l,
        k in entries] == [
            "rename",
            "remove"],
    "BLUE on a folder: Rename / Remove")
choose("rename")
cls, args, kw, cb = s.opened[-1]
check(kw.get("text") == "Sport", "rename: the keyboard starts with the name")
cb("Calcio")
check(store.folders() == ["Calcio"] and NOTES[-1]
      == "Folder renamed to Calcio", "renamed")
w["menulist"].moveToIndex(1)
a["ok"]()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VavooFavourites and args == (
    "favourites", "Calcio"), "OK opens the folder screen")
sub = make(plugin.VavooFavourites, s, "favourites", "Calcio")
sub._build_list()
check(sub.widgets["proxy_status"].text == u"★ Favourites ➾ Calcio · 1/1" and [r[0][0]
      for r in sub.widgets["menulist"].rows] == ["RAI 1"], "folder screen: its channels, title with ➾")
store.set_folder("u4", "Calcio")
sub._build_list()
sub.widgets["menulist"].moveToIndex(1)
sub.widgets["actions"].actions["yellow"]()
sub.widgets["actions"].actions["up"]()
sub.widgets["actions"].actions["ok"]()
order = [e["url"] for e in store.load_favourites()]
check(
    order == [
        "u2",
        "u4",
        "u1",
        "u3"] or order.index("u1") == 2 and order.index("u3") == 3,
    "a folder's channels swap only their own places: %r" %
    order)
none = make(plugin.VavooFavourites, s, "favourites",
            plugin.VavooFavourites.FOLDER_NONE)
none._build_list()
check([r[0][0] for r in none.widgets["menulist"].rows] == ["SIC", "TF1"] and
      u"No folder" in none.widgets["proxy_status"].text, "No folder screen")
fv._build_list()
w["menulist"].moveToIndex(1)
a["blue"]()
MENUS[-1][2]("remove")
check(
    store.folders() == [] and len(
        store.load_favourites()) == 4 and not fv.showing_folders,
    "folder removed, channels stay; no folder left: plain list")

print("5. Remove (GREEN) keeps the place")
w["menulist"].moveToIndex(1)
removed = w["menulist"].rows[1][0][0]
a["green"]()
check(len(store.load_favourites()) == 3 and w["menulist"].index == 1 and
      w["menulist"].rows[1][0][0] != removed, "removed, the next one takes its place")

print("6. Recently watched keys")
rc = make(plugin.VavooFavourites, s, "recent")
check([rc.widgets[k].text for k in ("red",
                                    "green",
                                    "yellow",
                                    "blue")] == ["Back",
                                                 "Add Fav",
                                                 "Search",
                                                 "Full Screen"],
      "recent: Back / Add Fav / Search / Full Screen")
store._write_json(store.recent_file(),
                  [{"name": "SIC",
                    "url": "u1",
                    "country_name": "Portugal",
                    "country_code": "pt"},
                   {"name": "X",
                    "url": "ux"}])
rc._build_list()
rc.widgets["actions"].actions["yellow"]()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VavooSearch and args[1] == [
      "SIC###u1", "X###ux"], "YELLOW: search in this list")
played = []
rc._play_selected = lambda: played.append(rc.widgets["menulist"].index)
cb(("X", "ux"))
check(played == [1], "a result: highlighted and played")
rc.widgets["actions"].actions["yellow"]
rc.widgets["menulist"].moveToIndex(0)
check(rc.widgets["green"].text == "Remove Fav" and rc.widgets["proxy_status"].text.endswith(
    u"★"), "recent: SIC is a favourite")

print("7. The proxy's channel_rows(): categories, grouped / not")
fp = vp.VavooProxy.__new__(vp.VavooProxy)
fp.get_local_ip = lambda: "127.0.0.1"
fp.channels_by_country = {"italy": [
    {"id": "1", "name": "RAI 1 .b", "group": "Italy ➾ Generalisti", "country": "Italy"},
    {"id": "2", "name": "RAI 1 .c", "group": "Italy ➾ Generalisti", "country": "Italy"},
    {"id": "3", "name": "SKY SPORT", "group": "Italy ➾ Sport", "country": "Italy"},
    {"id": "4", "name": "TV8", "group": "Italy", "country": "Italy"}]}
rows = vp.VavooProxy.channel_rows(fp, "Italy")
check([(r["name"], r["category"]) for r in rows] ==
      [("RAI 1", "Generalisti"), ("SKY SPORT", "Sport"), ("TV8", "")],
      "grouped: one RAI 1 row, categories after ➾: %r" % [(r["name"], r["category"]) for r in rows])
check(rows[0]["id"].startswith("grp:italy:"), "grouped row: a group id")
rows = vp.VavooProxy.channel_rows(fp, "italy", grouped=False)
check([r["name"] for r in rows] == ["RAI 1 .b", "RAI 1 .c", "SKY SPORT",
      "TV8"], "Group Sources off: every source, its catalog name")
check(
    vp.VavooProxy.country_counts(
        fp,
        False) == {
            "italy": 4} and vp.VavooProxy.country_counts(fp) == {
                "italy": 3},
    "counts follow the setting")
fp.group_lock = __import__("threading").Lock()
fp._group_state = {
    "grp:italy:rai 1": {
        "member": "1", "avoid": {
            "2": __import__("time").time()}}}
fp._group_pins = {}
fp._group_members = lambda country, key: fp.channels_by_country["italy"][:2]
src = vp.VavooProxy.get_group_sources(fp, "grp:italy:rai 1")
check([m["failed"] for m in src["members"]] == [False,
                                                True] and src["current"] == "1",
      "sources: the one that failed a moment ago marked")

print("8. Sub-categories in the channel list")
plugin.cfg.subcategories = V(True)
plugin.cfg.group_sources = V(True)
plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True
v = make(plugin.vavoo, s, "Italy", None)
v._preload_channel_picons = lambda: None
data = vp.VavooProxy.channel_rows(fp, "Italy")
v._build_channel_list(data)
vw = v.widgets
check(
    v.showing_categories and [
        row_text(r) for r in vw["menulist"].rows] == [
            "All channels (3)",
            "Generalisti (1)",
            "Sport (1)",
            "General (1)"],
    "rows: All channels, categories A-Z, General last: %r" %
    [
        row_text(r) for r in vw["menulist"].rows])
check([r[0][0] for r in vw["menulist"].rows] == ["Italy"]
      * 4, "each with the country's flag (its name)")
check(
    vw["proxy_status"].text == u"Italy · 1/4",
    "status line %r" %
    vw["proxy_status"].text)
check(
    v.itemlist == [
        "RAI 1###" +
        data[0]["url"],
        "SKY SPORT###" +
        data[1]["url"],
        "TV8###" +
        data[2]["url"]],
    "search: the whole country")
before = len(store.load_favourites())
vw["actions"].actions["green"]()
check(len(store.load_favourites()) == before,
      "GREEN does nothing on a category")
vw["menulist"].moveToIndex(2)
vw["actions"].actions["ok"]()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.vavoo and kw.get("category") == "Sport" and kw.get(
    "channels") is v._all_channels, "OK opens the category with the country's list")
sub = make(
    plugin.vavoo,
    s,
    "Italy",
    None,
    None,
    category="Sport",
    channels=v._all_channels)
sub._preload_channel_picons = lambda: None
sub.cat()
check(
    not sub.showing_categories and [
        r[0][0] for r in sub.widgets["menulist"].rows] == ["SKY SPORT"],
    "category screen: its channels, no second request")
check(
    sub.widgets["proxy_status"].text == u"Italy ➾ Sport · 1/1",
    "title 'Italy ➾ Sport' %r" %
    sub.widgets["proxy_status"].text)
check(len(sub.itemlist) == 3, "its search: still the whole country")
plugin.cfg.subcategories = V(False)
flat = make(plugin.vavoo, s, "Italy", None)
flat._preload_channel_picons = lambda: None
flat._build_channel_list(data)
check(
    not flat.showing_categories and [
        row_text(r) for r in flat.widgets["menulist"].rows] == [
            u"1  RAI 1",
            u"2  SKY SPORT",
            u"3  TV8"],
    "Sub-categories off: numbered channels")
flat.widgets["number_actions"].actions["3"]()
check(flat.widgets["menulist"].index == 2, "number key: row 3")
one = make(plugin.vavoo, s, "Spain", None)
one._preload_channel_picons = lambda: None
plugin.cfg.subcategories = V(True)
one._build_channel_list([{"name": "La 1", "url": "e1", "category": "Spain TV"}, {
                        "name": "La 2", "url": "e2", "category": "Spain TV"}])
check(not one.showing_categories, "one category only: plain list")

print("9. Search as in the app")
plugin.NumericalTextInput = lambda **k: type(
    "N", (), {"nextKey": lambda self: None})()
items = [
    "SPORT 1###a1###Italy",
    "SPORT 11###a2###Italy",
    "SKY SPORT 1 HD###a3###Italy",
    "ATV###a4###Turkey",
    "TV 2###a5###Denmark",
    "Cuátro###a6###Spain"]
store.add_favourite("TV 2", "a5", "Denmark", "dk")
se = make(plugin.VavooSearch, s, None, items, scope="all channels")
se.search_text = "1"
se.updateFilteredList()
check([r[0] for r in se.filteredList] == ["SKY SPORT 1 HD", "SPORT 1"] or
      set(r[0] for r in se.filteredList) == set(["SPORT 1", "SKY SPORT 1 HD"]),
      "'1': not SPORT 11 %r" % [r[0] for r in se.filteredList])
se.search_text = "tv"
se.updateFilteredList()
check([r[0] for r in se.filteredList] == ["TV 2"], "'tv': not ATV")
check(row_text(se.widgets["channel_list"].rows[0]) ==
      u"TV 2  ★  · Denmark", "row: 'TV 2  ★  · Denmark'")
check(se.widgets["status"].text == "1 found", "status: 1 found")
se.search_text = "cuatro"
se.updateFilteredList()
check([r[0] for r in se.filteredList] == ["Cuátro"], "accents do not count")
se.search_text = ""
se.updateFilteredList()
check(se.widgets["status"].text == "6 channels", "empty: N channels")
se.search_text = "sport"
se.updateFilteredList()
se.selectedIndex = 1
se.onOk()
res = se.closed_with[-1][0]
check(res[0] == se.filteredList[1][0] and len(res[3]) ==
      3 and res[4] == 1, "OK: the results and the place")
guide = object()
plugin.vUtils.peek_epg_guide = lambda code: guide if code == "dk" else None
plugin.vUtils.peek_now_next = lambda name, code: (
    "ok", (0, 1, u"Formula 1 Grand Prix"), None) if name == "TV 2" else (
        "ok", (0, 1, "News"), None)
plugin.get_country_code = lambda c: {
    "Denmark": "dk",
    "Italy": "it",
    "Turkey": "tr",
    "Spain": "es"}.get(c)
se.search_text = "grand"
se.updateFilteredList()
check([(r[0], r[3]) for r in se.filteredList] == [("TV 2", u"Formula 1 Grand Prix")],
      "3+ letters: the programme on now (guides in memory only)")
check(row_text(se.widgets["channel_list"].rows[0]).endswith(
    u"▶ Formula 1 Grand Prix"), "row: '▶ title'")
se.search_text = "gr"
se.updateFilteredList()
check(se.filteredList == [], "fewer than 3: no programme matches")
played = []
plugin._require_parental_pin = lambda session, screen, country, fn, **kw: (
    played.append((country, kw.get("channel_name"))), fn())
s2 = Session()
plugin.play_search_result(s2,
                          None,
                          ("SKY SPORT 1 HD",
                           "a3",
                           "Italy",
                           [("SPORT 1",
                             "a1",
                             "Italy"),
                            ("SKY SPORT 1 HD",
                             "a3",
                             "Italy"),
                               ("TV 2",
                                "a5",
                                "Denmark")],
                              1),
                          lambda *a: None)
cls, args, kw, cb = s2.opened[-1]
check(cls is plugin.Playstream2 and args[0] == "SKY SPORT 1 HD" and args[2] == 1 and len(
    args[4]) == 3, "the player gets the results as its list, at the chosen one")
check(
    kw["country_names"] == [
        "Italy",
        "Italy",
        "Denmark"] and kw["country_codes"] == [
            "it",
            "it",
            "dk"] and played == [
                ("Italy",
                 "SKY SPORT 1 HD")],
    "each result keeps its country; PIN of the chosen one's country")

print("10. Search all: in-process, hidden countries left out")
store.set_hidden_countries(["Spain"])
mv = make(
    plugin.MainVavoo.__new__(
        plugin.MainVavoo).__class__,
    s) if False else None
MV = plugin.MainVavoo
obj = MV.__new__(MV)
obj.widgets = {}
MV.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
MV.__getitem__ = lambda self, k: self.widgets[k]
obj._closed = False
obj._search_loading = False
obj.session = s
obj.countries = ["Italy", "Spain"]
asked = []


class FakeRows(object):
    def channel_rows(self, country, grouped=True):
        asked.append((country, grouped))
        return [{"name": "X " + country, "url": "x" + country}]


plugin.vavoo_proxy.proxy = FakeRows()


class Now(object):
    def __init__(self, target=None):
        self.target = target
        self.daemon = True

    def start(self):
        self.target()


real_thread = plugin.threading.Thread
plugin.threading.Thread = Now
plugin.reactor.callFromThread = lambda fn, *a: fn(*a)
opened = []
obj._open_search_all = lambda items: opened.append(items)
obj.search_all()
plugin.threading.Thread = real_thread
check(asked == [("Italy", True)] and opened == [["X Italy###xItaly###Italy"]],
      "only the shown countries, read in-process %r %r" % (asked, opened))

print("11. Choose countries")
store.set_hidden_countries([])
cs = make(plugin.VavooCountries, s, ["Spain", "Albania", "Italy"])
cs.refresh(0)
cw = cs.widgets
check([cw[k].text for k in ("red", "green", "yellow", "blue")] == [
      "Back", "Save", "Show all", "Hide all"], "keys: Back / Save / Show all / Hide all")
vals = [[e.text for e in r[1:] if hasattr(
    e, "text")][0] for r in cw["menulist"].rows]
check([r[0][0] for r in cw["menulist"].rows] == ["Albania",
      "Italy", "Spain"] and vals == [u"✓"] * 3, "A-Z, all ✓")
check(cw["statusbar"].text == "3 of 3 countries shown", "status")
cw["menulist"].moveToIndex(2)
cw["actions"].actions["ok"]()
row = cw["menulist"].rows[2]
check([e.text for e in row[1:] if hasattr(e, "text")][0] == u"✗" and getattr(
    row[-1], "color", None) == 0x7a7a86, "OK: Spain ✗ and greyed")
check(cw["statusbar"].text == "2 of 3 countries shown", "status follows")
cw["actions"].actions["red"]()
check(cs.closed_with == [] and NOTES[-1].startswith("Changes not saved"),
      "Back with changes: warned once")
cw["actions"].actions["blue"]()
cw["actions"].actions["green"]()
check(NOTES[-1] == "Keep at least one country" and cs.closed_with ==
      [], "all hidden: not saved")
cw["actions"].actions["yellow"]()
cw["menulist"].moveToIndex(0)
cw["actions"].actions["left"]()
cw["actions"].actions["green"]()
check(
    cs.closed_with == [
        (True,
         )] and store.hidden_countries() == set(
        ["Albania"]),
    "saved: Albania hidden")
cs2 = make(plugin.VavooCountries, s, ["Albania", "Italy"])
cs2.widgets["actions"].actions["red"]()
check(cs2.closed_with == [(False,)], "Back without changes: leaves at once")

print("12. Main list: hidden countries, first start")
plugin.cfg.countries_asked = type(
    "C", (), {"value": False, "save": lambda self: None})()
plugin.configfile = type("F", (), {"save": lambda self: None})()
obj.cat_list = []
obj._themed = True
obj._reloading = False
obj._start_last_done = True
obj._country_load_failures = 0
obj._update_ui = lambda: obj.widgets["menulist"].setList(obj.cat_list)
obj.widgets["menulist"] = plugin.m2list([])
obj.widgets["version"] = plugin.Label()
obj.widgets["name"] = plugin.Label()
obj._on_countries_response(
    '["Albania", "Italy", "Spain"]', None, {
        "italy": 3}, 0, [])
check([r[0][0] for r in obj.widgets["menulist"].rows] == [
      "Italy", "Spain"], "Albania hidden from the main list")
check(
    obj.countries == [
        "Albania",
        "Italy",
        "Spain"],
    "...but kept for Choose countries")
check(not any(o[0] is plugin.VavooCountries for o in s.opened[-1:]),
      "no Choose countries over the main list (a new install's welcome asks before it)")
store.set_hidden_countries([])

print("13. Settings rows")
plugin.cfg.choose_countries = object()

print("14. The pick skin")
for theme in vt.MODERN_THEMES:
    for large in (True, False):
        for width in (1280, 1920, 2560):
            text = vt.pick_screen(theme, large, width)
            root = ET.fromstring(text)
            names = set(w.get("name") for w in root if w.get("name"))
            ok = names == {
                "menulist",
                "description",
                "statusbar",
                "version",
                "red",
                "green",
                "yellow",
                "blue"}
            inside = all(int(w.get("position").split(",")[0]) + int(w.get("size").split(",")[0]) <= width
                         for w in root if w.get("position"))
            if not (ok and inside):
                check(
                    False, "pick %s %s %d: %r" %
                    (theme, large, width, sorted(names)))
check(True, "pick skin: the widgets VavooPickScreen creates, inside the screen (all themes/sizes)")
m = vt.list_metrics("prism", True, 1920, "big")
check(m["list_w"] == 880 and m["rows"] == vt.list_metrics("prism", True, 1920)[
      "rows"], "the 'big' list: the settings' width, the list's rows")
check(vt.pick_screen("classic", True, 1920)
      is None, "Classic: its own vavoo_pick.xml")

print("15. Channel logos / initials")
plugin.cfg.logos = V(False)
plugin.theme_active = lambda: True
row = plugin.show_list(
    "RAI 1",
    "u",
    is_channel=True,
    logo_url="http://x/logo.png",
    themed=True)
pics = [e for e in row[1:] if hasattr(e, "png")]
txts = [e for e in row[1:] if hasattr(e, "text")]
m = plugin.theme_metrics("list")
check(
    len(pics) == 1 and "/tiles/tile_%d_" %
    m["icon_h"] in pics[0].png and pics[0].size == (
        m["icon_h"],
        m["icon_h"]),
    "logos off: a square tile, the icon box's height %r" %
    [
        getattr(
            p,
            "png",
            None) for p in pics])
check(pics[0].pos[0] == m["icon_x"] + (m["icon_w"] -
      m["icon_h"]) // 2, "centred in the icon box")
check(txts[0].text == "R1" and txts[0].font == 1 and txts[0].pos ==
      pics[0].pos, "'R1' over it, two-letter font")
row = plugin.show_list("ZDF", "u", is_channel=True, themed=True)
check([e for e in row[1:] if hasattr(e, "text")]
      [0].font == 2, "one letter: the bigger font")
cache = []
plugin.get_picon_cache_path = lambda url: os.path.join(
    plugin.vavoo_store.TILE_DIR, "logo.png")
open(
    os.path.join(
        plugin.vavoo_store.TILE_DIR,
        "logo.png"),
    "wb").write(
    b"x" *
    200)
row = plugin.show_list(
    "RAI 1",
    "u",
    is_channel=True,
    logo_url="http://x/logo.png",
    themed=True)
check([e.png for e in row[1:] if hasattr(e,
                                         "png")][0].endswith("tile_%d_%03d.png" % (m["icon_h"],
                                                                                   plugin.vavoo_store.tile_hue("RAI 1"))),
      "logos off: no logo even when one is cached")
plugin.cfg.logos = V(True)
row = plugin.show_list(
    "RAI 1",
    "u",
    is_channel=True,
    logo_url="http://x/logo.png",
    themed=True)
check([e.png for e in row[1:] if hasattr(e, "png")] == [os.path.join(
    plugin.vavoo_store.TILE_DIR, "logo.png")], "logos on: the logo")
row = plugin.show_list(
    "RAI 1",
    "u",
    is_channel=True,
    logo_url=None,
    themed=True)
check("tile_" in [e.png for e in row[1:] if hasattr(
    e, "png")][0], "logos on, no logo: the initials")
plugin.cfg.logos = V(False)
plugin.loadPNG = lambda path: path
row = plugin.show_list(
    "RAI 1",
    "u",
    is_channel=True,
    logo_url="http://x/logo.png",
    themed=False)
check([e.png for e in row[1:] if hasattr(e, "png")][0].endswith("vavoo_ico.png") and not [
      e for e in row[1:] if getattr(e, "text", None) == "R1"], "Classic, logos off: the Vavoo icon")
dl = []
v2 = make(plugin.vavoo, s, "Italy", None)
v2._channel_entries = [("A", "u", "http://logo")]
plugin.threading.Thread = lambda target=None: dl.append(target) or type(
    "T", (), {"start": lambda self: None, "daemon": True})()
v2._preload_channel_picons()
check(dl == [], "logos off: nothing downloaded")
plugin.threading.Thread = real_thread
row = plugin.show_list("Italy", "Italy", themed=True)
check(not [e for e in row[1:] if getattr(e, "text", None)
      in ("IT", "I")], "countries keep their flag (no tile)")

print("16. Parental control: the PIN pad")
store.set_pin(None)
pad = make(plugin.VavooPin, s, "Enter the PIN", 4, lambda pin: pin == "1234")
pw = pad.widgets
check(pw["dots"].text == u"○ ○ ○ ○" and pw["title"].text ==
      "Enter the PIN", "four empty dots")
for d in (1, 2, 9):
    pw["actions"].actions[str(d)]()
check(pw["dots"].text == u"● ● ● ○", "three typed")
pw["actions"].actions["left"]()
check(pad.digits == "12", "LEFT deletes one")
pw["actions"].actions["9"]()
pw["actions"].actions["9"]()
pw["actions"].actions["7"]()
check(pad.digits == "1299", "no more than four")
pad.submit()
check(pw["message"].text == "Wrong PIN - try again" and pad.digits ==
      "" and pad.closed_with == [], "wrong: says so, dots emptied, stays open")
for d in "1234":
    pw["actions"].actions[d]()
pad.submit()
check(pad.closed_with == [("1234",)], "right: closes with the PIN")
pad2 = make(plugin.VavooPin, s, "x", 4, lambda pin: None)
for d in "0000":
    pad2.widgets["actions"].actions[d]()
pad2.submit()
check(pad2.closed_with == [(None,)],
      "checker None (the pause): closes with nothing")
pad3 = make(plugin.VavooPin, s, "x")
pad3.widgets["actions"].actions["cancel"]()
check(pad3.closed_with == [(None,)], "EXIT cancels")

print("17. ask_pin / _require_parental_pin")
plugin._require_parental_pin = REAL_REQUIRE
ok = []
plugin.ask_pin(s, None, lambda: ok.append(1))
check(ok == [1], "no PIN: open at once")
store.set_pin("1234")
store.relock()
n = len(s.opened)
plugin.ask_pin(s, None, lambda: ok.append(2))
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VavooPin and args[1] == 4 and ok == [
      1], "PIN set: the pad (4 digits)")
check(args[2]("0000") is False and args[2]("1234")
      is True, "its checker: wrong / right")
cb("1234")
check(ok == [1, 2], "right PIN: goes on")
plugin.ask_pin(s, None, lambda: ok.append(3))
check(ok == [1, 2, 3] and len(s.opened) ==
      n + 1, "then open for a while: no pad")
store.relock()
for _x in range(5):
    store.check_pin("0000")
plugin.ask_pin(s, None, lambda: ok.append(4))
check(ok == [1,
             2,
             3] and NOTES[-1].startswith("Too many wrong PINs - try again in"),
      "the pause: a note, no pad")
p_ = store._parental()
for k in ("blocked_until", "blocked_until_up", "boot", "wrong", "blocks"):
    p_.pop(k, None)
store._save_parental(p_)
store.relock()
called = []
plugin._require_parental_pin(
    s,
    None,
    "Spain",
    lambda: called.append("es"),
    channel_name="TVE 1")
check(called == ["es"], "an ordinary channel: no PIN")
plugin._require_parental_pin(
    s,
    None,
    "Spain",
    lambda: called.append("xxx"),
    channel_name="XXX Gold")
check(s.opened[-1][0] is plugin.VavooPin and called == ["es"],
      "an adult channel: the pad %r %r %r %r" % (s.opened[-1][0],
                                                 called,
                                                 store.lock_adult(),
                                                 store.is_unlocked()))
store.set_locked_countries(["Spain"])
plugin._require_parental_pin(
    s, None, "Spain", lambda: called.append("country"))
check(s.opened[-1][0] is plugin.VavooPin, "a locked country: the pad")
store.unlock()
plugin._require_parental_pin(s, None, "Spain", lambda: called.append("open"))
check(called[-1] == "open", "unlocked: straight on")

print("18. New PIN twice")
got = []
plugin.ask_new_pin(s, lambda pin: got.append(pin))
cls, args, kw, cb = s.opened[-1]
check(args[0] == "New PIN (4 digits)" and args[1]
      == 4, "first: New PIN (4 digits)")
cb("5678")
cls, args, kw, cb2 = s.opened[-1]
check(args[0] == "The same PIN again", "then: The same PIN again")
cb2("5679")
check(got == [] and NOTES[-1] ==
      "The two PINs differ - not changed", "differ: not changed")
plugin.ask_new_pin(s, lambda pin: got.append(pin))
s.opened[-1][3]("5678")
s.opened[-1][3]("5678")
check(got == ["5678"], "same twice: done")

print("19. Parental Control screen")
store.set_pin(None)
store.set_locked_countries([])
ps = make(plugin.VavooParental, s, ["Italy", "Albania"])
ps.refresh(0)
pw = ps.widgets
names = [row_text(r) for r in pw["menulist"].rows]
check(
    names == [
        "Set a PIN",
        "Lock adult channels",
        "Lock the settings",
        "Albania",
        "Italy"],
    "no PIN: rows %r" %
    names)
vals = [[e.text for e in r[1:] if hasattr(
    e, "text")][0] for r in pw["menulist"].rows]
check(vals[:3] == [u"—", u"‹ Yes ›", u"‹ No ›"] and vals[3:] == [u"—", u"—"],
      "values: —, ‹ Yes ›, ‹ No ›, countries —")
check(
    pw["statusbar"].text == "No PIN yet: nothing is locked until one is set.",
    "status without PIN")
check([pw[k].text for k in ("red", "green", "yellow", "blue")]
      == ["Back", "", "", ""], "only RED Back")
check(
    'name="red"' in ps.skin and 'name="green"' not in ps.skin and 'key_green' not in ps.skin,
    "its theme skin draws only the RED button")
check(not any(hasattr(e,
                      "png") for r in pw["menulist"].rows[:3] for e in r[1:]) and any(hasattr(e,
                                                                                              "png") for e in pw["menulist"].rows[3][1:]),
      "option rows: text only; countries: flags")
pw["actions"].actions["ok"]()
s.opened[-1][3]("1111")
s.opened[-1][3]("1111")
check(store.has_pin() and NOTES[-1] == "PIN saved", "Set a PIN: saved")
names = [row_text(r) for r in pw["menulist"].rows]
check(names[:2] == ["Change the PIN",
                    "Remove the PIN (unlock everything)"],
      "now: Change / Remove")
pw["menulist"].moveToIndex(2)
pw["actions"].actions["right"]()
check(not store.lock_adult(), "adult lock off")
pw["menulist"].moveToIndex(3)
pw["actions"].actions["left"]()
check(store.lock_settings(), "settings lock on")
pw["menulist"].moveToIndex(5)   # Italy
pw["actions"].actions["ok"]()
check(store.locked_countries() == set(["Italy"]), "Italy locked")
row = pw["menulist"].rows[5]
check(any(getattr(e, "png", "").find("lock_") >=
      0 for e in row[1:]), "a padlock on Italy's row")
check(pw["statusbar"].text == u"PIN set · 1 countries locked",
      "status: PIN set · 1 countries locked")
pw["menulist"].moveToIndex(1)
pw["actions"].actions["ok"]()
check(store.has_pin() and NOTES[-1] ==
      "Press again to confirm", "Remove: press again")
pw["actions"].actions["ok"]()
check(not store.has_pin() and store.locked_countries()
      == set(["Italy"]), "removed; the choices stay")

print("20. The old settings PIN moves; settings lock; Now/Next; zapping")
store.set_pin(None)
store.set_locked_countries([])


class T(object):
    def __init__(self, v):
        self.value = v

    def save(self):
        pass


plugin.cfg.parental_pin = T("2468")
plugin.cfg.parental_countries = T("Turkey, Albania")
plugin._move_parental_out_of_settings()
check(store.has_pin() and store.locked_countries() == set(["Turkey", "Albania"]) and
      plugin.cfg.parental_pin.value == "" and plugin.cfg.parental_countries.value == "",
      "old PIN and countries moved, the settings emptied")
check(store.check_pin("2468")[0] == "ok", "the old PIN still opens")
store.set_pin("1234")
store.set_option("settings", True)
store.relock()
plugin.open_settings(s)
check(s.opened[-1][0] is plugin.VavooPin, "settings locked: the pad first")
s.opened[-1][1][2]("1234")
s.opened[-1][3]("1234")
check(s.opened[-1][0] is plugin.vavoo_config,
      "then the settings %r" % (s.opened[-1:],))
store.set_option("settings", False)
store.relock()
plugin.open_settings(s)
check(s.opened[-1][0] is plugin.vavoo_config,
      "not locked: the settings at once")
store.set_option("adult", True)
host = make(plugin.VavooFavourites, s)
store.add_favourite("XXX Gold", "xg", "Spain", "es")
host._build_list()
plugin.cfg.list_epg = V(True)
for i, r in enumerate(host.widgets["menulist"].rows):
    if r[0][0] == "XXX Gold":
        host.widgets["menulist"].moveToIndex(i)
host._epg_panel_row = None
host._epg_panel_changed()
check(
    host.widgets["epg_now_title"].text == "Locked",
    "Now/Next: a locked channel shows Locked %r %r" %
    (host.widgets["epg_now_title"].text,
     host._epg_panel_row))
plugin.cfg.list_epg = V(False)
pl = plugin.Playstream2.__new__(plugin.Playstream2)
pl.session = s
pl.list = [[("RAI 1", "r1")], [("XXX Gold", "xg")]]
pl.itemscount = 2
pl.currentindex = 0
pl.country_names = ["Italy", "Spain"]
pl.country_name = "Italy"
n = len(s.opened)
pl.zap_to(1)
check(len(s.opened) == n + 1 and s.opened[-1][0] is plugin.VavooPin and pl.currentindex ==
      0, "zapping to an adult channel: the pad first %r" % (s.opened[-1:],))

print("21. Main list padlock")
store.set_locked_countries(["Italy"])
obj._on_countries_response('["Albania", "Italy"]', None, {}, 0, [])
rows = {r[0][0]: r for r in obj.widgets["menulist"].rows}
check(any("lock_" in str(getattr(e,
                                 "png",
                                 "")) for e in rows["Italy"][1:]) and not any("lock_" in str(getattr(e,
                                                                                                     "png",
                                                                                                     "")) for e in rows["Albania"][1:]),
      "a padlock on the locked country only")
store.set_pin(None)
obj._on_countries_response('["Albania", "Italy"]', None, {}, 0, [])
rows = {r[0][0]: r for r in obj.widgets["menulist"].rows}
check(not any("lock_" in str(getattr(e, "png", ""))
      for e in rows["Italy"][1:]), "no PIN: no padlock")

print("22. Settings: the new rows, backup / restore, licences, about")


class Elem(object):
    def __init__(self, value):
        self.value = value
        self.saved_value = None
        self.saved = 0

    def tostring(self, v):
        return str(v)

    def load(self):
        self.value = self.saved_value

    def save(self):
        self.saved += 1


for name in plugin.BACKUP_SETTINGS:
    setattr(plugin.cfg, name, Elem("x_" + name))
plugin.cfg.theme = Elem("halo")
settings = plugin.plugin_settings()
check(
    settings["theme"] == "halo" and len(settings) == len(
        plugin.BACKUP_SETTINGS) and "parental_pin" not in settings,
    "plugin_settings(): the chosen settings, no parental control")
plugin.configfile = type("F", (), {"save": lambda self: None})()
plugin.apply_settings(
    {"theme": "orbit", "parental_pin": "9999", "nonsense": "1"})
check(plugin.cfg.theme.value == "orbit" and plugin.cfg.theme.saved ==
      1, "apply_settings(): set and saved")
plugin.getConfigListEntry = lambda *a: a
for name in (
    "genm3u",
    "show_log",
    "view_favourites",
    "choose_countries",
    "parental",
    "backup",
    "restore",
    "clear_favourites",
    "licences",
    "about",
        "playlist_key"):
    setattr(plugin.cfg, name, Elem(name))
cs = plugin.vavoo_config.__new__(plugin.vavoo_config)
cs.widgets = {
    "config": type(
        "C", (), {
            "l": type(
                "L", (), {
                    "setList": lambda self, l: None})()})()}
plugin.vavoo_config.__getitem__ = lambda self, k: self.widgets[k]
cs.setInfo = lambda: None
real_current_theme = plugin.current_theme
plugin.current_theme = lambda: "prism"
cs.show_all = True                  # (all the rows: "All settings")
cs._rows_seen = {}
cs.createSetup()
labels = [e[0] for e in cs.list]
order = [
    "Group Sources",
    "Channel Logos",
    "Sub-categories",
    "Choose countries",
    "Parental Control",
    "Backup Settings & Favourites",
    "Restore from Backup",
    "Show Log (Ok to view)",
    "View Favourites (Ok to open)",
    "Clear Favourites",
    "Licences",
    "About"]
check([l for l in labels if l in order] == order,
      "rows in the app's order: %r" % [l for l in labels if l in order])
check(
    "Parental Control PIN" not in labels and "Locked Countries" not in labels,
    "the old PIN rows are gone")
# Classic's backgrounds: a sub-option of Theme, only with Classic
plugin.current_theme = real_current_theme
plugin.cfg.theme = Elem("prism")
cs.createSetup()
labels = [e[0] for e in cs.list]
check(
    labels[0] == "Theme" and not any(
        "Background" in l for l in labels),
    "Prism: no background row")
plugin.cfg.theme.value = "classic"
cs.widgets["green"] = type(
    "G", (), {
        "instance": type(
            "I", (), {
                "setText": lambda self, t: None})()})()
cs.widgets["config"].isChanged = lambda: True
cs.onChangedEntry = []
cs.changedEntry()
labels = [e[0] for e in cs.list]
check(labels[:2] == ["Theme", "- Background"] and cs.list[1][1] is plugin.cfg.back,
      "Classic chosen (without LEFT / RIGHT): '- Background' right under Theme %r" % labels[:3])
check("Select Background" not in labels,
      "the old row after Clock Format is gone")
plugin.cfg.theme.value = "orbit"
cs.changedEntry()
check(not any("Background" in e[0]
      for e in cs.list), "another theme: the row goes")
names = dict(plugin.BakP)
check(names.get("oktus") == "Oktus" and names.get("kiddac") == "Kiddac",
      "choices shown 'Oktus' / 'Kiddac', saved as 'oktus' / 'kiddac': %r" % plugin.BakP)
plugin.current_theme = lambda: "prism"
cs.session = s
cs._closed = False
store.set_pin(None)
media = __import__("tempfile").mkdtemp()
store.BACKUP_MEDIA = (media,)
store.add_favourite("SIC", "u-sic", "Portugal", "pt")
cs.widgets["config"].getCurrent = lambda: ("x", plugin.cfg.backup)
cs.gnm3u()
check(NOTES[-1].startswith("Saved: " + media),
      "Backup: saved in the first folder: %r" % NOTES[-1])
store.clear_favourites()
cs.widgets["config"].getCurrent = lambda: ("x", plugin.cfg.restore)
restarted = []
plugin.restart_proxy_in_background = lambda: restarted.append(1)
cs.createSetup = lambda: None
cs.gnm3u()
title, entries, choose = MENUS[-1]
check(title == "Restore from Backup" and len(entries) ==
      1 and media in entries[0][0], "Restore: the backups found")
choose(entries[0][1])
check(store.is_favourite("u-sic") and restarted == [1] and NOTES[-1].startswith("Restored"),
      "restored: favourites back, proxy restarted")
bad = __import__("os").path.join(media, "VavooStream-backup-x.json")
open(bad, "w").write("{}")
choose(bad)
check(NOTES[-1] == "That file is not a Vavoo Stream backup",
      "another file: refused")
store.set_pin("1234")
store.relock()
cs.widgets["config"].getCurrent = lambda: ("x", plugin.cfg.backup)
cs.gnm3u()
check(s.opened[-1][0] is plugin.VavooPin,
      "Backup with a PIN set: the pad first")
store.set_pin(None)
cs.widgets["config"].getCurrent = lambda: ("x", plugin.cfg.clear_favourites)
cs.gnm3u()
cls, args, kw, cb = s.opened[-1]
check(
    cls is plugin.MessageBox and "Remove all favourite channels?" in args,
    "Clear Favourites asks first")
cb(False)
check(store.is_favourite("u-sic"), "no: kept")
cb(True)
check(store.load_favourites() == [] and NOTES[-1]
      == "Favourites cleared", "yes: cleared")
text = plugin.licences_text()
check(
    "CC BY-NC-SA 4.0" in text and all(
        ("  %s  " %
         n) in text for n in (
            "Lexend",
            "LiberationSans",
            "Manrope",
            "Oxanium",
            "Sora")),
    "Licences: the plugin's, then every font's")
cs.widgets["config"].getCurrent = lambda: ("x", plugin.cfg.licences)
cs.gnm3u()
cls, args, kw, cb = s.opened[-1]
check(cls is plugin.VavooLogViewer and kw.get("title") == "Licences" and kw.get(
    "tail_lines") >= 10000, "Licences opens the text viewer, the whole text")
cs.widgets["config"].getCurrent = lambda: ("x", plugin.cfg.about)
cs.gnm3u()
check(s.opened[-1][0] is plugin.MessageBox, "About: the information box")

finish()
