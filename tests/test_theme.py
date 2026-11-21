# -*- coding: utf-8 -*-
"""Phase 1 of the Android look: the theme skins (vavoo_theme.py), the
pictures they point at, and plugin.py's side of it (skin choice and
Classic fallback, keys, MENU, status lines, Now/Next lines), with
Enigma2 faked (e2stub.py). Run via run_theme_tests.sh."""
from __future__ import print_function
import io
import os
import re
import struct
import sys
import time as real_time
import types
import xml.etree.ElementTree as ET

import tempfile                                 # noqa: E402
import e2env                                    # noqa: E402
REPO = e2env.REPO
PLUGIN_DIR = e2env.PLUGIN_DIR
DEPLOYED = "/usr/lib/enigma2/python/Plugins/Extensions/vavoo"
import vavoo.vavoo_store as vstore              # noqa: E402
import vavoo.vavoo_theme as vt                  # noqa: E402
plugin = e2env.load_plugin()
vstore.set_paths(tempfile.mkdtemp(prefix="vavoo_theme_data_"))
import vavoo.vavoo_proxy as vp                  # noqa: E402
import vavoo.notification_system as ns          # noqa: E402

FAILS = 0
CHECKS = 0


def check(cond, what):
    global FAILS, CHECKS
    CHECKS += 1
    if not cond:
        FAILS += 1
        print("  FAIL: " + what)
    else:
        print("  ok:   " + what)


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    return struct.unpack(">II", head[16:24])


def jpg_size(path):
    data = open(path, "rb").read()
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + struct.unpack(">H", data[i + 2:i + 4])[0]
    return None


def local(path):
    """A skin's path on the box -> this checkout (vavoo_theme's own
    default base is wherever it is imported from)."""
    if path.startswith(PLUGIN_DIR):
        return path
    return path.replace(DEPLOYED, PLUGIN_DIR)


def classic_names(name):
    text = open(PLUGIN_DIR + "/skin/fhd/" + name).read()
    return set(re.findall(r'<widget name="([^"]+)"', text))


def built(kind, theme, large, width, **kw):
    return vt.BUILDERS[kind](theme, large, width, **kw)


