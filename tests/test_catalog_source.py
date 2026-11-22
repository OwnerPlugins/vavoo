# -*- coding: utf-8 -*-
"""The catalog source does not answer (a box: "Vavoo/Kool only" and
vavoo.to's catalog HTTP 500 for an hour - 0 countries, "✓ Vavoo OK ·
0 ch"): a server error hands over to the next site (kool.to); a source
that gives nothing, with nothing in use, lends the saved list (or the
other source's) meanwhile and keeps asking sooner; the status line and
the main list say why."""
from __future__ import print_function
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
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn

PATH = vp.CATALOG_FILE
SETTING = ["vavoo"]
vp.catalog_setting = lambda: SETTING[0]
# (no real ping for a token)
vp.VavooProxy.refresh_addon_sig_if_needed = lambda self, force=False: "sig"


def channels(n, country=u"Italy", start=0):
    return [{"id": u"%d" % (start + i),
             "name": u"Canale %d" % (start + i),
             "url": u"http://x/%d" % (start + i),
             "country": country,
             "logo": u"",
             "group": country + u" ➾ Generale",
             "epg_id": u""} for i in range(n)]


def vavoo_items(n, start=0):
    return [{"type": "iptv",
             "ids": {"id": "v%d" % (start + i)},
             "name": "Canal %d" % (start + i),
             "url": "http://vavoo/%d" % (start + i),
             "group": u"Portugal ➾ Geral",
             "logo": ""} for i in range(n)]


# ---------------------------------------------------------------- the sites
ANSWERS = {"a": [500], "b": [500]}   # per site: status codes, last repeats
HITS = {"a": 0, "b": 0}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length") or 0)
        if length:
            self.rfile.read(length)
        site = self.path.strip("/").split("/")[0]
        HITS[site] = HITS.get(site, 0) + 1
        codes = ANSWERS.get(site, [404])
        code = codes.pop(0) if len(codes) > 1 else codes[0]
        body = b"oops"
        if code == 200:
            body = json.dumps({"items": vavoo_items(
                150), "nextCursor": None}).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True


server = Server(("127.0.0.1", 0), Handler)
SITE_PORT = server.server_address[1]
threading.Thread(target=server.serve_forever).start()
SITES = [
    "http://127.0.0.1:%d/a" %
    SITE_PORT,
    "http://127.0.0.1:%d/b" %
    SITE_PORT]


def fresh(geil=None):
    """A proxy on the fake sites; geil: what load_geil_catalog() gives."""
    p = vp.VavooProxy()
    p.base_sites = list(SITES)
    p.base_site_index = 0
    p._update_endpoints()

    def fake_geil():
        if geil:
            p._geil_error = ""
            return list(geil)
        p._geil_error = "geil.to timeout"
        return None
    p.load_geil_catalog = fake_geil
    return p


def answers(a, b):
    ANSWERS["a"], ANSWERS["b"] = list(a), list(b)
    HITS["a"] = HITS["b"] = 0


def forget_saved():
    if os.path.exists(PATH):
        os.remove(PATH)
    vp._catalog_digest[0] = None


print("== a server error hands over to the next site")
answers([500], [200])
p = fresh()
got = p.load_catalog("sig")
check(len(got) == 150 and got[0]["id"] == "v0",
      "vavoo.to HTTP 500, kool.to fine: the list from kool.to (%d)" % len(got))
check(HITS["a"] == 2 and HITS["b"] == 1,
      "the failing site asked twice (once more), then the next (%r)" % HITS)
check(p.base_site_index == 1 and p.catalog_url.startswith(SITES[1]),
      "kool.to stays the site in use")
check(p._vavoo_error == "", "no error kept")
answers([503], [200])
check(len(fresh().load_catalog("sig")) == 150, "...an HTTP 503 too")
answers([500], [500])
p = fresh()
check(p.load_catalog("sig") == [], "both sites 500: no list ([])")
check(p._vavoo_error.count("HTTP 500") == 2,
      "both sites' failure kept: %r" % p._vavoo_error)
check(vp.catalog_error_text({"vavoo": p._vavoo_error}) == "Vavoo: HTTP 500",
      "...said in a few words: 'Vavoo: HTTP 500'")
