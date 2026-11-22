# -*- coding: utf-8 -*-
"""Country / category separators with unicode and byte names (Python 2:
non-ASCII byte literals beside unicode raised on every catalog group)."""
from __future__ import print_function
import os
import sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402,F401
from harness import check, finish               # noqa: E402
import vavoo.vUtils as vu                       # noqa: E402
import vavoo.vavoo_proxy as vp                  # noqa: E402
import vavoo.bouquet_manager as bm              # noqa: E402

U = u"Italy ➾ Sport"
B = U.encode("utf-8") if sys.version_info[0] == 2 else U
for label, name in (("unicode", U), ("str", B)):
    check(vu.get_country_code(name) == "it", "get_country_code(%s)" % label)
    check(vu.get_country_code_from_bouquet_name(name) == "it", "from_bouquet_name(%s)" % label)
    check(vp._base_country_from_group(name) == "Italy", "_base_country_from_group(%s)" % label)
    check(vp._category_from_group(name) == "Sport", "_category_from_group(%s)" % label)
    check(bm._build_bouquet_filename(name, "hierarchical") == "userbouquet.vavoo_italy_sport.tv",
          "_build_bouquet_filename(%s)" % label)
    check(bm._bouquet_country_prefix(name) == "italy", "_bouquet_country_prefix(%s)" % label)
    check(bm.is_bouquet_exported(name) in (True, False), "is_bouquet_exported(%s) answers" % label)
check(vu.get_country_code(u"Italy") == "it" and vu.get_country_code(u"United Kingdom") == "gb",
      "plain unicode names")
check(vp._base_country_from_group(u"Italia » Calcio") == "Italia", "» separator, unicode")
finish()
