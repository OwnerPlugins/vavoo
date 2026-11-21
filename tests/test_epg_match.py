# -*- coding: utf-8 -*-
"""The EPG matcher's order (as the app): the source's own guide id
(geil.to's "tvg") first, then the alias table, the box's cache, the
curated database, the feed's own names - every id one the feed has.
No Rytec, no satellites."""
from __future__ import print_function
import io
import os
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
vu = harness.plugin.vUtils
TMP = tempfile.mkdtemp(prefix="vavoo_match_")
vu.UNMATCHED_FILE = os.path.join(TMP, "unmatched.json")
vu.CACHE_FILE = os.path.join(TMP, "cache.json")
vu._unmatched_cache_data = None

FEEDS = {
    "it": [("Rai.1.it", "Rai 1"), ("Rai.2.it", "Rai 2"), ("BBC.One.uk", "BBC One")],
    "gb": [("BBC.One.uk", "BBC One")],
    "pl": [("TVP.1.pl", "TVP 1"), ("TVP.2.pl", "TVP 2"), ("Polsat.pl", "Polsat"), ("TVN.pl", "TVN"),
           ("Canal+.Sport.pl", "Canal+ Sport")],
}
INDEX = {}
for cc, rows in FEEDS.items():
    names = {}
    for fid, dn in rows:
        clean = vu.clean_name_for_similarity(dn)
        names[clean] = (fid, vu._tokenize_for_compat(clean))
    INDEX[cc] = (set(fid for fid, _dn in rows), names)
FEED_IDS = INDEX["pl"][0]
CURATED = {}
vu._get_epg_feed_index = lambda cc: INDEX.get(cc, (None, None))
vu._load_curated_channel_db = lambda cc: CURATED


def matcher(cache=None, aliases=None):
    m = vu.VavooEPGMatcher.__new__(vu.VavooEPGMatcher)
    m.similarity_threshold = 0.75
    m._cache_lock = threading.RLock()
    m.cache = dict(cache or {})
    m.new_matches = {}
    m.normalized_index = {}
    m._build_normalized_index()
    m.alias_map = dict(aliases or {})
    return m


print("== nothing of Rytec or the satellites is left")
src = open(os.path.join(harness.PLUGIN_DIR, "vUtils.py")).read()
for name in ("rytec_by_id", "_load_rytec_database", "nimmanager", "get_configured_satellites",
             "_get_signal_priority", "rytec.channels.xml", "_SATELLITE_NAMESPACES"):
    check(name not in src, "no %s" % name)
check(not hasattr(vu, "get_satellite_priority") and not hasattr(vu.VavooEPGMatcher, "is_valid_rytec_id"),
      "the functions are gone")
init = open(os.path.join(harness.PLUGIN_DIR, "__init__.py")).read()
check("satellite_positions" not in init, "no satellite table")

print("== _feed_spelling(): the id as the feed writes it")
check(vu._feed_spelling("TVP.1.pl", FEED_IDS) == "TVP.1.pl", "the same")
check(vu._feed_spelling("tvp.1.PL", FEED_IDS) == "TVP.1.pl", "other case")
check(vu._feed_spelling("TVP1.pl", FEED_IDS) == "TVP.1.pl", "other dots")
check(vu._feed_spelling("canal+sport.PL", FEED_IDS) == "Canal+.Sport.pl", "both")
check(vu._feed_spelling("TVP.9.pl", FEED_IDS) is None and vu._feed_spelling("", FEED_IDS) is None
      and vu._feed_spelling("TVP.1.pl", None) is None, "not there: None")
check(vu._feed_spelling(u"tvp.2.pl", FEED_IDS) == "TVP.2.pl", "unicode id")

print("== 1. the source's own guide id first")
m = matcher(cache={"tvp 1_pl": {"id": "TVP.2.pl", "sref": "1:0:1:2:3:4:5:6:0:0:", "source": "live"}})
CURATED.clear()
CURATED[vu.clean_name_for_similarity("TVP 1")] = "Polsat.pl"
got = m.find_match("TVP 1", "pl", channel_id="t1", epg_guide_id="tvp1.PL")
check(got[0] == "TVP.1.pl" and got[2] == "live", "beats the cache and the curated database: %s" % (got,))
check(got[1] == vu.unique_fallback_sref("4097", "t1"), "its own synthetic sref")
got = m.find_match("TVP 1", "pl", channel_id="t1", epg_guide_id="Nope.pl")
check(got[0] == "TVP.2.pl", "an id the feed lacks: the next steps - here the cache (%s)" % (got,))
got = matcher().find_match("TVP 1", "es", channel_id="t1", epg_guide_id="TVP.1.pl")
check(got[0] != "TVP.1.pl", "no feed for the country: not trusted blindly (%s)" % (got,))
CURATED.clear()

