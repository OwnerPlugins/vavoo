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
import sys
from difflib import SequenceMatcher
from io import BytesIO
from os.path import join
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from epg_name_utils import (
    clean_name_for_similarity,
    tokenize_for_compat,
    token_pair_compatible,
    tokens_compatible,
)

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

    # No VAVOO_COUNTRIES-verified alias for this code - several display
    # names can still map to it (e.g. "cz" <- "Czech"/"Czech Republic",
    # "us" <- "America"/"USA"/"United States"). Picking dict-insertion
    # order here was a real bug (silently resolved "gb" to "UK" instead
    # of "United Kingdom", which don't match the same catalog string) -
    # deterministically prefer the longest (most specific/complete) name
    # instead, tie-broken alphabetically so the result never depends on
    # dict iteration order (which Python 2 does not guarantee).
    code_candidates = [name for name, c in COUNTRY_CODES.items()
                       if c == lower]
    if code_candidates:
        best = sorted(code_candidates, key=lambda n: (-len(n), n))[0]
        return best.lower(), lower

    # Substring fallback, mirroring vUtils.py's get_country_code() - a
    # group name that embeds a real country name (e.g. "France Sport"
    # contains "France") resolves to that country's EPG feed code. This
    # is what the live plugin actually does for EPG matching, so the
    # generator needs to agree: "France Sport" -> feed code "fr". The
    # proxy query name stays the original input though (Vavoo's catalog
    # country field is the literal "France Sport", not "France" - only
    # the feed code should borrow from the matched country).
    #
    # Deliberately one-directional: only "country name is a substring
    # of the input" (name_lower in lower), never the reverse ("input is
    # a substring of the country name"). The reverse direction is what
    # made a short input like "Ira" or "Korea" spuriously match against
    # any country name that happens to *contain* those letters
    # (formerly picked "United Arab Emirates" for "Ira" - "ira" is
    # buried inside "emIRAtes" - or an arbitrary Korea) with nothing
    # like the "France Sport" use case to justify it: any real
    # abbreviation-style input (e.g. "UK") is already resolved by the
    # exact-name-match branch above via its own country_codes entry, so
    # this fallback never legitimately needs that direction.
    substring_candidates = [
        name for name in COUNTRY_CODES if name.lower() in lower]
    if substring_candidates:
        # Prefer a VAVOO_COUNTRIES-verified name first (this is what
        # makes "France Sport" reliably resolve via "France" rather
        # than any other substring hit), then the longest/most specific
        # name, alphabetically tie-broken so the result never depends
        # on Python's dict iteration order.
        vavoo_hits = [n for n in substring_candidates
                      if n.lower() in vavoo_lower]
        pool = vavoo_hits or substring_candidates
        best = sorted(pool, key=lambda n: (-len(n), n))[0]
        return lower, COUNTRY_CODES[best]

    return lower, lower


# Name-cleaning / token-compatibility helpers live in epg_name_utils.py
# (imported above) - single source of truth shared with VavooEPGMatcher
# in vUtils.py, so the two can no longer silently drift apart the way
# two independently hand-maintained copies could.


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


class EmptyResultError(Exception):
    """Raised when a fetch technically succeeded (no HTTPError) but
    returned nothing usable - zero Vavoo channels for the query, or an
    epg_<cc>.xml that parsed to zero channel entries. Deliberately
    distinct from a 404: the caller must NOT write an output file for
    this case, since main()'s "generated" write happens unconditionally
    otherwise and would silently overwrite a previously-good curated
    file with an empty one on a bad/typo'd query or a transient feed
    blip - exactly what wiped France's real data out via an automated
    CI run once already."""


