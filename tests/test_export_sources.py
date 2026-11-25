# -*- coding: utf-8 -*-
"""Exported bouquets (and the .m3u files) carry every source of a
channel, under its catalog name ("SIC .b", "SIC .c", "SIC .d"), whatever
"Group Sources" says for the plugin's own list: a bouquet has no source
menu. They asked /channels grouped, one "grp:" row per channel, and the
.b / .c / .d were not there."""
from __future__ import print_function
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
plugin = harness.plugin
vu = plugin.vUtils
vp = plugin.vavoo_proxy
bm = sys.modules["vavoo.bouquet_manager"]
ca = sys.modules["vavoo.channel_alias"]
try:
    from urllib.parse import urlparse, parse_qs
except ImportError:
    from urlparse import urlparse, parse_qs

TMP = tempfile.mkdtemp(prefix="vavoo_sources_")
vu.UNMATCHED_FILE = os.path.join(TMP, "unmatched.json")
vu.CACHE_FILE = os.path.join(TMP, "cache.json")
vu._unmatched_cache_data = None

CATALOG = [
    ("s1", u"SIC .b"), ("s2", u"SIC .c"), ("s3", u"SIC .d"),
    ("r1", u"RTP 1"), ("x2", u"RAI 1 .2")]
p = vp.VavooProxy()
p.get_local_ip = lambda: "127.0.0.1"
p.channels_by_country = {"portugal": [
    {"id": cid, "name": name, "url": u"http://x/" + cid, "logo": u"",
     "country": u"Portugal", "group": u"Portugal", "epg_id": u""}
    for cid, name in CATALOG]}
check(len(p.channel_rows("Portugal", True)) == 3,
      "the plugin's list (Group Sources on): SIC in one row - 3 rows")

asked = []


def fake_get_url(url, timeout=None, **kwargs):
    asked.append(url)
    query = parse_qs(urlparse(url).query)
    grouped = query.get("grouped", ["1"])[0] != "0"
    return json.dumps(p.channel_rows(query["country"][0], grouped))


print("== the bouquet export asks for every source")
real_bm_get = bm.getUrl
bm.getUrl = fake_get_url
rows = bm.get_channels_from_proxy("Portugal", "flat")
check(asked and "grouped=0" in asked[-1],
      "/channels asked with grouped=0: %r" % asked[-1:])
names = sorted(r["name"] for r in rows)
check(names == sorted(n for _i, n in CATALOG),
      "every source, under its catalog name: %r" % names)

print("== the bouquet file: one entry per source")
real_running, real_ready = bm.is_proxy_running, bm.is_proxy_ready
real_enigma, real_add = bm.ENIGMA_PATH, bm._add_to_main_bouquet
bm.is_proxy_running = lambda *a, **k: True
bm.is_proxy_ready = lambda *a, **k: True
bm.ENIGMA_PATH = TMP
bm._add_to_main_bouquet = lambda *a, **k: None
try:
    count, filename, channels, _cc = bm.create_fallback_bouquet_sync(
        "4097", "Portugal", "flat", "bottom")
    text = open(os.path.join(TMP, filename), "rb").read().decode(
        "utf-8") if filename else u""
    services = [line for line in text.splitlines()
                if line.startswith("#SERVICE")]
    descriptions = [line[len("#DESCRIPTION "):] for line in text.splitlines()
                    if line.startswith("#DESCRIPTION")]
    check(count == 5 and len(services) == 5,
          "5 #SERVICE lines (%d, %d)" % (count, len(services)))
    for cid, name in CATALOG:
        check(any(s.endswith("vavoo?channel=" + cid) for s in services),
              "%s has its own entry (channel=%s)" % (name, cid))
    check(set(["SIC .b", "SIC .c", "SIC .d"]) <= set(descriptions),
          "named SIC .b / .c / .d: %r" % descriptions)
    check(not any("grp%3a" in s for s in services), "no grouped row")
    check(len(set(s.split("http")[0] for s in services)) == 5,
          "each its own service reference")
    check(text.splitlines()[0] == u"#NAME Vavoo ★ Portugal" and
          filename == "userbouquet.vavoo_portugal.tv",
          "named 'Vavoo ★ Portugal' (as the favourites), the file as "
          "before: %r" % text.splitlines()[:1])

    print("== the scheduled update's bouquet: the same name")

    class NoMatch(object):
        def find_match(self, *a, **k):
            return None, None, None

    for name, wanted, wanted_file in (
            (u"Portugal", u"#NAME Vavoo ★ Portugal",
             "userbouquet.vavoo_portugal.tv"),
            (u"Italy ➾ Sport", u"#NAME Vavoo ★ Italy ➾ Sport",
             "userbouquet.vavoo_italy_sport.tv")):
        result = bm.create_bouquet_file(
            name, rows, "4097", "hierarchical", "bottom", NoMatch(), "")
        first = open(os.path.join(TMP, result[1]), "rb").read().decode(
            "utf-8").splitlines()[0] if result[1] else u""
        check(first == wanted and result[1] == wanted_file,
              "%s: %r, %s" % (name, first, result[1]))
    check(bm.bouquet_title(u"Vavoo ★ Italy") == u"Vavoo ★ Italy",
          "a name with the prefix gets no second one")

    print("== the bouquets exported before get the name")

    def write(fname, text):
        with open(os.path.join(TMP, fname), "wb") as f:
            f.write(text.encode("utf-8"))

    def read(fname):
        return open(os.path.join(TMP, fname), "rb").read().decode("utf-8")

    old_lines = u"#NAME Portugal\n#SERVICE 4097:0:1:a:b:0:0:0:0:0:x\n" \
        u"#DESCRIPTION SIC\n"
    write("userbouquet.vavoo_portugal.tv", old_lines)
    write("userbouquet.vavoo_italy.tv", u"#NAME Vavoo ★ Italy\n")
    write(bm.FAVOURITES_BOUQUET, u"#NAME Vavoo ★ Favoritos\n")
    write("userbouquet.favourites.tv", u"#NAME Favourites (TV)\n")
    write("userbouquet.vavoo_italy_sport.tv", u"#NAME Italy ➾ Sport\n")
    check(bm.retitle_vavoo_bouquets() == 2, "two renamed")
    check(read("userbouquet.vavoo_portugal.tv") ==
          old_lines.replace(u"#NAME Portugal", u"#NAME Vavoo ★ Portugal"),
          "Portugal: 'Vavoo ★ Portugal', its channels as they were")
    check(read("userbouquet.vavoo_italy_sport.tv") ==
          u"#NAME Vavoo ★ Italy ➾ Sport\n", "a category too")
    check(read("userbouquet.vavoo_italy.tv") == u"#NAME Vavoo ★ Italy\n" and
          read(bm.FAVOURITES_BOUQUET) == u"#NAME Vavoo ★ Favoritos\n" and
          read("userbouquet.favourites.tv") == u"#NAME Favourites (TV)\n",
          "already named, the favourites' and Enigma2's own: untouched")
    check(bm.retitle_vavoo_bouquets() == 0, "again: nothing to do")
    check(plugin.retitle_bouquets_in_background and
          "retitle_bouquets_in_background()" in
          harness.e2env.source_of("main"),
          "main() does it each time the plugin opens")
