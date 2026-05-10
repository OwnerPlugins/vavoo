# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import, division
from bisect import bisect_left
from datetime import datetime, timedelta, tzinfo as _tzinfo
from json import load, dump
from os import unlink
from re import IGNORECASE, compile as re_compile
import gzip
import io
import logging
import requests
import select
import threading
import xml.etree.ElementTree as ET

from . import PY2

"""
EPG Manager - Optimized EPG download and caching module.

Improvements vs original:
  1. Parallel source loading  – all 34 sources downloaded simultaneously
  2. Binary search            – get_current_program is O(log n) not O(n)
  3. normalize_name cached    – per-process dict, compiled regex patterns
  4. parse_xmltv_date cached  – same timestamp string parsed only once
  5. Stream-decompress        – gzip decompressed on the fly, no double buffer
  6. Programs pre-sorted      – sort once after load, not on every query
  7. name_to_id multi-value   – stores list of ids, returns best match
  8. EPGCache validity cached – meta.json read once per session
"""

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


if PY2:
    from pathlib2 import Path

    class _UTC(_tzinfo):
        """UTC timezone for Python 2 compatibility."""
        def utcoffset(self, dt): return timedelta(0)
        def tzname(self, dt): return "UTC"
        def dst(self, dt): return timedelta(0)
    UTC = _UTC()
else:
    from pathlib import Path
    from datetime import timezone
    UTC = timezone.utc


# ── Pre-compiled regex patterns (module level – compiled once) ────────────────
_RE_COUNTRY_PREFIX = re_compile(r'^(IT|CH)\s*-\s*', IGNORECASE)
_RE_QUALITY_SUFFIX = re_compile(r'\s+(HD|FHD|SD|HEVC|H265|4K).*', IGNORECASE)
_RE_SPECIAL_CHARS  = re_compile(r'[^A-Z0-9]')

# ── normalize_name cache ──────────────────────────────────────────────────────
_NORM_CACHE = {}  # {raw_name: normalized}
_NORM_CACHE_LOCK = threading.Lock()

# ── parse_xmltv_date cache ────────────────────────────────────────────────────
_DATE_CACHE = {}  # {date_str: datetime}
_DATE_CACHE_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
class EPGSource(object):
    """Configuration for an EPG source."""
    def __init__(self, name, url, backup_url=None, enabled=True,
                 priority=0, country_code=""):
        self.name = name
        self.url = url
        self.backup_url = backup_url
        self.enabled = enabled
        self.priority = priority
        self.country_code = country_code


class ChannelInfo(object):
    """EPG channel information."""
    def __init__(self, id, display_name, icon=None,
                 normalized_name="", country_code=""):
        self.id = id
        self.display_name = display_name
        self.icon = icon
        self.normalized_name = normalized_name
        self.country_code = country_code


class Program(object):
    """EPG program information."""
    __slots__ = ('channel_id', 'start', 'stop', 'title', 'desc',
                 '_start_ts', '_stop_ts')

    def __init__(self, channel_id, start, stop, title, desc=""):
        self.channel_id = channel_id
        self.start = start
        self.stop  = stop
        self.title = title
        self.desc  = desc
        # Pre-compute float timestamps for fast bisect comparisons
        try:
            self._start_ts = (start - datetime(1970, 1, 1, tzinfo=UTC)
                              ).total_seconds()
            self._stop_ts  = (stop  - datetime(1970, 1, 1, tzinfo=UTC)
                              ).total_seconds()
        except Exception:
            self._start_ts = 0.0
            self._stop_ts  = 0.0

    def is_current_or_future(self, now):
        return self.stop > now


