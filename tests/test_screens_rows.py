# -*- coding: utf-8 -*-
"""The lists with rows in them - channels, favourites (and a folder),
recently watched, the guide, recordings and timers, the search -
accented names, every theme and Classic, on whichever Python runs this
(run.sh: 3, run2.sh: 2.7)."""
from __future__ import print_function
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, V, run_layout   # noqa: E402
plugin = harness.plugin
store = harness.store
import vavoo.vavoo_record as vr                 # noqa: E402

class FakeGuideList(harness.FakeList):
    def __init__(self, item_height=40, font_name="", font_size=20):
        harness.FakeList.__init__(self)
        self.item_height = item_height


plugin.GuideList = FakeGuideList
plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True
plugin.cfg.subcategories = V(True)
plugin.cfg.group_sources = V(True)
plugin.cfg.list_epg = V(False)
plugin.cfg.preview_window = V(False)
plugin.vUtils.RECENT_FILE = store.recent_file()
U = u"Rai Südtirol"
CHANNELS = [{"name": U, "url": u"http://127.0.0.1:4323/vavoo?channel=a", "logo": "", "category": u"Generalisti"},
            {"name": u"TF1 Séries ★", "url": u"http://127.0.0.1:4323/vavoo?channel=b", "logo": "",
             "category": u"Sport"},
            {"name": u"Canale 5", "url": u"http://127.0.0.1:4323/vavoo?channel=c", "logo": ""}] + \
           [{"name": u"Ch %d" % i, "url": u"http://127.0.0.1:4323/vavoo?channel=x%d" % i, "logo": ""}
            for i in range(12)]
GUIDE = [dict(c, country_name=u"Italia", country_code="it", epg_id="x.it") for c in CHANNELS[:5]]
REC = os.path.join(harness.DATA, "movie")
if not os.path.isdir(REC):
    os.makedirs(REC)
plugin.cfg.record_path = V(REC)
vr.on_disk = lambda p: True

for c in CHANNELS[:3]:
    store.add_favourite(c["name"], c["url"], u"Italia", "it")
store.set_folder(CHANNELS[0]["url"], u"Desporto á")
plugin.vUtils.add_recent(U, CHANNELS[0]["url"], u"Italia", "it")
now = int(time.time())
store.add_timer(store.KIND_RECORD, CHANNELS[0]["url"], U, u"Telegiornale à sera", now + 3600, now + 7200,
                u"Italia", "it")
p = vr.new_path(REC, U, u"Film é", now - 3600)
with open(vr._native(p), "wb") as f:
    f.write(b"\x47" + b"\x00" * 187)
vr.write_info(p, {"format": vr.INFO_FORMAT, "name": U, "title": u"Film é", "start": now - 3600,
                  "duration": 1200, "country": u"Italia"})


def channel_list(s, subcategories=True):
    plugin.cfg.subcategories = V(subcategories)
    v = make(plugin.vavoo, s, u"Italia", None)
    v._preload_channel_picons = lambda: None
    v._build_channel_list(CHANNELS)
    return v


def category(s):
    plugin.cfg.subcategories = V(True)
    v = make(plugin.vavoo, s, u"Italia", None, None, category=u"Sport", channels=CHANNELS)
    v._preload_channel_picons = lambda: None
    run_layout(v)
    v._build_channel_list(CHANNELS)
    return v


def favourites(s, *a):
    f = make(plugin.VavooFavourites, s, *a)
    run_layout(f)
    f._build_list()
    return f


def search(s):
    items = [u"%s###%s###Italia" % (c["name"], c["url"]) for c in CHANNELS]
    se = make(plugin.VavooSearch, s, None, items, scope="all channels")
    run_layout(se)
    se.search_text = "sud"
    se.updateFilteredList()
    se.keyNumber(7)
    se.deleteChar()
    return se


CASES = [
    ("channel list (categories)", channel_list),
    ("channel list (numbered rows)", lambda s: channel_list(s, False)),
    ("a category", category),
    ("Favourites", lambda s: favourites(s)),
    ("a folder", lambda s: favourites(s, "favourites", u"Desporto á")),
    ("Recently watched", lambda s: favourites(s, "recent")),
    ("guide", lambda s: (lambda g: (run_layout(g), g)[1])(make(plugin.VavooGuide, s, GUIDE, 0, u"Italia"))),
    ("Recordings", lambda s: (lambda r: (run_layout(r), r)[1])(make(plugin.VavooRecordings, s))),
    ("player channel list", lambda s: (lambda r: (run_layout(r), r)[1])(make(
        plugin.VavooPlayerList, s, [(c["name"], c["url"]) for c in CHANNELS], 1, ["it"] * len(CHANNELS),
        [""] * len(CHANNELS), [u"Italia"] * len(CHANNELS)))),
    ("search", search),
]

print("Python", sys.version.split()[0])
for theme in ("classic", "prism", "halo", "orbit"):
    for folder, width in (("hd", 1280), ("fhd", 1920), ("wqhd", 2560)):
        plugin.screen_width = width
        plugin.THEME_WIDTH = width
        plugin.skin_path = os.path.join(harness.PLUGIN_DIR, "skin", folder)
        plugin.cfg.theme = V(theme)
        plugin._theme_skin_cache.clear()
        plugin._icon_cache.clear()
        for title, build in CASES:
            try:
                scr = build(Session())
                rows = scr.widgets.get("grid") or scr.widgets.get("channel_list") or scr.widgets.get("menulist")
                n = len(getattr(rows, "rows", []) or [])
                problem = None
            except Exception as e:
                n, problem = 0, "%s: %s\n%s" % (e.__class__.__name__, e, traceback.format_exc(limit=6))
            check(problem is None and n > 0, "%s %s: %s, %d rows%s" % (theme, folder, title, n,
                                                              "" if problem is None else "\n" + problem))
finish()
