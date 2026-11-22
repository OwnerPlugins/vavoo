# -*- coding: utf-8 -*-
"""MENU → Factory reset: every data file, the Vavoo bouquets, the logos,
the settings back to their defaults and the welcome again - the
recordings, the backups and the statistics choice kept. Not while a
recording runs; the PIN first when there is one."""
from __future__ import print_function
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, V   # noqa: E402
plugin = harness.plugin
store = harness.store
import vavoo.bouquet_manager as bm              # noqa: E402
import vavoo.vUtils as vu                       # noqa: E402

TMP = tempfile.mkdtemp(prefix="vavoo_reset_")
DATA = store.DATA_DIR


def touch(path, text="x"):
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w") as f:
        f.write(text)
    return path


class Setting(object):
    """A setting with a default (Components.config)."""
    def __init__(self, value, default):
        self.value, self.default = value, default
        self.saved = 0

    def save(self):
        self.saved += 1


class Nav(object):
    def getCurrentlyPlayingServiceReference(self):
        return None

    def stopService(self):
        pass

    def playService(self, sref):
        pass


def session():
    s = Session()
    s.nav = Nav()
    s.dialog_stack = []
    return s


# ---- what is there before
data_files = [touch(os.path.join(DATA, name)) for name in store.RESET_FILES]
old_plugin = os.path.join(TMP, "plugin")
store.set_paths(None, old_plugin)
old_files = [touch(os.path.join(old_plugin, name)) for name in store.RESET_OLD_PLUGIN_FILES]
backup = touch(os.path.join(DATA, "VavooStream-backup-20261122-1000.json"), "{}")
recording = touch(os.path.join(TMP, "movie", "RAI 1 - Film.ts"))
recording_record = touch(recording + ".vavoo.json", "{}")
stats_off = touch(os.path.join(DATA, "disable_vavoo_stats"))
other_e2 = touch(os.path.join(DATA, "settings"))           # Enigma2's own

e2 = os.path.join(TMP, "e2")
bouquets = [touch(os.path.join(e2, "userbouquet.vavoo_italy.tv")),
            touch(os.path.join(e2, "userbouquet.vavoo_italy_sport.tv"))]
other_bouquet = touch(os.path.join(e2, "userbouquet.favourites.tv"))
touch(os.path.join(e2, "bouquets.tv"),
      '#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.favourites.tv" ORDER BY bouquet\n'
      '#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "userbouquet.vavoo_italy.tv" ORDER BY bouquet\n')
bm.ENIGMA_PATH = e2
bm.update_epg_sources = lambda *a, **k: None    # (never /etc/epgimport from a test)

ram_logos = touch(os.path.join(TMP, "picons", "a.png"))
disk = os.path.join(TMP, "usb")
disk_logos = touch(os.path.join(disk, ".vavoo_logos", "b.png"))
disk_other = touch(os.path.join(disk, "keep", "mine.txt"))
tiles = touch(os.path.join(store.TILE_DIR, "t.png"))
harness.patch("PICON_CACHE_DIR", os.path.dirname(ram_logos))
harness.patch("media_mounts", lambda network=False: [disk])
harness.patch("recordings_folder", lambda: os.path.join(TMP, "movie"))

settings = {
    "theme": Setting("classic", "prism"),
    "text_size": Setting("large", "normal"),
    "welcome_done": Setting(True, False),
    "countries_asked": Setting(True, False),
    "stats_enabled": Setting(False, True),
    "back": Setting("blue", "oktus"),
}
settings["back"].getValue = lambda: settings["back"].value
real_settings = {}
for name, element in settings.items():
    real_settings[name] = getattr(plugin.cfg, name, None)
    setattr(plugin.cfg, name, element)
store.set_pin("1357")
store.relock()          # (set_pin() opens it for 15 minutes)
store.set_hidden_countries(["Albania"])

calls = {"proxy": [], "main": []}
harness.patch("restart_proxy_in_background", lambda *a, **k: calls["proxy"].append(k))
harness.patch("main", lambda s, **k: calls["main"].append(s))
plugin.RECORDINGS.running = lambda: []