def generate_for_country(
        query_name,
        feed_code,
        proxy_host,
        proxy_port,
        threshold):
    """query_name is what vavoo_proxy's /channels endpoint expects
    (Vavoo's own raw catalog country field - a display name, e.g.
    "portugal"); feed_code is the 2-letter code epg_<cc>.xml is named
    with (e.g. "pt"). See resolve_country()."""
    channels = fetch_vavoo_channels(proxy_host, proxy_port, query_name)
    print("{}: {} Vavoo channels".format(feed_code.upper(), len(channels)))
    if not channels:
        raise EmptyResultError(
            "0 Vavoo channels for query '{}' - bad country name, or "
            "the catalog genuinely has none right now".format(query_name))

    feed_index = fetch_feed_index(feed_code)
    print("{}: {} feed channels".format(feed_code.upper(), len(feed_index)))
    if not feed_index:
        raise EmptyResultError(
            "epg_{}.xml parsed to 0 channels - missing/empty feed, or "
            "a transient fetch failure".format(feed_code))

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
    if not (0.0 <= args.threshold <= 1.0):
        parser.error("--threshold must be between 0.0 and 1.0")

    countries = VAVOO_COUNTRIES if args.all else args.countries

    # cc -> (matched_dict, review_by_name_dict), accumulated across the
    # whole run. Some VAVOO_COUNTRIES entries have no epg_<cc>.xml feed
    # of their own and resolve through resolve_country()'s substring
    # fallback to an EXISTING country's code instead (e.g. "France
    # Sport" -> "fr", same as "France" itself). Without merging, writing
    # each country's own result directly let a later entry silently
    # overwrite an earlier, better one sharing the same code - confirmed
    # in production: "France Sport" (a narrow, sports-only catalog
    # bucket) clobbered "France"'s real ~155-entry curated file with its
    # own much smaller match set whenever --all ran both, since it's
    # listed right after "France" in VAVOO_COUNTRIES.
    combined = {}

    generated = 0
    skipped_no_feed = 0
    errors = 0
    for country in countries:
        query_name, cc = resolve_country(country)
        print("'{}' resolved to: proxy query='{}', feed code='{}'".format(
            country, query_name, cc))
        # Fetch/match AND the file writes below all live inside this one
        # try - a filesystem error on the write step used to be able to
        # propagate straight out of this loop and abort every remaining
        # country in an --all run instead of being counted and skipped.
        try:
            matched, review = generate_for_country(
                query_name, cc, args.proxy_host, args.proxy_port,
                args.threshold)

            prev_matched, prev_review = combined.get(cc, ({}, {}))
            merged_matched = dict(prev_matched)
            merged_matched.update(matched)
            merged_review = dict(prev_review)
            for r in review:
                existing = merged_review.get(r["name"])
                if not existing or r["best_score"] > existing["best_score"]:
                    merged_review[r["name"]] = r
            combined[cc] = (merged_matched, merged_review)
            review_list = sorted(
                merged_review.values(),
                key=lambda r: r["best_score"], reverse=True)

            out_path = join(
                args.output_dir, "vavoo_channels_{}.json".format(cc))
            review_path = join(
                args.output_dir, "vavoo_channels_{}.review.json".format(cc))

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(
                    merged_matched, f, indent=2, sort_keys=True,
                    ensure_ascii=False)
            with open(review_path, "w", encoding="utf-8") as f:
                json.dump(review_list, f, indent=2, ensure_ascii=False)

            print("{}: {} auto-matched -> {}".format(
                cc, len(merged_matched), out_path))
            print("{}: {} need manual review -> {}".format(
                cc, len(review_list), review_path))
            generated += 1
        except EmptyResultError as e:
            print("{}: skipped ({})".format(cc, e))
            skipped_no_feed += 1
        except HTTPError as e:
            if e.code == 404:
                print("{}: skipped (no epg_{}.xml feed)".format(cc, cc))
                skipped_no_feed += 1
            else:
                print("ERROR generating {}: HTTP {} - {}".format(
                    cc, e.code, e))
                errors += 1
        except Exception as e:
            print("ERROR generating {}: {}".format(cc, e))
            errors += 1

    print(
        "\n{} generated, {} skipped (no feed/empty result), {} errors".format(
            generated,
            skipped_no_feed,
            errors))

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