print("== 2. an alias counts when the feed has it")
got = matcher().find_match("RAI 1 .b", "it", channel_id="r1")
check(got[0] == "Rai.1.it" and got[2] == "alias",
      "ALIAS_MAP's Rai1.it -> the feed's Rai.1.it (Rytec's ids were needed before) (%s)" % (got,))
got = matcher(aliases={"TVP INFO": "TVPInfo.pl"}).find_match("TVP Info", "pl", channel_id="ti")
check(got[2] != "alias", "an alias the feed lacks: the next steps (%s)" % (got,))
got = matcher(aliases={"BBC ONE": "BBC.One.uk"}).find_match("BBC One", "gb", channel_id="b1")
check(got[0] == "BBC.One.uk" and got[2] == "alias", "gb -> .uk ids (%s)" % (got,))
got = matcher(aliases={"POLSAT": "BBC.One.uk"}).find_match("Polsat", "pl", channel_id="p1")
check(got[2] != "alias", "another country's id: not for Poland (%s)" % (got,))
got = matcher(aliases={"BBC ONE": "BBC.One.uk"}).find_match("BBC One", "it", channel_id="b1")
check(got[2] == "alias", "Italy (the table's home) trusts every entry (%s)" % (got,))

print("== 3. the cache: its id must be the feed's")
cache = {"polsat_pl": {"id": "polsat.PL", "sref": "1:0:19:1:2:3:4:0:0:0:", "source": "live", "matched": True},
         "tvp kultura_pl": {"id": "TVPKultura.pl", "sref": "1:0:19:9:2:3:4:0:0:0:", "source": "live",
                            "matched": True}}
m = matcher(cache=cache)
got = m.find_match("Polsat", "pl", channel_id="p1")
check(got[0] == "Polsat.pl" and got[1] == vu.unique_fallback_sref("4097", "p1"),
      "an old entry: the feed's spelling and a synthetic sref (%s)" % (got,))
got = m.find_match("TVP Kultura", "pl", channel_id="tk")
check(got == (None, None, None), "an old Rytec id the feed lacks, no name: unmatched (%s)" % (got,))
check(m.cache["tvp kultura_pl"]["matched"] is False, "...and the entry says so")
cache_es = {"polsat_es": {"id": "Polsat.pl", "sref": "x", "source": "live"}}
got = matcher(cache=cache_es).find_match("Polsat", "es", channel_id="p1")
check(got[0] == "Polsat.pl", "no feed index: the cache as it is (%s)" % (got,))

print("== 4. the curated database, 5. the feed's names")
CURATED[vu.clean_name_for_similarity("Canal Plus Sport HD")] = "Canal+.Sport.pl"
got = matcher().find_match("Canal Plus Sport HD", "pl", channel_id="cs")
check(got[0] == "Canal+.Sport.pl" and got[2] == "curated", "curated (%s)" % (got,))
CURATED.clear()
got = matcher().find_match("TVP 2 .b", "pl", channel_id="t2")
check(got[0] == "TVP.2.pl" and got[2] == "live", "the feed's own name (%s)" % (got,))
got = matcher().find_match("Nothing Like It", "pl", channel_id="n")
check(got == (None, None, None), "nothing: unmatched")

print("== the guide: the source's id without the matcher")
calls = []
real_get = vu.get_epg_matcher
vu.get_epg_matcher = lambda *a: calls.append(1) or real_get()
guide = vu.EpgGuide("it", time.time())
now = time.time()
guide.programmes = {"Rai.1.it": [(now - 60, now + 3000, "Tg1", "")]}
guide.feed_ids = set(["Rai.1.it"])
key = vu._resolve_guide_channel(guide, "RAI 1", "it", "r1", epg_id="rai1.it")
check(key == "Rai.1.it" and not calls, "rai1.it -> Rai.1.it, no matcher call")
vu.get_epg_matcher = real_get

finish()
