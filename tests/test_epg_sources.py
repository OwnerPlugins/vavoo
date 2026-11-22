# -*- coding: utf-8 -*-
"""Where the programmes come from (the app's Epg.kt): the daily files of
epgshare01.online first (.xml.gz, the Balkans' three together), the
GitHub copy when they fail or are out of date - all through the proxy's
/epg/<cc>.xml, as plain XMLTV. Fake feeds on 127.0.0.1."""
from __future__ import print_function
import gzip
import io
import os
import sys
import threading
import time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
vu = harness.plugin.vUtils
vp = harness.plugin.vavoo_proxy
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
    os.environ.pop(key, None)
try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
    from email.utils import formatdate
    from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
    from urllib.error import HTTPError
except ImportError:                             # Python 2
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn
    from email.utils import formatdate
    from urllib2 import Request, build_opener, ProxyHandler, HTTPRedirectHandler, HTTPError

NOW = time.time()


def xt(t):
    return time.strftime("%Y%m%d%H%M%S +0000", time.gmtime(t))


def feed(channels, programmes, pad=0):
    """XMLTV bytes: channels [(id, name)], programmes [(channel, start, stop, title)]."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n',
           '<!DOCTYPE tv SYSTEM "xmltv.dtd">\n<tv generator-info-name="test">\n']
    for cid, name in channels:
        out.append('  <channel id="%s">\n    <display-name lang="xx">%s</display-name>\n  </channel>\n'
                   % (cid, name))
    for ch, start, stop, title in programmes:
        out.append('  <programme start="%s" stop="%s" channel="%s">\n    <title>%s</title>\n'
                   '    <desc>%s</desc>\n  </programme>\n' % (xt(start), xt(stop), ch, title, "x" * pad))
    out.append('</tv>\n')
    return "".join(out).encode("utf-8")


def gz(data):
    buf = io.BytesIO()
    f = gzip.GzipFile(fileobj=buf, mode="wb")
    f.write(data)
    f.close()
    return buf.getvalue()


def hours(ch, title, count=6, start=NOW - 3600):
    return [(ch, start + i * 3600, start + (i + 1) * 3600, "%s %d" % (title, i)) for i in range(count)]


FILES = {}       # path -> (status, body, headers)
HITS = []


def serve(path, body, status=200, headers=None):
    FILES[path] = (status, body, headers or {})


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        HITS.append(self.path)
        status, body, headers = FILES.get(self.path, (404, b"no", {}))
        try:
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass


class TS(ThreadingMixIn, HTTPServer):
    daemon_threads = True


up = TS(("127.0.0.1", 0), Upstream)
threading.Thread(target=up.serve_forever).start()
UP = "http://127.0.0.1:%d" % up.server_address[1]
FRESH = {"Content-Type": "application/x-gzip", "Last-Modified": formatdate(NOW - 3600, usegmt=True)}

vu.EPG_DAILY_URL = UP + "/%s.xml.gz"
vu.EPG_COPY_URL = UP + "/copy_%s.xml"
vu.EPG_DAILY_SOURCES = {"al": ("AL1",), "bk": ("BA1", "HR1", "RS1"), "xx": ("XX1",), "st": ("ST1",),
                        "ol": ("OL1",), "er": ("ER1",), "bg": ("BG1",), "two": ("T1", "T2")}

print("== open_url_stream: a .gz file, a gzip answer, a plain one")
AL = feed([("Top.Channel.al", "Top Channel"), ("Klan.al", "Klan")],
          hours("Top.Channel.al", "Lajme") + hours("Klan.al", "Film"))
serve("/AL1.xml.gz", gz(AL), headers=FRESH)
serve("/enc.xml", gz(AL), headers={"Content-Encoding": "gzip"})
serve("/plain.xml", AL)
for path in ("/AL1.xml.gz", "/enc.xml", "/plain.xml"):
    s = vu.open_url_stream(UP + path)
    body = s.read()
    s.close()
    check(body == AL, "%s read unpacked (%d bytes)" % (path, len(body)))
s = vu.open_url_stream(UP + "/AL1.xml.gz")
check(vu.response_header(s, "Last-Modified") == FRESH["Last-Modified"], "its headers")
s.close()
empty = vu._HttpStream(io.BytesIO(b""), False)
check(empty.read(10) == b"" and empty.read(10) == b"", "an empty answer is just empty")
one = vu._HttpStream(io.BytesIO(b"<"), False)
check(one.read(10) == b"<" and one.read(10) == b"", "a one-byte answer is that byte")

print("== one file goes through as it is")
out = b"".join(vu.country_epg_chunks("al", vu.epg_daily_urls("al")))
check(out == AL, "the same XML")

print("== the Balkans: three files, one guide")
BA = feed([("HRT1.hr", "HRT 1"), ("BHT1.ba", "BHT 1")], hours("HRT1.hr", "BA-HRT") + hours("BHT1.ba", "BHT"))
HR = feed([("HRT1.hr", "HRT 1 HR"), ("RTL.hr", "RTL")], hours("HRT1.hr", "HR-HRT") + hours("RTL.hr", "RTL"))
RS = feed([("RTS1.rs", "RTS 1")], hours("RTS1.rs", "RTS") + hours("Stray.rs", "stray"))
for name, body in (("BA1", BA), ("HR1", HR), ("RS1", RS)):
    serve("/%s.xml.gz" % name, gz(body), headers=FRESH)
merged = b"".join(vu.country_epg_chunks("bk", vu.epg_daily_urls("bk")))
root = ET.fromstring(merged)
tags = [e.tag for e in root]
check(tags.index("programme") > max(i for i, t in enumerate(tags) if t == "channel"),
      "every channel before the first programme")
ids = [e.get("id") for e in root.findall("channel")]
check(sorted(ids) == ["BHT1.ba", "HRT1.hr", "RTL.hr", "RTS1.rs"], "each channel once: %s" % ids)
check([e.findtext("display-name") for e in root.findall("channel") if e.get("id") == "HRT1.hr"] == ["HRT 1"],
      "a channel in two files: the first file's")
hrt = [e.findtext("title") for e in root.findall("programme") if e.get("channel") == "HRT1.hr"]
check(len(hrt) == 6 and all(t.startswith("BA-HRT") for t in hrt), "...and the first file's programmes only")
check(len([e for e in root.findall("programme") if e.get("channel") == "RTS1.rs"]) == 6
      and len([e for e in root.findall("programme") if e.get("channel") == "Stray.rs"]) == 6,
      "the other files' programmes (even of a channel none declares)")
check(merged.rstrip().endswith(b"</tv>") and merged.count(b"<tv ") == 1 and merged.count(b"</tv>") == 1,
      "one <tv> ... </tv>")
fids, names = vu._read_epg_feed_channels(io.BytesIO(merged))
check(sorted(fids) == ["BHT1.ba", "HRT1.hr", "RTL.hr", "RTS1.rs"], "the feed index sees the three files' channels")
guide = vu._parse_epg_guide(io.BytesIO(merged), "bk", NOW)
check(set(guide.programmes) >= {"HRT1.hr", "BHT1.ba", "RTL.hr", "RTS1.rs"}, "the guide has them all")

print("== cut anywhere: the same pieces")
pieces = vu._XmltvPieces()
got = []
for i in range(0, len(BA), 7):
    got.extend(pieces.feed(BA[i:i + 7]))
got.extend(pieces.finish())
whole = vu._XmltvPieces()
ref = whole.feed(BA) + whole.finish()
check(got == ref and b"".join(p[-1] for p in got) == BA, "7-byte chunks: %d pieces, nothing lost" % len(got))
check([p[0] for p in ref].count("channel") == 2 and [p[0] for p in ref].count("programme") == 12
      and ref[0][0] == "head" and ref[-1][0] == "tail", "head, 2 channels, 12 programmes, tail")
quoted = feed([("A.x", "A")], [])
quoted = quoted.replace(b'id="A.x"', b"id='A.x'")
qp = vu._XmltvPieces()
qr = qp.feed(quoted) + qp.finish()
check([p[1] for p in qr if p[0] == "channel"] == [b"A.x"], "single-quoted ids too")

print("== one of three fails: the other two")
del FILES["/RS1.xml.gz"]
merged = b"".join(vu.country_epg_chunks("bk", vu.epg_daily_urls("bk")))
root = ET.fromstring(merged)
check(sorted(e.get("id") for e in root.findall("channel")) == ["BHT1.ba", "HRT1.hr", "RTL.hr"], "BA1 + HR1")
del FILES["/BA1.xml.gz"]
del FILES["/HR1.xml.gz"]
try:
    next(vu.country_epg_chunks("bk", vu.epg_daily_urls("bk")))
    check(False, "all three failing: an error")
except Exception as e:
    check(not isinstance(e, vu.EpgFeedStale), "all three failing: an error before any byte (%s)" % e)

print("== out of date, not XMLTV")
serve("/ST1.xml.gz", gz(AL), headers={"Last-Modified": formatdate(NOW - 10 * 86400, usegmt=True)})
try:
    next(vu.country_epg_chunks("st", vu.epg_daily_urls("st")))
    check(False, "a file not changed for 10 days")
except vu.EpgFeedStale as e:
    check(True, "a file not changed for 10 days: out of date (%s)" % e)
serve("/ER1.xml.gz", b"<html><body>Service Unavailable</body></html>", headers={"Content-Type": "text/html"})
try:
    next(vu.country_epg_chunks("er", vu.epg_daily_urls("er")))
    check(False, "an error page")
except Exception as e:
    check(not isinstance(e, vu.EpgFeedStale), "an error page is not a guide (%s)" % e)


print("== through the proxy")


class FakeProxy(object):
    def is_stopped(self):
        return False


vp.proxy = FakeProxy()
px = vp.ThreadedHTTPServer(("127.0.0.1", 0), vp.VavooHTTPHandler)
threading.Thread(target=px.serve_forever).start()
PX = "http://127.0.0.1:%d" % px.server_address[1]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def get(path, method="GET", follow=False):
    req = Request(PX + path)
    req.get_method = lambda: method
    handlers = [ProxyHandler({})] + ([] if follow else [NoRedirect()])
    try:
        r = build_opener(*handlers).open(req, timeout=20)
        return r.getcode(), r.info(), r.read()
    except HTTPError as e:
        return e.code, e.info(), b""


serve("/AL1.xml.gz", gz(AL), headers=FRESH)
code, h, body = get("/epg/al.xml")
check(code == 200 and h.get("X-Vavoo-EPG") == "daily" and body == AL, "daily: 200, plain XML (%s)" % code)
code, h, body = get("/epg/AL.xml")
check(code == 200 and body == AL, "the country in capitals too")
before = len(HITS)
code, h, body = get("/epg/al.xml", "HEAD")
check(code == 200 and len(HITS) == before, "HEAD: 200 and nothing downloaded")
code, h, body = get("/epg/zz.xml")
check(code == 302 and h.get("Location") == UP + "/copy_zz.xml", "no daily files: the GitHub copy (%s)" % code)
code, h, body = get("/epg/xx.xml")
check(code == 302 and h.get("Location") == UP + "/copy_xx.xml", "daily file missing: the copy")
left = vu._epg_daily_unusable.get("xx", 0) - time.time()
check(vu.epg_daily_urls("xx") == [] and 250 < left <= 300, "...and the copy for 5 minutes (%d s)" % left)
before = len(HITS)
code, h, body = get("/epg/xx.xml")
check(code == 302 and len(HITS) == before, "meanwhile not asked again")
code, h, body = get("/epg/st.xml")
left = vu._epg_daily_unusable.get("st", 0) - time.time()
check(code == 302 and left > 5 * 3600, "out of date: the copy for 6 hours (%d s)" % left)
serve("/copy_zz.xml", AL)
code, h, body = get("/epg/zz.xml", follow=True)
check(code == 200 and body == AL and h.get("X-Vavoo-EPG") is None, "following the redirect gives the copy")

print("== a client that stops reading: the downloads close")
BIG = feed([("Big.bg", "Big")], hours("Big.bg", "Long", count=4000), pad=2000)
serve("/BG1.xml.gz", gz(BIG), headers=FRESH)
CLOSED = []
real_open = vu.open_url_stream


def tracked(url, timeout=20):
    s = real_open(url, timeout=timeout)
    real_close = s.close

    def close():
        CLOSED.append(url)
        real_close()
    s.close = close
    return s


vu.open_url_stream = tracked
import socket                                   # noqa: E402
sock = socket.create_connection(px.server_address)
sock.sendall(b"GET /epg/bg.xml HTTP/1.0\r\nHost: x\r\n\r\n")
first = sock.recv(4096)
sock.close()
for _ in range(100):
    if CLOSED:
        break
    time.sleep(0.1)
check(first.startswith(b"HTTP/1.0 200") and CLOSED == [UP + "/BG1.xml.gz"],
      "%d MB guide, client gone after 4 KB: its download closed" % (len(BIG) // 1000000))
vu.open_url_stream = real_open

print("== the plugin's guide: daily, or the copy when the daily one is out of date")
vu.PORT = px.server_address[1]
vu.PROXY_HOST = "127.0.0.1"
OLD = feed([("Old.ol", "Old")], hours("Old.ol", "Past", start=NOW - 20 * 3600))
NEW = feed([("Old.ol", "Old")], hours("Old.ol", "Now"))
serve("/OL1.xml.gz", gz(OLD), headers=FRESH)
serve("/copy_ol.xml", gz(NEW), headers={"Content-Encoding": "gzip"})
g = vu._download_epg_guide("al")
check(g is not None and set(g.programmes) == {"Top.Channel.al", "Klan.al"}, "al: the daily guide")
g = vu._download_epg_guide("ol")
titles = [entry[2] for entry in (g.programmes.get("Old.ol") or [])] if g else []
check(titles and all(t.startswith("Now") for t in titles), "ol: daily all over -> the copy's programmes")
left = vu._epg_daily_unusable.get("ol", 0) - time.time()
check(left > 5 * 3600, "...and the copy for 6 hours (%d s)" % left)
check(vu._guide_is_current(g, NOW) and not vu._guide_is_current(vu._parse_epg_guide(io.BytesIO(OLD), "ol", NOW), NOW),
      "_guide_is_current()")

REAL = [os.path.join(os.environ.get("VAVOO_EPG_SAMPLES") or os.path.join(HERE, "epgdl"), "epg_%s.xml.gz" % cc)
        for cc in ("fr", "pl")]
if all(os.path.exists(p) for p in REAL):
    print("== two real files (fr + pl, the GitHub copies) put together")
    raw = []
    for name, p in zip(("T1", "T2"), REAL):
        data = open(p, "rb").read()
        serve("/%s.xml.gz" % name, data, headers=FRESH)
        raw.append(gzip.GzipFile(fileobj=io.BytesIO(data)).read())
    t0 = time.time()
    merged = b"".join(vu.country_epg_chunks("two", vu.epg_daily_urls("two")))
    took = time.time() - t0
    own = [vu._read_epg_feed_channels(io.BytesIO(r))[0] for r in raw]
    fids, _names = vu._read_epg_feed_channels(io.BytesIO(merged))
    check(fids == own[0] | own[1], "%d + %d channels -> %d, all of them" % (len(own[0]), len(own[1]), len(fids)))
    count = merged.count(b"<programme ")
    expected = raw[0].count(b"<programme ") + sum(
        1 for line in raw[1].split(b"<programme ")[1:]
        if vu._XMLTV_KEY[b"programme"].search(b" " + line[:400]).group(1) not in own[0])
    check(count == expected, "%d programmes (%.1f MB in %.1f s)" % (count, len(merged) / 1e6, took))
    guide = vu._parse_epg_guide(io.BytesIO(merged), "two", NOW)
    check(len(guide.feed_ids) == len(fids), "the guide parses it: %d programmes kept" % guide.programme_count)

px.shutdown()
up.shutdown()
finish()
