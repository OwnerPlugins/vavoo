# CLAUDE.md

Guidance for AI assistants (Claude Code) working in this repository.

## What this is

Enigma2 set-top-box plugin ("Vavoo Stream Live") that streams live TV
channels from Vavoo/Kool.to. It is **not** a standard installable Python
package — it's a filesystem tree that gets copied verbatim onto an Enigma2
receiver (a Linux-based satellite/IPTV STB running the Enigma2 middleware,
e.g. OpenATV, OpenPLi, Dreambox OS). There is no local dev server or way
to "run" it outside actual Enigma2 hardware/emulation - but `tests/` runs
the real plugin code against a faked Enigma2 (see "Tests" below).

Current version: see `__version__` in
`usr/lib/enigma2/python/Plugins/Extensions/vavoo/__init__.py` (also mirrored
in `CONTROL/control` and `installer.sh`).

License: CC BY-NC-SA 4.0 — non-commercial, attribution required.

## Repository layout

```
usr/lib/enigma2/python/Plugins/Extensions/vavoo/   # the actual plugin (deployed as-is to the box)
  __init__.py            # constants, paths, PROXY_* URLs, PLUGIN_ROOT, PY2/PY3 flags
  plugin.py              # the entry (Plugins(), main(), autostart) + startVavoo, UpdatePopup,
                          #   MainVavoo, vavoo (channel list), VavooFavourites, VavooSearch
  ui_base.py             # the screens' shared ground: cfg (every setting), keys, skins/themes,
                          #   list rows (m2list/show_list), VavooMenu, NowNextPanel, NOW_PLAYING,
                          #   PreviewWindow, show_keys, the log viewer, ACTIVE, small helpers
  ui_pick.py             # VavooPickScreen, Choose countries, Parental Control, the PIN pad (ask_pin)
  ui_record.py           # memory watch, RECORDINGS, folders / disks, Recordings list + its player
  ui_settings.py         # vavoo_config (Settings), backup / restore, licences, About, open_settings
  ui_guide.py            # VavooGuide (the EPG grid), the reminders service (REMINDERS)
  ui_player.py           # Playstream2, its channel list over the video, sleep timer, info bar
  vavoo_proxy.py         # local HTTP proxy (port 4323): auth/token handling, stream resolution,
                          #   the country guides (/epg), recordings (/file)
                          #   started as an in-process daemon thread (see the proxy-start helpers,
                          #   not a separate subprocess)
  bouquet_manager.py     # builds/exports Enigma2 bouquets (flat + hierarchical) pointing at the proxy
  channel_alias.py       # channel name normalization/aliasing for EPG matching
  vUtils.py              # grab-bag: logging, HTTP helpers, caching, proxy status/health helpers,
                          #   EPG sources (epgshare01 daily, GitHub copy), download/parse/cache,
                          #   channel -> feed-id matching (geil id, alias, cache, curated, names)
  epg_name_utils.py      # channel-name normalization/token-compatibility helpers, shared
                          #   as-is by vUtils.py (on-box) and generate_epg_channel_db.py (off-box) -
                          #   has zero Enigma2 imports so both sides can use the exact same code
  notification_system.py # singleton, thread-safe on-screen notification/toast manager
  vavoo_store.py         # the app's lists and data, no Enigma2 imports: favourites (order,
                          #   folders), hidden countries, parental control (PIN, adult words,
                          #   pause, unlock), backup/restore, initials + colour, search rules,
                          #   a pure-Python PNG writer for the initials tiles / padlock
  vavoo_record.py        # recordings, no Enigma2 imports: Recorder (ffmpeg -c copy -f mpegts
                          #   into a pipe, whole TS packets into a .ts, re-resolve and go on in
                          #   the same file, "seconds -> byte" index), the pause buffer, list /
                          #   delete recordings, the ids vavoo_proxy's /file may serve
  vavoo_theme.py         # the themes (Prism/Halo/Orbit = the Android app's Look/Geo tables):
                          #   builds every screen's skin XML for hd/fhd/wqhd - no Enigma2 imports
  make_theme_assets.py   # dev-time script: draws skin/themes/<theme>/<hd|fhd|wqhd>/*.png
                          #   (pure Python, no Pillow) from vavoo_theme.asset_specs()
  vavoo_stats.py         # anonymous opt-out startup/heartbeat telemetry (no PII)
  Console.py             # generic subprocess-output Screen used for shell commands in the UI
  update_translations.py # dev-time script: extracts strings, updates .po/.pot, compiles .mo
  xml2pot.py             # dev-time helper: pulls translatable strings out of skin XML into .pot
  check_skin_consistency.py # dev-time script: compares widget name= sets across hd/fhd/wqhd skins
  generate_epg_channel_db.py # dev-time script: matches a country's live Vavoo channel list
                          #   against its own epg_<cc>.xml feed (not Rytec) to bootstrap a
                          #   curated channel-name -> EPG-feed-id mapping
  locale/<lang>/LC_MESSAGES/vavoo.{po,mo}  # gettext translations, ~90 languages
  skin/{hd,fhd,wqhd}/*.xml   # per-resolution skin layouts (HD, FullHD, WQHD/4K) = the Classic theme
                            #   (vavoo_pick.xml: Choose countries / Parental; vavoo_pin.xml: PIN pad)
  skin/themes/<theme>/      # theme backgrounds (bg*_hd/fhd.jpg, the app's) + drawn PNGs per resolution
  skin/cowntry/*.png, skin/pics/*.png, skin/images*/*.png  # flags/backgrounds
  fonts/*.ttf               # cvfont (MavenPro-Medium = Liberation Sans) + the themes' Lexend,
                            #   Manrope, Sora, Oxanium (SIL OFL, licence texts beside them)
  keymap.xml             # the plugin's own keys (VavooPlayerActions, VavooListActions,
                          #   VavooMainActions), loaded by ui_base.py's load_keymap() -
                          #   the same on every image
  plugin.png             # plugin icon shown in Enigma2 menu

CONTROL/                 # Debian/ipkg package control files (control, postinst, postrm, preinst)
enigma2-plugin-extensions-vavoo.bb   # Yocto/OpenEmbedded bitbake recipe (alternate packaging path)
installer.sh              # curl|bash-style installer: detects OS/Python version, installs deps, deploys plugin, restarts box
update_all_plugins.py     # repo-root dev script: finds every plugin's locale dir and runs its update_translations.py
.github/workflows/         # CI (see below)
tests/                     # the tests: Enigma2 faked, the real plugin code run (see "Tests")
screen/                    # README screenshots: <theme>_<screen>.jpg = the Full HD skins drawn
                          #   with sample data (README links them as /screen/..., so the plugin
                          #   folder's identical readme.md works too); screen1-9 = old (1.61)
```

There is exactly one plugin in this repo (`vavoo`); `update_all_plugins.py`
is written generically (as if for a multi-plugin monorepo) but currently
only ever discovers this one.

## Architecture

**Plugin process (`plugin.py` + `ui_*.py`)** — runs inside Enigma2's own
Python interpreter. The `Screen` subclasses (Enigma2's UI framework, similar
in spirit to a single-activity mobile app) live in layers, each importing
only the ones below it: `ui_base` → `ui_pick` → `ui_record` →
`ui_settings` → `ui_guide` → `ui_player` → `plugin`. plugin.py has the
main menu (`MainVavoo`), channel/category browsing (`vavoo`),
`VavooFavourites`, search (`VavooSearch`), startup (`startVavoo`) and
`Plugins(**kwargs)`, the Enigma2 entry point returning `PluginDescriptor`s
for the menu, plugin-menu, and autostart hooks (Enigma2 loads
`Plugins.Extensions.vavoo.plugin`, so that stays its name). Rules:
- A module never imports a higher one at its top (Python 2 fails on
  an import cycle there): the three upward calls import inside the
  function (`vavoo_config` → `VavooFavourites` / `check_configuring`,
  `play_reminder` → `main`). A new upward need does the same.
