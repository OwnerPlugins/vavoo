# CLAUDE.md

Guidance for AI assistants (Claude Code) working in this repository.

## What this is

Enigma2 set-top-box plugin ("Vavoo Stream Live") that streams live TV
channels from Vavoo/Kool.to. It is **not** a standard installable Python
package — it's a filesystem tree that gets copied verbatim onto an Enigma2
receiver (a Linux-based satellite/IPTV STB running the Enigma2 middleware,
e.g. OpenATV, OpenPLi, Dreambox OS). There is no local dev server, test
suite, or way to "run" this repo outside actual Enigma2 hardware/emulation.

Current version: see `__version__` in
`usr/lib/enigma2/python/Plugins/Extensions/vavoo/__init__.py` (also mirrored
in `CONTROL/control` and `installer.sh`).

License: CC BY-NC-SA 4.0 — non-commercial, attribution required.

## Repository layout

```
usr/lib/enigma2/python/Plugins/Extensions/vavoo/   # the actual plugin (deployed as-is to the box)
  __init__.py            # constants, paths, PROXY_* URLs, PLUGIN_ROOT, PY2/PY3 flags
  plugin.py              # ~5000 lines: all Enigma2 Screens (UI), PluginDescriptor, autostart, main()
  vavoo_proxy.py         # local HTTP proxy (127.0.0.1:4323): auth/token handling, stream resolution, EPG redirects
                          #   started as an in-process daemon thread (see plugin.py's proxy-start helpers,
                          #   not a separate subprocess)
  bouquet_manager.py     # builds/exports Enigma2 bouquets (flat + hierarchical) pointing at the proxy
  channel_alias.py       # channel name normalization/aliasing for EPG matching
  vUtils.py              # grab-bag: logging, HTTP helpers, caching, proxy status/health helpers,
                          #   EPG download/parse/cache + Rytec/satellite-priority channel matching
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
  plugin.png             # plugin icon shown in Enigma2 menu

CONTROL/                 # Debian/ipkg package control files (control, postinst, postrm, preinst)
enigma2-plugin-extensions-vavoo.bb   # Yocto/OpenEmbedded bitbake recipe (alternate packaging path)
installer.sh              # curl|bash-style installer: detects OS/Python version, installs deps, deploys plugin, restarts box
update_all_plugins.py     # repo-root dev script: finds every plugin's locale dir and runs its update_translations.py
.github/workflows/         # CI (see below)
screen/                    # README screenshots
```

There is exactly one plugin in this repo (`vavoo`); `update_all_plugins.py`
is written generically (as if for a multi-plugin monorepo) but currently
only ever discovers this one.

## Architecture

**Plugin process (`plugin.py`)** — runs inside Enigma2's own Python
interpreter. Defines `Screen` subclasses (Enigma2's UI framework, similar in
spirit to a single-activity mobile app) for the main menu (`MainVavoo`),
config (`vavoo_config`), channel/category browsing (`vavoo`), search
(`VavooSearch`), player overlay (`Playstream2`), and startup (`startVavoo`).
`Plugins(**kwargs)` at the bottom is the Enigma2 entry point returning
`PluginDescriptor`s for the menu, plugin-menu, and autostart hooks.

**Themes (`vavoo_theme.py`)** — the plugin follows the companion Android
app (`pQu4k3r/vavoo_android`): its `Look` (colours, radii, fonts per
theme) and `Geo` (widget positions, in this plugin's own FHD skin
coordinates) tables are carried over and every screen's skin is built
from them for the box's resolution. Rules:
- Classic (`cfg.theme == "classic"`) is never built: builders return
  None and the screen loads its XML file as always. `plugin.py`'s
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
  `/channels`, computed once per catalog). "Reload List" =
  `restart_proxy_in_background()` (the catalog is only loaded at start).

**Preview window and player (`plugin.py`)** — as in the app, OK on a
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
`peek_schedule()` (same rules as `lookup_now_next()`); its keys are the
app's (OK bar → list, GREEN fav, YELLOW/BLUE CH∓, digits, 0/RECALL,
MENU options via `open_action_menu(..., layout="player_menu")`;
LEFT / RIGHT highlight the bar's buttons in `PLAYER_BAR_BUTTONS` order
(`sel_<button>` widgets, themes only) and OK presses the highlighted
one; `hide_help_overlay()` clears the highlight;
`mainMenu()` is overridden so MENU never opens Enigma2's own menu).
RED / EXIT / BACK go through `back()`: behind live (Pause Live TV,
below) they return to live first, else `cancel()` closes.

**Local proxy (`vavoo_proxy.py`)** — a long-running background HTTP server
started as an in-process daemon thread (`threading.Thread(target=
start_proxy)`, spawned from `run_proxy_in_background()`), monitored/restarted
by `plugin.py` and `ProxyHealthMonitor`, listening on `127.0.0.1:4323`. It:
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
  `/refresh_token`, `/group_sources`, `/epg/<country>.xml` (redirects to
  GitHub-hosted EPG), `/file`, and `/shutdown`.
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
- Falls back from `vavoo.to` to `kool.to` on HTTP 451.
- Bouquets and M3U exports embed proxy URLs
  (`http://127.0.0.1:4323/vavoo?channel=...`), not raw Vavoo URLs — this is
  the core trick that makes streams stable.

**Bouquets (`bouquet_manager.py`)** — writes Enigma2 bouquet files (flat or
per-category/hierarchical) that reference the proxy, matches services
against the Rytec database for EPG service-reference compatibility, and can
reorganize bouquet position (top/bottom of channel list).

