<h1 align="center">🎬 Vavoo Stream Live</h1>

<p align="center">
  <a href="https://github.com/Belfagor2005/vavoo">
    <img src="https://img.shields.io/badge/Version-1.88-blue.svg" alt="Version">
  </a>

  <a href="https://www.enigma2.net">
    <img src="https://img.shields.io/badge/Enigma2-Plugin-ff6600.svg" alt="Enigma2">
  </a>

  <a href="https://python.org">
    <img src="https://img.shields.io/badge/Python-2.7%2F3.x-yellow.svg" alt="Python">
  </a>

  <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">
    <img src="https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-green.svg" alt="License">
  </a>

  <a href="https://github.com/Belfagor2005/vavoo/actions/workflows/pylint.yml">
    <img src="https://github.com/Belfagor2005/vavoo/actions/workflows/pylint.yml/badge.svg" alt="Pylint">
  </a>

</p>

<p align="center">
  <a href="https://github.com/Belfagor2005">
    <img src="https://komarev.com/ghpvc/?username=Belfagor2005&label=Repository%20Views&color=blueviolet" alt="Visitors">
  </a>
</p>

<p align="center">
  <a href="https://ko-fi.com/lululla">
    <img src="https://img.shields.io/badge/_-Donate-red.svg?logo=githubsponsors&labelColor=555555&style=for-the-badge" alt="Ko-fi">
  </a>

  <a href="https://paypal.me/belfagor2005">
    <img src="https://img.shields.io/badge/_-Donate-green.svg?logo=githubsponsors&labelColor=555555&style=for-the-badge" alt="PayPal">
  </a>
</p>

## 📌 Overview
Vavoo Stream Live Plugin is an Enigma2 extension that provides access to thousands of live TV channels from multiple countries. It features a built-in local proxy that keeps streams stable, a choice of stream source per channel, automatic bouquet updates, EPG integration, real-time notifications, satellite priority matching, and seamless integration with your Enigma2 receiver.

## 🖼️ Screenshots

| <img src="https://raw.githubusercontent.com/Belfagor2005/vavoo/main/screen/screen9.gif" width="400"> |

## ✨ Key Features

### Watching
- **Live TV Streaming** – Thousands of live channels, browsed by country, with country flags and channel logos (picons)
- **Stable Streams** – The local proxy keeps one stream address for the whole viewing. When a stream fails it is retried with a fresh address, and if it fails again the plugin moves to another source of the same channel by itself
- **Choose Your Source** – A channel available from several sources is shown as one row. Press **YELLOW** in the player to pick the source by its own name (for example "SIC .b", "SIC HD .s"). The pick is remembered, also for exported bouquets
- **Player Overlay** – Press OK for the current programme, the channel logo and the proxy status; INFO looks the programme up in IMDb/TMDB
- **Search** – Find channels by name inside a country
- **Favourites** – Star/unstar any channel with the INFO key while browsing; "View Favourites" in Config to browse and play them
- **Parental Control** – Optional PIN lock on chosen countries

### In your Enigma2 channel list
- **Enigma2 Bouquet Export** – Export a country's channels straight into your channel list, at the top or the bottom
- **Scheduled Updates** – Re-match EPG and refresh the exported bouquets at an interval or at a fixed time of day
- **EPG Integration** – Electronic Program Guide for supported channels, through EPGImport, served via GitHub
- **Satellite Priority Matching** – EPG matching that prefers the satellites configured on your box
- **M3U Playlist Generation** – Create standard M3U playlist files for external players
- **Live Playlist Server** – `/playlist.m3u` always reflects the current catalog, no manual regeneration needed; optional access key

