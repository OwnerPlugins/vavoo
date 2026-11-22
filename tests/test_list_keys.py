# -*- coding: utf-8 -*-
"""The list screens' keys on the real keymaps of OpenATV, OpenPLi and
OpenViX (Enigma2's dispatch simulated): one action per press, CH± pages."""
from __future__ import print_function
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import make, Session, V, check, finish   # noqa: E402
plugin = harness.plugin
import test_keys_lib as tk                      # noqa: E402

plugin.ActionMap = tk.RAM
s = Session()
plugin.is_proxy_running = lambda *a, **k: True
plugin.is_proxy_ready = lambda *a, **k: True
plugin.cfg.subcategories = V(False)
CH = [{"name": "RAI 1",
       "url": "vavoo?channel=r1",
       "country_name": "Italy",
       "country_code": "it",
       "epg_id": "Rai1.it"}]
MV = plugin.MainVavoo
mv = MV.__new__(MV)
mv.widgets = {}
MV.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
MV.__getitem__ = lambda self, k: self.widgets[k]
MV._initialize_actions(mv)
screens = [
    ("main list", mv),
    ("channel list", make(plugin.vavoo, s, "Italy", None)),
    ("Favourites", make(plugin.VavooFavourites, s)),
    ("guide", make(plugin.VavooGuide, s, CH, 0, "Italy")),
    ("Recordings", make(plugin.VavooRecordings, s)),
    ("Choose countries", make(plugin.VavooCountries, s, ["Albania", "Italy"])),
    ("Parental Control", make(plugin.VavooParental, s, ["Italy", "Albania"])),
    ("PIN pad", make(plugin.VavooPin, s, "x", 4, lambda pin: None)),
    ("Search", make(plugin.VavooSearch, s, None, [], scope="all channels")),
]
KEYS = [
    "KEY_OK",
    "KEY_EXIT",
    "KEY_RED",
    "KEY_GREEN",
    "KEY_YELLOW",
    "KEY_BLUE",
    "KEY_MENU",
    "KEY_INFO",
    "KEY_EPG",
    "KEY_UP",
    "KEY_DOWN",
    "KEY_LEFT",
    "KEY_RIGHT",
    "KEY_CHANNELUP",
    "KEY_CHANNELDOWN",
    "KEY_1",
    "KEY_0"]
PAGE = {"KEY_CHANNELUP": ("nextBouquet",), "KEY_CHANNELDOWN": ("prevBouquet",)}

for image, folder in sorted(tk.IMAGES.items()):
    keymap = tk.read_keymap(os.path.join(tk.KEYMAPS, folder, "keymap.xml"))
    print("==", image)
    for title, scr in screens:
        maps = [v for v in scr.widgets.values() if isinstance(v, tk.RAM)]
        twice, fired = [], {}
        for key in KEYS:
            ran = []
            for flag in "mb":
                m, action = tk.dispatch(keymap, maps, key, flag)
                if m is not None:
                    ran.append((m, action))
            fired[key] = [a for _m, a in ran]
            if len(ran) > 1:
                # one function reached twice (press and release)
                twice.append("%s: %s" % (key, ", ".join(a for _m, a in ran)))
        check(not twice, "%s: one action per press%s" %
              (title, "" if not twice else " - " + "; ".join(twice)))
        actions = {}
        for m in maps:
            for name in m.actions:
                actions.setdefault(name, m)
        if "nextBouquet" in actions:
            ok = all(fired[k] and fired[k][0] in PAGE[k] for k in PAGE)
            check(ok, "%s: CH+ / CH- page (%r, %r)" %
                  (title, fired["KEY_CHANNELUP"], fired["KEY_CHANNELDOWN"]))
        if "info" in actions:
            check(
                fired["KEY_INFO"] in (
                    ["info"], ["InfoPressed"]) and fired["KEY_EPG"] in (
                    ["epg"], ["info"]), "%s: INFO / EPG (%r, %r)" %
                (title, fired["KEY_INFO"], fired["KEY_EPG"]))
        for colour in ("red", "green", "yellow", "blue"):
            if colour in actions:
                key = "KEY_" + colour.upper()
                check(
                    fired[key] == [colour], "%s: %s once (%r)" %
                    (title, colour.upper(), fired[key]))
        if "menu" in actions:
            check(
                fired["KEY_MENU"] == ["menu"], "%s: MENU once (%r)" %
                (title, fired["KEY_MENU"]))
finish()
