#!/usr/bin/env python
# -*- coding: UTF-8 -*-
# Copyright (c) @Lululla 2026
# Google Translate API for Foreca One Weather Plugin

import hashlib
import json
import socket
import time
from json import JSONDecodeError, loads
from os import makedirs, remove
from os.path import dirname, exists, join

from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from Components.config import config

from . import DEBUG, HEADERS, SYSTEM_DIR

# ============================================================
# CUSTOM CONFIGURATION
# ============================================================

# Translation API URL (can be changed if needed)
TRANSLATE_API_URL = "https://translate.googleapis.com/translate_a/single"

# Timeout for HTTP requests (in seconds)
REQUEST_TIMEOUT = 8

# Character limit for batch translation (to avoid errors)
MAX_CHARS_PER_REQUEST = 2000

# Local cache to avoid repetitive requests
CACHE_FILE = join(SYSTEM_DIR, "translation_cache.json")
_translation_cache = {}
_cache_hits = 0
_cache_misses = 0
_cache_dirty = False    # flag to know if there are changes to save

# Enable logging
ENABLE_LOGGING = True


# ============================================================
# CACHE PERSISTENCE
# ============================================================


def _ensure_cache_dir():
    """Create the directory for the cache file if it does not exist."""
    cache_dir = dirname(CACHE_FILE)
    if not exists(cache_dir):
        try:
            makedirs(cache_dir)
        except Exception as e:
            _log(f"Error creating cache directory: {e}")


def load_cache_from_disk():
    """Load the cache from the JSON file at startup."""
    global _translation_cache
    _ensure_cache_dir()
    if exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                _translation_cache = json.load(f)
            _log(f"Cache loaded from disk ({len(_translation_cache)} entries)")
        except Exception as e:
            _log(f"Error loading cache: {e}")
            _translation_cache = {}
    else:
        _translation_cache = {}


def save_cache_to_disk():
    """Save the cache to disk if there are changes."""
    global _cache_dirty
    if not _cache_dirty:
        return
    _ensure_cache_dir()
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_translation_cache, f, ensure_ascii=False, indent=2)
        _log(f"Cache saved to disk ({len(_translation_cache)} entries)")
        _cache_dirty = False
    except Exception as e:
        _log(f"Error saving cache: {e}")


# ============================================================
# UTILITY FUNCTIONS
# ============================================================


def _log(message):
    """Custom logging"""
    if ENABLE_LOGGING and DEBUG:
        timestamp = time.time()
        print(f"[Foreca-1-Translate][{timestamp:.2f}] {message}")


def _get_system_language():
    """Get system language in short format"""
    try:
        lang = config.misc.language.value
        return lang.split('_')[0].lower()
    except Exception:
        lang = config.osd.language.value
        return lang.split('_')[0].lower()

# print("System Language:", _get_system_language())


def _to_unicode(text):
    """Convert any input into a Unicode string."""
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


# ============================================================
# ARABIC LANGUAGE DETECTION
# ============================================================


def _is_arabic_char(char):
    """Check if a character is Arabic"""
    try:
        code = ord(char)
        # Unicode ranges for Arabic characters
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
    """
    Determines whether a text is predominantly Arabic.
    Returns True if more than 60% of alphabetic characters are Arabic.
    """
    text_unicode = _to_unicode(text)
    if not text_unicode:
        return False

    total_letters = 0
    arabic_letters = 0

    for char in text_unicode:
        # Consider only alphabetic characters (exclude spaces, numbers,
        # punctuation)
        if char.isalpha():
            total_letters += 1
            if _is_arabic_char(char):
                arabic_letters += 1

    # If there are no letters, it's not Arabic
    if total_letters == 0:
        return False

    # Calculate percentage
    arabic_ratio = float(arabic_letters) / float(total_letters)

    # Threshold to consider the text Arabic (60%)
    return arabic_ratio >= 0.6


# ============================================================
# CACHE AND PERFORMANCE
# ============================================================


def _get_cache_key(text, target_lang):
    """Generate a unique cache key using MD5 (stable across runs)"""
    # Use MD5 because it is fast and deterministic
    key_string = f"{target_lang}:{text}".encode('utf-8')
    return hashlib.md5(key_string).hexdigest()


def _cache_translation(text, target_lang, translated):
    """Store a translation in the cache and save immediately to disk."""
    global _cache_dirty
    cache_key = _get_cache_key(text, target_lang)
    _translation_cache[cache_key] = translated
    _cache_dirty = True
    save_cache_to_disk()
    return translated


def _get_cached_translation(text, target_lang):
    """Retrieve a translation from the cache"""
    global _cache_hits, _cache_misses
    cache_key = _get_cache_key(text, target_lang)

    if cache_key in _translation_cache:
        _cache_hits += 1
        return _translation_cache[cache_key]

    _cache_misses += 1
    return None


def get_cache_stats():
    """Return cache statistics"""
    return {
        'hits': _cache_hits,
        'misses': _cache_misses,
        'size': len(_translation_cache),
        'hit_rate': _cache_hits / max(1, _cache_hits + _cache_misses)
    }