### Under the hood
- **Local Proxy** – Always on, handles the authentication tokens (no 10-minute blocks), with its status shown in the main screens
- **Two Catalog Sources** – Geil (default, needs no token) with automatic fallback to Vavoo/Kool, or pin one of them in the settings
- **Mirror Fallback** – Automatic switch to a mirror when a site answers HTTP 451 or is unreachable
- **Real-time Notifications** – A bar at the top of the screen for exports, EPG processing and errors, on any screen resolution
- **Update Check** – On start the plugin checks for a newer version and shows its changelog; one key press installs it
- **In-UI Log Viewer** – "Show Log" in Config shows the last 200 lines of `vavoo.log`; "Debug logging" adds detail when troubleshooting
- **Cache Format Fix** – YELLOW in the main menu cleans up the EPG match cache
- **Multi-Language** – Translated into 90+ languages
- **Custom Backgrounds** – Selectable background image
- **Anonymous Statistics** – Opt-out, no personal data (see Privacy below)

## 🎮 Remote Control Keys

### Main menu (country list)
| Key | Action |
|-----|--------|
| OK | Open the selected country |
| MENU | Settings |
| GREEN | Remove ALL exported Vavoo bouquets (asks first) |
| YELLOW | Fix the EPG cache format |
| BLUE | Reload bouquets |
| EPG | Start an EPG import now (needs "Enable Vavoo EPG") |
| INFO | About the plugin |
| TEXT | Refresh the proxy token |
| CH+ / CH- | Page up / down |
| RED / EXIT | Quit |

### Channel list
| Key | Action |
|-----|--------|
| OK | Play the channel |
| GREEN | Export this country as a bouquet; on an already exported one, remove it |
| YELLOW | Search |
| BLUE | Reload bouquets |
| INFO | Star / unstar as favourite |
| MENU | Settings |
| CH+ / CH- | Page up / down |
| RED / EXIT | Back |

### Player
| Key | Action |
|-----|--------|
| CH+ / CH- or UP / DOWN | Next / previous channel |
| OK | Show / hide the overlay (programme, logo, proxy status) |
| YELLOW | Choose Stream Source (channels with more than one source) |
| INFO or EPG | Look up the current programme in IMDb/TMDB (needs "Enable Vavoo EPG" and an IMDb or TMDB plugin) |
| STOP / EXIT | Close the player |

LEFT and RIGHT do nothing during live playback (there is nothing to seek in a live stream).

### Search
| Key | Action |
|-----|--------|
| Number keys | Type |
| GREEN | On-screen keyboard |
| YELLOW | Backspace |
| BLUE | Space |
| RED | Clear all |
| OK | Play the selected result |

### Favourites
| Key | Action |
|-----|--------|
| OK | Play |
| GREEN | Remove the highlighted favourite |
| RED / EXIT | Back |

### Settings
| Key | Action |
|-----|--------|
| OK | Run the highlighted action ("Ok for Exec", "Ok to view", "Ok to open") or edit a text field |
| LEFT / RIGHT | Change the highlighted option |
| GREEN | Save |
| RED / EXIT | Leave without saving (asks if something changed) |

## 🔔 Notifications
A bar at the top of the screen gives feedback while you work:
- **Welcome message** when the plugin starts
- **Export progress** – "Export started. Bouquet will be available shortly.", then the EPG result
- **Errors and warnings** – for example "An export for another country is already in progress. Please wait."
- **Player notices** – for example "Only one source available for this channel"

Each message stays for a few seconds and then hides by itself. The bar is centred on HD, Full HD and WQHD screens.

## 🚀 Quick Start Guide

### First-Time Setup
1. **Open the Vavoo Plugin** – The proxy starts automatically (a start screen shows its progress)
2. **Select a Country** – Choose your desired country (e.g., "Italy") and press OK
3. **Watch** – Press OK on a channel to play it
4. **Export (optional)** – In the channel list press GREEN to export the country to your Enigma2 bouquets (notifications show progress). Pressing GREEN again on an exported country offers to remove it
5. **Return to TV** – Your channels appear in the channel list

### Automatic Updates (Recommended)
- Go to **MENU (Config)** → set **"Scheduled EPG/Bouquet Update:"** to on
- Choose the schedule type: an interval (5-3600 minutes, in 5-minute steps) or a fixed time of day
- The exported bouquets and their EPG matching are then refreshed in the background

