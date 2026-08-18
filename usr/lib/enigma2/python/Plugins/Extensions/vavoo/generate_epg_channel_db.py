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
over the LAN). Country codes or display names both work (see
resolve_country()):

    python generate_epg_channel_db.py es pl tr --proxy-host 192.168.1.50
    python generate_epg_channel_db.py Spain Poland Turkey --proxy-host 192.168.1.50

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
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

DEFAULT_THRESHOLD = 0.70
EPG_FEED_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/Belfagor2005/vavoo-player/"
    "master/epg_{}.xml")

# Mirrors __init__.py's country_codes dict - display name -> 2-letter
# code. Two DIFFERENT things need two DIFFERENT strings and this
# script previously conflated them into a single "country" argument:
#   - vavoo_proxy.py's /channels endpoint filters on Vavoo's own raw
#     catalog "country" field, which holds the full display name
#     (e.g. "portugal"), NOT a 2-letter code - confirmed by a user
#     run where --proxy-host .../channels?country=portugal correctly
#     returned 291 channels.
#   - epg_<cc>.xml (the GitHub-hosted programme feed) is always named
#     with the 2-letter ISO-style code (e.g. "epg_pt.xml") - a request
#     for "epg_portugal.xml" 404s.
# resolve_country() below turns either form the user types into both.
COUNTRY_CODES = {
    # Africa
    "Africa": "africa", "Algeria": "dz", "Egypt": "eg", "Ethiopia": "et",
    "Ghana": "gh", "Kenya": "ke", "Libya": "ly", "Morocco": "ma",
    "Nigeria": "ng", "South Africa": "za", "Sudan": "sd", "Tanzania": "tz",
    "Tunisia": "tn", "Uganda": "ug",
    # Americas
    "America": "us", "Argentina": "ar", "Bolivia": "bo", "Brazil": "br",
    "Canada": "ca", "Chile": "cl", "Colombia": "co", "Costa Rica": "cr",
    "Cuba": "cu", "Dominican Republic": "do", "Ecuador": "ec",
    "Guatemala": "gt", "Honduras": "hn", "Jamaica": "jm", "Mexico": "mx",
    "Nicaragua": "ni", "Panama": "pa", "Paraguay": "py", "Peru": "pe",
    "Puerto Rico": "pr", "Salvador": "sv", "El Salvador": "sv",
    "Uruguay": "uy", "USA": "us", "United States": "us", "Venezuela": "ve",
    # Asia
    "Afghanistan": "af", "Arabia": "sa", "Azerbaijan": "az",
    "Bangladesh": "bd", "China": "cn", "Georgia": "ge", "Hong Kong": "hk",
    "India": "in", "Indonesia": "id", "Iran": "ir", "Iraq": "iq",
    "Israel": "il", "Japan": "jp", "Jordan": "jo", "Kazakhstan": "kz",
    "Kuwait": "kw", "Lebanon": "lb", "Malaysia": "my", "Mongolia": "mn",
    "Myanmar": "mm", "Nepal": "np", "North Korea": "kp", "Oman": "om",
    "Pakistan": "pk", "Palestine": "ps", "Philippines": "ph", "Qatar": "qa",
    "Saudi Arabia": "sa", "Singapore": "sg", "South Korea": "kr",
    "Sri Lanka": "lk", "Syria": "sy", "Taiwan": "tw", "Thailand": "th",
    "UAE": "ae", "United Arab Emirates": "ae", "Uzbekistan": "uz",
    "Vietnam": "vn", "Yemen": "ye",
    # Europe
    "Albania": "al", "Andorra": "ad", "Austria": "at", "Balkans": "bk",
    "Baltic": "baltic", "Belarus": "by", "Belgium": "be", "Bosnia": "ba",
    "Bosnia Herzegovina": "ba", "Bulgaria": "bg", "Croatia": "hr",
    "Cyprus": "cy", "Czech": "cz", "Czech Republic": "cz", "Denmark": "dk",
    "Estonia": "ee", "Finland": "fi", "France": "fr", "Germany": "de",
    "Greece": "gr", "Holy See": "va", "Hungary": "hu", "Iceland": "is",
    "Ireland": "ie", "Italy": "it", "Kosovo": "xk", "Latvia": "lv",
    "Liechtenstein": "li", "Lithuania": "lt", "Luxembourg": "lu",
    "Malta": "mt", "Moldova": "md", "Monaco": "mc", "Montenegro": "me",
    "Netherlands": "nl", "North Macedonia": "mk", "Norway": "no",
    "Poland": "pl", "Portugal": "pt", "Romania": "ro", "Russia": "ru",
    "Russian Federation": "ru", "San Marino": "sm",
    "Scandinavia": "scandinavia", "Serbia": "rs", "Slovak Republic": "sk",
    "Slovakia": "sk", "Slovenia": "si", "Spain": "es", "Sweden": "se",
    "Switzerland": "ch", "Turkey": "tr", "UK": "gb", "Ukraine": "ua",
    "United Kingdom": "gb", "Vatican City": "va",
    # International / Catch-all
    "Global": "internat", "Great Britain": "gb", "Internat": "internat",
    "International": "internat", "Internaz": "internat", "World": "internat",
    # Oceania
    "Australia": "au", "New Zealand": "nz",
}


