# Tests

The plugin cannot run outside an Enigma2 box, so these tests fake
Enigma2 (`e2stub.py`: every `enigma`, `Components.*`, `Screens.*` ...
module and class made up on demand) and run the real plugin code against
it: every screen opening in every theme and resolution, every key, menu
entry and dialog of every screen, the proxy (with hostile requests), the
EPG sources and matching, recordings and Pause Live TV against a fake
live channel, the lists and data files (also broken ones).

```
python3 tests/run_tests.py            # everything (about 2.5 minutes)
python3 tests/run_tests.py --quick    # without the ffmpeg tests (about 30 s)
python2.7 tests/run_tests.py          # the Python 2 list
python3 tests/test_guide.py           # one test
```

Needs `six` and `requests` (as the plugin); the recording tests need
`ffmpeg` and `ffprobe` and are skipped without them. CI runs them on
Python 3 and 2.7 (`.github/workflows/tests.yml`).

- `e2env.py` - the faked Enigma2, a throw-away data folder, the
  anonymous statistics off; `load_plugin()` returns a view of the
  plugin's screen modules (`plugin.X` finds X in plugin.py or a ui_*.py;
  `plugin.X = fake` replaces it in each of them).
- `harness.py` - fake widgets, `make()` (a screen built by its real
  `__init__`), `enigma2_close()` (closed as Enigma2's `doClose()` does:
  every attribute gone), `Pending` (the threads and reactor calls a
  screen leaves, run after it closed), `check()` / `finish()`.
- `fakehls.py` - a fake live HLS channel (segments made once with
  ffmpeg in the temp folder).
- `test_keys_lib.py` - Enigma2's key dispatch, with the images' own
  keymaps in `data/keymaps/`.
- `py2_smoke.py` - a manual Python 2 check that records with ffmpeg
  (`python2.7 tests/py2_smoke.py <python3>`).

Two checks need the real guides of France and Poland (14 MB, not in
the repository): put `epg_fr.xml.gz` and `epg_pl.xml.gz` in
`tests/epgdl/` (or point `$VAVOO_EPG_SAMPLES` at them).
