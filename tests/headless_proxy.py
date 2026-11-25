# -*- coding: utf-8 -*-
"""The plugin's proxy on a machine with no Enigma2: Enigma2 faked as in
the tests (e2env), a throw-away data folder, the catalog downloaded from
the network (setting "auto": Geil first, which needs no token, Vavoo
after). For the EPG channel database workflow
(.github/workflows/generate_epg_channel_db.yml): on GitHub's own runners
it matches each country's live channel list (/channels) against the
guide the plugin itself reads (/epg/<cc>.xml) - no box, no runner of
our own.

    python3 tests/headless_proxy.py [--port 4323] [--source auto]
                                    [--wait 600]

Prints "READY <n> channels (<source>)" once a catalog is in, then serves
until it is killed; "NO CATALOG ..." and exit 1 when none came within
--wait seconds. Not a test (run_tests.py runs test_*.py only)."""
from __future__ import print_function
import argparse
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import e2env                                    # noqa: E402
import vavoo.vavoo_proxy as vp                  # noqa: E402
import vavoo.vUtils as vu                       # noqa: E402


def start(port, source="auto"):
    """The proxy started as run_proxy_in_background() does, on `port`,
    the catalog setting `source`. Returns its thread."""
    vp.PORT = port
    vu.PORT = port
    vp.BOOTING_FILE = os.path.join(e2env.DATA, "vavoo_proxy_booting")
    vp.CATALOG_FILE = os.path.join(e2env.DATA, "vavoo_catalog.json.gz")
    vp.catalog_setting = lambda: source
    vp.proxy = vp.VavooProxy()
    thread = threading.Thread(target=vp._proxy_thread_main)
    thread.daemon = True
    thread.start()
    return thread


def wait_ready(seconds, step=2.0):
    """The proxy's state once it serves a catalog, or None after
    `seconds`."""
    deadline = time.time() + seconds
    while True:
        state = vp.proxy_state()
        if state.get("ready") and state.get("channels_count"):
            return state
        if time.time() >= deadline:
            return None
        time.sleep(step)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="The plugin's proxy without Enigma2 (EPG database "
                    "workflow).")
    parser.add_argument("--port", type=int, default=4323)
    parser.add_argument("--source", default="auto",
                        choices=("auto", "geil", "vavoo"))
    parser.add_argument("--wait", type=int, default=600,
                        help="seconds to wait for a catalog (default 600)")
    args = parser.parse_args(argv)
    thread = start(args.port, args.source)
    state = wait_ready(args.wait)
    if state is None:
        state = vp.proxy_state()
        print("NO CATALOG after %d s: %s" % (
            args.wait, state.get("catalog_error") or "no answer"))
        sys.stdout.flush()
        return 1
    print("READY %d channels (%s)" % (
        state.get("channels_count"), state.get("catalog_source")))
    sys.stdout.flush()
    while thread.is_alive():
        thread.join(60)
    return 0


if __name__ == "__main__":
    e2env.exit_now(main())
