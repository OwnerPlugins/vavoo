# -*- coding: utf-8 -*-
"""The faster paths: the next channel resolved ahead of CH+ / CH-
(VavooProxy.prefetch(), Geil only), the logos on a flash disk instead
of /tmp (ui_record.logo_folder()), the favourites' guides loaded ahead
(vUtils.preload_epg_guides())."""
from __future__ import print_function
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session  # noqa: E402
plugin = harness.plugin
vp = plugin.vavoo_proxy
vu = plugin.vUtils
vr = plugin.vavoo_record
TMP = tempfile.mkdtemp(prefix="vavoo_speed_")

print("== prefetch(): the next channel's address ready, nothing else touched")
p = vp.VavooProxy()
channels = [{"id": u"1", "name": u"Canale 5", "url": u"http://geil/c5", "country": u"Italy"},
            {"id": u"2", "name": u"RAI 1 .b", "url": u"http://geil/r1b", "country": u"Italy"},
            {"id": u"3", "name": u"RAI 1 .c", "url": u"http://geil/r1c", "country": u"Italy"}]
for c in channels:
    c.update({"logo": u"", "group": u"Italy", "epg_id": u""})
p._install_catalog(channels, "geil")
asked = []
p.resolve_with_retry = lambda url, max_retries=2: asked.append((url, max_retries)) or "http://stream/" + url
streams = p.active_streams
check(p.prefetch(u"1") is True and asked == [(u"http://geil/c5", 1)], "a channel: resolved once, one try")
p._cache_resolved_url(u"http://geil/c5", "http://stream/c5")
del asked[:]
check(p.prefetch(u"1") is True and not asked, "already in the cache: nothing asked")
group = [k for k, members in p._group_members_cache.items() if len(members) > 1][0]
group_id = vp.GROUP_ID_PREFIX + group[0] + ":" + group[1]
state_before = dict(p._group_state)
check(p.prefetch(group_id) is True and asked and asked[-1][0] == u"http://geil/r1b",
      "a group: its first source (%s)" % (asked[-1:]))
check(p._group_state == state_before and p.active_streams == streams,
      "no group state, no stream count changed")
del asked[:]
check(p.prefetch(u"999") is False and p.prefetch(None) is False and not asked, "unknown / none: nothing")
p.catalog_source = "vavoo"
check(p.prefetch(u"2") is False and not asked, "the Vavoo catalog: never (one stream per token)")
p.catalog_source = "geil"
p._prefetch_lock.acquire()
check(p.prefetch(u"2") is False and not asked, "one at a time: a second one while one runs gives up")
p._prefetch_lock.release()

print("== the player asks for the next one in its direction")


class Nav(object):
    def getCurrentlyPlayingServiceReference(self):
        return None

    def getCurrentService(self):
        return None

    def stopService(self):
        pass

    def playService(self, sref):
        pass


s = Session()
s.nav = Nav()
s.dialog_stack = []
URLS = ["http://127.0.0.1:4323/vavoo?channel=%d" % i for i in (10, 11, 12, 13)]
ps = make(plugin.Playstream2, s, "A", URLS[0], 0, None, [[("Ch %d" % i, u)] for i, u in enumerate(URLS)], "it")
ps.startStream = lambda *a, **k: None
ps.stopStream = lambda *a, **k: None
asked_ids = []


class FakeProxy(object):
    def prefetch(self, channel_id):
        asked_ids.append(channel_id)


real_proxy = vp.proxy
vp.proxy = FakeProxy()


class SyncThread(object):
    def __init__(self, target=None, **k):
        self.target = target
        self.daemon = True

    def start(self):
        self.target()


real_thread = plugin.threading.Thread
plugin.threading.Thread = SyncThread
ps.nextitem()
check(ps.currentindex == 1 and getattr(ps, "_prefetch_dir", None) == 1 and ps._prefetch_timer is not None,
      "CH+: the next one to prepare, in 3 s")
