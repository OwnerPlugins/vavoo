# -*- coding: utf-8 -*-
"""Enigma2's key dispatch, simulated (shared by the key tests)."""
import os
import xml.etree.ElementTree as ET
HERE = os.path.dirname(os.path.abspath(__file__))
IMAGES = {"OpenATV": "oatv", "OpenPLi": "opli", "OpenViX": "ovix"}
# (the images' own keymaps: data/keymaps/README.md)
KEYMAPS = os.path.join(HERE, "data", "keymaps")


def read_keymap(path, into=None):
    into = {} if into is None else into
    for m in ET.parse(path).getroot().findall("map"):
        rows = into.setdefault(m.get("context"), [])
        for k in m.findall("key"):
            rows.append((k.get("id"), set(k.get("flags")),
                        k.get("mapto") or k.get("mapTo")))
    return into


class RAM(object):
    def __init__(self, contexts, actions, prio=0):
        self.contexts, self.actions, self.prio = contexts, actions, prio
        self.enabled = True
        self.disabled = set()


def dispatch(keymap, maps, key, flag):
    order = sorted(range(len(maps)), key=lambda i: (maps[i].prio, i))
    for i in order:
        m = maps[i]
        if not m.enabled:
            continue
        for context in m.contexts:
            for k, flags, action in keymap.get(context, []):
                if k == key and flag in flags and action in m.actions and action not in m.disabled:
                    return m, action
    return None, None
