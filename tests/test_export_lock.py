# -*- coding: utf-8 -*-
"""A box's scheduled bouquet update hung for good (1.91): the export
holds export_lock (a plain Lock) for its whole run and find_match(),
inside it, asked for it again to save the EPG cache - at the first
cached channel whose id the country's feed no longer had ("ANIXE
SERIE" -> AnixeSerie.de). The bouquet it had just removed was never
written again, and every export after it was refused ("an export for
another country is already in progress") until a reboot. CACHE_FILE
has its own lock now; nothing inside an export asks for export_lock."""
from __future__ import print_function
import json
import os
import re
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
plugin = harness.plugin
vu = plugin.vUtils
TMP = tempfile.mkdtemp(prefix="vavoo_lock_")
vu.UNMATCHED_FILE = os.path.join(TMP, "unmatched.json")
vu.CACHE_FILE = os.path.join(TMP, "cache.json")
vu._unmatched_cache_data = None
# (the one lock every export takes: the package's, as plugin.py and
# bouquet_manager.py import it)
EXPORT_LOCK = sys.modules["vavoo"].export_lock
bm = sys.modules["vavoo.bouquet_manager"]

clean = vu.clean_name_for_similarity("Das Erste")
vu._get_epg_feed_index = lambda cc: (
    set(["DasErste.de"]),
    {clean: ("DasErste.de", vu._tokenize_for_compat(clean))})
vu._load_curated_channel_db = lambda cc: {}


def matcher(cache):
    m = vu.VavooEPGMatcher.__new__(vu.VavooEPGMatcher)
    m.similarity_threshold = 0.75
    m._cache_lock = threading.RLock()
    m.new_matches = {}
    m.normalized_index = {}
    m.alias_map = {}
    m.cache = dict(cache)
    m._build_normalized_index()
    return m


def entry(name, epg_id):
    return {"id": epg_id, "name": name, "country": "de",
            "sref": "4097:0:0:0:0:0:0:0:0:0:", "timestamp": "x",
            "matched": True}


def in_thread(fn, seconds=5):
    """fn() in another thread: (finished, its result)."""
    out = []
    t = threading.Thread(target=lambda: out.append(fn()))
    t.daemon = True
    t.start()
    t.join(seconds)
    return bool(out), (out[0] if out else None)


print("== the box: an export holds export_lock, a cached id is gone")
m = matcher({})
key = m._normalize_key("ANIXE SERIE", "de")
m.cache = {key: entry("ANIXE SERIE", "AnixeSerie.de")}
m._build_normalized_index()
check(EXPORT_LOCK.acquire(False), "export_lock taken (as an export does)")
try:
    done, result = in_thread(
        lambda: m.find_match("ANIXE SERIE", "de", channel_id="x1"))
    check(done, "find_match() comes back while the export holds the lock "
          "(it hung for good)")
    check(result == (None, None, None), "no match: %r" % (result,))
    saved = json.load(open(vu.CACHE_FILE)) if os.path.exists(
        vu.CACHE_FILE) else {}
    check(saved.get(key, {}).get("matched") is False,
          "the gone id saved as matched=False (CACHE_FILE's own lock)")
    check(vu._unmatched_cache_data and
          "ANIXE SERIE_de" in vu._unmatched_cache_data,
          "and staged as unmatched")
finally:
    EXPORT_LOCK.release()

print("== a whole bouquet export, the scheduled update's way")
m = matcher({m._normalize_key("ANIXE SERIE", "de"):
             entry("ANIXE SERIE", "AnixeSerie.de"),
             m._normalize_key("Das Erste", "de"):
             entry("Das Erste", "DasErste.de")})
real_enigma = bm.ENIGMA_PATH
bm.ENIGMA_PATH = TMP
bm._add_to_main_bouquet = lambda *a, **k: None
channels = [{"name": n, "url": "http://127.0.0.1:4323/vavoo?channel=%d" % i,
             "id": "%d" % i} for i, n in enumerate(
                 ["ANIXE SERIE", "Das Erste", "Sender Ohne Guide"])]
check(EXPORT_LOCK.acquire(False), "export_lock taken")
try:
    done, result = in_thread(lambda: bm.create_bouquet_file(
        "Germany", channels, "4097", "flat", "bottom", m, "de"))
    check(done and result and result[0] == 3,
          "create_bouquet_file() finishes with the lock held: %r" %
          ((result or ())[:2],))
    path = os.path.join(TMP, result[1]) if done and result else ""
    check(path and os.path.exists(path) and
          open(path).read().count("#SERVICE") == 3,
          "the bouquet is written again (3 channels)")
    done, _r = in_thread(lambda: vu.update_complete_cache(
        result[2], result[3], "de"))
    check(done, "update_complete_cache() too")
finally:
    EXPORT_LOCK.release()
bm.ENIGMA_PATH = real_enigma
check(EXPORT_LOCK.acquire(False), "...and the lock is free afterwards")
EXPORT_LOCK.release()

print("== CACHE_FILE's writers share one lock, export_lock is the exporter's")
src = open(os.path.join(harness.PLUGIN_DIR, "vUtils.py")).read()
code = "\n".join(line.split("#")[0] for line in src.splitlines())
check(not re.search(r"\bexport_lock\b", code),
      "vUtils never takes export_lock (the matcher runs inside exports)")
for name in ("save_cache", "fix_cache_format"):
    body = code.split("def %s(" % name, 1)[1].split("\ndef ", 1)[0]
    check("_cache_file_lock" in body, "%s() under _cache_file_lock" % name)
body = code.split("def update_complete_cache(", 1)[1].split("\ndef ", 1)[0]
check("_cache_file_lock.acquire()" in body and
      "_merge_matched_into_cache_file(" in body,
      "update_complete_cache(): its read-modify-write under it")
check(vu._cache_file_lock.acquire(False), "the file lock is free at rest")
vu._cache_file_lock.release()
finish()