# ---------------------------------------------------------------- 1
print("1. Every theme skin: valid, inside its box, pictures there and the size they say")
EXPECTED = {
    "list": classic_names("defaultListScreen.xml") | {"key_menu", "key_info"},
    "config": classic_names("vavoo_config.xml"),
    "pick": classic_names("vavoo_pick.xml"),
    "pin": classic_names("vavoo_pin.xml"),
    "guide": {"heading", "ruler", "grid", "details", "red", "green", "yellow", "blue"},
    "search": classic_names("vavoo_search.xml"),
    "splash": classic_names("Plgnstrt.xml"),
    "update": classic_names("UpdatePopup.xml"),
    "menu": {"title", "menulist"},
    "notify": {"notification_text"},
    "log": {"text", "key_red"},
    "player": {"logo", "number", "name", "now", "progress_track", "progress", "left", "next",
               "status", "key_options", "key_list", "key_red",
               "key_green", "key_yellow", "key_blue", "info_box", "stream_info"},
    "player_list": {"menulist", "guide"},
    "player_menu": {"menulist"},
}
problems = []
names_ok = True
count = 0
for theme in vt.MODERN_THEMES:
    for large in (True, False):
        for tag, width in vt.RESOLUTIONS:
            height = width * 9 // 16
            for kind in vt.BUILDERS:
                kw = {"title": "Vavoo Log"} if kind == "log" else {}
                text = built(kind, theme, large, width, **kw)
                count += 1
                try:
                    root = ET.fromstring(text)
                except Exception as e:
                    problems.append("%s/%s/%s: not XML (%s)" % (theme, kind, tag, e))
                    continue
                sx, sy = [int(v) for v in root.get("position").split(",")]
                sw, sh = [int(v) for v in root.get("size").split(",")]
                if sx < 0 or sy < 0 or sx + sw > width or sy + sh > height:
                    problems.append("%s/%s/%s: screen off the desktop" % (theme, kind, tag))
                names = set()
                for el in root:
                    if el.get("name"):
                        names.add(el.get("name"))
                    x, y = [int(v) for v in el.get("position").split(",")]
                    w, h = [int(v) for v in el.get("size").split(",")]
                    if x < 0 or y < 0 or x + w > sw or y + h > sh:
                        problems.append("%s/%s/%s: %s %s at %d,%d %dx%d outside %dx%d" % (
                            theme, kind, tag, el.tag, el.get("name") or el.get("pixmap", "")[-30:],
                            x, y, w, h, sw, sh))
                    for attr in ("pixmap", "selectionPixmap"):
                        path = el.get(attr)
                        if not path:
                            continue
                        if not path.startswith(DEPLOYED) and not path.startswith(PLUGIN_DIR):
                            problems.append("not a box path: " + path)
                            continue
                        real = local(path)
                        if not os.path.isfile(real):
                            problems.append("missing " + real)
                            continue
                        if real.endswith(".png") and attr == "pixmap" and el.tag == "ePixmap":
                            if png_size(real) != (w, h):
                                problems.append("%s: drawn %s, skin says %dx%d" % (
                                    real[-50:], png_size(real), w, h))
                if names != EXPECTED[kind] and not (kind == "list"):
                    names_ok = False
                    problems.append("%s/%s/%s: widgets %r" % (theme, kind, tag, sorted(names ^ EXPECTED[kind])))
                if kind == "list" and not names <= EXPECTED[kind]:
                    names_ok = False
                    problems.append("list widgets not owned: %r" % sorted(names - EXPECTED[kind]))
for p in problems[:12]:
    print("     " + p)
check(not problems, "%d skins (3 themes x 2 text sizes x 3 resolutions x %d screens) - %d problems"
      % (count, len(vt.BUILDERS), len(problems)))
check(names_ok, "each skin names only widgets its screen creates (Classic's set, + key_menu/key_info on the lists)")

# selection bars are exactly one row of their listbox
bad = []
for theme in vt.MODERN_THEMES:
    for tag, width in vt.RESOLUTIONS:
        for name, spec in vt.asset_specs(theme).items():
            if "row" not in spec:
                continue
            kind, large = spec["row"]
            m = vt.list_metrics(theme, large, width, kind)
            real = local(vt.asset_path(theme, name, width))
            if png_size(real)[1] != m["row_h"] or m["row_h"] * m["rows"] != m["list_h"]:
                bad.append((theme, tag, name, png_size(real), m["row_h"], m["rows"], m["list_h"]))
            if m["icon_y"] + m["icon_h"] > m["row_h"] or m["text_x"] + m["text_w"] > m["list_w"]:
                bad.append((theme, tag, name, "icon/text outside the row"))
check(not bad, "selection bars: one listbox row high, lists show whole rows, icon and text inside the row %r" % bad[:3])

# backgrounds: real JPEGs of the right size
bad = []
for theme in vt.MODERN_THEMES:
    for width, size in ((1280, (1280, 720)), (1920, (1920, 1080))):
        for plain in (False, True):
            path = vt.background_path(theme, width, plain, PLUGIN_DIR)
            if not os.path.isfile(path) or jpg_size(path) != size:
                bad.append(path)
check(not bad, "12 theme backgrounds, 1280x720 and 1920x1080 JPEGs %r" % bad)

# fonts and licences
fonts = vt.fonts_to_register(PLUGIN_DIR)
check(len(fonts) == 6 and all(os.path.isfile(p) for p, _n in fonts), "6 theme fonts present")
check(all(os.path.isfile(PLUGIN_DIR + "/fonts/%s-OFL.txt" % n) for n in ("Lexend", "Manrope", "Sora", "Oxanium")),
      "their OFL licence texts ship with them")

