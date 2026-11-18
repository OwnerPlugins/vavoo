# -*- coding: utf-8 -*-
"""Recordings, as in the Android app (pQu4k3r/vavoo_android: Recorder,
Recordings, RecordingService): a channel recorded into a .ts file, the
recordings listed and deleted, and the buffer behind "Pause Live TV".

No Enigma2 imports (like vavoo_store.py / vavoo_theme.py): plugin.py
starts the recordings, vavoo_proxy.py serves their files (/file?id=),
and the tests run it off the box against a fake live channel.

Enigma2 itself records only DVB services, and its timeshift is DVB
only too. An internet stream (HLS) is recorded here: ffmpeg copies the
channel (no re-encoding) as MPEG-TS into a pipe, and a thread of ours
writes it out - whole 188-byte TS packets only - so that:
- an address that runs out (Vavoo's do, after a while) is resolved
  again and the recording goes on in the SAME file, as the app's
  Recorder does;
- the file can be played while it is still being written, from any
  point: the thread keeps an index "seconds -> byte" from the time
  stamps it sees go by (offset_for()), and every offset in it is a
  packet boundary.
"""
from __future__ import absolute_import, division, print_function

import binascii
import bisect
import json
import os
import re
import select
import subprocess
import sys
import threading
import time

try:
    from urllib.parse import urljoin, urlparse
    from urllib.request import ProxyHandler, Request, build_opener
except ImportError:  # Python 2
    from urlparse import urljoin, urlparse
    from urllib2 import ProxyHandler, Request, build_opener

PY2 = sys.version_info[0] == 2
if PY2:
    text_type = unicode  # noqa: F821
else:
    text_type = str

# Less than this free where the recording goes: none starts (the app's
# Recordings.MIN_FREE), and one running stops below half of it.
MIN_FREE = 400 * 1048576
STOP_FREE = MIN_FREE // 2
# One started by hand: until stopped, 4 hours at most (the app's); one
# from the guide: until its end (it is given stop_at) and at most this
# much after it; the pause buffer: 2 hours.
MANUAL_MAX = 4 * 3600
TIMER_EXTRA = 600
SHIFT_MAX = 2 * 3600

PACKET = 188
USER_AGENT = "VAVOO/2.6"
INFO_SUFFIX = ".vavoo.json"
INFO_FORMAT = "vavoo_recording"
META_SUFFIX = ".meta"
SHIFT_PREFIX = "vavoo_pause_"
# What Enigma2 keeps beside a recording (deleted with it).
COMPANIONS = (META_SUFFIX, INFO_SUFFIX, ".ap", ".sc", ".cuts")

# The app's Recorder: an address that cannot be had, or a part that
# brought nothing, 6 times in a row - it gives up.
MAX_FAILURES = 6
NO_ADDRESS_DELAY = 5
RETRY_DELAY = 2
# No data from ffmpeg for this long: it is stuck - a new address.
STALL_SECONDS = 30
INFO_EVERY = 30
SPACE_EVERY = 10
KEEP_ALIVE_EVERY = 60
# An index entry for every second of the recording (at most). Every
# block written is looked at (a short scan): the stream arrives in
# bursts of whole segments, so looking only now and then would leave
# one entry per segment.
INDEX_STEP = 1.0
# ffmpeg runs below Enigma2's priority (the video and the menus come
# first; a recording only has to keep up with the stream).
FFMPEG_NICE = 10

FFMPEG_PATHS = ("/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/bin/ffmpeg",
                "/opt/bin/ffmpeg")


_logger = [None]


def set_logger(function):
    """Where the messages go (plugin.py: its vavoo.log printer)."""
    _logger[0] = function


def _log(message):
    message = "[vavoo_record] " + message
    if _logger[0] is not None:
        try:
            _logger[0](message)
            return
        except Exception:
            pass
    print(message)


_prctl = [None]


