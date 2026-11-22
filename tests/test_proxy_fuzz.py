# -*- coding: utf-8 -*-
"""The final audit: the real proxy (a fake catalog, no network) given
odd, broken and hostile requests - every one gets an HTTP answer (never
a dropped connection), none a 500 for bad input, and the proxy still
answers afterwards."""
from __future__ import print_function
import os
import socket
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
vp = harness.plugin.vavoo_proxy
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)

p = vp.VavooProxy()
p.channels_by_country = {"italy": [{"id": "1",
                                    "name": u"RAI 1 .b",
                                    "group": u"Italy ➾ Generalisti",
                                    "country": "Italy",
                                    "url": "x1"},
                                   {"id": "2",
                                    "name": u"Canale 5 Más",
                                    "group": u"Italy ➾ Generalisti",
                                    "country": "Italy",
                                    "url": "x2"}]}
p.channels_by_id = dict((c["id"], c) for c in p.channels_by_country["italy"])
p.countries_list = ["Italy"]
p.initialized = True
p.get_local_ip = lambda: "127.0.0.1"
# (no network: a resolve fails at once instead of waiting on a timeout)
p.resolve_channel = lambda *a, **k: None
p.refresh_addon_sig_if_needed = lambda force=False: None
vp.proxy = p
server = vp.ThreadedHTTPServer(("127.0.0.1", 0), vp.VavooHTTPHandler)
threading.Thread(target=server.serve_forever).start()
PORT = server.server_address[1]


def raw(request, timeout=10):
    """The answer's status line to raw bytes, or what went wrong."""
    s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
    try:
        s.sendall(request)
        data = b""
        while b"\r\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        return data.split(b"\r\n", 1)[0].decode("latin-1")
    except Exception as e:
        return "ERROR %s" % e
    finally:
        s.close()


def get(path, method="GET", headers=""):
    line = raw(
        ("%s %s HTTP/1.0\r\nHost: x\r\n%s\r\n" %
         (method, path, headers)).encode(
            "utf-8", "replace"))
    try:
        return int(line.split()[1])
    except Exception:
        return line


CASES = [
    ("/", (404,)), ("/nope", (404,)), ("/vavoo",
                                       (400,)), ("/vavoo?channel=", (400,)),
    ("/vavoo?channel=999", (404, 502, 503)
     ), ("/vavoo?channel=%00", (400, 404, 502, 503)),
    ("/vavoo?channel=" + "a" * 5000, (400, 404, 414, 502, 503)),
    ("/vavoo?channel=%E2%9E%BE", (400, 404, 502, 503)),
    ("/channels", (400,)), ("/channels?country=zz", (200,)
                            ), ("/channels?country=Italy&grouped=abc", (200,)),
    ("/channels?country=It%C3%A1lia", (200,)), ("/group_sources", (400, 404)),
    ("/group_sources?group=grp:italy:nothing", (200, 404)
     ), ("/group_sources?group=bad", (400,)), ("/playlist.m3u", (200, 403)),
    ("/playlist.m3u?country=%00", (200, 403, 404)
     ), ("/catalog", (200,)), ("/countries", (200,)),
    ("/status", (200,)), ("/health", (200,)
                          ), ("/file", (404,)), ("/file?id=zzz", (404,)),
    ("/file?id=../../etc/passwd", (404,)), ("/file?path=/etc/passwd", (404,)),
    ("/stream", (404,)), ("/stream?ref=garbage", (404,)),   # (gone: never worked)
    ("/epg/.xml", (302, 200)), ("/epg/..%2f..%2fetc%2fpasswd.xml", (302,)),
    ("/epg/../../etc/passwd.xml", (302,)),
]
print("== odd and hostile requests: an answer each, never a 500 for bad input")
for path, allowed in CASES:
    status = get(path)
    check(status in allowed, "GET %s -> %s" % (path[:60], status))
    status = get(path, "HEAD")
    check(isinstance(status, int) and status != 500,
          "HEAD %s -> %s" % (path[:60], status))

print("== broken HTTP")
for what, request in [
        ("garbage", b"\x00\x01\x02 garbage\r\n\r\n"),
        ("no version", b"GET /status\r\n\r\n"),
        ("huge header", b"GET /status HTTP/1.0\r\nX: " + b"a" * 70000 + b"\r\n\r\n"),
        ("POST", b"POST /status HTTP/1.0\r\nContent-Length: 3\r\n\r\nabc"),
        ("bad Range", b"GET /file?id=zz HTTP/1.0\r\nRange: bytes=abc-\r\n\r\n")]:
    line = raw(request)
    check(not line.startswith("ERROR") or "reset" in line or "timed out" not in line,
          "%s: answered or closed, no hang (%r)" % (what, line[:60]))
print("== still serving")
check(get("/status") == 200 and get("/health") ==
      200, "/status and /health after all of it")
server.shutdown()
finish()
