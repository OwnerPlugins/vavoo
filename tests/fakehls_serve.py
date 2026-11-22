"""Serves fakehls.FakeChannel (Python 3) and prints its address, for a
Python 2 process to record from."""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fakehls  # noqa: E402

channel = fakehls.FakeChannel()
print(channel.url(), flush=True)
while True:
    time.sleep(1)