def name_this_thread(name):
    """Give the running thread a name the system shows ("top -H",
    /proc/<pid>/task/*/comm: "vv-guide", "vv-rec"...), so what loads
    the box can be told apart inside Enigma2's one process. Linux
    only, 15 characters at most; nothing at all where it cannot.
    (Here because this module has no Enigma2 imports: every other
    one can use it.)"""
    if _prctl[0] is False:
        return
    try:
        import ctypes
        if _prctl[0] is None:
            # (the running program's own symbols: libc is in them -
            # no library search, which can start processes)
            _prctl[0] = ctypes.CDLL(None).prctl
        raw = _native(name)
        if not isinstance(raw, bytes):
            raw = raw.encode("ascii", "replace")
        _prctl[0](15, ctypes.c_char_p(raw[:15]), 0, 0, 0)  # PR_SET_NAME
    except Exception:
        _prctl[0] = False


def find_nice():
    """The nice program (busybox has it), or None."""
    for folder in (os.environ.get("PATH") or "").split(os.pathsep) + \
            ["/bin", "/usr/bin", "/sbin"]:
        path = os.path.join(folder, "nice") if folder else ""
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _text(value):
    if value is None:
        return u""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return text_type(value)


def _native(value):
    """A path or name as the os functions want it (Python 2: UTF-8
    bytes - a box's file system encoding is often ASCII)."""
    value = _text(value)
    if PY2:
        return value.encode("utf-8")
    return value


# ------------------------------------------------------------ the box


def find_ffmpeg():
    """The ffmpeg program, or None (a dependency of the plugin, but an
    image may lack it)."""
    seen = []
    for folder in (os.environ.get("PATH") or "").split(os.pathsep):
        if folder:
            seen.append(os.path.join(folder, "ffmpeg"))
    seen.extend(FFMPEG_PATHS)
    for path in seen:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def free_bytes(path):
    """Free space where `path` is (or would be); None when unknown."""
    path = _native(path)
    while path and not os.path.exists(path):
        parent = os.path.dirname(path.rstrip("/"))
        if not parent or parent == path:
            break
        path = parent
    try:
        st = os.statvfs(path or "/")
        return st.f_bavail * st.f_frsize
    except Exception:
        return None


# File systems that are not a disk: the box's memory. (The root file
# system is refused by its mount point: on most boxes it is the
# internal flash, which a stream of several Mbit/s wears out and
# saturates - the whole box then waits on it.)
_RAM_FS = ("tmpfs", "ramfs", "devtmpfs", "rootfs", "proc", "sysfs")


def mount_of(path):
    """(mount point, file system type) of the disk `path` is on (or
    would be on: the nearest existing folder above it)."""
    path = os.path.realpath(_native(path) or "/")
    while path and not os.path.exists(path):
        parent = os.path.dirname(path.rstrip("/"))
        if not parent or parent == path:
            break
        path = parent
    point = path
    while point not in ("", "/") and not os.path.ismount(point):
        point = os.path.dirname(point.rstrip("/")) or "/"
    point = point or "/"
    fstype = ""
    try:
        with open("/proc/mounts") as f:
            for line in f:
                fields = line.split()
                if len(fields) > 2 and \
                        fields[1].replace("\\040", " ") == point:
                    fstype = fields[2]
    except Exception:
        pass
    return point, fstype


def on_disk(path):
    """True when `path` is on a mounted disk (HDD, USB, network share)
    - not the box's internal flash (the root file system) nor its
    memory (/tmp...). Recordings and the pause buffer only go there."""
    point, fstype = mount_of(path)
    return point != "/" and fstype not in _RAM_FS


def _clean(text, limit=50):
    """A name fit for a file name (as Enigma2's own recordings)."""
    text = re.sub(u'[\\x00-\\x1f/\\\\:*?"<>|]+', u" ", _text(text))
    text = re.sub(u"\\s+", u" ", text).strip(u" .")
    return text[:limit].strip(u" .")


def new_path(folder, channel_name, title=None, start=None):
    """A new recording's file, named as Enigma2 names its own:
    "20261118 2000 - RAI 1 - Title.ts" (the title left out when there
    is none or it is the channel's name)."""
    start = time.time() if start is None else start
    parts = [_text(time.strftime("%Y%m%d %H%M", time.localtime(start))),
             _clean(channel_name) or u"Vavoo"]
    if title and _clean(title) and _clean(title) != _clean(channel_name):
        parts.append(_clean(title, 80))
    base = u" - ".join(parts)
    folder = _text(folder)
    path = os.path.join(folder, base + u".ts")
    number = 2
    while os.path.exists(_native(path)) or \
            os.path.exists(_native(path + INFO_SUFFIX)):
        path = os.path.join(folder, u"%s_%d.ts" % (base, number))
        number += 1
    return _native(path)


