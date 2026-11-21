# -*- coding: utf-8 -*-
"""vavoo_record.py against a fake live channel (fakehls.py) and the
real ffmpeg / ffprobe of this machine."""
from __future__ import print_function
import json
import os
import shutil
import subprocess
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


# quicker for the tests
vr.STALL_SECONDS = 4
vr.NO_ADDRESS_DELAY = 0.2
vr.RETRY_DELAY = 0.2
vr.SPACE_EVERY = 0.5
vr.INFO_EVERY = 1
ENV = fakehls.no_proxy_env()
for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(key, None)
os.environ["no_proxy"] = "127.0.0.1,localhost"

TMP = tempfile.mkdtemp(prefix="vavoo_rec_")
LOG = os.path.join(TMP, "ffmpeg.log")
channel = fakehls.FakeChannel()

print("== finding ffmpeg, naming files")
check(vr.find_ffmpeg() is not None, "ffmpeg found")
start = time.mktime((2026, 11, 18, 20, 0, 0, 0, 0, -1))
p1 = vr.new_path(TMP, "RAI 1", "Il Commissario: Montalbano?", start)
check(os.path.basename(p1) == "20261118 2000 - RAI 1 - Il Commissario Montalbano.ts",
      "Enigma2-style name: " + os.path.basename(p1))
open(p1, "wb").close()
p2 = vr.new_path(TMP, "RAI 1", "Il Commissario: Montalbano?", start)
check(p2.endswith("Montalbano_2.ts"), "a second one gets _2")
os.remove(p1)
p3 = vr.new_path(TMP, "RAI 1", "RAI 1", start)
check(os.path.basename(p3) == "20261118 2000 - RAI 1.ts", "title = channel: once")
check(vr.free_bytes(os.path.join(TMP, "not", "there")) > 0, "free space of a folder to be made")

print("== playlists")
final, text = vr.fetch_playlist(channel.url(path="/redirect"))
check(final.endswith("/master.m3u8?tok=0"), "redirect followed: " + final)
check("#EXT-X-STREAM-INF" in text, "master read")
picked = vr.pick_variant(final, text)
check(picked[0] == 1 and picked[1].endswith("live_hi.m3u8?tok=0") and not picked[2],
      "highest bandwidth picked: %r" % (picked,))
address, maps = vr.input_args(channel.url())
check(address.endswith("live_hi.m3u8?tok=0") and maps == ["-map", "0:v?", "-map", "0:a?"],
      "ffmpeg gets the variant itself")
sep = fakehls.FakeChannel(separate_audio=True)
address, maps = vr.input_args(sep.url())
check(address.endswith("master.m3u8?tok=0") and maps == ["-map", "0:p:1:v?", "-map", "0:p:1:a?"],
      "separate sound: the master, program 1 mapped (%s)" % maps)
seg = os.path.join(fakehls.SEG_DIR, "seg003.ts")
with open(seg, "rb") as f:
    data = bytearray(f.read())
found = vr.first_pts(data)
check(found is not None and found[1] % 188 == 0, "first video PTS found at a packet: %r" % (found,))


def record(source, **kw):
    path = vr.new_path(TMP, kw.pop("name", "Test"), kw.pop("title", "Show"))
    ended = []
    info = {"name": "Test", "title": "Show", "url": "/vavoo?channel=abc",
            "start": time.time(), "sref": "4097:0:1:0:0:0:0:0:0:0::Test",
            "country": "Italy"}
    rec = vr.Recorder(source, path, info=kw.pop("info", info), log_path=LOG,
                      env=ENV, on_end=ended.append, **kw)
    return rec, ended


print("== a recording that stops at its time")
rec, ended = record(lambda force: channel.url(), stop_at=time.time() + 9)
check(rec.start(), "started")
check(vr.file_entry(rec.file_id)[1] is rec, "registered for /file")
rec.join(30)
check(ended == [rec] and rec.finished and not rec.running, "ended, on_end called")
check(rec.failure is None, "no failure: %r" % rec.failure)
size = os.path.getsize(rec.path)
check(size > 0 and size % 188 == 0 and size == rec.bytes, "whole TS packets (%d bytes)" % size)
duration = fakehls.probe_duration(rec.path)
check(abs(duration - rec.duration) < 2.5 and duration > 6,
      "own duration %.1f s ~ ffprobe %.1f s" % (rec.duration, duration))
check(fakehls.probe_streams(rec.path) == ["audio", "video"], "picture and sound")
check(all(o % 188 == 0 for o in rec._offsets), "index offsets at packets")
check(rec._times == sorted(rec._times) and len(rec._times) >= 3,
      "index in order (%d entries)" % len(rec._times))
off = rec.offset_for(4)
check(0 < off < size, "offset_for(4 s) = %d" % off)
check(abs(rec.time_at(off) - 4) <= 2.5, "time_at(offset) ~ 4 s (%.1f)" % rec.time_at(off))
tail = os.path.join(TMP, "tail.ts")
with open(rec.path, "rb") as f, open(tail, "wb") as g:
    f.seek(off)
    g.write(f.read())
check(abs(fakehls.probe_duration(tail) - (duration - rec.time_at(off))) < 3,
      "the part from that offset plays (%.1f s)" % fakehls.probe_duration(tail))
info = vr.read_info(rec.path)
check(info["format"] == "vavoo_recording" and info["finished"] and info["country"] == "Italy"
      and info["duration"] >= 6 and info["bytes"] == size, "record written: %s" % sorted(info))
