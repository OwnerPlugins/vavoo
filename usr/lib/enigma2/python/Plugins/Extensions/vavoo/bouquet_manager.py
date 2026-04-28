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
from os import listdir, remove
from os.path import exists as file_exists, isfile, join, basename
from re import compile, search
from enigma import eTimer
from Components.config import config
from Tools.Directories import SCOPE_PLUGINS, resolveFilename

from .vUtils import (
    decodeHtml,
    getUrl,
    get_country_code_from_bouquet_name,
    get_epg_matcher,
    get_proxy_channels,
    is_proxy_ready,
    is_proxy_running,
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
    # CACHE_FILE,
    # UNMATCHED_FILE,
    # SREF_MAP_FILE,
    # export_lock,
    PY3,
    PORT,
    PLUGIN_ROOT,
    PROXY_HOST,
    ENIGMA_PATH,
    country_codes
)

"""
#########################################################
#                                                       #
#  Vavoo Stream Live Plugin                             #
#  Created by Lululla (https://github.com/Belfagor2005) #
#  License: CC BY-NC-SA 4.0                             #
#  https://creativecommons.org/licenses/by-nc-sa/4.0    #
#  Last Modified: 20260315                              #
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

try:
    from urllib.parse import unquote, quote
except ImportError:
    from urllib import unquote, quote


# Constants
PLUGIN_PATH = PLUGIN_ROOT
PLUGIN_PATH = resolveFilename(SCOPE_PLUGINS, "Extensions/{}".format('vavoo'))

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def get_local_ip():
    """Get the local IP address"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except BaseException:
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
        # Read existing content
        if isfile(main_bouquet_path):
            with open(main_bouquet_path, 'r') as f:
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

        # Write file
        with open(main_bouquet_path, 'w') as f:
            f.writelines(new_lines)

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
                with open(bouquet_path, 'r') as f:
                    lines = f.readlines()

                # Keep only lines that do not contain ".vavoo_"
                new_lines = [line for line in lines if '.vavoo_' not in line]

                with open(bouquet_path, 'w') as f:
                    f.writelines(new_lines)

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
        separators = ["➾", "⟾", "->", "→"]
        base_name = name
        for sep in separators:
            if sep in name:
                base_name = name.split(sep)[0].strip()
                break
        country_code = country_codes.get(base_name.capitalize(), "")

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
            # Now include the channel name as well
            epg_entries = [(m['rytec_id'], m['dvb_ref'], m['name'])
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
    print(
        "[DEBUG] export_bouquet_async called for %s, type %s" %
        (name, export_type))

    def task():
        try:
            print("[DEBUG] Background task started for %s" % name)

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

                timer = eTimer()
                timer.callback.append(do_callback)
                timer.start(0, True)
                return

            # Instant recharge of services to make the bouquet visible
            def do_reload():
                try:
                    ReloadBouquets()
                    print("[Bouquet] Services reloaded after fallback creation")
                except Exception as e:
                    print("[Bouquet] Error reloading services: %s" % e)

            reload_timer = eTimer()
            reload_timer.callback.append(do_reload)
            reload_timer.start(500, True)   # 500 ms di delay
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

            timer = eTimer()
            timer.callback.append(do_first_callback)
            timer.start(0, True)

            # PHASE 2: Process EPG matching in background (same thread)
            if channels_list:
                process_epg_matching_background(
                    name, bouquet_filename, channels_list, country_code,
                    parent_screen, callback
                )
            else:
                # No channels for EPG, just call callback again? Already
                # called.
                pass

        except Exception as e:
            print("[DEBUG] Background task error: %s" % str(e))
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

            timer = eTimer()
            timer.callback.append(do_callback)
            timer.start(0, True)

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


def _prepare_bouquet_filenames(name, bouquet_type, max_length=100):
    """Prepare sanitized file names for bouquet creation with ReDoS protection"""
    # Convert to string and truncate to prevent excessively long inputs
    name_str = str(name)
    if len(name_str) > max_length:
        name_str = name_str[:max_length]
        print("WARNING: Input truncated to {} characters".format(max_length))

    # Use compiled regex patterns for better performance
    # Simple character class replacements - safe from backtracking
    invalid_chars = compile(r'[<>:"/\\|?*, ]')
    digit_colon_pattern = compile(
        r'\d+:\d+(?:\.\d+)+')  # More specific pattern
    multiple_underscores = compile(r'_+')
    non_alnum = compile(r'[^a-zA-Z0-9_]')

    # Apply patterns in sequence
    name_file = invalid_chars.sub('_', name_str)
    name_file = digit_colon_pattern.sub('_', name_file)
    name_file = multiple_underscores.sub('_', name_file)
    name_file = non_alnum.sub('', name_file)

    # Check for separators with length limits
    separators = ["➾", "⟾", "->", "→"]
    has_separator = False
    separator_found = None

    for sep in separators:
        if sep in name_str:
            has_separator = True
            separator_found = sep
            break

    if has_separator and separator_found:
        # Split only once to avoid unnecessary processing
        parts = name_str.split(separator_found, 1)
        if len(parts) >= 2:
            # Limit the length of each part
            country_part = parts[0].strip().lower().replace(' ', '_')[:50]
            category_part = parts[1].strip().lower().replace(' ', '_')[:50]
            name_file = country_part + "_" + category_part
        else:
            name_file = name_file[:100]  # Truncate if something went wrong

    # Ensure final filename has reasonable length
    name_file = name_file[:100]

    if has_separator:
        bouquet_name = "subbouquet.vavoo_" + name_file + "." + bouquet_type.lower()
        print("DEBUG: Creating SUBBOUQUET: " + bouquet_name)
    else:
        bouquet_name = "userbouquet.vavoo_" + name_file.lower() + "." + \
            bouquet_type.lower()
        print("DEBUG: Creating USERBOUQUET: " + bouquet_name)

    return name_file, bouquet_name


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
            print("[DEBUG] original_name in ch:", repr(ch['original_name']))

            rytec_id, dvb_ref = matcher.find_match(
                ch['original_name'], country_code)
            if dvb_ref:
                if dvb_ref.endswith(':'):
                    dvb_ref = dvb_ref[:-1]
                matched.append({
                    'name': ch['original_name'],
                    'channel_id': ch['channel_id'],
                    'dvb_ref': dvb_ref,
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
        if file_exists(bouquet_path):
            # Read current lines
            with io.open(bouquet_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            new_lines = []
            i = 0
            changes = 0
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
            epg_entries = [(m['rytec_id'], m['dvb_ref'], m['name'])
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

        # 8. Callback to notify completion
        print(
            "[EPGBackground] COMPLETED for %s - matched=%d" %
            (name, len(matched)))
        print("[EPGBackground] Calling callback with message='EPG processing completed'")
        try:
            saved_callback(True, saved_matched, "EPG processing completed")
        except Exception as cb_e:
            print("[EPGBackground] Error in completion callback: %s" % cb_e)

        # Update the complete cache with matched channels only;
        # - unmatched go to unmatched.json.
        update_complete_cache(matched, unmatched, country_code, servicetype)

    except Exception as exc:
        print("[EPGBackground] Error: %s" % str(exc))
        trace_error()
        try:
            callback(False, 0, str(exc))
        except Exception as cb_e:
            print("[EPGBackground] Error in error callback: %s" % cb_e)


def _create_flat_bouquet_proxy(
        country_name,
        channels,
        servicetype,
        bouquet_position):
    """Create a flat bouquet (no categories) using proxy channels"""
    try:
        # Prepare file names
        safe_name = country_name.lower().replace(' ', '_')
        bouquet_name = "userbouquet.vavoo_%s.tv" % safe_name
        bouquet_path = join(ENIGMA_PATH, bouquet_name)

        # Create bouquet lines
        lines = ["#NAME %s" % country_name]
        for channel in channels:
            channel_name = channel.get('name', '')
            channel_url = channel.get('url', '')
            if not channel_name or not channel_url:
                continue

            # Encode URL
            encoded_url = channel_url.replace(":", "%3a")
            encoded_name = channel_name.replace(":", "%3a")

            # Add service line
            line = "#SERVICE %s:0:0:0:0:0:0:0:0:0:%s:%s" % (
                servicetype, encoded_url, encoded_name)
            lines.append(line)
            lines.append("#DESCRIPTION %s" % channel_name)

        # Write the file
        with open(bouquet_path, 'w') as f:
            f.write('\n'.join(lines))

        # Add to main bouquet
        _add_to_main_bouquet(bouquet_name, 'tv', bouquet_position)

        return len(channels)

    except Exception as e:
        print("[Flat Bouquet] Error: %s" % str(e))
        return 0


def _create_hierarchical_bouquet_proxy(
        category_name,
        channels,
        servicetype,
        bouquet_position):
    """Create a bouquet for a category and add it to the country's container"""
    try:
        # Extract country and category from name (e.g., "Italy ➾ Sports")
        separators = ["➾", "⟾", "->", "→"]
        country = None
        category = None

        for sep in separators:
            if sep in category_name:
                parts = category_name.split(sep)
                country = parts[0].strip()
                category = parts[1].strip()
                break

        if not country or not category:
            print("[Hierarchical] Invalid category name: %s" % category_name)
            return 0

        # Create the bouquet for the category
        safe_country = country.lower().replace(' ', '_')
        safe_category = category.lower().replace(' ', '_')
        bouquet_name = "subbouquet.vavoo_%s_%s.tv" % (
            safe_country, safe_category)
        bouquet_path = join(ENIGMA_PATH, bouquet_name)

        # Create bouquet lines
        lines = ["#NAME %s - %s" % (country, category)]

        for channel in channels:
            channel_name = channel.get('name', '')
            channel_url = channel.get('url', '')
            if not channel_name or not channel_url:
                continue

            encoded_url = channel_url.replace(":", "%3a")
            encoded_name = channel_name.replace(":", "%3a")

            line = "#SERVICE %s:0:0:0:0:0:0:0:0:0:%s:%s" % (
                servicetype, encoded_url, encoded_name)
            lines.append(line)
            lines.append("#DESCRIPTION %s" % channel_name)

        with open(bouquet_path, 'w') as f:
            f.write('\n'.join(lines))

        # Update country container
        container_name = "userbouquet.vavoo_%s_cowntry.tv" % safe_country
        container_path = join(ENIGMA_PATH, container_name)

        # Read existing container or create new
        if isfile(container_path):
            with open(container_path, 'r') as f:
                container_lines = f.read().splitlines()
        else:
            container_lines = ["#NAME %s - Categories" % country]

        # Add reference to sub-bouquet if not already present
        new_line = '#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "%s" ORDER BY bouquet' % bouquet_name
        if new_line not in container_lines:
            container_lines.append(new_line)
            with open(container_path, 'w') as f:
                f.write('\n'.join(container_lines))

            # Add container to main bouquet if not already present
            _add_to_main_bouquet(container_name, 'tv', bouquet_position)

        return len(channels)

    except Exception as e:
        print("[Hierarchical Bouquet] Error: %s" % str(e))
        return 0


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
        separators = ["➾", "⟾", "->", "→"]
        base_name = name
        for sep in separators:
            if sep in name:
                base_name = name.split(sep)[0].strip()
                break
        country_code = country_codes.get(base_name.capitalize(), "")

        # 5. Prepare bouquet filename (same logic as create_bouquet_file)
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


# not used
def _create_flat_bouquet(name, url, service, bouquet_type, server_url):
    """Create flat bouquet using PROXY ONLY"""
    try:
        print(
            "[bouquet_manager] Creating bouquet for: " +
            name +
            " using proxy")

        # Get channels from proxy
        channels = get_proxy_channels(name)

        if not channels:
            print("[bouquet_manager] No channels received from proxy for: " + name)
            return 0

        # Prepare filenames
        safe_name = name.lower().replace(' ', '_')
        bouquet_name = "userbouquet.vavoo_" + safe_name + "." + bouquet_type
        bouquet_path = join(ENIGMA_PATH, bouquet_name)

        # Build bouquet
        content_lines = ["#NAME " + name]
        ch_count = 0

        # Use proxy URL format
        for channel in channels:
            if not isinstance(channel, dict):
                continue

            name_channel = channel.get("name", "")
            if not name_channel:
                continue

            name_channel = decodeHtml(name_channel)
            name_channel = remove_parentheses(name_channel)
            name_channel = sanitizeFilename(name_channel)

            channel_id = channel.get("id", "")
            if not channel_id:
                continue

            # Use proxy URL format
            url_channel = "https://" + PROXY_HOST + ":" + \
                str(PORT) + "/vavoo?channel=" + channel_id

            tag = "2" if bouquet_type.upper() == "RADIO" else "1"
            url_encoded = url_channel.replace(":", "%3a")

            service_line = "#SERVICE " + \
                str(service) + ":0:" + tag + ":0:0:0:0:0:0:0:" + url_encoded + ":" + name_channel
            desc_line = "#DESCRIPTION " + name_channel

            content_lines.append(service_line)
            content_lines.append(desc_line)
            ch_count += 1

        if ch_count == 0:
            print("[bouquet_manager] No valid channels found for: " + name)
            return 0

        # Save file
        try:
            if PY3:
                with io.open(bouquet_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(content_lines))
            else:
                with open(bouquet_path, 'w') as f:
                    f.write('\n'.join(content_lines).encode('utf-8'))
        except Exception as e:
            print("[bouquet_manager] Error writing with encoding: " + str(e))
            with open(bouquet_path, 'w') as f:
                f.write('\n'.join(content_lines))

        _add_to_main_bouquet(bouquet_name, bouquet_type)

        print("[bouquet_manager] Created bouquet: " +
              bouquet_name + " (" + str(ch_count) + " channels)")
        return ch_count

    except Exception as error:
        print("[bouquet_manager] Error in _create_flat_bouquet: " + str(error))
        trace_error()
        return 0


# not used
def _create_hierarchical_bouquet(
        country_name,
        url,
        service,
        app,
        bouquet_type,
        server_url,
        list_position="bottom"):
    """Create hierarchical bouquet structure with only exported categories"""
    try:
        # Get all data to find categories for this country
        content = getUrl(url)
        if PY3:
            content = content.decode(
                "utf-8") if isinstance(content, bytes) else content
        all_data = loads(content)

        # Use robust approach for separators
        separators = ["➾", "⟾", "->", "→"]

        # Find all categories for this country
        all_categories = set()
        for entry in all_data:
            country = unquote(entry["country"]).strip("\r\n")
            # Check if starts with the country and has any separator
            if country.startswith(country_name) and any(
                    sep in country for sep in separators):
                all_categories.add(country)

        if not all_categories:
            print(
                "[bouquet_manager] No categories found for " +
                country_name +
                ", using flat structure")
            return _create_flat_bouquet(
                country_name, url, service, bouquet_type, server_url
            )

        # Create category sub-bouquets (children) and track which ones were
        # created
        exported_categories = []
        total_ch = 0
        for category in sorted(all_categories):
            ch_count = _create_category_bouquet(
                category, url, service, bouquet_type, server_url
            )
            if ch_count > 0:  # Only add successfully exported categories
                exported_categories.append(category)
                total_ch += ch_count

        # Create container bouquet (parent) with only exported categories
        if exported_categories:
            container_ch_count = _create_or_update_container_bouquet(
                country_name, exported_categories, bouquet_type, list_position
            )
        else:
            container_ch_count = 0

        return total_ch + container_ch_count

    except Exception as error:
        print(
            "[bouquet_manager] Error creating hierarchical bouquet: " +
            str(error))
        return _create_flat_bouquet(
            country_name,
            url,
            service,
            bouquet_type,
            server_url
        )


# not used
def _create_or_update_container_bouquet(
        country_name, new_categories, bouquet_type, list_position="bottom"):
    """Create or update container bouquet"""
    print("[bouquet_manager] _create_or_update_container_bouquet called")
    print("[bouquet_manager] country_name = " + country_name)
    print("[bouquet_manager] new_categories = " + str(new_categories))

    # Container filename
    container_name = "userbouquet.vavoo_" + country_name.lower().replace(' ', '_') + \
        "_cowntry." + bouquet_type
    container_path = join(ENIGMA_PATH, container_name)

    # Read existing content to preserve already added categories
    existing_categories = set()
    content = []

    if isfile(container_path):
        with open(container_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#NAME'):
                    content = [line]  # Keep existing name
                elif line.startswith('#SERVICE') and 'FROM BOUQUET "' in line:
                    # Extract subbouquet reference from existing line
                    parts = line.split('FROM BOUQUET "')
                    if len(parts) > 1:
                        subbouquet_ref = parts[1].split('"')[0]
                        existing_categories.add(subbouquet_ref)
                        content.append(line)  # Keep existing categories
    else:
        content = ["#NAME " + country_name + " - Categories"]

    # Process each new category
    for category in sorted(new_categories):
        category_part = category
        for sep in ["➾", "⟾", "->", "→"]:
            if sep in category:
                category_part = category.split(sep)[1].strip()
                break

        country_safe = country_name.lower().replace(' ', '_')
        category_safe = category_part.lower().replace(' ', '_')
        subbouquet_ref = "subbouquet.vavoo_" + country_safe + \
            "_" + category_safe + "." + bouquet_type

        if subbouquet_ref not in existing_categories:
            bouquet_line = '#SERVICE 1:7:1:0:0:0:0:0:0:0:FROM BOUQUET "' + \
                subbouquet_ref + '" ORDER BY bouquet'
            content.append(bouquet_line)
            existing_categories.add(subbouquet_ref)
            print(
                "[bouquet_manager] Added new subbouquet reference: " +
                subbouquet_ref)
        else:
            print(
                "[bouquet_manager] Subbouquet already exists: " +
                subbouquet_ref)

    print("[bouquet_manager] Final content lines: " + str(len(content)))
    print("[bouquet_manager] Total categories in container: " +
          str(len(existing_categories)))

    # Write the container bouquet file
    try:
        with open(container_path, 'w') as f:
            for line in content:
                f.write(line + '\n')
        print("[bouquet_manager] ✓ Container bouquet updated: " +
              container_name +
              " with " +
              str(len(existing_categories)) +
              " categories")

        # Add to main bouquet
        _add_to_main_bouquet(container_name, bouquet_type, "bottom")

        return len(existing_categories)

    except Exception as e:
        print(
            "[bouquet_manager] ERROR: Failed to save container bouquet: " +
            str(e))
        return 0


# not used
def _create_category_bouquet(
        category_name,
        url,
        service,
        bouquet_type,
        server_url):
    """Create category bouquet using PROXY ONLY"""
    try:
        print("[bouquet_manager] Creating category bouquet: " + category_name)

        separators = ["➾", "⟾", "->", "→"]
        country_part = None
        category_part = None

        for sep in separators:
            if sep in category_name:
                parts = category_name.split(sep)
                if len(parts) >= 2:
                    country_part = parts[0].strip()
                    category_part = parts[1].strip()
                    break

        if country_part is None or category_part is None:
            print("ERROR: Could not parse category: " + category_name)
            return 0

        # Get channels from proxy for the main country
        channels = get_proxy_channels(country_part)

        if not channels:
            print(
                "[bouquet_manager] No channels received from proxy for: " +
                country_part)
            return 0

        # Filter channels for this specific category
        filtered_channels = []
        for channel in channels:
            if not isinstance(channel, dict):
                continue

            channel_country = channel.get("country", "")
            if category_name == channel_country:
                filtered_channels.append(channel)

        if not filtered_channels:
            print(
                "[bouquet_manager] No channels found for category: " +
                category_name)
            return 0

        # Prepare filenames
        country_safe = country_part.lower().replace(' ', '_')
        category_safe = category_part.lower().replace(' ', '_')
        bouquet_name = "subbouquet.vavoo_" + country_safe + \
            "_" + category_safe + "." + bouquet_type
        bouquet_path = join(ENIGMA_PATH, bouquet_name)

        # Build bouquet
        content_lines = ["#NAME " + country_part + " - " + category_part]
        ch_count = 0

        # Use proxy URL format
        for channel in filtered_channels:
            name_channel = channel.get("name", "")
            if not name_channel:
                continue

            name_channel = decodeHtml(name_channel)
            name_channel = remove_parentheses(name_channel)
            name_channel = sanitizeFilename(name_channel)

            channel_id = channel.get("id", "")
            if not channel_id:
                continue

            # Use proxy URL format
            url_channel = "https://" + PROXY_HOST + ":" + \
                str(PORT) + "/vavoo?channel=" + channel_id

            tag = "2" if bouquet_type.upper() == "RADIO" else "1"
            url_encoded = url_channel.replace(":", "%3a")

            service_line = "#SERVICE " + \
                str(service) + ":0:" + tag + ":0:0:0:0:0:0:0:" + url_encoded + ":" + name_channel
            desc_line = "#DESCRIPTION " + name_channel

            content_lines.append(service_line)
            content_lines.append(desc_line)
            ch_count += 1

        # Save file
        try:
            if PY3:
                with io.open(bouquet_path, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(content_lines))
            else:
                with open(bouquet_path, 'w') as f:
                    f.write('\n'.join(content_lines).encode('utf-8'))
        except Exception as e:
            print("[bouquet_manager] Error writing with encoding: " + str(e))
            with open(bouquet_path, 'w') as f:
                f.write('\n'.join(content_lines))

        print("Created category bouquet: " + bouquet_name +
              " (" + str(ch_count) + " channels)")
        return ch_count

    except Exception as e:
        print("Error in _create_category_bouquet: " + str(e))
        trace_error()
        return 0


def _update_favorite_file(name, url, export_type):
    """Update Favorite.txt - URL is always empty (proxy only)"""

    favorite_path = join(PLUGIN_PATH, 'Favorite.txt')
    print("[Bouquet] Updating Favorite.txt: " +
          name + " (type: " + export_type + ")")

    # Read existing bouquets
    existing_bouquets = {}
    if isfile(favorite_path):
        try:
            with open(favorite_path, 'r') as f:
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
        with open(favorite_path, 'w') as f:
            for bouq_name, bouq_data in sorted(existing_bouquets.items()):
                line = bouq_name + "|" + \
                    bouq_data['url'] + "|" + bouq_data['export_type'] + "|" + bouq_data['timestamp']
                f.write(line + "\n")

        print("[Bouquet] Favorite.txt updated with " +
              str(len(existing_bouquets)) + " bouquets")

    except Exception as e:
        print("[Bouquet] Error writing Favorite.txt: " + str(e))


def reorganize_all_bouquets_position(list_position="bottom"):
    """Reorganize all Vavoo bouquets to the configured position"""
    try:
        for bouquet_type in ['tv', 'radio']:
            main_bouquet_path = join(ENIGMA_PATH, "bouquets." + bouquet_type)

            if not isfile(main_bouquet_path):
                continue

            with open(main_bouquet_path, 'r') as f:
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

            with open(main_bouquet_path, 'w') as f:
                f.writelines(new_lines)

        print("Reorganized all Vavoo bouquets to " + list_position)
        return True

    except Exception as e:
        print("Error reorganizing bouquets: " + str(e))
        return False
