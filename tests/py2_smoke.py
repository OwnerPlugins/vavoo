# -*- coding: utf-8 -*-
"""Python 2.7 (as many boxes still run): the plugin's Enigma2-free
modules - lists and data (vavoo_store), recordings (vavoo_record), the
themes (vavoo_theme), name matching (epg_name_utils) - with accented
names as UTF-8 bytes and as unicode, broken files, and a real recording
(ffmpeg) of a fake live channel served by another process."""
from __future__ import absolute_import, print_function
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

PLUGIN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "usr", "lib", "enigma2", "python", "Plugins", "Extensions", "vavoo")
sys.path.insert(0, PLUGIN_DIR)
import vavoo_store as store      # noqa: E402
import vavoo_record as vr        # noqa: E402
import vavoo_theme as vt         # noqa: E402
import epg_name_utils as en      # noqa: E402

STATE = {"fails": 0, "checks": 0}


def check(cond, what):
    STATE["checks"] += 1
    if not cond:
        STATE["fails"] += 1
        print("  FAIL: " + what)
    else:
        print("  ok:   " + what)


def run(what, fn):
    try:
        return fn()
    except Exception:
        import traceback
        STATE["checks"] += 1
        STATE["fails"] += 1
        print("  FAIL: %s raised:\n%s" % (what, traceback.format_exc()))
        return None


print("Python", sys.version.split()[0])
check(sys.version_info[0] == 2, "this is Python 2")
TMP = tempfile.mkdtemp(prefix="vavoo_py2_")
store.set_paths(TMP, PLUGIN_DIR, os.path.join(TMP, "tiles"))
U = u"Rai Südtirol"
B = U.encode("utf-8")
URL1 = "http://127.0.0.1:4323/vavoo?channel=abc"
URL2 = u"http://127.0.0.1:4323/vavoo?channel=déf"

print("== favourites, folders, order")
run("add (unicode)", lambda: store.add_favourite(U, URL1, u"Italia", "it"))
run("add (UTF-8 bytes)", lambda: store.add_favourite(u"TF1 Séries".encode("utf-8"), URL2, "France", "fr"))
favs = run("load", store.load_favourites) or []
check([f["name"] for f in favs] == [U, u"TF1 Séries"], "names kept, as unicode: %r" % [f["name"] for f in favs])
run("folder", lambda: store.set_folder(URL1, u"Desporto ★"))
check(run("folders", store.folders) == [u"Desporto ★"], "a folder with an accent and a star")
run("rename folder", lambda: store.rename_folder(u"Desporto ★", u"Futebol"))
run("reorder", lambda: store.reorder_favourites([URL2, URL1]))
check([f["url"] for f in store.load_favourites()] == [URL2, URL1], "reordered")
run("repair", lambda: store.repair_favourites(u"Italia", [{"name": U, "url": URL1 + "x"}]))
run("toggle off", lambda: store.toggle_favourite(U, store.load_favourites()[1]["url"]))
check(run("is_favourite", lambda: store.is_favourite(URL2)) is True, "is_favourite")

print("== parental control")
run("set pin", lambda: store.set_pin("1234"))
check(run("check pin", lambda: store.check_pin("1234")) == ("ok", 0) and store.check_pin("0000")[0] == "wrong",
      "PIN checked (salted SHA-256)")
with open(store.parental_file(), "rb") as f:
    saved = f.read()
with open(store.parental_file(), "wb") as f:
    f.write(json.dumps({"pin": "x", "salt": "y", "wrong": "many", "blocks": None,
                        "blocked_until": "later", "boot": "z"}).encode("utf-8"))
check(run("pin wait (broken file)", store.pin_wait) == 0 and
      run("check pin (broken file)", lambda: store.check_pin("1234"))[0] == "wrong",
      "a broken parental file: no pause, the PIN just wrong")
with open(store.parental_file(), "wb") as f:
    f.write(saved)
run("lock countries", lambda: store.set_locked_countries([u"España", "Italy"]))
check(store.needs_pin_for_country(u"España") in (True, False), "a locked country with an accent")
check(store.is_adult("XXX Gold") is True and store.is_adult(U) is False, "adult words")
run("relock", store.relock)