with open(rec.path + ".meta", "rb") as f:
    meta = f.read().decode("utf-8").split("\n")
check(meta[0] == "4097:0:1:0:0:0:0:0:0:0::Test" and meta[1] == "Show"
      and int(meta[5]) > 6 * 90000 and int(meta[6]) == size, "Enigma2 .meta: %r" % meta[:7])
check(any("live_hi" in r for r in channel.requests) and
      not any("live_lo" in r for r in channel.requests), "only the chosen variant downloaded")
first_path = rec.path

print("== an address that runs out: resolved again, same file")
calls = []


def renewing(force):
    calls.append(force)
    if force:
        return channel.url(tok=len(calls))
    return channel.url(tok="old")


rec, ended = record(renewing, stop_at=time.time() + 16, name="Renew")
rec.start()
time.sleep(5)
first_bytes = rec.bytes
channel.bad.add("old")
rec.join(40)
check(first_bytes > 0, "data before the cut (%d)" % first_bytes)
check(calls[0] is False and True in calls, "a fresh address asked (force): %r" % calls)
check(rec.bytes > first_bytes and rec.failure is None,
      "went on after the cut (%d bytes)" % rec.bytes)
check(os.path.getsize(rec.path) % 188 == 0, "still whole packets")
check(fakehls.probe_duration(rec.path) > 3, "file still plays")
check(rec._times == sorted(rec._times), "time goes on across the cut")

print("== giving up")
rec, ended = record(lambda force: None, name="None1")
rec.start()
rec.join(20)
check(rec.failure == "no stream address" and ended, "no address 6 times: gave up")
channel.bad.add("dead")
rec, ended = record(lambda force: channel.url(tok="dead"), name="Dead")
rec.start()
rec.join(40)
check(rec.failure == "the stream keeps failing", "refused 6 times: gave up (%r)" % rec.failure)

print("== maximum length, disk full, stop()")
rec, ended = record(lambda force: channel.url(), max_seconds=5, name="Max")
rec.start()
rec.join(30)
check(rec.failure is None and 5 <= rec.duration < 9, "stopped at its length (%.1f s)" % rec.duration)
rec, ended = record(lambda force: channel.url(), name="Full",
                    space=lambda path: vr.STOP_FREE - 1)
rec.start()
rec.join(20)
check(rec.failure == "no space left", "nearly full disk: stopped")
rec, ended = record(lambda force: channel.url(), name="Stop")
rec.start()
time.sleep(4)
t = time.time()
rec.stop()
check(time.time() - t < 0.5, "stop() does not wait")
rec.join(10)
check(rec.finished and rec.bytes > 0, "stopped by hand, kept")
none = vr.Recorder(lambda f: None, os.path.join(TMP, "x.ts"))
none.ffmpeg = None
check(none.start() is False and none.failure == "no ffmpeg", "no ffmpeg: says so")

print("== a pause buffer")
buf = vr.Recorder(lambda force: channel.url(), vr.shift_path(TMP), max_seconds=vr.SHIFT_MAX,
                  log_path=LOG, env=ENV, tag="Pause")
buf.start()
time.sleep(5)
check(os.path.basename(buf.path).startswith("vavoo_pause_") and buf.bytes > 0, "buffer growing")
check(not os.path.exists(buf.path + ".vavoo.json"), "no record beside a buffer")
fid = buf.file_id
buf.discard()
buf.join(10)
time.sleep(0.5)
check(vr.file_entry(fid) is None and not os.path.exists(buf.path), "discarded: file gone")
open(vr.shift_path(TMP), "wb").close()
check(vr.clean_shift_files(TMP) == 1, "a buffer left over is deleted")

print("== listing, deleting")
recs = vr.list_recordings(TMP)
names = [os.path.basename(r["path"]) for r in recs]
check(len(recs) >= 5 and recs == sorted(recs, key=lambda r: r["start"], reverse=True),
      "listed, newest first (%d)" % len(recs))
check(all(r["bytes"] == os.path.getsize(r["path"]) for r in recs), "sizes")
orphan = os.path.join(TMP, "20261118 2100 - Gone.ts")
with open(orphan + ".vavoo.json", "w") as f:
    json.dump({"format": "vavoo_recording", "name": "Gone", "start": 1}, f)
old = time.time() - 3600
os.utime(orphan + ".vavoo.json", (old, old))
vr.list_recordings(TMP, active=[])
check(not os.path.exists(orphan + ".vavoo.json"), "record of a deleted .ts removed")
with open(orphan + ".vavoo.json", "w") as f:
    f.write("{")
open(orphan, "wb").close()
r = [x for x in vr.list_recordings(TMP) if x["path"] == orphan][0]
check(r["name"] == "Gone" and r["start"] > 1e9, "damaged record: from its name (%s)" % r["name"])
check(vr.delete_recording(first_path) and not os.path.exists(first_path + ".meta")
      and not os.path.exists(first_path + ".vavoo.json"), "deleted with its companions")
fid = vr.register_file(orphan)
check(vr.register_file(orphan) == fid and len(fid) == 24, "one id per file")
vr.delete_recording(orphan)
check(vr.file_entry(fid) is None, "deleting unregisters")

channel.close()
sep.close()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d checks, %d failed" % (STATE["checks"], STATE["fails"]))
sys.exit(1 if STATE["fails"] else 0)