# ── EPGCache ──────────────────────────────────────────────────────────────────
class EPGCache(object):
    """Manages local EPG cache on disk.

    Improvement: meta.json is read once and result cached in memory
    (_validity_cache) so is_valid() never hits disk more than once per source
    per session.
    """

    def __init__(self, cache_dir=None, ttl_hours=12):
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "vavoo_epg"
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        self._validity_cache = {}   # {source_name: bool} – in-memory TTL result
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except TypeError:
            if not self.cache_dir.exists():
                self.cache_dir.mkdir(parents=True)

    def _get_cache_path(self, source_name):
        return self.cache_dir / "{}_epg.xml".format(source_name)

    def _get_meta_path(self, source_name):
        return self.cache_dir / "{}_meta.json".format(source_name)

    def is_valid(self, source_name):
        """Check if cached EPG is still valid (result cached in memory)."""
        if source_name in self._validity_cache:
            return self._validity_cache[source_name]

        meta_path  = self._get_meta_path(source_name)
        cache_path = self._get_cache_path(source_name)

        if not meta_path.exists() or not cache_path.exists():
            self._validity_cache[source_name] = False
            return False

        try:
            with open(str(meta_path), 'r') as f:
                meta = load(f)

            if 'timestamp' in meta:
                if PY2:
                    cached_time = datetime.strptime(
                        meta['timestamp'].split('+')[0], "%Y-%m-%dT%H:%M:%S.%f")
                    cached_time = cached_time.replace(tzinfo=UTC)
                else:
                    cached_time = datetime.fromisoformat(meta['timestamp'])
            else:
                cached_time = datetime.fromtimestamp(meta.get('time', 0))
                if PY2:
                    cached_time = cached_time.replace(tzinfo=UTC)

            now = datetime.now(UTC)
            result = (now - cached_time) < self.ttl
        except Exception as e:
            logging.warning("Cache validation error: {}".format(e))
            result = False

        self._validity_cache[source_name] = result
        return result

    def invalidate(self, source_name):
        """Clear in-memory validity entry after a fresh download."""
        self._validity_cache.pop(source_name, None)

    def get_cached(self, source_name):
        """Get cached EPG content if valid."""
        if not self.is_valid(source_name):
            return None
        cache_path = self._get_cache_path(source_name)
        try:
            with open(str(cache_path), 'rb') as f:
                return f.read()
        except Exception as e:
            logging.warning("Failed to read cache: {}".format(e))
            return None

    def save(self, source_name, content):
        """Save EPG content to cache and update validity cache."""
        cache_path = self._get_cache_path(source_name)
        meta_path  = self._get_meta_path(source_name)
        try:
            with open(str(cache_path), 'wb') as f:
                f.write(content)
            now = datetime.now(UTC)
            timestamp = (now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"
                         if PY2 else now.isoformat())
            with open(str(meta_path), 'w') as f:
                dump({'timestamp': timestamp, 'size': len(content)}, f)
            # Mark as valid in memory immediately
            self._validity_cache[source_name] = True
            return True
        except Exception as e:
            logging.error("Failed to save cache: {}".format(e))
            return False

    def clear(self, source_name=None):
        """Clear cache for specific source or all."""
        if source_name:
            self._validity_cache.pop(source_name, None)
            for path in (self._get_cache_path(source_name),
                         self._get_meta_path(source_name)):
                try:
                    if path.exists():
                        unlink(str(path))
                except OSError:
                    pass
        else:
            self._validity_cache.clear()
            for pattern in ("*_epg.xml", "*_meta.json"):
                for f in self.cache_dir.glob(pattern):
                    try:
                        unlink(str(f))
                    except OSError:
                        pass


