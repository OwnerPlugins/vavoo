# -*- coding: utf-8 -*-
"""The plugin's files under /etc/enigma2 (and a recording's record)
broken in every likely way - not JSON, the wrong shape, wrong types,
missing fields, an old format, hand edits: nothing that reads them may
raise, and the screens that show them still open."""
from __future__ import print_function
import json
import os
import shutil
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, make, Session, V, run_layout   # noqa: E402
plugin = harness.plugin
store = harness.store
import vavoo.vavoo_record as vr                 # noqa: E402

TMP = tempfile.mkdtemp(prefix="vavoo_bad_")
store.set_paths(TMP, None, os.path.join(TMP, "tiles"))
plugin.vUtils.RECENT_FILE = store.recent_file()
REC = os.path.join(TMP, "movie")
os.makedirs(REC)
plugin.cfg.record_path = V(REC)
vr.on_disk = lambda p: True
plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True

BAD = [
    ("not JSON", b"{oops"),
    ("empty", b""),
    ("binary", b"\x00\xff\xfe\x00"),
    ("a number", b"42"),
    ("null", b"null"),
    ("a string", b'"text"'),
    ("a list of junk", b'[1, "x", null, [], {}]'),
    ("a dict of junk", b'{"a": 1, "favourites": "x", "timers": 5, "version": "two"}'),
    ("entries with wrong types", json.dumps({
        "format": "x", "version": 2,
        "favourites": [{"name": 5, "url": None}, {"name": "A", "url": 7, "folder": []},
                       {"name": u"Rai Südtirol", "url": "http://127.0.0.1:4323/vavoo?channel=a",
                        "country": None, "folder": 3}],
        "timers": [{"id": "abc", "kind": "record", "url": "u", "start": "1"},
                   {"id": 1, "kind": "remind", "url": "u", "start": "soon"},
                   {"id": None, "kind": None, "url": "u", "start": 1, "stop": "x"},
                   {"kind": "record", "url": "u", "start": 1.5e9, "title": 7, "name": None}],
        "countries": "Italy", "hidden": {"x": 1}, "pin": 1234, "salt": None,
        "locked": "Italy", "adult": "yes", "settings": None, "fails": "x", "until": "x",
    }).encode("utf-8")),
    ("old favourites dict", json.dumps({"RAI 1": "http://x/vavoo?channel=1", "x": 5}).encode("utf-8")),
    ("unicode names", json.dumps([{"name": u"TF1 Séries ★", "url": u"http://x/é"}],
                                 ensure_ascii=False).encode("utf-8")),
]

FILES = [
    store.favourites_file(),
    store.recent_file(),
    store.source_prefs_file(),
    store.hidden_countries_file(),
    store.parental_file(),
    store.timers_file()]

READERS = [
    ("load_favourites", lambda: store.load_favourites()),
    ("favourite_urls", lambda: store.favourite_urls()),
    ("is_favourite", lambda: store.is_favourite("http://x/vavoo?channel=1")),
    ("hidden_countries", lambda: store.hidden_countries()),
    ("has_pin", lambda: store.has_pin()),
    ("is_unlocked", lambda: store.is_unlocked()),
    ("locked_countries", lambda: store.locked_countries()),
    ("needs_pin_for_channel", lambda: store.needs_pin_for_channel(u"Rai Süd", "Italy")),
    ("needs_pin_for_settings", lambda: store.needs_pin_for_settings()),
    ("load_timers", lambda: store.load_timers()),
    ("due_timers", lambda: store.due_timers(2e9) if hasattr(store, "due_timers") else None),
    ("load_recent", lambda: plugin.vUtils.load_recent() if hasattr(plugin.vUtils, "load_recent") else None),
    ("get_next_wakeup", lambda: plugin.get_next_wakeup()),
    ("reminder tick", lambda: plugin.REMINDERS.tick()),
]


def recording_files(content):
    """A recording whose record is `content` (and one with no record)."""
    for name in os.listdir(REC):
        os.remove(os.path.join(REC, name))
    path = os.path.join(REC, "20261118 2000 - RAI 1 - Show.ts")
    with open(path, "wb") as f:
        f.write(b"\x47" + b"\x00" * 187)
    with open(path + vr.INFO_SUFFIX, "wb") as f:
        f.write(content)
    other = os.path.join(REC, "20261118 2100 - Canale 5 - Film.ts")
    with open(other, "wb") as f:
        f.write(b"\x47" + b"\x00" * 187)
    with open(other + vr.INFO_SUFFIX, "wb") as f:
        f.write(json.dumps({"format": vr.INFO_FORMAT,
                            "name": None,
                            "title": 5,
                            "start": "x",
                            "duration": "y",
                            "country": []}).encode("utf-8"))