print("== timers")
now = int(time.time())
run("add timer", lambda: store.add_timer(store.KIND_RECORD, URL1, B, u"Telegiornale à sera",
                                         now + 3600, now + 7200, u"Italia", "it"))
run("add reminder", lambda: store.add_timer(store.KIND_REMIND, URL2, U, "Film", now - 10, now + 600))
check(len(run("load timers", store.load_timers) or []) == 2, "two timers")
check(len(run("due", lambda: store.due_timers(now)) or []) == 1, "the reminder is due")
run("next alarm", store.next_alarm)

print("== backup")
path = run("write backup", lambda: store.write_backup({"theme": u"prism", "x": u"é"}, "1.90", [TMP]))
data = run("read backup", lambda: store.read_backup(path)) if path else None
check(isinstance(data, dict) and data.get("format") == store.BACKUP_FORMAT, "written and read back")
if data:
    check(run("restore", lambda: store.restore_backup(data)) is not None, "restored")

print("== broken files")
for content in (b"{oops", b"", b"42", b"null", b'[1, "x", null]',
                b'{"timers": 5, "favourites": "x", "version": "two"}',
                json.dumps({"timers": [{"id": "abc", "kind": "record", "url": "u", "start": "1"}],
                            "favourites": [{"name": 5, "url": None}]}).encode("utf-8")):
    for f in (store.favourites_file(), store.timers_file(), store.hidden_countries_file(),
              store.parental_file(), store.recent_file()):
        with open(f, "wb") as out:
            out.write(content)
    store._timer_cache[0] = None
    for name, fn in (("favourites", store.load_favourites), ("timers", store.load_timers),
                     ("hidden", store.hidden_countries), ("pin", store.has_pin),
                     ("locked", store.locked_countries), ("unlocked", store.is_unlocked)):
        run("%s from %r" % (name, content[:20]), fn)
check(True, "every broken file read without an error")

print("== initials, colours, search, drawn pictures")
check(run("initials", lambda: store.initials(U)) == u"RS", "initials of %r" % U)
run("colour", lambda: store.color_for(B))
items = [U, u"TF1 Séries", "Canale 5"]
found = run("search", lambda: store.search(items, u"sudtirol"))
check(found == [U], "search without the accent finds it: %r" % (found,))
for fn in (lambda: store.tile_path(U, 40), lambda: store.lock_path(24), lambda: store.clock_path(20)):
    p = run("draw", fn)
    check(p and os.path.isfile(p) and open(p, "rb").read(8) == b"\x89PNG\r\n\x1a\n", "a PNG drawn: %s" % p)

print("== recordings: names, records, list")
folder = os.path.join(TMP, u"movie é")
os.makedirs(folder.encode("utf-8"))
p1 = run("new_path", lambda: vr.new_path(folder, U, u"Telegiornale à sera", now - 3600))
check(p1 is not None and u"Südtirol" in (p1 if isinstance(p1, type(u"")) else p1.decode("utf-8")),
      "a file name with the accents: %r" % (p1,))
with open(vr._native(p1), "wb") as f:
    f.write(b"\x47" + b"\x00" * 187)
run("write_info", lambda: vr.write_info(p1, {"format": vr.INFO_FORMAT, "name": U, "title": B,
                                             "start": now - 3600, "duration": 600, "country": u"Italia"}))
info = run("read_info", lambda: vr.read_info(p1))
check(info and info["name"] == U, "the record read back")
run("write_meta", lambda: vr.write_meta(p1, u"4097:0:1::" + U, U, B, now, 600, 188))
p2 = vr.new_path(folder, "Canale 5", "Film", now)
with open(vr._native(p2), "wb") as f:
    f.write(b"\x47" + b"\x00" * 187)
with open(vr._native(p2) + vr.INFO_SUFFIX, "wb") as f:
    f.write(b'{"format": "vavoo_recording", "start": "x", "title": 7, "name": null}')