### EPG Setup
- Turn on **"Enable Vavoo EPG"** in the configuration menu
- Export (or re-export) a country: the plugin writes that country's EPG files to `/etc/epgimport/` and enables the "Vavoo" sources in EPGImport for you
- Press **EPG** in the main menu to start an EPG import right away
- In the player, press OK to see the current programme

### Cache Maintenance
- Press **YELLOW button** in the main menu to fix cache format
- This will add missing fields and remove duplicate entries
- A notification will show the result

## 🔧 User Configuration
Press **MENU** in the main menu or the channel list. Options appear in this order:

| Option | What it does | Default |
|--------|--------------|---------|
| **Generate .m3u files (Ok for Exec)** | Press OK to export `.m3u` playlist files (one country or all), with links for this box only (127.0.0.1) or for other devices on your network | – |
| **Playlist Access Key (optional)** | If set, the live playlist at `/playlist.m3u` requires `?key=<this value>` | empty (no key) |
| **Catalog/Stream Source** | Where channels and streams come from: "Auto (Geil, fallback Vavoo)", "Geil only" or "Vavoo/Kool only". Saving a change restarts the proxy | Auto |
| **Proxy startup timeout (seconds)** | How long the start screen waits for the proxy. Raise it on a slow connection or VPN | 120 (15-300) |
| **Enable Vavoo EPG** | Creates the EPG source for EPGImport with Vavoo programme data and enables it there after each export | Off |
| **Scheduled EPG/Bouquet Update:** | Periodically re-matches EPG and refreshes the bouquets of your exported countries in the background | Off |
| – **Schedule type:** | "interval" or "fixed time" (shown when the schedule is on) | interval |
| – **EPG/Bouquet update interval (minutes):** | How often, counting from now | 360 (5-3600) |
| – **Time to start EPG/bouquet update:** | Time of day, for "fixed time" | – |
| **Movie Services Reference** | The Enigma2 player used for streams: 4097 always; 5001 when gstplayer is installed; 5002 when exteplayer3 is installed; 8193 on DreamOS images | 4097 |
| **Bouquet Position in List** | Put the Vavoo bouquets at the top or the bottom of the channel list | Bottom |
| **Select Background** | Background image of the plugin screens | oktus |
| **Link in Main Menu** | Show the plugin in the main Enigma2 menu | Yes |
| **Send Anonymous Statistics** | Anonymous startup/heartbeat ping (see Privacy below) | Yes |
| **Debug logging** | Verbose messages in `vavoo.log`; takes effect immediately. Leave off unless troubleshooting | No |
| **Show Log (Ok to view)** | View the last 200 lines of `/tmp/vavoo.log` | – |
| **View Favourites (Ok to open)** | Browse and play your starred channels | – |
| **Parental Control PIN** | Set a PIN to lock the countries below; empty disables parental control | empty (off) |
| – **Locked Countries** | Comma-separated country names (e.g. "Italy, Spain") that need the PIN to open (shown once a PIN is set) | empty |

The local proxy has no on/off switch: every channel list and stream goes through it, and it is started and monitored automatically.

**Removed in this version:** "Proxy Enabled" (the proxy is always on), "Auto-update EPG" (now simply part of "Enable Vavoo EPG") and "EPG Similarity Threshold" (fixed at 75%).

### Favourites
- Press **INFO** on any channel while browsing to star/unstar it
- Config Menu → **"View Favourites"** to browse and play your starred channels (GREEN removes the highlighted one)

### Parental Control
- Config Menu → **"Parental Control PIN"**: enter a PIN, then list the countries to lock in **"Locked Countries"**
- Opening a locked country, or playing a favourite from one, asks for the PIN first