# make_theme_assets.py agrees: nothing missing, and a redraw is identical
import vavoo.make_theme_assets as mta           # noqa: E402
w, rows = mta.draw("halo", "key_red", 1920)
same = open(local(vt.asset_path("halo", "key_red", 1920)), "rb").read()
tmp = os.path.join(tempfile.mkdtemp(prefix="vavoo_theme_"), "redraw_key.png")
mta.write_png(tmp, w, rows)
check(open(tmp, "rb").read() == same, "make_theme_assets.py redraws a picture byte for byte")
os.unlink(tmp)
check(vt.e2_color("#D91A0C2C") == "#261a0c2c" and vt.e2_color("#8b3fd9") == "#8b3fd9",
      "Android opacity -> Enigma2 transparency")

# ---------------------------------------------------------------- 2
print("2. plugin.py chooses the skin, and falls back to Classic")


class V(object):
    def __init__(self, value):
        self.value = value


plugin.cfg.theme = V("prism")
plugin.cfg.text_size = V("large")
plugin.cfg.clock_format = V("24")
plugin.cfg.show_counts = V(True)
plugin.cfg.back = V("oktus")
plugin._theme_skin_cache.clear()
check(plugin.THEME_WIDTH in (1280, 1920, 2560), "THEME_WIDTH is one of the three drawn sizes")
text, themed = plugin.load_screen_skin("list", "defaultListScreen.xml", cvs=True, clock_24=True)
check(themed and 'name="key_menu"' in text and "themes/prism" in text, "Prism: the built list skin")
check(plugin.theme_active(), "theme_active() with all files present")
plugin.cfg.theme = V("classic")
text, themed = plugin.load_screen_skin("list", "defaultListScreen.xml", cvs=True, clock_24=True)
check(not themed and "images" in text and "key_menu" not in text, "Classic: the XML file, as before")
check(plugin.build_theme_skin("menu") is None and not plugin.theme_active(), "Classic: no theme skin at all")
plugin.cfg.theme = V("orbit")
real_isfile = plugin.isfile
plugin.isfile = lambda p: False if p.endswith("Oxanium-Regular.ttf") else real_isfile(p)
plugin._theme_skin_cache.clear()
text, themed = plugin.load_screen_skin("search", "vavoo_search.xml", cvs=True, background=False)
check(not themed and "VavooSearch" in text, "a theme font missing: Classic instead")
check(plugin.build_theme_skin("splash") is None, "...for every screen (all or nothing)")
plugin.isfile = lambda p: False if "/themes/halo/" in p and p.endswith("frame.png") else real_isfile(p)
plugin.cfg.theme = V("halo")
plugin._theme_skin_cache.clear()
check(plugin.build_theme_skin("list") is None and plugin.build_theme_skin("config") is None,
      "a picture missing: no theme")
plugin.isfile = real_isfile
plugin._theme_skin_cache.clear()
real_builder = vt.BUILDERS["list"]
vt.BUILDERS["list"] = lambda *a, **k: (_ for _ in ()).throw(ValueError("broken"))
check(plugin.build_theme_skin("list") is None, "a builder that raises: None (Classic), not a crash")
vt.BUILDERS["list"] = real_builder
plugin._theme_skin_cache.clear()
plugin.cfg.theme = V("prism")
check(plugin.build_theme_skin("list", clock_24=False) != plugin.build_theme_skin("list", clock_24=True),
      "the clock setting is part of the skin")
plugin.cfg.theme = V("nonsense")
check(plugin.current_theme() == "prism", "an unknown stored theme is read as Prism")
plugin.cfg.theme = V("prism")

# ---------------------------------------------------------------- 3
print("3. Keys, MENU and the status lines")


class FakeLabel(object):
    def __init__(self, text=""):
        self.text = text

    def setText(self, text):
        self.text = text

    def getText(self):
        return self.text


