#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import re
import subprocess
from xml.etree import ElementTree as ET
"""
###########################################################
Plugin for Enigma2
Created by: Lululla
###########################################################
Last Updated: 2026-04-19
Credits: Lululla (modifications)
Homepage: www.corvoboys.org
          www.linuxsat-support.com
###########################################################
"""

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
PLUGIN_NAME = os.path.basename(PLUGIN_DIR)
LOCALE_DIR = os.path.join(PLUGIN_DIR, "res", "locale")


def get_locale_dir(plugin_dir):
    candidates = [
        os.path.join(plugin_dir, "locale"),         # es. /plugin/locale
        os.path.join(plugin_dir, "res", "locale")   # es. /plugin/res/locale
    ]
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    # default: verrà creata successivamente
    return os.path.join(plugin_dir, "locale")


LOCALE_DIR = get_locale_dir(PLUGIN_DIR)
POT_FILE = os.path.join(LOCALE_DIR, "{}.pot".format(PLUGIN_NAME))


STANDARD_LANGUAGES = [
    'af',         # Afrikaans
    'am',         # Amharic
    'ar',         # Arabic
    'az',         # Azerbaijani
    'be',         # Belarusian
    'bg',         # Bulgarian
    'bn',         # Bengali
    'bs',         # Bosnian
    'ca',         # Catalan
    'cs',         # Czech
    'cy',         # Welsh
    'da',         # Danish
    'de',         # German
    'el',         # Greek
    'en',         # English
    'en_GB',      # British English
    'eo',         # Esperanto
    'es',         # Spanish
    'et',         # Estonian
    'eu',         # Basque
    'fa',         # Persian
    'fi',         # Finnish
    'fr',         # French
    'fy',         # Frisian
    'ga',         # Irish
    'gd',         # Scottish Gaelic
    'gl',         # Galician
    'gu',         # Gujarati
    'he',         # Hebrew
    'hi',         # Hindi
    'hr',         # Croatian
    'hu',         # Hungarian
    'hy',         # Armenian
    'id',         # Indonesian
    'is',         # Icelandic
    'it',         # Italian
    'ja',         # Japanese
    'ka',         # Georgian
    'kk',         # Kazakh
    'km',         # Khmer
    'kn',         # Kannada
    'ko',         # Korean
    'ku',         # Kurdish
    'ky',         # Kyrgyz
    'lt',         # Lithuanian
    'lv',         # Latvian
    'mk',         # Macedonian
    'ml',         # Malayalam
    'mn',         # Mongolian
    'mr',         # Marathi
    'ms',         # Malay
    'mt',         # Maltese
    'my',         # Burmese
    'nb',         # Norwegian Bokmål
    'ne',         # Nepali
    'nl',         # Dutch
    'no',         # Norwegian
    'oc',         # Occitan
    'or',         # Odia
    'pa',         # Punjabi
    'pl',         # Polish
    'ps',         # Pashto
    'pt',         # Portuguese
    'pt_BR',      # Brazilian Portuguese
    'pt_PT',      # European Portuguese
    'ro',         # Romanian
    'ru',         # Russian
    'si',         # Sinhala
    'sk',         # Slovak
    'sl',         # Slovenian
    'sq',         # Albanian
    'sq_AL',      # Albanian (Albania) - CHE C'È NEL TUO FILE!
    'sr',         # Serbian
    'sr_Latn',    # Serbian (Latin)
    'sv',         # Swedish
    'sw',         # Swahili
    'ta',         # Tamil
    'te',         # Telugu
    'tg',         # Tajik
    'th',         # Thai
    'tk',         # Turkmen
    'tl',         # Tagalog
    'tr',         # Turkish
    'tt',         # Tatar
    'ug',         # Uyghur
    'uk',         # Ukrainian
    'ur',         # Urdu
    'uz',         # Uzbek
    'vi',         # Vietnamese
    'yi',         # Yiddish
    'zh',         # Chinese
    'zh_CN',      # Simplified Chinese
    'zh_HK',      # Hong Kong Chinese
    'zh_SG',      # Singapore Chinese
    'zh_TW',      # Traditional Chinese
]