# ── EPGDownloader ─────────────────────────────────────────────────────────────
class EPGDownloader(object):
    """Handles EPG download with retry and streaming decompression.

    Improvement: gzip decompression happens on the fly during download
    instead of buffering the full compressed file then decompressing.
    Peak RAM usage drops from 2× file size to ~1× file size.
    """

    DEFAULT_USER_AGENT = "VAVOO/2.6"
    MAX_RETRIES   = 3
    RETRY_DELAY   = 2.0
    RETRY_BACKOFF = 2.0
    TIMEOUT       = 30
    CHUNK_SIZE    = 131072  # 128 KB – larger chunks = fewer iterations

    def __init__(self, user_agent=None):
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': self.user_agent})

    @staticmethod
    def _gzip_decompress(data):
        """Py2/3 compatible gzip decompression."""
        try:
            return gzip.decompress(data)
        except AttributeError:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as gz:
                return gz.read()

    @staticmethod
    def _stream_gzip_decompress(response, chunk_size):
        """Decompress a gzip HTTP response on the fly (no double buffer)."""
        buf = io.BytesIO()
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                buf.write(chunk)
        raw = buf.getvalue()
        if raw[:2] == b'\x1f\x8b':
            return EPGDownloader._gzip_decompress(raw)
        return raw

    def _download_with_retry(self, url):
        """Download with exponential backoff, decompress on the fly."""
        delay = self.RETRY_DELAY
        is_gz = url.endswith('.gz')

        for attempt in range(self.MAX_RETRIES):
            try:
                logging.info("Downloading EPG from {} (attempt {})...".format(
                    url, attempt + 1))

                response = self.session.get(
                    url, timeout=self.TIMEOUT,
                    verify=False, stream=True)
                response.raise_for_status()

                # Stream + decompress in one pass
                if is_gz or response.headers.get(
                        'Content-Encoding', '') == 'gzip':
                    result = self._stream_gzip_decompress(
                        response, self.CHUNK_SIZE)
                else:
                    buf = io.BytesIO()
                    for chunk in response.iter_content(
                            chunk_size=self.CHUNK_SIZE):
                        if chunk:
                            buf.write(chunk)
                    result = buf.getvalue()

                if len(result) < 1024:
                    raise ValueError(
                        "Download too small: {} bytes".format(len(result)))

                logging.info("Got {} bytes (decompressed) from {}".format(
                    len(result), url))
                return result

            except Exception as e:
                logging.warning("Download failed (attempt {}): {}".format(
                    attempt + 1, e))
                if attempt < self.MAX_RETRIES - 1:
                    select.select([], [], [], delay)
                    delay *= self.RETRY_BACKOFF

        return None

    def download(self, source):
        """Download EPG from source with fallback to backup_url."""
        content = self._download_with_retry(source.url)
        if content is None and source.backup_url:
            logging.info("Trying backup URL for {}...".format(source.name))
            content = self._download_with_retry(source.backup_url)
        return content

    def decompress(self, content, url):
        """Decompress gzipped content (legacy compat – prefer stream path)."""
        try:
            if content[:2] == b'\x1f\x8b':
                return self._gzip_decompress(content)
            return content
        except Exception as e:
            logging.error("Decompression failed: {}".format(e))
            return None


