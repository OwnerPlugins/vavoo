# -*- coding: utf-8 -*-
from __future__ import print_function, absolute_import, division
from datetime import datetime, timedelta
from json import load, dump
from os import unlink
from re import IGNORECASE, sub
from six import text_type
import gzip
import io
import logging
import requests
import select
import xml.etree.ElementTree as ET

from . import PY2
"""
EPG Manager - Optimized EPG download and caching module.

Features:
- Local disk cache with configurable TTL
- Streaming download with on-the-fly decompression
- Retry with exponential backoff
- Memory-efficient XML parsing
- Program filtering (only current/future programs)
"""
# Modified by lululla 20260314
# Python 2/3 compatibility


# Disable SSL warnings
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except BaseException:
    pass


if PY2:
    from pathlib2 import Path

    # Python 2 doesn't have timezone, create UTC
    class UTC(datetime.tzinfo):
        def utcoffset(self, dt):
            return timedelta(0)

        def tzname(self, dt):
            return "UTC"

        def dst(self, dt):
            return timedelta(0)

    UTC = UTC()
else:
    from pathlib import Path
    from datetime import timezone
    UTC = timezone.utc


# Simple class instead of dataclass for Py2 compatibility
class EPGSource(object):
    """Configuration for an EPG source."""

    def __init__(
            self,
            name,
            url,
            backup_url=None,
            enabled=True,
            priority=0,
            country_code=""):
        self.name = name
        self.url = url
        self.backup_url = backup_url
        self.enabled = enabled
        self.priority = priority
        self.country_code = country_code


class ChannelInfo(object):
    """EPG channel information."""

    def __init__(
            self,
            id,
            display_name,
            icon=None,
            normalized_name="",
            country_code=""):
        self.id = id
        self.display_name = display_name
        self.icon = icon
        self.normalized_name = normalized_name
        self.country_code = country_code


class Program(object):
    """EPG program information."""

    def __init__(self, channel_id, start, stop, title, desc=""):
        self.channel_id = channel_id
        self.start = start
        self.stop = stop
        self.title = title
        self.desc = desc

    def is_current_or_future(self, now):
        """Check if program is currently running or in the future."""
        return self.stop > now


class EPGCache(object):
    """Manages local EPG cache on disk."""

    def __init__(self, cache_dir=None, ttl_hours=12):
        if cache_dir is None:
            cache_dir = Path.home() / ".cache" / "vavoo_epg"
        self.cache_dir = cache_dir
        self.ttl = timedelta(hours=ttl_hours)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        except TypeError:
            # Python 2 doesn't have exist_ok
            if not self.cache_dir.exists():
                self.cache_dir.mkdir(parents=True)

    def _get_cache_path(self, source_name):
        return self.cache_dir / "{}_epg.xml".format(source_name)

    def _get_meta_path(self, source_name):
        return self.cache_dir / "{}_meta.json".format(source_name)

    def is_valid(self, source_name):
        """Check if cached EPG is still valid."""
        meta_path = self._get_meta_path(source_name)
        cache_path = self._get_cache_path(source_name)

        if not meta_path.exists() or not cache_path.exists():
            return False

        try:
            with open(str(meta_path), 'r') as f:
                meta = load(f)

            # Handle both ISO format and timestamp for backward compatibility
            if 'timestamp' in meta:
                if PY2:
                    # Python 2 datetime doesn't have fromisoformat
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
            return (now - cached_time) < self.ttl
        except Exception as e:
            logging.warning("Cache validation error: {}".format(e))
            return False

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
        """Save EPG content to cache."""
        cache_path = self._get_cache_path(source_name)
        meta_path = self._get_meta_path(source_name)

        try:
            with open(str(cache_path), 'wb') as f:
                f.write(content)

            # Prepare metadata
            now = datetime.now(UTC)
            if PY2:
                timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.%f") + "+00:00"
            else:
                timestamp = now.isoformat()

            meta = {
                'timestamp': timestamp,
                'size': len(content)
            }

            with open(str(meta_path), 'w') as f:
                dump(meta, f)
            return True
        except Exception as e:
            logging.error("Failed to save cache: {}".format(e))
            return False

    def clear(self, source_name=None):
        """Clear cache for specific source or all."""
        if source_name:
            cache_path = self._get_cache_path(source_name)
            meta_path = self._get_meta_path(source_name)

            # Safe unlink for Py2
            try:
                if cache_path.exists():
                    unlink(str(cache_path))
            except OSError:
                pass
            try:
                if meta_path.exists():
                    unlink(str(meta_path))
            except OSError:
                pass
        else:
            for f in self.cache_dir.glob("*_epg.xml"):
                try:
                    unlink(str(f))
                except OSError:
                    pass
            for f in self.cache_dir.glob("*_meta.json"):
                try:
                    unlink(str(f))
                except OSError:
                    pass


