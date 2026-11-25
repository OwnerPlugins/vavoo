# -*- coding: utf-8 -*-
"""The curated EPG channel database: its workflow runs on GitHub's own
runners (it waited for a self-hosted runner that was gone - every run
cancelled after 24 h since 2026-10-12), with the plugin's proxy started
there by tests/headless_proxy.py; the generator matches against the
guide the plugin reads (the proxy's /epg/<cc>.xml); the plugin reads the
database from this repository (it read Belfagor2005's, which the
workflow never wrote), and a curated id the guide does not have is not
taken. Python 3 (the generator is a Python 3 tool)."""
from __future__ import print_function
import io
import json
import os
import socket
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
import headless_proxy                           # noqa: E402
sys.path.insert(0, harness.PLUGIN_DIR)
import generate_epg_channel_db as gen           # noqa: E402
plugin = harness.plugin
vu = plugin.vUtils
vp = plugin.vavoo_proxy
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
except ImportError:                             # (Python 3 only test)
    BaseHTTPRequestHandler = HTTPServer = None


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


print("== the workflow: GitHub's runners, the proxy started there")
wf = io.open(os.path.join(harness.e2env.REPO, ".github", "workflows",
                          "generate_epg_channel_db.yml"),
             encoding="utf-8").read()
check("runs-on: ubuntu-latest" in wf and "self-hosted" not in
      wf.split("jobs:", 1)[1], "runs on ubuntu-latest, not self-hosted")
check("tests/headless_proxy.py" in wf and "--proxy-host 127.0.0.1" in wf,
      "starts tests/headless_proxy.py and asks it")
check("contents: write" in wf and "git push" in wf,
      "may push the database back")
check("VAVOO_PROXY_HOST" not in wf, "no LAN box address needed")

print("== the proxy without a box")
CATALOG = [{"id": u"s%d" % i, "name": u"SIC .%s" % tag,
            "url": u"http://x/s%d" % i, "country": u"Portugal",
            "logo": u"", "group": u"Portugal", "epg_id": u""}
           for i, tag in enumerate("bcd")]
CATALOG += [{"id": u"r1", "name": u"RTP 1", "url": u"http://x/r1",
             "country": u"Portugal", "logo": u"", "group": u"Portugal",
             "epg_id": u""}]
CATALOG += [{"id": u"n%d" % i, "name": u"Canal %d" % i,
             "url": u"http://x/n%d" % i, "country": u"Portugal",
             "logo": u"", "group": u"Portugal", "epg_id": u""}
            for i in range(120)]
vp.VavooProxy._download_catalog = lambda self, setting: (
    list(CATALOG), "geil")
vp.VavooProxy.refresh_addon_sig_if_needed = lambda self, force=False: None
PORT = free_port()
thread = headless_proxy.start(PORT, "auto")
state = headless_proxy.wait_ready(20, step=0.1)
check(state and state.get("channels_count") == len(CATALOG),
      "ready with the catalog: %r" % (state or {}).get("channels_count"))
rows = gen.fetch_vavoo_channels("127.0.0.1", PORT, "portugal")
check(any(r["name"] == "SIC" for r in rows) and
      any(r["name"] == "RTP 1" for r in rows),
      "the generator reads /channels from it (%d rows)" % len(rows))

print("== the generator matches against the plugin's own guide")
check(gen.PROXY_FEED_URL.format(host="127.0.0.1", port=4323).format("pt")
      == "http://127.0.0.1:4323/epg/pt.xml",
      "by default the proxy's /epg/<cc>.xml")
asked = []
real_fetch = gen.fetch_feed_index
gen.fetch_feed_index = lambda cc, url: asked.append(url.format(cc)) or [
    ("SIC.pt", u"sic", gen.tokenize_for_compat(u"sic"))]
gen.generate_for_country("portugal", "pt", "127.0.0.1", PORT, 0.7)
gen.fetch_feed_index = real_fetch
check(asked == ["http://127.0.0.1:%d/epg/pt.xml" % PORT],
      "generate_for_country() asks the proxy's guide: %r" % asked)

FEED = (b'<?xml version="1.0" encoding="UTF-8"?><tv>'
        b'<channel id="SIC.pt"><display-name>SIC</display-name></channel>'
        b'<channel id="RTP1.pt"><display-name>RTP 1</display-name>'
        b'</channel><programme channel="SIC.pt" start="x"><title>a'
        b'</title></programme>' + b'<!-- -->' * 50000 + b'</tv>')


class Feed(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/xml")
        self.end_headers()
        self.wfile.write(FEED)

    def log_message(self, *a):
        pass


feed_server = HTTPServer(("127.0.0.1", 0), Feed)
feed_thread = threading.Thread(target=feed_server.serve_forever)
feed_thread.daemon = True
feed_thread.start()
feed_url = "http://127.0.0.1:%d/epg_{}.xml" % feed_server.server_port
index = gen.fetch_feed_index("pt", feed_url)
check(sorted(i[0] for i in index) == ["RTP1.pt", "SIC.pt"],
      "the guide's channels, read up to the first programme: %r" % index)
matched, review = gen.generate_for_country(
    "portugal", "pt", "127.0.0.1", PORT, 0.7, feed_url)
check(matched.get("sic") == "SIC.pt" and matched.get("rtp 1") == "RTP1.pt",
      "SIC and RTP 1 matched: %r" % dict(list(matched.items())[:4]))
feed_server.shutdown()
vp.shutdown_proxy()

print("== the plugin reads the database from this repository")
urls = []
real_get = vu.getUrl
vu.getUrl = lambda url, **k: urls.append(url) or json.dumps(
    {"sic": "SIC.pt"})
vu._curated_channel_db_cache.clear()
db = vu._load_curated_channel_db("pt")
vu.getUrl = real_get
check(urls == ["https://raw.githubusercontent.com/OwnerPlugins/vavoo/main/"
               "epg-channel-db/vavoo_channels_pt.json"] and db == {
    "sic": "SIC.pt"}, "OwnerPlugins/vavoo main: %r" % urls)

print("== a curated id the guide does not have is not taken")
vu.UNMATCHED_FILE = os.path.join(harness.DATA, "unmatched_wf.json")
vu.CACHE_FILE = os.path.join(harness.DATA, "cache_wf.json")
vu._unmatched_cache_data = None


def matcher():
    m = vu.VavooEPGMatcher.__new__(vu.VavooEPGMatcher)
    m.similarity_threshold = 0.75
    m._cache_lock = threading.RLock()
    m.new_matches = {}
    m.normalized_index = {}
    m.alias_map = {}
    m.cache = {}
    return m


clean = vu.clean_name_for_similarity("SIC")
vu._get_epg_feed_index = lambda cc: (
    set(["SIC.pt"]), {clean: ("SIC.pt", vu._tokenize_for_compat(clean))})
vu._load_curated_channel_db = lambda cc: {clean: "OldSIC.pt"}
feed_id, _sref, source = matcher().find_match("SIC", "pt", channel_id="s1")
check(feed_id == "SIC.pt" and source != "curated",
      "an old curated id: the guide's own name finds it (%r, %r)" %
      (feed_id, source))
vu._load_curated_channel_db = lambda cc: {clean: "sic.pt"}
feed_id, _sref, source = matcher().find_match("SIC", "pt", channel_id="s2")
check(feed_id == "SIC.pt" and source == "curated",
      "one the guide has in another case: in the guide's spelling (%r, %r)"
      % (feed_id, source))
finish()