def shift_path(folder):
    """A pause buffer's file (deleted again when going back to live)."""
    return _native(os.path.join(_text(folder), u"%s%d.ts" % (
        SHIFT_PREFIX, int(time.time() * 1000))))


def clean_shift_files(folder, keep=()):
    """Pause buffers left over (the box was switched off meanwhile)."""
    folder = _native(folder)
    keep = set(_native(path) for path in keep)
    try:
        names = os.listdir(folder)
    except Exception:
        return 0
    removed = 0
    for name in names:
        if name.startswith(SHIFT_PREFIX) and name.endswith(".ts"):
            path = os.path.join(folder, name)
            if path in keep:
                continue
            try:
                os.remove(path)
                removed += 1
            except Exception:
                pass
    return removed


# ------------------------------------------------- what is kept beside


def _write_atomically(path, data):
    temp = path + ".tmp"
    with open(temp, "wb") as f:
        f.write(data)
    os.rename(temp, path)


def write_info(path, info):
    """The recording's own record: channel, country, title, start,
    duration... (atomically: a box switched off while it is written
    must not leave an empty file)."""
    try:
        data = json.dumps(info, ensure_ascii=False, indent=1, sort_keys=True)
        if not isinstance(data, bytes):
            data = data.encode("utf-8")
        _write_atomically(_native(path) + INFO_SUFFIX, data)
        return True
    except Exception as e:
        _log("info not written: {}".format(e))
        return False


def read_info(path):
    try:
        with open(_native(path) + INFO_SUFFIX, "rb") as f:
            info = json.loads(f.read().decode("utf-8"))
        if isinstance(info, dict) and info.get("format") == INFO_FORMAT:
            return info
    except Exception:
        pass
    return None


def write_meta(path, sref, title, description, start, duration=0, size=0):
    """Enigma2's own .meta, so that the box's movie list shows the
    recording with its title (service reference, name, description,
    time, tags, length in 1/90000 s, size)."""
    lines = [_text(sref), _text(title), _text(description),
             u"%d" % int(start or 0), u"",
             u"%d" % int((duration or 0) * 90000),
             u"%d" % int(size or 0)]
    try:
        _write_atomically(_native(path) + META_SUFFIX,
                          (u"\n".join(lines) + u"\n").encode("utf-8"))
        return True
    except Exception as e:
        _log("meta not written: {}".format(e))
        return False


def _from_name(path):
    """A recording without its record: what its file name tells (the
    app's fromFolder)."""
    base = os.path.basename(_text(path))
    if base.endswith(u".ts"):
        base = base[:-3]
    start = None
    match = re.match(u"(\\d{8} \\d{4}) - (.*)$", base)
    name = base
    if match:
        try:
            start = time.mktime(time.strptime(match.group(1), "%Y%m%d %H%M"))
        except Exception:
            start = None
        name = match.group(2)
    parts = name.split(u" - ", 1)
    try:
        mtime = os.path.getmtime(_native(path))
    except Exception:
        mtime = 0
    return {"format": INFO_FORMAT, "name": parts[0],
            "title": parts[1] if len(parts) > 1 else u"",
            "start": start or mtime, "duration": 0}


def list_recordings(folder, active=()):
    """The recordings in `folder` (the ones this plugin made: with
    their .vavoo.json), the newest first, each a dict with "path" and
    "bytes" added. A record whose .ts was deleted (from the box's own
    movie list, say) is deleted too, unless it is being recorded."""
    folder = _native(folder)
    active = set(_native(path) for path in active)
    try:
        names = os.listdir(folder)
    except Exception:
        return []
    now = time.time()
    out = []
    for name in names:
        if not name.endswith(INFO_SUFFIX):
            continue
        info_path = os.path.join(folder, name)
        path = info_path[:-len(INFO_SUFFIX)]
        if not os.path.isfile(path):
            if path not in active:
                try:
                    if now - os.path.getmtime(info_path) > 600:
                        os.remove(info_path)
                except Exception:
                    pass
            continue
        info = read_info(path) or _from_name(path)
        recording = dict(info)
        recording["path"] = path
        try:
            recording["bytes"] = os.path.getsize(path)
        except Exception:
            recording["bytes"] = 0
        recording["recording"] = path in active
        out.append(recording)
    out.sort(key=lambda r: r.get("start") or 0, reverse=True)
    return out


