#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
Dev-time consistency checker.

Compares the set of name= attributes used across the hd/fhd/wqhd skin
XML variants of each screen. plugin.py's Screen classes bind widgets by
name (self["widget_name"] = ...) against whichever resolution's skin
gets loaded at runtime; if a widget is added/renamed in one resolution
and the same change is forgotten in another, nothing catches it until a
user on that specific resolution reports a missing or misaligned
widget. This script catches that class of bug ahead of time.

Usage: python check_skin_consistency.py
Exit code is non-zero if any inconsistency is found, so this can be
wired into CI later if desired - it isn't currently.
"""
from __future__ import absolute_import, print_function
import os
import sys
import xml.etree.ElementTree as ET

SKIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skin")
RESOLUTIONS = ["hd", "fhd", "wqhd"]


def collect_widget_names(xml_path):
    """Return the set of name= values used on any element except the
    root <screen> tag (which just names the screen itself, not a
    Python-bound widget)."""
    names = set()
    try:
        tree = ET.parse(xml_path)
    except ET.ParseError as e:
        print("  ERROR parsing {}: {}".format(xml_path, e))
        return names
    root = tree.getroot()
    for elem in root.iter():
        if elem is root:
            continue
        name = elem.get("name")
        if name:
            names.add(name)
    return names


def main():
    filenames = set()
    for res in RESOLUTIONS:
        res_dir = os.path.join(SKIN_DIR, res)
        if not os.path.isdir(res_dir):
            print("Missing resolution directory: {}".format(res_dir))
            continue
        filenames.update(
            f for f in os.listdir(res_dir) if f.endswith(".xml"))

    problems = 0
    for filename in sorted(filenames):
        per_res = {}
        missing_dirs = []
        for res in RESOLUTIONS:
            path = os.path.join(SKIN_DIR, res, filename)
            if not os.path.isfile(path):
                missing_dirs.append(res)
                continue
            per_res[res] = collect_widget_names(path)

        if missing_dirs:
            print("{}: missing from {}".format(
                filename, ", ".join(missing_dirs)))
            problems += 1
            continue

        all_names = set()
        for names in per_res.values():
            all_names |= names

        diffs = {}
        for name in sorted(all_names):
            present_in = [res for res in RESOLUTIONS if name in per_res[res]]
            if len(present_in) != len(RESOLUTIONS):
                diffs[name] = present_in

        if diffs:
            print("{}:".format(filename))
            for name, present_in in diffs.items():
                missing_from = [r for r in RESOLUTIONS if r not in present_in]
                print("  '{}' present in {} but missing from {}".format(
                    name, present_in, missing_from))
            problems += 1

    if problems:
        print(
            "\n{} screen(s) with inconsistent widgets across resolutions.".format(
                problems))
        return 1
    print("All skin resolutions have matching widget name= sets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
