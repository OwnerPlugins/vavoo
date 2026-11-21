# Enigma2 images' own keymaps

Copies of the key maps three Enigma2 images ship, used by the key tests
(`test_keys.py`, `test_direct_keys.py`, `test_list_keys.py`) to check
that every key of the plugin reaches the right function on each image.
They are read only by the tests and never go to a box.

| Folder | Image | Files (from the image's `enigma2` repository) |
|---|---|---|
| `oatv/` | OpenATV (github.com/openatv/enigma2) | `data/keymap.xml` |
| `opli/` | OpenPLi (github.com/OpenPLi/enigma2) | `data/keymap.xml`, `lib/python/keyids.py` (the key names' numbers) |
| `ovix/` | OpenViX (github.com/OpenViX/enigma2) | `data/keymap.xml` |

Copied in November 2026. These files belong to their projects and are
under their licence (GNU GPL v2), not this repository's.