def ensure_directory_structure(lang_code):
    """Crea la struttura delle cartelle per una lingua specifica"""
    lang_dir = os.path.join(LOCALE_DIR, lang_code)
    lc_messages_dir = os.path.join(lang_dir, "LC_MESSAGES")

    try:
        if not os.path.exists(lc_messages_dir):
            os.makedirs(lc_messages_dir, exist_ok=True)
            print("  Created directory structure for: {}".format(lang_code))
        return lc_messages_dir
    except Exception as e:
        print("  ERROR creating directories for {}: {}".format(lang_code, e))
        return None


def extract_xml_strings():
    """Extract all strings from setup.xml"""
    xml_file = os.path.join(PLUGIN_DIR, "setup.xml")

    if not os.path.exists(xml_file):
        print("INFO: {} not found! Skipping XML extraction.".format(xml_file))
        return []

    strings = []
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()

        # Search all relevant tags
        for elem in root.findall('.//*[@text]'):
            text = elem.get('text', '').strip()
            if text and not re.match(r'^#[0-9a-fA-F]{6,8}$', text):
                strings.append(('text', text))

        for elem in root.findall('.//*[@description]'):
            desc = elem.get('description', '').strip()
            if desc and not re.match(r'^#[0-9a-fA-F]{6,8}$', desc):
                strings.append(('description', desc))

        for elem in root.findall('.//*[@title]'):
            title = elem.get('title', '').strip()
            if title:
                strings.append(('title', title))

    except Exception as e:
        print("ERROR parsing XML: {}".format(e))
        return []

    # Remove duplicates
    seen = set()
    unique = []
    for _, text in strings:
        if text and text.strip():
            cleaned_text = text.strip()
            if cleaned_text not in seen:
                seen.add(cleaned_text)
                unique.append(cleaned_text)

    print("XML: found {} unique strings".format(len(unique)))
    return clean_strings(unique)


def clean_strings(strings):
    """Clean extracted strings to remove common issues"""
    cleaned = []
    for s in strings:
        # Skip empty strings
        if not s or not s.strip():
            continue

        # Remove leading/trailing whitespace
        s = s.strip()

        # Skip strings that are only formatting placeholders without context
        if s in [
            '{0}',
            '{1}',
            '{2}',
            '{3}',
            '{4}',
            '{5}',
            '{6}',
            '{7}',
            '{8}',
                '{9}']:
            continue

        # Skip strings that are just numbers or symbols
        if re.match(r'^[0-9\s\W]+$', s):
            continue

        cleaned.append(s)

    return cleaned


def extract_python_strings():
    """Extract strings from all .py files using xgettext"""
    py_strings = []

    try:
        # Create temporary .pot file from Python files
        temp_pot = os.path.join(PLUGIN_DIR, "temp_python.pot")

        # Find all .py files
        py_files = []
        for root_dir, _, files in os.walk(PLUGIN_DIR):
            for f in files:
                if f.endswith('.py') and not f.startswith('test_'):
                    py_files.append(os.path.join(root_dir, f))

        if not py_files:
            print("No .py files found")
            return []

        # xgettext command
        cmd = [
            'xgettext',
            '--no-wrap',
            '-L', 'Python',
            '--from-code=UTF-8',
            '-kpgettext:1c,2',
            '--add-comments=TRANSLATORS:',
            '-d', PLUGIN_NAME,
            '-s',
            '-o', temp_pot
        ] + py_files

        # Run xgettext - Python 2 compatible
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = process.communicate()
            if process.returncode != 0:
                print("ERROR xgettext: {}".format(stderr))
                return []
        except OSError as e:
            print("ERROR running xgettext: {}".format(e))
            return []

        if os.path.exists(temp_pot):
            with open(temp_pot, 'r') as f:
                content = f.read()

            # Extract all msgid
            for match in re.finditer(r'msgid "([^"]+)"', content):
                text = match.group(1)
                if text and text.strip():
                    py_strings.append(text.strip())

            # Clean up temp file
            try:
                os.remove(temp_pot)
            except BaseException:
                pass

        print("Python: found {} strings".format(len(py_strings)))
        return clean_strings(py_strings)
    except Exception as e:
        print("ERROR extracting Python strings: {}".format(e))
        return []