plugin.REMINDERS.session = Session()
plugin._in_standby = lambda: True


def screens():
    s = Session()
    out = []
    for title, build in (
        ("Recordings", lambda: make(
            plugin.VavooRecordings, s)), ("Favourites", lambda: make(
            plugin.VavooFavourites, s)), ("Recently watched", lambda: make(
                plugin.VavooFavourites, s, "recent")), ("Choose countries", lambda: make(
                    plugin.VavooCountries, s, [
                        "Albania", "Italy"])), ("Parental Control", lambda: make(
                            plugin.VavooParental, s, [
                                "Italy", "Albania"]))):
        try:
            scr = build()
            run_layout(scr)
            out.append((title, None))
        except Exception as e:
            out.append(
                (title,
                 "%s: %s\n%s" %
                 (e.__class__.__name__,
                  e,
                  traceback.format_exc(
                      limit=6))))
    return out


for label, content in BAD:
    for path in FILES:
        with open(path, "wb") as f:
            f.write(content)
    recording_files(content)
    store._timer_cache[0] = None if hasattr(store, "_timer_cache") else None
    failed = []
    for name, reader in READERS:
        try:
            reader()
        except Exception as e:
            failed.append(
                "%s: %s: %s\n%s" %
                (name,
                 e.__class__.__name__,
                 e,
                 traceback.format_exc(
                     limit=4)))
    try:
        vr.list_recordings(REC)
    except Exception as e:
        failed.append("list_recordings: %s: %s" % (e.__class__.__name__, e))
    try:
        plugin.vavoo_proxy._load_source_prefs()
    except Exception as e:
        failed.append("source picks: %s: %s" % (e.__class__.__name__, e))
    # a backup file with this content, and one that says it is a backup
    # but holds this junk in every field
    backup = os.path.join(TMP, "VavooStream-backup-x.json")
    with open(backup, "wb") as f:
        f.write(content)
    try:
        data = store.read_backup(backup)
        if data is not None:
            store.restore_backup(data)
        try:
            junk = json.loads(content.decode("utf-8"))
        except Exception:
            junk = content.decode("utf-8", "replace")
        store.restore_backup({"format": store.BACKUP_FORMAT,
                              "favourites": junk,
                              "recent": junk,
                              "source_prefs": junk,
                              "hidden_countries": junk,
                              "timers": junk,
                              "settings": junk})
    except Exception as e:
        failed.append("backup: %s: %s\n%s" %
                      (e.__class__.__name__, e, traceback.format_exc(limit=4)))
    for title, problem in screens():
        if problem:
            failed.append("%s does not open: %s" % (title, problem))
    check(not failed, "%s: read without an error, the screens open%s" % (
        label, "" if not failed else "\n      " + "\n      ".join(failed)))

print("== a record with the wrong types")
recording_files(
    b'{"format": "vavoo_recording", "start": "yesterday", "duration": "long", '
    b'"title": 7, "name": null, "country": ["x"], "url": "u"}')
recs = vr.list_recordings(REC)
check(
    len(recs) == 2 and all(
        isinstance(
            r["start"],
            (int,
             float)) and isinstance(
            r["duration"],
            (int,
             float)) for r in recs),
    "numbers are numbers (from the file name when wrong)")
show = [r for r in recs if r["path"].endswith("Show.ts")][0]
check(
    show["title"] == u"7" and show["name"] == u"RAI 1" and show.get(
        "country",
        u"") == u"",
    "texts are texts; a missing name comes from the file name: %r" %
    ((show["title"],
      show["name"]),
     ))
check(abs(show["start"] -
          __import__("time").mktime((2026, 11, 18, 20, 0, 0, 0, 0, -
                                     1))) < 1, "the start from the file name ('20261118 2000')")
try:
    rp = make(plugin.VavooRecordingPlayer, Session(), show)
    run_layout(rp)
    ok = True
except Exception as e:
    ok = False
    print(traceback.format_exc(limit=5))
check(ok, "the recording player opens on it")

shutil.rmtree(TMP, ignore_errors=True)
finish()
