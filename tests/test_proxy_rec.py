# -*- coding: utf-8 -*-
"""vavoo_proxy.py's recording side: a recording's own token,
resolve_own(), and /file (registered ids only, offset, Range, follow)."""
from __future__ import print_function
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
import fakehls                                  # noqa: E402
vp = harness.plugin.vavoo_proxy
import vavoo.vavoo_record as vr                 # noqa: E402
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)

print("== own tokens")
p = vp.VavooProxy.__new__(vp.VavooProxy)
p.addon_sig_data = {"sig": "SHARED", "ts": time.time()}
p.addon_sig_lock = threading.Lock()
p._own_sigs = {}
p._own_sig_lock = threading.Lock()
pings = []


def fake_ping():
    pings.append(1)
    return "OWN%d" % len(pings)


p._request_addon_sig = fake_ping
check(p.own_signature("rec1") == "OWN1", "a token of its own")
check(p.own_signature("rec1") == "OWN1" and len(pings) == 1, "kept while young")
check(p.own_signature("rec2") == "OWN2", "another recording: another token")
check(p.addon_sig_data["sig"] == "SHARED", "the shared token untouched")
check(p.own_signature("rec1", force=True) == "OWN1" and len(
    pings) == 2, "forced right away: the same")
p._own_sigs["rec1"]["ts"] -= vp.OWN_SIG_FORCE_MIN + 1
check(p.own_signature("rec1", force=True) == "OWN3", "forced later: a new one")
p._own_sigs["rec1"]["ts"] -= vp.TOKEN_REFRESH_AGE + 1
p._request_addon_sig = lambda: None
check(p.own_signature("rec1") is None, "old and no new one: none")
p._request_addon_sig = fake_ping
check(p.own_signature("rec1") is None, "a failure is not repeated at once")
p._own_sigs["rec1"]["failed"] -= vp.OWN_SIG_RETRY + 1
check(p.own_signature("rec1") == "OWN4", "after a while: asked again")
p.drop_own_signature("rec1")
check("rec1" not in p._own_sigs, "dropped when the recording ends")

print("== resolve_own")
posted = []


class Resp(object):
    status_code = 200

    def __init__(self, url):
        self.url = url

    def raise_for_status(self):
        pass

    def close(self):
        pass


class Session(object):
    def post(self, url, json=None, headers=None, timeout=None):
        posted.append((json["url"], headers["mediahubmx-signature"]))
        return Resp("https://cdn.example/" +
                    json["url"].split("/")[-1] + ".m3u8")


vp_decode = vp.decode_response
vp.decode_response = lambda r: {"url": r.url}
p.session = Session()
p.catalog_source = "vavoo"
p.resolve_url = "https://vavoo.example/resolve"
p.current_language = "en"
p.current_region = "US"
p.resolve_cache = {}
p.resolve_cache_lock = threading.Lock()
p.channels_by_id = {"abc": {"id": "abc", "url": "https://vavoo.to/play/abc"},
                    "m1": {"id": "m1", "url": "https://vavoo.to/play/m1"},
                    "m2": {"id": "m2", "url": "https://vavoo.to/play/m2"}}
p.group_lock = threading.Lock()
p._group_state = {"grp:italy:rai 1": {"member": "m2"}}
p._group_pins = {}
p._group_members_cache = {
    ("italy", "rai 1"): [p.channels_by_id["m1"], p.channels_by_id["m2"]]}
url = p.resolve_own("abc", "recA")
check(url == "https://cdn.example/abc.m3u8", "resolved: " + str(url))
check(posted[-1][1].startswith("OWN"), "with its own token: " + posted[-1][1])
check(p.resolve_cache == {}, "nothing cached (the player's address stays)")
url = p.resolve_own("grp:italy:rai 1", "recA")
check(
    url.endswith("/m2.m3u8"),
    "a group: the source it plays from first (%s)" %
    url)
check(p._group_state["grp:italy:rai 1"]["member"]
      == "m2", "group state untouched")
check(p.resolve_own("nope", "recA") is None, "unknown channel: None")
p._request_addon_sig = lambda: None
p._own_sigs.clear()
check(p.resolve_own("abc", "recB") is None,
      "no token to be had: None (the recorder retries)")
vp.decode_response = vp_decode

print("== /file")
TMP = tempfile.mkdtemp(prefix="vavoo_file_")


class FakeProxy(object):
    def is_stopped(self):
        return False


old_proxy = vp.proxy
vp.proxy = FakeProxy()
server = vp.ThreadedHTTPServer(("127.0.0.1", 0), vp.VavooHTTPHandler)
port = server.server_address[1]
threading.Thread(target=server.serve_forever).start()
base = "http://127.0.0.1:%d" % port


def get(path, headers=None, timeout=10):
    from urllib.request import Request, build_opener, ProxyHandler
    from urllib.error import HTTPError
    req = Request(base + path, headers=headers or {})
    try:
        r = build_opener(ProxyHandler({})).open(req, timeout=timeout)
        return r.getcode(), dict(r.headers), r.read()
    except HTTPError as e:
        return e.code, {}, b""


seg = os.path.join(fakehls.SEG_DIR, "seg000.ts")
fakehls.make_segments()
path = os.path.join(TMP, "done.ts")
shutil.copy(seg, path)
size = os.path.getsize(path)
data = open(path, "rb").read()
code, _h, _b = get("/file?id=0000")
check(code == 404, "an unknown id: 404")
code, _h, _b = get("/file?path=" + path)
check(code == 404, "a path is never served")
fid = vr.register_file(path)
code, h, body = get("/file?id=" + fid)
check(code == 200 and body == data and h.get("Content-Length") == str(size),
      "the whole file, with its length")
code, h, body = get("/file?id=%s&offset=%d" % (fid, 188 * 10 + 7))
check(body == data[1880:], "offset rounded down to a packet")
code, h, body = get("/file?id=" + fid, {"Range": "bytes=188-375"})
check(code == 206 and body == data[188:376] and h.get(
    "Content-Range") == "bytes 188-375/%d" % size, "Range: %s" % h.get("Content-Range"))
code, h, body = get("/file?id=%s&offset=376" % fid, {"Range": "bytes=188-"})
check(code == 206 and body == data[564:], "Range counts from the offset")
code, h, body = get("/file?id=%s&offset=%d" % (fid, size + 188))
check(code == 416, "past the end: 416")


class GrowingRecorder(object):
    running = True


grow = os.path.join(TMP, "grow.ts")
open(grow, "wb").close()
rec = GrowingRecorder()
gid = vr.register_file(grow, rec)
result = {}


def reader():
    result["r"] = get("/file?id=%s&follow=1" % gid, timeout=30)


t = threading.Thread(target=reader)
t.start()
for i in range(0, len(data), 18800):
    with open(grow, "ab") as f:
        f.write(data[i:i + 18800])
    time.sleep(0.15)
time.sleep(0.5)
check(t.is_alive(), "follow: still open while recording")
rec.running = False
t.join(10)
code, h, body = result["r"]
check(code == 200 and body == data and "Content-Length" not in h,
      "follow: every byte as it came, then the end (%d bytes)" % len(body))
out = os.path.join(TMP, "followed.ts")
open(out, "wb").write(body)
check(fakehls.probe_duration(out) > 1.5, "what came plays (ffprobe)")
code, h, body = get("/file?id=%s&follow=1" % gid)
check(code == 200 and h.get("Content-Length") == str(len(data)),
      "follow on a finished one: the plain file")

server.shutdown()
vp.proxy = old_proxy
shutil.rmtree(TMP, ignore_errors=True)
finish()