def clear_cache():
    """Clear the translation cache and delete the file"""
    global _cache_hits, _cache_misses, _cache_dirty
    _translation_cache.clear()
    _cache_hits = 0
    _cache_misses = 0
    _cache_dirty = False
    if exists(CACHE_FILE):
        try:
            remove(CACHE_FILE)
        except Exception as e:
            _log(f"Error deleting cache file: {e}")
    _log("Cache cleared")


# ============================================================
# MAIN TRANSLATION FUNCTION
# ============================================================

def translate_text(text, target_lang=None, use_cache=True):
    """
    Translates text using the Google Translate API.

    Args:
        text (str): Text to translate
        target_lang (str): Target language (e.g. 'it', 'en', 'de')
                           If None, uses the system language
        use_cache (bool): Whether to use the local cache

    Returns:
        str: Translated text or original text in case of error
    """
    start_time = time.time()
    _log(f"Target language: '{target_lang}'")
    # Input validation
    if not text:
        return ""

    # Convert to Unicode
    text_unicode = _to_unicode(text)

    # Use system language if not specified
    if target_lang is None:
        target_lang = _get_system_language()

    # Normalize language (ensure lowercase)
    target_lang = target_lang.lower()

    # If the text is already Arabic, do not translate it
    if _is_text_arabic(text_unicode):
        _log(f"Arabic text detected, not translated: '{text_unicode[:50]}...'")
        return text_unicode

    # Check cache if enabled
    if use_cache:
        cached = _get_cached_translation(text_unicode, target_lang)
        if cached is not None:
            _log(f"Cache HIT: '{text_unicode[:30]}...' -> '{cached[:30]}...'")
            return cached

    # Error handling for overly long texts
    if len(text_unicode) > MAX_CHARS_PER_REQUEST:
        _log("Text too long (" +
             str(len(text_unicode)) +
             " chars), truncated to " +
             str(MAX_CHARS_PER_REQUEST))
        text_unicode = text_unicode[:MAX_CHARS_PER_REQUEST]

    # Prepare the request
    params = {
        "client": "gtx",           # Fake client to bypass restrictions
        "sl": "auto",              # Automatic source language
        "tl": target_lang,         # Target language
        "dt": "t",                 # Response type: translation only
        "q": text_unicode,         # Text to translate
    }

    try:
        # Build the URL
        query_string = urlencode(params)
        url = f"{TRANSLATE_API_URL}?{query_string}"

        _log(f"Translating: '{text_unicode[:40]}...' -> {target_lang}")

        # Set timeout to avoid blocking
        socket.setdefaulttimeout(REQUEST_TIMEOUT)

        # Perform the request
        req = Request(url)
        for key, value in HEADERS.items():
            req.add_header(key, value)
        response = urlopen(req, timeout=REQUEST_TIMEOUT)
        raw_data = response.read()

        # Decode the response
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode('utf-8')

        # Parse JSON response
        data = loads(raw_data)

        # Extract the translation from the JSON structure
        translated_text = ""
        if isinstance(data, list) and data:
            # Typical structure: [[[translation, original], ...], ...]
            for item in data[0]:
                if item and isinstance(item, list) and item[0]:
                    translated_text += item[0]

        # Clean the result
        if translated_text:
            translated_text = _clean_whitespace(translated_text)

            # Save to cache
            if use_cache:
                _cache_translation(text_unicode, target_lang, translated_text)

            elapsed = time.time() - start_time
            _log((
                f"Translation completed in {elapsed:.2f}s: '{text_unicode[:30]}...' -> "
                f"'{translated_text[:30]}...'"
            ))

            return translated_text
        else:
            _log(f"Empty API response for: '{text_unicode[:30]}...'")
            return text_unicode

    except socket.timeout:
        _log(f"TIMEOUT during translation: '{text_unicode[:30]}...'")
        return text_unicode

    except (URLError, HTTPError) as e:
        _log(f"HTTP error {getattr(e, 'code', 'N/A')}: {str(e)}")
        return text_unicode

    except JSONDecodeError as e:
        _log(f"JSON error: {str(e)}")
        return text_unicode

    except Exception as e:
        error_type = type(e).__name__
        _log(f"Error {error_type}: {str(e)}")
        return text_unicode

    finally:
        # Restore default timeout
        socket.setdefaulttimeout(None)


# ============================================================
# AUXILIARY FUNCTIONS FOR SPECIAL CASES
# ============================================================