print("== the PIN first, then a Yes / No (No by default)")
done = []
s = session()
plugin.ask_factory_reset(s, None, lambda: done.append(1))
opened = [cls.__name__ if hasattr(cls, "__name__") else str(cls) for cls, a, k, cb in s.opened]
check(opened and "VavooPin" in opened[-1], "a PIN is set: the PIN pad (%s)" % opened)
pin_cb = s.opened[-1][3]
pin_cb(None)
check(len(s.opened) == 1 and os.path.isfile(data_files[0]), "PIN pad cancelled: nothing asked, nothing deleted")
store.unlock()
s = session()
plugin.ask_factory_reset(s, None, lambda: done.append(1))
box = s.opened[-1] if s.opened else None
check(box is not None and box[2].get("default") is False and "recordings" in str(box[1][0]),
      "entered: the question, No by default, it says the recordings stay")
box[3](False)
check(os.path.isfile(data_files[0]) and not done, "No: nothing deleted")

print("== not while a recording runs")
plugin.RECORDINGS.running = lambda: [object()]
del harness.NOTES[:]
s = session()
plugin.ask_factory_reset(s, None, lambda: done.append(1))
check(not s.opened and any("recording" in n for n in harness.NOTES), "refused, said why (%s)" % harness.NOTES)
plugin.RECORDINGS.running = lambda: []

print("== Yes: all of it")
pending = harness.Pending().hold()
s = session()
plugin.ask_factory_reset(s, None, lambda: done.append(1))
s.opened[-1][3](True)
failures = pending.run()
pending.release()
for failure in failures:
    print(failure)
check(not failures, "the reset's thread and its call back: no error")
check(done == [1], "on_done called once")
left = [p for p in data_files + old_files if os.path.exists(p)]
check(not left, "every data file deleted (%s)" % left)
check(all(not os.path.exists(b) for b in bouquets) and os.path.isfile(other_bouquet),
      "the Vavoo bouquets gone, the user's own kept")
main_list = open(os.path.join(e2, "bouquets.tv")).read()
check(".vavoo_" not in main_list and "favourites" in main_list, "bouquets.tv: only the Vavoo lines removed")
check(not os.path.exists(os.path.dirname(ram_logos)) and not os.path.exists(os.path.dirname(disk_logos)),
      "the logos (RAM and the disk's .vavoo_logos) deleted")
check(os.path.isfile(disk_other), "nothing else on the disk touched")
check(not os.path.exists(tiles), "the initials tiles deleted")
check(all(os.path.isfile(p) for p in (backup, recording, recording_record, stats_off, other_e2)),
      "kept: the backup, the recording and its record, the statistics choice, Enigma2's files")
check(settings["theme"].value == "prism" and settings["text_size"].value == "normal",
      "the settings back to their defaults")
check(settings["welcome_done"].value is False and settings["countries_asked"].value is False,
      "welcome_done / countries_asked back to False")
check(settings["stats_enabled"].value is False, "the statistics choice kept (stays off)")
check(harness.SKIN_BACKS and harness.SKIN_BACKS[-1] == "oktus.png",
      "the default background put back (%s)" % harness.SKIN_BACKS[-1:])
check(not store.has_pin() and not store.hidden_countries(), "no PIN, no hidden country")
check(calls["proxy"] and calls["proxy"][-1].get("fresh") is True, "the proxy restarted fresh (a new catalog)")
check(plugin.welcome_needed(), "the welcome runs again")

print("== from the main list: it closes and opens again")
pending = harness.Pending().hold()
scr = make(plugin.MainVavoo, session())
del harness.MENUS[:]
scr.open_menu()
entries = harness.MENUS[-1][1] if harness.MENUS else []
keys = [key for _label, key in entries]
check("factory_reset" in keys and keys.index("factory_reset") == len(keys) - 2,
      "MENU has Factory reset, before About (%s)" % keys)
scr._after_factory_reset()
check(scr.closed_with, "the main list closed")
harness.enigma2_close(scr)
failures = pending.run()
pending.release()
check(not failures and len(calls["main"]) == 1, "the plugin opened again after the close (%s)" % failures)

for name, element in real_settings.items():
    if element is not None:
        setattr(plugin.cfg, name, element)
finish()
