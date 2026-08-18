#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Dev-time generator for a curated Vavoo-channel-name -> EPG-feed-id
mapping, built by matching a country's live Vavoo channel list against
that same country's own epg_<cc>.xml programme feed (the one
vavoo_proxy.py's /epg/<cc>.xml endpoint redirects EPGImport to) instead
of Rytec's much sparser database for most countries (see this
project's own investigation: Spain had 7 Rytec entries vs 373 channels
in its own feed, Poland 0 vs 636, Turkey 10 vs 178).

The output is a plain {vavoo_channel_name: epg_feed_channel_id} JSON
file - not a full service reference. The actual DVB tuple used in a
bouquet is always synthesized locally per channel_id at export time
(see unique_fallback_sref() in vUtils.py), so this file only needs to
solve the "which programme-guide id does this Vavoo channel name
correspond to" problem, the same thing VavooEPGMatcher's live Rytec
fuzzy-matching (and its own epg-feed fallback) already solve on-box,
just precomputed once here instead of redone on every user's export.

Run this against a box's running proxy (or point --proxy-host at one
over the LAN):

    python generate_epg_channel_db.py es pl tr --proxy-host 192.168.1.50

Writes, per country, into --output-dir (default: current directory):
  vavoo_channels_<cc>.json         auto-matched (name -> feed channel id)
  vavoo_channels_<cc>.review.json  names that need a human to resolve
                                    (no confident match found)