def delete_recording(path):
    """The .ts and what Enigma2 / this plugin keep beside it."""
    path = _native(path)
    unregister_path(path)
    for suffix in ("",) + COMPANIONS:
        try:
            if os.path.exists(path + suffix):
                os.remove(path + suffix)
        except Exception as e:
            _log("not deleted: {} ({})".format(path + suffix, e))
    if path.endswith(".ts"):
        try:
            if os.path.exists(path[:-3] + ".eit"):
                os.remove(path[:-3] + ".eit")
        except Exception:
            pass
    return not os.path.exists(path)


# ------------------------------------- files the proxy may serve (/file)

_files = {}
_files_lock = threading.Lock()


def register_file(path, recorder=None):
    """An id under which vavoo_proxy's /file serves `path` (never a
    path in the address: only what is registered here can be read).
    `recorder`: the Recorder still writing it (served as it grows)."""
    path = _native(path)
    with _files_lock:
        for file_id, entry in _files.items():
            if entry[0] == path:
                _files[file_id] = (path, recorder or entry[1])
                return file_id
        file_id = binascii.hexlify(os.urandom(12))
        if not isinstance(file_id, str):
            file_id = file_id.decode("ascii")
        _files[file_id] = (path, recorder)
        return file_id


def file_entry(file_id):
    """(path, recorder or None) for a registered id, else None."""
    with _files_lock:
        return _files.get(file_id)


def unregister_file(file_id):
    with _files_lock:
        _files.pop(file_id, None)


def unregister_path(path):
    path = _native(path)
    with _files_lock:
        for file_id in [k for k, v in _files.items() if v[0] == path]:
            _files.pop(file_id, None)


# ------------------------------------------------------- the stream


def _attr(line, key):
    match = re.search(r'(?:^|[:,])' + key + r'=("([^"]*)"|[^,]*)', line)
    if not match:
        return None
    return match.group(2) if match.group(2) is not None else match.group(1)


def pick_variant(base_url, text):
    """A master playlist's best picture (the highest bandwidth, as the
    app's pickVariant without a height limit): (index, address,
    separate_audio) - the index is ffmpeg's program number for it; a
    variant whose sound comes from a playlist of its own
    (#EXT-X-MEDIA:TYPE=AUDIO,URI=) needs the master (separate_audio)."""
    audio_groups = set()
    variants = []
    pending = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXT-X-MEDIA:") and \
                _attr(line, "TYPE") == "AUDIO" and _attr(line, "URI"):
            audio_groups.add(_attr(line, "GROUP-ID"))
        elif line.startswith("#EXT-X-STREAM-INF:"):
            try:
                bandwidth = int(_attr(line, "BANDWIDTH") or 0)
            except ValueError:
                bandwidth = 0
            pending = (bandwidth, _attr(line, "AUDIO"))
        elif line and not line.startswith("#") and pending is not None:
            variants.append((pending[0], urljoin(base_url, line), pending[1]))
            pending = None
    if not variants:
        return None
    best = max(range(len(variants)), key=lambda i: (variants[i][0], -i))
    return best, variants[best][1], variants[best][2] in audio_groups


def _opener(url):
    host = (urlparse(url).hostname or "").lower()
    if host in ("127.0.0.1", "localhost", "::1"):
        return build_opener(ProxyHandler({}))
    return build_opener()