### Choosing a stream source
- Channels that exist from several sources (Vavoo's ".b" / ".c" / ".s" variants and the like) appear once in the list
- While such a channel is playing, press **YELLOW**: the menu lists every source by its channel name and marks the one in use with "(current)"
- Pick another one if a source buffers or keeps stopping. The choice is remembered for that channel, also in exported bouquets

## 🎯 Benefits
- ✅ **No 10-minute blocks** – Proxy handles authentication tokens
- ✅ **Streams that stay up** – One address per viewing, automatic recovery when a source fails
- ✅ **Automatic updates** – Keep bouquets fresh without manual work
- ✅ **EPG support** – Program guide for many channels with satellite priority
- ✅ **Clean system** – Single configuration point
- ✅ **Real-time monitoring** – Proxy status always visible
- ✅ **Visual feedback** – Notifications for all operations
- ✅ **Manual control** – Pick the stream source with YELLOW, refresh the proxy token with TEXT
- ✅ **Cache management** – Fix cache format with YELLOW button

## 🛠 Technical Features

### Local Proxy (127.0.0.1:4323)
- **Catalog source**: tries Geil (and its mirrors) first - the same
  kind of IPTV catalog, but with no authentication/token step needed
  at all. Falls back to Vavoo's servers (Vavoo, then Kool) only
  if Geil's whole catalog can't be loaded. Check which one is
  active via `catalog_source` in `/status`/`/health`. Same default/
  fallback order the companion Android app uses.
- **One stream address per viewing**: Enigma2's players come back to
  the proxy on every playlist refresh (about every 10 seconds while a
  channel is watched), so the proxy keeps answering with the same
  resolved address for as long as it keeps being asked, and forgets it
  45 seconds after the last request. A new address is only resolved
  when nobody is watching any more or when the plugin's player reports
  that the stream ended. (Earlier versions re-resolved every watched
  stream after 5 minutes, which interrupted playback.)
- **Channel logos (picons)**: Vavoo's catalog still names a dead logo
  host (`logo.huhu.to`); Geil gives the same pictures as a relative
  path. Both are normalized to the host that actually serves them
  (`vavoo.to/live2/logo/<n>.png`) before reaching `/channels` or any
  export, regardless of which catalog is active. The plugin's own
  channel list downloads and caches these per-channel (`/tmp/vavoo_picons`,
  same on-box cache-dir convention as the country flag icons), showing
  the real picon instead of the generic channel icon once it lands.
- Manages authentication with Vavoo servers (only needed when running
  on the Vavoo fallback)
- Automatically renews tokens every 8-9 minutes (TOKEN_ADDON_SIG = 600 seconds)
- Provides stable URLs for bouquets
- Completely eliminates 10-minute streaming blocks
- Self-monitoring with automatic restart on failure
- Connection pool management to prevent timeouts
- **Mirror Support**: Automatic fallback between Geil's own mirrors,
  and separately between Vavoo and Kool when HTTP 451 is detected
- **Grouped sources**: several catalog entries for the same channel
  (Vavoo's own `.b`/`.c`/`.s`-style suffix, Geil's `(N)` already
  normalized to match it) are shown as a single row in `/channels`
  (and so in the plugin's channel list, search, favourites, and
  exported bouquets - all of which read `/channels`), named without
  the suffix, same idea as the companion Android app's "group
  sources" option. The proxy picks one source and stays on it. When
  the plugin's player reports that the stream ended, the same source
  is retried once with a fresh address; a second failure within a
  minute moves on to the next source. In the player, **YELLOW** opens
  a "Choose Stream Source" menu to pick one yourself - each source is
  listed under its own catalog name (e.g. "SIC .b", "SIC HD .s"), the
  pick is remembered (`/etc/enigma2/vavoo_source_prefs.json`) and also
  applies to that channel in exported bouquets. This can't recover a source
  that resolved fine but is slow/buffering - pick another one for that.
- **Token Monitor**: Background thread that checks token age every 60 seconds
- **Active Stream Tracking**: Notifies proxy when streams start/end for better resource management

### EPG Integration & Satellite Priority Matching
- EPG data is generated per country and stored in `/etc/epgimport/vavoo_<country>.channels.xml`
- A master source file (`vavoo.sources.xml`) is created for EPGImport
- The player fetches EPG via the proxy redirect to GitHub raw files
- **Intelligent Channel Matching** (in priority order):
  - Local per-box cache
  - **Curated EPG channel database** (`epg-channel-db/vavoo_channels_<cc>.json`,
    fetched and cached in-memory for 24h): a pre-solved
    channel-name → EPG-feed-id mapping, generated offline per country
    by matching Vavoo's own live channel list against that country's
    own `epg_<cc>.xml` feed directly - built specifically for
    countries Rytec covers poorly (e.g. Spain, Poland, Turkey)
  - **Geil's own guide id** (its catalog's "tvg" field, present when
    the catalog source is Geil): checked directly against that
    country's own EPG feed - an exact id match, skipping fuzzy name
    matching entirely for that channel. No equivalent on the Vavoo
    catalog fallback, which has no such id to offer.
  - Live Rytec fuzzy matching, then a live feed-direct fallback
  - Every matched channel gets a synthetic, per-channel-unique service
    reference (not a shared Rytec tuple) so unrelated channels across
    different countries can never collide in Enigma2's EPG cache, even
    when they share the exact same EPG id
  - Scans user-configured satellites from Enigma2 NimManager
  - Prioritizes matches from satellites the user actually has configured
  - Falls back to Italian satellites (13°E HotBird, 5°W Eutelsat) for Italian channels
  - Priority levels: Satellite > Terrestrial > Cable > IPTV
  - **Boost multipliers**: 1.5× for user-configured satellites, 1.3× for Italian satellites

