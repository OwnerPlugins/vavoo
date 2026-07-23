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
  start_proxy.py / start_proxy.sh   # spawns vavoo_proxy.py as a detached background process
  bouquet_manager.py     # builds/exports Enigma2 bouquets (flat + hierarchical) pointing at the proxy
  channel_alias.py       # channel name normalization/aliasing for EPG matching
  vUtils.py              # grab-bag: logging, HTTP helpers, caching, proxy status/health helpers,
                          #   EPG download/parse/cache + Rytec/satellite-priority channel matching
  notification_system.py # singleton, thread-safe on-screen notification/toast manager
  vavoo_stats.py         # anonymous opt-out startup/heartbeat telemetry (no PII)
  Console.py             # generic subprocess-output Screen used for shell commands in the UI
  update_translations.py # dev-time script: extracts strings, updates .po/.pot, compiles .mo
  xml2pot.py             # dev-time helper: pulls translatable strings out of skin XML into .pot
  check_skin_consistency.py # dev-time script: compares widget name= sets across hd/fhd/wqhd skins
  locale/<lang>/LC_MESSAGES/vavoo.{po,mo}  # gettext translations, ~90 languages
  skin/{hd,fhd,wqhd}/*.xml   # per-resolution skin layouts (HD, FullHD, WQHD/4K)
  skin/cowntry/*.png, skin/pics/*.png, skin/images*/*.png  # flags/backgrounds
  fonts/*.ttf
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

**Local proxy (`vavoo_proxy.py`)** — a separate, long-running background
process (started via `start_proxy.sh`/`start_proxy.py`, monitored/restarted
by `plugin.py` and `ProxyHealthMonitor`) listening on `127.0.0.1:4323`. It:
- Obtains/renews the Vavoo auth signature/token (`TOKEN_ADDON_SIG`, renewed
  every ~8-9 min) so bouquets never hit Vavoo's 10-minute anonymous block.
- Resolves `/vavoo?channel=<id>` to a real stream URL via 302 redirect.
- Serves `/channels`, `/catalog`, `/countries`, `/status`, `/health`,
  `/refresh_token`, `/epg/<country>.xml` (redirects to GitHub-hosted EPG),
  and `/shutdown`.
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

**Notifications (`notification_system.py`)** — singleton
`HybridNotificationManager`, thread-safe (lock-protected), with a message
queue for messages sent before the UI is ready. `init_notification_system(session)`
must be called exactly once (from `MainVavoo`). Use `quick_notify(message, seconds)`
from anywhere, including background threads.

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
- `ruff.yml` — runs `ruff check .` inside
  `usr/lib/enigma2/python/Plugins/Extensions/vavoo/` only, on push/PR.
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
on merge to `main`. Also update the version badge in `README.md` and
`Version:` in `CONTROL/control` to keep them in sync (they are not
auto-synced).

## Packaging / distribution paths

Three independent ways this plugin reaches a box — keep them consistent
when changing paths, dependencies, or version:
1. **ipkg/opkg package** — `CONTROL/control` (declares
   `python3-requests`, `python3-six` deps) + `CONTROL/postinst` /
   `preinst` / `postrm` shell scripts.
2. **Yocto/OpenEmbedded recipe** — `enigma2-plugin-extensions-vavoo.bb`,
   pulls from `git://github.com/Belfagor2005/vavoo.git` branch `main`,
   depends on `ffmpeg gstplayer exteplayer3
   enigma2-plugin-systemplugins-serviceapp python3-requests python3-six`.
3. **Self-installer** — `installer.sh`, a curl/wget-friendly script users
   run directly on the box: detects OS flavor (DreamOS/OE/Debian) and
   Python 2 vs 3, installs `wget`/`requests`/`six` (and OE-only deps),
   downloads the `main` branch tarball from GitHub, and copies
   `usr/` into place, then prompts a reboot.

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
