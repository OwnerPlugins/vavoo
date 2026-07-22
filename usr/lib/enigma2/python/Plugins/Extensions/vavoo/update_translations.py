#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
##############################################################################
Generic Translation Management Script for Enigma2 Plugins
Created by: Lululla
Integrates Google Translate auto-translation for missing strings
##############################################################################
Last Updated: 2026-05-27
##############################################################################
"""
from os import makedirs, walk, remove, listdir, environ
from os.path import dirname, abspath, basename, join, exists, isdir
import re
import subprocess
import hashlib
import json
import time
import socket
from xml.etree import ElementTree as ET
from json import loads
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# ============================================================
# PLUGIN CONFIGURATION (auto-detected from folder name or __init__.py)
# ============================================================
PLUGIN_DIR = dirname(abspath(__file__))
PLUGIN_NAME = basename(PLUGIN_DIR)  # fallback


# Try to read PluginLanguageDomain from __init__.py
init_file = join(PLUGIN_DIR, "__init__.py")
if exists(init_file):
    try:
        with open(init_file, 'r', encoding='utf-8') as f:
            content = f.read()
        match = re.search(
            r'^PluginLanguageDomain\s*=\s*["\']([^"\']+)["\']',
            content, re.MULTILINE
        )
        if match:
            PLUGIN_NAME = match.group(1)
            print(
                "Detected PluginLanguageDomain = '{}' from __init__.py".format(PLUGIN_NAME))
        else:
            print("PluginLanguageDomain not found in __init__.py, using folder name: {}".format(
                PLUGIN_NAME))
    except Exception as e:
        print(
            "Warning: could not read __init__.py: {}, using folder name: {}".format(
                e, PLUGIN_NAME))
else:
    print("__init__.py not found, using folder name: {}".format(PLUGIN_NAME))

LOCALE_DIR = join(PLUGIN_DIR, "locale")
POT_FILE = join(LOCALE_DIR, "{}.pot".format(PLUGIN_NAME))

# ============================================================
# GOOGLE TRANSLATE MODULE CONFIGURATION
# ============================================================
TRANSLATE_API_URL = "https://translate.googleapis.com/translate_a/single"
REQUEST_TIMEOUT = 8
MAX_CHARS_PER_REQUEST = 2000
CACHE_FILE = join(PLUGIN_DIR, "translation_cache.json")
ENABLE_LOGGING = True
DEBUG = True   # Set to False to reduce output

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'gzip, deflate',
    'Connection': 'keep-alive',
}


# ============================================================
# TRANSLATION CACHE
# ============================================================
_translation_cache = {}
_cache_hits = 0
_cache_misses = 0
_cache_dirty = False


# ============================================================
# UTILITY FUNCTIONS FOR TRANSLATION
# ============================================================


def _log(message):
    if ENABLE_LOGGING and DEBUG:
        timestamp = time.time()
        print("[Translate][{:.2f}] {}".format(timestamp, message))


def _get_system_language():
    """Return system language (for Enigma2 or environment variable)"""
    try:
        from Components.config import config
        lang = config.misc.language.value
        return lang.split('_')[0].lower()
    except ImportError:
        lang = environ.get('LANG', 'en_US.UTF-8').split('.')[0]
        return lang.split('_')[0].lower()
    except Exception:
        return 'en'


def _to_unicode(text):
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    if isinstance(text, bytes):
        try:
            return text.decode("utf-8", errors="ignore")
        except Exception:
            return str(text, errors="ignore")
    try:
        return str(text)
    except Exception:
        return ""


def _clean_whitespace(text):
    text_unicode = _to_unicode(text)
    while "  " in text_unicode:
        text_unicode = text_unicode.replace("  ", " ")
    return text_unicode.strip()


def _is_arabic_char(char):
    try:
        code = ord(char)
        return (
            0x0600 <= code <= 0x06FF or
            0x0750 <= code <= 0x077F or
            0x08A0 <= code <= 0x08FF or
            0xFB50 <= code <= 0xFDFF or
            0xFE70 <= code <= 0xFEFF
        )
    except Exception:
        return False


def _is_text_arabic(text):
    text_unicode = _to_unicode(text)
    if not text_unicode:
        return False
    total_letters = 0
    arabic_letters = 0
    for char in text_unicode:
        if char.isalpha():
            total_letters += 1
            if _is_arabic_char(char):
                arabic_letters += 1
    if total_letters == 0:
        return False
    return (float(arabic_letters) / float(total_letters)) >= 0.6


def _get_cache_key(text, target_lang):
    key_string = "{}:{}".format(target_lang, text).encode('utf-8')
    return hashlib.md5(key_string).hexdigest()


def _cache_translation(text, target_lang, translated):
    global _cache_dirty
    cache_key = _get_cache_key(text, target_lang)
    _translation_cache[cache_key] = translated
    _cache_dirty = True
    save_cache_to_disk()
    return translated


def _get_cached_translation(text, target_lang):
    global _cache_hits, _cache_misses
    cache_key = _get_cache_key(text, target_lang)
    if cache_key in _translation_cache:
        _cache_hits += 1
        return _translation_cache[cache_key]
    _cache_misses += 1
    return None


def save_cache_to_disk():
    global _cache_dirty
    if not _cache_dirty:
        return
    try:
        cache_dir = dirname(CACHE_FILE)
        if not exists(cache_dir):
            makedirs(cache_dir, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_translation_cache, f, ensure_ascii=False, indent=2)
        _log("Cache saved ({} entries)".format(len(_translation_cache)))
        _cache_dirty = False
    except Exception as e:
        _log("Error saving cache: {}".format(e))


def load_cache_from_disk():
    global _translation_cache
    if exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                _translation_cache = json.load(f)
            _log("Cache loaded ({} entries)".format(len(_translation_cache)))
        except Exception as e:
            _log("Error loading cache: {}".format(e))
            _translation_cache = {}
    else:
        _translation_cache = {}


def translate_text(text, target_lang=None, use_cache=True):
    """Translate a text using Google Translate API"""
    if not text:
        return ""
    text_unicode = _to_unicode(text)
    if target_lang is None:
        target_lang = _get_system_language()
    target_lang = target_lang.lower()

    if _is_text_arabic(text_unicode):
        _log("Arabic text detected, not translated: '{}...'".format(
            text_unicode[:30]))
        return text_unicode
    if use_cache:
        cached = _get_cached_translation(text_unicode, target_lang)
        if cached is not None:
            return cached
    if len(text_unicode) > MAX_CHARS_PER_REQUEST:
        _log("Text too long ({} chars), truncated to {}".format(
            len(text_unicode), MAX_CHARS_PER_REQUEST))
        text_unicode = text_unicode[:MAX_CHARS_PER_REQUEST]
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target_lang,
        "dt": "t",
        "q": text_unicode,
    }
    try:
        query_string = urlencode(params)
        url = "{}?{}".format(TRANSLATE_API_URL, query_string)
        req = Request(url)
        for key, value in HEADERS.items():
            req.add_header(key, value)
        socket.setdefaulttimeout(REQUEST_TIMEOUT)
        response = urlopen(req, timeout=REQUEST_TIMEOUT)
        raw_data = response.read()
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode('utf-8')
        data = loads(raw_data)
        translated_text = ""
        if isinstance(data, list) and data:
            for item in data[0]:
                if item and isinstance(item, list) and item[0]:
                    translated_text += item[0]
        if translated_text:
            translated_text = _clean_whitespace(translated_text)
            if use_cache:
                _cache_translation(text_unicode, target_lang, translated_text)
            return translated_text
        else:
            _log("Empty API response for: '{}...'".format(text_unicode[:30]))
            return text_unicode
    except Exception as e:
        _log("Translation error: {}".format(str(e)))
        return text_unicode
    finally:
        socket.setdefaulttimeout(None)


def auto_translate_po_file(po_file, target_lang):
    """Automatically translate empty msgstr entries in a .po file"""
    if not exists(po_file):
        return False
    with open(po_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    new_lines = []
    msgid = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('msgid "'):
            msgid = line.split('msgid "')[1].rstrip('"\n')
            new_lines.append(line)
            i += 1
            while i < len(lines) and not lines[i].startswith('msgstr "'):
                new_lines.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].startswith('msgstr "'):
                msgstr_line = lines[i]
                msgstr_content = msgstr_line.split('msgstr "')[1].rstrip('"\n')
                if not msgstr_content.strip():
                    translated = translate_text(msgid, target_lang)
                    if translated and translated != msgid:
                        msgstr_line = 'msgstr "{}"\n'.format(translated)
                        print("  [auto-translated] {}... -> {}...".format(
                            msgid[:40], translated[:40]))
                new_lines.append(msgstr_line)
                i += 1
        else:
            new_lines.append(line)
            i += 1
    with open(po_file, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    return True


def ensure_directory_structure(lang_code):
    lang_dir = join(LOCALE_DIR, lang_code)
    lc_messages_dir = join(lang_dir, "LC_MESSAGES")
    try:
        if not exists(lc_messages_dir):
            makedirs(lc_messages_dir, exist_ok=True)
            print("  Created directory structure for: {}".format(lang_code))
        return lc_messages_dir
    except Exception as e:
        print("  ERROR creating directories for {}: {}".format(lang_code, e))
        return None


def extract_xml_strings():
    xml_file = join(PLUGIN_DIR, "setup.xml")
    if not exists(xml_file):
        print("INFO: {} not found! Skipping XML extraction.".format(xml_file))
        return []
    strings = []
    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        for elem in root.findall('.//*[@text]'):
            text = elem.get('text', '').strip()
            if text and not re.match(r'^#[0-9a-fA-F]{6,8}$', text):
                strings.append(text)
        for elem in root.findall('.//*[@description]'):
            desc = elem.get('description', '').strip()
            if desc and not re.match(r'^#[0-9a-fA-F]{6,8}$', desc):
                strings.append(desc)
        for elem in root.findall('.//*[@title]'):
            title = elem.get('title', '').strip()
            if title:
                strings.append(title)
    except Exception as e:
        print("ERROR parsing XML: {}".format(e))
        return []
    seen = set()
    unique = []
    for s in strings:
        if s and s.strip() and s.strip() not in seen:
            seen.add(s.strip())
            unique.append(s.strip())
    print("XML: found {} unique strings".format(len(unique)))
    return clean_strings(unique)


def clean_strings(strings):
    cleaned = []
    for s in strings:
        if not s or not s.strip():
            continue
        s = s.strip()
        if s in [
            '{0}', '{1}', '{2}', '{3}', '{4}',
            '{5}', '{6}', '{7}', '{8}', '{9}'
        ]:
            continue
        if re.match(r'^[0-9\s\W]+$', s):
            continue
        cleaned.append(s)
    return cleaned


def extract_python_strings():
    py_strings = []
    try:
        temp_pot = join(PLUGIN_DIR, "temp_python.pot")
        py_files = []
        for root_dir, _, files in walk(PLUGIN_DIR):
            for f in files:
                if f.endswith('.py') and not f.startswith(
                        'test_') and f != 'update_translations.py':
                    py_files.append(join(root_dir, f))
        if not py_files:
            print("No .py files found")
            return []
        cmd = [
            'xgettext',
            '--no-wrap',
            '-L',
            'Python',
            '--from-code=UTF-8',
            '-kpgettext:1c,2',
            '--add-comments=TRANSLATORS:',
            '-d',
            PLUGIN_NAME,
            '-s',
            '-o',
            temp_pot] + py_files
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _, stderr = process.communicate()
            if process.returncode != 0:
                print("ERROR xgettext: {}".format(stderr))
                return []
        except OSError as e:
            print("ERROR running xgettext: {}".format(e))
            return []
        if exists(temp_pot):
            with open(temp_pot, 'r') as f:
                content = f.read()
            for match in re.finditer(r'msgid "([^"]+)"', content):
                text = match.group(1)
                if text and text.strip():
                    py_strings.append(text.strip())
            try:
                remove(temp_pot)
            except Exception:
                pass
        print("Python: found {} strings".format(len(py_strings)))
        return clean_strings(py_strings)
    except Exception as e:
        print("ERROR extracting Python strings: {}".format(e))
        return []


def update_pot_file(xml_strings, py_strings):
    try:
        makedirs(LOCALE_DIR, exist_ok=True)
    except Exception:
        pass
    all_strings = list(set(xml_strings + py_strings))
    filtered_strings = []
    for s in all_strings:
        if s.startswith(' ') or s.endswith(' '):
            s = s.strip()
        if s and s not in filtered_strings:
            filtered_strings.append(s)
    filtered_strings.sort()
    all_strings = filtered_strings
    print("TOTAL: {} unique strings".format(len(all_strings)))
    existing_translations = {}
    pot_header = ""
    if exists(POT_FILE):
        try:
            with open(POT_FILE, 'r') as f:
                content = f.read()
            parts = content.split('msgid "')
            if len(parts) > 1:
                pot_header = parts[0]
            for match in re.finditer(
                r'msgid "([^"]+)"\s*\nmsgstr "([^"]*)"',
                content, re.DOTALL
            ):
                existing_translations[match.group(1)] = match.group(2)
        except Exception:
            pass
    with open(POT_FILE, 'w') as f:
        if pot_header:
            f.write(pot_header)
        else:
            f.write('# {} translations\n'.format(PLUGIN_NAME))
            f.write('# Copyright (C) 2025 Lululla & Qu4k3 Team\n')
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
        for msgid in all_strings:
            msgstr_value = existing_translations.get(msgid, "")
            f.write('\nmsgid "{}"\nmsgstr "{}"\n'.format(msgid, msgstr_value))
    print("Updated .pot file: {}".format(POT_FILE))
    return len(all_strings)


def fix_po_file(po_file):
    try:
        with open(po_file, 'r') as f:
            lines = f.readlines()
        fixed_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if line.strip() == 'msgid ""' and i + \
                    1 < len(lines) and lines[i + 1].strip() == 'msgstr ""':
                if not any(ls.strip().startswith('"Project-Id-Version:')
                           for ls in fixed_lines):
                    fixed_lines.append(line)
                    fixed_lines.append(lines[i + 1])
                    i += 2
                    while i < len(lines) and lines[i].strip().startswith('"'):
                        fixed_lines.append(lines[i])
                        i += 1
                    continue
                else:
                    # Duplicate header block: skip its msgid/msgstr AND
                    # all its quoted continuation lines too, or those
                    # would fall through below as orphaned top-level
                    # strings attached to no msgid/msgstr (invalid PO).
                    i += 2
                    while i < len(lines) and lines[i].strip().startswith('"'):
                        i += 1
                    continue
            if line.strip().startswith('msgid "') and '""' in line:
                fixed_lines.append('msgid ""\n')
                i += 1
                continue
            fixed_lines.append(line)
            i += 1
        seen_msgids = set()
        cleaned_lines = []
        i = 0
        while i < len(fixed_lines):
            if fixed_lines[i].strip().startswith('msgid "'):
                msgid_line = fixed_lines[i]
                if msgid_line in seen_msgids:
                    i += 1
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
        with open(po_file, 'w') as f:
            f.writelines(cleaned_lines)
        return True
    except Exception as e:
        print("ERROR fixing {}: {}".format(po_file, e))
        return False


STANDARD_LANGUAGES = [
    'af', 'am', 'ar', 'az', 'be', 'bg', 'bn', 'bs', 'ca', 'cs', 'cy', 'da',
    'de', 'el', 'en', 'en_GB', 'eo', 'es', 'et', 'eu', 'fa', 'fi', 'fr', 'fy',
    'ga', 'gd', 'gl', 'gu', 'he', 'hi', 'hr', 'hu', 'hy', 'id', 'is', 'it',
    'ja', 'ka', 'kk', 'km', 'kn', 'ko', 'ku', 'ky', 'lt', 'lv', 'mk', 'ml',
    'mn', 'mr', 'ms', 'mt', 'my', 'nb', 'ne', 'nl', 'no', 'oc', 'or', 'pa',
    'pl', 'ps', 'pt', 'pt_BR', 'pt_PT', 'ro', 'ru', 'si', 'sk', 'sl', 'sq',
    'sq_AL', 'sr', 'sr_Latn', 'sv', 'sw', 'ta', 'te', 'tg', 'th', 'tk', 'tl',
    'tr', 'tt', 'ug', 'uk', 'ur', 'uz', 'vi', 'yi', 'zh', 'zh_CN', 'zh_HK',
    'zh_SG', 'zh_TW'
]


def create_template_po_file(po_file, lang_code):
    try:
        with open(POT_FILE, 'r', encoding='utf-8') as f:
            pot_content = f.read()
        msgid_blocks = re.findall(
            r'msgid "([^"]+)"\s*\nmsgstr ""\s*\n', pot_content, re.DOTALL
        )
        with open(po_file, 'w', encoding='utf-8') as f:
            f.write('# {} translations\n'.format(PLUGIN_NAME))
            f.write('# Copyright (C) 2025 Lululla Team\n')
            f.write(
                '# This file is distributed under the same license as the Lululla package.\n')
            f.write('# [lululla] <ekekaz@gmail.com>, 2025.\n')
            f.write('#\n')
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
            for msgid in msgid_blocks:
                f.write('msgid "{}"\n'.format(msgid))
                f.write('msgstr ""\n\n')
        print(" ✓ Created clean template for: {}".format(lang_code))
        return True
    except Exception as e:
        print(" ✗ ERROR creating template for {}: {}".format(lang_code, e))
        return False


def update_po_files():
    if not exists(POT_FILE):
        print("ERROR: .pot file not found")
        return
    existing_languages = []
    if exists(LOCALE_DIR):
        for item in listdir(LOCALE_DIR):
            item_path = join(LOCALE_DIR, item)
            if isdir(item_path) and item != 'templates':
                po_file = join(
                    item_path,
                    "LC_MESSAGES",
                    "{}.po".format(PLUGIN_NAME))
                if exists(po_file):
                    existing_languages.append(item)
    all_languages = list(set(existing_languages + STANDARD_LANGUAGES))
    all_languages.sort()
    print(
        "Processing {} languages: {}".format(
            len(all_languages),
            ', '.join(all_languages)))
    for lang_code in all_languages:
        lc_messages_dir = ensure_directory_structure(lang_code)
        if not lc_messages_dir:
            continue
        po_file = join(lc_messages_dir, "{}.po".format(PLUGIN_NAME))
        if exists(po_file):
            print("Updating: {}".format(lang_code))
            fix_po_file(po_file)
            cmd = [
                'msgmerge',
                '--update',
                '--backup=none',
                '--no-wrap',
                po_file,
                POT_FILE]
            try:
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                process.communicate()
                if process.returncode == 0:
                    fix_po_file(po_file)
                    print(" ✓ {} updated".format(lang_code))
                    auto_translate_po_file(po_file, lang_code)
                else:
                    print("  First merge failed, fixing and retrying...")
                    if fix_po_file(po_file):
                        process = subprocess.Popen(
                            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                        process.communicate()
                        if process.returncode == 0:
                            print(" ✓ {} updated after fix".format(lang_code))
                            auto_translate_po_file(po_file, lang_code)
                        else:
                            print(
                                " ✗ ERROR updating {} after fix".format(lang_code))
            except Exception as e:
                print(" ✗ ERROR updating {}: {}".format(lang_code, e))
        else:
            print("Creating new: {}".format(lang_code))
            lang_code_hyphen = lang_code.replace('_', '-')
            cmd = [
                'msginit',
                '--no-wrap',
                '-i',
                POT_FILE,
                '-o',
                po_file,
                '-l',
                lang_code_hyphen]
            try:
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                process.communicate()
                if process.returncode == 0:
                    print(" ✓ Created new file for: {}".format(lang_code))
                    fix_po_file(po_file)
                    auto_translate_po_file(po_file, lang_code)
                else:
                    print("  msginit failed, creating template manually...")
                    create_template_po_file(po_file, lang_code)
                    auto_translate_po_file(po_file, lang_code)
            except Exception as e:
                print(" ✗ ERROR creating file for {}: {}".format(lang_code, e))


def compile_mo_files():
    if not exists(LOCALE_DIR):
        print("No locale directory found")
        return
    for lang_code in listdir(LOCALE_DIR):
        lc_messages_dir = join(LOCALE_DIR, lang_code, "LC_MESSAGES")
        po_file = join(lc_messages_dir, "{}.po".format(PLUGIN_NAME))
        mo_file = join(lc_messages_dir, "{}.mo".format(PLUGIN_NAME))
        if exists(po_file):
            try:
                fix_po_file(po_file)
                cmd = ['msgfmt', po_file, '-o', mo_file]
                process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                process.communicate()
                if process.returncode == 0:
                    print(
                        "✓ Compiled: {}/LC_MESSAGES/{}.mo".format(lang_code, PLUGIN_NAME))
                else:
                    print("✗ ERROR compiling {}".format(lang_code))
            except Exception as e:
                print("✗ ERROR compiling {}: {}".format(lang_code, e))


def main():
    print("=" * 60)
    print("UPDATING TRANSLATIONS: {}".format(PLUGIN_NAME))
    print("=" * 60)

    load_cache_from_disk()

    xml_strings = extract_xml_strings()
    py_strings = extract_python_strings()
    if not py_strings:
        print("No Python strings found! Nothing to update.")
        return
    total = update_pot_file(xml_strings, py_strings)
    if total == 0:
        print("ERROR: Failed to create .pot file")
        return
    update_po_files()
    compile_mo_files()

    save_cache_to_disk()

    print("\n" + "=" * 60)
    print("COMPLETED: {} strings in the catalog".format(total))
    print("Languages processed: {}".format(len(STANDARD_LANGUAGES)))
    print("=" * 60)


if __name__ == "__main__":
    main()