### Notification System Architecture
- **Singleton Pattern**: Single manager instance across all screens
- **Thread-safe**: Lock mechanism prevents race conditions
- **Message Queue**: Pending messages stored until UI is ready
- **Auto-cleanup**: Notifications automatically hide after timeout
- **Fallback**: Console logging when UI not available
- **Any resolution**: The bar is sized and centred from the real screen width (HD, Full HD, WQHD)

## 📋 API Endpoints
The proxy provides these endpoints:
- `/status` – Check proxy status (includes `catalog_source`: "geil" or "vavoo")
- `/channels?country=CountryName` – Get channels by country (sources of
  the same channel grouped into one row - see Grouped sources above;
  its `id` is then a synthetic `grp:<country>:<key>` handle rather
  than a single catalog id)
- `/vavoo?channel=ChannelID` – Resolve stream URLs (302 redirect). The
  answer stays the same address while it keeps being requested (see
  "One stream address per viewing" above); a `grp:...` id resolves to
  one of the group's sources and stays on it. Takes no other parameters
- `/group_sources?group=GroupID` – List a grouped channel's individual
  sources and which one is in use (read-only)
- `/stream?ref=ServiceReference` – Resolve by Enigma2 service reference (via `vavoo_sref_map.json`) and proxy the stream content directly
- `/playlist.m3u?country=CountryName&key=AccessKey` – Live, always-current M3U playlist for external players (VLC/Kodi/TiviMate); `country` and `key` are both optional (key only required if "Playlist Access Key" is set in Config)
- `/catalog` – Full channel catalog
- `/countries` – List all countries
- `/refresh_token` – Force token refresh
- `/epg/<country>.xml` – Redirect to GitHub EPG file
- `/health` – Detailed health check with token age (token is only required/reported when `catalog_source` is "vavoo" - Geil needs none)
- `/shutdown` – Gracefully stop proxy

## 🗂 File Management

### Bouquet Export
- Path: Plugin menu → Select country → GREEN button
- Creates bouquets with proxy URLs: `http://127.0.0.1:4323/vavoo?channel=CHANNEL_ID`
- Service references are matched against the curated EPG channel database and the Rytec database for EPG compatibility (see "EPG Integration & Satellite Priority Matching" above)
- EPG mapping files are automatically generated for each country
- Supports both flat bouquets and hierarchical categories