def update_pot_file(xml_strings, py_strings):
    """Create or update the final .pot file"""
    # Ensure the folder exists
    try:
        os.makedirs(LOCALE_DIR, exist_ok=True)
    except BaseException:
        pass

    # Merge all strings
    all_strings = list(set(xml_strings + py_strings))

    # Filter problematic strings
    filtered_strings = []
    for s in all_strings:
        if s.startswith(' ') or s.endswith(' '):
            s = s.strip()
        if s and s not in filtered_strings:
            filtered_strings.append(s)

    filtered_strings.sort()
    all_strings = filtered_strings
    print("TOTAL: {} unique strings".format(len(all_strings)))

    # Read existing .pot file to preserve translations
    existing_translations = {}
    pot_header = ""

    if os.path.exists(POT_FILE):
        try:
            with open(POT_FILE, 'r') as f:
                content = f.read()
            # Separate header (everything before first msgid)
            parts = content.split('msgid "')
            if len(parts) > 1:
                pot_header = parts[0]

            # Extract existing translations
            for match in re.finditer(
                r'msgid "([^"]+)"\s*\nmsgstr "([^"]*)"',
                content,
                    re.DOTALL):
                msgid = match.group(1)
                msgstr = match.group(2)
                existing_translations[msgid] = msgstr
        except BaseException:
            pass

    # Write the new .pot file
    try:
        with open(POT_FILE, 'w') as f:
            # Header
            if pot_header:
                f.write(pot_header)
            else:
                f.write('# {} translations\n'.format(PLUGIN_NAME))
                f.write('# Copyright (C) 2025 Lululla Team\n')
                f.write(
                    '# This file is distributed under the same license as the Lululla package.\n')
                f.write('# [lululla] <ekekaz@gmail.com>, 2025.\n')
                f.write('#\n')
                f.write('msgid ""\n')
                f.write('msgstr ""\n')
                f.write('"Project-Id-Version: {}\\n"\n'.format(PLUGIN_NAME))
                f.write('"Report-Msgid-Bugs-To: \\n"\n')
                f.write('"POT-Creation-Date: \\n"\n')
                f.write('"PO-Revision-Date: \\n"\n')
                f.write('"Last-Translator: \\n"\n')
                f.write('"Language-Team: ekekaz@gmail.com [lululla]\\n"\n')
                f.write('"Language: \\n"\n')
                f.write('"MIME-Version: 1.0\\n"\n')
                f.write('"Content-Type: text/plain; charset=UTF-8\\n"\n')
                f.write('"Content-Transfer-Encoding: 8bit\\n"\n\n')

            # Write all strings
            for msgid in all_strings:
                f.write('\n')
                f.write('msgid "{}"\n'.format(msgid))
                f.write(
                    'msgstr "{}"\n'.format(
                        existing_translations.get(
                            msgid, "")))

        print("Updated .pot file: {}".format(POT_FILE))
        return len(all_strings)

    except Exception as e:
        print("ERROR writing .pot file: {}".format(e))
        return 0


def fix_po_file(po_file):
    """Fix common issues in .po files"""
    try:
        with open(po_file, 'r') as f:
            lines = f.readlines()

        fixed_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]

            # Skip empty msgid blocks
            if line.strip() == 'msgid ""' and i + \
                    1 < len(lines) and lines[i + 1].strip() == 'msgstr ""':
                # Check if this is the header (should be only one)
                if not any(ls.strip().startswith('"Project-Id-Version:')
                           for ls in fixed_lines):
                    # Keep header
                    fixed_lines.append(line)
                    fixed_lines.append(lines[i + 1])
                    i += 2
                    # Continue reading header lines
                    while i < len(lines) and lines[i].strip().startswith('"'):
                        fixed_lines.append(lines[i])
                        i += 1
                    continue
                else:
                    # Skip duplicate empty msgid
                    i += 2
                    continue

            # Check for syntax errors at specific lines
            if line.strip().startswith('msgid "') and '""' in line:
                # Fix malformed msgid
                fixed_line = 'msgid ""\n'
                fixed_lines.append(fixed_line)
                i += 1
                continue

            fixed_lines.append(line)
            i += 1

        # Remove duplicate msgid entries
        cleaned_lines = []
        seen_msgids = set()
        i = 0
        while i < len(fixed_lines):
            if fixed_lines[i].strip().startswith('msgid "'):
                msgid_line = fixed_lines[i]
                if msgid_line in seen_msgids:
                    # Skip this duplicate block
                    i += 1
                    # Skip until next empty line or end of file
                    while i < len(
                            fixed_lines) and fixed_lines[i].strip() != '':
                        i += 1
                    continue
                else:
                    seen_msgids.add(msgid_line)
                    cleaned_lines.append(fixed_lines[i])
                    i += 1
            else:
                cleaned_lines.append(fixed_lines[i])
                i += 1

        # Write back fixed file
        with open(po_file, 'w') as f:
            f.writelines(cleaned_lines)

        return True

    except Exception as e:
        print("ERROR fixing {}: {}".format(po_file, e))
        return False


