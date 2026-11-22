#!/usr/bin/python
# -*- coding: utf-8 -*-
"""Recordings: the memory watch, the recording service (RECORDINGS),
the folders and disks, the Recordings list and its player."""
from __future__ import absolute_import, print_function
from .ui_pick import (
    VavooPickScreen, ask_pin)
from .ui_base import (
    ACTIVE, NOW_PLAYING, PLAYER_BAR_LABELS, PLAYER_KEYS_PRIO, _icon_cache,
    build_theme_skin, cfg, clock_24, clock_text, file_stream_sref,
    open_action_menu, player_keys, show_keys, show_list, stream_channel_id,
    to_string, to_text)

import os
import time
import threading
from os.path import basename, dirname, join
from twisted.internet import reactor
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Pixmap import Pixmap
from Components.ProgressBar import ProgressBar
from Components.ServiceEventTracker import InfoBarBase
from Components.config import config
from enigma import eServiceReference, eTimer
from Screens.InfoBarGenerics import (
    InfoBarSubtitleSupport,
    InfoBarSeek,
    InfoBarAudioSelection,
    InfoBarNotifications,
    InfoBarShowHide
)
from Screens.Screen import Screen
from . import vavoo_proxy
from .vavoo_proxy import run_proxy_in_background
from . import _, PROXY_BASE_URL
from . import vUtils
from . import vavoo_store
from . import vavoo_record
from .vUtils import debug, make_print, is_proxy_ready
"""
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin                             #
#  Created by Lululla (https://github.com/Belfagor2005) #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0    #
#  Last Modified: 202600503                              #
#                                                       #
#  Credits:                                             #
#  - Original concept by Lululla                        #
#  - Background images by @oktus                        #
#  - Additional contributions by Qu4k3                  #
#  - Linuxsat-support.com & Corvoboys communities       #
#                                                       #
#  Usage of this code without proper attribution        #
#  is strictly prohibited.                              #
#  For modifications and redistribution,                #
#  please maintain this credit header.                  #
#########################################################
"""
# Import notification system
try:
    from .notification_system import (
        init_notification_system, quick_notify, set_notify_skin)
    NOTIFICATION_AVAILABLE = True
except ImportError as e:
    debug("Notification system not available: {}".format(e))
    NOTIFICATION_AVAILABLE = False

    def quick_notify(*args, **kwargs):
        pass

    def init_notification_system(*args, **kwargs):
        pass

    def set_notify_skin(*args, **kwargs):
        pass

print = make_print("PLUGIN")


# ---------------------------------------------------------------------
# The box's memory (a box was seen with 32 MB left of 926 and the
# kernel killing processes - the reboot then wiped who held it)
# ---------------------------------------------------------------------
MEMORY_LOW_KB = 100 * 1024       # below this much free: report, release
MEMORY_CHECK_EVERY = 60          # read /proc/meminfo this often
MEMORY_TREND_EVERY = 1800        # a "[MEM]" line in vavoo.log this often
MEMORY_REPORT_EVERY = 600        # at most one report this often
MEMORY_LOG_MAX = 64 * 1024       # the report file's size


def memory_log_file():
    """In /etc/enigma2: it outlives the reboot that usually follows."""
    return vavoo_store.data_file("vavoo_memory.log")