**EPG (`vUtils.py`'s `VavooEPGMatcher` + `channel_alias.py`)** — downloads/parses EPG,
caches matched/unmatched channels to
`/etc/enigma2/vavoo_epg_cache.json` and `..._unmatched_cache.json`, and
does satellite-priority matching: it reads the user's configured satellites
from Enigma2's `NimManager` and boosts matches from those (1.5x) and from
Italian satellites/13°E HotBird/5°W Eutelsat (1.3x) as a fallback for
Italian channels. Priority order: Satellite > Terrestrial > Cable > IPTV.
`find_match()`'s full priority chain: country-gated `channel_alias.ALIAS_MAP`
→ local per-box cache → **curated channel database** (below) → live
Rytec fuzzy matching → live own-feed fallback → unmatched. `VavooEPGMatcher` is a per-process singleton
(`get_epg_matcher()`) called concurrently from real usage (a bouquet
export's background thread vs. a per-channel EPG-overlay daemon thread
spawned by watching TV) — its `cache`/`normalized_index`/`new_matches`
mutations are guarded by `self._cache_lock` (an `RLock`), taken by
`find_match()` and by every external mutator
(`update_complete_cache()`, `clean_cache_and_unmatched()`).

**Curated EPG channel database** — a Rytec-independent matching path
added to cover countries Rytec handles poorly (e.g. Spain, Poland,
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
next export. Every match this path (and Rytec, and the alias table) produces
gets a synthetic, per-channel-unique service reference via
`unique_fallback_sref()` rather than a shared Rytec tuple, so different
channels/countries can never collide in Enigma2's `eEPGCache` (which
indexes purely by the DVB tuple, ignoring the embedded stream URL) even
when they share the same EPG id. `.github/workflows/generate_epg_channel_db.yml`
regenerates this weekly (plus on-demand) on a self-hosted runner — required
since fetching Vavoo's live channel list needs an authenticated
`vavoo_proxy` instance, unreachable from GitHub's hosted cloud runners.

**In-plugin programme info (`vUtils.py`'s `load_epg_guide()` /
`lookup_now_next()`)** — what is on a channel now and next, read
straight from the country's `epg_<cc>.xml` (through the proxy's
`/epg/<cc>.xml` redirect), no EPGImport involved. Two users, one
lookup, so they always agree: the Now/Next panel beside the channel
list (`NowNextPanel` mixin in `plugin.py`, used by `vavoo` and
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
  as tuples. One `EpgGuide` per country, reused for an hour, four
  countries at most, one download at a time per country.
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
  `plugin.py`'s `ask_pin()` / `_require_parental_pin(...,
  channel_name=)` ask for it (the `VavooPin` pad); once entered all is
  open for 15 minutes (`is_unlocked()`, `/proc/uptime`) or until
  `MainVavoo.closex()` calls `relock()`. Adult = `ADULT_RE` on the
  name or category. Never in a backup, never touched by a restore.
- Backup: `VavooStream-backup-*.json` (`"format": "vavoo_e2_backup"`):
  `plugin.py`'s `BACKUP_SETTINGS` plus the lists; restore replaces.
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

**Programme guide and reminders (`plugin.py`'s `VavooGuide`,
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
opens with `ACTIVE["pending"]`). The guide's OK on a programme to
come offers Remind me / Record / Watch; MENU is the app's key menu
(Now, `_programme_actions()` while the programme is not over,
Settings when not over the player). A locked row has no programmes,
so no actions.

**Recordings and Pause Live TV (`vavoo_record.py`, `plugin.py`'s
`RECORDINGS`, `Playstream2`, `VavooRecordings`,
`VavooRecordingPlayer`)** — the app's Recorder / RecordingService /
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
  `vavoo_record.MIN_FREE`; the recorder's thread waits for the proxy
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
- `VavooRecordings` (a `VavooPickScreen`, Settings → Recordings and the
  main list's `REMINDERS_ROW` row "Recordings (n)") lists timers then
  recordings; a recording of a locked channel needs the PIN
  (`recording_needs_pin()`). `VavooRecordingPlayer` plays a finished
  file directly (`eServiceReference(int(cfg.services.value), 0,
  path)`, Enigma2's own seeking) and one still recording through
  `/file` like the pause buffer; it lets go of a preview stream
  (`NOW_PLAYING.release_preview()`) and puts back only a non-plugin
  service when it closes.
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

## Enigma2-specific conventions

- UI code imports from Enigma2 framework packages that only exist on real
  hardware/emulation (`enigma`, `Components.*`, `Screens.*` is implied via
  `Screen`, `Tools.Directories`, `twisted.internet.reactor`). These cannot
  be imported or unit-tested on a normal dev machine — there is no mock
  layer in this repo. Static review (read the code, run linters) is the
  practical verification method available in this environment.
- Translatable strings use gettext `_()`, domain `PluginLanguageDomain =
  "vavoo"`, path `Extensions/vavoo/locale`. New user-facing strings should
  be wrapped in `_()`.
- Config options are declared via `Components.config` (`ConfigSelection`,
  `ConfigYesNo`, `ConfigSubsection`, etc.) — follow the existing pattern in
  `plugin.py`/`vavoo_config` rather than inventing a separate config
  mechanism.
- Skins are resolution-specific XML under `skin/{hd,fhd,wqhd}/`. If you
  change a screen's layout/widgets in `plugin.py`, check whether the
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
  `plugin.py` (and other modules) plus strings extracted from skin XML.
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
- Because there's no automated test suite or way to exercise Enigma2 UI
  code locally, prioritize: (a) not breaking Python 2/3 import
  compatibility, (b) keeping `plugin.py` Screens and their skin XML in
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
