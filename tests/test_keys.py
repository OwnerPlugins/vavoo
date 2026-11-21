# -*- coding: utf-8 -*-
"""The players' keys on the real keymaps of OpenATV, OpenPLi and OpenViX:
Enigma2's dispatch (eActionMap::keyPressed - key lists by priority, the
first that knows the action takes the key) simulated over the plugin's
own key lists, its keymap.xml and Enigma2's own handlers the players are
built from (main menu, seek, arrow seek, audio, subtitles, show/hide)."""
from __future__ import print_function
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import harness                                  # noqa: E402
from harness import check, finish, Session      # noqa: E402
plugin = harness.plugin
OWN = harness.PLUGIN_DIR + "/keymap.xml"
IMAGES = {"OpenATV": "oatv", "OpenPLi": "opli", "OpenViX": "ovix"}

ns = {}
exec(open(os.path.join(HERE, "data", "keymaps", "opli", "keyids.py")).read(), ns)
KEYIDS = ns["KEYIDS"]


def read_keymap(path, into=None):
    """{context: [(key, flags, action)]}, generic device only, file order."""
    into = {} if into is None else into
    for m in ET.parse(path).getroot().findall("map"):
        rows = into.setdefault(m.get("context"), [])
        for k in m.findall("key"):
            rows.append((k.get("id"), set(k.get("flags")), k.get("mapto") or k.get("mapTo")))
    return into


print("== keymap.xml itself")
own = read_keymap(OWN)
check(sorted(own) == sorted([plugin.PLAYER_KEYS, plugin.LIST_KEYS, plugin.MAIN_KEYS]),
      "its contexts: %s" % ", ".join(sorted(own)))
rows = [r for ctx in sorted(own) for r in own[ctx]]
check(all(k in KEYIDS for k, _f, _a in rows), "every key id is a known key (keyids.py)")
check(all(f <= set("mbrl") for _k, f, _a in rows), "only the flags m, b, r, l (older images know no others)")
for ctx, key in sorted(set((c, k) for c in own for k, _f, _a in own[c])):
    flags = [f for k, f, _a in own[ctx] if k == key]
    every = set()
    for f in flags:
        every |= f
    overlap = sum(len(f) for f in flags) != len(every)
    if every != set("mbrl") or overlap:
        check(False, "%s: each event exactly once (%r)" % (key, flags))
check(True, "every key takes all its events (press, release, repeat, hold), each once")


class RAM(object):
    """ActionMap recorder."""
    def __init__(self, contexts, actions, prio=0):
        self.contexts, self.actions, self.prio = contexts, actions, prio
        self.enabled = True
        self.disabled = set()


plugin.ActionMap = RAM
CALLS = []


def spy(name):
    return lambda *a: CALLS.append((name,) + a)


def e2(name):
    return lambda *a: CALLS.append(("E2:" + name,) + a)


def e2_maps(family, screen_cls, seekable, arrows, menu=True, showhide=False):
    """Enigma2's own key lists of a player built from InfoBarMenu,
    InfoBarSeek, InfoBarAudioSelection, InfoBarSubtitleSupport (and
    InfoBarShowHide) - as in each image's InfoBarGenerics.py."""
    def own_or_e2(method):
        # a method the plugin's class defines itself wins (Python MRO)
        for klass in screen_cls.__mro__:
            if klass.__module__.endswith("vavoo.plugin") and method in vars(klass):
                return ("plugin", method)
        return ("E2", method)

    out = []
    if menu:
        if family == "OpenATV":
            out.append(RAM(["InfoBarMenuActions"], {"showMenu": own_or_e2("showMainMenu"),
                                                     "showSetup": ("E2", "setup menu")}, 0))
        else:
            out.append(RAM(["InfobarMenuActions"], {"mainMenu": own_or_e2("mainMenu")}, 0))
    seek = {a: own_or_e2(a) for a in ("playpauseService", "pauseService", "unPauseService",
                                      "seekFwd", "seekBack")}
    seek.update({"okButton": ("E2", "okButton"), "seekFwdManual": ("E2", "seekFwdManual"),
                 "seekBackManual": ("E2", "seekBackManual")})
    if family == "OpenATV":
        seek.update({"left": own_or_e2("seekBack"), "right": own_or_e2("seekFwd"),
                     "SeekbarFwd": ("E2", "seekbar"), "SeekbarBack": ("E2", "seekbar")})
        for d in "134679":
            seek["seekdef:" + d] = ("E2", "seekdef")
    sm = RAM(["InfobarSeekActions"], seek, -1)
    sm.enabled = seekable
    out.append(sm)
    if family == "OpenATV" and arrows:
        out.append(RAM(["InfobarArrowSeekActions"], {a: ("E2", "arrow seek " + a)
                                                       for a in ("left", "right", "up", "down")}, -1))
        sm.disabled = {"left", "right"}
    audio = {"audioSelection": ("E2", "audioSelection")}
    if family == "OpenATV":
        audio["yellow_key"] = ("E2", "audioSelection")
    out.append(RAM(["InfobarAudioSelectionActions"], audio, 0))
    out.append(RAM(["InfobarSubtitleSelectionActions"], {"subtitleSelection": ("E2", "subtitleSelection")}, 0))
    if showhide:
        out.append(RAM(["InfobarShowHideActions"], {"toggleShow": ("E2", "toggleShow"),
                                                    "hide": ("E2", "hide")}, 1))
    return out


