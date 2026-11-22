# -*- coding: utf-8 -*-
"""A fake live channel for the recording tests: 2-second H.264/AAC
segments made once with ffmpeg, served as a live HLS playlist that
grows with the clock (a sliding window of 5), behind a master playlist
with two variants. Addresses carry ?tok=<n>; a token put in `bad`
gets 403 from then on (an address that ran out)."""
from __future__ import print_function
import os
import subprocess
import tempfile
import threading
import time

try:
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn
    from urllib.parse import urlparse, parse_qs
except ImportError:
    from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
    from SocketServer import ThreadingMixIn
    from urlparse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
# (made once per machine, outside the repository)
SEG_DIR = os.path.join(tempfile.gettempdir(), "vavoo_test_hls")
SEG_SECONDS = 2
SEG_COUNT = 60
WINDOW = 5


def make_segments():
    if os.path.exists(os.path.join(SEG_DIR, "seg%03d.ts" % (SEG_COUNT - 1))):
        return
    if not os.path.isdir(SEG_DIR):
        os.makedirs(SEG_DIR)
    subprocess.check_call([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
        "-t", str(SEG_SECONDS * SEG_COUNT),
        "-c:v", "libx264", "-preset", "ultrafast", "-g", "50",
        "-keyint_min", "50", "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "64k",
        "-f", "hls", "-hls_time", str(SEG_SECONDS), "-hls_list_size", "0",
        "-hls_segment_filename", os.path.join(SEG_DIR, "seg%03d.ts"),
        os.path.join(SEG_DIR, "all.m3u8")])


class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class FakeChannel(object):
    def __init__(self, separate_audio=False):
        make_segments()
        self.t0 = time.time() - WINDOW * SEG_SECONDS
        self.bad = set()
        self.requests = []
        self.separate_audio = separate_audio
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                owner.requests.append(self.path)
                parsed = urlparse(self.path)
                tok = (parse_qs(parsed.query).get("tok") or ["0"])[0]
                if tok in owner.bad:
                    self.send_error(403)
                    return
                if parsed.path == "/master.m3u8":
                    body = owner.master(tok)
                    return self._send(body, "application/vnd.apple.mpegurl")
                if parsed.path in ("/live_hi.m3u8", "/live_lo.m3u8"):
                    return self._send(owner.live(tok),
                                      "application/vnd.apple.mpegurl")
                if parsed.path.startswith("/seg/"):
                    name = os.path.basename(parsed.path)
                    path = os.path.join(SEG_DIR, name)
                    if not os.path.isfile(path):
                        self.send_error(404)
                        return
                    with open(path, "rb") as f:
                        return self._send(f.read(), "video/mp2t")
                if parsed.path in ("/redirect", "/vavoo"):
                    self.send_response(302)
                    self.send_header("Location", "/master.m3u8?tok=" + tok)
                    self.end_headers()
                    return
                self.send_error(404)

            def _send(self, body, ctype):
                if not isinstance(body, bytes):
                    body = body.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = _Server(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        thread = threading.Thread(target=self.server.serve_forever)
        thread.daemon = True
        thread.start()

    def url(self, tok=0, path="/master.m3u8"):
        return "http://127.0.0.1:%d%s?tok=%s" % (self.port, path, tok)

    def master(self, tok):
        lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
        audio = ""
        if self.separate_audio:
            lines.append('#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",NAME="en",'
                         'DEFAULT=YES,URI="live_lo.m3u8?tok=%s"' % tok)
            audio = ',AUDIO="aud"'
        lines += ["#EXT-X-STREAM-INF:BANDWIDTH=500000,RESOLUTION=320x240" +
                  audio, "live_lo.m3u8?tok=%s" %
                  tok, "#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=320x240" +
                  audio, "live_hi.m3u8?tok=%s" %
                  tok]
        return "\n".join(lines) + "\n"

    def live(self, tok):
        now_seq = int((time.time() - self.t0) / SEG_SECONDS)
        last = min(now_seq, SEG_COUNT - 1)
        first = max(0, last - WINDOW + 1)
        lines = ["#EXTM3U", "#EXT-X-VERSION:3",
                 "#EXT-X-TARGETDURATION:%d" % SEG_SECONDS,
                 "#EXT-X-MEDIA-SEQUENCE:%d" % first]
        for seq in range(first, last + 1):
            lines.append("#EXTINF:%.3f," % SEG_SECONDS)
            lines.append("seg/seg%03d.ts?tok=%s" % (seq, tok))
        return "\n".join(lines) + "\n"

    def close(self):
        self.server.shutdown()


def no_proxy_env():
    env = dict(os.environ)
    for key in list(env):
        if key.lower() in ("http_proxy", "https_proxy", "all_proxy"):
            env.pop(key)
    env["no_proxy"] = "127.0.0.1,localhost"
    return env


def probe_duration(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1", path])
    try:
        return float(out.decode().strip())
    except ValueError:
        return 0.0


def probe_streams(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
        "-of", "csv=p=0", path])
    return sorted(set(out.decode().split()))
