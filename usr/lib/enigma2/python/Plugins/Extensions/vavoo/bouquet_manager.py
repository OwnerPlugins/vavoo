#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import absolute_import, print_function
import io
import time
import glob
import threading
import urllib3
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
    update_complete_cache,
    update_epg_sources,
    write_epg_mapping_file,
    ensure_sref_trailing_colon
)
from .vavoo_proxy import run_proxy_in_background
from . import (
    PORT,
    PLUGIN_ROOT,
    PROXY_HOST,
    ENIGMA_PATH,
)

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
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


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
    """Add bouquet reference to the main bouquet file"""
    main_bouquet_path = join(ENIGMA_PATH, "bouquets." + bouquet_type.lower())

    if not bouquet_name.startswith("userbouquet."):
        print("DEBUG: Skipping " + bouquet_name + " - not a userbouquet")
        return

    bouquet_line = '#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "' + \
        bouquet_name + '" ORDER BY bouquet\n'

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
            if 'vavoo' in line.lower():
                # Skip if it's the specific bouquet we're updating
                if bouquet_name not in line:
                    vavoo_lines.append(line)
            else:
                non_vavoo_lines.append(line)

        # Add the current bouquet to Vavoo lines
        vavoo_lines.append(bouquet_line)

        position_info = list_position
        vavoo_lines = list(dict.fromkeys(vavoo_lines))

        # Configurable position
        if list_position == "top":
            new_lines = vavoo_lines + non_vavoo_lines
            position_info = "top"
        else:
            new_lines = non_vavoo_lines + vavoo_lines
            position_info = "bottom"

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
    """Remove Vavoo references from main bouquet files"""
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


def remove_bouquets_by_name(name=None):
    """Remove Vavoo bouquets by name. If name is None, remove all Vavoo bouquets."""
    try:
        removed_count = 0
        for fname in listdir(ENIGMA_PATH):
            if '.vavoo_' in fname and (
                    fname.endswith('.tv') or fname.endswith('.radio')):
                if name is not None:
                    name_safe = name.lower().replace(
                        ' ',
                        '_').replace(
                        '➾',
                        '_').replace(
                        '⟾',
                        '_').replace(
                        '->',
                        '_').replace(
                        '→',
                        '_')
                    if name_safe not in fname:
                        continue

                bouquet_path = join(ENIGMA_PATH, fname)
                try:
                    remove(bouquet_path)
                    removed_count += 1
                    print("✓ Removed: " + fname)
                except Exception as e:
                    print("Error removing " + fname + ": " + str(e))

        deep_clean_bouquet_files()

        # --- also remove associated EPG files ---
        epg_dir = "/etc/epgimport"

        if name is not None:
            # Specific removal for a country
            country_code = get_country_code_from_bouquet_name(name)
            if country_code:
                epg_file = join(
                    epg_dir, "vavoo_{}.channels.xml".format(
                        country_code.lower()))
                if file_exists(epg_file):
                    try:
                        remove(epg_file)
                        print(
                            "✓ Removed EPG file: vavoo_{}.channels.xml".format(country_code))
                    except Exception as e:
                        print("Error removing EPG file: {}".format(e))
        else:
            # Removing all bouquets: delete all vavoo_*.channels.xml files
            pattern = join(epg_dir, "vavoo_*.channels.xml")
            for epg_file in glob.glob(pattern):
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
        name_safe = name.lower().replace(
            ' ', '_').replace(
            '➾', '_').replace(
            '⟾', '_').replace(
            '->', '_').replace(
            '→', '_')
        for fname in listdir(ENIGMA_PATH):
            if '.vavoo_' in fname and (
                    fname.endswith('.tv') or fname.endswith('.radio')):
                if name_safe in fname:
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
        server,
        bouquet_position):
    """Compatible (synchronous) version for existing calls."""
    return convert_bouquet_sync(
        servicetype,
        name,
        url,
        export_type,
        server,
        bouquet_position)