def update_po_files():
    """Update all .po files with new strings"""
    if not os.path.exists(POT_FILE):
        print("ERROR: .pot file not found")
        return

    # Prima controlla le lingue esistenti
    existing_languages = []
    if os.path.exists(LOCALE_DIR):
        for item in os.listdir(LOCALE_DIR):
            item_path = os.path.join(LOCALE_DIR, item)
            if os.path.isdir(item_path) and item != 'templates':
                po_file = os.path.join(
                    item_path, "LC_MESSAGES", "{}.po".format(PLUGIN_NAME))
                if os.path.exists(po_file):
                    existing_languages.append(item)

    # Combina lingue esistenti con standard
    all_languages = list(set(existing_languages + STANDARD_LANGUAGES))
    all_languages.sort()

    print(
        "Processing {} languages: {}".format(
            len(all_languages),
            ', '.join(all_languages)))

    for lang_code in all_languages:
        # Crea la struttura delle cartelle
        lc_messages_dir = ensure_directory_structure(lang_code)
        if not lc_messages_dir:
            continue

        po_file = os.path.join(lc_messages_dir, "{}.po".format(PLUGIN_NAME))

        if os.path.exists(po_file):
            print("Updating: {}".format(lang_code))

            # First fix the existing .po file
            if fix_po_file(po_file):
                print("  Fixed syntax issues in {}".format(lang_code))

            # Use msgmerge WITHOUT --sort-output (-s)
            cmd = [
                'msgmerge',
                '--update',
                '--backup=none',
                '--no-wrap',
                po_file,
                POT_FILE
            ]

            try:
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = process.communicate()
                if process.returncode == 0:
                    # Fix again after merging
                    fix_po_file(po_file)
                    print(" ✓ {} updated".format(lang_code))
                else:
                    # Try to fix and retry
                    print("  First merge failed, fixing and retrying...")
                    if fix_po_file(po_file):
                        # Retry
                        process = subprocess.Popen(
                            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        stdout, stderr = process.communicate()
                        if process.returncode == 0:
                            print(" ✓ {} updated after fix".format(lang_code))
                        else:
                            print(
                                " ✗ ERROR updating {} after fix: {}".format(
                                    lang_code, stderr.decode('utf-8')[:100]))
            except Exception as e:
                print(" ✗ ERROR updating {}: {}".format(lang_code, e))

        else:
            # Create new .po file from template
            print("Creating new: {}".format(lang_code))

            cmd = [
                'msginit',
                '--no-wrap',
                '-i',
                POT_FILE,
                '-o',
                po_file,
                '-l',
                # msginit usa trattini invece di underscore
                lang_code.replace('_', '-')
            ]

            try:
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = process.communicate()
                if process.returncode == 0:
                    print(" ✓ Created new file for: {}".format(lang_code))
                    # Fix the new file
                    fix_po_file(po_file)
                else:
                    # Alternative method: copy template
                    print("  msginit failed, creating template manually...")
                    create_template_po_file(po_file, lang_code)
            except Exception as e:
                print(
                    " ✗ ERROR creating file for {}: {}".format(
                        lang_code, e))


def create_template_po_file(po_file, lang_code):
    """Create a basic .po template file"""
    try:
        with open(POT_FILE, 'r') as f:
            pot_content = f.read()

        # Extract header from POT
        header_end = pot_content.find('msgid ""')
        if header_end == -1:
            header = '# {} translations\n'.format(PLUGIN_NAME)
            header += '# Copyright (C) 2025 Lululla Team\n'
            header += '# This file is distributed under the same license as the Lululla package.\n'
            header += '# [lululla] <ekekaz@gmail.com>, 2025.\n'
            header += '#\n'
        else:
            header = pot_content[:header_end]

        # Extract msgid entries
        msgid_blocks = re.findall(
            r'(msgid "[^"]+"\s*\nmsgstr ""\s*\n)',
            pot_content,
            re.DOTALL)

        with open(po_file, 'w') as f:
            f.write(header)
            f.write('msgid ""\n')
            f.write('msgstr ""\n')
            f.write('"Project-Id-Version: {}\\n"\n'.format(PLUGIN_NAME))
            f.write('"POT-Creation-Date: \\n"\n')
            f.write('"PO-Revision-Date: \\n"\n')
            f.write('"Last-Translator: \\n"\n')
            f.write(
                '"Language-Team: {} <ekekaz@gmail.com>\\n"\n'.format(lang_code))
            f.write('"Language: {}\\n"\n'.format(lang_code))
            f.write('"MIME-Version: 1.0\\n"\n')
            f.write('"Content-Type: text/plain; charset=UTF-8\\n"\n')
            f.write('"Content-Transfer-Encoding: 8bit\\n"\n\n')

            for block in msgid_blocks:
                f.write(block)

        print(" ✓ Created template for: {}".format(lang_code))
        return True

    except Exception as e:
        print(" ✗ ERROR creating template for {}: {}".format(lang_code, e))
        return False


def compile_mo_files():
    """Compile all .po files into .mo"""
    if not os.path.exists(LOCALE_DIR):
        print("No locale directory found")
        return

    for lang_code in os.listdir(LOCALE_DIR):
        lc_messages_dir = os.path.join(LOCALE_DIR, lang_code, "LC_MESSAGES")
        po_file = os.path.join(lc_messages_dir, "{}.po".format(PLUGIN_NAME))
        mo_file = os.path.join(lc_messages_dir, "{}.mo".format(PLUGIN_NAME))

        if os.path.exists(po_file):
            try:
                # First fix the .po file before compiling
                fix_po_file(po_file)

                cmd = ['msgfmt', po_file, '-o', mo_file]
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                stdout, stderr = process.communicate()
                if process.returncode == 0:
                    print(
                        "✓ Compiled: {}/LC_MESSAGES/{}.mo".format(lang_code, PLUGIN_NAME))
                else:
                    # Try to fix common errors and retry
                    print(
                        "  First compile failed for {}, trying to fix...".format(lang_code))

                    # Remove problematic lines
                    try:
                        with open(po_file, 'r') as f:
                            lines = f.readlines()

                        # Rimuovi linee problematiche
                        clean_lines = []
                        for line in lines:
                            # Rimuovi linee vuote duplicate
                            if line.strip() == '' and len(
                                    clean_lines) > 0 and clean_lines[-1].strip() == '':
                                continue
                            clean_lines.append(line)

                        with open(po_file, 'w') as f:
                            f.writelines(clean_lines)

                        # Try compiling again
                        process = subprocess.Popen(
                            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        stdout, stderr = process.communicate()
                        if process.returncode == 0:
                            print(
                                "✓ Compiled: {}/LC_MESSAGES/{}.mo (after fix)".format(lang_code, PLUGIN_NAME))
                        else:
                            print("✗ ERROR compiling {}: {}".format(
                                lang_code, stderr.decode('utf-8')[:100]))
                    except Exception as e:
                        print(
                            "✗ ERROR fixing and compiling {}: {}".format(
                                lang_code, e))

            except Exception as e:
                print("✗ ERROR compiling {}: {}".format(lang_code, e))

# ===== MAIN =====


def main():
    print("=" * 60)
    print("UPDATING TRANSLATIONS: {}".format(PLUGIN_NAME))
    print("=" * 60)

    # 1. Extract strings
    xml_strings = extract_xml_strings()
    py_strings = extract_python_strings()

    # Continue even if no XML strings found
    if not py_strings:
        print("No Python strings found! Nothing to update.")
        return

    # 2. Update .pot
    total = update_pot_file(xml_strings, py_strings)

    if total == 0:
        print("ERROR: Failed to create .pot file")
        return

    # 3. Update existing .po files and create missing ones
    update_po_files()

    # 4. Compile .mo files
    compile_mo_files()

    print("\n" + "=" * 60)
    print("COMPLETED: {} strings in the catalog".format(total))
    print("Languages processed: {}".format(len(STANDARD_LANGUAGES)))
    print("=" * 60)


if __name__ == "__main__":
    main()
