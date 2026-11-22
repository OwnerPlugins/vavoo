# -*- coding: utf-8 -*-
"""Instant start: the proxy keeps the last catalog that loaded
(vavoo_catalog.json.gz), starts with it at once and fetches the new one
behind it; "Reload List" waits for a new one; the main list follows
when it comes in."""
from __future__ import print_function
import gzip
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session  # noqa: E402
plugin = harness.plugin
vp = plugin.vavoo_proxy
PATH = vp.CATALOG_FILE
# (the faked Enigma2 config has no real catalog_source setting)
vp.catalog_setting = lambda: "auto"
check(
    PATH.startswith(
        harness.DATA),
    "the tests' catalog file is in the temp folder: %s" %
    PATH)


def channels(n, country=u"Italy", start=0):
    return [{"id": u"%d" % (start + i),
             "name": u"Canale %d" % (start + i),
             "url": u"http://x/%d" % (start + i),
             "country": country,
             "logo": u"",
             "group": country + u" ➾ Generale",
             "epg_id": u""} for i in range(n)]


def write(doc, path=PATH):
    with gzip.open(path, "wb") as f:
        f.write(json.dumps(doc).encode("utf-8"))
    vp._catalog_digest[0] = None


print("== save and load")
vp._catalog_digest[0] = None
items = channels(150) + channels(20, u"France", 1000)
check(vp.save_catalog(items, "geil", "auto")
      is True and os.path.exists(PATH), "saved")
mtime = os.path.getmtime(PATH)
got = vp.load_saved_catalog("auto")
check(
    got is not None and got[1] == "geil" and len(
        got[0]) == 170 and got[0][0]["name"] == u"Canale 0",
    "read back: 170 channels from geil")
time.sleep(0.05)
check(vp.save_catalog(items, "geil", "auto") is False and os.path.getmtime(
    PATH) == mtime, "the same catalog again: not written (the flash)")
vp._catalog_digest[0] = None
check(vp.save_catalog(list(items), "geil", "auto") is False,
      "...also after a restart (the file's own hash)")
check(
    vp.save_catalog(
        items +
        channels(
            1,
            u"Spain",
            5000),
        "geil",
        "auto") is True,
    "a changed catalog: written")
check(not os.path.exists(PATH + ".tmp"), "no temp file left")
check(vp.load_saved_catalog("vavoo") is None,
      "saved for another catalog_source setting: not used")
saved = json.loads(gzip.open(PATH).read().decode("utf-8"))["saved"]
check(
    vp.load_saved_catalog(
        "auto",
        now=saved +
        4 *
        86400) is None,
    "4 days old: not used")
check(
    vp.load_saved_catalog(
        "auto",
        now=saved +
        2 *
        86400) is not None,
    "2 days old: used")
check(vp.load_saved_catalog("auto", now=86400) is not None,
      "the box's clock not set yet (1970): used")

print("== broken files")
for what, data in (("not gzip", b"hello"), ("gzip, not JSON", None)):
    if data is None:
        with gzip.open(PATH, "wb") as f:
            f.write(b"{not json")
    else:
        open(PATH, "wb").write(data)
    check(
        vp.load_saved_catalog("auto") is None,
        "%s: not used, no error" %
        what)
base = {
    "format": "vavoo_catalog",
    "version": 1,
    "setting": "auto",
    "source": "geil",
    "saved": int(
        time.time()),
    "hash": "x"}
write(dict(base, format="other", channels=items))
check(vp.load_saved_catalog("auto") is None, "another format: not used")
write(dict(base, source="nonsense", channels=items))
check(vp.load_saved_catalog("auto") is None, "an unknown source: not used")
write(dict(base, saved="yesterday", channels=items))
check(vp.load_saved_catalog("auto") is None,
      "a time that is not a number: not used")
bad = items[:120] + [None,
                     5,
                     {"id": u"x"},
                     {"id": [1],
                         "name": u"a",
                         "url": u"u",
                         "country": u"c"},
                     {"id": 7,
                         "name": u"Seven",
                         "url": u"http://x/7b",
                         "country": u"Italy"}]
write(dict(base, channels=bad))
got = vp.load_saved_catalog("auto")
check(got is not None and len(got[0]) == 121 and got[0][-1]["id"] == u"7" and got[0][-1]["logo"] == u"",
      "broken entries dropped, a number id made text, missing fields empty (%s)" % (got and len(got[0])))
write(dict(base, channels=items[:50]))
check(vp.load_saved_catalog("auto") is None, "almost empty (50): not used")
os.remove(PATH)
check(vp.load_saved_catalog("auto") is None, "no file: none")

print("== initialize_proxy(): the saved catalog first, the network behind it")
downloads = []


def fake_download(setting, result=None):
    downloads.append(setting)
    return result if result is not None else (
        channels(200, u"Portugal", 9000), "geil")


vp._catalog_digest[0] = None
vp.save_catalog(items, "geil", "auto")
p = vp.VavooProxy()
p._download_catalog = fake_download
p.initialize_proxy()
check(not downloads and p.initialized and len(p.all_filtered_items)
      == 170, "started at once with the saved 170, " "no download")
check(p.catalog_needs_refresh and p.catalog_version ==
      1 and p.catalog_source == "geil", "the new one still to fetch; version 1")
check(sorted(p.countries_list) == [u"France", u"Italy"] and len(
    p.channels_by_country["italy"]) == 150, "indexes built: countries, by country")