class FakeList(object):
    def __init__(self, *a, **k):
        self.rows = []
        self.index = 0
        self.onSelectionChanged = []
        self.l = self

    def setList(self, rows):
        self.rows = rows

    def getCurrent(self):
        return self.rows[self.index] if self.rows else None

    def getSelectedIndex(self):
        return self.index

    def getCurrentSelection(self):
        return self.getCurrent()

    def moveToIndex(self, i):
        self.index = i
        for fn in self.onSelectionChanged:
            fn()


class FakeActionMap(object):
    def __init__(self, contexts, actions, prio=0):
        self.contexts, self.actions = contexts, actions


class FakeTimer(object):
    def __init__(self):
        self.callback = []

    def start(self, *a):
        pass

    def stop(self):
        pass

    def isActive(self):
        return False


plugin.Label = FakeLabel
plugin.m2list = FakeList
plugin.ActionMap = FakeActionMap
plugin.eTimer = FakeTimer
plugin._ = lambda s: s
notes = []
plugin.quick_notify = lambda msg, sec=3: notes.append(msg)
plugin.NOTIFICATION_AVAILABLE = True


def bare(cls, themed=True):
    obj = cls.__new__(cls)
    obj.widgets = {}
    obj._closed = False
    obj.execing = True
    obj.onExecBegin = []
    obj.onClose = []
    obj._themed = themed
    obj._favourite_keys = set()
    obj._proxy_down = False
    return obj


for cls in (plugin.vavoo, plugin.VavooFavourites, plugin.MainVavoo):
    cls.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
    cls.__getitem__ = lambda self, k: self.widgets[k]

list_names = EXPECTED["list"]
mv = bare(plugin.MainVavoo)
mv.countries, mv._channel_total, mv._reloading, mv._search_loading = [], None, False, False
mv._initialize_labels()
mv._initialize_actions()
check(list_names <= set(mv.widgets), "MainVavoo owns every widget of the theme list skin: %r" % sorted(list_names - set(mv.widgets)))
check([mv.widgets[k].text for k in ("red", "green", "yellow", "blue")] == ["Exit", "Favourites", "Search", "Reload List"],
      "main keys as in the app: Exit / Favourites / Search / Reload List")
a = mv.widgets["actions"].actions
check(a["green"] == mv.open_favourites and a["yellow"] == mv.search_all and a["blue"] == mv.reload_list
      and a["menu"] == mv.open_menu and a["info"] == mv.info_toast and a["red"] == mv.closex,
      "...and what they do; MENU = action menu, INFO = the app's info")
check(a["epg"] == mv.favourites_guide and "text" not in a and mv.widgets["list_keys"].actions["search"] == mv.search_all,
      "EPG: the favourites' guide; TEXT: search (the EPG import and the token are in MENU)")

menus = []
plugin.open_action_menu = lambda session, title, entries, on_choice: menus.append((title, entries, on_choice))
mv.session = None
mv.open_menu()
title, entries, on_choice = menus[-1]
keys = [k for _l, k in entries]
check(set(keys) == {"settings", "reload_bouquets", "remove_all", "epg_import", "fix_cache",
                    "refresh_token", "log", "about"},
      "main MENU: settings + every Enigma2 tool that left the colour keys %r" % keys)
called = []
mv.goConfig = lambda: called.append("settings")
mv.msgdeleteBouquets = lambda: called.append("remove_all")
mv.open_menu()
menus[-1][2]("remove_all")
menus[-1][2]("settings")
check(called == ["remove_all", "settings"], "picking an entry runs it")

v = bare(plugin.vavoo)
v._initialize_labels()
v._initialize_actions()
check(list_names <= set(v.widgets), "channel list owns every widget of the theme list skin")
check([v.widgets[k].text for k in ("red", "green", "yellow", "blue")] == ["Back", "Add Fav", "Search", "Full Screen"],
      "channel keys as in the app: Back / Add Fav / Search / Full Screen")
