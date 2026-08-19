#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Shared, dependency-free channel-name normalization/comparison helpers,
used identically by both:
  - vUtils.py's VavooEPGMatcher (on-box, Rytec/curated-DB matching)
  - generate_epg_channel_db.py (off-box dev-time curated-DB generator)

This module exists specifically so those two call sites can't drift
apart - they used to be two hand-maintained copies of the same logic,
one of which could silently fall out of sync with the other and break
curated-DB lookups with no error, just a quiet drop in match rate.
Pulled out into its own module (rather than importing straight from
vUtils.py) because vUtils.py pulls in Enigma2-only modules
(Components.config, enigma.eTimer, ...) that don't exist off-box, and
the generator must run standalone. This file must stay free of any such
import so both sides can keep using it.

Must work on both Python 2 and Python 3 (vUtils.py's side runs on
whatever Enigma2 image installed the plugin), and matches every regex
flag choice `re.UNICODE` needed so a channel name in any script
normalizes the same way in both interpreters.
"""
from __future__ import absolute_import, print_function

import re

# Vavoo suffix (.c, .s, .b, ...) must be stripped BEFORE the
# quality-tag strip below: names very often carry both (e.g. "6TER FHD
# .b"), and the quality tag isn't at the string's end while the Vavoo
# suffix is still there - stripping in the other order left "FHD"/"HD"
# stuck in the cleaned name (e.g. "6ter fhd" instead of "6ter"), which
# tanks the similarity score against the plain Rytec name.
_BRACKETS_RE = re.compile(r'\[.*\]')
_PARENS_RE = re.compile(r'\(.*\)')
_VAVOO_SUFFIX_RE = re.compile(r'\s+\.[A-Z0-9]{1,3}$')
_QUALITY_TAG_RE = re.compile(
    r'\s+(HD|FHD|SD|4K|ITA|ITALIA|BACKUP|TIMVISION|PLUS)$')
_TRAILING_PLUS_RE = re.compile(r'\s+\+$')
# Any word character in any script (Unicode-aware in both Py2 - via the
# explicit UNICODE flag - and Py3, where it's the default for str
# patterns) plus space survives; everything else (punctuation, symbols)
# is dropped. Broader than the old ASCII-only [^A-Z0-9 ] class so
# non-Latin names (Cyrillic, Greek, Arabic, ...) don't collapse to
# near-nothing the moment a feed/catalog actually uses them - ASCII
# names normalize identically to before this change.
_NON_WORD_RE = re.compile(r'[^\w ]', re.UNICODE)
_MULTI_SPACE_RE = re.compile(r'\s+')
_DIGIT_BOUNDARY_RE = re.compile(r'(?<=[a-z])(?=[0-9])')


def clean_name_for_similarity(name):
    """Normalize a channel name for similarity comparison: uppercase,
    strip Vavoo's own [.]/(.) tags, its trailing .c/.s/.b-style suffix,
    common quality tags, and any non-word character, collapsing
    whitespace - so two spellings of the same channel end up as the
    same key regardless of source/formatting quirks."""
    if not name:
        return ""
    n = name.upper()
    n = _BRACKETS_RE.sub('', n)
    n = _PARENS_RE.sub('', n)
    if not n.startswith("HISTORY"):
        n = _VAVOO_SUFFIX_RE.sub('', n)
    n = _QUALITY_TAG_RE.sub('', n)
    n = _TRAILING_PLUS_RE.sub('', n)
    n = _NON_WORD_RE.sub('', n)
    n = _MULTI_SPACE_RE.sub(' ', n)
    return n.strip().lower()


def tokenize_for_compat(clean_name):
    """Split an already-cleaned (lowercase) name into tokens for
    tokens_compatible(), first inserting a space between a letter and
    an immediately-following digit (e.g. "sport1" -> "sport 1").

    Rytec's own channel comments frequently glue a trailing channel
    number straight onto the preceding word with no space (e.g. "Bein
    Sport1"), while Vavoo's own channel names always space it out
    ("BEIN SPORTS 1"). Without this, an otherwise very close match
    never even reaches the similarity check, rejected outright by
    tokens_compatible() because "sport1" and "sports"+"1" don't
    tokenize the same way. This only affects tokenization for the
    compatibility gate - clean_name_for_similarity()'s output (used for
    actual scoring and cache-key comparisons) is untouched."""
    return _DIGIT_BOUNDARY_RE.sub(' ', clean_name).split()


def token_pair_compatible(a, b):
    """Two tokens are compatible if identical, or if they differ only
    by a trailing "s" on a non-numeric word (tolerates a singular/
    plural naming difference, e.g. Rytec's "sport" vs Vavoo's
    "sports"). Never applies when either token is purely numeric - a
    different number at a shared position (e.g. "3" vs "5") is exactly
    what tokens_compatible() exists to catch, since that's what turns
    an otherwise near-identical name into a genuinely different
    channel."""
    if a == b:
        return True
    if a.isdigit() or b.isdigit():
        return False
    return a + 's' == b or b + 's' == a


def tokens_compatible(a_tokens, b_tokens):
    """True unless the two token lists differ at a shared position -
    i.e. one is a genuine word-for-word prefix of the other (or
    they're equal, allowing singular/plural pairs - see
    token_pair_compatible()). A longer name is allowed to just add
    trailing descriptive words (e.g. "sky sport" / "sky sport 4k"), but
    substituting a different word at a position both share (e.g.
    "canale 5" vs "canale 122") means these are actually different
    channels, no matter how high the raw character-level similarity
    looks."""
    shorter, longer = (
        (a_tokens, b_tokens) if len(a_tokens) <= len(b_tokens)
        else (b_tokens, a_tokens))
    prefix = longer[:len(shorter)]
    return len(prefix) == len(shorter) and all(
        token_pair_compatible(x, y) for x, y in zip(shorter, prefix))
