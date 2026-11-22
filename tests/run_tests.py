# -*- coding: utf-8 -*-
"""Runs the tests, each in its own process, and sums them up.

    python3 tests/run_tests.py            every test this Python can run
    python3 tests/run_tests.py --quick    without the ffmpeg ones (slow)
    python2.7 tests/run_tests.py          the Python 2 list
    python3 tests/run_tests.py test_guide test_lists   only these

Each test is a plain script (Enigma2 faked by e2env.py / harness.py):
it prints its checks and exits 1 when one fails. Needs `six` and
`requests`; the recording tests need `ffmpeg` / `ffprobe` (skipped
without them)."""
from __future__ import print_function
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY2 = sys.version_info[0] == 2

# tests that record a fake live channel with ffmpeg (fakehls.py)
FFMPEG = ("test_memory", "test_proxy_rec", "test_record", "test_record_disk",
          "test_recservice", "test_shift")
# what runs on Python 2 (the rest uses Python 3 only things in the test
# itself - the plugin code they test is checked there too)
PYTHON2 = ("test_audit", "test_bad_files", "test_direct_keys", "test_epg_match",
           "test_catalog_cache", "test_closed", "test_epg_sources", "test_every_key", "test_factory_reset", "test_keys", "test_list_keys",
           "test_log", "test_proxy_start", "test_proxy_state",
           "test_py2_separators", "test_screens_open", "test_screens_rows", "test_settings_welcome",
           "test_speedups",
           "test_store")
TIMEOUT = 600


def which(name):
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def repo_state():
    """`git status --porcelain` of the checkout (None without git): a
    test must never change a file of the repository."""
    try:
        process = subprocess.Popen(["git", "status", "--porcelain", "--untracked-files=no"],
                                   cwd=os.path.dirname(HERE), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        out = process.communicate()[0]
        return out.decode("utf-8", "replace") if process.returncode == 0 else None
    except Exception:
        return None


def last_line(text):
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def main(argv):
    quick = "--quick" in argv
    wanted = [a[:-3] if a.endswith(".py") else a for a in argv if not a.startswith("-")]
    names = sorted(os.path.basename(p)[:-3] for p in glob.glob(os.path.join(HERE, "test_*.py"))
                   if not p.endswith("test_keys_lib.py"))
    if wanted:
        names = [n for n in names if n in wanted]
    elif PY2:
        names = [n for n in names if n in PYTHON2]
    has_ffmpeg = which("ffmpeg") is not None and which("ffprobe") is not None
    before = repo_state()
    results = []
    started = time.time()
    for name in names:
        if name in FFMPEG and (quick or not has_ffmpeg):
            results.append((name, "skipped", "--quick" if quick else "no ffmpeg / ffprobe", 0.0))
            continue
        t0 = time.time()
        command = [sys.executable, "-B", os.path.join(HERE, name + ".py")]
        process = subprocess.Popen(command, cwd=HERE, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT)
        timer_out = [False]
        try:
            output, _err = _communicate(process, TIMEOUT)
        except _Timeout:
            timer_out[0] = True
            process.kill()
            output = process.communicate()[0]
        took = time.time() - t0
        text = output.decode("utf-8", "replace")
        if timer_out[0]:
            status = "FAILED"
            note = "timed out after %d s" % TIMEOUT
        elif process.returncode == 0:
            status = "ok"
            note = last_line(text)
        else:
            status = "FAILED"
            note = last_line(text)
        if status == "FAILED":
            print("=" * 70)
            print("%s FAILED (exit %s)" % (name, process.returncode))
            print("\n".join(line for line in text.splitlines()
                            if "FAIL" in line or "Error" in line or "Traceback" in line
                            or line.startswith("  File "))[-6000:])
        results.append((name, status, note, took))
        print("%-22s %-8s %6.1f s  %s" % (name, status, took, note))
        sys.stdout.flush()
    after = repo_state()
    if before is not None and after != before:
        changed = sorted(set(after.splitlines()) ^ set(before.splitlines()))
        results.append(("(repository)", "FAILED", "files changed by the tests: %s" % ", ".join(changed), 0.0))
        print("(repository)           FAILED  the tests changed files in the checkout:\n  " + "\n  ".join(changed))
    failed = [r for r in results if r[1] == "FAILED"]
    skipped = [r for r in results if r[1] == "skipped"]
    print("-" * 70)
    print("Python %d.%d: %d tests, %d failed, %d skipped, %.0f s" % (
        sys.version_info[0], sys.version_info[1], len(results), len(failed),
        len(skipped), time.time() - started))
    for name, _status, note, _took in skipped:
        print("  skipped %s (%s)" % (name, note))
    return 1 if failed else 0


class _Timeout(Exception):
    pass


def _communicate(process, timeout):
    """process.communicate() with a time limit, on Python 2 too."""
    if not PY2:
        try:
            return process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            raise _Timeout()
    import threading
    box = {}

    def read():
        box["out"] = process.communicate()

    reader = threading.Thread(target=read)
    reader.daemon = True
    reader.start()
    reader.join(timeout)
    if reader.is_alive():
        raise _Timeout()
    return box["out"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