class EPGDownloader(object):
    """Handles EPG download with retry and streaming."""

    DEFAULT_USER_AGENT = "VAVOO/2.6"
    MAX_RETRIES = 3
    RETRY_DELAY = 2.0
    RETRY_BACKOFF = 2.0
    TIMEOUT = 30
    CHUNK_SIZE = 65536  # 64KB chunks

    def __init__(self, user_agent=None):
        if user_agent is None:
            user_agent = self.DEFAULT_USER_AGENT
        self.user_agent = user_agent
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': user_agent})

    def _download_with_retry(self, url):
        """Download with exponential backoff retry."""
        delay = self.RETRY_DELAY

        for attempt in range(self.MAX_RETRIES):
            try:
                logging.info(
                    "Downloading EPG from {} (attempt {})...".format(
                        url, attempt + 1))

                response = self.session.get(
                    url,
                    timeout=self.TIMEOUT,
                    verify=False,
                    stream=True
                )
                response.raise_for_status()

                # Stream download to memory
                content = io.BytesIO()
                total = 0

                for chunk in response.iter_content(chunk_size=self.CHUNK_SIZE):
                    if chunk:
                        content.write(chunk)
                        total += len(chunk)

                result = content.getvalue()
                logging.info(
                    "Downloaded {} bytes from {}".format(
                        len(result), url))

                if len(result) < 1024:
                    raise ValueError(
                        "Download too small: {} bytes".format(
                            len(result)))

                return result

            except Exception as e:
                logging.warning(
                    "Download failed (attempt {}): {}".format(
                        attempt + 1, e))
                if attempt < self.MAX_RETRIES - 1:
                    select.select([], [], [], delay)
                    delay *= self.RETRY_BACKOFF

        return None

    def download(self, source):
        """Download EPG from source with fallback."""
        content = self._download_with_retry(source.url)

        if content is None and source.backup_url:
            logging.info("Trying backup URL for {}...".format(source.name))
            content = self._download_with_retry(source.backup_url)

        return content

    def decompress(self, content, url):
        """Decompress gzipped content if needed."""
        try:
            if url.endswith('.gz'):
                logging.debug("Decompressing GZIP content...")
                return gzip.decompress(content)
            return content
        except Exception as e:
            logging.error("Decompression failed: {}".format(e))
            return None


