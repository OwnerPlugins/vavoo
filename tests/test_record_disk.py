# -*- coding: utf-8 -*-
"""The disk going away under a recording (a USB disk pulled out, full,
a file too big): the recorder stops at once, says why, keeps what it
wrote - no new ffmpeg / stream address against a dead disk."""
from __future__ import print_function
import errno
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "usr", "lib", "enigma2", "python", "Plugins", "Extensions", "vavoo")
sys.path.insert(0, PLUGIN_DIR)
sys.path.insert(0, HERE)
import vavoo_record as vr      # noqa: E402
import fakehls                 # noqa: E402

STATE = {"fails": 0, "checks": 0}


def check(cond, what):
    STATE["checks"] += 1
    if not cond:
        STATE["fails"] += 1
        print("  FAIL: " + what)
    else:
        print("  ok:   " + what)


vr.STALL_SECONDS = 4
vr.NO_ADDRESS_DELAY = 0.2
vr.RETRY_DELAY = 0.2
vr.SPACE_EVERY = 0.5
vr.INFO_EVERY = 1
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
ENV = fakehls.no_proxy_env()
TMP = tempfile.mkdtemp(prefix="vavoo_disk_")
channel = fakehls.FakeChannel()
real_open = open


class DyingFile(object):
    """A file that fails once `limit` bytes are in, with `code`."""

    def __init__(self, f, limit, code):
        self.f, self.limit, self.code = f, limit, code
        self.written = 0

    def write(self, data):
        if self.written + len(data) > self.limit:
            raise IOError(self.code, os.strerror(self.code))
        self.written += len(data)
        return self.f.write(data)

    def __getattr__(self, name):
        return getattr(self.f, name)


for code, want in ((errno.EIO, vr.FAILURE_DISK), (errno.ENOSPC, vr.FAILURE_SPACE),
                   (errno.EFBIG, vr.FAILURE_FAT), (errno.EROFS, vr.FAILURE_DISK)):
    name = errno.errorcode[code]
    path = os.path.join(TMP, "rec_%s.ts" % name)
    limit = 188 * 3000

    def fake_open(p, mode="r", *a, **k):
        f = real_open(p, mode, *a, **k)
        if p == path and "a" in mode:
            return DyingFile(f, limit, code)
        return f

    vr.open = fake_open
    addresses = []

    def source(force):
        addresses.append(force)
        return channel.url()

    ended = []
    rec = vr.Recorder(source, path, max_seconds=60, env=ENV, on_end=ended.append)
    started = time.time()
    rec.start()
    rec.join(40)
    took = time.time() - started
    del vr.open
    size = os.path.getsize(path)
    print("== %s" % name)
    check(rec.failure == want, "stopped, and why: %r" % rec.failure)
    check(len(addresses) == 1 and ended, "no new stream address against the dead disk (%d asked)" % len(addresses))
    check(took < 20, "at once (%.1f s)" % took)
    check(0 < size <= limit and size % 188 == 0, "what was written stays, whole packets (%d bytes)" % size)
    check(fakehls.probe_duration(path) > 0.5, "and it plays")

import glob                    # noqa: E402
src = "".join(real_open(name).read() for name in sorted(glob.glob(os.path.join(PLUGIN_DIR, "*.py"))))
check("vavoo_record.FAILURE_DISK" in src and "the disk could not be" in src,
      "the player says it: 'Recording stopped: the disk could not be written (removed?)'")
channel.close()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d checks, %d failed" % (STATE["checks"], STATE["fails"]))
sys.exit(1 if STATE["fails"] else 0)