- Imports are relative and explicit (`from .ui_base import (...)`, no
  `*`); each module has the credit header, its own `print =
  make_print("PLUGIN")` and the notification fallbacks it uses.
- Names rebound with `global` at run time (`_session`, `first`,
  `_update_check_*`, `auto_start_timer`...) live in plugin.py, which no
  module imports from at its top: a `from x import NAME` copy would
  keep the old value. Shared state elsewhere is an object changed in
  place (`cfg`, `ACTIVE`, `NOW_PLAYING`, `RECORDINGS`, `REMINDERS`,
  caches).
- Side effects at import run once, in their module: the config
  declarations, `load_keymap()`, the data migrations
  (`_move_data_out_of_plugin_folder()` in ui_base,
  `_move_parental_out_of_settings()` in ui_pick),
  `vavoo_record.set_logger(print)`.

**Themes (`vavoo_theme.py`)** — the plugin follows the companion Android
app (`pQu4k3r/vavoo_android`): its `Look` (colours, radii, fonts per
theme) and `Geo` (widget positions, in this plugin's own FHD skin
coordinates) tables are carried over and every screen's skin is built
from them for the box's resolution. Rules:
- Classic (`cfg.theme == "classic"`) is never built: builders return
  None and the screen loads its XML file as always. `ui_base.py`'s
  `load_screen_skin(kind, classic_file, ...)` returns `(text, themed)`;
  `build_theme_skin()` is all or nothing (if the list skin cannot be
  built, or a referenced picture / theme font is missing, no screen
  uses the theme) and caches per settings.
- Skins are built for `THEME_WIDTH` (2560 / 1920 / 1280, the Classic
  tiers), and a picture's declared size must equal the PNG's: sizes
  come from `asset_pixel_size()`, which `make_theme_assets.py` draws
  to. Change a size or colour in the tables → re-run
  `make_theme_assets.py` and commit the PNGs. Selection bars are exactly
  one listbox row high; a list's row height is its height shared by
  whole rows (`list_metrics()`), and `m2list` / `show_list()` use the
  same metrics (icons scaled with `ePicLoad` once each, `scaled_icon()`).
- Colours in the tables are Android `#AARRGGBB` (AA = opacity);
  `e2_color()` converts to Enigma2's inverted transparency.
- A theme skin names only widgets its screen creates: the list skin
  adds `key_menu` / `key_info` (every list screen calls
  `add_key_hint_labels()`); the time labels of Now/Next are 1 px there.
- Keys follow the app in every theme: main menu Exit / Favourites /
  Search all / Reload List; channel list Back / Add-Remove Fav / Search
  / Full Screen; Favourites Back / Remove Fav / Move (Done) / Folder; MENU opens `open_action_menu()` (`VavooMenu` in a
  theme, `ChoiceBox` in Classic) holding Settings and the Enigma2 tools
  (bouquets, EPG import, cache fix, token, log, about).
- Screens with no Classic file of their own get a built Classic-coloured
  skin instead of None: `player_list_classic()` (the player's channel
  list). The player bar (`player_bar`) is themes-only: Classic keeps
  `skinName = 'MoviePlayer'` and the top overlays, and only creates the
  bar's widgets (`PLAYER_BAR_LABELS` + logo / info_box /
  progress_track / progress) when the theme skin is used.
- Main-list counts come from `vavoo_proxy.proxy.country_counts()`
  (in-process, from `cat()`'s background thread; grouped like
  `/channels`, computed once per catalog). `cat()` notes the catalog's
  `catalog_version`; `MainVavoo._follow_catalog()` (from the 10 s
  monitor) runs `cat()` again when a new catalog came in behind the
  saved one (highlight kept). "Reload List" =
  `restart_proxy_in_background(fresh=True)` (waits for a new catalog
  from the network, see "Saved catalog" below).
- The status line is `proxy_status_text(get_proxy_status(), total)`
  (plugin.py), read in-process: "✓ Geil OK · 9818 ch", "Loading
  channels..." while it starts (booting, or listening without a
  catalog), else what is wrong. The 60 s watchdog checks the port (the
  real proof the server answers) and never restarts a proxy that is
  only booting.