a = v.widgets["actions"].actions
check(a["green"] == v.toggle_favourite and a["blue"] == v.full_screen and a["yellow"] == v.search_vavoo
      and a["menu"] == v.open_menu and a["info"] == v.info_key and a["epg"] == v.info_key,
      "...and what they do (INFO / EPG: the guide)")
v.country_name = v.name = "Portugal"
v.category, v._preloaded, v.showing_categories, v.category_keys = None, None, False, []
v.url = None
v._epg_country_code = ""
v._channel_entries = []
v._preload_channel_picons = lambda: None
v._epg_panel_changed = lambda: None
URL1 = "http://127.0.0.1:4323/vavoo?channel=sic"
v._build_channel_list([{"name": "SIC", "url": URL1, "logo": ""},
                       {"name": "RTP 1", "url": "u2", "logo": ""}])
check(v.widgets["proxy_status"].text == "Portugal · 1/2" and v.widgets["green"].text == "Add Fav",
      "status line 'Portugal · 1/2', GREEN = Add Fav: %r" % v.widgets["proxy_status"].text)
toggled = []


def fake_toggle(name, url, **kw):
    toggled.append((name, url))
    return True


plugin.vUtils.toggle_favourite = fake_toggle
v.toggle_favourite()
check(v.widgets["proxy_status"].text == "Portugal · 1/2  ★" and v.widgets["green"].text == "Remove Fav",
      "after GREEN: star on the line, GREEN = Remove Fav")
v.widgets["menulist"].moveToIndex(1)
v._update_status_line()
check(v.widgets["proxy_status"].text == "Portugal · 2/2" and v.widgets["green"].text == "Add Fav",
      "another row: its own state")
v._proxy_down = True
v._update_status_line()
check("Offline" in v.widgets["proxy_status"].text, "proxy gone: the line says so")
v._proxy_down = False
plugin.is_bouquet_exported = lambda name: True
v.session = None
v.open_menu()
keys = [k for _l, k in menus[-1][1]]
labels = [l for l, _k in menus[-1][1]]
check(keys == ["settings", "bouquet", "reload_bouquets", "log"] and "Remove this country's bouquet" in labels,
      "channel MENU: settings, export/remove this country's bouquet, reload bouquets, log")
plugin.is_bouquet_exported = lambda name: False
v.open_menu()
check("Export this country as a bouquet" in [l for l, _k in menus[-1][1]], "...'Export' when it is not exported")

fv = bare(plugin.VavooFavourites)
plugin.vUtils.load_favourites = lambda: []
fv.cat_list = []
fv.widgets = {}
fv.session = None
plugin.Screen.__init__ = lambda self, session: None
plugin.init_notification_system = lambda session: None
plugin.VavooFavourites.__init__(fv, None)
check(list_names <= set(fv.widgets), "Favourites owns every widget of the theme list skin")
check(fv.widgets["red"].text == "Back" and fv.widgets["green"].text == "Remove Fav", "Favourites keys")
fa = fv.widgets["actions"].actions
check(fa["menu"] == fv.open_menu and fa["info"] == fv.info_key and fa["epg"] == fv.info_key,
      "Favourites: MENU, INFO / EPG (the guide)")
plugin.vUtils.load_favourites = lambda: [
    {"name": "SIC", "url": URL1, "country_name": "Portugal", "country_code": "pt"},
    {"name": "TF1", "url": "u3", "country_name": "France", "country_code": "fr"}]
fv._epg_panel_changed = lambda: None
fv._build_list()
check(fv.widgets["proxy_status"].text == "★ Favourites · 1/2" and fv.widgets["name"].text == "SIC",
      "Favourites status line and name")