def resolve_country(user_input):
    """Turn whatever the user typed (a display name like "Portugal" or
    a 2-letter code like "pt") into (proxy_query_name, feed_code).

    Falls back to using user_input as-is for whichever side it wasn't
    recognized for, so an unmapped/new country still gets a best-effort
    attempt instead of a hard failure - resolve_for_country() prints
    what it resolved to either way, so a bad guess is visible."""
    stripped = user_input.strip()
    lower = stripped.lower()

    for name, code in COUNTRY_CODES.items():
        if name.lower() == lower:
            return name.lower(), code

    # A code can map to several display names (e.g. "gb" <- "UK",
    # "United Kingdom", "Great Britain"). Prefer whichever one matches
    # a real Vavoo catalog country (VAVOO_COUNTRIES) over an arbitrary
    # first-in-dict alias, since only the catalog's own string works
    # against /channels?country=.
    vavoo_lower = {c.lower() for c in VAVOO_COUNTRIES}
    for name, code in COUNTRY_CODES.items():
        if code == lower and name.lower() in vavoo_lower:
            return name.lower(), code

    for name, code in COUNTRY_CODES.items():
        if code == lower:
            return name.lower(), code

    return lower, lower


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
    # quote(): country names can contain spaces (e.g. "France Sport") -
    # an unescaped space in the query string breaks the request.
    url = "http://{}:{}/channels?country={}".format(
        proxy_host, proxy_port, quote(country))
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
    # quote(): country falls through to a raw, unmapped feed code for
    # anything not in COUNTRY_CODES (e.g. "france sport") - an unescaped
    # space there breaks the request, same class of bug as in
    # fetch_vavoo_channels() above.
    url = EPG_FEED_URL_TEMPLATE.format(quote(country.lower()))
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


def generate_for_country(query_name, feed_code, proxy_host, proxy_port, threshold):
    """query_name is what vavoo_proxy's /channels endpoint expects
    (Vavoo's own raw catalog country field - a display name, e.g.
    "portugal"); feed_code is the 2-letter code epg_<cc>.xml is named
    with (e.g. "pt"). See resolve_country()."""
    channels = fetch_vavoo_channels(proxy_host, proxy_port, query_name)
    print("{}: {} Vavoo channels".format(feed_code.upper(), len(channels)))
    feed_index = fetch_feed_index(feed_code)
    print("{}: {} feed channels".format(feed_code.upper(), len(feed_index)))

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


# The actual set of countries Vavoo's own catalog offers, as reported
# directly against a live box - NOT every country COUNTRY_CODES
# recognizes has real Vavoo content, so sweeping that whole dict (an
# earlier version of --all did this) tried ~100 countries with nothing
# to find. "France Sport" and "Arabia"/"Balkans" aren't plain ISO
# countries - resolve_country() falls through to a best-effort
# lowercased attempt for anything not in COUNTRY_CODES by name, so an
# unmapped one like "France Sport" still gets tried, just without a
# guaranteed-correct feed code guess.
VAVOO_COUNTRIES = [
    "Albania", "Arabia", "Balkans", "Bulgaria", "Croatia", "France",
    "France Sport", "Germany", "Italy", "Netherlands", "Poland",
    "Portugal", "Romania", "Russia", "Spain", "Turkey", "United Kingdom",
]


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate a Vavoo channel name -> EPG feed id mapping for "
            "one or more countries, by matching the live Vavoo channel "
            "list against that country's own epg_<cc>.xml programme "
            "feed instead of Rytec."))
    parser.add_argument(
        "countries", nargs="*",
        help="Country code(s) or display name(s) to generate, e.g. "
             "'es pl tr' or 'Spain Poland Turkey' - either form works, "
             "see resolve_country(). Omit and pass --all instead to try "
             "every known country.")
    parser.add_argument(
        "--all", action="store_true",
        help="Try every country Vavoo's own catalog actually offers "
             "(VAVOO_COUNTRIES), instead of an explicit list. Some of "
             "these still won't have an epg_<cc>.xml feed - that's "
             "reported as 'skipped (no feed)' rather than a failure.")
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

    if args.all and args.countries:
        parser.error("pass either country arguments or --all, not both")
    if not args.all and not args.countries:
        parser.error("pass at least one country, or --all")

    countries = VAVOO_COUNTRIES if args.all else args.countries

    generated = 0
    skipped_no_feed = 0
    errors = 0
    for country in countries:
        query_name, cc = resolve_country(country)
        print("'{}' resolved to: proxy query='{}', feed code='{}'".format(
            country, query_name, cc))
        try:
            matched, review = generate_for_country(
                query_name, cc, args.proxy_host, args.proxy_port,
                args.threshold)
        except Exception as e:
            if "404" in str(e):
                print("{}: skipped (no epg_{}.xml feed)".format(cc, cc))
                skipped_no_feed += 1
            else:
                print("ERROR generating {}: {}".format(cc, e))
                errors += 1
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
        generated += 1

    print("\n{} generated, {} skipped (no feed), {} errors".format(
        generated, skipped_no_feed, errors))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