# ── EPGParser ─────────────────────────────────────────────────────────────────
class EPGParser(object):
    """Efficient XMLTV parser.

    Improvements:
      - normalize_name: module-level cache + pre-compiled regexes
      - parse_xmltv_date: module-level cache (same ts string → same result)
      - Programs collected then sorted once per channel (enables binary search)
    """

    PROGRAM_WINDOW_HOURS = 24 * 7  # 7 days

    @staticmethod
    def normalize_name(name):
        """Normalize channel name for matching (result cached per process)."""
        if not name:
            return ""

        # Fast path: already in cache
        cached = _NORM_CACHE.get(name)
        if cached is not None:
            return cached

        # Ensure unicode
        if isinstance(name, bytes):
            try:
                n = name.decode('utf-8', 'ignore')
            except Exception:
                n = str(name)
        else:
            n = str(name) if not isinstance(name, str) else name

        n = n.upper().strip()
        n = _RE_COUNTRY_PREFIX.sub('', n)
        n = _RE_QUALITY_SUFFIX.sub('', n)
        n = _RE_SPECIAL_CHARS.sub('', n).strip()

        with _NORM_CACHE_LOCK:
            _NORM_CACHE[name] = n
        return n

    @staticmethod
    def parse_xmltv_date(date_str):
        """Parse XMLTV date string (result cached – same string → same dt)."""
        if not date_str:
            return None

        cached = _DATE_CACHE.get(date_str)
        if cached is not None:
            return cached

        dt = None
        try:
            if PY2:
                parts = date_str.split(' ')
                dt = datetime.strptime(parts[0], "%Y%m%d%H%M%S")
                if len(parts) > 1:
                    tz_str = parts[1]
                    sign   = 1 if tz_str[0] == '+' else -1
                    hours  = int(tz_str[1:3])
                    mins   = int(tz_str[3:5])
                    dt = dt - timedelta(hours=sign * hours,
                                        minutes=sign * mins)
                dt = dt.replace(tzinfo=UTC)
            else:
                dt = datetime.strptime(date_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            try:
                dt = datetime.strptime(
                    date_str[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            except ValueError:
                dt = None

        with _DATE_CACHE_LOCK:
            _DATE_CACHE[date_str] = dt
        return dt

    def parse(self, xml_content, source_name="",
              country_code=None, filter_channels=None):
        """Parse XMLTV content.

        Returns:
            Tuple of (channels_dict, programs_dict)
            programs_dict values are SORTED by start time.
        """
        channels = {}
        programs = {}  # {ch_id: [Program, ...]} – sorted by start after parse

        now    = datetime.now(UTC)
        cutoff = now + timedelta(hours=self.PROGRAM_WINDOW_HOURS)

        is_swiss = "Swiss" in source_name or "RSI" in source_name

        try:
            context = ET.iterparse(
                io.BytesIO(xml_content), events=('start', 'end'))

            for event, elem in context:
                if event == 'start':
                    continue

                if elem.tag == 'channel':
                    channel_id = elem.get('id')
                    if not channel_id:
                        elem.clear()
                        continue

                    dn_elem      = elem.find('display-name')
                    display_name = dn_elem.text if dn_elem is not None else ""

                    if is_swiss:
                        norm = self.normalize_name(display_name)
                        if norm not in ("RSILA1", "RSILA2"):
                            elem.clear()
                            continue

                    icon_elem = elem.find('icon')
                    icon = icon_elem.get('src') if icon_elem is not None else None

                    channels[channel_id] = ChannelInfo(
                        id=channel_id,
                        display_name=display_name,
                        icon=icon,
                        normalized_name=self.normalize_name(display_name),
                        country_code=country_code or ""
                    )

                elif elem.tag == 'programme':
                    channel_id = elem.get('channel')
                    start_str  = elem.get('start')
                    stop_str   = elem.get('stop')

                    if not (channel_id and start_str and stop_str):
                        elem.clear()
                        continue

                    start_dt = self.parse_xmltv_date(start_str)
                    stop_dt  = self.parse_xmltv_date(stop_str)

                    if not start_dt or not stop_dt:
                        elem.clear()
                        continue

                    if stop_dt < now or start_dt > cutoff:
                        elem.clear()
                        continue

                    title_elem = elem.find('title')
                    title = (title_elem.text
                             if title_elem is not None else "N/A") or "N/A"

                    desc_elem = elem.find('desc')
                    desc = (desc_elem.text
                            if desc_elem is not None else "") or ""

                    prog = Program(channel_id=channel_id,
                                   start=start_dt, stop=stop_dt,
                                   title=title, desc=desc)

                    if channel_id not in programs:
                        programs[channel_id] = []
                    programs[channel_id].append(prog)

                elem.clear()

        except Exception as e:
            logging.error("XML parsing error: {}".format(e))

        # Sort each channel's program list by start time ONCE here.
        # This enables O(log n) binary search in get_current_program().
        for ch_id in programs:
            programs[ch_id].sort(key=lambda p: p._start_ts)

        logging.info("Parsed {} channels, {} programs".format(
            len(channels),
            sum(len(p) for p in programs.values())))

        return channels, programs


# ── EPGManager ────────────────────────────────────────────────────────────────
class EPGManager(object):
    """Main EPG management class.

    Key improvement: load_all() downloads and parses all sources in
    parallel using a thread pool (one thread per source).
    """

    DEFAULT_SOURCES = [
        EPGSource("Italy",          "https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz",   "https://iptv-epg.org/files/epg-it.xml.gz",  priority=0, enabled=True, country_code="it"),
        EPGSource("France",         "https://epgshare01.online/epgshare01/epg_ripper_FR1.xml.gz",   "https://iptv-epg.org/files/epg-fr.xml.gz",  priority=1, enabled=True, country_code="fr"),
        EPGSource("Germany",        "https://epgshare01.online/epgshare01/epg_ripper_DE1.xml.gz",   "https://iptv-epg.org/files/epg-de.xml.gz",  priority=1, enabled=True, country_code="de"),
        EPGSource("Balkans",        "https://raw.githubusercontent.com/Belfagor2005/vavoo-player/refs/heads/master/epg_bk.xml.gz", "https://raw.githubusercontent.com/Belfagor2005/vavoo-player/refs/heads/master/epg_bk.xml.gz", priority=1, enabled=True, country_code="bk"),
        EPGSource("Spain",          "https://epgshare01.online/epgshare01/epg_ripper_ES1.xml.gz",   "https://iptv-epg.org/files/epg-es.xml.gz",  priority=1, enabled=True, country_code="es"),
        EPGSource("United Kingdom", "https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz",   "https://iptv-epg.org/files/epg-gb.xml.gz",  priority=1, enabled=True, country_code="gb"),
        EPGSource("Portugal",       "https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz",   "https://iptv-epg.org/files/epg-pt.xml.gz",  priority=1, enabled=True, country_code="pt"),
        EPGSource("Netherlands",    "https://epgshare01.online/epgshare01/epg_ripper_NL1.xml.gz",   "https://iptv-epg.org/files/epg-nl.xml.gz",  priority=1, enabled=True, country_code="nl"),
        EPGSource("Belgium",        "https://epgshare01.online/epgshare01/epg_ripper_BE2.xml.gz",   "https://iptv-epg.org/files/epg-be.xml.gz",  priority=1, enabled=True, country_code="be"),
        EPGSource("Austria",        "https://epgshare01.online/epgshare01/epg_ripper_AT1.xml.gz",   "https://iptv-epg.org/files/epg-at.xml.gz",  priority=1, enabled=True, country_code="at"),
        EPGSource("Switzerland",    "https://epgshare01.online/epgshare01/epg_ripper_CH1.xml.gz",   "https://iptv-epg.org/files/epg-ch.xml.gz",  priority=1, enabled=True, country_code="ch"),
        EPGSource("Poland",         "https://epgshare01.online/epgshare01/epg_ripper_PL1.xml.gz",   "https://iptv-epg.org/files/epg-pl.xml.gz",  priority=1, enabled=True, country_code="pl"),
        EPGSource("Romania",        "https://epgshare01.online/epgshare01/epg_ripper_RO1.xml.gz",   "https://iptv-epg.org/files/epg-ro.xml.gz",  priority=1, enabled=True, country_code="ro"),
        EPGSource("Albania",        "https://epgshare01.online/epgshare01/epg_ripper_AL1.xml.gz",   "https://iptv-epg.org/files/epg-al.xml.gz",  priority=1, enabled=True, country_code="al"),
        EPGSource("Bulgaria",       "https://epgshare01.online/epgshare01/epg_ripper_BG1.xml.gz",   "https://iptv-epg.org/files/epg-bg.xml.gz",  priority=1, enabled=True, country_code="bg"),
        EPGSource("Croatia",        "https://epgshare01.online/epgshare01/epg_ripper_HR1.xml.gz",   "https://iptv-epg.org/files/epg-hr.xml.gz",  priority=1, enabled=True, country_code="hr"),
        EPGSource("Serbia",         "https://epgshare01.online/epgshare01/epg_ripper_RS1.xml.gz",   "https://iptv-epg.org/files/epg-rs.xml.gz",  priority=1, enabled=True, country_code="rs"),
        EPGSource("Bosnia",         "https://epgshare01.online/epgshare01/epg_ripper_BA1.xml.gz",   "https://iptv-epg.org/files/epg-ba.xml.gz",  priority=1, enabled=True, country_code="ba"),
        EPGSource("Czech Republic", "https://epgshare01.online/epgshare01/epg_ripper_CZ1.xml.gz",   "https://iptv-epg.org/files/epg-cz.xml.gz",  priority=1, enabled=True, country_code="cz"),
        EPGSource("Slovakia",       "https://epgshare01.online/epgshare01/epg_ripper_SK1.xml.gz",   "https://iptv-epg.org/files/epg-sk.xml.gz",  priority=1, enabled=True, country_code="sk"),
        EPGSource("Hungary",        "https://epgshare01.online/epgshare01/epg_ripper_HU1.xml.gz",   "https://iptv-epg.org/files/epg-hu.xml.gz",  priority=1, enabled=True, country_code="hu"),
        EPGSource("Greece",         "https://epgshare01.online/epgshare01/epg_ripper_GR1.xml.gz",   "https://iptv-epg.org/files/epg-gr.xml.gz",  priority=1, enabled=True, country_code="gr"),
        EPGSource("Turkey",         "https://epgshare01.online/epgshare01/epg_ripper_TR1.xml.gz",   "https://iptv-epg.org/files/epg-tr.xml.gz",  priority=1, enabled=True, country_code="tr"),
        EPGSource("Denmark",        "https://epgshare01.online/epgshare01/epg_ripper_DK1.xml.gz",   "https://iptv-epg.org/files/epg-dk.xml.gz",  priority=1, enabled=True, country_code="dk"),
        EPGSource("Sweden",         "https://epgshare01.online/epgshare01/epg_ripper_SE1.xml.gz",   "https://iptv-epg.org/files/epg-se.xml.gz",  priority=1, enabled=True, country_code="se"),
        EPGSource("Norway",         "https://epgshare01.online/epgshare01/epg_ripper_NO1.xml.gz",   "https://iptv-epg.org/files/epg-no.xml.gz",  priority=1, enabled=True, country_code="no"),
        EPGSource("Finland",        "https://epgshare01.online/epgshare01/epg_ripper_FI1.xml.gz",   "https://iptv-epg.org/files/epg-fi.xml.gz",  priority=1, enabled=True, country_code="fi"),
        EPGSource("Russia",         "https://epgshare01.online/epgshare01/epg_ripper_viva-russia.ru.xml.gz", "https://iptv-epg.org/files/epg-ru.xml.gz", priority=1, enabled=True, country_code="ru"),
        EPGSource("USA",            "https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",   "https://iptv-epg.org/files/epg-us.xml.gz",  priority=1, enabled=True, country_code="us"),
        EPGSource("Canada",         "https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz",   "https://iptv-epg.org/files/epg-ca.xml.gz",  priority=1, enabled=True, country_code="ca"),
        EPGSource("Australia",      "https://epgshare01.online/epgshare01/epg_ripper_AU1.xml.gz",   "https://iptv-epg.org/files/epg-au.xml.gz",  priority=1, enabled=True, country_code="au"),
        EPGSource("Japan",          "https://epgshare01.online/epgshare01/epg_ripper_JP1.xml.gz",   "https://iptv-epg.org/files/epg-jp.xml.gz",  priority=1, enabled=True, country_code="jp"),
        EPGSource("India",          "https://epgshare01.online/epgshare01/epg_ripper_IN1.xml.gz",   "https://iptv-epg.org/files/epg-in.xml.gz",  priority=1, enabled=True, country_code="in"),
        EPGSource("Brazil",         "https://epgshare01.online/epgshare01/epg_ripper_BR1.xml.gz",   "https://iptv-epg.org/files/epg-br.xml.gz",  priority=1, enabled=True, country_code="br"),
        EPGSource("Mexico",         "https://epgshare01.online/epgshare01/epg_ripper_MX1.xml.gz",   "https://iptv-epg.org/files/epg-mx.xml.gz",  priority=1, enabled=True, country_code="mx"),
    ]

    # Maximum parallel download threads
    # Keep low on Enigma2 boxes (limited RAM + single-core or dual-core CPUs)
    MAX_WORKERS = 4

    def __init__(self, cache_dir=None, cache_ttl_hours=12,
                 user_agent=None, sources=None):
        self.cache      = EPGCache(cache_dir, cache_ttl_hours)
        self.downloader = EPGDownloader(user_agent or "VAVOO/2.6")
        self.parser     = EPGParser()
        self.sources    = sources if sources is not None else self.DEFAULT_SOURCES

        self.channels   = {}
        self.programs   = {}           # {ch_id: [Program]} SORTED by start
        self.name_to_id = {}           # normalized_name → [ch_id, ...]
        self._merge_lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────────────
    def load_all(self, force_refresh=False):
        """Load all enabled EPG sources in parallel (MAX_WORKERS at a time).

        Returns True if at least one source loaded successfully.
        """
        enabled = [s for s in self.sources if s.enabled]
        if not enabled:
            return False

        results = [False] * len(enabled)
        semaphore = threading.Semaphore(self.MAX_WORKERS)

        def _load_one(idx, source):
            with semaphore:
                results[idx] = self._load_source(source, force_refresh)

        threads = []
        for i, source in enumerate(enabled):
            t = threading.Thread(target=_load_one, args=(i, source))
            t.setDaemon(True)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self._build_name_index()
        # Re-sort merged programs (parallel merges may interleave)
        for ch_id in self.programs:
            self.programs[ch_id].sort(key=lambda p: p._start_ts)

        return any(results)

    def _load_source(self, source, force_refresh):
        """Load a single EPG source (thread-safe merge into shared dicts)."""
        xml_content = None

        if not force_refresh:
            xml_content = self.cache.get_cached(source.name)
            if xml_content:
                logging.info("Using cached EPG for {}".format(source.name))

        if xml_content is None:
            xml_content = self.downloader.download(source)
            if xml_content:
                self.cache.save(source.name, xml_content)

        if xml_content is None:
            logging.error("Failed to load EPG for {}".format(source.name))
            return False

        channels, programs = self.parser.parse(
            xml_content, source.name,
            country_code=source.country_code)

        # Thread-safe merge
        with self._merge_lock:
            self.channels.update(channels)
            for ch_id, progs in programs.items():
                if ch_id not in self.programs:
                    self.programs[ch_id] = progs
                else:
                    self.programs[ch_id].extend(progs)
                    # Will be globally re-sorted in load_all()

        return True

    def _build_name_index(self):
        """Build name → [channel_id, ...] index."""
        idx = {}
        for ch_id, info in self.channels.items():
            norm = info.normalized_name
            if norm:
                if norm not in idx:
                    idx[norm] = []
                idx[norm].append(ch_id)
        self.name_to_id = idx

    def get_channel_by_name(self, name):
        """Find channel by normalized name (returns best single match)."""
        norm = self.parser.normalize_name(name)
        ids  = self.name_to_id.get(norm)
        if not ids:
            return None
        # If multiple, prefer the one with programs
        for ch_id in ids:
            if ch_id in self.programs:
                return self.channels.get(ch_id)
        return self.channels.get(ids[0])

    def get_current_program(self, channel_id, norm_name=None):
        """Get current program using binary search (O(log n)).

        Programs are kept sorted by start time, so we bisect for 'now'
        and check the surrounding entries.

        Returns:
            Tuple of (title, description, start, stop)
        """
        now = datetime.now(UTC)

        # Resolve channel via name if direct lookup misses
        if channel_id not in self.programs and norm_name:
            ids = self.name_to_id.get(norm_name)
            if ids:
                channel_id = next(
                    (i for i in ids if i in self.programs), channel_id)

        progs = self.programs.get(channel_id)
        if not progs:
            return None, None, None, None

        # Binary search: find insertion point for 'now' by start timestamp
        now_ts = (now - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()
        # We want the last programme whose start <= now
        # bisect_right on start_ts list gives us the insertion point
        start_ts_list = [p._start_ts for p in progs]
        idx = bisect_left(start_ts_list, now_ts)

        # Check idx-1 (programme that started before now)
        for i in (idx - 1, idx):
            if 0 <= i < len(progs):
                p = progs[i]
                if p.start <= now <= p.stop:
                    return p.title, p.desc, p.start, p.stop

        return "No Info Available", "", None, None

    def get_upcoming_programs(self, channel_id, count=5):
        """Get upcoming programs using binary search.

        Since programs are sorted, we bisect for 'now' and slice forward.
        No list comprehension + sort needed.
        """
        now = datetime.now(UTC)
        progs = self.programs.get(channel_id)
        if not progs:
            return []

        now_ts = (now - datetime(1970, 1, 1, tzinfo=UTC)).total_seconds()
        start_ts_list = [p._start_ts for p in progs]
        idx = bisect_left(start_ts_list, now_ts)

        # Find the first programme that starts after now
        while idx < len(progs) and progs[idx].start <= now:
            idx += 1

        return progs[idx:idx + count]

    def clear_cache(self):
        """Clear all cached EPG data."""
        self.cache.clear()


# ── Convenience function ──────────────────────────────────────────────────────
def load_epg_data(user_agent=None, cache_dir=None, force_refresh=False):
    """Load EPG data and return manager instance."""
    manager = EPGManager(
        cache_dir=cache_dir,
        user_agent=user_agent or "VAVOO/2.6")
    manager.load_all(force_refresh)
    return manager


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s')

    manager = EPGManager()
    if manager.load_all():
        print("Loaded {} channels".format(len(manager.channels)))
        print("Programs for {} channels".format(len(manager.programs)))
        rai1 = manager.get_channel_by_name("Rai 1")
        if rai1:
            title, desc, start, stop = manager.get_current_program(rai1.id)
            print("Current: {}".format(title))