# ---------------------------------------------------------------- 4
print("4. The main list: favourites row, counts, highlight kept")
mv.cat_list = []
mv.session = None
mv._update_proxy_status_display = lambda: None
mv._on_countries_response('["Portugal", "France"]', None, {"portugal": 174, "france": 90}, 3)
rows = mv.widgets["menulist"].rows
texts = [r[-1].text if hasattr(r[-1], "text") else None for r in rows]
check([r[0] for r in rows] == [("★ Favourites", plugin.FAVOURITES_ROW), ("France", "France"), ("Portugal", "Portugal")],
      "rows: (name, link) - Favourites first, then the countries")
check(mv._channel_total == 264 and mv.countries == ["France", "Portugal"], "total and countries kept for INFO / search")
mv.widgets["menulist"].moveToIndex(2)
plugin.cfg.show_counts = V(False)
mv._on_countries_response('["Portugal", "France"]', None, {"portugal": 174, "france": 90}, 0)
check(mv.widgets["menulist"].getCurrent()[0] == ("Portugal", "Portugal") and len(mv.widgets["menulist"].rows) == 2,
      "no favourites: no row; the highlight stays on Portugal")
plugin.cfg.show_counts = V(True)
opened = []
mv.open_favourites = lambda: opened.append("fav")
mv._on_countries_response('["Portugal"]', None, {}, 2)
mv.widgets["menulist"].moveToIndex(0)
mv.ok()
check(opened == ["fav"], "OK on the Favourites row opens the Favourites")
del notes[:]
mv.info_toast()
check(notes and "V." in notes[-1] and "1 countries" in notes[-1], "INFO: version and counts %r" % notes[-1:])

# The rows' text with the counts: built with show_list(display=...)
captured = []
real_show_list = plugin.show_list
plugin.show_list = lambda name, link, **kw: (captured.append((name, kw.get("display"))), [(name, link)])[1]
mv._on_countries_response('["Portugal"]', None, {"portugal": 174}, 3)
check(("★ Favourites", "★ Favourites (3)") in captured and ("Portugal", "Portugal (174)") in captured,
      "counts on the rows: 'Portugal (174)', '★ Favourites (3)' %r" % captured)
plugin.show_list = real_show_list

# ---------------------------------------------------------------- 5
print("5. Now / Next lines, clock, search, counts, notifications, updates")
T = real_time.mktime((2026, 11, 15, 20, 50, 0, 0, 0, -1))
plugin.time = types.SimpleNamespace(localtime=real_time.localtime, strftime=real_time.strftime,
                                    time=lambda: T)
real_lt = real_time.localtime
plugin.time.localtime = lambda t=None: real_lt(T if t is None else t)
check(plugin.programme_time(T) == "20:50", "24 h: 20:50")
plugin.cfg.clock_format = V("12")
check(plugin.programme_time(T) == "8:50 PM", "12 h: 8:50 PM")
plugin.cfg.clock_format = V("24")
check(re.match(r"^[A-Za-z]+ 09:00$", plugin.programme_time(T + 12 * 3600 + 10 * 60)), "tomorrow: weekday in front")
host = bare(plugin.vavoo)
for w in plugin.EPG_PANEL_WIDGETS:
    host.widgets[w] = FakeLabel()
host._epg_panel_draw(("ok", (T, T + 3600, "Jornal da Noite"), (T + 3600, T + 7200, "Telejornal")))
check(host.widgets["epg_now_title"].text == u"▶ 20:50  Jornal da Noite"
      and host.widgets["epg_next_title"].text == u"» 21:50  Telejornal"
      and host.widgets["epg_now_time"].text == "", "theme: the app's two lines %r" % host.widgets["epg_now_title"].text)
host._themed = False
host._epg_panel_draw(("ok", (T, T + 3600, "Jornal da Noite"), None))
check(host.widgets["epg_now_title"].text == "Jornal da Noite" and host.widgets["epg_now_time"].text.startswith("Now"),
      "Classic: unchanged")

