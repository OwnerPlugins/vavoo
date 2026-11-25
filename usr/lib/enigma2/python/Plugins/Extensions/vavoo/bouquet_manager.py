#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import io
import time
import glob
import threading
try:
    import urllib3
except ImportError:
    urllib3 = None
import select
from json import loads
from os import listdir, remove, rename
from os.path import exists as file_exists, isfile, join, basename
from re import search
from Components.config import config
from twisted.internet import reactor

from .vUtils import (
    debug,
    decodeHtml,
    getUrl,
    flush_unmatched_cache,
    get_country_code_from_bouquet_name,
    get_epg_matcher,
    is_proxy_ready,
    is_proxy_running,
    make_print,
    remove_parentheses,
    ReloadBouquets,
    sanitizeFilename,
    save_unmatched,
    trace_error,
    unique_fallback_sref,
    update_complete_cache,
    update_epg_sources,
    write_epg_mapping_file,
    ensure_sref_trailing_colon,
    prune_epg_mapping_file,
    prune_epg_mapping_files,
)
from . import vUtils
from .vavoo_proxy import run_proxy_in_background
from . import (
    PORT,
    PROXY_HOST,
    ENIGMA_PATH,
    group_separators,
    literals_for,
)
from . import vavoo_store

"""
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin                             #
#  Created by Lululla (https://github.com/Belfagor2005) #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0    #
#  Last Modified: 20260501                              #
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
__author__ = "Lululla"
__license__ = "CC BY-NC-SA 4.0"

print = make_print("BOUQUET")

try:
    from urllib.parse import unquote, quote
except ImportError:
    from urllib import unquote, quote


# Disable SSL warnings
if urllib3 is not None:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _sanitize_name_for_path(name):
    """Strip path-separator and traversal sequences from a country/
    category name before it's embedded in a bouquet filename.

    name comes from Vavoo's remote, mirror-switchable catalog (the
    'group' field) - only lowercasing/space-replacement was applied to
    it before, so a rogue/compromised mirror returning '/' or '..'
    sequences could steer the resulting os.path.join() outside
    ENIGMA_PATH. Only used for the filename - the original name is
    still used for display (#NAME line) and catalog lookups."""
    name = name.replace('/', '_').replace('\\', '_')
    while '..' in name:
        name = name.replace('..', '_')
    return name


def _ensure_trailing_newline(lines):
    """Ensure the last element of a readlines()-style list ends with a
    newline, so concatenating it with another such list can't merge the
    last line of one onto the first line of the other. readlines()
    doesn't add a trailing newline to a final line that doesn't already
    have one - if bouquets.tv/.radio (edited by any installed plugin,
    not just this one) happened to end that way, writelines()-ing this
    list followed by another would silently corrupt that boundary
    line."""
    if lines and not lines[-1].endswith('\n'):
        lines = lines[:-1] + [lines[-1] + '\n']
    return lines


def _merge_bouquet_lines(vavoo_lines, other_lines, list_position):
    """The new content of bouquets.tv/.radio: every Vavoo bouquet line
    as one block at the top or the bottom of everything else.

    - The file's own "#NAME ..." header line stays the first line -
      "top" used to put the Vavoo block above it.
    - Vavoo lines are de-duplicated keeping their order. This used to
      be list(dict.fromkeys(...)), which only preserves order on
      Python 3.7+ - on Python 2 it reshuffled the Vavoo bouquets on
      every export.
    """
    seen = set()
    unique = []
    for line in vavoo_lines:
        if not line.endswith('\n'):
            line += '\n'
        if line not in seen:
            seen.add(line)
            unique.append(line)

    header = []
    rest = list(other_lines)
    if rest and rest[0].startswith('#NAME'):
        header = _ensure_trailing_newline(rest[:1])
        rest = rest[1:]

    if list_position == "top":
        return header + unique + rest
    return header + _ensure_trailing_newline(rest) + unique


def _strip_control_chars(text):
    """Strip characters with ord() <= 31 (e.g. an embedded newline) from
    network-sourced text before it's written as a raw bouquet line -
    matches the control-char stripping sanitizeFilename() already does
    for filenames, but without ASCII-folding so unicode separators
    (e.g. the '➾' used in category display names) survive."""
    return ''.join(c for c in text if ord(c) > 31)


# Every Vavoo bouquet's name in the channel list starts the same way as
# the favourites' ("Vavoo ★ Favourites"): "Vavoo ★ Portugal", "Vavoo ★
# Italy ➾ Sport". Only the #NAME line: the file names stay as they were.
BOUQUET_TITLE_PREFIX = u"Vavoo ★ "


def bouquet_title(name):
    """A country's (or category's) bouquet name in the channel list."""
    title = _strip_control_chars(vavoo_store.to_text(name)).strip()
    if title.startswith(BOUQUET_TITLE_PREFIX):
        return title
    return BOUQUET_TITLE_PREFIX + title


def retitle_vavoo_bouquets():
    """The bouquets exported before their names began with "Vavoo ★ "
    get it: only their #NAME line, written again (atomic); the
    favourites bouquet has its own title. Returns how many changed.

    Precondition: the caller holds export_lock."""
    changed = 0
    try:
        names = listdir(ENIGMA_PATH)
    except Exception:
        return 0
    for fname in sorted(names):
        if not (fname.startswith("userbouquet.vavoo_") and
                (fname.endswith(".tv") or fname.endswith(".radio"))):
            continue
        if fname == FAVOURITES_BOUQUET:
            continue
        path = join(ENIGMA_PATH, fname)
        try:
            with io.open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            if not lines or not lines[0].startswith(u"#NAME "):
                continue
            title = lines[0][len(u"#NAME "):].strip()
            if not title or title.startswith(BOUQUET_TITLE_PREFIX):
                continue
            lines[0] = u"#NAME " + bouquet_title(title) + u"\n"
            temp_path = path + ".tmp"
            with io.open(temp_path, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            rename(temp_path, path)
            changed += 1
        except Exception as e:
            print("[Bouquet] Cannot rename %s: %s" % (fname, e))
    if changed:
        print(u"[Bouquet] %d bouquets renamed Vavoo ★ ..." % changed)
    return changed


def get_local_ip():
    """Get the local IP address (2s timeout to avoid blocking on restricted networks)."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return ip
    except Exception:
        return PROXY_HOST


def _add_to_main_bouquet(bouquet_name, bouquet_type, list_position="bottom"):
    """Add bouquet reference to the main bouquet file.

    Precondition: caller holds plugin.py's module-level export_lock -
    this function has no locking of its own, and read-modify-write via
    rename() on this shared file means a concurrent unlocked caller
    would silently lose the other's update."""
    main_bouquet_path = join(ENIGMA_PATH, "bouquets." + bouquet_type.lower())

    if not bouquet_name.startswith("userbouquet."):
        print("DEBUG: Skipping " + bouquet_name + " - not a userbouquet")
        return

    # (text: bouquets.tv is written through io.open(), which on Python 2
    # takes no byte string - a str bouquet name made every line fail)
    bouquet_line = u'#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "' + \
        vavoo_store.to_text(bouquet_name) + u'" ORDER BY bouquet\n'

    try:
        # Read existing content - this is a shared, system-wide file that
        # can carry lines contributed by any other installed plugin, not
        # just Vavoo's own (always utf-8) content, so read/write it
        # explicitly as utf-8 rather than relying on the platform's
        # default encoding (not guaranteed utf-8 on every STB image).
        if isfile(main_bouquet_path):
            with io.open(main_bouquet_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        else:
            lines = []

        # Remove all Vavoo lines first
        non_vavoo_lines = []
        vavoo_lines = []

        for line in lines:
            # Precise ".vavoo_" match (same as deep_clean_bouquet_files()/
            # _remove_bouquet_lines_from_main_files()), not a bare
            # "vavoo" substring - the loose check could sweep up an
            # unrelated bouquet whose name merely contains "vavoo"
            # (e.g. a user's own "userbouquet.myvavoofavs.tv").
            if '.vavoo_' in line:
                # Skip if it's the specific bouquet we're updating
                if bouquet_name not in line:
                    vavoo_lines.append(line)
            else:
                non_vavoo_lines.append(line)

        # Add the current bouquet to Vavoo lines
        vavoo_lines.append(bouquet_line)

        # Configurable position
        position_info = "top" if list_position == "top" else "bottom"
        new_lines = _merge_bouquet_lines(
            vavoo_lines, non_vavoo_lines, list_position)

        # Write file atomically (temp file + rename) - this is
        # Enigma2's entire channel/bouquet index, not just Vavoo's own
        # bouquets; writing it in place would leave it truncated if the
        # process is killed mid-write (STB power loss, OOM-kill).
        temp_path = main_bouquet_path + ".tmp"
        with io.open(temp_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        rename(temp_path, main_bouquet_path)

        ReloadBouquets(3000)
        print(
            "Added " +
            bouquet_name +
            " to " +
            position_info +
            " (all Vavoo grouped)")

    except Exception as e:
        print("Error adding to main bouquet: " + str(e))


def deep_clean_bouquet_files():
    """Remove Vavoo references from main bouquet files.

    Precondition: caller holds plugin.py's module-level export_lock -
    same shared-file race as _add_to_main_bouquet()."""
    try:
        for bfile in ['bouquets.tv', 'bouquets.radio']:
            bouquet_path = join(ENIGMA_PATH, bfile)
            if file_exists(bouquet_path):
                with io.open(bouquet_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()

                # Keep only lines that do not contain ".vavoo_"
                new_lines = [line for line in lines if '.vavoo_' not in line]

                # Atomic write (temp file + rename) - same reasoning as
                # _add_to_main_bouquet(): this is Enigma2's whole channel
                # index, not just Vavoo's bouquets.
                temp_path = bouquet_path + ".tmp"
                with io.open(temp_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                rename(temp_path, bouquet_path)

                print("✓ Cleaned: " + bfile)

    except Exception as e:
        print("Error in deep clean: " + str(e))


def _remove_bouquet_lines_from_main_files(removed_filenames):
    """Remove only the bouquets.tv/.radio line(s) referencing the given
    bouquet filenames, leaving every other Vavoo bouquet's registration
    intact.

    Unlike deep_clean_bouquet_files() (which unconditionally wipes every
    ".vavoo_" line and is only correct for the "remove every Vavoo
    bouquet" case), this is what remove_bouquets_by_name(name) needs when
    scoped to one bouquet - otherwise, removing/recreating bouquet A
    while bouquet B already exists wipes B's line too and never puts it
    back, so B silently disappears from the channel list the next time
    any other Vavoo bouquet is updated (confirmed via a user-submitted
    log: exporting France then Portugal left bouquets.tv with only
    Portugal's line, even though France's bouquet file was created fine).

    Precondition: caller holds plugin.py's module-level export_lock -
    same shared-file race as _add_to_main_bouquet().
    """
    if not removed_filenames:
        return
    try:
        for bfile in ['bouquets.tv', 'bouquets.radio']:
            bouquet_path = join(ENIGMA_PATH, bfile)
            if not file_exists(bouquet_path):
                continue

            with io.open(bouquet_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            new_lines = [
                line for line in lines
                if not any(fname in line for fname in removed_filenames)
            ]

            if len(new_lines) == len(lines):
                continue

            temp_path = bouquet_path + ".tmp"
            with io.open(temp_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            rename(temp_path, bouquet_path)

            print(
                "✓ Removed %d line(s) from %s" %
                (len(lines) - len(new_lines), bfile))

    except Exception as e:
        print("Error removing bouquet lines: " + str(e))


def remove_bouquets_by_name(name=None):
    """Remove Vavoo bouquets by name. If name is None, remove all Vavoo bouquets."""
    try:
        removed_count = 0
        removed_filenames = []
        for fname in listdir(ENIGMA_PATH):
            if '.vavoo_' in fname and (
                    fname.endswith('.tv') or fname.endswith('.radio')):
                if name is not None:
                    name_safe = name.lower().replace(' ', '_')
                    for sep in literals_for(name_safe, '➾', '⟾', '->', '→'):
                        name_safe = name_safe.replace(sep, '_')
                    # Exact match for the flat bouquet
                    # ("userbouquet.vavoo_<name>.tv"/".radio") or a
                    # category sub-bouquet of it
                    # ("userbouquet.vavoo_<name>_<category>.tv") -
                    # previously a bare "name_safe in fname" substring
                    # check, which also matched a DIFFERENT country
                    # sharing the substring (e.g. removing "Italy" also
                    # deleted "userbouquet.vavoo_italy_sport.tv" as
                    # intended, but would equally have matched an
                    # unrelated "userbouquet.vavoo_bigitaly.tv" had one
                    # existed).
                    if not (fname.startswith(
                            "userbouquet.vavoo_%s." % name_safe) or
                            fname.startswith(
                                "userbouquet.vavoo_%s_" % name_safe)):
                        continue

                bouquet_path = join(ENIGMA_PATH, fname)
                try:
                    remove(bouquet_path)
                    removed_count += 1
                    removed_filenames.append(fname)
                    print("✓ Removed: " + fname)
                except Exception as e:
                    print("Error removing " + fname + ": " + str(e))

        if name is None:
            # Removing every Vavoo bouquet - the blanket wipe is correct
            # here.
            deep_clean_bouquet_files()
        else:
            # Scoped to one bouquet - only strip that bouquet's own
            # line(s), so any other already-exported Vavoo bouquet's
            # registration in bouquets.tv/.radio survives.
            _remove_bouquet_lines_from_main_files(removed_filenames)

        # --- also the EPG files' entries no bouquet holds any more ---
        # A country's channels file is shared by every bouquet playing
        # its channels (its categories, the favourites bouquet): only
        # the entries of the bouquets just removed go.
        if name is not None:
            country_code = get_country_code_from_bouquet_name(name)
            if country_code:
                prune_epg_mapping_file(country_code, ENIGMA_PATH)
        else:
            # Every Vavoo bouquet gone: every vavoo*.channels.xml - also
            # "vavoo.channels.xml", the file write_epg_mapping_file()
            # uses when a bouquet's country is not known.
            for epg_file in glob.glob(join(vUtils.EPGIMPORT_DIR,
                                           "vavoo*.channels.xml")):
                try:
                    remove(epg_file)
                    print("✓ Removed EPG file: {}".format(basename(epg_file)))
                except Exception as e:
                    print("Error removing EPG file {}: {}".format(epg_file, e))

        # Update the sources.xml file after removals
        update_epg_sources()
        # ------------------

        return removed_count
    except Exception as e:
        print("Error removing bouquets: " + str(e))
        return 0


def is_bouquet_exported(name):
    """Whether a Vavoo bouquet already exists on disk for this name.

    Uses the same name_safe derivation as remove_bouquets_by_name() so
    "is it exported" and "remove it" always agree on the same files.
    """
    if not name:
        return False
    try:
        name_safe = name.lower().replace(' ', '_')
        for sep in literals_for(name_safe, '➾', '⟾', '->', '→'):
            name_safe = name_safe.replace(sep, '_')
        for fname in listdir(ENIGMA_PATH):
            if '.vavoo_' in fname and (
                    fname.endswith('.tv') or fname.endswith('.radio')):
                # Same exact/category-prefix match as
                # remove_bouquets_by_name() - see its comment for why a
                # bare substring check is wrong.
                if (fname.startswith("userbouquet.vavoo_%s." % name_safe) or
                        fname.startswith("userbouquet.vavoo_%s_" % name_safe)):
                    return True
        return False
    except Exception as e:
        print("Error checking bouquet export state: " + str(e))
        return False


def convert_bouquet(
        servicetype,
        name,
        url,
        export_type,
        bouquet_position):
    """Compatible (synchronous) version for existing calls."""
    return convert_bouquet_sync(
        servicetype,
        name,
        url,
        export_type,
        bouquet_position)


def convert_bouquet_sync(
        servicetype,
        name,
        url,
        export_type,
        bouquet_position):
    """Creates the bouquet synchronously and returns the number of channels."""
    try:
        print("[Bouquet] Starting bouquet creation for: " + name)

        # 1. Check proxy
        if not is_proxy_running():
            print("[Bouquet] Proxy not running, starting...")
            if not run_proxy_in_background():
                print("[Bouquet] Failed to start proxy")
                return 0

        # 2. Wait for proxy (max 15 seconds)
        for i in range(15):
            if is_proxy_ready(timeout=2):
                break
            select.select([], [], [], 1)
        else:
            print("[Bouquet] Proxy not ready")
            return 0

        # 3. Get channels from proxy
        channels = get_channels_from_proxy(name, export_type)
        if not channels:
            return 0

        # 4. Extract country code
        country_code = get_country_code_from_bouquet_name(name) or ""

        # 5. Get matcher
        matcher = get_epg_matcher()

        # 6. Create bouquet file (this does matching and writes the bouquet)
        ch_count, bouquet_filename, matched, unmatched = create_bouquet_file(
            name, channels, servicetype, export_type, bouquet_position, matcher, country_code)

        if ch_count == 0:
            print("[Bouquet] No channels written")
            return 0

        # 7. Generate EPG mapping if enabled
        if matched and config.plugins.vavoo.epg_enabled.value:
            # Use full_service_ref (dvb_ref + stream URL), not the bare
            # dvb_ref - EPGImport's channelFilter() silently drops any
            # channel ref without an embedded URL (see the comment in
            # create_bouquet_file() above where full_service_ref is
            # built).
            epg_entries = [(m['feed_id'], m['full_service_ref'], m['name'])
                           for m in matched if m['feed_id']]
            if epg_entries:
                try:
                    write_epg_mapping_file(epg_entries, country_code,
                                       ENIGMA_PATH)
                    print(
                        "[Bouquet] EPG mapping written for {} channels".format(
                            len(epg_entries)))
                except Exception as e:
                    print("[Bouquet] Error writing EPG mapping: {}".format(e))
            else:
                print("[Bouquet] No valid EPG entries")
        else:
            print("[Bouquet] EPG disabled or no matched channels")

        # 8. Always update the sources.xml file after any
        # change to channel files
        try:
            update_epg_sources()
            print("[Bouquet] EPG sources updated")
        except Exception as e:
            print("[Bouquet] Error updating EPG sources: {}".format(e))

        # 9. Save matcher cache (matched channels) and unmatched channels.
        # update_complete_cache() is the sole CACHE_FILE writer here - see
        # its docstring for why a separate matcher.save_cache() call isn't
        # needed alongside it.
        try:
            update_complete_cache(
                matched, unmatched, country_code, servicetype)
        except Exception as e:
            print("[Bouquet] Error updating cache: %s" % e)

        # save_unmatched() (called per-channel above, both inside
        # create_bouquet_file()'s matching and update_complete_cache()'s
        # own loop) only stages changes in memory now - write them once
        # here instead of once per channel.
        try:
            flush_unmatched_cache()
        except Exception as e:
            print("[Bouquet] Error flushing unmatched cache: %s" % e)

        return ch_count
    except Exception as e:
        print("[Bouquet] Error in convert_bouquet_sync: " + str(e))
        trace_error()
        return 0


def export_bouquet_async(
        name,
        export_type,
        parent_screen,
        callback,
        servicetype,
        bouquet_position,
        lock=None):
    debug(
        "export_bouquet_async called for %s, type %s" %
        (name, export_type))

    def task():
        try:
            debug("Background task started for %s" % name)

            # PHASE 1: Create fallback bouquet (fast)
            ch_count, bouquet_filename, channels_list, country_code = create_fallback_bouquet_sync(
                servicetype, name, export_type, bouquet_position)

            if ch_count == 0:
                # Failed to create bouquet
                def do_callback():
                    try:
                        # Screen.close() doesn't clear self.session, so
                        # that check could never actually detect a closed
                        # screen - parent_screen._closed (set by vavoo's
                        # own close() override) is the real signal.
                        if parent_screen and not getattr(
                                parent_screen, "_closed", False):
                            callback(False, 0, "No channels found")
                        else:
                            print(
                                "[Bouquet] Export failed (no channels) but plugin closed")
                    except Exception as cb_e:
                        print("[Bouquet] Error in callback: %s" % cb_e)

                # Constructing/starting an eTimer directly from this
                # background thread isn't safe - marshal onto the reactor
                # thread instead, same as everywhere else callbacks need
                # to run from here.
                reactor.callFromThread(do_callback)
                return

            # Instant recharge of services to make the bouquet visible
            def do_reload():
                try:
                    ReloadBouquets()
                    print("[Bouquet] Services reloaded after fallback creation")
                except Exception as e:
                    print("[Bouquet] Error reloading services: %s" % e)

            reactor.callFromThread(reactor.callLater, 0.5, do_reload)
            # -------------------------------------------------

            # Notify that bouquet is ready (first callback)
            def do_first_callback():
                try:
                    if parent_screen and not getattr(
                            parent_screen, "_closed", False):
                        callback(True, ch_count, "Bouquet created")
                    else:
                        print(
                            "[Bouquet] Export completed (fallback) but plugin closed, %d channels" %
                            ch_count)
                except Exception as cb_e:
                    print("[Bouquet] Error in first callback: %s" % cb_e)

            reactor.callFromThread(do_first_callback)

            # PHASE 2: Process EPG matching in background (same thread)
            if channels_list:
                process_epg_matching_background(
                    name, bouquet_filename, channels_list, country_code,
                    parent_screen, callback, servicetype=servicetype
                )
            else:
                # No channels for EPG, just call callback again? Already
                # called.
                pass

        except Exception as e:
            debug("Background task error: %s" % str(e))
            trace_error()
            exc = e

            def do_callback():
                try:
                    if parent_screen and not getattr(
                            parent_screen, "_closed", False):
                        callback(False, 0, str(exc))
                    else:
                        print(
                            "[Bouquet] Export failed but plugin closed: %s" %
                            str(exc))
                except Exception as cb_e:
                    print("[Bouquet] Error in error callback: %s" % cb_e)

            reactor.callFromThread(do_callback)

        finally:
            # Release the lock if provided
            if lock:
                lock.release()

    t = threading.Thread(target=task)
    t.daemon = True
    t.start()


def get_channels_from_proxy(name, export_type):
    """Get channels from the proxy"""
    try:
        # Encode the name
        encoded_name = quote(name)

        # Every source of a channel its own entry ("SIC .b", "SIC .c",
        # "SIC .d" - grouped=0), whatever "Group Sources" says for the
        # plugin's own list: a bouquet has no source menu, so it lists
        # them all, under their catalog names.
        proxy_url = "http://{}:{}/channels?country={}&grouped=0".format(
            PROXY_HOST, PORT, encoded_name)

        # Request to the proxy
        response = getUrl(proxy_url, timeout=30)

        if not response:
            print("[Proxy] No response for %s" % name)
            return []

        # JSON parsing
        try:
            channels = loads(response)
        except Exception:
            # If response is bytes, decode
            if isinstance(response, bytes):
                channels = loads(response.decode('utf-8', 'ignore'))
            else:
                raise

        if not isinstance(channels, list):
            print("[Proxy] Invalid response format for %s" % name)
            return []

        print("[Proxy] Got %d channels for %s" % (len(channels), name))
        return channels

    except Exception as e:
        print("[Proxy] Error getting channels: %s" % str(e))
        trace_error()
        return []


def process_epg_matching_background(
        name,
        bouquet_filename,
        channels_list,
        country_code,
        parent_screen,
        callback,
        servicetype="4097"):
    """
    Perform EPG matching in background, update the bouquet with converted service references,
    generate EPG files, and update cache.
    """
    try:
        print("[EPGBackground] Starting EPG matching for %s" % name)

        # 1. Get matcher
        matcher = get_epg_matcher()

        # 2. Prepare lists for matched/unmatched
        matched = []

        # each: {'name': clean_name, 'channel_id': id, 'original_url': url, 'original_sref': sref}
        unmatched = []

        for ch in channels_list:
            try:
                debug(
                    "original_name in ch: {}".format(
                        repr(ch['original_name'])))

                feed_id, dvb_ref, match_source = matcher.find_match(
                    ch['original_name'], country_code, servicetype,
                    channel_id=ch['channel_id'],
                    allow_curated_promotion=True,
                    epg_guide_id=ch.get('epg_id'))
                if dvb_ref:
                    if dvb_ref.endswith(':'):
                        dvb_ref = dvb_ref[:-1]
                    # EPGImport's channelFilter() only fast-accepts a channel
                    # ref if it contains an embedded URL ("%3a//" in the
                    # string) - a bare DVB-tuple ref falls through to a
                    # fake-recording probe instead, which fails (silently, no
                    # exception) for a reference with no stream URL at all.
                    # Without this, write_epg_mapping_file() below wrote only
                    # the bare tuple and EPGImport dropped almost every
                    # channel during its own channels.xml parse pass, logging
                    # "[XMLTVConverter] Unknown channel: ..." for each one
                    # regardless of how good the id match was.
                    full_service_ref = "{}:{}".format(
                        dvb_ref, ch['url'].replace(':', '%3a'))
                    matched.append({
                        'name': ch['original_name'],
                        'channel_id': ch['channel_id'],
                        'dvb_ref': dvb_ref,
                        'full_service_ref': full_service_ref,
                        'feed_id': feed_id,
                        'original_url': ch['url'],
                        'source': match_source
                    })
                else:
                    # Unmatched: keep the original sref from the fallback bouquet
                    # 'fallback_sref' was stored in ch by create_fallback_bouquet_sync.
                    # dict.get()'s default arg is evaluated eagerly regardless
                    # of whether the key is present - `or` short-circuits so
                    # unique_fallback_sref() only actually runs on the rare
                    # miss, not on every unmatched channel.
                    unmatched.append({
                        'name': ch['original_name'],
                        'channel_id': ch['channel_id'],
                        'original_url': ch['url'],
                        'original_sref': ch.get('fallback_sref') or
                        unique_fallback_sref(servicetype, ch['channel_id'])
                    })
            except Exception as e:
                # One bad channel must not abort matching for the whole
                # country - mirrors create_bouquet_file()'s per-channel
                # try/except (used by the scheduled auto-update path);
                # this loop (the interactive/UI export path) previously
                # had no isolation here at all.
                print(
                    "[EPGBackground] Error matching channel %s: %s" %
                    (ch.get('original_name', '?'), str(e)))
                continue
            select.select([], [], [], 0.001)

        # Save callback and matched count AFTER the loop
        saved_matched = len(matched)
        saved_callback = callback

        # 3. Update cache files (only matched channels go to main cache)
        # Handle unmatched channels: save them to unmatched cache with their
        # original sref
        for u in unmatched:
            save_unmatched(
                u['name'],
                country_code,
                servicetype,
                matched=False,
                sref=ensure_sref_trailing_colon(u['original_sref'])
            )

        # 4. Rewrite the bouquet file with converted references
        bouquet_path = join(ENIGMA_PATH, bouquet_filename)
        changes = 0
        if file_exists(bouquet_path):
            # Read current lines
            with io.open(bouquet_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            new_lines = []
            i = 0
            match_dict = {m['channel_id']: m['dvb_ref'] for m in matched}

            while i < len(lines):
                line = lines[i].strip()
                if line.startswith('#SERVICE '):
                    service_line = line[9:]
                    parts = service_line.split(':')
                    if len(parts) < 11:
                        new_lines.append(lines[i])
                        i += 1
                        continue

                    url_part = parts[10] if len(parts) > 10 else ''
                    url_decoded = unquote(url_part)
                    match = search(r'[?&]channel=([^&]+)', url_decoded)
                    if match:
                        channel_id = match.group(1)
                        if channel_id in match_dict:
                            new_service_line = "#SERVICE %s:%s" % (
                                match_dict[channel_id], url_part)
                            new_lines.append(new_service_line + '\n')
                            changes += 1
                            i += 1
                            continue
                    # No match, keep original
                    new_lines.append(lines[i])
                    i += 1
                else:
                    new_lines.append(lines[i])
                    i += 1

            if changes > 0:
                temp_path = bouquet_path + ".tmp"
                with io.open(temp_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                rename(temp_path, bouquet_path)
                print(
                    "[EPGBackground] Updated %d service lines in %s" %
                    (changes, bouquet_filename))

        # 5. Generate EPG mapping files
        if matched:
            # full_service_ref (dvb_ref + stream URL) - see the comment
            # where it's built above; a bare dvb_ref gets silently
            # dropped by EPGImport's channelFilter().
            epg_entries = [(m['feed_id'], m['full_service_ref'], m['name'])
                           for m in matched if m['feed_id']]
            if epg_entries:
                write_epg_mapping_file(epg_entries, country_code,
                                       ENIGMA_PATH)
                print(
                    "[EPGBackground] EPG mapping written for %d channels" %
                    len(epg_entries))

        # 6. Update sources.xml
        update_epg_sources()

        # 7. Save matched and unmatched channels to the cache files.
        # update_complete_cache() is the sole CACHE_FILE writer here - see
        # its docstring for why a separate matcher.save_cache() call isn't
        # needed alongside it. save_unmatched() (called per-channel above)
        # only stages changes in memory - update_complete_cache() calls it
        # again for each unmatched channel and flush_unmatched_cache()
        # writes them all out once, instead of once per channel.
        update_complete_cache(matched, unmatched, country_code, servicetype)
        flush_unmatched_cache()

        # Reload only now that the bouquet's #SERVICE lines, the EPG
        # channel mapping, and sources.xml are all in their final state -
        # without this, Enigma2's live service database keeps using the
        # fallback refs written in phase 1 until a manual reload/reboot,
        # so the just-matched EPG never actually shows up despite the
        # "completed" notification. Reloading before the EPG
        # mapping/sources files existed (the previous order) meant
        # Enigma2 picked up the new service references before EPGImport
        # had anything to associate with them for this export.
        if changes > 0:
            reactor.callFromThread(ReloadBouquets)

        # 8. Callback to notify completion
        print(
            "[EPGBackground] COMPLETED for %s - matched=%d" %
            (name, len(matched)))
        print("[EPGBackground] Calling callback with message='EPG processing completed'")

        def _do_completion_callback():
            try:
                saved_callback(True, saved_matched, "EPG processing completed")
            except Exception as cb_e:
                print(
                    "[EPGBackground] Error in completion callback: %s" %
                    cb_e)
        # This whole function runs on a background thread (see task() in
        # export_bouquet_async) - the callback ends up in plugin.py's
        # _on_export_complete(), a UI-touching method, so marshal it onto
        # the reactor thread rather than calling it directly.
        reactor.callFromThread(_do_completion_callback)

    except Exception as exc:
        # Python 3 deletes an "except ... as exc" binding once this block
        # exits, but _do_error_callback() runs later (asynchronously, via
        # callFromThread) - capture the message into a plain local first.
        exc_message = str(exc)
        print("[EPGBackground] Error: %s" % exc_message)
        trace_error()

        def _do_error_callback():
            try:
                callback(False, 0, exc_message)
            except Exception as cb_e:
                print("[EPGBackground] Error in error callback: %s" % cb_e)
        reactor.callFromThread(_do_error_callback)


def _build_bouquet_filename(name_for_path, export_type):
    """Compute this bouquet's on-disk filename from its (already
    path-sanitized, see _sanitize_name_for_path()) display name and
    export mode - shared by create_fallback_bouquet_sync() and
    create_bouquet_file(), which used to each carry their own
    identical copy of this logic. That duplicated copy only recognized
    4 of GROUP_NAME_SEPARATORS' 6 known country/category separators -
    "»"/"›" survived verbatim into the generated filename instead of
    being stripped/replaced like the other four.
    """
    is_category = any(
        sep in name_for_path for sep in group_separators(name_for_path))

    if export_type == "flat" or not is_category:
        safe_name = name_for_path.lower().replace(' ', '_')
        for sep in group_separators(safe_name):
            safe_name = safe_name.replace(sep, '')
        return "userbouquet.vavoo_%s.tv" % safe_name

    country_part = ""
    category_part = ""
    for sep in group_separators(name_for_path):
        if sep in name_for_path:
            parts = name_for_path.split(sep)
            country_part = parts[0].strip()
            category_part = parts[1].strip()
            break

    if not country_part or not category_part:
        safe_name = name_for_path.lower().replace(' ', '_')
        for sep in group_separators(safe_name):
            safe_name = safe_name.replace(sep, '_')
        return "userbouquet.vavoo_%s.tv" % safe_name

    country_safe = country_part.lower().replace(' ', '_')
    category_safe = category_part.lower().replace(' ', '_')
    return "userbouquet.vavoo_%s_%s.tv" % (country_safe, category_safe)


def _bouquet_country_prefix(name_for_path):
    """The sanitized country-name prefix _build_bouquet_filename() would
    use for a category sub-bouquet's filename (e.g. "italy" out of
    "Italy -> Sport"), or None if name_for_path isn't a "country <sep>
    category" name at all.

    Used by remove_bouquets_by_name() to tell whether a sibling category
    bouquet for the same country still exists on disk before deleting
    that country's shared EPG channels.xml file.
    """
    for sep in group_separators(name_for_path):
        if sep in name_for_path:
            parts = name_for_path.split(sep)
            country_part = parts[0].strip()
            category_part = parts[1].strip()
            if country_part and category_part:
                return country_part.lower().replace(' ', '_')
            break
    return None


def create_fallback_bouquet_sync(
        servicetype,
        name,
        export_type,
        bouquet_position):
    """
    Create a bouquet using ONLY fallback service references (servicetype:0:0:0:0:0:0:0:0:0:)
    for all channels.
    Returns (channel_count, bouquet_filename, channels_list, country_code)
    where channels_list is a list of dicts with 'name', 'channel_id', 'url', 'original_name'.
    """
    try:
        print("[FallbackBouquet] Creating fallback bouquet for: %s" % name)

        # 1. Check proxy
        if not is_proxy_running():
            print("[FallbackBouquet] Proxy not running, starting...")
            if not run_proxy_in_background():
                print("[FallbackBouquet] Failed to start proxy")
                return 0, "", [], ""

        # 2. Wait for proxy (max 15 seconds)
        for i in range(15):
            if is_proxy_ready(timeout=2):
                break
            select.select([], [], [], 1)
        else:
            print("[FallbackBouquet] Proxy not ready")
            return 0, "", [], ""

        # 3. Get channels from proxy
        channels = get_channels_from_proxy(name, export_type)
        if not channels:
            return 0, "", [], ""

        # 4. Extract country code for later EPG
        country_code = get_country_code_from_bouquet_name(name) or ""

        # 5. Prepare bouquet filename (same logic as create_bouquet_file)
        name_for_path = _sanitize_name_for_path(name)
        bouquet_filename = _build_bouquet_filename(name_for_path, export_type)

        bouquet_path = join(ENIGMA_PATH, bouquet_filename)

        # 6. Build bouquet lines with fallback
        # (text: on Python 2 a name with an accent, in bytes, beside
        # the unicode lines made the file fail to write)
        lines = [u"#NAME " + bouquet_title(name)]
        channel_count = 0
        channels_list = []
        seen_channel_ids = set()

        for channel in channels:
            try:
                if not isinstance(channel, dict):
                    continue
                channel_name = channel.get('name', 'Unknown')
                # print("[DEBUG] original channel_name:", repr(channel_name))

                channel_url = channel.get('url', '')
                channel_id = channel.get('id', '')
                if not channel_name or not channel_url or not channel_id:
                    continue
                if channel_id in seen_channel_ids:
                    debug(
                        "[FallbackBouquet] Skipping duplicate channel_id "
                        "%s (%s)" % (channel_id, channel_name))
                    continue
                seen_channel_ids.add(channel_id)

                # Clean name
                clean_name = decodeHtml(channel_name)
                clean_name = remove_parentheses(clean_name)
                clean_name = sanitizeFilename(clean_name)

                # Encode URL
                encoded_url = channel_url.replace(':', '%3a')

                # Fallback service reference - sid:tsid derived from
                # channel_id so unmatched channels don't all collide on
                # one shared eEPGCache key (see unique_fallback_sref()).
                fallback_dvb_ref = unique_fallback_sref(
                    servicetype, channel_id)
                service_line = "#SERVICE %s%s" % (
                    fallback_dvb_ref, encoded_url)
                lines.append(service_line)
                lines.append("#DESCRIPTION %s" % clean_name)
                channel_count += 1

                # Store for later matching
                channels_list.append({
                    'name': clean_name,
                    'channel_id': channel_id,
                    'url': channel_url,
                    'original_name': channel_name,
                    'epg_id': channel.get('epg_id', ''),
                    'fallback_sref': "%s%s" % (fallback_dvb_ref, encoded_url)
                })

            except Exception as e:
                print(
                    "[FallbackBouquet] Error processing channel: %s" %
                    str(e))
                continue

        if channel_count == 0:
            print("[FallbackBouquet] No valid channels for %s" % name)
            return 0, "", [], ""

        # 7. Write bouquet file atomically (temp file + rename)
        temp_path = bouquet_path + ".tmp"
        try:
            with io.open(temp_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            rename(temp_path, bouquet_path)
            print(
                "[FallbackBouquet] File created: %s (%d channels)" %
                (bouquet_filename, channel_count))
        except Exception as e:
            print(
                "[FallbackBouquet] Error writing file with encoding: %s" %
                str(e))
            try:
                with open(temp_path, 'wb') as f:
                    f.write(('\n'.join(lines)).encode('utf-8', 'ignore'))
                rename(temp_path, bouquet_path)
                print(
                    "[FallbackBouquet] File created (binary fallback): %s (%d channels)" %
                    (bouquet_filename, channel_count))
            except Exception as e2:
                print(
                    "[FallbackBouquet] Critical error writing file: %s" %
                    str(e2))
                return 0, "", [], ""

        # 8. Add to main bouquet
        _add_to_main_bouquet(bouquet_filename, 'tv', bouquet_position)

        return channel_count, bouquet_filename, channels_list, country_code

    except Exception as e:
        print("[FallbackBouquet] Error: %s" % str(e))
        trace_error()
        return 0, "", [], ""


def create_bouquet_file(
        name,
        channels,
        servicetype,
        export_type,
        bouquet_position,
        matcher,
        country_code):
    """
    Create bouquet file, performing matching once.
    Returns (channel_count, bouquet_filename, matched_channels, unmatched_channels)
    where matched_channels is a list of dicts with 'name', 'channel_id', 'dvb_ref', 'feed_id', 'source'
    and unmatched_channels is a list of dicts with 'name', 'channel_id'.
    """
    try:
        print("[Bouquet] Creating bouquet: %s (%s)" % (name, export_type))

        # Determine if it is a country or category, and build the filename
        name_for_path = _sanitize_name_for_path(name)
        bouquet_filename = _build_bouquet_filename(name_for_path, export_type)

        bouquet_path = join(ENIGMA_PATH, bouquet_filename)

        # Lists to store results
        # Store items for background processing
        # background_items = []
        # each item: {'name': name, 'channel_id': id, 'dvb_ref': ref,
        # 'feed_id': feed_id}
        matched = []
        unmatched = []    # each item: {'name': name, 'channel_id': id}
        tv_lines = [u"#NAME " + bouquet_title(name)]
        channel_count = 0
        seen_channel_ids = set()
        for channel in channels:
            try:
                if not isinstance(channel, dict):
                    continue
                channel_name = channel.get('name', 'Unknown')
                channel_url = channel.get('url', '')
                channel_id = channel.get('id', '')
                if not channel_name or not channel_url or not channel_id:
                    continue
                if channel_id in seen_channel_ids:
                    debug(
                        "[Bouquet] Skipping duplicate channel_id %s (%s)" %
                        (channel_id, channel_name))
                    continue
                seen_channel_ids.add(channel_id)

                # Clean name for description and matching
                clean_name = decodeHtml(channel_name)
                clean_name = remove_parentheses(clean_name)
                clean_name = sanitizeFilename(clean_name)

                # Encode URL for Enigma2 (replace ':' with '%3a')
                encoded_url = channel_url.replace(':', '%3a')

                # Perform matching once
                feed_id, dvb_ref, match_source = matcher.find_match(
                    channel_name, country_code, servicetype,
                    channel_id=channel_id, allow_curated_promotion=True,
                    epg_guide_id=channel.get('epg_id'))

                if dvb_ref:
                    if dvb_ref.endswith(':'):
                        dvb_ref = dvb_ref[:-1]
                    service_line = "#SERVICE {}:{}".format(
                        dvb_ref, encoded_url)
                    full_service_ref = "{}:{}".format(dvb_ref, encoded_url)
                    matched.append({
                        'name': clean_name,
                        'channel_id': channel_id,
                        'dvb_ref': dvb_ref,
                        'full_service_ref': full_service_ref,
                        'feed_id': feed_id,
                        'source': match_source
                    })
                else:
                    # Fallback: sid:tsid derived from channel_id so
                    # unmatched channels don't all collide on one shared
                    # eEPGCache key (see unique_fallback_sref()). Only
                    # computed here, not for every channel up front - the
                    # majority end up matched and this result would just
                    # be discarded.
                    service_line = "#SERVICE {}{}".format(
                        unique_fallback_sref(servicetype, channel_id),
                        encoded_url)
                    unmatched.append({
                        'name': clean_name,
                        'channel_id': channel_id
                    })

                tv_lines.append(service_line)
                tv_lines.append("#DESCRIPTION %s" % clean_name)
                channel_count += 1

            except Exception as e:
                print("[Bouquet] Error processing channel: %s" % str(e))
                continue
            # Yield after every channel, same as process_epg_matching_background()'s
            # loop - this is the scheduled auto-update's own matching pass
            # (see create_bouquet_file()'s only caller, convert_bouquet_sync(),
            # called from AutoStartTimer._update_bouquets()), which otherwise
            # runs the CPU-heavy fuzzy-matcher back to back for every channel
            # with no yield point at all, unlike the manual-export path.
            select.select([], [], [], 0.001)

        if channel_count == 0:
            print("[Bouquet] No valid channels for %s" % name)
            return 0, "", [], []

        # Write bouquet file atomically (temp file + rename)
        temp_path = bouquet_path + ".tmp"
        try:
            with io.open(temp_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(tv_lines))
            rename(temp_path, bouquet_path)
            print(
                "[Bouquet] File created: %s (%d channels)" %
                (bouquet_filename, channel_count))
        except Exception as e:
            print("[Bouquet] Error writing file with encoding: %s" % str(e))
            try:
                with open(temp_path, 'wb') as f:
                    f.write(('\n'.join(tv_lines)).encode('utf-8', 'ignore'))
                rename(temp_path, bouquet_path)
                print(
                    "[Bouquet] File created (binary fallback): %s (%d channels)" %
                    (bouquet_filename, channel_count))
            except Exception as e2:
                print("[Bouquet] Critical error writing file: %s" % str(e2))
                return 0, "", [], []

        # Add to main bouquet
        _add_to_main_bouquet(bouquet_filename, 'tv', bouquet_position)

        return channel_count, bouquet_filename, matched, unmatched

    except Exception as e:
        print("[Bouquet] Error in create_bouquet_file: %s" % str(e))
        trace_error()
        return 0, "", [], []


def _update_favorite_file(name, url, export_type):
    """Update the bouquet list (vavoo_store.bouquet_list_file(), Favorite.txt
    in the plugin folder before) - URL is always empty (proxy only).

    Precondition: caller holds plugin.py's module-level export_lock -
    same shared-file race as _add_to_main_bouquet()."""

    # name comes from Vavoo's remote catalog (country/category text) -
    # unlike bouquet filenames (_sanitize_name_for_path()) or #NAME
    # lines (_strip_control_chars(), used elsewhere), this pipe-
    # delimited field had no escaping: an embedded '|' misaligns every
    # field on read-back (here and in remove_favorite_entry()), and an
    # embedded newline would inject an extra pseudo-entry into the flat
    # file.
    name = _strip_control_chars(vavoo_store.to_text(name)).replace(u'|', u'')

    favorite_path = vavoo_store.bouquet_list_file()
    print("[Bouquet] Updating bouquet list: " +
          name + " (type: " + export_type + ")")

    # Read existing bouquets
    existing_bouquets = {}
    if isfile(favorite_path):
        try:
            with io.open(favorite_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and '|' in line:
                        parts = line.split('|')
                        if len(parts) >= 3:
                            bouq_name = parts[0].strip()
                            existing_bouquets[bouq_name] = {
                                'url': parts[1].strip() if len(parts) > 1 and parts[1].strip() else "",
                                'export_type': parts[2].strip(),
                                'timestamp': parts[3].strip() if len(parts) > 3 else str(
                                    time.time())}
        except Exception as e:
            print("[Bouquet] Error reading bouquet list: " + str(e))

    # Update/add current bouquet
    existing_bouquets[name] = {
        'url': "",  # ALWAYS empty (proxy only)
        'export_type': export_type,
        'timestamp': str(time.time())
    }

    # Write file atomically (temp file + rename)
    try:
        temp_path = favorite_path + ".tmp"
        with io.open(temp_path, 'w', encoding='utf-8') as f:
            for bouq_name, bouq_data in sorted(existing_bouquets.items()):
                # (text on both Pythons, see _add_to_main_bouquet())
                line = u"|".join(vavoo_store.to_text(part) for part in (
                    bouq_name, bouq_data['url'], bouq_data['export_type'],
                    bouq_data['timestamp']))
                f.write(line + "\n")
        rename(temp_path, favorite_path)

        print("[Bouquet] bouquet list updated with " +
              str(len(existing_bouquets)) + " bouquets")

    except Exception as e:
        print("[Bouquet] Error writing bouquet list: " + str(e))


def remove_favorite_entry(name):
    """Remove a single bouquet's entry from Favorite.txt, if present.

    Counterpart to _update_favorite_file() - keeps a per-country/category
    "Remove Fav" from leaving a stale entry that a later scheduled
    auto-update run would just re-create.

    Precondition: caller holds plugin.py's module-level export_lock -
    same shared-file race as _add_to_main_bouquet().
    """
    # Match _update_favorite_file()'s sanitization so a name containing
    # '|'/newline still finds and removes the entry it actually wrote.
    name = _strip_control_chars(vavoo_store.to_text(name)).replace(u'|', u'')

    favorite_path = vavoo_store.bouquet_list_file()
    if not isfile(favorite_path):
        return

    try:
        remaining = []
        with io.open(favorite_path, 'r', encoding='utf-8') as f:
            for line in f:
                stripped = line.strip()
                if stripped and '|' in stripped:
                    bouq_name = stripped.split('|')[0].strip()
                    if bouq_name == name:
                        continue
                remaining.append(line.rstrip('\n'))

        if remaining:
            temp_path = favorite_path + ".tmp"
            with io.open(temp_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(remaining) + '\n')
            rename(temp_path, favorite_path)
        else:
            remove(favorite_path)
        print("[Bouquet] Removed {} from bouquet list".format(name))
    except Exception as e:
        print("[Bouquet] Error removing {} from bouquet list: {}".format(name, e))


# ---------------------------------------------------------------------
# The favourites bouquet: one bouquet with the user's favourites, a
# marker (a title line Enigma2 does not play) for each country and its
# channels under it - the Favourites list's order
# (vavoo_store.favourites_by_country()). Exported from the Favourites'
# MENU, kept by the scheduled update (its line in the bouquet list) and
# rewritten by the plugin when the favourites change.

FAVOURITES_BOUQUET = "userbouquet.vavoo_favourites.tv"
FAVOURITES_NAME = "Favourites"          # its line in the bouquet list
FAVOURITES_EXPORT = "favourites"        # ... and that line's type


def favourites_bouquet_exported():
    return isfile(join(ENIGMA_PATH, FAVOURITES_BOUQUET))


def _url_id(url):
    """The id in a proxy address "...vavoo?channel=<id>" (a catalog id
    or a "grp:" group id), decoded, or None."""
    url = vavoo_store.to_text(url)
    if u"vavoo?channel=" not in url:
        return None
    channel_id = url.split(u"vavoo?channel=", 1)[1]
    for separator in (u"&", u"?", u"#"):
        channel_id = channel_id.split(separator)[0]
    if str is bytes:    # Python 2: unquote bytes, then UTF-8
        channel_id = unquote(channel_id.encode("utf-8")).decode(
            "utf-8", "ignore")
    else:
        channel_id = unquote(channel_id)
    return channel_id or None


def _quote_id(channel_id):
    if str is bytes:
        return vavoo_store.to_text(
            quote(channel_id.encode("utf-8"), safe=""))
    return quote(channel_id, safe="")


def favourites_bouquet_lines(title, entries, servicetype, other_label=u"Other"):
    """(lines, channels, left out, [channel]) of the favourites
    bouquet: "#NAME title", then for each country a marker with its
    name and its channels, each as a country bouquet writes it (the
    proxy's address, unique_fallback_sref() of its id). A channel that
    asks for the PIN (Parental Control) is left out: the bouquet plays
    without one. Each channel: {name, id, url, country_code, ref}."""
    text = vavoo_store.to_text
    lines = [u"#NAME " + _strip_control_chars(text(title))]
    channels = []
    skipped = 0
    marker = 0
    for country, members in vavoo_store.favourites_by_country(entries):
        rows = []
        for entry in members:
            channel_id = _url_id(entry.get("url"))
            name = text(entry.get("name")).strip()
            if not channel_id or not name:
                continue
            if vavoo_store.is_channel_locked(name, entry.get("country_name")):
                skipped += 1
                continue
            url = u"http://%s:%d/vavoo?channel=%s" % (
                PROXY_HOST, PORT, _quote_id(channel_id))
            ref = text(unique_fallback_sref(servicetype, channel_id)) + \
                url.replace(u":", u"%3a")
            shown = text(sanitizeFilename(remove_parentheses(
                decodeHtml(name)))) or name
            rows.append(u"#SERVICE " + ref)
            rows.append(u"#DESCRIPTION " + _strip_control_chars(shown))
            channels.append({"name": name, "id": channel_id, "url": url,
                             "country_code": text(entry.get("country_code")),
                             "ref": ref})
        if not rows:
            continue
        marker += 1
        label = _strip_control_chars(
            text(country) or text(other_label)).replace(u":", u" ").strip()
        lines.append(u"#SERVICE 1:64:%x:0:0:0:0:0:0:0::%s" % (marker, label))
        lines.append(u"#DESCRIPTION " + label)
        lines.extend(rows)
    return lines, len(channels), skipped, channels


def _favourites_epg(channels, servicetype):
    """The favourites' guide, per country: matched as a country export
    does, into the country's channels file (shared, see
    write_epg_mapping_file())."""
    matcher = get_epg_matcher()
    by_country = {}
    for channel in channels:
        code = channel["country_code"]
        if code:
            by_country.setdefault(code, []).append(channel)
    for code, members in by_country.items():
        matched = []
        unmatched = []
        for channel in members:
            try:
                feed_id, dvb_ref, source = matcher.find_match(
                    channel["name"], code, servicetype,
                    channel_id=channel["id"], allow_curated_promotion=True)
            except Exception as e:
                print("[Favourites] Matching %s: %s" % (channel["name"], e))
                continue
            if feed_id and dvb_ref:
                matched.append({
                    'name': channel["name"], 'channel_id': channel["id"],
                    'dvb_ref': dvb_ref.rstrip(':'),
                    'full_service_ref': channel["ref"], 'feed_id': feed_id,
                    'source': source})
            else:
                unmatched.append({'name': channel["name"],
                                  'channel_id': channel["id"]})
        entries = [(m['feed_id'], m['full_service_ref'], m['name'])
                   for m in matched]
        if entries:
            write_epg_mapping_file(entries, code, ENIGMA_PATH)
        try:
            update_complete_cache(matched, unmatched, code, servicetype)
        except Exception as e:
            print("[Favourites] Error updating the EPG cache: %s" % e)
    try:
        flush_unmatched_cache()
    except Exception as e:
        print("[Favourites] Error flushing the unmatched cache: %s" % e)
    update_epg_sources()


def export_favourites_sync(title, servicetype, bouquet_position,
                           other_label=u"Other", epg=True):
    """The favourites bouquet written (again), in the channel list and
    in the bouquet list (the scheduled update keeps it), then - with
    `epg` and "Enable Vavoo EPG" - its guide. Returns (channels, left
    out for the PIN), or None when it could not be written.

    Precondition: the caller holds export_lock (the files it shares
    with every export: bouquets.tv, the bouquet list, the EPG files)."""
    lines, count, skipped, channels = favourites_bouquet_lines(
        title, vavoo_store.load_favourites(), servicetype, other_label)
    path = join(ENIGMA_PATH, FAVOURITES_BOUQUET)
    try:
        temp_path = path + ".tmp"
        with io.open(temp_path, 'w', encoding='utf-8') as f:
            f.write(u"\n".join(lines) + u"\n")
        rename(temp_path, path)
    except Exception as e:
        print("[Favourites] Cannot write %s: %s" % (FAVOURITES_BOUQUET, e))
        return None
    print("[Favourites] %s written: %d channels, %d left out (PIN)" % (
        FAVOURITES_BOUQUET, count, skipped))
    _add_to_main_bouquet(FAVOURITES_BOUQUET, 'tv', bouquet_position)
    _update_favorite_file(FAVOURITES_NAME, "", FAVOURITES_EXPORT)
    if epg and channels and config.plugins.vavoo.epg_enabled.value:
        try:
            _favourites_epg(channels, servicetype)
        except Exception as e:
            print("[Favourites] EPG: %s" % e)
            trace_error()
    return count, skipped


def remove_favourites_bouquet():
    """The favourites bouquet gone: its file, its line in bouquets.tv and
    in the bouquet list, its entries in the EPG files. True if it was
    there. Precondition: the caller holds export_lock."""
    path = join(ENIGMA_PATH, FAVOURITES_BOUQUET)
    existed = isfile(path)
    if existed:
        try:
            remove(path)
        except Exception as e:
            print("[Favourites] Cannot remove %s: %s" % (FAVOURITES_BOUQUET, e))
            return False
    _remove_bouquet_lines_from_main_files([FAVOURITES_BOUQUET])
    remove_favorite_entry(FAVOURITES_NAME)
    prune_epg_mapping_files(ENIGMA_PATH)
    update_epg_sources()
    ReloadBouquets(500)
    print("[Favourites] Favourites bouquet removed")
    return existed


def reorganize_all_bouquets_position(list_position="bottom"):
    """Reorganize all Vavoo bouquets to the configured position.

    Precondition: caller holds plugin.py's module-level export_lock -
    same shared-file race as _add_to_main_bouquet()."""
    try:
        for bouquet_type in ['tv', 'radio']:
            main_bouquet_path = join(ENIGMA_PATH, "bouquets." + bouquet_type)

            if not isfile(main_bouquet_path):
                continue

            with io.open(main_bouquet_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            non_vavoo_lines = []
            vavoo_lines = []

            for line in lines:
                # Precise match, same reasoning as _add_to_main_bouquet().
                if '.vavoo_' in line:
                    vavoo_lines.append(line)
                else:
                    non_vavoo_lines.append(line)

            # Apply the configured position
            new_lines = _merge_bouquet_lines(
                vavoo_lines, non_vavoo_lines, list_position)

            # Atomic write (temp file + rename) - same reasoning as
            # _add_to_main_bouquet()/deep_clean_bouquet_files().
            temp_path = main_bouquet_path + ".tmp"
            with io.open(temp_path, 'w', encoding='utf-8') as f:
                f.writelines(new_lines)
            rename(temp_path, main_bouquet_path)

        print("Reorganized all Vavoo bouquets to " + list_position)
        return True

    except Exception as e:
        print("Error reorganizing bouquets: " + str(e))
        return False