def dispatch(keymap, maps, key, flag):
    """What runs for one event: the key lists by priority (ties: bound
    first), each list's contexts in order, the keymap's entries for the
    key and event in file order; the first list knowing the action."""
    order = sorted(range(len(maps)), key=lambda i: (maps[i].prio, i))
    for i in order:
        m = maps[i]
        if not m.enabled:
            continue
        for context in m.contexts:
            for k, flags, action in keymap.get(context, []):
                if k != key or flag not in flags:
                    continue
                if action in m.actions and action not in m.disabled:
                    return m, action
    return None, None


def candidates(keymap, maps, key, flag):
    """Every (list, action) the event reaches, in Enigma2's order."""
    order = sorted(range(len(maps)), key=lambda i: (maps[i].prio, i))
    for i in order:
        m = maps[i]
        if not m.enabled:
            continue
        for context in m.contexts:
            for k, flags, action in keymap.get(context, []):
                if k == key and flag in flags and action in m.actions and action not in m.disabled:
                    yield m, action


def press(keymap, maps, screen, key, flag):
    """What runs: the first list whose function takes the key (a
    function returning 0 lets it go on, as in ActionMap.action())."""
    for m, action in candidates(keymap, maps, key, flag):
        target = m.actions[action]
        del CALLS[:]
        if isinstance(target, tuple):
            where, method = target
            if where != "plugin":
                return "E2:" + method
            result = getattr(screen, method)()
        else:
            result = target()
        if result == 0 and not CALLS:
            continue
        return CALLS[0] if CALLS else "nothing"
    return None


# ------------------------------------------------------------ the live player
P_SPIES = ("OkPressed", "back", "leavePlayer", "nextitem", "previousitem", "key_left",
           "key_right", "toggle_favourite", "chooseStreamSource", "list_key", "mainMenu",
           "showMainMenu", "open_guide", "_call_infobar", "toggle_record",
           "playpauseService", "pauseService", "unPauseService", "seekFwd", "seekBack",
           "key_digit", "recall")


class Nav(object):
    def getCurrentlyPlayingServiceReference(self):
        return None


def build_player():
    cls = plugin.Playstream2
    cls.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
    cls.__getitem__ = lambda self, k: self.widgets[k]
    obj = cls.__new__(cls)
    obj.widgets = {}
    obj.onClose, obj.onExecBegin, obj.onLayoutFinish, obj.onFirstExecBegin = [], [], [], []
    for name in P_SPIES:
        setattr(obj, name, spy(name))
    s = Session()
    s.nav = Nav()
    s.dialog_stack = []
    cls.__init__(obj, s, "RAI 1", "http://127.0.0.1:4323/vavoo?channel=abc", 0,
                 None, [("RAI 1", "http://127.0.0.1:4323/vavoo?channel=abc")])
    plugin.ACTIVE["player"] = None
    return obj


player = build_player()
own_map = player.widgets["vavoo_keys"]
check(own_map.contexts == [plugin.PLAYER_KEYS] and own_map.prio == plugin.PLAYER_KEYS_PRIO < -1,
      "live player: its own keys, above Enigma2's seek (-1) and menu (0)")
P_MAPS = [v for v in player.widgets.values() if isinstance(v, RAM)]

P_EXPECT = [
    ("KEY_OK", ("OkPressed",)), ("KEY_EXIT", ("back",)), ("KEY_BACK", ("back",)),
    ("KEY_RED", ("back",)), ("KEY_STOP", ("leavePlayer",)),
    ("KEY_UP", ("nextitem",)), ("KEY_DOWN", ("previousitem",)),
    ("KEY_CHANNELUP", ("nextitem",)), ("KEY_CHANNELDOWN", ("previousitem",)),
    ("KEY_LEFT", ("key_left",)), ("KEY_RIGHT", ("key_right",)),
    ("KEY_GREEN", ("toggle_favourite",)), ("KEY_YELLOW", ("chooseStreamSource",)),
    ("KEY_BLUE", ("list_key",)), ("KEY_MENU", ("mainMenu",)),
    ("KEY_INFO", ("open_guide",)), ("KEY_EPG", ("open_guide",)),
    ("KEY_AUDIO", ("_call_infobar", "audioSelection")),
    ("KEY_SUBTITLE", ("_call_infobar", "subtitleSelection")),
    ("KEY_RECORD", ("toggle_record",)),
    ("KEY_PLAY", ("playpauseService",)), ("KEY_PAUSE", ("playpauseService",)),
    ("KEY_PLAYPAUSE", ("playpauseService",)),
    ("KEY_FASTFORWARD", ("seekFwd",)), ("KEY_REWIND", ("seekBack",)),
] + [("KEY_%d" % d, ("key_digit", d)) for d in range(10)]