ps._prefetch_next()
check(asked_ids == ["12"], "...the channel after it: %r" % asked_ids)
ps.previousitem()
ps._prefetch_next()
check(ps.currentindex == 0 and asked_ids[-1] == "13", "CH-: the one before (wrapping round): %r" % asked_ids[-1])
ps.zap_to(2)
check(ps._prefetch_dir == 1, "a number / RECALL / the list: counts as +1")
ps._shift_state = "paused"
del asked_ids[:]
ps._prefetch_next()
check(not asked_ids, "behind live (Pause Live TV): nothing")
ps._shift_state = None
plugin.threading.Thread = real_thread
vp.proxy = real_proxy

print("== the logos: a flash disk, never a hard disk, else /tmp")
mounts = os.path.join(TMP, "mounts")
open(mounts, "w").write("/dev/sda1 /media/usb vfat rw 0 0\n/dev/sdb1 /media/hdd ext4 rw 0 0\n"
                        "/dev/mmcblk0p1 /media/mmc ext4 rw 0 0\n//nas/share /media/net cifs rw 0 0\n")
sysb = os.path.join(TMP, "block")
for disk, value in (("sda", "0"), ("sdb", "1"), ("mmcblk0", "0")):
    os.makedirs(os.path.join(sysb, disk, "queue"))
    open(os.path.join(sysb, disk, "queue", "rotational"), "w").write(value + "\n")
check(vr.mount_device("/media/usb", mounts) == "/dev/sda1", "mount_device()")
check(vr.non_rotational("/media/usb", sysb, mounts) is True, "a USB stick: flash")
check(vr.non_rotational("/media/hdd", sysb, mounts) is False, "a hard disk: not")
check(vr.non_rotational("/media/mmc", sysb, mounts) is True, "an SD card (mmcblk0p1 -> mmcblk0): flash")
check(vr.non_rotational("/media/net", sysb, mounts) is False and vr.non_rotational("/nowhere", sysb, mounts) is False,
      "a share, an unknown mount: not")

saved = dict((n, getattr(vr, n)) for n in ("mount_of", "on_disk", "non_rotational", "free_bytes"))
kind = {"/media/usb": "vfat", "/media/hdd": "ext4", "/media/net": "cifs", "/media/mmc": "ext4"}
flash = {"/media/usb": True, "/media/hdd": False, "/media/net": True, "/media/mmc": True}
free = {"/media/usb": 8 * 1024 ** 3, "/media/hdd": 500 * 1024 ** 3, "/media/net": 9 * 1024 ** 4,
        "/media/mmc": 50 * 1024 ** 2}
vr.mount_of = lambda path: ("/media/hdd", "ext4") if path.startswith("/media/hdd") else (path, kind.get(path, ""))
vr.on_disk = lambda path: True
vr.non_rotational = lambda point: flash.get(point, False)
vr.free_bytes = lambda point: free.get(point, 0)
plugin.recordings_folder = lambda: "/media/hdd/movie/"
plugin.media_mounts = lambda network=False: ["/media/hdd", "/media/mmc", "/media/net", "/media/usb"]
plugin.usable_folder = lambda folder, create=True: folder
check(plugin.logo_folder() == "/media/usb/.vavoo_logos",
      "recordings on a hard disk, an SD card too full, a share: the USB stick (%s)" % plugin.logo_folder())
free["/media/usb"] = 10
check(plugin.logo_folder() is None, "no flash disk with room: None (= /tmp)")
plugin.recordings_folder = lambda: "/media/usb/movie/"
free["/media/usb"] = 8 * 1024 ** 3
vr.mount_of = lambda path: ("/media/usb", "vfat") if path.startswith("/media/usb") else (path, kind.get(path, ""))
check(plugin.logo_folder() == "/media/usb/.vavoo_logos", "recordings on the stick: there")
for name, fn in saved.items():
    setattr(vr, name, fn)

folder = os.path.join(TMP, "logos")
os.makedirs(folder)
check(vu.set_picon_cache_dir(folder) == folder and not vu.picon_cache_in_ram(), "set_picon_cache_dir(): the disk")
check(vu.get_picon_cache_path("http://x/logo.png").startswith(folder), "logo paths there")
for i in range(3):
    open(os.path.join(folder, "l%d.png" % i), "wb").write(b"x" * (20 * 1024 * 1024))