Nothing here runs inside Enigma2 - only vUtils.py's VavooEPGMatcher
running on the box does that, and this script deliberately doesn't
import it (vUtils.py pulls in Enigma2-only modules like
Components.config/enigma.eTimer that don't exist off-box). The
matching helpers below are intentionally a plain-Python mirror of
VavooEPGMatcher's own _clean_name_for_similarity()/
_tokenize_for_compat()/_tokens_compatible() in vUtils.py - keep them in
sync if that logic changes there.
"""
import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from io import BytesIO
from os.path import join
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

DEFAULT_THRESHOLD = 0.70
EPG_FEED_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/Belfagor2005/vavoo-player/"
    "master/epg_{}.xml")


# ---------------------------------------------------------------------
# Name-cleaning / token-compatibility helpers - mirror VavooEPGMatcher
# in vUtils.py so this generator's matches agree with what the live
# plugin would do for the same names.
# ---------------------------------------------------------------------

def clean_name_for_similarity(name):
    """Mirrors VavooEPGMatcher._clean_name_for_similarity()."""
    if not name:
        return ""
    n = name.upper()
    n = re.sub(r'\[.*\]', '', n)
    n = re.sub(r'\(.*\)', '', n)
    if not n.startswith("HISTORY"):
        n = re.sub(r'\s+\.[A-Z0-9]{1,3}$', '', n)
    n = re.sub(r'\s+(HD|FHD|SD|4K|ITA|ITALIA|BACKUP|TIMVISION|PLUS)$', '', n)
    n = re.sub(r'\s+\+$', '', n)
    n = re.sub(r'[^A-Z0-9 ]', '', n)
    n = re.sub(r'\s+', ' ', n)
    return n.strip().lower()


def tokenize_for_compat(clean_name):
    """Mirrors vUtils.py's module-level _tokenize_for_compat()."""
    return re.sub(r'(?<=[a-z])(?=[0-9])', ' ', clean_name).split()


def token_pair_compatible(a, b):
    """Mirrors vUtils.py's module-level _token_pair_compatible()."""
    if a == b:
        return True
    if a.isdigit() or b.isdigit():
        return False
    return a + 's' == b or b + 's' == a


def tokens_compatible(a_tokens, b_tokens):
    """Mirrors vUtils.py's module-level _tokens_compatible()."""
    shorter, longer = (
        (a_tokens, b_tokens) if len(a_tokens) <= len(b_tokens)
        else (b_tokens, a_tokens))
    prefix = longer[:len(shorter)]
    return len(prefix) == len(shorter) and all(
        token_pair_compatible(x, y) for x, y in zip(shorter, prefix))


def fetch_url(url, timeout=60):
    req = Request(url, headers={"User-Agent": "vavoo-epg-db-generator/1.0"})
    resp = urlopen(req, timeout=timeout)
    try:
        return resp.read()
    finally:
        resp.close()


def fetch_vavoo_channels(proxy_host, proxy_port, country):
    """Fetch {name, id} pairs for a country from a running vavoo_proxy
    instance's /channels endpoint (see vavoo_proxy.py's handler)."""
    url = "http://{}:{}/channels?country={}".format(
        proxy_host, proxy_port, country)
    print("Fetching {} ...".format(url))
    data = fetch_url(url, timeout=30)
    channels = json.loads(data.decode("utf-8"))
    seen = set()
    result = []
    for c in channels:
        name, cid = c.get("name"), c.get("id")
        if name and cid and name not in seen:
            seen.add(name)
            result.append({"name": name, "id": cid})
    return result


def fetch_feed_index(country):
    """Fetch and parse this country's epg_<cc>.xml, returning a list of
    (feed_id, clean_display_name, tokens) - same shape of work
    vUtils.py's _get_epg_feed_index() does on-box, fetched directly
    from GitHub here instead of via the local proxy's redirect, since
    this script may run off-box."""
    url = EPG_FEED_URL_TEMPLATE.format(country.lower())
    print("Fetching {} ...".format(url))
    data = fetch_url(url, timeout=120)
    index = []
    seen_names = set()
    for event, elem in ET.iterparse(BytesIO(data), events=("start", "end")):
        if event == "end" and elem.tag == "channel":
            chan_id = elem.get("id")
            if chan_id:
                for dn in elem.findall("display-name"):
                    dn_text = (dn.text or "").strip()
                    if not dn_text:
                        continue
                    clean = clean_name_for_similarity(dn_text)
                    if clean and clean not in seen_names:
                        seen_names.add(clean)
                        index.append(
                            (chan_id, clean, tokenize_for_compat(clean)))
            elem.clear()
        elif event == "start" and elem.tag == "programme":
            break
    return index


def find_best_match(vavoo_name, feed_index, threshold):
    """Mirrors vUtils.py's module-level _find_feed_id_by_name(), but
    returns the best score too (even below threshold) so unmatched
    names can be sorted by how close they came in the review file."""
    clean = clean_name_for_similarity(vavoo_name)
    if not clean:
        return None, 0.0
    source_tokens = tokenize_for_compat(clean)
    sm = SequenceMatcher(None, clean)
    best_id, best_score = None, 0.0
    for feed_id, feed_clean, feed_tokens in feed_index:
        if (source_tokens and feed_tokens and
                not tokens_compatible(source_tokens, feed_tokens)):
            continue
        sm.set_seq2(feed_clean)
        score = sm.ratio()
        if score > best_score:
            best_score = score
            best_id = feed_id
    if best_id and best_score >= threshold:
        return best_id, best_score
    return None, best_score


def generate_for_country(country, proxy_host, proxy_port, threshold):
    channels = fetch_vavoo_channels(proxy_host, proxy_port, country)
    print("{}: {} Vavoo channels".format(country.upper(), len(channels)))
    feed_index = fetch_feed_index(country)
    print("{}: {} feed channels".format(country.upper(), len(feed_index)))

    matched = {}
    review = []
    for ch in channels:
        best_id, score = find_best_match(ch["name"], feed_index, threshold)
        if best_id:
            # Keyed by the same normalized form VavooEPGMatcher itself
            # compares against at match time (see vUtils.py's
            # _clean_name_for_similarity() calls) - a raw-name key
            # would miss on-box lookups over small formatting
            # differences (case, whitespace) between generation time
            # and match time.
            matched[clean_name_for_similarity(ch["name"])] = best_id
        else:
            review.append(
                {"name": ch["name"], "best_score": round(score, 3)})

    review.sort(key=lambda r: r["best_score"], reverse=True)
    return matched, review


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate a Vavoo channel name -> EPG feed id mapping for "
            "one or more countries, by matching the live Vavoo channel "
            "list against that country's own epg_<cc>.xml programme "
            "feed instead of Rytec."))
    parser.add_argument(
        "countries", nargs="+",
        help="Country code(s) to generate, e.g. es pl tr")
    parser.add_argument(
        "--proxy-host", default="127.0.0.1",
        help="Host of a running vavoo_proxy instance (default: 127.0.0.1)")
    parser.add_argument(
        "--proxy-port", type=int, default=4323,
        help="Port of a running vavoo_proxy instance (default: 4323)")
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_THRESHOLD,
        help="Minimum similarity to auto-accept a match "
             "(default: {})".format(DEFAULT_THRESHOLD))
    parser.add_argument(
        "--output-dir", default=".",
        help="Directory to write vavoo_channels_<cc>.json / "
             ".review.json into (default: current directory)")
    args = parser.parse_args()

    exit_code = 0
    for country in args.countries:
        cc = country.lower()
        try:
            matched, review = generate_for_country(
                cc, args.proxy_host, args.proxy_port, args.threshold)
        except Exception as e:
            print("ERROR generating {}: {}".format(cc, e))
            exit_code = 1
            continue

        out_path = join(args.output_dir, "vavoo_channels_{}.json".format(cc))
        review_path = join(
            args.output_dir, "vavoo_channels_{}.review.json".format(cc))

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(
                matched, f, indent=2, sort_keys=True, ensure_ascii=False)
        with open(review_path, "w", encoding="utf-8") as f:
            json.dump(review, f, indent=2, ensure_ascii=False)

        print("{}: {} auto-matched -> {}".format(cc, len(matched), out_path))
        print("{}: {} need manual review -> {}".format(
            cc, len(review), review_path))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