check(vp.catalog_error_text(
    {"vavoo": "vavoo.to HTTP 500, kool.to timeout",
     "geil": "geil.to no connection"}) ==
    "Geil: no connection; Vavoo: vavoo.to HTTP 500, kool.to timeout",
    "different failures: each site's")
check(vp.catalog_error_text({}) == "", "nothing failed: ''")
items, source = p._download_catalog("vavoo")
check(items == [] and source == "vavoo" and
      vp.catalog_error_text(p.catalog_errors) == "Vavoo: HTTP 500",
      "_download_catalog(): why, in catalog_errors")
answers([200], [200])
items, source = p._download_catalog("vavoo")
check(len(items) == 150 and p.catalog_errors == {},
      "a list again: the error gone")

print("== pinned to Vavoo, Vavoo gives nothing: the saved Geil list meanwhile")
forget_saved()
saved_items = channels(150) + channels(20, u"France", 1000)
vp.save_catalog(saved_items, "geil", "auto")
answers([500], [500])
p = fresh()
check(p.initialize_proxy() is True, "initialize_proxy(): True")
check(len(p.all_filtered_items) == 170 and p.catalog_source == "geil",
      "started with the saved Geil list (%d, %s)" %
      (len(p.all_filtered_items), p.catalog_source))
check(p.catalog_fallback == "vavoo" and p.catalog_needs_refresh,
      "Vavoo waited for; the refresh still to run")
state = vp.status_of(p)
check(state["catalog_fallback"] == "vavoo" and
      state["catalog_error"] == "Vavoo: HTTP 500",
      "/status says so: %r / %r" %
      (state["catalog_fallback"], state["catalog_error"]))
check(vp.load_saved_catalog("auto") is not None and
      len(vp.load_saved_catalog("auto")[0]) == 170 and
      vp.load_saved_catalog("vavoo") is None,
      "the saved file untouched (still the Geil one, saved for Auto)")

print("== ... and Vavoo again soon: its list in, nothing lent any more")
real_soon = vp.CATALOG_RETRY_SOON
vp.CATALOG_RETRY_SOON = (0.05, 0.05, 0.05)
answers([500, 500, 200], [500, 500, 200])
p.start_catalog_refresh()
for _i in range(300):
    if not p.catalog_refreshing:
        break
    time.sleep(0.02)
check(p.catalog_source == "vavoo" and len(p.all_filtered_items) == 150 and
      p.catalog_fallback is None,
      "Vavoo's list in use, fallback gone (%s, %d, %r)" %
      (p.catalog_source, len(p.all_filtered_items), p.catalog_fallback))
saved = vp.load_saved_catalog("vavoo")
check(saved is not None and saved[1] == "vavoo" and len(saved[0]) == 150,
      "Vavoo's list saved for the next start")
vp.CATALOG_RETRY_SOON = real_soon

print("== a list of the pinned source itself, saved under another setting")
forget_saved()
vp.save_catalog(saved_items, "geil", "auto")
got = vp.load_saved_catalog("geil")
check(got is not None and got[1] == "geil",
      "pinned to Geil: the Geil list saved under Auto starts at once")
check(vp.load_saved_catalog("vavoo") is None,
      "pinned to Vavoo: not the Geil one (that is only lent)")
check(vp.load_saved_catalog("vavoo", any_setting=True) is not None,
      "...unless lent (any_setting)")

print("== no saved list: the other source's from the network")
forget_saved()
answers([500], [500])
p = fresh(geil=channels(120, u"Spain", 500))
p.initialize_proxy()
check(p.catalog_source == "geil" and len(p.all_filtered_items) == 120 and
      p.catalog_fallback == "vavoo",
      "Geil's list lent (%s, %d)" % (p.catalog_source,
                                     len(p.all_filtered_items)))
check(not os.path.exists(PATH), "a lent list is never saved")

print("== nothing anywhere: empty, why on /status, sooner tries")
forget_saved()
answers([500], [500])
p = fresh()
p.initialize_proxy()
check(p.initialized and p.all_filtered_items == [] and
      p.catalog_fallback is None, "started empty")
check(vp.status_of(p)["catalog_error"] == "Geil: timeout; Vavoo: HTTP 500",
      "both sources' failure: %r" % vp.status_of(p)["catalog_error"])