check(
    p.channel_rows(
        "Italy",
        False) and plugin.vavoo_proxy.proxy is not None,
    "channel_rows() answers from it")
old_by_country = p.channels_by_country
old_italy = list(old_by_country["italy"])
counts1 = p.country_counts(True)
check(
    p.start_catalog_refresh() is True and p.catalog_refreshing,
    "refresh started (vv-catalog)")
for _i in range(100):
    if not p.catalog_refreshing:
        break
    time.sleep(0.02)
check(
    downloads == ["auto"] and p.catalog_version == 2 and list(
        p.countries_list) == [u"Portugal"],
    "the new catalog in: version 2, Portugal only")
check(
    old_by_country["italy"] == old_italy and p.channels_by_country is not old_by_country,
    "the old indexes were never changed in place (a reader in the middle keeps whole data)")
check(p.country_counts(True) != counts1 and p.country_counts(
    True).get("portugal"), "counts follow the new catalog")
check(not p.catalog_needs_refresh and p.start_catalog_refresh()
      is False, "done: no second refresh")
saved = vp.load_saved_catalog("auto")
check(
    saved is not None and len(
        saved[0]) == 200,
    "the new one saved for the next start")

print("== a refresh that fails keeps what is in use, and tries again")
real_retry = vp.CATALOG_RETRY
vp.CATALOG_RETRY = 0.05
results = [([], "geil"), ([], "geil"),
           (channels(300, u"Spain", 20000), "geil")]
p2 = vp.VavooProxy()
p2._install_catalog(items, "geil")
p2.catalog_needs_refresh = True
p2._download_catalog = lambda setting: results.pop(0)
p2.start_catalog_refresh()
for _i in range(200):
    if not p2.catalog_refreshing:
        break
    time.sleep(0.02)
check(not results and list(p2.countries_list) == [
      u"Spain"], "two failures (the saved one stayed), then in")
p3 = vp.VavooProxy()
p3._install_catalog(items, "geil")
p3.catalog_needs_refresh = True
p3._download_catalog = lambda setting: ([], "geil")
vp.CATALOG_RETRY = 30
p3.start_catalog_refresh()
time.sleep(0.1)
p3.stop()
for _i in range(100):
    if not p3.catalog_refreshing:
        break
    time.sleep(0.02)
check(not p3.catalog_refreshing and len(p3.all_filtered_items)
      == 170, "a stopped proxy's refresh ends at once")
vp.CATALOG_RETRY = real_retry

print("== no saved catalog / Reload List: the network, waited for")
os.remove(PATH)
vp._catalog_digest[0] = None
del downloads[:]
p4 = vp.VavooProxy()
p4._download_catalog = fake_download
p4.initialize_proxy()
check(
    downloads == ["auto"] and len(
        p4.all_filtered_items) == 200 and not p4.catalog_needs_refresh,
    "no file: downloaded at start, nothing to refresh")
check(os.path.exists(PATH), "...and saved")
del downloads[:]
p5 = vp.VavooProxy()
p5._download_catalog = fake_download
p5.initialize_proxy(use_saved=False)
check(
    downloads == ["auto"],
    "use_saved=False (Reload List): downloaded although a file exists")
p6 = vp.VavooProxy()
p6._download_catalog = lambda setting: ([], "geil")
os.remove(PATH)
vp._catalog_digest[0] = None
p6.initialize_proxy()
check(
    p6.initialized and p6.all_filtered_items == [] and p6.catalog_needs_refresh,
    "nothing anywhere: an empty start that keeps trying")

print("== restart_proxy_in_background(fresh=True)")
saved_fns = (
    vp.shutdown_proxy,
    vp._spawn_proxy_thread,
    vp.is_proxy_port_listening)
vp.shutdown_proxy = lambda: None
vp._spawn_proxy_thread = lambda: True
vp.is_proxy_port_listening = lambda: False
vp._fresh_start[0] = False
vp.restart_proxy_in_background()
time.sleep(0.2)
check(vp._fresh_start[0] is False,
      "a plain restart starts with the saved catalog")
vp.restart_proxy_in_background(fresh=True)
time.sleep(0.2)
check(
    vp._fresh_start[0] is True,
    "fresh=True: the next start loads from the network")
vp._fresh_start[0] = False
vp.shutdown_proxy, vp._spawn_proxy_thread, vp.is_proxy_port_listening = saved_fns
vp.remove_booting_file()
src = harness.plugin_source()
check("restart_proxy_in_background(fresh=True)" in harness.source_of(
    "MainVavoo"), "Reload List asks for a fresh catalog")

print("== the main list follows a new catalog")
main = make(plugin.MainVavoo, Session())
reloads = []
main.cat = lambda: reloads.append(1)
main.cat_list = ["row"]
main._reloading = False
main._catalog_seen = 1
plugin.get_proxy_status = lambda: {"ready": True, "catalog_version": 1}
main._follow_catalog()
check(not reloads, "the same catalog: nothing")
plugin.get_proxy_status = lambda: {"ready": True, "catalog_version": 2}
main._follow_catalog()
check(reloads == [1], "a new one: the countries and counts again")
main._reloading = True
main._follow_catalog()
check(reloads == [1], "not while Reload List runs")
plugin.get_proxy_status = plugin.vUtils.get_proxy_status
check(
    vp.proxy_state()["catalog_version"] == getattr(
        vp.proxy,
        "catalog_version",
        0),
    "proxy_state() carries catalog_version")
finish()