def fetch_playlist(url, timeout=15, limit=2 * 1048576):
    """(address after redirects, text) - text None when the answer is
    not a playlist (a plain TS stream). Raises on an HTTP error."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    response = _opener(url).open(request, timeout=timeout)
    try:
        final = response.geturl() or url
        head = response.read(4096)
        if b"#EXTM3U" not in head[:1024]:
            return final, None
        body = head + response.read(limit)
    finally:
        try:
            response.close()
        except Exception:
            pass
    return final, body.decode("utf-8", "replace")


def input_args(url):
    """What ffmpeg is given for `url`: (address, -map arguments) - one
    picture of a master playlist (only that variant is downloaded),
    every sound track of it."""
    plain = ["-map", "0:v?", "-map", "0:a?"]
    if not url.startswith("http"):
        return url, plain
    final, text = fetch_playlist(url)
    if text is None or "#EXT-X-STREAM-INF" not in text:
        return final, plain
    picked = pick_variant(final, text)
    if picked is None:
        return final, plain
    index, variant, separate_audio = picked
    if separate_audio:
        return final, ["-map", "0:p:%d:v?" % index,
                       "-map", "0:p:%d:a?" % index]
    return variant, plain


def first_pts(data, start=0, video_only=True):
    """(PTS in 1/90000 s, offset of its packet) of the first PES header
    in `data` (a bytearray of whole TS packets from `start`), else
    None. Video only unless video_only is False (a radio channel)."""
    end = len(data) - PACKET + 1
    for i in range(start, max(start, end), PACKET):
        if data[i] != 0x47 or not data[i + 1] & 0x40:
            continue
        control = (data[i + 3] >> 4) & 3
        if control not in (1, 3):
            continue
        p = i + 4
        if control == 3:
            p += 1 + data[p]
        if p + 14 > i + PACKET:
            continue
        if data[p] != 0 or data[p + 1] != 0 or data[p + 2] != 1:
            continue
        stream_id = data[p + 3]
        if video_only and not 0xE0 <= stream_id <= 0xEF:
            continue
        if not video_only and not 0xC0 <= stream_id <= 0xEF:
            continue
        if not data[p + 7] & 0x80:
            continue
        pts = (((data[p + 9] >> 1) & 7) << 30) | (data[p + 10] << 22) | \
            ((data[p + 11] >> 1) << 15) | (data[p + 12] << 7) | \
            (data[p + 13] >> 1)
        return pts, i
    return None


class Recorder(object):
    """Records one channel into `path` (the app's Recorder).

    source(force) gives the stream's address (force: a fresh one, the
    last was refused). Runs until stop(), `stop_at` (wall clock, 0 =
    none), `max_seconds` of recording, or the disk getting full."""

    def __init__(self, source, path, stop_at=0, max_seconds=MANUAL_MAX,
                 info=None, ffmpeg=None, on_end=None, keep_alive=None,
                 log_path=None, tag="Recording", env=None,
                 space=free_bytes, thread_name="vv-rec"):
        self.id = binascii.hexlify(os.urandom(8))
        if not isinstance(self.id, str):
            self.id = self.id.decode("ascii")
        self.source = source
        self.path = _native(path)
        self.stop_at = stop_at or 0
        self.max_seconds = max_seconds
        self.info = dict(info) if info is not None else None
        self.ffmpeg = ffmpeg or find_ffmpeg()
        self.on_end = on_end
        self.keep_alive = keep_alive
        self.log_path = log_path
        self.tag = tag
        self.env = env
        self.space = space
        self.thread_name = thread_name
        self.bytes = 0
        self.duration = 0.0
        self.running = False
        self.finished = False
        self.failure = None
        self.started_at = None
        self.file_id = None
        self._stop = threading.Event()
        self._proc = None
        self._thread = None
        self._index_lock = threading.Lock()
        self._times = []
        self._offsets = []
        self._pts_last = None
        self._pts_base = 0.0
        self._video = True
        self._no_pts_bytes = 0
        self._part_start = None
        self._part_base = 0.0
        self._space_at = 0.0
        self._info_at = 0.0
        self._alive_at = 0.0
        self._alive_thread = None

    # ---- outside

    def start(self):
        if self.running or self.finished:
            return False
        if not self.ffmpeg:
            self.failure = "no ffmpeg"
            return False
        self.running = True
        self.started_at = time.time()
        self.file_id = register_file(self.path, self)
        self._thread = threading.Thread(target=self._run, name=self.tag)
        self._thread.daemon = True
        self._thread.start()
        return True

    def stop(self):
        """Ends it (does not wait - the thread finishes ffmpeg off):
        what was recorded stays."""
        self._stop.set()
        proc = self._proc
        try:
            if proc is not None and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass

    def join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    def discard(self):
        """A pause buffer: stopped, its file deleted."""
        self.stop()
        unregister_path(self.path)

        def _remove():
            self.join(10)
            try:
                if os.path.exists(self.path):
                    os.remove(self.path)
            except Exception:
                pass
        worker = threading.Thread(target=_remove)
        worker.daemon = True
        worker.start()

    def offset_for(self, seconds):
        """The byte (a packet boundary) where the recording is
        `seconds` in - the index entry at or before it."""
        with self._index_lock:
            if not self._times:
                return 0
            i = bisect.bisect_right(self._times, seconds) - 1
            return self._offsets[max(0, i)]

    def time_at(self, offset):
        with self._index_lock:
            if not self._offsets:
                return 0.0
            i = bisect.bisect_right(self._offsets, offset) - 1
            return self._times[max(0, i)]

    def snapshot(self):
        info = dict(self.info or {})
        info.update({"format": INFO_FORMAT, "duration": int(self.duration),
                     "bytes": self.bytes})
        if self.failure:
            info["failure"] = self.failure
        if self.finished:
            info["finished"] = True
        return info

    # ---- the thread

    def _done(self):
        if self._stop.is_set():
            return True
        now = time.time()
        if self.stop_at and now >= self.stop_at:
            return True
        if self.max_seconds and self.duration >= self.max_seconds:
            return True
        if now - self._space_at >= SPACE_EVERY:
            self._space_at = now
            free = self.space(self.path) if self.space else None
            if free is not None and free < STOP_FREE:
                if self.failure is None:
                    self.failure = "no space left"
                    _log("{}: stopped, the disk is nearly full".format(
                        self.tag))
                return True
        return False

    def _wait(self, seconds):
        end = time.time() + seconds
        while not self._done() and time.time() < end:
            self._stop.wait(min(0.5, max(0.01, end - time.time())))

    def _run(self):
        name_this_thread(self.thread_name)
        failures = 0
        out = None
        try:
            out = open(self.path, "ab", 0)
            self.bytes = os.path.getsize(self.path)
            self._write_records()
            while not self._done():
                try:
                    url = self.source(failures > 0)
                except Exception as e:
                    _log("{}: no address ({})".format(self.tag, e))
                    url = None
                if not url:
                    failures += 1
                    if failures >= MAX_FAILURES:
                        self.failure = "no stream address"
                        break
                    self._wait(NO_ADDRESS_DELAY)
                    continue
                before = self.bytes
                try:
                    self._pump(url, out)
                except Exception as e:
                    _log("{}: {}".format(self.tag, e))
                if self._done():
                    break
                # only a part that brought nothing is a failure (a long
                # one that ran out did fine - the app's rule)
                failures = failures + 1 if self.bytes == before else 1
                if failures >= MAX_FAILURES:
                    self.failure = "the stream keeps failing"
                    break
                _log("{}: a new stream address".format(self.tag))
                self._wait(RETRY_DELAY)
        except Exception as e:
            self.failure = str(e) or e.__class__.__name__
            _log("{}: stopped ({})".format(self.tag, self.failure))
        finally:
            self._kill()
            if out is not None:
                try:
                    out.close()
                except Exception:
                    pass
            self.running = False
            self.finished = True
            self._write_records()
            _log("{}: ended - {} s, {} MB".format(
                self.tag, int(self.duration), self.bytes // 1048576))
            if self.on_end is not None:
                try:
                    self.on_end(self)
                except Exception as e:
                    _log("on_end: {}".format(e))

    def _write_records(self):
        if self.info is None:
            return
        info = self.snapshot()
        write_info(self.path, info)
        write_meta(self.path, info.get("sref") or u"", info.get("title") or
                   info.get("name") or u"", info.get("description") or
                   info.get("name") or u"", info.get("start") or
                   self.started_at, self.duration, self.bytes)
        self._info_at = time.time()

    def _kill(self):
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is None:
                proc.terminate()
                for _i in range(20):
                    if proc.poll() is not None:
                        break
                    time.sleep(0.1)
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
        except Exception:
            pass

    def _command(self, url):
        address, maps = input_args(url)
        cmd = [self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
        nice = find_nice() if FFMPEG_NICE else None
        if nice:
            cmd = [nice, "-n", str(FFMPEG_NICE)] + cmd
        if address.startswith("http"):
            cmd += ["-user_agent", USER_AGENT]
        return cmd + ["-i", address] + maps + \
            ["-c", "copy", "-f", "mpegts", "pipe:1"]

    def _pump(self, url, out):
        """One ffmpeg run: its output into the file until it ends, gets
        stuck or the recording is done."""
        cmd = self._command(url)
        log = open(self.log_path, "ab") if self.log_path else \
            open(os.devnull, "wb")
        null = open(os.devnull, "rb")
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log,
                                    stdin=null, close_fds=True, env=self.env)
        finally:
            null.close()
        self._proc = proc
        self._new_part()
        fd = proc.stdout.fileno()
        pending = bytearray()
        synced = False
        last_data = time.time()
        try:
            while not self._done():
                ready = select.select([fd], [], [], 1.0)[0]
                now = time.time()
                if not ready:
                    if now - last_data > STALL_SECONDS:
                        raise IOError("no data for {} s".format(STALL_SECONDS))
                    self._side_jobs(now)
                    continue
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                last_data = now
                pending.extend(chunk)
                if not synced:
                    start = _sync(pending)
                    if start < 0:
                        if len(pending) > 4 * PACKET:
                            del pending[:len(pending) - 4 * PACKET]
                        continue
                    del pending[:start]
                    synced = True
                whole = len(pending) - len(pending) % PACKET
                if not whole:
                    continue
                if PY2:
                    self._index(pending[:whole], now)
                    out.write(bytes(pending[:whole]))
                else:
                    # looked at and written as it is, no copy (the
                    # views let go before the buffer is shortened)
                    whole_view = memoryview(pending)
                    part = whole_view[:whole]
                    self._index(part, now)
                    out.write(part)
                    part.release()
                    whole_view.release()
                del pending[:whole]
                self.bytes += whole
                self._side_jobs(now)
        finally:
            self._kill()
            self._proc = None
            try:
                proc.stdout.close()
            except Exception:
                pass
            log.close()

    def _side_jobs(self, now):
        if self.info is not None and now - self._info_at >= INFO_EVERY:
            self._write_records()
        if self.keep_alive is not None and \
                now - self._alive_at >= KEEP_ALIVE_EVERY:
            self._alive_at = now
            if self._alive_thread is None or not self._alive_thread.is_alive():
                self._alive_thread = threading.Thread(target=self._alive)
                self._alive_thread.daemon = True
                self._alive_thread.start()

    def _alive(self):
        try:
            self.keep_alive()
        except Exception as e:
            _log("{}: token not renewed ({})".format(self.tag, e))

    # ---- time

    def _new_part(self):
        """A new ffmpeg run: its time stamps start again - the
        recording's time goes on from where it was."""
        self._pts_last = None
        self._part_start = None
        self._part_base = self.duration

    def _index(self, block, now):
        """The time at the first PES header of each block written (a
        short scan: one comes within a few packets)."""
        if self._part_start is None:
            self._part_start = now
        found = first_pts(block, 0, self._video)
        if found is None:
            self._no_pts_bytes += len(block)
            if self._video and self._no_pts_bytes > 4 * 1048576:
                self._video = False       # a channel without picture
            if self._no_pts_bytes > 8 * 1048576:
                # no time stamps at all: the wall clock
                self.duration = max(self.duration, self._part_base +
                                    now - self._part_start)
                self._add_index(self.duration, self.bytes, now)
            return
        self._no_pts_bytes = 0
        pts, at = found
        seconds = pts / 90000.0
        if self._pts_last is None:
            self._pts_base = self.duration - seconds
        else:
            step = seconds - self._pts_last
            if step < -(1 << 32) / 90000.0:
                step += (1 << 33) / 90000.0   # the 26.5-hour wrap
                self._pts_base += (1 << 33) / 90000.0
            if step < -1 or step > 30:
                # a jump (a server restart): carried on from here
                self._pts_base = self.duration - seconds
        self._pts_last = seconds
        position = seconds + self._pts_base
        self.duration = max(self.duration, position)
        self._add_index(position, self.bytes + at, now)

    def _add_index(self, seconds, offset, now):
        with self._index_lock:
            if self._times and seconds < self._times[-1] + INDEX_STEP:
                return
            self._times.append(seconds)
            self._offsets.append(offset)


def _sync(data):
    """Where the TS packets start in `data` (three sync bytes 188
    apart), or -1."""
    for i in range(0, max(0, len(data) - 2 * PACKET)):
        if data[i] == 0x47 and data[i + PACKET] == 0x47 and \
                data[i + 2 * PACKET] == 0x47:
            return i
    return -1
