# -*- coding: utf-8 -*-
"""A screen that closes while its work goes on (the OpenATV 8.1 crash
logs): Enigma2's Screen is a dict and its doClose() calls self.items(),
then clears the screen's __dict__ - so no attribute may hide a dict
method, and threads / calls that come back afterwards must find the
screen closed (`_closed` read from the class) and touch nothing else."""
from __future__ import print_function
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, V, run_layout   # noqa: E402
plugin = harness.plugin
store = harness.store
plugin.cfg.subcategories = V(False)
plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True
plugin.is_proxy_booting = lambda *a, **k: False


class Nav(object):
    def getCurrentlyPlayingServiceReference(self):
        return None

    def getCurrentService(self):
        return None

    def stopService(self):
        pass

    def playService(self, sref):
        pass


def session():
    s = Session()
    s.nav = Nav()
    s.dialog_stack = []
    s.current_dialog = None
    return s


def attempt(fn, *a):
    try:
        fn(*a)
        return None
    except Exception as e:
        return "%s: %s" % (e.__class__.__name__, e)


print("== the harness closes like Enigma2")


class _Probe(plugin.Screen):
    def __init__(self, session):
        self.onClose = []


probe = _Probe.__new__(_Probe)
probe.onClose = []
probe.items = []
check(attempt(harness.enigma2_close, probe) is not None and "not callable" in attempt(
    harness.enigma2_close, probe), "an attribute named items: the TypeError of the crash log")
probe = _Probe.__new__(_Probe)
probe.onClose = []
probe.thing = 1
harness.enigma2_close(probe)
check(attempt(lambda: probe.thing) is not None, "after the close an attribute is gone (AttributeError)")

print("== every class that uses _closed has it True on the class (read after the close)")
import inspect                                  # noqa: E402
missing = []
for module in harness.ui_modules():
    for name, klass in sorted(vars(module).items()):
        if not inspect.isclass(klass) or klass.__module__ != module.__name__:
            continue
        try:
            text = inspect.getsource(klass)
        except (IOError, TypeError):
            continue
        if "self._closed" in text and getattr(klass, "_closed", None) is not True:
            missing.append("%s.%s" % (module.__name__, name))
check(not missing, "_closed = True on the class (%s)" % ", ".join(missing))

print("== Recordings (OK / EXIT on the main list's row)")
store.add_timer(store.KIND_RECORD, "http://127.0.0.1:4323/vavoo?channel=r1", u"RAI 1",
                u"Film", time.time() + 3600, time.time() + 7200, country=u"Italy")
error = attempt(lambda: make(plugin.VavooRecordings, session()))
check(error is None, "built (%s)" % error)
if error is None:
    scr = make(plugin.VavooRecordings, session())
    run_layout(scr)
    scr.refresh()
    check(not harness.dict_shadows(scr), "no attribute hides a dict method (%s)" % harness.dict_shadows(scr))
    error = attempt(harness.enigma2_close, scr)
    check(error is None, "closed like Enigma2: no 'list' object is not callable (%s)" % error)
    check(attempt(scr._tick) is None, "its refresh timer firing late: nothing done, no error")

print("== Parental Control")
error = attempt(lambda: make(plugin.VavooParental, session(), ["Italy", "Albania"]))
check(error is None, "built (%s)" % error)
if error is None:
    scr = make(plugin.VavooParental, session(), ["Italy", "Albania"])
    run_layout(scr)
    scr.refresh()
    check(not harness.dict_shadows(scr), "no attribute hides a dict method (%s)" % harness.dict_shadows(scr))
    error = attempt(harness.enigma2_close, scr)
    check(error is None, "closed like Enigma2 (%s)" % error)

    def parental():
        try:
            return open(store.parental_file(), "rb").read()
        except IOError:
            return None
    before = parental()
    error = attempt(scr._new_pin, "1234")
    check(error is None and parental() == before,
          "a PIN typed after it closed: nothing saved, no error (%s)" % error)

print("== a country's list closed while its logos download (the vv-logos error)")
plugin.cfg.logos = V(True)
CHANNELS = [{"name": u"Channel %d" % i, "url": "http://127.0.0.1:4323/vavoo?channel=c%d" % i,
             "logo": "http://logos.invalid/%d.png" % i, "category": u"Generale"}
            for i in range(30)]
pending = harness.Pending().hold()
scr = make(plugin.vavoo, session(), "Italy", None)
run_layout(scr)
pending.clear()
scr._build_channel_list(CHANNELS)
check(len(pending.threads) >= 1, "the logo download is a thread (%d held)" % len(pending.threads))
downloads = []


def fake_download(logo, *a, **k):
    downloads.append(logo)
    if len(downloads) == 23:
        # the user leaves the list in the middle of the second batch
        harness.own_close(scr)
        harness.enigma2_close(scr)
    return True, "/tmp/none.png"


real_download = plugin.download_picon_online
plugin.download_picon_online = fake_download
failures = pending.run()
plugin.download_picon_online = real_download
pending.release()
for failure in failures:
    print("-" * 60)
    print(failure)
check(not failures, "the thread and the calls it left: no exception (%d)" % len(failures))
check(len(downloads) == 23, "it stopped at the close (%d downloads, not 30)" % len(downloads))

finish()