class EPGParser(object):
    """Efficient XMLTV parser with filtering."""

    # Only keep programs within this time window
    PROGRAM_WINDOW_HOURS = 24 * 7  # 7 days

    @staticmethod
    def normalize_name(name):
        """Normalize channel name for matching."""
        if not name:
            return ""

        # Handle Unicode compatibly with Py2/Py3
        if isinstance(name, text_type):
            if PY2:
                name = name.encode('utf-8')
        else:
            name = text_type(name)

        n = name.upper().strip()

        # Remove country prefixes
        n = sub(r'^(IT|CH)\s*-\s*', '', n, flags=IGNORECASE)

        # Remove quality suffixes
        n = sub(r'\s+(HD|FHD|SD|HEVC|H265|4K).*', '', n, flags=IGNORECASE)

        # Remove special chars
        n = sub(r'[^A-Z0-9]', '', n)

        return n.strip()

    @staticmethod
    def parse_xmltv_date(date_str):
        """Parse XMLTV date format."""
        if not date_str:
            return None
        try:
            # Format: YYYYMMDDHHMMSS +ZZZZ
            # Python 2 compatible parsing
            if PY2:
                # Remove timezone part for parsing
                parts = date_str.split(' ')
                dt = datetime.strptime(parts[0], "%Y%m%d%H%M%S")
                if len(parts) > 1:
                    # Parse timezone offset
                    tz_str = parts[1]
                    sign = 1 if tz_str[0] == '+' else -1
                    hours = int(tz_str[1:3])
                    minutes = int(tz_str[3:5])
                    tz_offset = timedelta(
                        hours=sign * hours, minutes=sign * minutes)
                    dt = dt - tz_offset  # Convert to UTC
                return dt.replace(tzinfo=UTC)
            else:
                return datetime.strptime(date_str, "%Y%m%d%H%M%S %z")
        except ValueError:
            try:
                # Try without timezone
                dt = datetime.strptime(date_str[:14], "%Y%m%d%H%M%S")
                return dt.replace(tzinfo=UTC)
            except ValueError:
                return None

    def parse(
            self,
            xml_content,
            source_name="",
            country_code=None,
            filter_channels=None):
        """Parse XMLTV content efficiently.

        Returns:
            Tuple of (channels_dict, programs_dict)
        """
        channels = {}
        programs = {}

        now = datetime.now(UTC)
        cutoff = now + timedelta(hours=self.PROGRAM_WINDOW_HOURS)

        try:
            # Use iterparse for memory efficiency
            context = ET.iterparse(
                io.BytesIO(xml_content), events=(
                    'start', 'end'))

            for event, elem in context:
                if event == 'start':
                    continue

                if elem.tag == 'channel':
                    channel_id = elem.get('id')
                    if not channel_id:
                        elem.clear()
                        continue

                    display_name_elem = elem.find('display-name')
                    display_name = display_name_elem.text if display_name_elem is not None else ""

                    # Filter Swiss channels (RSI only)
                    if "Swiss" in source_name or "RSI" in source_name:
                        norm = self.normalize_name(display_name)
                        if norm not in ["RSILA1", "RSILA2"]:
                            elem.clear()
                            continue

                    icon_elem = elem.find('icon')
                    icon = icon_elem.get(
                        'src') if icon_elem is not None else None

                    channels[channel_id] = ChannelInfo(
                        id=channel_id,
                        display_name=display_name,
                        icon=icon,
                        normalized_name=self.normalize_name(display_name),
                        country_code=country_code or ""
                    )

                elif elem.tag == 'programme':
                    channel_id = elem.get('channel')
                    start_str = elem.get('start')
                    stop_str = elem.get('stop')

                    if not channel_id or not start_str or not stop_str:
                        elem.clear()
                        continue

                    start_dt = self.parse_xmltv_date(start_str)
                    stop_dt = self.parse_xmltv_date(stop_str)

                    if not start_dt or not stop_dt:
                        elem.clear()
                        continue

                    # Filter old programs
                    if stop_dt < now:
                        elem.clear()
                        continue

                    # Filter far future programs
                    if start_dt > cutoff:
                        elem.clear()
                        continue

                    title_elem = elem.find('title')
                    title = title_elem.text if title_elem is not None else "N/A"

                    desc_elem = elem.find('desc')
                    desc = desc_elem.text if desc_elem is not None else ""

                    prog = Program(
                        channel_id=channel_id,
                        start=start_dt,
                        stop=stop_dt,
                        title=title,
                        desc=desc or ""
                    )

                    if channel_id not in programs:
                        programs[channel_id] = []
                    programs[channel_id].append(prog)

                # Clear element to free memory
                elem.clear()

        except Exception as e:
            logging.error("XML parsing error: {}".format(e))

        logging.info(
            "Parsed {} channels, {} programs".format(
                len(channels), sum(
                    len(p) for p in programs.values())))
        return channels, programs