def run_table(title, cls, screen, plugin_maps, expect, showhide=False, menu=True):
    for image, folder in sorted(IMAGES.items()):
        keymap = read_keymap(os.path.join(HERE, "data", "keymaps", folder, "keymap.xml"))
        read_keymap(OWN, keymap)
        for seekable, arrows in ((False, False), (True, False), (True, True), (False, True)):
            if arrows and image != "OpenATV":
                continue
            maps = e2_maps(image, cls, seekable, arrows, menu=menu, showhide=showhide) + plugin_maps
            bad = []
            for key, want in expect:
                got = press(keymap, maps, screen, key, "m")
                if got != want:
                    bad.append("%s -> %r (want %r)" % (key, got, want))
                for flag in "brl":
                    got = press(keymap, maps, screen, key, flag)
                    if got not in (None, "nothing"):
                        if not (flag == "r" and key in ("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT")
                                and got == want):
                            bad.append("%s %s -> %r" % (key, flag, got))
            what = "%s, %s, %s%s" % (title, image, "seekable" if seekable else "live",
                                     ", arrow seek on" if arrows else "")
            check(not bad, what + ": every key does its one thing" + ("" if not bad else
                                                                      "\n        " + "\n        ".join(bad)))


print("== the live player, with keymap.xml")
run_table("live player", plugin.Playstream2, player, P_MAPS, P_EXPECT)

print("== the live player where keymap.xml could not be loaded (the image's names)")
fallback = [m for m in P_MAPS if m is not own_map]
check(all(m.prio == plugin.PLAYER_KEYS_PRIO + 1 for m in fallback if m.contexts != ["InfobarShowHideActions"]),
      "fallback lists: above Enigma2's seek (-1), below the plugin's own keys")


# Left as they were, only where keymap.xml cannot be loaded (the image
# gives the two the same name): OpenPLi's YELLOW release is its audio menu
# (reached only when the source choice opened no window), OpenViX's LEFT /
# RIGHT release is "seekBack" / "seekFwd" like << >>.
FALLBACK_KNOWN = {("OpenPLi", "KEY_YELLOW"), ("OpenViX", "KEY_LEFT"), ("OpenViX", "KEY_RIGHT")}


def both(keymap, maps, screen, key):
    """What runs on the press and on the release."""
    return [press(keymap, maps, screen, key, f) for f in "mb"]


for image, folder in sorted(IMAGES.items()):
    keymap = read_keymap(os.path.join(HERE, "data", "keymaps", folder, "keymap.xml"))
    for seekable in (False, True):
        maps = e2_maps(image, plugin.Playstream2, seekable, image == "OpenATV") + fallback
        got, twice = {}, []
        for key, want in P_EXPECT:
            ran = [r for r in both(keymap, maps, player, key) if r not in (None, "nothing")]
            got[key] = ran[0] if ran else None
            if ran[:1] == [("leavePlayer",)]:
                ran = ran[:1]          # (closed on the press: the release goes to the screen below)
            if (image, key) in FALLBACK_KNOWN:
                ran = ran[:1]
            if len(ran) > 1:
                twice.append("%s: %r" % (key, ran))
        what = "%s%s" % (image, ", seekable" if seekable else "")
        check(not twice, what + ": no key runs twice (press and release)" +
              ("" if not twice else " - " + "; ".join(twice)))
        check(got["KEY_MENU"] in (("mainMenu",), ("showMainMenu",)), "%s: MENU = the options (%r)" % (what, got["KEY_MENU"]))
        check(got["KEY_PAUSE"] in (("pauseService",), ("playpauseService",)), "%s: PAUSE = pause live (%r)" % (what, got["KEY_PAUSE"]))
        player._shift_state = "paused"
        played = press(keymap, maps, player, "KEY_PLAY", "m")
        player._shift_state = None
        check(played in (("playpauseService",), ("unPauseService",)), "%s: PLAY (paused) = play on (%r)" % (what, played))
        check(got["KEY_EPG"] == ("open_guide",) and got["KEY_INFO"] == ("open_guide",)
              and got["KEY_YELLOW"] == ("chooseStreamSource",) and got["KEY_GREEN"] == ("toggle_favourite",)
              and got["KEY_BLUE"] == ("list_key",) and got["KEY_RED"] == ("back",)
              and got["KEY_LEFT"] == ("key_left",) and got["KEY_1"] == ("key_digit", 1)
              and got["KEY_UP"] == ("nextitem",), "%s: INFO / EPG, colours, LEFT, digits, UP" % what)

