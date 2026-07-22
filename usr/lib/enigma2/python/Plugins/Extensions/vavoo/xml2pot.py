#!/usr/bin/python
# -*- coding: utf-8 -*-
# script: xml2pot.py (in the main plugin folder)

import sys
import os
import re
try:
    import xml.etree.ElementTree as ET
except ImportError:
    import cElementTree as ET


def extract_strings_from_xml(xml_file):
    """Extract all translatable strings from setup.xml"""
    strings = []

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()

        # Find all 'item' tags with text/description attributes
        for item in root.findall('.//item'):
            # Extract 'text' attribute
            if 'text' in item.attrib:
                text = item.attrib['text'].strip()
                if text and not re.match(r'^#[0-9a-fA-F]{6,8}$', text):
                    strings.append(text)

            # Extract 'description' attribute
            if 'description' in item.attrib:
                desc = item.attrib['description'].strip()
                if desc and not re.match(r'^#[0-9a-fA-F]{6,8}$', desc):
                    strings.append(desc)

        # Also look in 'setup' tag for the title
        for setup in root.findall('.//setup'):
            if 'title' in setup.attrib:
                title = setup.attrib['title'].strip()
                if title:
                    strings.append(title)

    except Exception as e:
        print("ERROR parsing XML: %s" % str(e))
        return []

    # Remove duplicates while preserving order
    seen = set()
    unique_strings = []
    for s in strings:
        if s not in seen:
            seen.add(s)
            unique_strings.append(s)

    return unique_strings


def main():
    if len(sys.argv) < 2:
        print("Usage: python xml2pot.py <setup.xml>")
        sys.exit(1)

    xml_file = sys.argv[1]
    pot_file = "locale/vavoo.pot"  # In locale/ folder

    if not os.path.exists(xml_file):
        print("File not found: %s" % xml_file)
        sys.exit(1)

    # Extract strings
    strings = extract_strings_from_xml(xml_file)

    if not strings:
        print("No strings found in %s" % xml_file)
        sys.exit(0)

    print("Found %d unique strings:" % len(strings))
    for i, text in enumerate(strings):
        print("%d. %s" % (i + 1, text[:80]))

    # Create locale/ directory if it doesn't exist
    if not os.path.exists("locale"):
        os.makedirs("locale")

    # Write to .pot file
    try:
        # Read existing content to avoid duplicates
        existing_strings = set()
        if os.path.exists(pot_file):
            with open(pot_file, 'r') as f:
                content = f.read()
                for match in re.finditer(r'msgid "([^"]+)"', content):
                    existing_strings.add(match.group(1))

        # Keep only new strings
        new_strings = [s for s in strings if s not in existing_strings]

        if not new_strings:
            print("\nAll strings are already present in %s" % pot_file)
            return

        with open(pot_file, 'a') as f:
            f.write('\n# Strings from setup.xml\n')
            for text in new_strings:
                f.write('\n')
                f.write('msgid "%s"\n' % text.replace('"', '\\"'))
                f.write('msgstr ""\n')

        print("\nAdded %d new strings to: %s" % (len(new_strings), pot_file))

    except Exception as e:
        print("ERROR writing .pot: %s" % str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
