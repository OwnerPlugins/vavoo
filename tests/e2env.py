# -*- coding: utf-8 -*-
"""The tests' Enigma2: the plugin package on sys.path, Enigma2 faked
(e2stub.py), a throw-away data folder, and the anonymous statistics off.
Import this first; then `load_plugin()` imports the plugin and returns a
view of its screen modules.

The view is not a module: reading a name finds it in plugin.py or a
ui_*.py beside it, and setting one (`plugin.ask_pin = fake`) replaces it
in every one of those modules that has it - so a test never depends on
which file a function is in."""
from __future__ import print_function
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EXTENSIONS = os.path.join(
    REPO,
    "usr",
    "lib",
    "enigma2",
    "python",
    "Plugins",
    "Extensions")
PLUGIN_DIR = os.path.join(EXTENSIONS, "vavoo")
for _path in (EXTENSIONS, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import e2stub                                   # noqa: E402
e2stub.install()
import Components.Language as _language         # noqa: E402


class _Lang(object):
    def getLanguage(self):
        return "en_EN"

    def addCallback(self, fn):
        pass


_language.language = _Lang()
import Tools.Directories as _directories        # noqa: E402
_directories.SCOPE_PLUGINS = 0
_directories.resolveFilename = lambda scope, path="": \
    os.path.join(os.path.dirname(EXTENSIONS), path)
_directories.fileExists = os.path.exists

DATA = tempfile.mkdtemp(prefix="vavoo_data_")
# Never the real anonymous statistics from a test: they are off while
# this file exists (the plugin's own opt-out switch).
STATS_OFF = os.path.join(DATA, "disable_vavoo_stats")
open(STATS_OFF, "w").close()
import vavoo.vavoo_stats as _stats              # noqa: E402
_stats.STATS_DISABLE_FILE = STATS_OFF
import vavoo.vavoo_store as store               # noqa: E402
store.set_paths(DATA, None, os.path.join(DATA, "tiles"))

_plugin_module = []


def ui_modules():
    """The plugin's screen modules: plugin.py first, then ui_*.py."""
    out = list(_plugin_module)
    for name in sorted(sys.modules):
        module = sys.modules[name]
        if module is not None and name.startswith("vavoo.ui_"):
            out.append(module)
    return out


def patch(name, value):
    """`name` replaced in every screen module that has it (else set on
    plugin.py)."""
    found = False
    for module in ui_modules():
        if name in module.__dict__:
            setattr(module, name, value)
            found = True
    if not found:
        setattr(_plugin_module[0], name, value)


class PluginView(object):
    """Every screen module seen as one (see the docstring at the top)."""

    def __getattr__(self, name):
        for module in ui_modules():
            if hasattr(module, name):
                return getattr(module, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        patch(name, value)

    def __delattr__(self, name):
        for module in ui_modules():
            if name in module.__dict__:
                delattr(module, name)


plugin = PluginView()


def load_plugin():
    """Import the plugin (once) and return the view of its modules."""
    if not _plugin_module:
        import vavoo.plugin as module
        _plugin_module.append(module)
        store.set_paths(DATA, None, os.path.join(DATA, "tiles"))
        patch("STATS_DISABLE_FILE", STATS_OFF)
        # (the proxy's saved catalog in the throw-away folder, never
        # /etc/enigma2)
        module.vavoo_proxy.CATALOG_FILE = os.path.join(
            DATA, "vavoo_catalog.json.gz")
    return plugin


def exit_now(code):
    """End the test process at once, its output flushed. A plain
    sys.exit() runs Python's shutdown while the plugin's daemon threads
    (proxy request handlers, the update check, a recorder) may still be
    writing to stdout - which crashes Python 3 now and then
    ("could not acquire lock for <stdout> at interpreter shutdown", or
    a segfault). The plugin itself never ends that way on a box."""
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        os._exit(code)


def module_of(name):
    """The module that defines a class / function (where its code is)."""
    obj = getattr(plugin, name)
    return sys.modules[getattr(obj, "__module__", _plugin_module[0].__name__)]


def source_of(*names):
    """The source text of classes / functions, joined."""
    import inspect
    return "\n".join(inspect.getsource(getattr(plugin, name))
                     for name in names)


def plugin_source():
    """All the screen modules' source text (plugin.py first)."""
    out = []
    for module in ui_modules():
        path = module.__file__
        if path.endswith((".pyc", ".pyo")):
            path = path[:-1]
        with open(path) as f:
            out.append(f.read())
    return "\n".join(out)
