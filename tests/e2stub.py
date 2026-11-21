# -*- coding: utf-8 -*-
"""Import hook that fabricates any Enigma2 module/class on demand, so
the real plugin.py can be imported (and its plain-Python logic run)
without Enigma2. Only names under the prefixes below are faked."""
import sys
import types
try:
    import importlib.abc
    import importlib.machinery
    _PY3 = True
except ImportError:          # Python 2: the old import hooks
    _PY3 = False

FAKE_ROOTS = ("enigma", "Components", "Screens", "Tools", "Plugins", "skin",
              "twisted", "ServiceReference", "boxbranding", "Screen")


class AnyMeta(type):
    """Class-level attribute access (MessageBox.TYPE_ERROR, ...)."""
    def __getattr__(cls, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return Any()


class Any(AnyMeta("AnyBase", (object,), {})):
    value = 0

    def __init__(self, *a, **k):
        pass

    def __call__(self, *a, **k):
        return Any()

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return Any()

    def __getitem__(self, k):
        return Any()

    def __setitem__(self, k, v):
        pass

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return False

    __nonzero__ = __bool__

    def __int__(self):
        return 0

    def __index__(self):
        return 0

    def __float__(self):
        return 0.0

    def __str__(self):
        return ""

    def __add__(self, o):
        return o

    __radd__ = __add__

    def __mul__(self, o):
        return 0

    __rmul__ = __mul__

    def __lt__(self, o):
        return False

    __gt__ = __le__ = __ge__ = __lt__


_class_cache = {}


class FakeModule(types.ModuleType):
    __path__ = []

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        key = (self.__name__, name)
        if key not in _class_cache and name.replace("_", "").isupper() and name.upper() == name:
            # constants (RT_HALIGN_LEFT, ...): numbers, as on a box
            _class_cache[key] = 0
        if key not in _class_cache:
            # lower-case names are usually singletons/functions,
            # CamelCase ones classes that get subclassed.
            if name[:1].isupper() or name[:1] == 'e' and name[1:2].isupper():
                _class_cache[key] = AnyMeta(str(name), (Any,), {})
            else:
                _class_cache[key] = Any()
        return _class_cache[key]


if _PY3:
    class Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
        def find_spec(self, fullname, path, target=None):
            if fullname.split(".")[0] in FAKE_ROOTS:
                return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
            return None

        def create_module(self, spec):
            return FakeModule(spec.name)

        def exec_module(self, module):
            pass
else:
    class Finder(object):
        def find_module(self, fullname, path=None):
            if fullname.split(".")[0] in FAKE_ROOTS:
                return self
            return None

        def load_module(self, fullname):
            if fullname in sys.modules:
                return sys.modules[fullname]
            module = FakeModule(fullname)
            module.__loader__ = self
            sys.modules[fullname] = module
            parent, _sep, child = fullname.rpartition(".")
            if parent and parent in sys.modules:
                setattr(sys.modules[parent], child, module)
            return module


def install():
    sys.meta_path.insert(0, Finder())