def translate_batch(texts, target_lang=None, use_cache=True):
    """
    Translates a list of texts in batch.
    Optimized to reduce the number of HTTP requests.

    Args:
        texts (list): List of texts to translate
        target_lang (str): Target language
        use_cache (bool): Use cache

    Returns:
        list: List of translated texts
    """
    if not texts:
        return []

    # Use system language if not specified
    if target_lang is None:
        target_lang = _get_system_language()
    results = []
    batch_text = []
    batch_indices = []

    for i, text in enumerate(texts):
        text_unicode = _to_unicode(text)

        # Check cache
        if use_cache:
            cached = _get_cached_translation(text_unicode, target_lang)
            if cached is not None:
                results.append(cached)
                continue

        # If the text is Arabic, do not translate it
        if _is_text_arabic(text_unicode):
            results.append(text_unicode)
            continue

        # Add to batch
        batch_text.append(text_unicode)
        batch_indices.append(i)
        results.append(None)  # Placeholder

    # If there are texts to translate in batch
    if batch_text:
        try:
            # Join texts with a special separator
            separator = u" ||| "
            combined_text = separator.join(batch_text)

            # Translate the batch
            combined_translated = translate_text(
                combined_text,
                target_lang,
                use_cache=False  # Do not use cache for batch
            )

            # Split results
            if separator in combined_translated:
                translated_parts = combined_translated.split(separator)
            else:
                # Fallback: split by approximate number
                translated_parts = [combined_translated] * len(batch_text)

            # Update results
            for idx, translated in zip(batch_indices, translated_parts):
                results[idx] = translated

                # Save to cache
                if use_cache and idx < len(texts):
                    text_unicode = _to_unicode(texts[idx])
                    _cache_translation(text_unicode, target_lang, translated)

        except Exception as e:
            _log(f"Batch translation error: {str(e)}")
            # Fallback: translate individually
            for idx in batch_indices:
                if results[idx] is None and idx < len(texts):
                    results[idx] = translate_text(
                        texts[idx], target_lang, use_cache)

    # Replace None with original text
    for i in range(len(results)):
        if results[i] is None:
            results[i] = _to_unicode(texts[i])

    return results


def safe_translate(text, fallback=None, **kwargs):
    """
    Safe version of translate_text that always returns a valid string.
    Args:
        text (str): Text to translate
        fallback (str): Fallback text if translation fails
        **kwargs: Additional arguments for translate_text
    Returns:
        str: Translated text, fallback or original
    """
    try:
        translated = translate_text(text, **kwargs)
        if translated and translated.strip():
            return translated

        # If translation is empty, use fallback
        if fallback is not None:
            return _to_unicode(fallback)

        return _to_unicode(text)

    except Exception as e:
        _log(f"Error in safe_translate: {str(e)}")
        if fallback is not None:
            return _to_unicode(fallback)
        return _to_unicode(text)


def trans(text, target_lang=None):
    """
    Simplified translation function for single strings.
    Uses cache and translate_text.
    """
    if target_lang is None:
        target_lang = _get_system_language()
    target_lang = target_lang.lower()

    if not text or not isinstance(text, str):
        return text or ""

    text = text.strip()
    if not text:
        return ""

    # Do not translate Arabic text
    if _is_text_arabic(text):
        return text

    # Check cache using full key (language + hash)
    cached = _get_cached_translation(text, target_lang)
    if cached is not None:
        return cached

    # Translate (translate_text already handles internal caching if
    # use_cache=True)
    translated = translate_text(text, target_lang, use_cache=True)
    if translated and translated != text:
        return translated
    return text


def translate_batch_strings(texts, target_lang=None):
    """
    High-level batch translation for a list of strings.
    """
    if not texts:
        return []
    valid_texts = [str(t).strip() for t in texts if t and str(t).strip()]
    if not valid_texts:
        return []

    # Use the existing cache via translate_batch
    return translate_batch(valid_texts, target_lang, use_cache=True)


# ============================================================
# TEST FUNCTION (for debugging)
# ============================================================


def test_translation():
    """Test function to verify functionality"""
    test_cases = [
        ("Hello world", "it", "Ciao mondo"),
        ("Weather forecast", "es", "Pronóstico del tiempo"),
        ("Temperature", "fr", "Température"),
    ]
    if DEBUG:
        print("=" * 60)
        print("Foreca One TRANSLATION TEST")
        print("=" * 60)

    all_passed = True

    for original, lang, expected in test_cases:
        result = translate_text(original, lang)

        if result and result.lower() == expected.lower():
            status = "✓ PASS"
        else:
            status = "✗ FAIL"
            all_passed = False
        if DEBUG:
            print(
                f"{status}: '{original}' -> '{result}' (expected: '{expected}')")
    if DEBUG:
        print("=" * 60)
        stats = get_cache_stats()
        print((
            f"Cache statistics: {stats['hits']} hits, {stats['misses']} misses, "
            f"rate: {stats['hit_rate']:.1%}"
        ))
        print("=" * 60)

    return all_passed


# ============================================================
# INITIALIZATION
# ============================================================

# Load cache at module startup
load_cache_from_disk()

if __name__ == "__main__":
    # Test mode when run directly
    if DEBUG:
        print("Google Translate API for Foreca")
        print("Enhanced custom version")

    if test_translation():
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")
else:
    # Imported as a module
    _log("Foreca One translation module loaded")
    _log(f"System language: {_get_system_language()}")