- Settings (`vavoo_config`) open with `basic_rows()` (14: look, player,
  lists, countries, PIN, recordings, backup / restore, About); the last
  row, `cfg.more_settings` ("All settings (n more) ▶" / "◀ Fewer
  settings"), is `toggle_all_settings()` from `gnm3u()`. Enigma2 only
  saves / cancels the rows in its list, so `createSetup()` remembers
  every row it built (`_rows_seen`) and save / extnok / the GREEN
  caption use `_all_entries()` / `_settings_changed()` - never
  `self["config"].list` / `.isChanged()` (a change made in "All
  settings" and hidden again would be lost).
- A new install's welcome (`ui_pick.run_welcome()`, from
  `startVavoo.clsgo()` when `welcome_needed()`, then `_open_main()`):
  the look (applied at once - MainVavoo is not open yet and
  `build_theme_skin()` caches per theme), Choose countries, a PIN for
  adult channels. `cfg.welcome_done`; `existing_install()` (countries
  asked, favourites, recents, hidden countries, a PIN) marks an install
  in use as welcomed without it. `open_action_menu()` and
  `ask_new_pin()` take `on_cancel` so a flow can go on after EXIT.

**Preview window and player (`ui_base.py`'s `NOW_PLAYING`, `ui_player.py`)** — as in the app, OK on a
channel plays it in the list's preview window and OK again (or BLUE)
opens `Playstream2` full screen on the same stream. One stream at a
time, owned by `NOW_PLAYING` (`_NowPlaying`): `preview_play()` /
`player_take()` (the player carries on without restarting) /
`player_give_back()` (on close with `hand_back`, it keeps playing in
the window) / `preview_stop()` (`MainVavoo.closex()`: stop and put back
the service that played before the plugin opened). The proxy's
`stream_started()` / `stream_ended()` count travels with the stream -
never call them twice for one stream. Both play the address from
`build_stream_sref()` (the plain `/vavoo?channel=` rule below).
`PreviewWindow` retries a preview stream that ends (3 times a minute,
`report_stream_failure()` each time). Every fresh play goes to
"Recently watched" (`remember_recent()` → `vUtils.add_recent()`,
background thread, `/etc/enigma2/vavoo_recent.json`, 20 max). The
player's mini guide uses `vUtils.lookup_schedule()` /
`peek_schedule()` (same rules as `lookup_now_next()`). The player's
keys are the same in every theme and in Classic, one key per function
(no walking a bar with the arrows - that was the app's touch UI): OK
shows / hides the bar, UP/DOWN and CH± zap, GREEN favourite, YELLOW
`chooseStreamSource()`, BLUE `list_key()` (the channel list over the
video), EPG / INFO `open_guide()`, MENU the options via
`open_action_menu(..., layout="player_menu")` (`mainMenu()` and
OpenATV 7's `showMainMenu()` are overridden so MENU never opens
Enigma2's own menu), AUDIO / SUBTITLE Enigma2's own, digits,
0/RECALL, PAUSE / PLAY / PLAY-PAUSE `playpauseService()`, << >>
`seekFwd()` / `seekBack()`; LEFT / RIGHT (`key_left()` /
`key_right()`) only move behind live. The themes' bar buttons are
captions of those keys, one row: the colour keys plus "EPG Guide" and
"MENU Options" (`PLAYER_SMALL_KEYS`; AUDIO / 0 recall are not shown -
the bar looks like a receiver's - but work and are in HELP), never
selected, and the date sits under the clock; Classic's top line is `classic_help_line()` (the keys, plus
`classic_proxy_problem()` only when the proxy is not right). Change a
key → change `keymap.xml` / the screen's `player_keys()` map, the
fallback ActionMap, `_fill_bar()`'s captions and `classic_help_line()`
together. RED / EXIT / BACK go through `back()`: behind live (Pause
Live TV, below) they return to live first, else `cancel()` closes.

**Keys on every image** — images name the same key differently in
their keymap.xml (OpenATV 7: MENU = `showMenu` in `InfoBarMenuActions`,
which opened Enigma2's main menu in the player; OpenPLi: PLAY =
`unPauseService`; OpenViX: no CH± where lists look), and Enigma2 turns
`InfoBarSeek`'s pause / seek keys off for a stream it cannot seek (live:
PAUSE did nothing). So:
- The players (`Playstream2`, `VavooRecordingPlayer`) use the plugin's
  own `keymap.xml` (context `PLAYER_KEYS`, loaded once at import by
  `load_keymap()` via `keymapparser.readKeymap`, "Own keys loaded" in
  vavoo.log), mapped with `player_keys()` at `PLAYER_KEYS_PRIO` (-3),
  above Enigma2's own handlers (seek / arrow seek -1, menu and audio
  0, show/hide 0-1). Every key there takes all its events: the action
  on the press, "ignore" on release / repeat / hold - so nothing below
  ever acts on the rest of a press. Only flags m b r l (older images'
  parsers know no others). A key the screen does not want maps to a
  no-op rather than falling through to Enigma2's.
- The image-context ActionMaps stay as the fallback (one step lower,
  still above Enigma2's), with every image's names for MENU / pause.
- The list screens take the remote's direct keys the same way:
  `keymap.xml`'s `VavooListActions` (`LIST_KEYS`, `list_keys(actions)`
  at `LIST_KEYS_PRIO` -2, above their own maps and Enigma2's listbox):
  FAV `favourites`, PVR / FILE / VIDEO / LIST `recordings`, TEXT
  `search`, HELP `help`, PLAY `play`, STOP `stop` (`stop_preview()` →
  `NOW_PLAYING.preview_halt()`, which keeps the service to put back),
  REC `record` (`record_channel()`, shared with the player's REC), BACK
  `back`; the main list's EPG is `VavooMainActions` (the favourites'
  guide, `open_favourites_guide()`; OpenPLi calls EPG "info" there).
  0 as the first digit is `play_last_watched()`. Only keys whose
  release no image uses for something a list needs go in there (its
  "ignore" takes the release) - EPG does not, in the shared context.
- HELP: every screen has `show_help()` → `show_keys(session,
  help_rows())`; `help_rows()` lists each key the screen takes (dynamic:
  Favourites while moving). Change a key → `keymap.xml`, the screen's
  maps, its `help_rows()`, README's table and the captions together.
- Never put `EPGSelectActions` in one ActionMap with `ColorActions`:
  OpenATV / OpenViX have RED / YELLOW / BLUE there on the press and
  ColorActions on the release, so a colour key ran twice (the guide's
  YELLOW moved 2 h, Move in Favourites went on and off). List screens
  take INFO / EPG / CH± from `info_page_keys(actions)` (EPGSelectActions
  + ChannelSelectBaseActions, which has CH± as nextBouquet /
  prevBouquet on every image), holding only those names. Same for the
  seek contexts in the players' fallback (their LEFT / RIGHT on the
  release moved a second time).
- Enigma2 dispatches a key to the key lists by priority and stops at
  the first whose action returns non-zero (`eActionMap::keyPressed`);
  a dialog opened on the press gets the release, but ignores it (it
  never saw the press).

**Local proxy (`vavoo_proxy.py`)** — a long-running background HTTP server
started as an in-process daemon thread (`threading.Thread(target=
start_proxy)`, spawned from `run_proxy_in_background()`), monitored/restarted
by `plugin.py` (`MainVavoo`'s watchdog: a port check every 60 s), listening
on `127.0.0.1:4323`. It:
- Obtains/renews the Vavoo auth signature/token (`TOKEN_ADDON_SIG`, renewed
  every ~8-9 min) so bouquets never hit Vavoo's 10-minute anonymous block.
- Resolves `/vavoo?channel=<id>` to a real stream URL via 302 redirect.
  **Enigma2's players re-request this URL on every HLS playlist refresh
  (~every 10 s while a channel is watched)**, because the redirect is
  temporary - so the answer must stay the same address for the whole
  viewing. The resolve cache is therefore an *idle* timeout
  (`RESOLVE_IDLE_TTL`, refreshed on every hit), not an age, and
  `/vavoo` takes no parameters besides `channel`: anything put in that
  URL would be re-applied every refresh. One-off events go through
  in-process calls on `vavoo_proxy.proxy` instead -
  `report_stream_failure(channel_id)` (the player's EOF handler),
  `set_group_source()` / `get_group_sources()` (the player's source
  menu, MENU → Source; the pick is persisted in
  `/etc/enigma2/vavoo_source_prefs.json`).
- Channels with several sources are grouped into one row
  (`grp:<country>:<key>` ids); the proxy stays on one source per group
  and only moves on after repeated failure reports.
- `/channels` is `VavooProxy.channel_rows(country, grouped)` (also
  called in-process: Search all, sub-categories); `&grouped=0` is
  Group Sources off. `country_counts(grouped)` follows it.
- Serves `/channels`, `/catalog`, `/countries`, `/status`, `/health`,
  `/refresh_token`, `/group_sources`, `/epg/<country>.xml` (the
  country's guide: `_serve_epg()`, see "EPG sources" below), `/file`,
  and `/shutdown`.
- Recordings get a token of their own (`own_signature(slot)`, one slot
  per recording, renewed at `TOKEN_REFRESH_AGE` by the recorder's
  keep-alive; `drop_own_signature()` at its end): Vavoo plays one
  stream per token. `resolve_own(channel_id, slot, force)` never
  touches the shared resolve cache or the group state (the player
  keeps its address); geil needs no token. The ping itself is
  `_request_addon_sig()`, shared with `refresh_addon_sig_if_needed()`.
- `/file?id=&offset=[&follow=1]` serves only ids registered with
  `vavoo_record.register_file()` - never a path (the proxy answers the
  LAN for bouquets). `offset` is rounded down to a 188-byte packet, a
  `Range` counts from it; `follow=1` streams a file still being
  recorded until its `Recorder` ends.
- There is no "proxy disabled" mode: every channel list and stream goes
  through it. `run_proxy_in_background()` never blocks (callers poll
  `is_proxy_ready()`); `restart_proxy_in_background()` is the only
  correct way to restart it, and a stopped `VavooProxy` instance is
  never reused (`start_proxy()` creates a fresh one).
- The plugin reads the proxy's state in-process, never over HTTP:
  `vavoo_proxy.proxy_state()` = `status_of(p)` (what `/status`
  answers) + `booting` / `listening` (server set, not stopped) / `ready`
  / `catalog_version` / `refreshing`, always through the module's
  `proxy` (a restart replaces it). `vUtils.get_proxy_status()` /
  `is_proxy_ready()` wrap it (import inside the function: vavoo_proxy
  imports vUtils). `is_proxy_running()` (a port probe) is only for the
  watchdog.
- Saved catalog: every catalog that loads is kept in `CATALOG_FILE`
  (`/etc/enigma2/vavoo_catalog.json.gz`, `save_catalog()`, atomic,
  not written when its hash is the same - the flash).
  `initialize_proxy(use_saved=True)` starts with it
  (`load_saved_catalog(setting)`: format / version / the same
  `catalog_source` setting / under `CATALOG_MAX_AGE` 3 days - a box
  whose clock is not set yet takes it - / entries cleaned, at least 100)
  so the port opens at once, and `start_proxy()` then calls
  `start_catalog_refresh()` (thread "vv-catalog": `_download_catalog()`
  - which never touches the catalog in use - then `_install_catalog()`,
  else again every `CATALOG_RETRY` 15 min while the instance lives; an
  empty start does the same). `_install_catalog()` builds every index
  aside and then assigns them (a dict in use is never changed; readers
  in other threads see whole dicts) and bumps `catalog_version`.
  `restart_proxy_in_background(fresh=True)` sets `_fresh_start`, read
  once by the next `start_proxy()`: the network only.
- `prefetch(channel_id)`: the player (`Playstream2._schedule_prefetch()`,
  3 s after `zap_to()`, the next channel in the zap's direction - CH+
  +1, CH- -1, the rest +1) has the address resolved ahead, into the
  resolve cache. Geil only (Vavoo plays one stream per token: no
  resolve on the shared one); a group's first source by
  `_ordered_group_members()` (read-only: no `_group_state`); no stream
  count; one at a time (`_prefetch_lock`).
- Falls back from `vavoo.to` to `kool.to` on HTTP 451.
- It listens on every address (bouquets and `/playlist.m3u` serve other
  devices), but its controls (`LOCAL_ONLY_PATHS`: `/shutdown`,
  `/refresh_token`) answer only the box itself (`is_loopback()`, 403
  otherwise): anything on the network, even a web page with an
  `<img src>`, could stop every channel. A new control goes there.
- Bouquets and M3U exports embed proxy URLs
  (`http://127.0.0.1:4323/vavoo?channel=...`), not raw Vavoo URLs — this is
  the core trick that makes streams stable.

**Bouquets (`bouquet_manager.py`)** — writes Enigma2 bouquet files (flat or
per-category/hierarchical) that reference the proxy, matches each
channel to its country's EPG feed (`find_match()`, below) for the
EPGImport channels file, and can reorganize bouquet position
(top/bottom of channel list). The match result's `feed_id` key is the
channel's id in the country's EPG feed.

**EPG sources (`vUtils.py`, `vavoo_proxy.py`'s `_serve_epg()`)** — as
the Android app (`Epg.kt`): a country's programmes come from its daily
files at epgshare01.online (`__init__.py`'s `EPG_DAILY_URL` /
`EPG_DAILY_SOURCES`, the app's table; the Balkans = BA1 + HR1 + RS1)
first, the GitHub copy (`EPG_COPY_URL`, Belfagor2005/vavoo-player) when
they fail or are out of date. The proxy's `/epg/<cc>.xml` is the one
place that chooses, so the plugin's guide, `_get_epg_feed_index()` and
EPGImport (`update_epg_sources()`) all read the same address:
- `epg_daily_urls(cc)` gives the files, or [] (no daily files, or
  `mark_epg_daily_unusable()`: a failure 5 min, out of date 6 h);
  `country_epg_chunks(cc, urls)` yields plain XMLTV bytes - one file
  as it is, several as one guide (each channel from the first file
  that has it, with that file's programmes). The proxy answers 200 +
  `X-Vavoo-EPG: daily`, or 302 to the copy when the first `next()`
  raises (`EpgFeedStale` = out of date). Never a .gz to EPGImport.
- Several files go in two passes: all channels first (each file read
  up to its first programme), then the programmes (files opened
  again) - `_read_epg_feed_channels()` stops at the first
  `<programme>`. `_XmltvPieces` cuts the bytes into elements by
  regex, no XML tree.
- `open_url_stream()` unpacks gzip by Content-Encoding or by the first
  bytes (1f 8b: a .gz file) and exposes `headers`. A daily file with a
  `Last-Modified` over 3 days old is out of date, and so is a daily
  guide `_download_epg_guide()` finds with no programme still to end
  (`_guide_is_current()`): marked, and fetched again (the copy).

**EPG matching (`vUtils.py`'s `VavooEPGMatcher` + `channel_alias.py`)** —
finds a channel's id in its country's feed, caches matched/unmatched
channels to `/etc/enigma2/vavoo_epg_cache.json` and
`..._unmatched_cache.json`. `find_match()`'s chain (as the app): the
source catalog's own guide id (`epg_guide_id`, geil.to's "tvg") →
country-gated `channel_alias.ALIAS_MAP` → local per-box cache →
**curated channel database** (below) → the feed's own display names
(`_match_feed_name()`) → unmatched. Every id from the first three must
be one the feed has: `_feed_spelling(id, feed_ids)` gives the feed's
own spelling (exact, else upper/lower case, else the dots) or None;
with no feed index (the fetch failed) an alias / cache id counts as
it is. There is no Rytec matching and no satellite priority any more
(its srefs were thrown away for `unique_fallback_sref()`, its ids are
mostly not the feeds', and it was the heaviest part); don't bring them
back. `_resolve_guide_channel()` takes the guide id straight from the
loaded guide first (no matcher). `VavooEPGMatcher` is a per-process singleton
(`get_epg_matcher()`) called concurrently from real usage (a bouquet
export's background thread vs. a per-channel EPG-overlay daemon thread
spawned by watching TV) — its `cache`/`normalized_index`/`new_matches`
mutations are guarded by `self._cache_lock` (an `RLock`), taken by
`find_match()` and by every external mutator
(`update_complete_cache()`, `clean_cache_and_unmatched()`).

**Curated EPG channel database** — a pre-solved matching path for
names that match the feed poorly (first made for Spain, Poland,
Turkey). `epg-channel-db/vavoo_channels_<cc>.json` in this repo maps
`channel name -> EPG feed id`, generated offline by
`generate_epg_channel_db.py` (dev-time script, run against a live
`vavoo_proxy` instance — fuzzy-matches Vavoo's live channel list
against that country's own `epg_<cc>.xml` feed, using name-normalization
helpers shared with the runtime matcher via `epg_name_utils.py`, a
plain-Python module with no Enigma2 dependency so it can be imported
both on-box and off-box). `vUtils.py`'s `_load_curated_channel_db()`
downloads and caches it in-memory for 24h. A failed/empty fetch is
remembered too, but only for 60 seconds: `find_match()` asks for this on
every channel lookup, so not remembering a failure at all cost one
GitHub request per channel (or a full timeout each when GitHub is
unreachable), while a short TTL still lets a transient blip clear by the
next export. Every match (any step of the chain) gets a synthetic,
per-channel-unique service reference via
`unique_fallback_sref()` rather than a shared DVB tuple, so different
channels/countries can never collide in Enigma2's `eEPGCache` (which
indexes purely by the DVB tuple, ignoring the embedded stream URL) even
when they share the same EPG id. `.github/workflows/generate_epg_channel_db.yml`
regenerates this weekly (plus on-demand) on a self-hosted runner — required
since fetching Vavoo's live channel list needs an authenticated
`vavoo_proxy` instance, unreachable from GitHub's hosted cloud runners.

**In-plugin programme info (`vUtils.py`'s `load_epg_guide()` /
`lookup_now_next()`)** — what is on a channel now and next, read
straight from the country's guide (through the proxy's
`/epg/<cc>.xml`, "EPG sources" above), no EPGImport involved. Two users, one
lookup, so they always agree: the Now/Next panel beside the channel
list (`NowNextPanel` mixin in `ui_base.py`, used by `vavoo` and
`VavooFavourites`; setting `cfg.list_epg`) and the player's OK overlay
(`Playstream2.get_current_epg()`, a thin wrapper). Rules that come from
the real files (measured, see the comment block above
`_EPG_GUIDE_TTL`):
- The files are 2 to 60 MB with up to 110 000 programmes. Never build
  one whole (`ET.fromstring()` did, and kept it: hundreds of MB on a
  box). `open_url_stream()` reads it compressed while it downloads and
  `_parse_epg_guide()` keeps only the programmes from 3 hours before
  load time to 24 hours after it (`_EPG_GUIDE_BEHIND` /
  `_EPG_GUIDE_AHEAD`, for the guide grid; measured: pl 11 MB, fr 6 MB),
  as tuples. One `EpgGuide` per country, reused for 6 hours
  (`_EPG_GUIDE_TTL`; a box paid 10-30 s of a core every hour before),
  three countries at most (`_EPG_GUIDE_KEEP`), one download at a time
  per country.
- Heavy loops in background threads (the guide parse, the matcher's
  feed-name scan, the proxy's guide streaming) call `_Breather().tick()` every turn:
  after 50 ms of work they rest 25 ms, never on the main thread. A
  new heavy loop does the same. Every plugin thread gets a system
  name through `named(target, "vv-...")` / `vavoo_record.
  name_this_thread()` (seen in `top -H`), and `find_match()` logs any
  lookup over 1 s ("[EPG] slow match").
  `lookup_programmes()` / `peek_programmes()` give a channel's
  programmes between two times (`EpgGuide.between()`).
- Every entry carries its own UTC offset and the files mix them
  (`+0000`, `+0100`, `+0300`, `-0600`). `parse_xmltv_time()` applies
  it; `epg_clock()` shows box-local time. Ignoring the offset is only
  right for `+0000` files.
- Channel ids: exact id first, "same but for the dots" only as a
  fallback (`EpgGuide.channel_for()`), and never merge the two - the
  French file lists France 2/3/4/5 and Arte twice under ids that
  differ only in dots, with different time zones.
- Names: the feed writes accents, Vavoo's lists often do not
  (`_fold_accents()`); some titles arrive with character codes instead
  of characters (`_repair_guide_text()`).
- `preload_epg_guides(codes, go_on)`: `MainVavoo._schedule_guide_preload()`,
  once per opening, 15 s after the list is up, thread "vv-preload",
  `guide_countries()` (favourites' countries, most first, then the
  recently watched): at most 2, never one that would push another
  guide out (`_EPG_GUIDE_KEEP - 1`), never under `PRELOAD_MIN_FREE_KB`
  (200 MB available), stopped by `go_on()` when the player opens.
- `lookup_now_next()` can block (download, matcher): background
  threads only. On the GUI thread use `peek_now_next()`, which answers
  from memory or returns None. `NowNextPanel` waits for the highlight
  to stop moving, then uses one worker thread per screen that only
  ever handles the latest row.
- `_get_epg_feed_index()` (bouquet export, `find_match()`) reuses a
  loaded guide's channel list, and otherwise reads the same stream
  only up to the first `<programme>`.

**Lists and data (`vavoo_store.py`)** — the app's Repository /
Parental / Backup / Monogram / SearchText, all under `ENIGMA_PATH`
(`vUtils` calls `vavoo_store.set_paths(ENIGMA_PATH, PLUGIN_ROOT)`):
- Favourites: `vavoo_favourites.json` (`{"format", "version": 2,
  "favourites": [entry]}`), the list order = the user's order, new
  ones at the end, `"folder"` on the entry (no empty folders). A
  favourite is its address (`/vavoo?channel=<id>`);
  `repair_favourites()` re-finds one by name when a country's list
  loads; `reorder_favourites()` keeps the places of the favourites it
  is given (a folder's move swaps only that folder's channels). The
  plugin folder is deleted by every update (installer.sh,
  CONTROL/preinst): never keep user data there - `migrate_old_files()`
  (and both installers) move the old `vavoo_favourites.json` /
  `Favorite.txt` (now `vavoo_bouquet_list.txt`) out once; the old dict
  format is read as it is.
- Parental control: `vavoo_parental.json` (salted SHA-256 PIN, locked
  countries, `adult` / `settings` options, the wrong-PIN pause). Only
  `ui_pick.py`'s `ask_pin()` / `_require_parental_pin(...,
  channel_name=)` ask for it (the `VavooPin` pad); once entered all is
  open for 15 minutes (`is_unlocked()`, `/proc/uptime`) or until
  `MainVavoo.closex()` calls `relock()`. Adult = `ADULT_RE` on the
  name or category. Never in a backup, never touched by a restore.
- Backup: `VavooStream-backup-*.json` (`"format": "vavoo_e2_backup"`):
  `ui_settings.py`'s `BACKUP_SETTINGS` plus the lists; restore replaces.
- Factory reset (main list MENU → `MainVavoo.factory_reset()` →
  `ui_settings.ask_factory_reset()`): refused while a recording runs,
  the PIN first (`ask_pin()`: the reset removes it), Yes / No (No by
  default); then `factory_reset()`: thread "vv-reset"
  `factory_reset_files()` - `vavoo_store.factory_reset()` (every name
  in `RESET_FILES` + the old plugin-folder files, `relock()`), all
  Vavoo bouquets under `export_lock`, the logo folders (only ones
  named `.vavoo_logos` / `PICON_CACHE_DIR`), the tiles, pause
  leftovers, `release_guides()`, `forget_epg_matches()` - and on the
  GUI thread `reset_settings()` (each `cfg` element to its default but
  `RESET_KEEP_SETTINGS`: the statistics choice), the skin / icon
  caches, `restart_proxy_in_background(fresh=True)`; `MainVavoo` closes
  and `main()` opens again: the welcome. Kept: recordings, backups,
  M3U exports, logs. A new data file of the plugin goes into
  `RESET_FILES` (`test_audit.py` checks).
- `tile_path()` / `lock_path()` draw small PNGs into `/tmp/vavoo_tiles`
  at run time (no Pillow on a box), so they are not theme assets.

The settings-wide list screens (Choose countries, Parental Control)
are `VavooPickScreen`s: theme `pick` builder ("big" list metrics) or
`vavoo_pick.xml`; the PIN pad is the `pin` builder / `vavoo_pin.xml`.
`show_list()` takes `value=` (right-end text), `dim=` and
`value_icon=` (padlock); channel rows in a theme draw the initials
tile unless `cfg.logos` is on and a logo is cached. A country's
`vavoo` screen shows category rows first (`cfg.subcategories`, the
proxy's `channel_rows()` `category`); a category opens a new `vavoo`
with `category=` and the country's `channels=` (no second request).
`VavooSearch` closes with `(name, url, country, results, index)` -
callers use `play_search_result()`.

**Programme guide and reminders (`ui_guide.py`'s `VavooGuide`,
`_ReminderService`)** — the app's EpgGuideActivity: opened with INFO /
EPG in `vavoo` / `VavooFavourites` (closes with `("watch", index)`)
and from the player's options (`over_player=True`, `on_zap`). The grid
is two `GuideList` MultiContent lists (ruler, rows) whose entries the
screen computes (boxes with `backcolor`, `floor_half_hour()` window
rules of `EpgGrid`, 3 h across, `GUIDE_BACK` = 3 h, up to the guide's
end); only visible rows are looked up (peek, then one worker thread).
Skins: `vavoo_theme.guide_screen()` / `guide_classic()` (no XML),
`guide_metrics()`, `guide_colors()`, `e2_int()`. Reminders are
`vavoo_store` timers of kind "remind" (`vavoo_timers.json`; the
recordings' are kind "record", below); `REMINDERS` is started at session start
(`autostart()`) and by `MainVavoo`, ticks every 15 s, takes due ones
(`due_timers()`) and asks with `Tools.Notifications.
AddNotificationWithCallback`; "watch it" goes through `ACTIVE`
(player → `play_channel()`, main → `_open_channel()`, else the plugin
opens with `ACTIVE["pending"]`). The guide's RED (and REC) records the
highlighted programme - again: cancel / stop - its caption following
it (`_update_record_key()`, from `draw()`); EXIT / BACK close. OK on a
programme to come offers Remind me / Record / Watch; MENU is the app's key menu
(Now, `_programme_actions()` while the programme is not over,
Settings when not over the player). A locked row has no programmes,
so no actions.

**Recordings and Pause Live TV (`vavoo_record.py`, `ui_record.py`'s
`RECORDINGS`, `VavooRecordings`, `VavooRecordingPlayer`, `ui_player.py`'s
`Playstream2`)** — the app's Recorder / RecordingService /
RecordingsActivity / RecordingPlayerActivity / timeshift. Enigma2
records and timeshifts only DVB, so the plugin does it itself:
- `vavoo_record.Recorder(source, path, ...)`: a thread runs `ffmpeg
  -nostdin -i <address> -map ... -c copy -f mpegts pipe:1` and writes
  whole TS packets into the file (no re-encoding). `input_args()`
  picks a master playlist's best variant (only that one downloads;
  separate audio renditions: the master with `-map 0:p:<n>:v?/a?`).
  An ffmpeg that ends, or sends nothing for `STALL_SECONDS`, is
  restarted with `source(force=True)` (a fresh address) into the same
  file; the app's rule: 6 failures in a row and it gives up
  (`failure`). It stops at `stop_at`, `max_seconds` or under
  `STOP_FREE`. The index (`offset_for()` / `time_at()`) comes from the
  first video PES time stamp of each block written, one entry a
  second, continued across restarts and the PTS wrap; offsets are
  packet boundaries. Recordings keep `<file>.ts.vavoo.json` (atomic)
  and Enigma2's `.meta`; `list_recordings()` reads the folder (a
  record whose `.ts` is gone is deleted), `delete_recording()` takes
  the companions too. No Enigma2 imports.
- `RECORDINGS` (`_Recordings`) starts one per channel at most
  (`recording_of(url)`), with its own token (`resolve_own()`), into
  `recordings_folder()` (`cfg.record_path`, "" = Enigma2's
  `config.usage.default_path`), only with `ffmpeg` and
  `vavoo_record.MIN_FREE`, and only on a mounted disk
  (`usable_folder()` → `vavoo_record.on_disk()`: never the root file
  system - the internal flash, where a `/media/hdd` with no disk is a
  plain folder - nor tmpfs; the pause buffer too); the recorder's thread waits for the proxy
  (`wait_for_proxy()`: a box woken for a recording). They run whatever
  the plugin does; Restore refuses while one runs.
- Timers of kind "record" go off in `_ReminderService.tick()` at
  `alarm_time()` (start - 2 min), in standby too, until stop + 2 min;
  `get_next_wakeup()` returns the next one minus `WAKE_BEFORE` (Enigma2
  wakes the box from deep standby).
- Pause Live TV (`cfg.timeshift`): `Playstream2` overrides
  InfoBarSeek's `pauseService` / `unPauseService` /
  `playpauseService` / `seekFwd` / `seekBack`. States in
  `_shift_state`: None (live), "paused" (live paused, a `Recorder` of
  the plain `/vavoo?channel=` address - the shared token - into
  `pause_folder()`), "behind" / "behind_paused" (the buffer played via
  `/file?...&follow=1` with `file_stream_sref()`, the same service
  type as live). Moves (LEFT/RIGHT 10 s, << >> 30 s) change
  `_shift_pos` at once and reopen after 0.8 s (`_shift_seek`).
  `_shift_end()` (BACK, zap, close, the buffer's EOF) discards the
  buffer and replays `self.sref`; the proxy's stream count never
  changes for it (the buffer is not a stream of the player's). A new
  service sets `seekstate` back to play (`_seek_state_play()`).
  `pause_folder()`: Enigma2's timeshift folder, the recordings folder,
  else the local disk under `/media` with the most room
  (`media_mounts()`; both Enigma2 folders default to `/media/hdd`, a
  USB stick is `/media/usb`) - never a network share;
  `clean_pause_leftovers()` looks in the same places. The disks come
  from `/proc/mounts` (`vavoo_record.mount_points()`), never
  `listdir` + `os.path.ismount` (False for a link: an autofs
  `/media/usb`); network shares are told by their file system
  (`vavoo_record.NETWORK_FS`). No buffer (no
  disk / ffmpeg / start): `_shift_why` ("disk", "ffmpeg", "start",
  "stopped" - `SHIFT_WHY` texts) is said after "Paused" (bar or a
  message), because PLAY then resumes the live stream itself (after
  a longer pause, live). A buffer that stops while paused is kept
  when it holds 2 s or more (PLAY plays it, its EOF goes live), else
  deleted with "stopped". The start of the buffer plays from byte 0
  (its tables come before the index's first picture). Each step logs
  a `[Pause] ...` line.
- `VavooRecordings` (a `VavooPickScreen`, Settings → Recordings and the
  main list's `REMINDERS_ROW` row "Recordings (n)") lists timers then
  recordings; a recording of a locked channel needs the PIN
  (`recording_needs_pin()`). `VavooRecordingPlayer` plays a finished
  file directly (`eServiceReference(int(cfg.services.value), 0,
  path)`, Enigma2's own seeking) and one still recording through
  `/file` like the pause buffer; it lets go of a preview stream
  (`NOW_PLAYING.release_preview()`) and puts back only a non-plugin
  service when it closes.
- A FAT32 disk cannot hold a 4 GB file: `Recorder(max_bytes=
  vavoo_record.file_size_limit(folder))` stops a little before
  (`FAILURE_FAT`). A failed write is the disk, not the stream: `_pump()`
  raises `_DiskError` and the recorder stops at once (no new ffmpeg /
  address) with `FAILURE_SPACE` (ENOSPC), `FAILURE_FAT` (EFBIG) or
  `FAILURE_DISK` (EIO, read-only, a USB disk pulled out - `free_bytes()`
  then climbs to the empty mount folder on the flash, so the space
  check alone never notices). Records are read through
  `_clean_record()` (numbers as numbers, texts as texts, the file name
  for what is wrong) and written through `_as_texts()` (Python 2: UTF-8
  bytes beside unicode broke `json.dumps`). The logos go to a flash disk
  when there is one: `main()` runs `vUtils.set_picon_cache_dir(
  ui_record.logo_folder())` - the recordings' disk, else a
  `media_mounts()` one, that is local (not `NETWORK_FS`), on a disk,
  non-rotational (`vavoo_record.non_rotational()`: `/sys/block/<disk>/
  queue/rotational` is 0; unknown = no), writable, with `LOGO_MIN_FREE`
  200 MB: `<disk>/.vavoo_logos`, `PICON_CACHE_MAX_DISK` 64 MB. Never a
  hard disk (waking it holds the list while rows draw logos on the GUI
  thread); else `/tmp/vavoo_picons` (RAM) trimmed to 8 MB. Leftover
  pause buffers are deleted (`clean_pause_leftovers()`) each time
  `main()` runs; the guide's load line carries `memory_note()`.
- `MEMORY_WATCH` (`_MemoryWatch`, ticked by `_ReminderService.tick()`,
  so it runs while the plugin is closed too) reads `/proc/meminfo` once
  a minute and logs "[MEM] " + `memory_note()` every 30 minutes. Below
  `MEMORY_LOW_KB` (100 MB available), at most every 10 minutes, it
  appends `vUtils.memory_report()` (memory, Shmem, Slab, the top 8
  processes by RSS from `/proc/<pid>/status`) to
  `/etc/enigma2/vavoo_memory.log` (survives the reboot an OOM ends in;
  kept to `MEMORY_LOG_MAX` 64 KB, whole lines) and releases the
  plugin's own memory: `vUtils.release_guides(keep=<the player's
  country>)`, `_icon_cache`, the logo cache down to 4 MB (only while
  it is in /tmp: `vUtils.picon_cache_in_ram()`).
- Logs: ffmpeg's to `/tmp/vavoo_record.log`, the rest to `vavoo.log`.
  The bar's glyphs are ❚❚ and ◀◀ (⏸ / ⏪ are missing from the fonts
  and from many boxes' fallback font).

**Notifications (`notification_system.py`)** — singleton
`HybridNotificationManager`, thread-safe (lock-protected), with a message
queue for messages sent before the UI is ready. `init_notification_system(session)`
must be called exactly once (from `MainVavoo`). Use `quick_notify(message, seconds)`
from anywhere, including background threads. `set_notify_skin()` (called
by `MainVavoo` via `set_notification_theme()`) gives it the theme's bar;
the window is rebuilt on the next `initialize()` when that changes.

**Stats (`vavoo_stats.py`)** — opt-out, anonymous-only startup/heartbeat
ping (session id + version + event type + timestamp, no PII). Toggle: config
menu → "Send Anonymous Statistics".

Runtime state/cache files live under `/etc/enigma2/` and `/etc/epgimport/`
on the box, not in this repo. Logs: `/tmp/vavoo.log` (plugin),
`/tmp/vavoo_proxy.log` (proxy). See README.md "Troubleshooting" for the full
list of cache/log file paths and their JSON schemas.

## Python 2/3 compatibility

Enigma2 images in the wild run either Python 2.7 or Python 3.x, so plugin
code (not the dev-only scripts) must keep working on both:
- `from __future__ import absolute_import, print_function` at the top of
  modules that need it.
- Guarded imports for stdlib moves, e.g.
  `try: from urllib.request import Request, urlopen \n except ImportError: from urllib2 import Request, urlopen`.
- `PY2`/`PY3` flags derived from `sys.version_info` (see `__init__.py`),
  used to branch on string/bytes handling.
- Optional third-party imports (`requests`, `HTTPAdapter`, `urllib3.util.retry.Retry`)
  are wrapped in `try/except` and checked for `None` before use, since not
  every box image has every package installed.
- Prefer `six`-free patterns already used in the codebase (manual
  try/except import shims) over adding new dependencies — `python3-six` is
  a declared dependency but used sparingly.

When editing plugin code, match this style: don't assume Python 3 only,
and don't introduce f-strings or other Python-3-only syntax into files that
currently avoid them (check the surrounding file for `.format(...)` vs
f-strings before choosing).

Python 2 traps found by running the plugin on a real 2.7 (each made a
screen crash or a lookup fail there, never on Python 3):
- `str.rjust/ljust/center(n, u"x")`: a unicode fill on a str is a
  TypeError - pad text (`row_number()`), not `str(n)`.
- A skin given to Enigma2 must be `str` (UTF-8 bytes) on Python 2: its
  parser (cElementTree) fails on unicode with a non-ASCII character
  (`read_classic_skin()` encodes; `vavoo_theme._esc()` keeps the built
  ones `str`).
- A plain literal with a non-ASCII character (`'ñ'`, `'→'`) is bytes on
  Python 2; mixed with unicode (`.replace()`, `in`, `.format()`) it
  raises. Use `u''` where the other side is text (vUtils' `ensure_str()`
  returns unicode on Python 2) - `decodeHtml()` failed on every name.
  The country / category separators (`GROUP_NAME_SEPARATORS`, "➾")
  are such literals: loop over `group_separators(text)` (or
  `literals_for(text, "➾", ...)`, both in `__init__.py`), which gives
  them in the text's own type - looping over the tuple made every
  catalog group and every `get_country_code()` call fail.
- Values from JSON files are unicode on Python 2, from `_()` and
  `to_string()` UTF-8 bytes: convert at the edge (`to_text()` in,
  `to_string()` out to widgets). A short ASCII value from a file that
  goes into byte-string text (a log line with "✓") is made a plain
  `str()` (`load_saved_catalog()`'s source).
- `vUtils.log()` builds its line as unicode (`u"[{0}] ..."`) and
  writes it as UTF-8 bytes on Python 2: a byte-string template with a
  non-ASCII message raised UnicodeEncodeError out of every module's
  `print()` - on images that keep Python's ASCII default codec the
  proxy stopped at its own "[✓] Ready" (`tests/test_log.py`,
  `tests/test_proxy_start.py` guard it).

## Enigma2-specific conventions

- `onLayoutFinish` (and `onContentChanged`) entries must be bound
  methods (`self.x`): OpenATV and OpenPLi `exec()` any other entry in
  `Screen.createGUIScreen`, so a lambda / function / partial there
  crashes the screen as it opens ("exec() arg 1 must be a string,
  bytes or code object" - the Recordings, Choose countries and Parental
  Control crash). `onExecBegin` / `onClose` / timers take any callable.
- A `Screen` is a `dict`, and `Screen.doClose()` / `deleteGUIScreen()`
  call `self.items()`: no attribute of a screen may be named like a
  dict method (`items`, `keys`, `values`, `get`, `update`, `pop`,
  `clear`, `copy`...) - `self.items = [...]` in Recordings made every
  EXIT a "'list' object is not callable" crash on OpenATV 8.1.
  `test_audit.py` scans for it; `harness.make()` / `enigma2_close()`
  refuse it.
- `Screen.doClose()` ends with `self.__dict__.clear()`: every attribute
  of a closed screen is gone. So (ui_base's `CLOSED_UNTIL_OPEN`) a
  screen with work that comes back later - a thread, a
  `reactor.callFromThread()` / `callLater()` - has `_closed = True` as
  a CLASS attribute (mixins too) and sets `self._closed = False` first
  thing in `__init__`; `onClose` sets it True. That work reads
  `self._closed` before anything else of the screen (never
  `getattr(self, "_closed", False)` - False is wrong after the close)
  and keeps what it needs in locals. In a thread a miss was an error in
  the log ("'vavoo' object has no attribute '_closed'", the logo
  download); on the GUI thread one can take Enigma2 down.
  `test_closed.py` checks the class attribute on every class that uses
  `_closed`; `test_every_key.py` closes every screen as Enigma2 does
  (fresh and after each key) and runs what it left behind.
- Every `<widget name="X">` of a screen's skin must be a component the
  screen created in `__init__` (else SkinError on open), and every
  `<widget source="X">` must be `session.*` / `global.*` or one of its
  own; a component the skin does not name is harmless.
- Anything read from a file under `/etc/enigma2` (or a recording's
  record) may be broken or hand-edited: the loaders in `vavoo_store` /
  `vavoo_record` clean what they read (types checked, a bad entry
  dropped, a bad number replaced - `_clean_timer()`, `_number()`,
  `_clean_record()`), so no screen that shows them can fail on it.
- UI code imports from Enigma2 framework packages that only exist on real
  hardware/emulation (`enigma`, `Components.*`, `Screens.*` is implied via
  `Screen`, `Tools.Directories`, `twisted.internet.reactor`). These cannot
  be imported on a normal dev machine as they are: `tests/e2stub.py`
  fakes every one of them (any module / class / constant made up on
  demand), so the tests run the real plugin code. Static review (read the
  code, run linters) is still needed for what a fake cannot show (the
  look on a real box, real streams, the image's own behaviour).
- Translatable strings use gettext `_()`, domain `PluginLanguageDomain =
  "vavoo"`, path `Extensions/vavoo/locale`. New user-facing strings should
  be wrapped in `_()`.
- Config options are declared via `Components.config` (`ConfigSelection`,
  `ConfigYesNo`, `ConfigSubsection`, etc.) — follow the existing pattern in
  `ui_base.py` (`cfg`) / `vavoo_config` rather than inventing a separate config
  mechanism.
- Skins are resolution-specific XML under `skin/{hd,fhd,wqhd}/`. If you
  change a screen's layout/widgets in `plugin.py` / `ui_*.py`, check whether the
  corresponding skin XML(s) need matching updates across all three
  resolutions.
- `defaultListScreen.xml` (and its `_cvs` DreamOS twin) is one skin
  shared by three screens: `MainVavoo`, `vavoo` and `VavooFavourites`.
  A `<widget name="...">` added to it must be created by all three,
  used or not (see `add_epg_panel_labels()` / `add_key_hint_labels()`;
  the theme list skin follows the same rule): a named widget the
  screen does not own is a skin error on current images and a crash on
  older ones. Positions are in the skin's own coordinates, measured on
  the background images (`skin/images/` for HD, `skin/images_new/` for
  Full HD, which WQHD scales by 4/3) - a user's screenshot may show
  the GUI scaled into the TV's safe area, so its pixels are not skin
  coordinates.

## Translations

- Source of truth for translatable strings: Python `_()` calls in
  `plugin.py`, `ui_*.py` (and other modules) plus strings extracted from skin XML.
- `update_translations.py` (in the plugin dir) is the per-plugin updater:
  extracts strings, updates `locale/<lang>/LC_MESSAGES/vavoo.po` and the
  master `.pot`, auto-translates missing entries (with an on-disk cache),
  and compiles `.mo` files via `msgfmt`.
- `update_all_plugins.py` at the repo root is a generic wrapper that
  discovers every plugin with a `locale/` dir and runs its
  `update_translations.py` — currently only finds this one plugin.
- `xml2pot.py` pulls strings specifically out of skin XML files.
- CI (`update_translations.yml`) runs `update_translations.py` on every
  push to `main` and auto-commits regenerated `locale/` files. **Don't
  hand-edit `.po`/`.mo` files** for strings that CI will regenerate; edit
  the source string in the `.py`/`.xml` file instead and let CI (or a local
  run of `update_translations.py`) regenerate translations.
- `translation_cache.json` is a dev-tooling cache used by
  `update_translations.py`'s auto-translate step, not read by the
  runtime plugin.

## CI / linting (`.github/workflows/`)

Filenames don't always match their content — check behavior, not just the name:
- `pylint.yml` ("Python package") — actually runs **flake8** (`E9,F63,F7,F82`
  syntax-error gate, then a non-blocking full lint) across Python
  3.10–3.14, on push/PR to `main`.
- `flake8.yml` ("PEP8 Aggressive Check and Fix") — **auto-formats**: converts
  tabs to spaces, runs `autopep8 --aggressive --aggressive` repo-wide, and
  **commits and pushes the result directly to `main`** on every push. Be
  aware CI itself can reformat your code after merge.
- `update_translations.yml` — regenerates locale files on push to `main`
  (see above).
- `autotag.yml` — watches `__init__.py` for changes; when
  `__version__` changes, tags `v<version>` and creates a GitHub Release
  with an auto-generated changelog from commit messages.
- `skin_consistency.yml` — runs `check_skin_consistency.py` on push/PR,
  failing the build if a widget's `name=` is missing from one
  resolution's skin XML but present in another.
- `tests.yml` — runs `tests/run_tests.py` on push to `develop` / `main`
  and on PRs: Python 3.10 and 3.13 (with ffmpeg) and Python 2.7 (the
  `python:2.7` container, the Python 2 list).

## Tests (`tests/`)

Every test is a plain script run in its own process (exit 1 when a
check fails): `python3 tests/run_tests.py` (all, about 2.5 min;
`--quick` without the ffmpeg ones), `python2.7 tests/run_tests.py` (the
`PYTHON2` list in it), or one file (`python3 tests/test_guide.py`).
Needs `six` and `requests`; the recording tests need `ffmpeg` /
`ffprobe` (skipped without them).
- `e2env.py`: the plugin package on `sys.path`, Enigma2 faked
  (`e2stub.py`), a throw-away data folder (`vavoo_store.set_paths`),
  the anonymous statistics off (`STATS_DISABLE_FILE` pointed at a file
  that exists - building `MainVavoo` would send the real ping), and
  `load_plugin()`, which returns a **view** of the screen modules:
  `plugin.X` finds X in plugin.py or a `ui_*.py`, `plugin.X = fake`
  replaces it in every one of them that has it (`patch()`). Tests never
  `import vavoo.plugin` themselves, so moving a function between those
  files breaks no test. Source-text checks use `plugin_source()` /
  `source_of()`.
- `harness.py` (most screen tests): fake `Label` / `ActionMap` /
  `eTimer` / `MultiContentEntry*` put into Enigma2's faked modules before
  the import, fake lists, `make(cls, ...)` (a screen built by its real
  `__init__`, widgets in a dict, Enigma2's `onLayoutFinish` rule
  checked), `run_layout()`, `Session` (records what opens), `MENUS`,
  `NOTES`, `check()` / `finish()`. `enigma2_close(screen)` closes as
  Enigma2's `doClose()` does (the `onClose` entries, the dict-name
  check, `__dict__` cleared - a missing attribute then raises, not the
  fake's made-up value); `own_close()` is the screen's own close /
  closex; `Pending().hold()` keeps the screen modules' reactor calls
  and threads to `run()` later.
- `test_every_key.py`: every action of every screen (Classic and a
  theme, lists filled and empty), every menu entry and every dialog's
  answers, from a fresh screen each time; on Python 2 also "widgets only
  get bytes". Then every screen closed as on the box (fresh, and after
  each key) and what it left running run against the closed screen. A
  new screen goes into its `SCREENS`.
- `test_keys_lib.py` simulates Enigma2's key dispatch with the images'
  own keymaps (`data/keymaps/`, GPL, copies - see its README).
- `fakehls.py` serves a fake live HLS channel (segments made once with
  ffmpeg in the temp folder) for the recording / pause tests.
- Two checks need the real fr / pl guides (14 MB, not committed):
  `tests/epgdl/` or `$VAVOO_EPG_SAMPLES`; without them they are skipped.
- The harness keeps tests away from the real world: no real proxy from
  the screens (`run_proxy_in_background` / `restart_proxy_in_background`
  replaced in the screen modules and bouquet_manager; the proxy's own
  tests start it themselves - `test_proxy_start.py`, on a free port),
  no write to the plugin's skin (`add_skin_back` replaced;
  `REAL_ADD_SKIN_BACK` for `test_audit`), the saved catalog in the
  temp folder. `run_tests.py` fails when the tests leave any file of
  the checkout changed. Tests end with `e2env.exit_now()` (no Python
  shutdown: daemon threads writing to stdout made it crash now and
  then).
- A change in behaviour → change or add the test that covers it, and run
  the whole suite on both Pythons before committing.

There's no `requirements.txt`, `pyproject.toml`, or lint config file
(ruff/flake8 run with defaults) — don't add one speculatively.

**Practical implication for version bumps:** if you change
`__version__` in `__init__.py`, that alone triggers a tag + GitHub Release
on merge to `main`. Also update the version badge in `README.md`,
`Version:` in `CONTROL/control`, `version=` in `installer.sh`, and
`PV`/`PKGV`/`VER` in `enigma2-plugin-extensions-vavoo.bb` to keep them
in sync (they are not auto-synced) — the `.bb` recipe in particular
stayed at a placeholder `1.0` for a long time before this was noticed.

## Packaging / distribution paths

Three independent ways this plugin reaches a box — keep them consistent
when changing paths, dependencies, or version:
1. **ipkg/opkg package** — `CONTROL/control` (declares
   `python3-requests`, `python3-six` deps) + `CONTROL/postinst` /
   `preinst` / `postrm` shell scripts.
2. **Yocto/OpenEmbedded recipe** — `enigma2-plugin-extensions-vavoo.bb`,
   pulls from `git://github.com/OwnerPlugins/vavoo.git` branch `main`,
   depends on `ffmpeg gstplayer exteplayer3
   enigma2-plugin-systemplugins-serviceapp python3-requests python3-six`.
3. **Self-installer** — `installer.sh`, a curl/wget-friendly script users
   run directly on the box: detects OS flavor (DreamOS/OE/Debian) and
   Python 2 vs 3, installs `wget`/`requests`/`six` (and OE-only deps),
   downloads the `main` branch tarball of `OwnerPlugins/vavoo` from
   GitHub, and copies `usr/` into place, then prompts a reboot.

Updates come from `OwnerPlugins/vavoo` too: `__init__.py`'s
`UPDATE_HOST` → `INSTALLER_URL` (the plugin's version check reads
`version=` from that installer.sh). `HOST_MAIN` / `HOST_GIT` (still
Belfagor2005) stay for the EPG feeds, `data.json` and the curated
channel database.

All three assume the plugin always lives at
`usr/lib/enigma2/python/Plugins/Extensions/vavoo/` (or the `lib64`
equivalent) — don't restructure that path without updating all three.

## Making changes

- This is a single-branch-per-fork style repo (upstream:
  `Belfagor2005/vavoo`); work on the assigned feature branch and push there.
- Run `tests/run_tests.py` (Python 3 and 2.7) before committing. Beyond
  the tests, prioritize: (a) not breaking Python 2/3 import
  compatibility, (b) keeping the Screens and their skin XML in
  sync, (c) running `ruff check .` /
  `flake8 --select=E9,F63,F7,F82` mentally or via the CLI (Python itself is
  available in this environment even though `enigma`/`Components.*` are
  not) to catch syntax errors, undefined names, and obvious bugs before
  committing.
- `python -m py_compile <file>` is a cheap sanity check for syntax errors
  in files you can't otherwise import (anything pulling in `enigma`/
  `Components.*`/`Screens.*`).
- Don't hand-edit generated files: `locale/**/*.po`/`.mo` (regenerated by
  translation tooling/CI) and `translation_cache.json` (runtime cache).
- Keep README.md's version badge, feature list, and API endpoint table in
  sync with real behavior when you change proxy endpoints, config options,
  or cache file formats — it's the primary user-facing documentation and
  is fairly detailed/current, so treat drift as a bug.