def convert_bouquet_sync(
        servicetype,
        name,
        url,
        export_type,
        server,
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
            epg_entries = [(m['rytec_id'], m['full_service_ref'], m['name'])
                           for m in matched if m['rytec_id']]
            if epg_entries:
                try:
                    write_epg_mapping_file(epg_entries, country_code)
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

        # 9. Save matcher cache (matched channels only - existing code)
        try:
            matcher.save_cache()
        except Exception as e:
            print("[Bouquet] Error saving cache: %s" % e)

        # 10. Persist unmatched channels too - without this, bouquets
        # kept up to date via the scheduled auto-update path (this
        # function) never accumulate retry/diagnostic data in
        # unmatched.json, unlike bouquets refreshed via a manual export
        # (process_epg_matching_background, which already does this).
        try:
            update_complete_cache(matched, unmatched, country_code, servicetype)
        except Exception as e:
            print("[Bouquet] Error updating unmatched cache: %s" % e)

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
                        if parent_screen and hasattr(
                                parent_screen, "session") and parent_screen.session:
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
                    if parent_screen and hasattr(
                            parent_screen, "session") and parent_screen.session:
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
                    if parent_screen and hasattr(
                            parent_screen, "session") and parent_screen.session:
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

        # Proxy URL
        proxy_url = "http://{}:{}/channels?country={}".format(
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
            debug("original_name in ch: {}".format(repr(ch['original_name'])))

            rytec_id, dvb_ref = matcher.find_match(
                ch['original_name'], country_code)
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
                    'rytec_id': rytec_id,
                    'original_url': ch['url']
                })
            else:
                # Unmatched: keep the original sref from the fallback bouquet
                # 'fallback_sref' was stored in ch by create_fallback_bouquet_sync
                unmatched.append({
                    'name': ch['original_name'],
                    'channel_id': ch['channel_id'],
                    'original_url': ch['url'],
                    'original_sref': ch.get('fallback_sref', "4097:0:0:0:0:0:0:0:0:0:")
                })
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
                with io.open(bouquet_path, 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                print(
                    "[EPGBackground] Updated %d service lines in %s" %
                    (changes, bouquet_filename))

        # 5. Generate EPG mapping files
        if matched:
            # full_service_ref (dvb_ref + stream URL) - see the comment
            # where it's built above; a bare dvb_ref gets silently
            # dropped by EPGImport's channelFilter().
            epg_entries = [(m['rytec_id'], m['full_service_ref'], m['name'])
                           for m in matched if m['rytec_id']]
            if epg_entries:
                write_epg_mapping_file(epg_entries, country_code)
                print(
                    "[EPGBackground] EPG mapping written for %d channels" %
                    len(epg_entries))

        # 6. Update sources.xml
        update_epg_sources()

        # 7. Save matcher cache
        matcher.save_cache()

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

        # Update the complete cache with matched channels only;
        # - unmatched go to unmatched.json.
        update_complete_cache(matched, unmatched, country_code, servicetype)

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
        separators = ["➾", "⟾", "->", "→"]
        is_category = any(sep in name for sep in separators)
        if export_type == "flat" or not is_category:
            safe_name = name.lower().replace(
                ' ',
                '_').replace(
                '➾',
                '').replace(
                '⟾',
                '').replace(
                '->',
                '').replace(
                    '→',
                '')
            bouquet_filename = "userbouquet.vavoo_%s.tv" % safe_name
        else:
            country_part = ""
            category_part = ""
            for sep in separators:
                if sep in name:
                    parts = name.split(sep)
                    country_part = parts[0].strip()
                    category_part = parts[1].strip()
                    break
            if not country_part or not category_part:
                safe_name = name.lower().replace(
                    ' ',
                    '_').replace(
                    '➾',
                    '_').replace(
                    '⟾',
                    '_').replace(
                    '->',
                    '_').replace(
                    '→',
                    '_')
                bouquet_filename = "userbouquet.vavoo_%s.tv" % safe_name
            else:
                country_safe = country_part.lower().replace(' ', '_')
                category_safe = category_part.lower().replace(' ', '_')
                bouquet_filename = "userbouquet.vavoo_%s_%s.tv" % (
                    country_safe, category_safe)

        bouquet_path = join(ENIGMA_PATH, bouquet_filename)

        # 6. Build bouquet lines with fallback
        lines = ["#NAME %s" % name]
        channel_count = 0
        channels_list = []

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

                # Clean name
                clean_name = decodeHtml(channel_name)
                clean_name = remove_parentheses(clean_name)
                clean_name = sanitizeFilename(clean_name)

                # Encode URL
                encoded_url = channel_url.replace(':', '%3a')

                # Fallback service reference
                service_line = "#SERVICE %s:0:0:0:0:0:0:0:0:0:%s" % (
                    servicetype, encoded_url)
                lines.append(service_line)
                lines.append("#DESCRIPTION %s" % clean_name)
                channel_count += 1

                # Store for later matching
                channels_list.append({
                    'name': clean_name,
                    'channel_id': channel_id,
                    'url': channel_url,
                    'original_name': channel_name,
                    'fallback_sref': "%s:0:0:0:0:0:0:0:0:0:%s" % (servicetype, encoded_url)
                })

            except Exception as e:
                print(
                    "[FallbackBouquet] Error processing channel: %s" %
                    str(e))
                continue

        if channel_count == 0:
            print("[FallbackBouquet] No valid channels for %s" % name)
            return 0, "", [], ""

        # 7. Write bouquet file
        try:
            with io.open(bouquet_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))
            print(
                "[FallbackBouquet] File created: %s (%d channels)" %
                (bouquet_filename, channel_count))
        except Exception as e:
            print(
                "[FallbackBouquet] Error writing file with encoding: %s" %
                str(e))
            try:
                with open(bouquet_path, 'wb') as f:
                    f.write(('\n'.join(lines)).encode('utf-8', 'ignore'))
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
    where matched_channels is a list of dicts with 'name', 'channel_id', 'dvb_ref', 'rytec_id'
    and unmatched_channels is a list of dicts with 'name', 'channel_id'.
    """
    try:
        print("[Bouquet] Creating bouquet: %s (%s)" % (name, export_type))

        # Determine if it is a country or category
        separators = ["➾", "⟾", "->", "→"]
        is_category = any(sep in name for sep in separators)

        # Prepare file name
        if export_type == "flat" or not is_category:
            safe_name = name.lower().replace(
                ' ',
                '_').replace(
                '➾',
                '').replace(
                '⟾',
                '').replace(
                '->',
                '').replace(
                    '→',
                '')
            bouquet_filename = "userbouquet.vavoo_%s.tv" % safe_name
        else:
            country_part = ""
            category_part = ""
            for sep in separators:
                if sep in name:
                    parts = name.split(sep)
                    country_part = parts[0].strip()
                    category_part = parts[1].strip()
                    break
            if not country_part or not category_part:
                safe_name = name.lower().replace(
                    ' ',
                    '_').replace(
                    '➾',
                    '_').replace(
                    '⟾',
                    '_').replace(
                    '->',
                    '_').replace(
                    '→',
                    '_')
                bouquet_filename = "userbouquet.vavoo_%s.tv" % safe_name
            else:
                country_safe = country_part.lower().replace(' ', '_')
                category_safe = category_part.lower().replace(' ', '_')
                bouquet_filename = "userbouquet.vavoo_%s_%s.tv" % (
                    country_safe, category_safe)

        bouquet_path = join(ENIGMA_PATH, bouquet_filename)

        # Lists to store results
        # Store items for background processing
        # background_items = []
        # each item: {'name': name, 'channel_id': id, 'dvb_ref': ref,
        # 'rytec_id': rytec_id}
        matched = []
        unmatched = []    # each item: {'name': name, 'channel_id': id}
        tv_lines = ["#NAME %s" % name]
        channel_count = 0
        for channel in channels:
            try:
                if not isinstance(channel, dict):
                    continue
                channel_name = channel.get('name', 'Unknown')
                channel_url = channel.get('url', '')
                channel_id = channel.get('id', '')
                if not channel_name or not channel_url or not channel_id:
                    continue

                # Clean name for description and matching
                clean_name = decodeHtml(channel_name)
                clean_name = remove_parentheses(clean_name)
                clean_name = sanitizeFilename(clean_name)

                # Encode URL for Enigma2 (replace ':' with '%3a')
                encoded_url = channel_url.replace(':', '%3a')

                # Perform matching once
                service_line = "#SERVICE {}:0:0:0:0:0:0:0:0:0:{}".format(
                    servicetype, encoded_url)
                rytec_id, dvb_ref = matcher.find_match(
                    channel_name, country_code)

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
                        'rytec_id': rytec_id
                    })
                else:
                    # Fallback: first 10 fields all zero (except servicetype
                    # and third field = 1)
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

        if channel_count == 0:
            print("[Bouquet] No valid channels for %s" % name)
            return 0, "", [], []

        # Write bouquet file
        try:
            with io.open(bouquet_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(tv_lines))
            print(
                "[Bouquet] File created: %s (%d channels)" %
                (bouquet_filename, channel_count))
        except Exception as e:
            print("[Bouquet] Error writing file with encoding: %s" % str(e))
            try:
                with open(bouquet_path, 'wb') as f:
                    f.write(('\n'.join(tv_lines)).encode('utf-8', 'ignore'))
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
    """Update Favorite.txt - URL is always empty (proxy only)"""

    favorite_path = join(PLUGIN_ROOT, 'Favorite.txt')
    print("[Bouquet] Updating Favorite.txt: " +
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
            print("[Bouquet] Error reading Favorite.txt: " + str(e))

    # Update/add current bouquet
    existing_bouquets[name] = {
        'url': "",  # ALWAYS empty (proxy only)
        'export_type': export_type,
        'timestamp': str(time.time())
    }

    # Write file
    try:
        with io.open(favorite_path, 'w', encoding='utf-8') as f:
            for bouq_name, bouq_data in sorted(existing_bouquets.items()):
                line = bouq_name + "|" + \
                    bouq_data['url'] + "|" + bouq_data['export_type'] + "|" + bouq_data['timestamp']
                f.write(line + "\n")

        print("[Bouquet] Favorite.txt updated with " +
              str(len(existing_bouquets)) + " bouquets")

    except Exception as e:
        print("[Bouquet] Error writing Favorite.txt: " + str(e))


def remove_favorite_entry(name):
    """Remove a single bouquet's entry from Favorite.txt, if present.

    Counterpart to _update_favorite_file() - keeps a per-country/category
    "Remove Fav" from leaving a stale entry that a later scheduled
    auto-update run would just re-create.
    """
    favorite_path = join(PLUGIN_ROOT, 'Favorite.txt')
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
            with io.open(favorite_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(remaining) + '\n')
        else:
            remove(favorite_path)
        print("[Bouquet] Removed {} from Favorite.txt".format(name))
    except Exception as e:
        print("[Bouquet] Error removing {} from Favorite.txt: {}".format(name, e))


def reorganize_all_bouquets_position(list_position="bottom"):
    """Reorganize all Vavoo bouquets to the configured position"""
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
                if 'vavoo' in line.lower():
                    vavoo_lines.append(line)
                else:
                    non_vavoo_lines.append(line)

            # Apply the configured position
            if list_position == "top":
                new_lines = vavoo_lines + non_vavoo_lines
            else:
                new_lines = non_vavoo_lines + vavoo_lines

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
