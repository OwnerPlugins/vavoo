#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
##############################################################################
Generic Translation Management Script for Enigma2 Plugins
Created by: Lululla
Google Translate auto-translation for missing strings.
Includes request throttling, HTTP 429 handling, retries and persistent cache.
##############################################################################
"""

from os import makedirs, walk, remove, listdir, environ
from os.path import dirname, abspath, basename, join, exists, isdir
import ast
import json
import hashlib
import random
import re
import subprocess
import time
from xml.etree import ElementTree as ET
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ============================================================
# PLUGIN CONFIGURATION
# ============================================================

PLUGIN_DIR = dirname(abspath(__file__))
PLUGIN_NAME = basename(PLUGIN_DIR)

init_file = join(PLUGIN_DIR, "__init__.py")
if exists(init_file):
    try:
        with open(init_file, "r", encoding="utf-8") as f:
            content = f.read()
        match = re.search(
            r"""^PluginLanguageDomain\s*=\s*["']([^"']+)["']""",
            content,
            re.MULTILINE,
        )
        if match:
            PLUGIN_NAME = match.group(1)
            print("Detected PluginLanguageDomain = '{}'".format(PLUGIN_NAME))
        else:
            print(
                "__init__.py has no PluginLanguageDomain; using '{}'".format(PLUGIN_NAME))
    except Exception as exc:
        print(
            "Warning reading __init__.py: {}; using '{}'".format(
                exc, PLUGIN_NAME))
else:
    print("__init__.py not found; using folder name '{}'".format(PLUGIN_NAME))

LOCALE_DIR = join(PLUGIN_DIR, "locale")
POT_FILE = join(LOCALE_DIR, "{}.pot".format(PLUGIN_NAME))


# ============================================================
# GOOGLE TRANSLATE CONFIGURATION
# ============================================================

TRANSLATE_API_URL = "https://translate.googleapis.com/translate_a/single"
REQUEST_TIMEOUT = int(environ.get("TRANSLATE_TIMEOUT", "15"))
MAX_CHARS_PER_REQUEST = 2000
MIN_REQUEST_INTERVAL = float(environ.get("TRANSLATE_MIN_INTERVAL", "2.0"))
MAX_RETRIES = int(environ.get("TRANSLATE_MAX_RETRIES", "5"))
RETRY_BACKOFF_BASE = float(environ.get("TRANSLATE_BACKOFF_BASE", "5"))
MAX_RETRY_WAIT = float(environ.get("TRANSLATE_MAX_RETRY_WAIT", "120"))
CACHE_SAVE_EVERY = int(environ.get("TRANSLATE_CACHE_SAVE_EVERY", "20"))

CACHE_FILE = join(PLUGIN_DIR, "translation_cache.json")
ENABLE_LOGGING = True
DEBUG = True

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.5",
}


# ============================================================
# CACHE AND RATE LIMIT STATE
# ============================================================

_translation_cache = {}
_cache_hits = 0
_cache_misses = 0
_cache_dirty = False
_cache_pending = 0
_last_request_time = 0.0


def _log(message):
    if ENABLE_LOGGING and DEBUG:
        print("[Translate][{}] {}".format(time.strftime("%H:%M:%S"), message))


def _get_system_language():
    try:
        from Components.config import config
        return config.misc.language.value.split("_")[0].lower()
    except Exception:
        lang = environ.get("LANG", "en_US.UTF-8").split(".")[0]
        return lang.split("_")[0].lower()


def _to_unicode(text):
    if text is None:
        return ""
    if isinstance(text, str):
        return text
    if isinstance(text, bytes):
        return text.decode("utf-8", errors="replace")
    return str(text)


def _clean_whitespace(text):
    return re.sub(r"[ \t]+", " ", _to_unicode(text)).strip()


def _is_arabic_char(char):
    code = ord(char)
    return (
        0x0600 <= code <= 0x06FF
        or 0x0750 <= code <= 0x077F
        or 0x08A0 <= code <= 0x08FF
        or 0xFB50 <= code <= 0xFDFF
        or 0xFE70 <= code <= 0xFEFF
    )


def _is_text_arabic(text):
    letters = [c for c in _to_unicode(text) if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if _is_arabic_char(c)) / \
        float(len(letters)) >= 0.6


def _get_cache_key(text, target_lang):
    raw = "{}:{}".format(target_lang.lower(), text).encode("utf-8")
    return hashlib.md5(raw).hexdigest()


def _cache_translation(text, target_lang, translated):
    global _cache_dirty, _cache_pending
    _translation_cache[_get_cache_key(text, target_lang)] = translated
    _cache_dirty = True
    _cache_pending += 1
    if _cache_pending >= max(1, CACHE_SAVE_EVERY):
        save_cache_to_disk()
    return translated


def _get_cached_translation(text, target_lang):
    global _cache_hits, _cache_misses
    key = _get_cache_key(text, target_lang)
    if key in _translation_cache:
        _cache_hits += 1
        return _translation_cache[key]
    _cache_misses += 1
    return None


def save_cache_to_disk():
    global _cache_dirty, _cache_pending
    if not _cache_dirty:
        return
    try:
        makedirs(dirname(CACHE_FILE), exist_ok=True)
        temporary_file = CACHE_FILE + ".tmp"
        with open(temporary_file, "w", encoding="utf-8") as f:
            json.dump(_translation_cache, f, ensure_ascii=False, indent=2)
        # Atomic replacement avoids leaving a partially written cache.
        import os
        os.replace(temporary_file, CACHE_FILE)
        _cache_dirty = False
        _cache_pending = 0
        _log("Cache saved ({} entries)".format(len(_translation_cache)))
    except Exception as exc:
        _log("Error saving cache: {}".format(exc))


def load_cache_from_disk():
    global _translation_cache
    if not exists(CACHE_FILE):
        _translation_cache = {}
        return
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        _translation_cache = loaded if isinstance(loaded, dict) else {}
        _log("Cache loaded ({} entries)".format(len(_translation_cache)))
    except Exception as exc:
        _log("Error loading cache: {}".format(exc))
        _translation_cache = {}


# ============================================================
# PLACEHOLDER PROTECTION
# ============================================================

def _protect_placeholders(text):
    if not text:
        return text, {}, {}

    python_placeholders = {}
    csharp_placeholders = {}
    protected = text

    python_regex = re.compile(r"%\([a-zA-Z_][a-zA-Z0-9_]*\)[diouxXeEfFgGcrs]")
    matches = list(python_regex.finditer(protected))
    for index, match in enumerate(reversed(matches)):
        placeholder = match.group(0)
        token = "__PYPH_{}__".format(len(matches) - index - 1)
        start, end = match.span()
        protected = protected[:start] + token + protected[end:]
        python_placeholders[token] = placeholder

    csharp_regex = re.compile(r"\{[^{}]+\}")
    matches = list(csharp_regex.finditer(protected))
    for index, match in enumerate(reversed(matches)):
        placeholder = match.group(0)
        token = "__CSH_{}__".format(len(matches) - index - 1)
        start, end = match.span()
        protected = protected[:start] + token + protected[end:]
        csharp_placeholders[token] = placeholder

    return protected, python_placeholders, csharp_placeholders


def _restore_placeholders(text, python_placeholders, csharp_placeholders):
    if not text:
        return text
    for token, value in csharp_placeholders.items():
        text = text.replace(token, value)
    for token, value in python_placeholders.items():
        text = text.replace(token, value)
    return text


# ============================================================
# RATE LIMITING AND TRANSLATION
# ============================================================

def _wait_for_rate_limit():
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    wait_for = MIN_REQUEST_INTERVAL - elapsed
    if wait_for > 0:
        time.sleep(wait_for)
    _last_request_time = time.monotonic()


def _retry_delay(error, attempt):
    delay = min(RETRY_BACKOFF_BASE * (2 ** attempt), MAX_RETRY_WAIT)
    try:
        retry_after = error.headers.get("Retry-After")
        if retry_after:
            delay = max(delay, float(retry_after))
    except (AttributeError, TypeError, ValueError):
        pass
    return min(delay + random.uniform(0, min(1.0, delay * 0.1)), MAX_RETRY_WAIT)


def translate_text(text, target_lang=None, use_cache=True):
    """Translate text; retry temporary failures and throttle API requests."""
    if not text:
        return ""

    original_text = _to_unicode(text)
    target_lang = (target_lang or _get_system_language()).lower()

    if _is_text_arabic(original_text):
        _log("Arabic source text skipped")
        return original_text

    protected_text, python_placeholders, csharp_placeholders = _protect_placeholders(
        original_text)

    if use_cache:
        cached = _get_cached_translation(protected_text, target_lang)
        if cached is not None:
            return _restore_placeholders(
                cached, python_placeholders, csharp_placeholders)

    # Do not silently truncate: that would permanently cache an incomplete
    # translation.
    if len(protected_text) > MAX_CHARS_PER_REQUEST:
        _log("Text exceeds {} characters; leaving it untranslated".format(
            MAX_CHARS_PER_REQUEST))
        return original_text

    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": target_lang,
        "dt": "t",
        "q": protected_text,
    }
    url = "{}?{}".format(TRANSLATE_API_URL, urlencode(params))
    request = Request(url, headers=HEADERS)

    for attempt in range(MAX_RETRIES + 1):
        try:
            _wait_for_rate_limit()
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                raw_data = response.read().decode("utf-8")
            data = json.loads(raw_data)

            translated = ""
            if isinstance(data, list) and data and isinstance(data[0], list):
                translated = "".join(
                    item[0] for item in data[0]
                    if isinstance(item, list) and item and item[0]
                )

            if not translated:
                _log("Empty translation response for '{}'".format(
                    original_text[:40]))
                return original_text

            translated = _clean_whitespace(translated)

            # Cache the protected form. Placeholders are restored only on
            # return.
            if use_cache:
                _cache_translation(protected_text, target_lang, translated)

            return _restore_placeholders(
                translated, python_placeholders, csharp_placeholders)

        except HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < MAX_RETRIES:
                delay = _retry_delay(exc, attempt)
                _log("HTTP {}: retry {}/{} in {:.1f}s".format(
                    exc.code, attempt + 1, MAX_RETRIES, delay
                ))
                time.sleep(delay)
                continue
            _log("HTTP error {}: {}".format(exc.code, exc.reason))
            return original_text

        except (URLError, TimeoutError, OSError) as exc:
            if attempt < MAX_RETRIES:
                delay = min(RETRY_BACKOFF_BASE *
                            (2 ** attempt), MAX_RETRY_WAIT)
                _log("Connection error: retry {}/{} in {:.1f}s ({})".format(
                    attempt + 1, MAX_RETRIES, delay, exc
                ))
                time.sleep(delay)
                continue
            _log("Connection failed after retries: {}".format(exc))
            return original_text

        except (ValueError, TypeError, IndexError) as exc:
            _log("Invalid translation response: {}".format(exc))
            return original_text
        except Exception as exc:
            _log("Translation error: {}".format(exc))
            return original_text

    return original_text


# ============================================================
# GETTEXT PO FILE PARSING
# ============================================================

def _parse_po_entries(text):
    """Parse gettext entries, including escaped and multiline msgid/msgstr."""
    entries = []
    current = []
    for line in text.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = []
        else:
            current.append(line)
    if current:
        entries.append(current)
    return entries


def _read_po_field(lines, field_name):
    """Return (decoded value, next index) for a PO field."""
    prefix = field_name + " "
    index = next((i for i, line in enumerate(lines)
                 if line.startswith(prefix)), None)
    if index is None:
        return None, None

    value_parts = []
    try:
        value_parts.append(ast.literal_eval(lines[index][len(prefix):]))
        i = index + 1
        while i < len(lines) and lines[i].startswith('"'):
            value_parts.append(ast.literal_eval(lines[i]))
            i += 1
        return "".join(value_parts), i
    except (SyntaxError, ValueError):
        return None, None


def _replace_po_field(lines, field_name, new_value):
    """Replace a field and its continuation lines, retaining other entry data."""
    prefix = field_name + " "
    index = next((i for i, line in enumerate(lines)
                 if line.startswith(prefix)), None)
    if index is None:
        return lines

    end = index + 1
    while end < len(lines) and lines[end].startswith('"'):
        end += 1

    encoded = json.dumps(new_value, ensure_ascii=False)
    return lines[:index] + [prefix + encoded] + lines[end:]


def auto_translate_po_file(po_file, target_lang):
    """Translate empty singular msgstr entries without damaging multiline PO data."""
    if not exists(po_file):
        return False

    try:
        with open(po_file, "r", encoding="utf-8") as f:
            original = f.read()
    except Exception as exc:
        print("ERROR reading {}: {}".format(po_file, exc))
        return False

    entries = _parse_po_entries(original)
    output_entries = []
    translated_count = 0

    for lines in entries:
        msgid, _ = _read_po_field(lines, "msgid")
        msgstr, _ = _read_po_field(lines, "msgstr")

        # Keep headers, plural entries, comments and already translated entries
        # intact.
        if msgid is None or msgstr is None or msgid == "" or msgstr.strip():
            output_entries.append(lines)
            continue
        if any(
            line.startswith("msgid_plural ") or re.match(
                r"msgstr\[\d+\]",
                line) for line in lines):
            output_entries.append(lines)
            continue

        translated = translate_text(msgid, target_lang)
        if translated and translated != msgid:
            lines = _replace_po_field(lines, "msgstr", translated)
            translated_count += 1
            print("  [auto-translated] {}...".format(msgid[:60]))

        output_entries.append(lines)

    try:
        with open(po_file, "w", encoding="utf-8") as f:
            f.write("\n\n".join("\n".join(entry)
                    for entry in output_entries) + "\n")
        print(
            "  {}: {} new translations".format(
                target_lang,
                translated_count))
        return True
    except Exception as exc:
        print("ERROR writing {}: {}".format(po_file, exc))
        return False


def ensure_directory_structure(lang_code):
    lc_messages_dir = join(LOCALE_DIR, lang_code, "LC_MESSAGES")
    try:
        makedirs(lc_messages_dir, exist_ok=True)
        return lc_messages_dir
    except Exception as exc:
        print("ERROR creating directories for {}: {}".format(lang_code, exc))
        return None


# ============================================================
# STRING EXTRACTION
# ============================================================

def clean_strings(strings):
    cleaned = []
    seen = set()
    for value in strings:
        if not value:
            continue
        value = value.strip()
        if not value or value in seen:
            continue
        if value in {
            "{0}",
            "{1}",
            "{2}",
            "{3}",
            "{4}",
            "{5}",
            "{6}",
            "{7}",
            "{8}",
                "{9}"}:
            continue
        if re.match(r"^[0-9\s\W]+$", value):
            continue
        seen.add(value)
        cleaned.append(value)
    return cleaned


def extract_xml_strings():
    xml_file = join(PLUGIN_DIR, "setup.xml")
    if not exists(xml_file):
        print("INFO: setup.xml not found; skipping XML extraction.")
        return []

    strings = []
    try:
        root = ET.parse(xml_file).getroot()
        for attribute in ("text", "description", "title"):
            for elem in root.findall(".//*[@{}]".format(attribute)):
                value = (elem.get(attribute) or "").strip()
                if value and not re.match(r"^#[0-9a-fA-F]{6,8}$", value):
                    strings.append(value)
    except Exception as exc:
        print("ERROR parsing XML: {}".format(exc))
        return []

    result = clean_strings(strings)
    print("XML: found {} unique strings".format(len(result)))
    return result


def extract_python_strings():
    py_files = []
    for root_dir, _, files in walk(PLUGIN_DIR):
        # Do not scan generated locale/build/cache directories.
        if any(part in root_dir.split("/")
               for part in (".git", "venv", "__pycache__")):
            continue
        for filename in files:
            if filename.endswith(".py") and not filename.startswith(
                    "test_") and filename != "update_translations.py":
                py_files.append(join(root_dir, filename))

    if not py_files:
        print("No Python files found")
        return []

    temp_pot = join(PLUGIN_DIR, "temp_python.pot")
    cmd = [
        "xgettext", "--no-wrap", "-L", "Python", "--from-code=UTF-8",
        "-kpgettext:1c,2", "--add-comments=TRANSLATORS:",
        "-d", PLUGIN_NAME, "-s", "-o", temp_pot,
    ] + py_files

    try:
        process = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True)
        if process.returncode != 0:
            print("ERROR xgettext: {}".format(process.stderr.strip()))
            return []
        strings = []
        if exists(temp_pot):
            with open(temp_pot, "r", encoding="utf-8") as f:
                entries = _parse_po_entries(f.read())
            for entry in entries:
                msgid, _ = _read_po_field(entry, "msgid")
                if msgid:
                    strings.append(msgid)
            remove(temp_pot)
        result = clean_strings(strings)
        print("Python: found {} strings".format(len(result)))
        return result
    except OSError as exc:
        print("ERROR running xgettext: {}".format(exc))
        return []
    except Exception as exc:
        print("ERROR extracting Python strings: {}".format(exc))
        return []


# ============================================================
# POT FILE GENERATION
# ============================================================

def update_pot_file(xml_strings, py_strings):
    makedirs(LOCALE_DIR, exist_ok=True)
    all_strings = sorted(set(clean_strings(xml_strings + py_strings)))
    print("TOTAL: {} unique strings".format(len(all_strings)))

    # Preserve the existing POT header if present.
    header = ""
    if exists(POT_FILE):
        try:
            with open(POT_FILE, "r", encoding="utf-8") as f:
                old_content = f.read()
            old_entries = _parse_po_entries(old_content)
            if old_entries and any(line.startswith('msgid ""')
                                   for line in old_entries[0]):
                header = "\n".join(old_entries[0])
        except Exception:
            pass

    with open(POT_FILE, "w", encoding="utf-8") as f:
        if header:
            f.write(header + "\n\n")
        else:
            f.write("# {} translations\n".format(PLUGIN_NAME))
            f.write("# Copyright (C) 2025 Lululla Team\n")
            f.write(
                "# This file is distributed under the same license as the package.\n")
            f.write('msgid ""\nmsgstr ""\n')
            f.write('"Project-Id-Version: {}\\n"\n'.format(PLUGIN_NAME))
            f.write('"MIME-Version: 1.0\\n"\n')
            f.write('"Content-Type: text/plain; charset=UTF-8\\n"\n')
            f.write('"Content-Transfer-Encoding: 8bit\\n"\n\n')

        for msgid in all_strings:
            f.write("msgid {}\nmsgstr \"\"\n\n".format(
                json.dumps(msgid, ensure_ascii=False)))

    print("Updated .pot file: {}".format(POT_FILE))
    return len(all_strings)


# ============================================================
# PO VALIDATION / LANGUAGE CONFIGURATION
# ============================================================

DEFAULT_KEEP_LANGS = [
    "en", "it", "fr", "de", "es", "pt", "ru", "zh", "ja", "ar",
    "hi", "bn", "id", "tr", "ko", "vi", "pl", "uk", "fa", "th",
]

_env_langs = environ.get("KEEP_LANGS", "").strip()
if _env_langs:
    STANDARD_LANGUAGES = [lang.strip()
                          for lang in _env_langs.split(",") if lang.strip()]
    print(
        "KEEP_LANGS from environment: {}".format(
            ", ".join(STANDARD_LANGUAGES)))
else:
    STANDARD_LANGUAGES = list(DEFAULT_KEEP_LANGS)
    print("Using default languages: {}".format(", ".join(STANDARD_LANGUAGES)))


def fix_po_file(po_file):
    """
    Validate a PO file without rewriting its contents.
    The previous regex-based fixer could corrupt multiline strings and plurals.
    GNU msgfmt is used for validation instead.
    """
    try:
        result = subprocess.run(
            ["msgfmt", "--check", "--check-format", "-o", "/dev/null", po_file],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if result.returncode != 0:
            print(
                "PO validation warning for {}:\n{}".format(
                    po_file, result.stderr.strip()))
            return False
        return True
    except OSError as exc:
        print("ERROR running msgfmt for {}: {}".format(po_file, exc))
        return False


def create_template_po_file(po_file, lang_code):
    try:
        with open(POT_FILE, "r", encoding="utf-8") as f:
            pot_content = f.read()
        entries = _parse_po_entries(pot_content)

        with open(po_file, "w", encoding="utf-8") as f:
            f.write("# {} translations\n".format(PLUGIN_NAME))
            f.write('msgid ""\nmsgstr ""\n')
            f.write('"Project-Id-Version: {}\\n"\n'.format(PLUGIN_NAME))
            f.write('"Language: {}\\n"\n'.format(lang_code))
            f.write('"MIME-Version: 1.0\\n"\n')
            f.write('"Content-Type: text/plain; charset=UTF-8\\n"\n')
            f.write('"Content-Transfer-Encoding: 8bit\\n"\n\n')
            for entry in entries:
                msgid, _ = _read_po_field(entry, "msgid")
                if msgid:
                    f.write(
                        "msgid {}\nmsgstr \"\"\n\n".format(
                            json.dumps(
                                msgid, ensure_ascii=False)))
        return True
    except Exception as exc:
        print("ERROR creating template for {}: {}".format(lang_code, exc))
        return False


def update_po_files():
    if not exists(POT_FILE):
        print("ERROR: POT file not found")
        return

    existing_languages = []
    if exists(LOCALE_DIR):
        for item in listdir(LOCALE_DIR):
            po_file = join(
                LOCALE_DIR,
                item,
                "LC_MESSAGES",
                "{}.po".format(PLUGIN_NAME))
            if isdir(join(LOCALE_DIR, item)) and exists(po_file):
                existing_languages.append(item)

    all_languages = sorted(
        set(existing_languages).intersection(STANDARD_LANGUAGES))
    all_languages.extend(
        lang for lang in STANDARD_LANGUAGES if lang not in all_languages)
    all_languages = sorted(set(all_languages))

    print(
        "Processing {} languages: {}".format(
            len(all_languages),
            ", ".join(all_languages)))

    for lang_code in all_languages:
        lc_messages_dir = ensure_directory_structure(lang_code)
        if not lc_messages_dir:
            continue
        po_file = join(lc_messages_dir, "{}.po".format(PLUGIN_NAME))

        if exists(po_file):
            print("Updating: {}".format(lang_code))
            cmd = [
                "msgmerge",
                "--update",
                "--backup=none",
                "--no-wrap",
                po_file,
                POT_FILE]
            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True)
                if result.returncode != 0:
                    print(
                        "ERROR msgmerge {}: {}".format(
                            lang_code, result.stderr.strip()))
                    continue
                print(" ✓ {} merged".format(lang_code))
            except OSError as exc:
                print(
                    "ERROR running msgmerge for {}: {}".format(
                        lang_code, exc))
                continue
        else:
            print("Creating new: {}".format(lang_code))
            lang_locale = lang_code.replace("_", "-")
            cmd = [
                "msginit",
                "--no-wrap",
                "-i",
                POT_FILE,
                "-o",
                po_file,
                "-l",
                lang_locale]
            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True)
                if result.returncode != 0:
                    print(
                        "msginit failed for {}; creating template".format(lang_code))
                    if not create_template_po_file(po_file, lang_code):
                        continue
            except OSError as exc:
                print("msginit unavailable for {}: {}".format(lang_code, exc))
                if not create_template_po_file(po_file, lang_code):
                    continue

        auto_translate_po_file(po_file, lang_code)


def compile_mo_files():
    if not exists(LOCALE_DIR):
        print("No locale directory found")
        return

    for lang_code in STANDARD_LANGUAGES:
        lc_messages_dir = join(LOCALE_DIR, lang_code, "LC_MESSAGES")
        po_file = join(lc_messages_dir, "{}.po".format(PLUGIN_NAME))
        mo_file = join(lc_messages_dir, "{}.mo".format(PLUGIN_NAME))
        if not exists(po_file):
            continue

        try:
            result = subprocess.run(
                ["msgfmt", "--check", "-o", mo_file, po_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if result.returncode == 0:
                print("✓ Compiled: {}/LC_MESSAGES/{}.mo".format(lang_code, PLUGIN_NAME))
            else:
                print(
                    "✗ ERROR compiling {}: {}".format(
                        lang_code,
                        result.stderr.strip()))
        except OSError as exc:
            print("✗ ERROR compiling {}: {}".format(lang_code, exc))


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("UPDATING TRANSLATIONS: {}".format(PLUGIN_NAME))
    print("=" * 60)

    load_cache_from_disk()

    try:
        xml_strings = extract_xml_strings()
        py_strings = extract_python_strings()

        if not py_strings and not xml_strings:
            print("No strings found. Nothing to update.")
            return

        total = update_pot_file(xml_strings, py_strings)
        if total == 0:
            print("ERROR: no strings available for POT")
            return

        update_po_files()
        compile_mo_files()

    finally:
        save_cache_to_disk()

    print("\n" + "=" * 60)
    print("COMPLETED: {} strings in the catalog".format(
        total if "total" in locals() else 0))
    print("Languages configured: {}".format(len(STANDARD_LANGUAGES)))
    print("Translation cache: {} hits / {} misses".format(_cache_hits, _cache_misses))
    print("=" * 60)


if __name__ == "__main__":
    main()