### M3U Export
- Path: Config Menu → "Generate .m3u files" (press OK)
- Downloads playlist from proxy and saves as `vavoo_[country]_playlist.m3u`
- Supports single country or all countries export

### EPG Files
- Location: `/etc/epgimport/vavoo_*.channels.xml`
- Generated locally on the box at export time (`write_epg_mapping_file()`), not by any GitHub Action
- Programme data source: `https://raw.githubusercontent.com/Belfagor2005/vavoo-player/master/epg_<country>.xml`

### Curated EPG Channel Database
- Location: `epg-channel-db/vavoo_channels_<cc>.json` in this repo, fetched by the plugin at match time and cached in-memory for 24h
- A `vavoo_channels_<cc>.review.json` file is generated alongside each one for names that need a human to resolve - never read by the running plugin
- Regenerated by `generate_epg_channel_db.py` (dev-time script, run against a live `vavoo_proxy` instance) - the GitHub Actions workflow `generate_epg_channel_db.yml` runs this weekly (plus on-demand) on a self-hosted runner and commits the result back

### Cache Files
- **EPG Cache**: `/etc/enigma2/vavoo_epg_cache.json` – Persistent cache of matched channels with Rytec IDs
  ```json
  {
    "channel_name_country": {
      "id": "rytec_id",
      "sref": "4097:0:1:1773:60E1:217C:5A0000:0:0:0:",
      "name": "channel_name",
      "country": "it",
      "matched": true,
      "timestamp": "2026-03-19 10:23:15"
    }
  }
  ```

- **Unmatched Cache**: `/etc/enigma2/vavoo_epg_unmatched_cache.json` – Stores channels that couldn't be matched
  ```json
  {
    "channel_name_country": {
      "id": "channel_name_country",
      "name": "channel_name",
      "country": "it",
      "sref": "4097:0:0:0:0:0:0:0:0:0:",
      "timestamp": "2026-03-19 10:23:15",
      "matched": false,
      "attempts": 3
    }
  }
  ```
  Features:
  - Tracks matching attempts count
  - Auto-converts old format entries
  - Persistent across plugin restarts
  - Used for future matching improvements

- **SREF Map**: `/etc/enigma2/vavoo_sref_map.json` – Maps service references to channel IDs for the proxy

- **Source Picks**: `/etc/enigma2/vavoo_source_prefs.json` – The stream source chosen with YELLOW in the player, per multi-source channel (`{"grp:<country>:<name>": "<source id>"}`). Delete it to go back to automatic selection everywhere

- **Curated Channel DB Cache** (in-memory only, not a file on disk): each country's downloaded `epg-channel-db/vavoo_channels_<cc>.json` is kept in memory for 24h per process so repeated exports/lookups don't re-download it every time (a failed download is retried after a minute) - cleared on plugin/proxy restart

## 🚨 Troubleshooting

### Quick Diagnostics
```bash
# Check proxy status
curl -s http://127.0.0.1:4323/status

# Check proxy logs
cat /tmp/vavoo_proxy.log

# Check plugin logs
cat /tmp/vavoo.log

# Check EPG cache
cat /etc/enigma2/vavoo_epg_cache.json

# Check unmatched cache
cat /etc/enigma2/vavoo_epg_unmatched_cache.json

# Check proxy health
curl -s http://127.0.0.1:4323/health
```