recs = run("list", lambda: vr.list_recordings(folder)) or []
check(len(recs) == 2 and all(isinstance(r["start"], (int, float, long)) for r in recs),  # noqa: F821
      "listed, a broken record cleaned: %r" % [(r.get("name"), r.get("start")) for r in recs])
fid = run("register", lambda: vr.register_file(p1))
check(fid and vr.file_entry(fid) is not None, "registered for /file")
check(run("delete", lambda: vr.delete_recording(p1)) is True, "deleted with its companions")
check(not os.path.exists(vr._native(p1) + vr.INFO_SUFFIX), "its record too")
check(run("free", lambda: vr.free_bytes(folder)) > 0, "free space")
run("mount", lambda: vr.mount_of(folder))
run("file size limit", lambda: vr.file_size_limit(folder))

print("== a real recording (ffmpeg), Python 2")
server = subprocess.Popen([sys.argv[1], os.path.join(os.path.dirname(os.path.abspath(__file__)), "fakehls_serve.py")],
                          stdout=subprocess.PIPE)
address = server.stdout.readline().strip().decode("ascii")
env = dict(os.environ)
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    env.pop(key, None)
env["no_proxy"] = "127.0.0.1,localhost"
vr.STALL_SECONDS = 4
vr.RETRY_DELAY = 0.2
rec_path = vr.new_path(folder, U, u"Live é", time.time())
ended = []
rec = vr.Recorder(lambda force: address, rec_path, max_seconds=6, env=env, on_end=ended.append,
                  info={"format": vr.INFO_FORMAT, "name": U, "title": u"Live é", "start": time.time()})
check(rec.start(), "started")
rec.join(40)
size = os.path.getsize(vr._native(rec_path))
check(ended and rec.failure is None and size > 0 and size % 188 == 0,
      "recorded %d bytes, whole packets, ended cleanly (%r)" % (size, rec.failure))
check(rec.duration > 3 and rec.offset_for(2.0) % 188 == 0 and rec.time_at(rec.offset_for(2.0)) <= 2.5,
      "the seconds -> bytes index (%.1f s)" % rec.duration)
check(vr.read_info(rec_path)["name"] == U, "its record, with the accent")
server.terminate()

print("== the themes, every screen, every resolution")
count = 0
for theme in ("prism", "halo", "orbit"):
    for large in (False, True):
        for width in (1280, 1920, 2560):
            for kind, builder in sorted(vt.BUILDERS.items()):
                kw = {"base_dir": PLUGIN_DIR}
                if kind == "log":
                    text = run(kind, lambda: builder(theme, large, width, u"Log é", **kw))
                else:
                    text = run(kind, lambda: builder(theme, large, width, **kw))
                if text:
                    count += 1
            run("metrics", lambda: vt.list_metrics(theme, large, width, "big"))
    run("assets", lambda: vt.asset_specs(theme))
run("classic player list", lambda: vt.player_list_classic(1920))
run("classic guide", lambda: vt.guide_classic(1920))
check(count == 3 * 2 * 3 * len(vt.BUILDERS), "%d skins built" % count)
import xml.etree.cElementTree as ET
text = vt.BUILDERS["log"]("prism", False, 1920, u"Registo \u00e9", base_dir=PLUGIN_DIR)
check(isinstance(text, str) and ET.fromstring(text) is not None and u"\u00e9".encode("utf-8") in text,
      "a unicode title: a UTF-8 skin Enigma2 (Python 2) can parse")

print("== channel names (EPG matching)")
names = [n for n in dir(en) if not n.startswith("_") and callable(getattr(en, n))]
for n in names:
    fn = getattr(en, n)
    try:
        fn(B)
        fn(U)
    except TypeError:
        pass
    except Exception:
        import traceback
        check(False, "%s(%r) raised:\n%s" % (n, B, traceback.format_exc()))
check(True, "name helpers take UTF-8 bytes and unicode")

shutil.rmtree(TMP, ignore_errors=True)
print("\n%d checks, %d failed" % (STATE["checks"], STATE["fails"]))
sys.exit(1 if STATE["fails"] else 0)