print("== before: what OpenATV did with MENU and PAUSE (the user's report)")
OLD_CONTEXTS = ['MoviePlayerActions', 'MovieSelectionActions', 'MediaPlayerActions', 'EPGSelectActions',
                'OkCancelActions', 'InfobarShowHideActions', 'InfobarActions', 'DirectionActions',
                'InfobarSeekActions', 'ColorActions', 'NumberActions', 'InfobarChannelSelection',
                'InfobarInstantRecord']
keymap = read_keymap(os.path.join(HERE, "data", "keymaps", "oatv", "keymap.xml"))
old_actions = RAM(OLD_CONTEXTS, {k: v for k, v in player.widgets["actions"].actions.items()
                                 if k not in ("showMenu", "mainMenu", "menu")}, -1)
old_menu = RAM(["InfoBarMenuActions"], {"showMenu": ("E2", "showMainMenu")}, 0)
old = [m for m in e2_maps("OpenATV", plugin.Playstream2, False, False) if m.contexts != ["InfoBarMenuActions"]]
old += [old_menu, old_actions, player.widgets["ShowHideActions"]]
check(press(keymap, old, player, "KEY_MENU", "m") == "E2:showMainMenu", "MENU: Enigma2's main menu (reproduced)")
check(press(keymap, old, player, "KEY_PAUSE", "m") is None and press(keymap, old, player, "KEY_PLAY", "m") is None,
      "PAUSE / PLAY: nothing on a live stream (reproduced)")
check(both(keymap, old, player, "KEY_RED") == [("back",), ("back",)],
      "RED: back() on the press and again on the release (reproduced - behind live: to live, then closed)")

# ------------------------------------------------------- the recording player
print("== the recording player, with keymap.xml")
R_SPIES = ("play_pause", "leave", "jump", "options", "_call")
cls = plugin.VavooRecordingPlayer
cls.__setitem__ = lambda self, k, v: self.widgets.__setitem__(k, v)
cls.__getitem__ = lambda self, k: self.widgets[k]
rp = cls.__new__(cls)
rp.widgets = {}
rp.onClose, rp.onExecBegin, rp.onLayoutFinish, rp.onFirstExecBegin = [], [], [], []
for name in R_SPIES:
    setattr(rp, name, spy(name))
s = Session()
s.nav = Nav()
cls.__init__(rp, s, {"path": "/media/hdd/movie/x.ts", "title": "Show", "channel": "RAI 1",
                     "duration": 60, "start": 0})
R_MAPS = [v for v in rp.widgets.values() if isinstance(v, RAM)]
B, S = cls.BIG_STEP, cls.STEP
R_EXPECT = [
    ("KEY_OK", ("play_pause",)), ("KEY_GREEN", ("play_pause",)),
    ("KEY_PLAY", ("play_pause",)), ("KEY_PAUSE", ("play_pause",)), ("KEY_PLAYPAUSE", ("play_pause",)),
    ("KEY_EXIT", ("leave",)), ("KEY_BACK", ("leave",)), ("KEY_RED", ("leave",)), ("KEY_STOP", ("leave",)),
    ("KEY_LEFT", ("jump", -S)), ("KEY_RIGHT", ("jump", S)),
    ("KEY_YELLOW", ("jump", -B)), ("KEY_REWIND", ("jump", -B)),
    ("KEY_BLUE", ("jump", B)), ("KEY_FASTFORWARD", ("jump", B)),
    ("KEY_MENU", ("options",)),
    ("KEY_AUDIO", ("_call", "audioSelection")), ("KEY_SUBTITLE", ("_call", "subtitleSelection")),
    ("KEY_UP", "nothing"), ("KEY_DOWN", "nothing"), ("KEY_INFO", "nothing"), ("KEY_1", "nothing"),
]
run_table("recording player", cls, rp, R_MAPS, R_EXPECT, showhide=True, menu=False)

src = harness.plugin_source()
check("def showMainMenu(self):" in harness.source_of("Playstream2"),
      "the live player answers OpenATV's showMainMenu with its options too")
check(plugin.KEYMAP_LOADED in (True, False) and plugin.load_keymap("/nonexistent/keymap.xml") in (True, False),
      "loading the keymap never raises")
finish()
