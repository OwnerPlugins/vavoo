# -*- coding: utf-8 -*-
"""vavoo.log: a line with a non-ASCII character ("✓", "✗", an accented
channel name), as a byte string or as text, never raises - on Python 2
it did, out of every module's print(), and the proxy stopped at its own
"[✓] Ready" line."""
from __future__ import print_function
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish               # noqa: E402
vu = harness.plugin.vUtils
vp = harness.plugin.vavoo_proxy
LOG = os.path.join(harness.DATA, "vavoo.log")
vu.LOG_FILE = LOG

print("== log() and every module's print()")
for what, msg in (("a byte string with ✓", "[✓] Channels: 9818"),
                  ("text with ✗", u"[✗] Critical error"),
                  ("an accented name", u"Canale 5 Más · Télé"),
                  ("plain ASCII", "Ready")):
    try:
        vu.log(msg, area="TEST")
        ok = True
    except Exception as e:
        ok = False
        print("    raised: %r" % e)
    check(ok, "log(): %s" % what)
try:
    vp.print("[✓] Ready")
    vp.print(u"[✓] IP: 127.0.0.1:4323", "and", 5)
    vu.plugin_print("[✗] Server error:", u"é")
    ok = True
except Exception as e:
    ok = False
    print("    raised: %r" % e)
check(ok, "the proxy's print() with ✓ / ✗, several arguments")
text = io.open(LOG, encoding="utf-8").read()
check(
    u"[✓] Channels: 9818" in text and u"Canale 5 Más · Télé" in text and u"[✓] Ready" in text,
    "all in the file, as UTF-8")
check(text.count("\n") >= 7, "one line each (%d)" % text.count("\n"))
finish()