finally:
    bm.is_proxy_running, bm.is_proxy_ready = real_running, real_ready
    bm.ENIGMA_PATH, bm._add_to_main_bouquet = real_enigma, real_add
    bm.getUrl = real_bm_get

print("== the .m3u files too")
ui_settings = sys.modules["vavoo.ui_settings"]
real_set_get = ui_settings.getUrl
ui_settings.getUrl = fake_get_url
try:
    screen = plugin.vavoo_config.__new__(plugin.vavoo_config)
    rows = screen.get_channels_for_country("Portugal")
    check("grouped=0" in asked[-1] and len(rows) == 5,
          "M3U export: grouped=0, 5 entries (%r)" % asked[-1:])
finally:
    ui_settings.getUrl = real_set_get

print("== the alias table knows every source tag")
base = ca.normalize_channel_name("RAI 1")
for name in ("RAI 1 .b", "RAI 1 .d", "RAI 1 .2", "RAI 1.b", "rai 1 .D"):
    check(ca.normalize_channel_name(name) == base,
          "%r -> %r" % (name, ca.normalize_channel_name(name)))
check(ca.normalize_channel_name("DMAX HD") == "DMAX HD" and
      ca.normalize_channel_name("DMAX HD .d") == "DMAX HD",
      "a dedicated HD entry is kept (DMAX HD)")
check(ca.normalize_channel_name("RTL 102.5") == "RTL 102.5",
      "a dot inside the name stays (RTL 102.5)")

print("== each source finds the channel's guide")
clean = vu.clean_name_for_similarity("SIC")
real_index = vu._get_epg_feed_index
real_curated = vu._load_curated_channel_db
vu._get_epg_feed_index = lambda cc: (
    set(["SIC.pt"]), {clean: ("SIC.pt", vu._tokenize_for_compat(clean))})
vu._load_curated_channel_db = lambda cc: {}
m = vu.VavooEPGMatcher.__new__(vu.VavooEPGMatcher)
m.similarity_threshold = 0.75
m._cache_lock = threading.RLock()
m.new_matches = {}
m.normalized_index = {}
m.alias_map = {}
m.cache = {}
try:
    for cid, name in CATALOG[:3]:
        feed_id, sref, _src = m.find_match(name, "pt", channel_id=cid)
        check(feed_id == "SIC.pt" and sref, "%s -> %r" % (name, feed_id))
finally:
    vu._get_epg_feed_index = real_index
    vu._load_curated_channel_db = real_curated
finish()