def write_memory_log(text):
    path = memory_log_file()
    try:
        old = ""
        if os.path.isfile(path):
            with open(path) as f:
                old = f.read()
        data = old + text
        if len(data) > MEMORY_LOG_MAX:
            data = data[-(MEMORY_LOG_MAX * 3 // 4):]
            data = data[data.find("\n") + 1:]
        with open(path, "w") as f:
            f.write(data)
    except Exception as e:
        debug("Memory report not written: {}".format(e))


class _MemoryWatch(object):
    """Run from the reminder service's tick (always on, plugin open or
    not): every MEMORY_TREND_EVERY a "[MEM] enigma2 166 MB, box 367 MB
    free" line in vavoo.log (does Enigma2 grow over days?); when the
    box has less than MEMORY_LOW_KB left, a report of who holds it in
    vavoo_memory.log, and the plugin lets go of what it can."""

    def __init__(self):
        self.checked_at = 0
        self.trend_at = 0
        self.reported_at = 0

    def tick(self, now=None):
        now = time.time() if now is None else now
        if now - self.checked_at < MEMORY_CHECK_EVERY:
            return
        self.checked_at = now
        if now - self.trend_at >= MEMORY_TREND_EVERY:
            self.trend_at = now
            print("[MEM] " + vUtils.memory_note())
        available = vUtils.read_meminfo().get("MemAvailable")
        if available is None or available >= MEMORY_LOW_KB:
            return
        if now - self.reported_at < MEMORY_REPORT_EVERY:
            return
        self.reported_at = now
        report = vUtils.memory_report()
        write_memory_log(report)
        print("[MEM] Low memory - report in {}:\n{}".format(
            memory_log_file(), report.rstrip()))
        self.release()

    def release(self):
        """Let go of the plugin's own memory: the guides but the one
        being watched, the scaled icons, most of the logo cache."""
        player = ACTIVE.get("player")
        keep = getattr(player, "country_code", None) \
            if player is not None else None
        guides = vUtils.release_guides(keep)
        icons = len(_icon_cache)
        _icon_cache.clear()
        if vUtils.picon_cache_in_ram():
            # (on a flash disk the logos take no memory)
            vUtils.trim_picon_cache(max_bytes=4 * 1024 * 1024)
        print("[MEM] Released {} guides, {} icons".format(guides, icons))


MEMORY_WATCH = _MemoryWatch()


# ---------------------------------------------------------------------
# Recordings (vavoo_record.py; the app's RecordingService)
# ---------------------------------------------------------------------
# ffmpeg's own messages (vavoo_record.py's Recorder).
RECORD_LOG = "/tmp/vavoo_record.log"


def default_movie_folder():
    try:
        path = config.usage.default_path.value
        if path:
            return path
    except Exception:
        pass
    return "/media/hdd/movie/"


def recordings_folder():
    return cfg.record_path.value or default_movie_folder()


def media_mounts(network=False):
    """The disks mounted under /media (/media/hdd, /media/usb, an autofs
    /media/autofs/sdb1...), from /proc/mounts - mount points only (a
    /media/hdd with no disk is a plain folder on the flash), and
    /media/usb as a link to one is its target. With `network` the
    network shares too (told by their file system, wherever mounted).
    Never the box's memory."""
    out = []
    for point, fstype in vavoo_record.mount_points():
        if not point.startswith("/media/") or point in out:
            continue
        if fstype in vavoo_record._RAM_FS:
            continue
        if fstype in vavoo_record.NETWORK_FS and not network:
            continue
        if os.path.isdir(point):
            out.append(point)
    return sorted(out)


def record_folder_choices():
    """[(value, folder)]: Enigma2's movie folder ("") and a movie
    folder on each disk mounted under /media (and /media/net)."""
    out = [("", default_movie_folder())]
    seen = set([out[0][1].rstrip("/")])
    for mount in media_mounts(network=True):
        folder = join(mount, "movie") + "/"
        if folder.rstrip("/") not in seen:
            seen.add(folder.rstrip("/"))
            out.append((folder, folder))
    current = cfg.record_path.value
    if current and current.rstrip("/") not in seen:
        out.append((current, current))
    return out


def usable_folder(folder, create=True):
    """`folder` if it is on a mounted disk and can be written to (made
    there when missing), else None. Never the box's internal flash: a
    /media/hdd with no disk mounted is a plain folder on it, and a
    recording there saturated the box."""
    if not folder:
        return None
    try:
        if not vavoo_record.on_disk(folder):
            debug("Folder {} is not on a disk: not used".format(folder))
            return None
        if not os.path.isdir(folder):
            if not create:
                return None
            parent = dirname(folder.rstrip("/"))
            if not os.path.isdir(parent):
                return None
            os.makedirs(folder)
        if os.access(folder, os.W_OK):
            return folder
    except Exception as e:
        debug("Folder {} not usable: {}".format(folder, e))
    return None


# The channel logos' folder on a flash disk (logo_folder()).
LOGO_FOLDER_NAME = ".vavoo_logos"
LOGO_MIN_FREE = 200 * 1024 * 1024


def logo_folder():
    """Where the channel logos are kept, when not in /tmp (RAM on a
    box): a flash disk - a USB stick, an SD card, an SSD
    (vavoo_record.non_rotational()) - that is local (no share), can be
    written and has LOGO_MIN_FREE: the recordings' disk first, else one
    under /media. None: /tmp, as before. Never a hard disk: waking one
    holds the channel list for seconds (logos are read as rows are
    drawn)."""
    candidates = []
    try:
        candidates.append(vavoo_record.mount_of(recordings_folder())[0])
    except Exception as e:
        debug("Recordings disk not read: {}".format(e))
    candidates.extend(media_mounts())
    seen = set()
    for point in candidates:
        if not point or point == "/" or point in seen:
            continue
        seen.add(point)
        try:
            if vavoo_record.mount_of(point)[1] in vavoo_record.NETWORK_FS:
                continue
            if not vavoo_record.on_disk(
                    point) or not vavoo_record.non_rotational(point):
                continue
            if vavoo_record.free_bytes(point) < LOGO_MIN_FREE:
                continue
            folder = usable_folder(os.path.join(point, LOGO_FOLDER_NAME))
            if folder:
                return folder
        except Exception as e:
            debug("Logo folder on {} not usable: {}".format(point, e))
    return None


# Why a PAUSE is not recorded (Playstream2._shift_why): the text after
# "Paused" in the bar / message - PLAY then goes on live.
SHIFT_WHY = {
    "disk": lambda: _("not recorded (no disk) - PLAY returns to live"),
    "ffmpeg": lambda: _("not recorded (no ffmpeg) - PLAY returns to live"),
    "start": lambda: _("not recorded - PLAY returns to live"),
    "stopped": lambda: _("not recorded (the stream could not be "
                         "recorded) - PLAY returns to live"),
}


def pause_folder():
    """Where the pause buffer goes: Enigma2's timeshift folder, else
    the recordings folder, else the disk under /media with the most
    room (a USB stick at /media/usb: Enigma2's two folders are both on
    /media/hdd unless changed) - with room to spare
    (vavoo_record.MIN_FREE), else None (PAUSE only pauses). Never a
    network share (written all the time)."""
    candidates = []
    try:
        candidates.append(config.usage.timeshift_path.value)
    except Exception:
        pass
    candidates.append(recordings_folder())
    for folder in candidates:
        folder = usable_folder(folder, create=False) or \
            (usable_folder(folder) if folder == recordings_folder() else None)
        if not folder:
            continue
        free = vavoo_record.free_bytes(folder)
        if free is None or free >= vavoo_record.MIN_FREE:
            return folder
    best, most = None, -1
    for mount in media_mounts():
        folder = usable_folder(mount, create=False)
        if not folder:
            continue
        free = vavoo_record.free_bytes(folder)
        if free is not None and free >= vavoo_record.MIN_FREE and free > most:
            best, most = folder, free
    return best


def clean_pause_leftovers():
    """Pause buffers left behind (the box was switched off, Enigma2
    restarted while paused) - each can be gigabytes."""
    keep = []
    player = ACTIVE.get("player")
    shift = getattr(player, "_shift", None) if player is not None else None
    if shift is not None:
        keep.append(shift.path)
    folders = [recordings_folder()]
    try:
        folders.append(config.usage.timeshift_path.value)
    except Exception:
        pass
    # (pause_folder() may also have used any disk's own top folder)
    folders.extend(media_mounts())
    for folder in folders:
        try:
            if folder and os.path.isdir(folder):
                removed = vavoo_record.clean_shift_files(folder, keep)
                if removed:
                    print("[vavoo] {} old pause buffers deleted from "
                          "{}".format(removed, folder))
        except Exception as e:
            debug("Pause buffers not cleaned in {}: {}".format(folder, e))


def size_text(size):
    if size >= 1e9:
        return "%.1f GB" % (size / 1e9)
    return "%d MB" % (size // 1048576)


def recording_text(title, stop_at=0):
    """"Recording: Title  →  21:02" (the app's recording_started)."""
    text = to_text(_("Recording: {}")).format(to_text(title))
    if stop_at:
        text += u"  →  " + to_text(clock_text(stop_at))
    return to_string(text)


def wait_for_proxy(seconds=90):
    """In a background thread: the proxy started if it is not
    running (a box woken up for a recording), and waited for."""
    if is_proxy_ready(timeout=2):
        return True
    try:
        run_proxy_in_background()
    except Exception as e:
        debug("Proxy not started for a recording: {}".format(e))
    end = time.time() + seconds
    while time.time() < end:
        if is_proxy_ready(timeout=2):
            return True
        time.sleep(2)
    return False


class _Recordings(object):
    """The recordings running now, by id (the app's
    RecordingService.active): started from the player's options, the
    REC key, the guide and its timers; they go on whatever the plugin
    does (zap, close, standby). Each has a Vavoo token of its own
    (vavoo_proxy's resolve_own(): one stream per token)."""

    def __init__(self):
        self.active = {}
        self.lock = threading.Lock()

    def running(self):
        with self.lock:
            return [r for r in self.active.values() if r.running]

    def recording_of(self, url):
        channel_id = stream_channel_id(url) if url else None
        if not channel_id:
            return None
        for recorder in self.running():
            if stream_channel_id((recorder.info or {}).get("url")) == \
                    channel_id:
                return recorder
        return None

    def active_paths(self):
        return [r.path for r in self.running()]

    def start(self, channel, title=None, stop_at=0, quiet=False):
        """Records `channel` ({"name", "url", "country_name",
        "country_code", "logo"}) from now until stop_at (0: until
        stopped, 4 hours at most). The Recorder, or None (said why
        unless quiet)."""
        url = channel.get("url")
        channel_id = stream_channel_id(url)
        name = to_text(channel.get("name"))
        title = to_text(title or name)

        def fail(message):
            if not quiet and NOTIFICATION_AVAILABLE:
                quick_notify(message, 4)
            return None

        if not channel_id:
            return fail(_("This channel cannot be played"))
        running = self.recording_of(url)
        if running is not None:
            return running
        ffmpeg = vavoo_record.find_ffmpeg()
        if not ffmpeg:
            return fail(_("Recording needs ffmpeg"))
        folder = usable_folder(recordings_folder())
        free = vavoo_record.free_bytes(folder) if folder else 0
        if not folder:
            return fail(_("Can't record: no disk (HDD / USB) found"))
        if free is not None and free < vavoo_record.MIN_FREE:
            return fail(_("Can't record (not enough free space?)"))
        now = time.time()
        path = vavoo_record.new_path(folder, name, title, now)
        info = {
            "format": vavoo_record.INFO_FORMAT, "version": 1,
            "name": name, "title": title, "url": to_text(url),
            "country": to_text(channel.get("country_name") or ""),
            "country_code": to_text(channel.get("country_code") or ""),
            "logo": to_text(channel.get("logo") or ""),
            "start": int(now), "stop_at": int(stop_at or 0),
            "sref": u"4097:0:1:0:0:0:0:0:0:0::" + name.replace(u":", u"%3a"),
            "description": name}
        if stop_at:
            max_seconds = stop_at - now + vavoo_record.TIMER_EXTRA
        else:
            max_seconds = vavoo_record.MANUAL_MAX
        slot = "recording:" + basename(path)

        def address(force):
            if not wait_for_proxy():
                return None
            return vavoo_proxy.proxy.resolve_own(channel_id, slot, force)

        def keep_alive():
            vavoo_proxy.proxy.own_signature(slot)

        recorder = vavoo_record.Recorder(
            address, path, stop_at=stop_at, max_seconds=max_seconds,
            info=info, ffmpeg=ffmpeg, on_end=self._ended,
            keep_alive=keep_alive, log_path=RECORD_LOG,
            tag="Recording " + to_string(name), thread_name="vv-rec",
            max_bytes=vavoo_record.file_size_limit(folder))
        recorder.slot = slot
        if not recorder.start():
            return fail(_("Can't record (not enough free space?)"))
        with self.lock:
            self.active[recorder.id] = recorder
        print("[vavoo] Recording {} -> {}".format(to_string(name), path))
        return recorder

    def stop(self, recorder):
        if recorder is not None:
            recorder.stop()

    def _ended(self, recorder):
        """(the recorder's thread)"""
        with self.lock:
            self.active.pop(recorder.id, None)
        try:
            vavoo_proxy.proxy.drop_own_signature(recorder.slot)
        except Exception:
            pass
        if recorder.failure and NOTIFICATION_AVAILABLE:
            title = (recorder.info or {}).get("title") or ""
            if recorder.failure == vavoo_record.FAILURE_SPACE:
                quick_notify(
                    _("Recording stopped: the disk is nearly full"), 6)
            elif recorder.failure == vavoo_record.FAILURE_FAT:
                quick_notify(_("Recording stopped: the disk's 4 GB file "
                               "limit (FAT32)"), 6)
            elif recorder.failure == vavoo_record.FAILURE_DISK:
                quick_notify(_("Recording stopped: the disk could not be "
                               "written (removed?)"), 6)
            else:
                quick_notify(_("Recording stopped early: {}").format(
                    to_string(title)), 6)


RECORDINGS = _Recordings()


def timer_when(timestamp):
    """"Sat 16 Nov 20:00" (the app's list of timers)."""
    moment = time.localtime(timestamp)
    return to_text(time.strftime("%a %d %b ", moment)) + \
        to_text(clock_text(timestamp))


class VavooRecordings(VavooPickScreen):
    """Settings → Recordings and the main list's row (the app's
    RecordingsActivity): the timers set in the guide ("● " a
    recording, else a reminder) with their day and time, then the
    recordings on the disk, the newest first, with their start and
    length ("● REC · 12 min" while recording). OK: play a recording
    (the PIN for a locked channel's) / cancel a timer; GREEN Delete
    (press twice; a running recording stops first); RED Back."""

    REFRESH_MS = 30000
    REFRESH_RECORDING_MS = 5000

    def __init__(self, session):
        self._closed = False
        # the rows' (kind, data) - not self.items: a Screen is a dict and
        # Enigma2's doClose() calls self.items() (the Recordings crash,
        # ui_base's CLOSED_UNTIL_OPEN)
        self._entries = []
        self._delete_armed = None
        VavooPickScreen.__init__(
            self, session,
            _("Reminders and recordings (●) set in the guide, and the "
              "recordings on the disk. OK: play (or cancel a timer) - "
              "GREEN: delete."),
            (_("Back"), _("Delete"), "", ""))
        self._timer = eTimer()
        try:
            self._timer.callback.append(self._tick)
        except Exception:
            self._timer.timeout.connect(self._tick)
        self.onClose.append(self._on_close)

    def _on_close(self):
        self._closed = True
        self._timer.stop()

    def key_actions(self):
        return {"ok": self.ok, "green": self.delete}

    def direct_keys(self):
        return {"play": self.play_selected, "stop": self.stop_selected}

    def help_rows(self):
        return [
            ("OK", _("Play the recording / cancel the timer")),
            ("PLAY", _("Play the recording")),
            ("STOP", _("Stop a recording that is running")),
            (_("GREEN"), _("Delete (press twice)")),
            (_("RED / EXIT"), _("Back")),
        ]

    def play_selected(self):
        """PLAY: the highlighted recording (a timer: nothing)."""
        item = self._selected()
        if item is not None and item[0] == "rec":
            self.ok()

    def stop_selected(self):
        """STOP: the highlighted recording stops, if it is running (it
        stays on the disk)."""
        item = self._selected()
        if item is None or item[0] != "rec":
            return
        recorder = next((r for r in RECORDINGS.running()
                         if r.path == item[1]["path"]), None)
        if recorder is None:
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("This recording is not running"), 2)
            return
        recorder.stop()
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Recording stopped"), 2)
        self.refresh()

    def _tick(self):
        # (a timer that went off meanwhile has left the file, a
        # recording has grown)
        if not self._closed:
            self.refresh()

    @staticmethod
    def _key(item):
        if item is None:
            return None
        kind, data = item
        return (kind, data["id"] if kind == "timer" else data["path"])

    def refresh(self, select=None):
        keep = self._key(self._selected()) if select is None else None
        timers = vavoo_store.load_timers()
        running = dict((r.path, r) for r in RECORDINGS.running())
        recordings = vavoo_record.list_recordings(recordings_folder(),
                                                  list(running))
        items = [("timer", t) for t in timers] + \
            [("rec", r) for r in recordings]
        rows = []
        for kind, data in items:
            if kind == "timer":
                sign = u"● " if data["kind"] == vavoo_store.KIND_RECORD \
                    else u""
                text = u"{}{}  ·  {}".format(
                    sign, to_text(data.get("title")),
                    to_text(data.get("name")))
                value = timer_when(data["start"])
                key = "timer:{}".format(data["id"])
            else:
                recorder = running.get(data["path"])
                seconds = recorder.duration if recorder is not None else \
                    data.get("duration") or 0
                minutes = int(seconds // 60)
                if recorder is not None:
                    value = to_text(_("● REC · {} min")).format(
                        minutes)
                else:
                    start = data.get("start") or 0
                    value = u"{} {} · {}".format(
                        to_text(time.strftime("%d/%m",
                                              time.localtime(start))),
                        to_text(clock_text(start)),
                        to_text(_("{} min")).format(minutes))
                title = to_text(data.get("title"))
                name = to_text(data.get("name"))
                text = name if not title or title == name else \
                    u"{}  ·  {}".format(title, name)
                key = "rec:" + to_text(basename(data["path"]))
            rows.append(show_list(
                to_string(text), to_string(key), is_category=True,
                kind="big", themed=self._themed, value=to_string(value),
                no_icon=True))
        self._entries = items
        if keep is not None:
            for index, item in enumerate(items):
                if self._key(item) == keep:
                    select = index
                    break
        self._show(rows, select)
        if items:
            free = vavoo_record.free_bytes(recordings_folder())
            self['statusbar'].setText(to_string(to_text(
                _("{} recordings · {} timers · {} free")).format(
                len(recordings), len(timers),
                size_text(free) if free is not None else "?")))
        else:
            self['statusbar'].setText(
                _("Nothing yet: record from the player's options, or set a "
                  "recording in the guide."))
        self._timer.start(self.REFRESH_RECORDING_MS if running
                          else self.REFRESH_MS, True)

    def _selected(self):
        index = self._index()
        if 0 <= index < len(self._entries):
            return self._entries[index]
        return None

    def _remove_timer(self, timer):
        vavoo_store.remove_timer(timer["id"])
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Cancelled"), 2)
        self.refresh()

    def ok(self):
        item = self._selected()
        if item is None:
            return
        kind, data = item
        if kind == "timer":
            label = _("Cancel recording") \
                if data["kind"] == vavoo_store.KIND_RECORD \
                else _("Cancel reminder")
            open_action_menu(
                self.session, to_string(data.get("title")),
                [(label, "cancel")],
                lambda key: self._remove_timer(data)
                if key == "cancel" else None)
            return

        def play():
            if not self._closed:
                self.session.openWithCallback(
                    lambda *a: self.refresh() if not self._closed else None,
                    VavooRecordingPlayer, data)
        if recording_needs_pin(data):
            ask_pin(self.session, self, play)
        else:
            play()

    def delete(self):
        item = self._selected()
        if item is None:
            return
        key = self._key(item)
        if self._delete_armed != key:
            self._delete_armed = key
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Press again to delete"), 3)
            return
        self._delete_armed = None
        kind, data = item
        if kind == "timer":
            self._remove_timer(data)
            return
        recorder = next((r for r in RECORDINGS.running()
                         if r.path == data["path"]), None)

        def deleted():
            if NOTIFICATION_AVAILABLE:
                quick_notify(_("Deleted"), 2)
            if not self._closed:
                self.refresh()

        if recorder is None:
            vavoo_record.delete_recording(data["path"])
            deleted()
            return

        def _stop_then_delete():
            # (deleted once it has really stopped: its last write
            # would otherwise bring the file back)
            recorder.join(10)
            vavoo_record.delete_recording(data["path"])
            reactor.callFromThread(deleted)

        recorder.stop()
        worker = threading.Thread(target=_stop_then_delete)
        worker.daemon = True
        worker.start()


def recording_needs_pin(recording):
    """A recording of a locked channel plays only with the PIN (an
    older one without its country: when any country is locked - the
    app's Recording.needsPin)."""
    name = recording.get("name")
    country = recording.get("country") or None
    if vavoo_store.needs_pin_for_channel(name, country):
        return True
    if not country and vavoo_store.locked_countries():
        return vavoo_store.has_pin() and not vavoo_store.is_unlocked()
    return False


class VavooRecordingPlayer(
        InfoBarBase,
        InfoBarSeek,
        InfoBarAudioSelection,
        InfoBarSubtitleSupport,
        InfoBarNotifications,
        InfoBarShowHide,
        Screen):
    """A recording played (the app's RecordingPlayerActivity): LEFT /
    RIGHT 10 s, YELLOW / BLUE and << / >> 30 s, OK / GREEN / PAUSE /
    PLAY pause and play on, EXIT / STOP / RED close. A finished one
    plays straight from its file with Enigma2's own seeking; one still
    being recorded through the proxy's /file as it grows, a jump
    opening it again at the byte for that time (as Pause Live TV)."""

    ALLOW_SUSPEND = True
    STEP = 10
    BIG_STEP = 30
    _closed = True          # (ui_base's CLOSED_UNTIL_OPEN)

    def __init__(self, session, recording):
        self._closed = False
        Screen.__init__(self, session)
        self.session = session
        self.recording = recording
        self.path = recording["path"]
        self.recorder = next((r for r in RECORDINGS.running()
                              if r.path == self.path), None)
        self._growing = self.recorder is not None
        self._pos = 0.0
        self._clock = None
        self._paused = False
        self.title = to_text(recording.get("title") or
                             recording.get("name") or "")
        skin = build_theme_skin("player", clock_24=clock_24())
        self._themed = skin is not None
        if self._themed:
            self.skin = skin
            self.skinName = "VavooPlayer"
            for widget in PLAYER_BAR_LABELS:
                self[widget] = Label("")
            self["logo"] = Pixmap()
            self["info_box"] = Pixmap()
            self["progress_track"] = Pixmap()
            self["progress"] = ProgressBar()
            self.onLayoutFinish.append(self._layout_finished)
        else:
            self.skinName = "MoviePlayer"
        for base in (InfoBarBase, InfoBarSeek, InfoBarAudioSelection,
                     InfoBarSubtitleSupport, InfoBarNotifications,
                     InfoBarShowHide):
            base.__init__(self)

        def nothing():
            return None

        # The same keys on every image (keymap.xml); the ones with no
        # use here do nothing rather than reach Enigma2's own (arrow
        # seek, seek by digits).
        own_keys = dict((str(d), nothing) for d in range(10))
        own_keys.update({
            "ok": self.play_pause,
            "green": self.play_pause,
            "playpause": self.play_pause,
            "exit": self.leave,
            "red": self.leave,
            "stop": self.leave,
            "left": lambda: self.jump(-self.STEP),
            "right": lambda: self.jump(self.STEP),
            "yellow": lambda: self.jump(-self.BIG_STEP),
            "rewind": lambda: self.jump(-self.BIG_STEP),
            "blue": lambda: self.jump(self.BIG_STEP),
            "forward": lambda: self.jump(self.BIG_STEP),
            "menu": self.options,
            "audio": lambda: self._call("audioSelection"),
            "subtitle": lambda: self._call("subtitleSelection"),
            "up": nothing, "down": nothing,
            "channelUp": nothing, "channelDown": nothing,
            "info": nothing, "epg": nothing, "record": nothing,
            "favourites": nothing, "help": self.show_help,
        })
        self["vavoo_keys"] = player_keys(own_keys)
        # (the image's names: where keymap.xml could not be loaded; the
        # seek lists' own, so that their arrows do not move again after
        # DirectionActions moved)
        self["seek_keys"] = ActionMap(
            ["InfobarSeekActions", "InfobarArrowSeekActions"],
            {"pauseService": self.play_pause,
             "playpauseService": self.play_pause,
             "unPauseService": self.play_pause,
             "seekFwd": lambda: self.jump(self.BIG_STEP),
             "seekBack": lambda: self.jump(-self.BIG_STEP),
             "left": nothing, "right": nothing,
             "up": nothing, "down": nothing},
            PLAYER_KEYS_PRIO + 1)
        self["actions"] = ActionMap(
            ["OkCancelActions", "ColorActions", "DirectionActions",
             "MoviePlayerActions", "MenuActions", "InfoBarMenuActions",
             "InfobarMenuActions"],
            {
                "showMenu": self.options,
                "mainMenu": self.options,
                "ok": self.play_pause,
                "cancel": self.leave,
                "leavePlayer": self.leave,
                "red": self.leave,
                "green": self.play_pause,
                "yellow": lambda: self.jump(-self.BIG_STEP),
                "blue": lambda: self.jump(self.BIG_STEP),
                "left": lambda: self.jump(-self.STEP),
                "right": lambda: self.jump(self.STEP),
                "menu": self.options,
            }, PLAYER_KEYS_PRIO + 1)
        self._previous = None
        self._was_preview = False
        self._seek_timer = eTimer()
        self._tick_timer = eTimer()
        for timer, function in ((self._seek_timer, self._seek_now),
                                (self._tick_timer, self._tick)):
            try:
                timer.callback.append(function)
            except Exception:
                timer.timeout.connect(function)
        self.onFirstExecBegin.append(self._start)
        self.onClose.append(self._on_close)

    def _layout_finished(self):
        for widget in ("info_box", "stream_info", "logo"):
            try:
                self[widget].hide()
            except Exception:
                pass

    def help_rows(self):
        return [
            (_("OK / GREEN / PAUSE / PLAY"), _("Pause / play on")),
            (_("LEFT / RIGHT"), _("10 seconds back / on")),
            (_("YELLOW / BLUE, << / >>"), _("30 seconds back / on")),
            ("MENU", _("Options")),
            ("AUDIO / SUBTITLE", _("Audio track / subtitles")),
            (_("RED / STOP / EXIT / BACK"), _("Close")),
        ]

    def show_help(self):
        show_keys(self.session, self.help_rows())

    def options(self):
        """MENU: the options, as in the live player."""
        open_action_menu(
            self.session, _("Options"),
            [(_("Audio track"), "audioSelection"),
             (_("Subtitles"), "subtitleSelection")],
            lambda key: self._call(key) if key and not self._closed
            else None, layout="player_menu")

    def _call(self, method):
        function = getattr(self, method, None)
        if function is not None:
            try:
                function()
            except Exception as e:
                debug("{} not opened: {}".format(method, e))

    def _start(self):
        try:
            self._previous = \
                self.session.nav.getCurrentlyPlayingServiceReference()
        except Exception:
            self._previous = None
        # (a channel in the list's preview window: let go of it - the
        # window stays empty until a channel is chosen again)
        self._was_preview = NOW_PLAYING.owner == NOW_PLAYING.PREVIEW
        if self._was_preview:
            NOW_PLAYING.release_preview()
        if self._growing:
            self._play_at(0.0)
        else:
            sref = eServiceReference(int(cfg.services.value), 0, self.path)
            sref.setName(to_string(self.title))
            self.session.nav.stopService()
            self.session.nav.playService(sref)
        self._tick_timer.start(1000, False)
        self._tick()
        if not self._themed and NOTIFICATION_AVAILABLE:
            # (Classic's MoviePlayer bar shows no captions of its own)
            quick_notify(_("LEFT / RIGHT 10 s · YELLOW / BLUE 30 s · "
                           "OK pause · MENU options · EXIT close"), 5)

    def isSeekable(self):
        return not self._growing

    def doEofInternal(self, playing):
        """The end of the recording: the player closes."""
        if self.execing and not self._closed:
            self.leave()

    # ---- where it is

    def position(self):
        if self._growing:
            position = self._pos
            if self._clock is not None and not self._paused:
                position += time.time() - self._clock
            return max(0.0, min(position, self.recorder.duration))
        return self._service_seconds("getPlayPosition")

    def length(self):
        if self._growing:
            return self.recorder.duration
        return self._service_seconds("getLength") or \
            float(self.recording.get("duration") or 0)

    def _service_seconds(self, what):
        try:
            seek = self.session.nav.getCurrentService().seek()
            answer = getattr(seek, what)()
            if answer and not answer[0]:
                return answer[1] / 90000.0
        except Exception:
            pass
        return 0.0

    # ---- keys

    def play_pause(self):
        if self._growing:
            if self._paused:
                self._paused = False
                self._play_at(self._pos)
            else:
                self._pos = self.position()
                self._paused = True
                self._seek_timer.stop()
                InfoBarSeek.pauseService(self)
        else:
            InfoBarSeek.playpauseService(self)
            self._paused = getattr(self, "seekstate", None) == \
                getattr(self, "SEEK_STATE_PAUSE", ())
        self._shown()

    def jump(self, seconds):
        if self._growing:
            end = max(0.0, self.recorder.duration - 2)
            self._pos = max(0.0, min(self.position() + seconds, end))
            self._clock = None
            self._paused = False
            self._seek_timer.start(800, True)
        else:
            try:
                self.doSeekRelative(int(seconds * 90000))
            except Exception as e:
                debug("Recording not moved: {}".format(e))
        self._shown()

    def _seek_now(self):
        if self._growing:
            self._play_at(self._pos)

    def _play_at(self, position):
        if self._closed:
            return
        offset = self.recorder.offset_for(position)
        url = "{}/file?id={}&offset={}&follow=1".format(
            PROXY_BASE_URL, self.recorder.file_id, offset)
        self._pos = self.recorder.time_at(offset)
        self._clock = time.time()
        self.session.nav.stopService()
        self.session.nav.playService(file_stream_sref(url, self.title))

    def leave(self):
        self.close()

    def _on_close(self):
        if self._closed:
            return
        self._closed = True
        self._seek_timer.stop()
        self._tick_timer.stop()
        try:
            self.session.nav.stopService()
            if not self._was_preview and self._previous is not None:
                self.session.nav.playService(self._previous)
        except Exception as e:
            debug("Service not put back: {}".format(e))

    # ---- the bar

    def _shown(self):
        try:
            self.doShow()
        except Exception:
            pass
        self._tick()

    def _tick(self):
        if not self._themed or self._closed:
            return
        if self._growing and not self.recorder.running and \
                self.recorder.finished:
            # (recorded to the end meanwhile: still played as it was)
            pass
        position, length = self.position(), self.length()

        def clock(seconds):
            seconds = int(seconds)
            if seconds >= 3600:
                return u"{}:{:02d}:{:02d}".format(
                    seconds // 3600, seconds // 60 % 60, seconds % 60)
            return u"{}:{:02d}".format(seconds // 60, seconds % 60)

        start = self.recording.get("start") or 0
        texts = {
            "number": u"● REC" if self._growing and
            self.recorder.running else u"",
            "name": self.title,
            "now": u"{}  ·  {}".format(
                to_text(self.recording.get("name")), timer_when(start)),
            "left": u"",
            "next": u"{} / {}".format(clock(position), clock(length)),
            "status": to_text(_("LEFT / RIGHT 10 s · YELLOW / BLUE "
                                "30 s · EXIT: close")),
            "key_red": to_text(_("Back")),
            "key_green": (u"▶ " + to_text(_("Play"))) if self._paused
            else (u"❚❚ " + to_text(_("Pause"))),
            "key_yellow": u"◀◀ 30 s",
            "key_blue": u"30 s ▶▶",
            "key_options": u"MENU " + to_text(_("Options")),
            # (LEFT / RIGHT)
            "key_list": u"◀ 10 s ▶",
        }
        for widget, text in texts.items():
            try:
                self[widget].setText(to_string(text))
            except Exception:
                pass
        try:
            self["progress"].setValue(
                int(100 * position / length) if length > 0 else 0)
        except Exception:
            pass


def record_channel(channel):
    """REC: records `channel` ({name, url, country_name, country_code,
    logo}) until the end of the programme on now plus 2 minutes (a
    receiver's instant recording) - or, with no guide or a programme
    ending within 10 minutes, until stopped (4 hours at most). Again:
    stops it. The player's REC and the lists' REC (the highlighted
    channel)."""
    url = channel.get("url")
    if not url:
        return
    running = RECORDINGS.recording_of(url)
    if running is not None:
        running.stop()
        if NOTIFICATION_AVAILABLE:
            quick_notify(_("Recording stopped"), 2)
        return
    name = channel.get("name")
    title, stop_at = to_text(name), 0
    try:
        answer = vUtils.peek_now_next(name, channel.get("country_code"))
    except Exception as e:
        debug("Now/next not read for a recording: {}".format(e))
        answer = None
    now = time.time()
    if answer and answer[0] == "ok" and answer[1]:
        programme = answer[1]
        if programme[2]:
            title = to_text(programme[2])
        if 600 <= programme[1] - now < 6 * 3600:
            stop_at = programme[1] + vavoo_store.RECORD_MARGIN
    if RECORDINGS.start(dict(channel), title, stop_at) is not None:
        if NOTIFICATION_AVAILABLE:
            quick_notify(recording_text(title, stop_at), 3)