check([p.catalog_retry_wait(n) for n in range(5)] ==
      [60, 120, 300, vp.CATALOG_RETRY, vp.CATALOG_RETRY],
      "empty: again after 1, 2, 5 min, then every 15")
p._install_catalog(channels(150), "geil", fallback="vavoo")
check(p.catalog_retry_wait(0) == 60, "a lent list: soon too")
p._install_catalog(channels(150), "geil")
check(p.catalog_retry_wait(0) == vp.CATALOG_RETRY,
      "the source's own list: every 15 min")
SETTING[0] = "auto"
p = fresh()
p.initialize_proxy()
check(p.all_filtered_items == [] and "Vavoo: HTTP 500" in
      vp.status_of(p)["catalog_error"], "Auto, both down: empty, why")

print("== the status line and the main list")


def text(state, *a):
    return plugin.to_text(plugin.proxy_status_text(state, *a))


ready = {"ready": True, "token_required": True, "addon_sig_valid": True,
         "addon_sig_age": 100}
check(text(dict(ready, channels_count=0, catalog_error="Vavoo: HTTP 500"))
      == u"✗ No channels - Vavoo: HTTP 500",
      "0 channels: never OK, and why (%r)" %
      text(dict(ready, channels_count=0, catalog_error="Vavoo: HTTP 500")))
check(text(dict(ready, channels_count=0)) == u"✗ No channels",
      "0 channels, no error known")
lent = {"ready": True, "token_required": False, "channels_count": 9612,
        "catalog_fallback": "vavoo"}
check(text(lent) == u"Geil (Vavoo not answering) · 9612 ch",
      "a lent list: %r" % text(lent))
check(text(dict(lent, catalog_fallback=None)) == u"✓ Geil OK · 9612 ch",
      "the source's own list: OK as before")
pinned = plugin.to_text(plugin.no_channels_text(
    {"catalog_error": "Vavoo: HTTP 500"}, "vavoo"))
check("Vavoo: HTTP 500" in pinned and "Settings" in pinned,
      "the main list's row, pinned: why + OK opens the settings (%r)" % pinned)
check("Reload List" in plugin.to_text(plugin.no_channels_text({}, "auto")),
      "Auto: OK reloads")

plugin.get_proxy_status = lambda: {"ready": True, "channels_count": 0,
                                   "catalog_error": "Vavoo: HTTP 500"}
plugin.cfg.catalog_source = harness.V("vavoo")
main = make(plugin.MainVavoo, Session())
main._update_proxy_status_display = lambda: None
main._on_countries_response("[]", None, {}, 0, [], 0)
rows = main["menulist"].rows
check(len(rows) == 1 and rows[0][0][1] == plugin.NO_CHANNELS_ROW,
      "no countries: one row, the reason (%r)" % [r[0] for r in rows])
check("HTTP 500" in plugin.to_text(rows[0][0][0]),
      "...which says why: %r" % rows[0][0][0])
opened = []
main.goConfig = lambda: opened.append("settings")
main.reload_list = lambda answer=None: opened.append(("reload", answer))
main.ok()
check(opened == ["settings"], "OK on it, pinned: the settings (%r)" % opened)
plugin.cfg.catalog_source = harness.V("auto")
del opened[:]
main.ok()
check(opened == [("reload", True)],
      "OK on it, Auto: Reload List, no question (%r)" % opened)
main._on_countries_response('["Portugal"]', None, {"portugal": 3}, 0, [], 0)
check([r[0][1] for r in main["menulist"].rows] == ["Portugal"],
      "countries again: no reason row")
notes = []
real_notify = plugin.quick_notify
plugin.quick_notify = lambda message, seconds=3: notes.append(
    plugin.to_text(message))
main._reloading = True
main._on_countries_response("[]", None, {}, 0, [], 0)
check(notes and "No channels" in notes[-1] and "HTTP 500" in notes[-1],
      "Reload List with nothing: the notice says why (%r)" % notes)
plugin.quick_notify = real_notify
plugin.get_proxy_status = plugin.vUtils.get_proxy_status

server.shutdown()
forget_saved()
finish()