class EPGManager(object):
    """Main EPG management class combining all components."""

    DEFAULT_SOURCES = [
        EPGSource(
            name="Italy",
            url="https://epgshare01.online/epgshare01/epg_ripper_IT1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-it.xml.gz",
            priority=0,
            enabled=True,
            country_code="it"
        ),
        EPGSource(
            name="France",
            url="https://epgshare01.online/epgshare01/epg_ripper_FR1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-fr.xml.gz",
            priority=1,
            enabled=True,
            country_code="fr"
        ),
        EPGSource(
            name="Germany",
            url="https://epgshare01.online/epgshare01/epg_ripper_DE1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-de.xml.gz.gz",
            priority=1,
            enabled=True,
            country_code="de"
        ),
        EPGSource(
            name="Balkans",
            url="https://raw.githubusercontent.com/Belfagor2005/vavoo-player/refs/heads/master/epg_bk.xml.gz",
            backup_url="https://raw.githubusercontent.com/Belfagor2005/vavoo-player/refs/heads/master/epg_bk.xml.gz",
            priority=1,
            enabled=True,
            country_code="bk"
        ),
        EPGSource(
            name="Spain",
            url="https://epgshare01.online/epgshare01/epg_ripper_ES1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-es.xml.gz",
            priority=1,
            enabled=True,
            country_code="es"
        ),
        EPGSource(
            name="United Kingdom",
            url="https://epgshare01.online/epgshare01/epg_ripper_UK1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-gb.xml.gz",
            priority=1,
            enabled=True,
            country_code="gb"
        ),
        EPGSource(
            name="Portugal",
            url="https://epgshare01.online/epgshare01/epg_ripper_PT1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-pt.xml.gz",
            priority=1,
            enabled=True,
            country_code="pt"
        ),
        EPGSource(
            name="Netherlands",
            url="https://epgshare01.online/epgshare01/epg_ripper_NL1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-nl.xml.gz",
            priority=1,
            enabled=True,
            country_code="nl"
        ),
        EPGSource(
            name="Belgium",
            url="https://epgshare01.online/epgshare01/epg_ripper_BE2.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-be.xml.gz",
            priority=1,
            enabled=True,
            country_code="be"
        ),
        EPGSource(
            name="Austria",
            url="https://epgshare01.online/epgshare01/epg_ripper_AT1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-at.xml.gz",
            priority=1,
            enabled=True,
            country_code="at"
        ),
        EPGSource(
            name="Switzerland",
            url="https://epgshare01.online/epgshare01/epg_ripper_CH1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-ch.xml.gz",
            priority=1,
            enabled=True,
            country_code="ch"
        ),
        EPGSource(
            name="Poland",
            url="https://epgshare01.online/epgshare01/epg_ripper_PL1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-pl.xml.gz",
            priority=1,
            enabled=True,
            country_code="pl"
        ),
        EPGSource(
            name="Romania",
            url="https://epgshare01.online/epgshare01/epg_ripper_RO1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-ro.xml.gz",
            priority=1,
            enabled=True,
            country_code="ro"
        ),
        EPGSource(
            name="Albania",
            url="https://epgshare01.online/epgshare01/epg_ripper_AL1.xml.gz",
            # url="https://raw.githubusercontent.com/Belfagor2005/vavoo-player/refs/heads/master/epg_bk.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-al.xml.gz",
            priority=1,
            enabled=True,
            country_code="al"
        ),
        EPGSource(
            name="Bulgaria",
            url="https://epgshare01.online/epgshare01/epg_ripper_BG1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-bg.xml.gz",
            priority=1,
            enabled=True,
            country_code="bg"
        ),
        EPGSource(
            name="Croatia",
            url="https://epgshare01.online/epgshare01/epg_ripper_HR1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-hr.xml.gz",
            priority=1,
            enabled=True,
            country_code="hr"
        ),
        EPGSource(
            name="Serbia",
            url="https://epgshare01.online/epgshare01/epg_ripper_RS1.xml.gz",
            # url="https://raw.githubusercontent.com/Belfagor2005/vavoo-player/refs/heads/master/epg_bk.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-rs.xml.gz",
            priority=1,
            enabled=True,
            country_code="rs"
        ),
        EPGSource(
            name="Bosnia",
            url="https://epgshare01.online/epgshare01/epg_ripper_BA1.xml.gz",
            # url="https://raw.githubusercontent.com/Belfagor2005/vavoo-player/refs/heads/master/epg_bk.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-ba.xml.gz",
            priority=1,
            enabled=True,
            country_code="ba"
        ),
        EPGSource(
            name="Czech Republic",
            url="https://epgshare01.online/epgshare01/epg_ripper_CZ1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-cz.xml.gz",
            priority=1,
            enabled=True,
            country_code="cz"
        ),
        EPGSource(
            name="Slovakia",
            url="https://epgshare01.online/epgshare01/epg_ripper_SK1.xml.gz",
            # url="https://raw.githubusercontent.com/Belfagor2005/vavoo-player/refs/heads/master/epg_bk.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-sk.xml.gz",
            priority=1,
            enabled=True,
            country_code="sk"
        ),
        EPGSource(
            name="Hungary",
            url="https://epgshare01.online/epgshare01/epg_ripper_HU1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-hu.xml.gz",
            priority=1,
            enabled=True,
            country_code="hu"
        ),
        EPGSource(
            name="Greece",
            url="https://epgshare01.online/epgshare01/epg_ripper_GR1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-gr.xml.gz",
            priority=1,
            enabled=True,
            country_code="gr"
        ),
        EPGSource(
            name="Turkey",
            url="https://epgshare01.online/epgshare01/epg_ripper_TR1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-tr.xml.gz",
            priority=1,
            enabled=True,
            country_code="tr"
        ),
        EPGSource(
            name="Denmark",
            url="https://epgshare01.online/epgshare01/epg_ripper_DK1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-dk.xml.gz",
            priority=1,
            enabled=True,
            country_code="dk"
        ),
        EPGSource(
            name="Sweden",
            url="https://epgshare01.online/epgshare01/epg_ripper_SE1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-se.xml.gz",
            priority=1,
            enabled=True,
            country_code="se"
        ),
        EPGSource(
            name="Norway",
            url="https://epgshare01.online/epgshare01/epg_ripper_NO1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-no.xml.gz",
            priority=1,
            enabled=True,
            country_code="no"
        ),
        EPGSource(
            name="Finland",
            url="https://epgshare01.online/epgshare01/epg_ripper_FI1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-fi.xml.gz",
            priority=1,
            enabled=True,
            country_code="fi"
        ),
        EPGSource(
            name="Russia",
            url="https://epgshare01.online/epgshare01/epg_ripper_viva-russia.ru.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-ru.xml.gz",
            priority=1,
            enabled=True,
            country_code="ru"
        ),
        EPGSource(
            name="USA",
            url="https://epgshare01.online/epgshare01/epg_ripper_US2.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-us.xml.gz",
            priority=1,
            enabled=True,
            country_code="us"
        ),
        EPGSource(
            name="Canada",
            url="https://epgshare01.online/epgshare01/epg_ripper_CA2.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-ca.xml.gz",
            priority=1,
            enabled=True,
            country_code="ca"
        ),
        EPGSource(
            name="Australia",
            url="https://epgshare01.online/epgshare01/epg_ripper_AU1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-au.xml.gz",
            priority=1,
            enabled=True,
            country_code="au"
        ),
        EPGSource(
            name="Japan",
            url="https://epgshare01.online/epgshare01/epg_ripper_JP1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-jp.xml.gz",
            priority=1,
            enabled=True,
            country_code="jp"
        ),
        EPGSource(
            name="India",
            url="https://epgshare01.online/epgshare01/epg_ripper_IN1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-in.xml.gz",
            priority=1,
            enabled=True,
            country_code="in"
        ),
        EPGSource(
            name="Brazil",
            url="https://epgshare01.online/epgshare01/epg_ripper_BR1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-br.xml.gz",
            priority=1,
            enabled=True,
            country_code="br"
        ),
        EPGSource(
            name="Mexico",
            url="https://epgshare01.online/epgshare01/epg_ripper_MX1.xml.gz",
            backup_url="https://iptv-epg.org/files/epg-mx.xml.gz",
            priority=1,
            enabled=True,
            country_code="mx"
        ),
    ]

    def __init__(
            self,
            cache_dir=None,
            cache_ttl_hours=12,
            user_agent=None,
            sources=None):
        if user_agent is None:
            user_agent = "VAVOO/2.6"
        self.cache = EPGCache(cache_dir, cache_ttl_hours)
        self.downloader = EPGDownloader(user_agent)
        self.parser = EPGParser()
        self.sources = sources if sources is not None else self.DEFAULT_SOURCES

        # In-memory storage
        self.channels = {}
        self.programs = {}
        self.name_to_id = {}  # normalized name -> channel id

    def load_all(self, force_refresh=False):
        """Load all EPG sources.

        Args:
            force_refresh: If True, ignore cache and download fresh.

        Returns:
            True if at least one source loaded successfully.
        """
        success = False

        for source in self.sources:
            if not source.enabled:
                continue

            if self._load_source(source, force_refresh):
                success = True

        self._build_name_index()
        return success

    def _load_source(self, source, force_refresh):
        """Load a single EPG source."""
        xml_content = None

        # Try cache first
        if not force_refresh:
            xml_content = self.cache.get_cached(source.name)
            if xml_content:
                logging.info("Using cached EPG for {}".format(source.name))

        # Download if not cached
        if xml_content is None:
            gz_content = self.downloader.download(source)
            if gz_content:
                xml_content = self.downloader.decompress(
                    gz_content, source.url)
                if xml_content:
                    self.cache.save(source.name, xml_content)

        if xml_content is None:
            logging.error("Failed to load EPG for {}".format(source.name))
            return False

        # Parse and merge
        channels, programs = self.parser.parse(
            xml_content, source.name, country_code=source.country_code)

        # Merge into main storage
        self.channels.update(channels)
        for ch_id, progs in programs.items():
            if ch_id not in self.programs:
                self.programs[ch_id] = []
            self.programs[ch_id].extend(progs)

        return True

    def _build_name_index(self):
        """Build index for name-based lookups."""
        self.name_to_id = {}
        for ch_id, info in self.channels.items():
            self.name_to_id[info.normalized_name] = ch_id

    def get_channel_by_name(self, name):
        """Find channel by normalized name."""
        norm = self.parser.normalize_name(name)
        ch_id = self.name_to_id.get(norm)
        return self.channels.get(ch_id) if ch_id else None

    def get_current_program(self, channel_id, norm_name=None):
        """Get current program for a channel.

        Returns:
            Tuple of (title, description, start, stop)
        """
        now = datetime.now(UTC)

        # Try to find channel ID from name if not found
        if channel_id not in self.programs and norm_name:
            channel_id = self.name_to_id.get(norm_name, channel_id)

        if channel_id not in self.programs:
            return None, None, None, None

        for prog in self.programs[channel_id]:
            if prog.start <= now <= prog.stop:
                return prog.title, prog.desc, prog.start, prog.stop

        return "No Info Available", "", None, None

    def get_upcoming_programs(self, channel_id, count=5):
        """Get upcoming programs for a channel."""
        now = datetime.now(UTC)

        if channel_id not in self.programs:
            return []

        upcoming = [p for p in self.programs[channel_id] if p.start > now]
        upcoming.sort(key=lambda p: p.start)

        return upcoming[:count]

    def clear_cache(self):
        """Clear all cached EPG data."""
        self.cache.clear()


# Convenience function for backward compatibility
def load_epg_data(user_agent=None, cache_dir=None, force_refresh=False):
    """Load EPG data and return manager instance."""
    if user_agent is None:
        user_agent = "VAVOO/2.6"
    manager = EPGManager(cache_dir=cache_dir, user_agent=user_agent)
    manager.load_all(force_refresh)
    return manager


if __name__ == "__main__":
    # Test the module
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    manager = EPGManager()
    if manager.load_all():
        print("Loaded {} channels".format(len(manager.channels)))
        print("Loaded programs for {} channels".format(len(manager.programs)))

        # Test lookup
        rai1 = manager.get_channel_by_name("Rai 1")
        if rai1:
            print("Found RAI 1: {}".format(rai1.display_name))
            title, desc, start, stop = manager.get_current_program(rai1.id)
            print("Current program: {}".format(title))