### Common Issues
| Problem | Solution |
|---------|----------|
| "No channels found" | Check the internet connection; press TEXT in the main menu to refresh the proxy, or restart the plugin |
| "Could not load channels - proxy not responding" | The proxy did not answer after three tries: wait for the proxy status to show OK, then open the country again |
| Bouquets don't open | Ensure proxy is running (check with curl) |
| Stream doesn't start | Check the proxy status line; on the Vavoo source press TEXT to refresh the token |
| A channel stops after a while | The player retries it by itself and then moves to another source; if it keeps happening, press YELLOW and pick another source |
| M3U export fails | Verify port 4323 is accessible |
| "No programme found" | Clear EPG cache and re-export bouquet; check country EPG file exists |
| EPG not updating | Verify EPG is enabled in config and GitHub files are accessible |
| HTTP 451 errors | Proxy automatically switches to mirror sites (Geil's mirrors, or Kool on the Vavoo fallback) |
| Streams not resolving at all | Check `catalog_source` in `/status` - if stuck on "vavoo" with no token, Geil may be unreachable from your network |
| A channel keeps stopping or buffering | Press YELLOW in the player and pick another source |
| Duplicate cache entries | Press YELLOW button in main menu to fix cache format |

### Notification Issues
| Problem | Solution |
|---------|----------|
| Notification bar cut off at the screen edge | Fixed in this version: the bar is centred on HD, Full HD and WQHD screens |
| No notifications at all | Check `/tmp/vavoo.log` ("Show Log" in Config) for errors from the notification system |

### Cache Issues
| Problem | Solution |
|---------|----------|
| Unmatched channels not saving | Check write permissions to `/etc/enigma2/` |
| Duplicate unmatched entries | Press YELLOW button or run `fix_cache_format(remove_duplicates=True)` |
| Cache file corrupted | Delete the file and restart - it will be regenerated |
| Old format entries | The plugin auto-converts them on read or use YELLOW button |

## Privacy & Anonymous Stats

Vavoo sends **anonymous** startup notifications to help improve the plugin.

**Collected (anonymous only):**
- Temporary session ID (changes on every reboot)
- Plugin version
- Event type (startup/heartbeat)
- Timestamp

**Not collected:** IP, MAC, personal data, channels, or any identifying info.

**Disable:** Config menu → "Send Anonymous Statistics" → No

[View source code](https://github.com/OwnerPlugins/vavoo/blob/main/usr/lib/enigma2/python/Plugins/Extensions/vavoo/vavoo_stats.py)

## 📝 Important Notes
- **The proxy is always on** – There is no switch for it any more; every channel list and stream goes through it
- **Proxy runs in the background** – Exported bouquets keep working after the plugin is closed (the proxy is started about 30 seconds after boot)
- **Bouquets exported by very old versions** (before the proxy existed) do not work – export the country again
- **Your source pick is remembered** – Stored in `/etc/enigma2/vavoo_source_prefs.json`; delete that file to return to automatic selection everywhere
- **Satellite priority** – The plugin reads your Enigma2 satellite configuration (east and west positions) and prefers those channels when matching EPG
- **Unmatched channels are persistent** – They survive plugin restarts and are used for future matching attempts
- **EPG cache includes matched/unmatched status** – Each entry has a `matched: true/false` flag
- Use **TEXT button** in main menu to manually refresh proxy token
- Use **YELLOW button** in the main menu to fix cache format, and in the player to choose the stream source
- Proxy status is displayed in real-time in the main interface
- For developers: `quick_notify(message, seconds)` is thread-safe and can be called from any background thread; messages sent before the UI is ready are queued

## 🤝 Credits
- **Created by**: Lululla (https://github.com/Belfagor2005)
- **Email**: ekekaz@gmail.com
- **Special thanks to**: @KiddaC for suggestions, Qu4k3 for technical support
- **Background images**: @oktus
- **Contributions**: Qu4k3, @Belfagor2005 (EPG integration), @giorbak
- **Notification System**: Based on original RaiPlay implementation
- **Satellite Priority System**: Based on user feedback and Enigma2 integration
- **Communities**: Linuxsat-support.com & Corvoboys

## 📄 License
CC BY-NC-SA 4.0  
https://creativecommons.org/licenses/by-nc-sa/4.0

**Usage of this code without proper attribution is strictly prohibited.**
**For modifications and redistribution, please maintain this credit header.**

---
*Last Modified: 2026-11-11*