s = plugin.VavooSearch.__new__(plugin.VavooSearch)
s.widgets = {}
plugin.VavooSearch.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
plugin.VavooSearch.__getitem__ = lambda self, k: self.widgets[k]
plugin.NumericalTextInput = lambda **k: types.SimpleNamespace(nextKey=lambda: None)
plugin.VavooSearch.__init__(s, None, None, ["SIC###u1###Portugal", "TF1###u2###France"], scope="all channels")
check(s.widgets["search_label"].text == "Search all channels", "search title says what is searched")
closed = []
s.close = lambda *a: closed.append(a)
s.search_text = "tf"
s.updateFilteredList()
s.onOk()
check(closed and closed[-1] == (("TF1", "u2", "France", [("TF1", "u2", "France")], 0),),
      "a result hands back its country, the results and its place %r" % closed[-1:])
shown = []
plugin.show_list = lambda name, link, **kw: (shown.append(kw.get("display")), [(name, link)])[1]
s.search_text = ""
s.updateFilteredList()
check(shown == ["SIC  · Portugal", "TF1  · France"], "rows show 'Channel  · Country' %r" % shown)
plugin.show_list = real_show_list

pins = []
plugin._require_parental_pin = lambda session, screen, country, fn, **kw: pins.append(country)
mv._on_search_all_result(("TF1", "u2", "France"))
check(pins == ["France"], "opening a result from all countries goes through the PIN check of its country")


class FakeProxy(object):
    pass


fp = FakeProxy()
fp.channels_by_country = {"portugal": [
    {"id": "1", "name": "SIC .b"}, {"id": "2", "name": "SIC .c"}, {"id": "3", "name": "RTP 1"},
    {"id": "4", "name": "!!!"}]}
counts = vp.VavooProxy.country_counts(fp)
check(counts == {"portugal": 3}, "country_counts(): sources of one channel counted once %r" % counts)
check(vp.VavooProxy.country_counts(fp) is counts, "...worked out once per catalog")

ns.set_notify_skin("<screen name=\"x\"/>")
check(ns.current_notify_skin() == "<screen name=\"x\"/>", "notifications take the theme's skin")
ns.set_notify_skin(None)
check("ff6699" in ns.current_notify_skin(), "...or their own bar")

init = io.open(PLUGIN_DIR + "/__init__.py", encoding="utf-8").read()
check("INSTALLER_URL = UPDATE_HOST" in init and "OwnerPlugins/vavoo/main" in init, "version check reads OwnerPlugins/vavoo main")
check("HOST_MAIN = 'https://raw.githubusercontent.com/Belfagor2005/vavoo/main'" in init, "guides / channel DB source unchanged")
inst = io.open(REPO + "/installer.sh", encoding="utf-8").read()
check("github.com/OwnerPlugins/vavoo/archive/refs/heads/main.tar.gz" in inst and "Belfagor2005" not in inst.split("DOWNLOAD_URL=")[1][:80],
      "installer downloads OwnerPlugins/vavoo")
bb = io.open(REPO + "/enigma2-plugin-extensions-vavoo.bb", encoding="utf-8").read()
check("git://github.com/OwnerPlugins/vavoo.git" in bb, "recipe builds from OwnerPlugins/vavoo")

src = e2env.plugin_source()
tsrc = io.open(PLUGIN_DIR + "/vavoo_theme.py", encoding="utf-8").read()
check(not re.search(r"""\bf["']""", tsrc) and "import enigma" not in tsrc and "from enigma" not in tsrc,
      "vavoo_theme.py: no f-strings, no Enigma2 imports")
for word in ('_("Theme")', '_("Text Size")', '_("Show Counts")', '_("Clock Format")', '_("Favourites")',
             '_("Reload List")', '_("Add Fav")', '_("Remove Fav")', '_("Full Screen")', '_("Settings")'):
    check(word in src or word.replace('"', "'") in src, "translatable: " + word)

print("\n%d checks, %d failed" % (CHECKS, FAILS))
e2env.exit_now(1 if FAILS else 0)