check(vu.trim_picon_cache() == 0, "60 MB on the disk: under its 64 MB, nothing deleted")
trims = []
real_trim = vu.trim_picon_cache
vu.trim_picon_cache = lambda *a, **k: trims.append(k)
plugin.MEMORY_WATCH.release()
check(not trims, "low memory: the logos on a disk are left alone (they take no memory)")
vu.set_picon_cache_dir(None)
check(vu.picon_cache_in_ram() and vu.picon_cache_dir() == "/tmp/vavoo_picons", "None: back to /tmp")
plugin.MEMORY_WATCH.release()
check(trims and trims[-1].get("max_bytes") == 4 * 1024 * 1024, "in /tmp: trimmed to 4 MB on low memory")
vu.trim_picon_cache = real_trim
check("set_picon_cache_dir(logo_folder())" in harness.source_of("main"), "main() chooses the folder each opening")

print("== the favourites' guides, loaded ahead")
loads = []


def fake_load(code):
    loads.append(code)
    g = vu.EpgGuide(code, time.time())
    with vu._epg_guide_lock:
        vu._epg_guide_cache[code] = g
    return g


real_load = vu.load_epg_guide
vu.load_epg_guide = fake_load
vu._epg_guide_cache.clear()
vu._epg_guide_failed.clear()
plenty = lambda: {"MemAvailable": 900 * 1024}         # noqa: E731
check(vu.preload_epg_guides(["PT", "it", "fr"], meminfo=plenty) == ["pt", "it"] and loads == ["pt", "it"],
      "two at most: %r" % loads)
check(vu.preload_epg_guides(["pt", "es"], meminfo=plenty) == [],
      "the guides in memory would push one out (keeps a place free): none")
vu._epg_guide_cache.clear()
vu._epg_guide_cache["pt"] = vu.EpgGuide("pt", time.time())
del loads[:]
check(vu.preload_epg_guides(["pt", "it"], meminfo=plenty) == ["it"] and loads == ["it"],
      "one already in memory: skipped")
vu._epg_guide_cache.clear()
vu._epg_guide_failed["it"] = time.time()
del loads[:]
check(vu.preload_epg_guides(["it", "fr"], meminfo=plenty) == ["fr"], "one that failed a moment ago: skipped")
vu._epg_guide_cache.clear()
vu._epg_guide_failed.clear()
check(vu.preload_epg_guides(["it"], meminfo=lambda: {"MemAvailable": 150 * 1024}) == [],
      "under 200 MB available: none")
check(vu.preload_epg_guides(["it"], go_on=lambda: False, meminfo=plenty) == [], "go_on() says no: none")
vu.load_epg_guide = real_load
vu._epg_guide_cache.clear()

store = harness.store
for name, cc in ((u"RAI 1", "it"), (u"SIC", "pt"), (u"RTP 1", "pt"), (u"TF1", "fr")):
    store.add_favourite(name, "http://127.0.0.1:4323/vavoo?channel=" + name, None, cc)
vu.add_recent(u"Das Erste", "http://127.0.0.1:4323/vavoo?channel=de1", "Germany", "de")
time.sleep(0.3)
check(plugin.guide_countries()[:3] == ["pt", "it", "fr"] and "de" in plugin.guide_countries(),
      "favourites' countries, most first, then the recently watched: %r" % plugin.guide_countries())
plugin.cfg.list_epg = harness.V(True)
main = make(plugin.MainVavoo, Session())
main._schedule_guide_preload()
check(getattr(main, "_guide_preload_timer", None) is not None, "the main list schedules it (15 s)")
first = main._guide_preload_timer
main._schedule_guide_preload()
check(main._guide_preload_timer is first, "once per opening")
main._closed = False
plugin.NOW_PLAYING.owner = plugin.NOW_PLAYING.PLAYER
check(main._preload_go_on() is False, "the player open: it stops")
plugin.NOW_PLAYING.owner = None
plugin.ACTIVE["player"] = None          # (the player made above)
check(main._preload_go_on() is True, "else it goes on")
shutil.rmtree(TMP, ignore_errors=True)
finish()
