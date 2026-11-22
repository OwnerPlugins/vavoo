#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
The plugin's themes: Prism, Halo, Orbit (the Android app's own themes)
and Classic (this plugin's original skin).

The Android app (pQu4k3r/vavoo_android) draws every screen from two
tables: a `Look` (one theme's colours, corner radii and fonts -
ui/skin/Look.kt) and a `Geo` (where each widget goes, in the
coordinates of this plugin's own Full HD skin - ui/skin/Geo.kt, which
started as a copy of skin/fhd/defaultListScreen.xml). Both tables are
carried over here unchanged, and the skin XML of each screen is built
from them for whatever resolution the box runs at - so a theme looks
on the box the way it looks in the app, measure for measure.

Classic is not built here: it stays the hand-written XML files under
skin/{hd,fhd,wqhd}/, untouched. Every builder returns None for it and
the caller loads the file it always loaded. That also makes Classic
the safety net: if a built skin cannot be used, plugin.py falls back
to the XML.

No Enigma2 imports, on purpose: everything in this module can be run
and tested off the box (and make_theme_assets.py, which draws the
PNGs the built skins refer to, takes its sizes and colours from here).
"""
from __future__ import absolute_import, print_function

from os.path import dirname, join

MODERN_THEMES = ("prism", "halo", "orbit")
THEMES = MODERN_THEMES + ("classic",)
DEFAULT_THEME = "prism"

# Width of the coordinate space every number below is written in.
BASE_WIDTH = 1920
BASE_HEIGHT = 1080

PLUGIN_DIR = dirname(__file__)

# ---------------------------------------------------------------------
# Looks (Look.kt). Colours are written the Android way, "#RRGGBB" or
# "#AARRGGBB" with AA = opacity (FF opaque) - e2_color() turns them
# into Enigma2's, whose first byte is the transparency instead.
# ---------------------------------------------------------------------
LOOKS = {
    # Vavoo's violet, made modern (the app's default).
    "prism": {
        "bg": "#1a0c2c",
        "selected": "#8b3fd9", "selected2": "#c2449c",
        "panel": "#D91A0C2C", "panel_stroke": "#55d38bff",
        "bar": "#EB1A0C2C", "hilite": "#e3b4ff", "glow": "#338b3fd9",
        "guide_bg": "#F01a0c2c", "guide_bg_over": "#B01a0c2c",
        "key_colors": ("#ff4f6a", "#3fdc8e", "#ffc94f", "#5a8cff"),
        "key_bg": "#D91A0C2C", "key_stroke": "#33d38bff",
        "panel_radius": 28, "key_radius": 18,
        "frame_radius": 16, "sel_radius": 14,
        "font": ("vvPrism", "Lexend-Regular.ttf"),
        "font_bold": ("vvPrismB", "Lexend-SemiBold.ttf"),
        "grid_header": "#140924", "grid_name": "#1f0f35",
        "grid_prog": "#26143d", "grid_now": "#3a1d5c",
        "grid_none": "#1a0c2c", "grid_now_line": "#ff7ac6",
        "card": "#E61a0c2c", "card_stroke": "#88d38bff",
        "title": "#f0e0ff", "text": "#e2cdf7", "text_sub": "#c9a8ec",
        "text_dim": "#b08ad6", "accent": "#ff9bd8",
        "progress": ("#d38bff", "#ff7ac6"), "divider": "#4dd38bff",
    },
    # Frosted glass over a blue / teal / violet aurora.
    "halo": {
        "bg": "#0b1226",
        "selected": "#1f9ab8", "selected2": "#6a5ae0",
        "panel": "#26FFFFFF", "panel_stroke": "#4DFFFFFF",
        "bar": "#E60b1226", "hilite": "#8ff0ff", "glow": "#3326c6da",
        "guide_bg": "#F00b1226", "guide_bg_over": "#B00b1226",
        "key_colors": ("#ff5d73", "#4ff0a0", "#ffd24f", "#5aa8ff"),
        "key_bg": "#26FFFFFF", "key_stroke": "#4DFFFFFF",
        "panel_radius": 32, "key_radius": 30,
        "frame_radius": 24, "sel_radius": 18,
        "font": ("vvHalo", "Manrope-Regular.ttf"),
        "font_bold": ("vvHaloB", "Sora-SemiBold.ttf"),
        "grid_header": "#0e1730", "grid_name": "#121c38",
        "grid_prog": "#16223f", "grid_now": "#1d3557",
        "grid_none": "#0b1226", "grid_now_line": "#8ff0ff",
        "card": "#D90b1226", "card_stroke": "#668ff0ff",
        "title": "#f4f7ff", "text": "#d3dcf5", "text_sub": "#a9b4d6",
        "text_dim": "#8a97c2", "accent": "#8ff0ff",
        "progress": ("#8ff0ff", "#c6a8ff"), "divider": "#4d8ff0ff",
    },
    # A cockpit display: teal on graphite, square corners.
    "orbit": {
        "bg": "#0b0f12",
        "selected": "#14917a", "selected2": "#0f6f5f",
        "panel": "#D90a1614", "panel_stroke": "#6639f2c8",
        "bar": "#EB0a1614", "hilite": "#39f2c8", "glow": "#2639f2c8",
        "guide_bg": "#F00a1614", "guide_bg_over": "#B00a1614",
        "key_colors": ("#ff4f6a", "#39f2c8", "#ffb547", "#4f9dff"),
        "key_bg": "#D90a1614", "key_stroke": "#5539f2c8",
        "panel_radius": 6, "key_radius": 4,
        "frame_radius": 4, "sel_radius": 2,
        "font": ("vvOrbit", "Oxanium-Regular.ttf"),
        "font_bold": ("vvOrbitB", "Oxanium-SemiBold.ttf"),
        "grid_header": "#0a1412", "grid_name": "#0f1c1a",
        "grid_prog": "#112321", "grid_now": "#15352f",
        "grid_none": "#0b0f12", "grid_now_line": "#ffb547",
        "card": "#E60a1614", "card_stroke": "#8839f2c8",
        "title": "#e6fff8", "text": "#c6eee4", "text_sub": "#9cc9bd",
        "text_dim": "#7fa79c", "accent": "#39f2c8",
        "progress": ("#39f2c8", "#8ff7df"), "divider": "#4d39f2c8",
    },
}

WHITE = "#ffffff"
BLACK = "#000000"


def normalize_theme(theme):
    """A theme id this module knows, DEFAULT_THEME for anything else."""
    theme = (theme or "").strip().lower()
    return theme if theme in THEMES else DEFAULT_THEME


def is_modern(theme):
    return normalize_theme(theme) in MODERN_THEMES


def parse_color(color):
    """An Android colour string as (red, green, blue, opacity), each
    0-255."""
    text = color.lstrip('#')
    if len(text) == 6:
        return (int(text[0:2], 16), int(text[2:4], 16),
                int(text[4:6], 16), 255)
    if len(text) == 8:
        return (int(text[2:4], 16), int(text[4:6], 16),
                int(text[6:8], 16), int(text[0:2], 16))
    raise ValueError("not a colour: %r" % (color,))


def e2_color(color):
    """An Android colour as an Enigma2 skin colour: "#RRGGBB" when
    opaque, else "#TTRRGGBB" with TT the transparency (Enigma2 counts
    the other way round: 00 is solid, ff is invisible)."""
    red, green, blue, opacity = parse_color(color)
    if opacity >= 255:
        return "#%02x%02x%02x" % (red, green, blue)
    return "#%02x%02x%02x%02x" % (255 - opacity, red, green, blue)


def solid(color):
    """The colour without its transparency, as an Enigma2 colour - for
    a label's backgroundColor (what its text is smoothed against)."""
    red, green, blue, _opacity = parse_color(color)
    return "#%02x%02x%02x" % (red, green, blue)


# ---------------------------------------------------------------------
# Geometry (Geo.kt): LANDSCAPE_PRISM and LANDSCAPE_PRISM_LARGE, which
# every modern theme uses. Rectangles are (x, y, width, height).
# ---------------------------------------------------------------------
_GEO_NORMAL = {
    "list": (152, 170, 640, 650), "list_panel": (130, 150, 684, 690),
    "big_list": (152, 170, 880, 650), "big_panel": (130, 150, 924, 690),
    "row_h": 50, "row_font": 34,
    "name": (116, 864, 707, 54), "name_font": 42,
    "status": (140, 931, 660, 55), "status_font": 34,
    "preview_name": (959, 448, 900, 45), "preview_name_font": 26,
    "preview_frame": (953, 500, 723, 412), "preview": (959, 506, 711, 400),
    "epg": (959, 918, 900, 74), "epg_font": 26,
    "clock": (1472, 92, 300, 96), "clock_font": 48,
    "version": (1748, 53, 158, 28), "version_font": 24,
    "key_x": (58, 355, 652, 948), "key_w": 297, "key_y": 995, "key_h": 59,
    "key_font": 30, "desc_font": 28,
    "menu": (1500, 992, 190, 62), "info": (1710, 992, 150, 62),
    "description": (130, 852, 924, 124),
    "statusbar": (1090, 930, 750, 60), "statusbar_font": 30,
    "toast": (460, 22, 1000, 108), "toast_font": 32,
    "search": (460, 190, 1000, 700),
    "update": (360, 195, 1200, 690),
    "splash_card": (290, 130, 1340, 820),
    "menu_box": (560, 190, 800, 700),
    # the PIN pad (the app's PinPopup), centred
    "pin_box": (610, 330, 700, 420),
}

_GEO_LARGE = dict(_GEO_NORMAL)
_GEO_LARGE.update({
    # (whole rows: 10 of 64, no half row at the bottom)
    "list": (152, 170, 640, 640), "big_list": (152, 170, 880, 640),
    "row_h": 64, "row_font": 44,
    "name": (116, 858, 707, 62), "name_font": 50,
    "status_font": 36,
    "preview_name": (959, 440, 900, 52), "preview_name_font": 36,
    "epg": (959, 916, 900, 76), "epg_font": 32,
    "clock_font": 64,
    "key_font": 34, "desc_font": 32,
    "description": (130, 846, 924, 136),
})


def geo(large=True):
    """The geometry table for large (the app's default) or normal
    text."""
    return _GEO_LARGE if large else _GEO_NORMAL


def text_scale(large):
    """Skin.ts(): sizes that are not in the table grow by a fifth with
    large text."""
    return 1.2 if large else 1.0


def resolution(width):
    """'hd', 'fhd' or 'wqhd' for a desktop width."""
    if width >= 2560:
        return "wqhd"
    if width >= 1920:
        return "fhd"
    return "hd"


RESOLUTIONS = (("hd", 1280), ("fhd", 1920), ("wqhd", 2560))


def scaled(value, width):
    """A Full HD measure on a desktop `width` pixels wide."""
    return int(round(value * width / float(BASE_WIDTH)))


def fonts_to_register(base_dir=None):
    """[(path of the .ttf, name to register it under)] for every
    modern theme - plugin.py hands them to Enigma2's addFont()."""
    font_dir = join(base_dir or PLUGIN_DIR, "fonts")
    out = []
    seen = set()
    for theme in MODERN_THEMES:
        for key in ("font", "font_bold"):
            name, filename = LOOKS[theme][key]
            if name not in seen:
                seen.add(name)
                out.append((join(font_dir, filename), name))
    return out


# ---------------------------------------------------------------------
# Lists: row height, font and icon box of the MultiContent lists.
# ---------------------------------------------------------------------
def _rows(height, row_h):
    return max(1, int(round(height / float(row_h))))


def list_metrics(theme, large, width, kind="list"):
    """What plugin.py's m2list / show_list() need to draw a row of the
    `kind` of list ("list": countries and channels, "search", "menu",
    "big": the settings-wide list of Choose countries / Parental)
    in a modern theme, in real pixels:

      row_h, rows, list_w, list_h   the listbox
      font, font_size               the row text
      icon_x, icon_y, icon_w, icon_h, text_x, text_w

    A row's height is the list's height shared out between its whole
    rows, never a rounded skin value: at 1280 ten rows of 64 * 2/3 =
    42.67 would be nine and a gap in a listbox that only shows whole
    rows.
    """
    theme = normalize_theme(theme)
    table = geo(large)
    if kind == "search":
        row_h = 60 if large else 50
        box_w, box_h = 960, table["search"][3] - 350
        font_size = 28 * text_scale(large)
    elif kind == "menu":
        row_h = table["row_h"]
        box_w = table["menu_box"][2] - 40
        box_h = (table["menu_box"][3] - 110) // row_h * row_h
        font_size = table["row_font"] - 2
    elif kind == "big":
        # the wide list of Choose countries / Parental Control (the
        # settings' list, rows with an icon and a value)
        row_h = table["row_h"]
        box_w, box_h = table["big_list"][2], table["big_list"][3]
        font_size = table["row_font"] - 4
    else:
        row_h = table["row_h"]
        box_w, box_h = table["list"][2], table["list"][3]
        font_size = table["row_font"]
    rows = _rows(box_h, row_h) if kind != "search" else max(1, box_h // row_h)
    list_h = scaled(rows * row_h, width)
    row_px = max(1, list_h // rows)
    list_h = row_px * rows
    list_w = scaled(box_w, width)
    # (plugin.py show_list() for FHD, as the app's SkinList draws it:
    # icon 4/5 of the row high and 3:2, 10 in from the left; the text
    # 20 after it)
    icon_h = scaled(row_h * 4 // 5, width)
    icon_w = scaled((row_h * 4 // 5) * 3 // 2, width)
    icon_x = scaled(10, width)
    text_x = icon_x + icon_w + scaled(10, width)
    look = LOOKS.get(theme)
    return {
        "row_h": row_px, "rows": rows, "list_w": list_w, "list_h": list_h,
        "font": look["font"][0] if look else "Regular",
        "font_bold": look["font_bold"][0] if look else "Regular",
        "font_size": max(8, scaled(font_size, width)),
        "icon_x": icon_x, "icon_y": max(0, (row_px - icon_h) // 2),
        "icon_w": icon_w, "icon_h": icon_h,
        "text_x": text_x,
        "text_w": max(10, list_w - text_x - scaled(10, width)),
        # a row without an icon (menus)
        "plain_x": scaled(15, width),
        "plain_w": max(10, list_w - scaled(25, width)),
    }


# ---------------------------------------------------------------------
# Pictures the built skins use (make_theme_assets.py draws them from
# this very table, so a skin can never refer to a size that was not
# drawn). Sizes in Full HD units; each layer is one of
#   ("box",  x, y, w, h, fill, stroke, stroke_width, radius)
#   ("grad", x, y, w, h, colour_left, colour_right, radius)
#   ("key",  x, y, w, h, fill, stroke, stroke_width, radius,
#            stripe_colour, stripe_width)
#   ("hole", x, y, w, h, radius)     clears what is inside
# "crop" cuts a piece out of the finished picture.
# ---------------------------------------------------------------------
TRANSPARENT = "#00000000"
KEY_NAMES = ("red", "green", "yellow", "blue")
FRAME_CORNERS = ("tl", "tr", "bl", "br")


def asset_specs(theme):
    """{name: {"size": (w, h), "layers": [...], "crop": (x, y, w, h)}}
    for one modern theme."""
    look = LOOKS[normalize_theme(theme)]
    radius = look["panel_radius"]
    key_radius = look["key_radius"]
    frame_radius = look["frame_radius"]
    sel_radius = look["sel_radius"]
    small_radius = min(14, key_radius)
    specs = {}

    def box(name, w, h, fill, stroke=TRANSPARENT, stroke_w=0, rad=0):
        specs[name] = {"size": (w, h), "layers": [
            ("box", 0, 0, w, h, fill, stroke, stroke_w, rad)]}

    def grad(name, w, h, left, right, rad):
        specs[name] = {"size": (w, h), "layers": [
            ("grad", 0, 0, w, h, left, right, rad)]}

    # panels behind the lists (BaseSkinActivity.addPanel)
    box("panel_list", 684, 690, look["panel"], look["panel_stroke"], 2, radius)
    box("panel_big", 924, 690, look["panel"], look["panel_stroke"], 2, radius)

    # the preview window's frame with its soft halo (previewFrame()):
    # 14 of halo all round a 723x412 frame; the video itself sits 6
    # inside the frame
    frame_w, frame_h = 723 + 28, 412 + 28
    frame_layers = [
        ("box", 0, 0, frame_w, frame_h, look["glow"], TRANSPARENT, 0,
         frame_radius + 14),
        ("box", 14, 14, 723, 412, BLACK, look["selected"], 4, frame_radius),
    ]
    specs["frame"] = {"size": (frame_w, frame_h), "layers": frame_layers}
    # The video rectangle has square corners; the app rounds them
    # (frame radius - 4). Four small pictures go over the video's
    # corners and repaint what the rounding leaves outside: the frame
    # picture again, with a rounded hole where the video is, cut down
    # to each corner. Where exactly is worked out in real pixels - see
    # frame_layout().
    for tag in FRAME_CORNERS:
        specs["frame_" + tag] = {
            "size": (frame_w, frame_h), "layers": frame_layers,
            "corner": tag}

    # colour keys (Skin.colorKey): the dark key with its colour as a
    # stripe on its left edge; MENU / INFO keys without one
    for name, color in zip(KEY_NAMES, look["key_colors"]):
        specs["key_" + name] = {"size": (285, 63), "layers": [
            ("key", 0, 0, 285, 63, look["key_bg"], look["key_stroke"], 1,
             key_radius, color, 12)]}
        specs["skey_" + name] = {"size": (225, 66), "layers": [
            ("key", 0, 0, 225, 66, look["key_bg"], look["key_stroke"], 1,
             key_radius, color, 12)]}
    box("key_menu", 190, 62, look["key_bg"], look["key_stroke"], 1, key_radius)
    box("key_info", 150, 62, look["key_bg"], look["key_stroke"], 1, key_radius)

    # the selected row (Skin.selection): a left-to-right gradient.
    # Drawn exactly one listbox row big - see asset_pixel_size().
    for tag, large in (("l", True), ("n", False)):
        row_h = geo(large)["row_h"]
        for name, w, h, kind in (
                ("sel_list_", 640, row_h, "list"),
                ("sel_big_", 880, row_h, "list"),
                ("sel_menu_", 760, row_h, "menu"),
                ("sel_search_", 960, 60 if large else 50, "search")):
            grad(name + tag, w, h, look["selected"], look["selected2"],
                 sel_radius)
            specs[name + tag]["row"] = (kind, large)

    # dialogs
    box("dialog_search", 1008, 708, look["bg"], look["selected"], 3, radius)
    box("search_input", 960, 60, look["bg"], look["panel_stroke"], 2,
        small_radius)
    box("dialog_menu", 800, 700, look["guide_bg"], look["progress"][0], 3,
        radius)
    box("dialog_update", 1200, 690, look["guide_bg"], look["progress"][0], 3,
        radius)
    box("dialog_inner", 1110, 450, look["grid_prog"], look["divider"], 2,
        small_radius)
    box("dialog_inner_s", 1110, 330, look["grid_prog"], look["divider"], 2,
        small_radius)
    box("toast", 1000, 108, look["bar"], look["progress"][0], 3, radius)
    box("dialog_pin", 700, 420, look["guide_bg"], look["progress"][0], 3,
        radius)
    # the guide grid's panel, over the background / over the video
    box("guide_panel", 1840, 940, look["guide_bg"], look["panel_stroke"], 2,
        radius)
    box("guide_panel_over", 1840, 940, look["guide_bg_over"],
        look["panel_stroke"], 2, radius)

    # the start screen's card with its halo (SplashActivity.buildModern)
    specs["splash_card"] = {"size": (1340 + 36, 820 + 36), "layers": [
        ("box", 0, 0, 1376, 856, look["glow"], TRANSPARENT, 0, radius + 20),
        ("box", 18, 18, 1340, 820, look["card"], look["card_stroke"], 2,
         radius + 8)]}
    box("splash_track", 1190, 14, "#33ffffff", TRANSPARENT, 0, small_radius)
    grad("splash_fill", 1190, 14, look["progress"][0], look["progress"][1],
         small_radius)

    # the player (PlayerActivity.buildLandscapeBar / overlayPanel /
    # buildChannelList / buildInfoOverlay)
    box("player_bar", 1800, 270, look["bar"], look["panel_stroke"], 2, radius)
    box("player_track", 190, 8, "#40ffffff", TRANSPARENT, 0, 4)
    box("player_fill", 190, 8, look["progress"][0], TRANSPARENT, 0, 4)
    box("pkey", 190, 54, look["key_bg"], look["key_stroke"], 1, key_radius)
    for name, color in zip(KEY_NAMES, look["key_colors"]):
        specs["pckey_" + name] = {"size": (280, 54), "layers": [
            ("key", 0, 0, 280, 54, look["key_bg"], look["key_stroke"], 1,
             key_radius, color, 12)]}
    box("plist_panel", 664, 690, look["bar"], look["panel_stroke"], 2, radius)
    box("pguide_panel", 950, 690, look["bar"], look["panel_stroke"], 2,
        radius)
    box("info_box", 1100, 168, look["bar"], look["panel_stroke"], 2, radius)
    return specs


def frame_layout(theme, width, large=True):
    """The preview window in real pixels:

      "frame":   (left, top, w, h)  the frame picture (halo included)
      "video":   (left, top, w, h)  the video rectangle
      "radius":  the video's corner radius
      "corners": {tag: (left, top, size)}  the four corner pictures

    The corner pictures have to meet the video rectangle to the pixel,
    so they are placed from its own edges here rather than scaled from
    Full HD positions (which round differently at 1280).
    """
    table = geo(large)
    look = LOOKS[normalize_theme(theme)]
    frame = table["preview_frame"]
    frame_left = scaled(frame[0] - 14, width)
    frame_top = scaled(frame[1] - 14, width)
    x, y, w, h = table["preview"]
    left, top = scaled(x, width), scaled(y, width)
    video_w = scaled(x + w, width) - left
    video_h = scaled(y + h, width) - top
    radius = max(2.0, look["frame_radius"] - 4) * width / float(BASE_WIDTH)
    size = max(3, int(radius + 0.999) + 1)
    return {
        "frame": (frame_left, frame_top, asset_pixels(frame[2] + 28, width),
                  asset_pixels(frame[3] + 28, width)),
        "video": (left, top, video_w, video_h),
        "radius": radius,
        "corners": {
            "tl": (left, top, size),
            "tr": (left + video_w - size, top, size),
            "bl": (left, top + video_h - size, size),
            "br": (left + video_w - size, top + video_h - size, size),
        },
    }


def asset_pixel_size(theme, name, width):
    """(width, height) in real pixels of a theme picture on a desktop
    `width` wide - what make_theme_assets.py draws and what the skins
    declare."""
    spec = asset_specs(theme)[name]
    if "corner" in spec:
        size = frame_layout(theme, width)["corners"][spec["corner"]][2]
        return size, size
    w, h = spec["size"]
    if "row" in spec:
        # exactly one row of the listbox it is the selection of
        kind, large = spec["row"]
        return asset_pixels(w, width), list_metrics(
            theme, large, width, kind)["row_h"]
    return asset_pixels(w, width), asset_pixels(h, width)


def asset_path(theme, name, width, base_dir=None):
    """Where a theme picture for this resolution lives on disk."""
    return join(base_dir or PLUGIN_DIR, "skin", "themes",
                normalize_theme(theme), resolution(width), name + ".png")


def background_path(theme, width, plain=False, base_dir=None):
    """The theme's background picture: with the VAVOO wordmark, or
    `plain` without it (the start screen shows the logo itself).
    Full HD and WQHD share one file (the skin scales it, as Classic's
    WQHD skin does with its own)."""
    name = "bg%s_%s.jpg" % ("_plain" if plain else "",
                            "hd" if width < 1920 else "fhd")
    return join(base_dir or PLUGIN_DIR, "skin", "themes",
                normalize_theme(theme), name)


# ---------------------------------------------------------------------
# Skin XML
# ---------------------------------------------------------------------
try:
    _unicode = unicode  # noqa: F821 (Python 2)
except NameError:
    _unicode = str


def _esc(value):
    """`value` as skin text: str on both Pythons (Python 2: UTF-8 - a
    unicode title with an accent made str() fail there)."""
    if isinstance(value, bytes) and not isinstance(value, str):
        value = value.decode("utf-8", "replace")
    elif _unicode is not str and isinstance(value, _unicode):
        value = value.encode("utf-8")
    else:
        value = str(value)
    return (value.replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


class _Skin(object):
    """Collects the widgets of one screen, converting Full HD measures
    to the desktop's as it goes."""

    def __init__(self, theme, large, width, base_dir=None):
        self.theme = normalize_theme(theme)
        self.look = LOOKS[self.theme]
        self.large = bool(large)
        self.width = int(width)
        self.height = int(round(self.width * BASE_HEIGHT / float(BASE_WIDTH)))
        self.base_dir = base_dir
        self.geo = geo(self.large)
        self.lines = []
        self.assets = []

    # ---- measures
    def px(self, value):
        return scaled(value, self.width)

    def rect(self, x, y, w, h):
        """A Full HD rectangle as real pixels: the far edges are
        converted, not the sizes, so two rectangles that touch in the
        table still touch on screen."""
        left, top = self.px(x), self.px(y)
        return left, top, max(1, self.px(
            x + w) - left), max(1, self.px(y + h) - top)

    def font(self, size, bold=False):
        name = self.look["font_bold" if bold else "font"][0]
        return "%s;%d" % (name, max(8, self.px(size)))

    def ts(self, size):
        return size * text_scale(self.large)

    # ---- widgets
    def add(self, tag, attrs, children=None):
        text = "<%s %s" % (tag, " ".join(
            '%s="%s"' % (key, _esc(value)) for key, value in attrs))
        if children:
            text += ">" + "".join(children) + "</%s>" % tag
        else:
            text += " />"
        self.lines.append("\t" + text)

    def background(self, plain=False):
        attrs = [("pixmap", background_path(self.theme, self.width, plain,
                                            self.base_dir)),
                 ("position", "0,0"),
                 ("size", "%d,%d" % (self.width, self.height)),
                 ("alphatest", "off"), ("zPosition", "-1")]
        if self.width > 1920:
            attrs.append(("scale", "1"))
        self.add("ePixmap", attrs)

    def picture(self, name, x, y, z=0):
        """A theme picture with its top-left corner at Full HD x, y,
        at the size it was drawn."""
        self.picture_px(name, self.px(x), self.px(y), z)

    def picture_px(self, name, left, top, z=0):
        """The same, placed in real pixels."""
        w, h = asset_pixel_size(self.theme, name, self.width)
        self.assets.append(name)
        self.add("ePixmap", [
            ("pixmap", asset_path(self.theme, name, self.width, self.base_dir)),
            ("position", "%d,%d" % (left, top)), ("size", "%d,%d" % (w, h)),
            ("alphatest", "blend"), ("zPosition", z)])

    def label(self, name, box, size, color=WHITE, halign="left",
              valign="center", bold=False, z=2, nowrap=False, back=None):
        left, top, w, h = self.rect(*box)
        attrs = [("name", name), ("position", "%d,%d" % (left, top)),
                 ("size", "%d,%d" % (w, h)), ("font", self.font(size, bold)),
                 ("halign", halign), ("valign", valign),
                 ("foregroundColor", e2_color(color)),
                 ("backgroundColor", solid(back or self.look["bg"])),
                 ("transparent", "1"), ("zPosition", z)]
        if nowrap:
            attrs.append(("noWrap", "1"))
        self.add("widget", attrs)

    def fixed(self, text, box, size, color=WHITE, halign="left",
              valign="center", bold=False, z=2):
        left, top, w, h = self.rect(*box)
        self.add("eLabel", [
            ("text", text), ("position", "%d,%d" % (left, top)),
            ("size", "%d,%d" % (w, h)), ("font", self.font(size, bold)),
            ("halign", halign), ("valign", valign),
            ("foregroundColor", e2_color(color)),
            ("backgroundColor", solid(self.look["bg"])),
            ("transparent", "1"), ("zPosition", z)])

    def block(self, box, color, z=1):
        left, top, w, h = self.rect(*box)
        self.add("eLabel", [
            ("position", "%d,%d" % (left, top)), ("size", "%d,%d" % (w, h)),
            ("backgroundColor", e2_color(color)), ("zPosition", z)])

    def clock(self, clock_24=True):
        left, top, w, h = self.rect(*self.geo["clock"])
        self.add("widget", [
            ("source", "global.CurrentTime"), ("render", "Label"),
            ("position", "%d,%d" % (left, top)), ("size", "%d,%d" % (w, h)),
            ("font", self.font(self.geo["clock_font"])),
            ("halign", "right"), ("valign", "center"),
            ("foregroundColor", "#ffffff"),
            ("backgroundColor", solid(self.look["bg"])),
            ("transparent", "1"), ("zPosition", 2)],
            ['<convert type="ClockToText">%s</convert>'
             % ("Format:%H:%M" if clock_24 else "Format:%l:%M")])

    def version(self):
        self.label("version", self.geo["version"], self.geo["version_font"],
                   self.look["hilite"], "center")

    def color_keys(self, names, widget_prefix=""):
        """The colour keys named in `names` (others get no button and
        no label: a screen that does not use BLUE shows no BLUE)."""
        table = self.geo
        for index, name in enumerate(KEY_NAMES):
            if name not in names:
                continue
            x = table["key_x"][index]
            self.picture("key_" + name, x + 6, table["key_y"] - 2, z=1)
            self.label(widget_prefix + name,
                       (x + 12, table["key_y"], table["key_w"] - 12,
                        table["key_h"]),
                       table["key_font"], WHITE, "center", z=3, nowrap=True,
                       back=self.look["key_bg"])

    def listbox(self, name, box, kind, selection, extra=None):
        metrics = list_metrics(self.theme, self.large, self.width, kind)
        left, top = self.px(box[0]), self.px(box[1])
        attrs = [("name", name), ("position", "%d,%d" % (left, top)),
                 ("size", "%d,%d" % (metrics["list_w"], metrics["list_h"])),
                 ("zPosition", 2), ("scrollbarMode", "showNever"),
                 ("transparent", "1"),
                 ("backgroundColor", solid(self.look["bg"])),
                 ("foregroundColor", "#ffffff"),
                 ("backgroundColorSelected", solid(self.look["selected"])),
                 ("foregroundColorSelected", "#ffffff"),
                 ("selectionPixmap", asset_path(
                     self.theme, selection, self.width, self.base_dir))]
        self.assets.append(selection)
        if extra:
            attrs.extend(extra)
        self.add("widget", attrs)

    def text(self, screen_name, x=0, y=0, w=None, h=None, transparent=False):
        if w is None:
            w, h = self.width, self.height
            pos = "0,0"
        else:
            # A dialog: exactly as big as its box picture (sized the
            # way the pictures are, asset_pixels()), or the picture
            # would stick out a pixel at 1280 / 2560.
            pos = "%d,%d" % (self.px(x), self.px(y))
            w, h = asset_pixels(w, self.width), asset_pixels(h, self.width)
        back = "#ff000000" if transparent else solid(self.look["bg"])
        return ('<screen name="%s" position="%s" size="%d,%d" '
                'backgroundColor="%s" flags="wfNoBorder">\n%s\n</screen>\n'
                % (screen_name, pos, w, h, back, "\n".join(self.lines)))


def asset_pixels(value, width):
    """The size in real pixels of a picture that is `value` Full HD
    units long (never 0)."""
    return max(1, scaled(value, width))


class _Sub(object):
    """A box inside a _Skin with its own origin (a dialog's inside):
    coordinates are the dialog's own, as in the app's source."""

    def __init__(self, skin, x, y):
        self.skin, self.x, self.y = skin, x, y

    def at(self, box):
        return (self.x + box[0], self.y + box[1], box[2], box[3])


# ---------------------------------------------------------------------
# Screens
# ---------------------------------------------------------------------
def list_screen(theme, large, width, keys=KEY_NAMES, menu_key=True,
                info_key=True, clock_24=True, cvs=False, base_dir=None):
    """Main menu, channel list, Favourites (defaultListScreen.xml).

    `keys`: the colour keys this screen uses. Same widget names as the
    Classic XML, plus key_menu / key_info for the two key hints the
    Classic background has painted in.
    """
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    table = skin.geo
    look = skin.look
    skin.background()
    skin.picture("panel_list", table["list_panel"][0], table["list_panel"][1])
    skin.listbox("menulist", table["list"], "list",
                 "sel_list_" + ("l" if large else "n"))
    skin.label("name", table["name"], table["name_font"], WHITE, "center",
               bold=True, nowrap=True)
    skin.label("proxy_status", table["status"], table["status_font"],
               look["hilite"], "center", z=3, nowrap=True)
    skin.version()
    skin.clock(clock_24)
    skin.color_keys(keys)
    if menu_key:
        skin.picture("key_menu", table["menu"][0], table["menu"][1], z=1)
        skin.label("key_menu", table["menu"], table["key_font"], WHITE,
                   "center", z=3, nowrap=True, back=look["key_bg"])
    if info_key:
        skin.picture("key_info", table["info"][0], table["info"][1], z=1)
        skin.label("key_info", table["info"], table["key_font"], WHITE,
                   "center", bold=True, z=3, nowrap=True, back=look["key_bg"])

    # the preview window: halo + frame, the channel's name over it, the
    # video, and the two programme lines under it
    frame = table["preview_frame"]
    skin.picture("frame", frame[0] - 14, frame[1] - 14, z=1)
    left, top, w, h = skin.rect(*table["preview_name"])
    skin.add("widget", [
        ("source", "session.CurrentService"), ("render", "Label"),
        ("position", "%d,%d" % (left, top)), ("size", "%d,%d" % (w, h)),
        ("font", skin.font(table["preview_name_font"], True)),
        ("halign", "left"), ("valign", "center"),
        ("foregroundColor", "#ffffff"), ("backgroundColor", solid(look["bg"])),
        ("transparent", "1"), ("zPosition", 30), ("noWrap", "1")],
        ['<convert type="ServiceName">Name</convert>'])
    layout = frame_layout(theme, width, large)
    left, top, w, h = layout["video"]
    skin.add("widget", [
        ("source", "session.VideoPicture"), ("render", "Pig"),
        ("position", "%d,%d" % (left, top)), ("size", "%d,%d" % (w, h)),
        ("zPosition", 20), ("backgroundColor", "#ff000000"),
        ("transparent", "0")])
    for tag in FRAME_CORNERS:
        corner_left, corner_top, _size = layout["corners"][tag]
        skin.picture_px("frame_" + tag, corner_left, corner_top, z=21)

    # Now / Next, the app's way: two lines under the preview window.
    # The two "time" labels of the Classic layout are not used in this
    # one (the time is part of the line) - kept, one pixel big, so
    # that the screen's widgets are the same set in every theme.
    x, y, w, h = table["epg"]
    half = h // 2
    skin.label("epg_now_time", (x, y, 1, 1), 8, look["text"], z=1)
    skin.label("epg_now_title", (x, y, w, half), table["epg_font"],
               look["text"], z=3, nowrap=True)
    skin.label("epg_next_time", (x, y + half, 1, 1), 8, look["text"], z=1)
    skin.label("epg_next_title", (x, y + half, w, h - half),
               table["epg_font"], look["text_sub"], z=3, nowrap=True)
    return skin.text("MainVavoo")


def config_screen(theme, large, width, clock_24=True, cvs=False,
                  base_dir=None):
    """Settings (vavoo_config.xml): the wide list, its description
    under it, the status line in the right column, RED and GREEN."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    table = skin.geo
    look = skin.look
    skin.background()
    skin.picture("panel_big", table["big_panel"][0], table["big_panel"][1])
    metrics = list_metrics(theme, large, width)
    left, top = skin.px(table["big_list"][0]), skin.px(table["big_list"][1])
    selection = "sel_big_" + ("l" if large else "n")
    skin.assets.append(selection)
    skin.add("widget", [
        ("name", "config"), ("position", "%d,%d" % (left, top)),
        ("size", "%d,%d" % (skin.px(table["big_list"][2]), metrics["list_h"])),
        ("zPosition", 2), ("font", skin.font(table["row_font"] - 4)),
        ("itemHeight", metrics["row_h"]), ("scrollbarMode", "showNever"),
        ("transparent", "1"), ("backgroundColor", solid(look["bg"])),
        ("foregroundColor", "#ffffff"),
        ("backgroundColorSelected", solid(look["selected"])),
        ("foregroundColorSelected", "#ffffff"),
        ("selectionPixmap", asset_path(theme, selection, width, base_dir))])
    skin.label("description", table["description"], table["desc_font"],
               WHITE, "center")
    skin.label("statusbar", table["statusbar"], table["statusbar_font"],
               WHITE, "left", z=3, nowrap=True)
    skin.version()
    skin.clock(clock_24)
    skin.color_keys(("red", "green"))
    return skin.text("vavoo_config")


def pick_screen(theme, large, width, clock_24=True, keys=KEY_NAMES,
                base_dir=None):
    """Choose countries / Parental Control (vavoo_pick.xml): the
    settings' wide list with icons and a value column, its description
    under it, the status line, all four colour keys
    (CountriesActivity / ParentalActivity)."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    table = skin.geo
    skin.background()
    skin.picture("panel_big", table["big_panel"][0], table["big_panel"][1])
    skin.listbox("menulist", table["big_list"], "big",
                 "sel_big_" + ("l" if large else "n"))
    skin.label("description", table["description"], table["desc_font"],
               WHITE, "center")
    skin.label("statusbar", table["statusbar"], table["statusbar_font"],
               WHITE, "left", z=3, nowrap=True)
    skin.version()
    skin.clock(clock_24)
    # (only the keys the screen uses: Parental Control has just Back)
    skin.color_keys(keys)
    return skin.text("VavooPick")


def search_screen(theme, large, width, cvs=False, base_dir=None):
    """Search (vavoo_search.xml): a dialog over whatever is behind
    it."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    rx, ry, rw, rh = skin.geo["search"]
    # (the box is 4 bigger all round than the dialog's own 1000-wide
    # coordinates, as in SearchActivity.buildUi)
    box = _Sub(skin, 4, 4)
    skin.picture("dialog_search", 0, 0, z=0)
    skin.label("search_label", box.at((20, 20, 960, 40)), 32, WHITE,
               nowrap=True)
    skin.picture("search_input", 4 + 20, 4 + 70, z=1)
    skin.label("search_text", box.at((38, 70, 924, 60)), 32, WHITE, z=3,
               nowrap=True)
    skin.label("input_info", box.at((20, 136, 960, 38)), skin.ts(24),
               "#cccccc", "center", nowrap=True)
    skin.listbox("channel_list", box.at((20, 180, 960, rh - 350)), "search",
                 "sel_search_" + ("l" if large else "n"))
    skin.label("status", box.at((20, rh - 166, 960, 38)), skin.ts(24), WHITE,
               "center", nowrap=True)
    skin.label("version", box.at((780, rh - 120, 200, 28)), 20,
               look["hilite"], "right")
    for index, name in enumerate(KEY_NAMES):
        x = 20 + index * 240
        skin.picture("skey_" + name, 4 + x, 4 + rh - 84, z=1)
        skin.label("key_" + name, box.at((x + 12, rh - 84, 225 - 12, 66)),
                   skin.ts(26), WHITE, "center", z=3, nowrap=True,
                   back=look["key_bg"])
    return skin.text("VavooSearch", rx - 4, ry - 4, rw + 8, rh + 8,
                     transparent=True)


def splash_screen(theme, large, width, base_dir=None):
    """The start screen (Plgnstrt.xml): the card with the logo and the
    progress bar (SplashActivity.buildModern)."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    cx, cy = skin.geo["splash_card"][0], skin.geo["splash_card"][1]
    card = _Sub(skin, cx, cy)
    skin.background(plain=True)
    skin.picture("splash_card", cx - 18, cy - 18, z=0)
    left, top, w, h = skin.rect(*card.at((335, 22, 670, 336)))
    skin.add("widget", [
        ("name", "poster"), ("position", "%d,%d" % (left, top)),
        ("size", "%d,%d" % (w, h)), ("alphatest", "on"), ("scale", "1"),
        ("zPosition", 5)])
    skin.label("title", card.at((75, 380, 1190, 62)), 48, look["title"],
               "center", bold=True, z=5, nowrap=True)
    skin.label("subtitle", card.at((75, 448, 1190, 40)), 28,
               look["text_sub"], "center", z=5, nowrap=True)
    skin.block(card.at((75, 506, 1190, 2)), look["divider"], z=4)
    skin.label("progress_label", card.at((75, 524, 900, 42)), 28,
               look["text"], "left", z=5, nowrap=True)
    skin.label("progress_pct", card.at((1005, 524, 260, 42)), 30,
               look["accent"], "right", bold=True, z=5, nowrap=True)
    skin.picture("splash_track", cx + 75, cy + 576, z=4)
    left, top, w, h = skin.rect(*card.at((75, 576, 1190, 14)))
    skin.assets.append("splash_fill")
    skin.add("widget", [
        ("name", "progress"), ("position", "%d,%d" % (left, top)),
        ("size", "%d,%d" % asset_pixel_size(theme, "splash_fill", width)),
        ("pixmap", asset_path(theme, "splash_fill", width, base_dir)),
        ("backgroundColor", solid(look["bg"])),
        ("foregroundColor", solid(look["progress"][0])),
        ("borderWidth", "0"), ("transparent", "1"), ("zPosition", 5)])
    skin.label("status", card.at((75, 604, 1190, 44)), 28, look["text"],
               "center", z=5, nowrap=True)
    skin.block(card.at((75, 660, 1190, 1)), look["divider"], z=4)
    skin.label("author", card.at((75, 672, 600, 42)), 28, look["text_dim"],
               "left", z=5, nowrap=True)
    skin.label("version", card.at((665, 672, 600, 42)), 28, look["text_dim"],
               "right", z=5, nowrap=True)
    skin.label("skip_hint", card.at((75, 728, 1190, 44)), 28, look["accent"],
               "center", z=6, nowrap=True)
    return skin.text("Plgnstrt")


def update_popup(theme, large, width, base_dir=None):
    """"Update available" (UpdatePopup.xml): the same layout in the
    theme's box, colours and fonts."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    ux, uy, uw, uh = skin.geo["update"]
    skin.picture("dialog_update", 0, 0, z=0)
    skin.label("title", (45, 36, 1110, 62), 44, look["title"], "center",
               bold=True, z=5, nowrap=True)
    skin.label("subtitle", (45, 102, 1110, 40), 26, look["accent"], "center",
               z=5, nowrap=True)
    skin.block((45, 153, 1110, 2), look["divider"], z=4)
    skin.label("changelog_label", (45, 164, 1110, 38), 26, look["text_sub"],
               "left", z=5, nowrap=True)
    skin.picture("dialog_inner_s", 45, 207, z=1)
    skin.label("changelog", (66, 222, 1068, 300), 24, look["text"], "left",
               "top", z=5, back=look["grid_prog"])
    for name, x, color in (("key_red", 45, look["key_colors"][0]),
                           ("key_green", 615, look["key_colors"][1])):
        skin.block((x, 588, 42, 42), color, z=4)
        skin.label(name, (x + 56, 584, 480, 50), 28, look["title"], "left",
                   z=5, nowrap=True)
    return skin.text("UpdatePopup", ux, uy, uw, uh, transparent=True)


def log_screen(theme, large, width, title, base_dir=None):
    """The log viewer: the update popup's box with the text in it (the
    same 13 lines as Console.py's own skin shows)."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    ux, uy, uw, uh = skin.geo["update"]
    skin.picture("dialog_update", 0, 0, z=0)
    skin.fixed(title, (45, 33, 1110, 48), 34, look["title"], bold=True, z=4)
    skin.block((45, 87, 1110, 2), look["divider"], z=4)
    skin.picture("dialog_inner", 45, 102, z=1)
    left, top, w, h = skin.rect(66, 120, 1068, 414)
    skin.add("widget", [
        ("name", "text"), ("position", "%d,%d" % (left, top)),
        ("size", "%d,%d" % (w, h)),
        ("font", "Console;%d" % max(8, skin.px(24))),
        ("foregroundColor", e2_color(look["text"])),
        ("backgroundColor", solid(look["grid_prog"])),
        ("transparent", "1"), ("zPosition", 5)])
    skin.block((45, 584, 42, 42), look["key_colors"][0], z=4)
    skin.label("key_red", (101, 580, 510, 50), 28, look["title"], "left",
               z=5, nowrap=True)
    return skin.text("VavooLog", ux, uy, uw, uh, transparent=True)


def menu_popup(theme, large, width, base_dir=None):
    """A small list of actions over the current screen (the app's
    PickerPopup): a title and the rows."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    mx, my, mw, mh = skin.geo["menu_box"]
    skin.picture("dialog_menu", 0, 0, z=0)
    skin.label("title", (20, 16, mw - 40, 60), 34, look["title"], "center",
               z=3, nowrap=True, back=look["guide_bg"])
    skin.listbox("menulist", (20, 90, mw - 40, mh - 110), "menu",
                 "sel_menu_" + ("l" if large else "n"))
    return skin.text("VavooMenu", mx, my, mw, mh, transparent=True)


def pin_popup(theme, large, width, base_dir=None):
    """The PIN pad (vavoo_pin.xml; the app's PinPopup): its title, the
    four dots, a line for "Wrong PIN" and what the keys do."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    px, py, pw, ph = skin.geo["pin_box"]
    skin.picture("dialog_pin", 0, 0, z=0)
    skin.label("title", (30, 24, pw - 60, 64), 36, look["title"], "center",
               bold=True, z=3, nowrap=True, back=look["guide_bg"])
    skin.label("dots", (30, 104, pw - 60, 120), 72, look["accent"],
               "center", z=3, nowrap=True, back=look["guide_bg"])
    skin.label("message", (30, 236, pw - 60, 56), 28, look["title"],
               "center", z=3, nowrap=True, back=look["guide_bg"])
    skin.label("hint", (30, ph - 96, pw - 60, 64), 26, look["text_sub"],
               "center", z=3, nowrap=True, back=look["guide_bg"])
    return skin.text("VavooPin", px, py, pw, ph, transparent=True)


def notify_bar(theme, large, width, base_dir=None):
    """The notification at the top of the screen (the app's popup())."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    tx, ty, tw, th = skin.geo["toast"]
    skin.picture("toast", 0, 0, z=0)
    skin.label("notification_text", (24, 8, tw - 48, th - 16),
               skin.geo["toast_font"], WHITE, "center", z=4, back=look["bar"])
    return skin.text("VavooNotify", tx, ty, tw, th, transparent=True)


# ---------------------------------------------------------------------
# The player
# ---------------------------------------------------------------------
PLAYER_SMALL_KEYS = (
    # (widget, x, y): captions of two more keys of the remote (EPG
    # guide, MENU options) - shown, never selected - on the colour
    # keys' row. (AUDIO and 0 recall were here too: they still work,
    # HELP lists them - the bar looks like a receiver's without them.)
    ("key_list", 1440, 978), ("key_options", 1640, 978))
PLAYER_KEY_X = (110, 410, 710, 1010)


def player_bar(theme, large, width, clock_24=True, base_dir=None):
    """The full-screen player's info bar (the app's landscape bar),
    over the video: logo, number, name, programme now with its progress
    and minutes left, next, status, clock and date, and one row of
    keys (the colour keys, EPG, MENU); and the stream-info box at the
    top left (hidden until asked for)."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    back = look["bar"]
    skin.picture("player_bar", 60, 780, z=0)
    left, top, w, h = skin.rect(100, 815, 120, 80)
    skin.add("widget", [
        ("name", "logo"), ("position", "%d,%d" % (left, top)),
        ("size", "%d,%d" % (w, h)), ("alphatest", "blend"),
        ("zPosition", 3)])
    skin.label("number", (70, 900, 186, 40), 30, look["hilite"], "center",
               bold=True, z=3, nowrap=True, back=back)
    skin.label("name", (260, 798, 1160, 62), 52, WHITE, bold=True, z=3,
               nowrap=True, back=back)
    skin.label("now", (260, 862, 860, 38), 30, look["text"], z=3,
               nowrap=True, back=back)
    # (a widget, not a fixed picture: with no programme known the
    # player hides the empty bar, as the app does)
    left, top, w, h = skin.rect(1130, 877, 190, 8)
    skin.assets.append("player_track")
    skin.add("widget", [
        ("name", "progress_track"), ("position", "%d,%d" % (left, top)),
        ("size", "%d,%d" % asset_pixel_size(theme, "player_track", width)),
        ("pixmap", asset_path(theme, "player_track", width, base_dir)),
        ("alphatest", "blend"), ("zPosition", 2)])
    skin.assets.append("player_fill")
    skin.add("widget", [
        ("name", "progress"), ("position", "%d,%d" % (left, top)),
        ("size", "%d,%d" % asset_pixel_size(theme, "player_fill", width)),
        ("pixmap", asset_path(theme, "player_fill", width, base_dir)),
        ("backgroundColor", solid(back)),
        ("borderWidth", "0"), ("transparent", "1"), ("zPosition", 3)])
    skin.label("left", (1325, 862, 95, 38), 24, look["text_sub"], "right",
               z=3, nowrap=True, back=back)
    skin.label("next", (260, 902, 1160, 34), 28 if large else 26,
               look["text_sub"], z=3, nowrap=True, back=back)
    skin.label("status", (260, 938, 1160, 30), 26 if large else 24,
               look["hilite"], z=3, nowrap=True, back=back)
    left, top, w, h = skin.rect(1440, 800, 390, 90)
    skin.add("widget", [
        ("source", "global.CurrentTime"), ("render", "Label"),
        ("position", "%d,%d" % (left, top)), ("size", "%d,%d" % (w, h)),
        ("font", skin.font(56)), ("halign", "right"), ("valign", "center"),
        ("foregroundColor", "#ffffff"), ("backgroundColor", solid(back)),
        ("transparent", "1"), ("zPosition", 3)],
        ['<convert type="ClockToText">%s</convert>'
         % ("Format:%H:%M" if clock_24 else "Format:%l:%M")])
    # the date under the clock, as on a receiver's info bar
    left, top, w, h = skin.rect(1440, 892, 390, 48)
    skin.add("widget", [
        ("source", "global.CurrentTime"), ("render", "Label"),
        ("position", "%d,%d" % (left, top)), ("size", "%d,%d" % (w, h)),
        ("font", skin.font(30)), ("halign", "right"), ("valign", "center"),
        ("foregroundColor", e2_color(look["text_sub"])),
        ("backgroundColor", solid(back)),
        ("transparent", "1"), ("zPosition", 3)],
        ['<convert type="ClockToText">Format:%a %d %b</convert>'])
    for name, x, y in PLAYER_SMALL_KEYS:
        skin.picture("pkey", x, y, z=1)
        # (24: "MENU Options" - the key, then its job - fits the box)
        skin.label(name, (x, y, 190, 54), 24, WHITE, "center", z=3,
                   nowrap=True, back=look["key_bg"])
    for index, name in enumerate(KEY_NAMES):
        x = PLAYER_KEY_X[index]
        skin.picture("pckey_" + name, x, 978, z=1)
        skin.label("key_" + name, (x + 10, 978, 270, 54), 30, WHITE,
                   "center", z=3, nowrap=True, back=look["key_bg"])
    # Stream info (Options -> Stream Info), top left, inside the safe
    # area. Its box is a widget too, so the player can show and hide
    # both together.
    left, top, w, h = skin.rect(96, 54, 1100, 168)
    skin.assets.append("info_box")
    skin.add("widget", [
        ("name", "info_box"), ("position", "%d,%d" % (left, top)),
        ("size", "%d,%d" % asset_pixel_size(theme, "info_box", width)),
        ("pixmap", asset_path(theme, "info_box", width, base_dir)),
        ("alphatest", "blend"), ("zPosition", 4)])
    skin.label("stream_info", (126, 66, 1040, 144), 28, look["text"],
               "left", "top", z=5, back=back)
    return skin.text("VavooPlayer", transparent=True)


def player_list(theme, large, width, base_dir=None):
    """The channel list over the video, with the mini guide beside it
    (PlayerActivity.buildChannelList)."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    look = skin.look
    skin.picture("plist_panel", 140, 150, z=0)
    skin.listbox("menulist", (152, 170, 640, 650), "list",
                 "sel_list_" + ("l" if large else "n"))
    skin.picture("pguide_panel", 830, 150, z=0)
    skin.label("guide", (860, 174, 890, 642), 30 if large else 28,
               look["text"], "left", "top", z=3, back=look["bar"])
    return skin.text("VavooPlayerList", transparent=True)


def player_menu(theme, large, width, base_dir=None):
    """The player's options (MENU) where the app shows them: in the
    list panel on the left, over the video (PlayerActivity.buildOptions
    - overlayPanel without icons). Same widgets as menu_popup()."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    skin.picture("plist_panel", 140, 150, z=0)
    skin.listbox("menulist", (152, 170, 640, 650), "list",
                 "sel_list_" + ("l" if large else "n"))
    return skin.text("VavooPlayerMenu", transparent=True)


CLASSIC_COLORS = {
    # Classic's own: the list skins' navy and wine red (defaultListScreen
    # .xml) and the app's Classic overlay box (#EE121018, white edge)
    "panel": "#11121018", "edge": "#ffffff", "selected": "#743554",
    "text": "#ffffff", "font": "cvfont",
}


def player_list_classic(width):
    """player_list() for the Classic theme, which has no file for this
    screen: the same boxes in Classic's colours, drawn with labels (no
    pictures). Rows are Classic's own (plugin.py's m2list)."""
    def px(value):
        return scaled(value, width)

    lines = []

    def rect(x, y, w, h, color, z):
        lines.append(
            '    <eLabel position="%d,%d" size="%d,%d" backgroundColor="%s" '
            'zPosition="%d" />' % (px(x), px(y), max(1, px(x + w) - px(x)),
                                   max(1, px(y + h) - px(y)), color, z))

    def framed(x, y, w, h):
        rect(x, y, w, h, CLASSIC_COLORS["panel"], 0)
        for bx, by, bw, bh in ((x, y, w, 3), (x, y + h - 3, w, 3),
                               (x, y, 3, h), (x + w - 3, y, 3, h)):
            rect(bx, by, bw, bh, CLASSIC_COLORS["edge"], 1)

    framed(140, 150, 664, 690)
    framed(830, 150, 950, 690)
    lines.append(
        '    <widget name="menulist" position="%d,%d" size="%d,%d" '
        'zPosition="2" scrollbarMode="showOnDemand" transparent="1" '
        'backgroundColor="#121018" foregroundColor="#ffffff" '
        'backgroundColorSelected="%s" foregroundColorSelected="#ffffff" />'
        % (px(152), px(170), px(640), px(650), CLASSIC_COLORS["selected"]))
    lines.append(
        '    <widget name="guide" position="%d,%d" size="%d,%d" '
        'font="%s;%d" halign="left" valign="top" foregroundColor="#ffffff" '
        'backgroundColor="#121018" transparent="1" zPosition="3" />'
        % (px(860), px(174), px(890), px(642), CLASSIC_COLORS["font"],
           max(8, px(28))))
    height = int(round(width * BASE_HEIGHT / float(BASE_WIDTH)))
    return ('<screen name="VavooPlayerList" position="0,0" size="%d,%d" '
            'backgroundColor="#ff000000" flags="wfNoBorder">\n%s\n</screen>\n'
            % (width, height, "\n".join(lines)))


# ---------------------------------------------------------------------
# The programme guide grid (the app's EpgGuideActivity / EpgGrid)
# ---------------------------------------------------------------------
# Classic's guide colours (the app's Classic Look).
CLASSIC_GRID = {
    "guide_bg": "#F00e0f1a", "guide_bg_over": "#B00e0f1a",
    "grid_header": "#101225", "grid_name": "#181b2e",
    "grid_prog": "#23263d", "grid_now": "#33375a",
    "grid_now_line": "#ff3b5c", "selected": "#743554",
    "tick_text": "#c8b6e2", "tick_line": "#2a2d45",
    "no_info": "#6f6f80", "text": "#e0d6ee", "details": "#e6d6f5",
    "font": "Regular", "font_bold": "Regular",
}
# The guide's three hours across.
GUIDE_WINDOW = 3 * 3600


def e2_int(color):
    """An Android colour as the integer Enigma2's list entries take
    (0xTTRRGGBB, TT = transparency)."""
    r, g, b, a = parse_color(color)
    return ((255 - a) << 24) | (r << 16) | (g << 8) | b


def _blend(color, under, alpha):
    """`color` at `alpha` (0-255) over `under`, opaque."""
    r1, g1, b1, _a = parse_color(color)
    r2, g2, b2, _b = parse_color(under)

    def mix(a, b):
        return int(round(a * alpha / 255.0 + b * (255 - alpha) / 255.0))
    return "#%02x%02x%02x" % (mix(r1, r2), mix(g1, g2), mix(b1, b2))


def guide_colors(theme):
    """The grid's colours (EpgGrid): a theme's Look, or Classic's."""
    if not is_modern(theme):
        out = dict(CLASSIC_GRID)
    else:
        look = LOOKS[normalize_theme(theme)]
        out = {
            "guide_bg": look["guide_bg"], "guide_bg_over": look["guide_bg_over"],
            "grid_header": look["grid_header"], "grid_name": look["grid_name"],
            "grid_prog": look["grid_prog"], "grid_now": look["grid_now"],
            "grid_now_line": look["grid_now_line"],
            "selected": look["selected"], "tick_text": look["text_sub"],
            "tick_line": "#" + look["divider"].lstrip("#")[-6:],
            "no_info": look["text_dim"], "text": look["text"],
            "details": look["text"], "font": look["font"][0],
            "font_bold": look["font_bold"][0],
        }
    # a row with nothing in the window: grid_prog at 0x99 over the
    # guide's background (EpgGrid's colNone)
    out["none"] = _blend(out["grid_prog"], "#" + out["guide_bg"][-6:], 0x99)
    return out


def guide_metrics(large, width, preview=False):
    """The grid's measures in real pixels (EpgGuideActivity.buildUi,
    EpgGrid.layout): the grid area, its rows, the time ruler above
    them, the channel column, the details text and the preview."""
    grid_h = 600 if preview else 690
    rows = (9 if preview else 10) - (1 if large else 0)
    header_h = grid_h / float(rows + 1) * 0.8
    row_h = (grid_h - header_h) / rows
    grid_x, grid_y, grid_w = 56, 110, 1808
    name_w = grid_w * 0.26
    info_y = 120 + grid_h
    info_h = 940 - grid_h - 100
    out = {
        "rows": rows,
        "grid_x": scaled(grid_x, width), "grid_y": scaled(grid_y, width),
        "grid_w": scaled(grid_w, width),
        "header_h": max(10, scaled(header_h, width)),
        "row_h": max(10, scaled(row_h, width)),
        "name_w": scaled(name_w, width),
        "info": (64, info_y, 1792, info_h),
        "font_size": max(8, scaled(row_h * 0.40, width)),
        "pad": max(2, scaled(row_h * 0.12, width)),
        "details_font": 26 * text_scale(large),
    }
    out["time_w"] = out["grid_w"] - out["name_w"]
    out["rows_y"] = out["grid_y"] + out["header_h"]
    if preview:
        pw = min(int((info_h - 12) * 16 / 9.0), int(1792 * 0.45))
        ph = pw * 9 // 16
        out["preview"] = (64 + 1792 - pw, info_y + (info_h - ph) // 2, pw, ph)
        out["info"] = (64, info_y, 1792 - pw - 30, info_h)
    return out


def _guide_widgets(add, px_rect, metrics, colors, width, font_name,
                   details_font, title_font):
    """The guide's named widgets (both looks)."""
    m = metrics
    bg = "#" + colors["guide_bg"][-6:]
    add('<widget name="heading" position="%d,%d" size="%d,%d" font="%s;%d" '
        'halign="left" valign="center" foregroundColor="#ffffff" '
        'backgroundColor="%s" transparent="1" zPosition="3" noWrap="1" />'
        % (px_rect(64, 44, 1792, 56) + (title_font, max(8, scaled(36, width)),
                                        bg)))
    for name, top, height in (("ruler", m["grid_y"], m["header_h"]),
                              ("grid", m["rows_y"], m["rows"] * m["row_h"])):
        add('<widget name="%s" position="%d,%d" size="%d,%d" zPosition="2" '
            'scrollbarMode="showNever" selectionDisabled="1" transparent="1" '
            'backgroundColor="%s" backgroundColorSelected="%s" '
            'foregroundColor="#ffffff" foregroundColorSelected="#ffffff" />'
            % (name, m["grid_x"], top, m["grid_w"], height, bg, bg))
    add('<widget name="details" position="%d,%d" size="%d,%d" font="%s;%d" '
        'halign="left" valign="top" foregroundColor="%s" backgroundColor="%s" '
        'transparent="1" zPosition="3" />'
        % (px_rect(*m["info"]) + (font_name,
                                  max(8, scaled(details_font, width)),
                                  "#" + colors["details"][-6:], bg)))
    if "preview" in m:
        add('<widget source="session.VideoPicture" render="Pig" '
            'position="%d,%d" size="%d,%d" zPosition="3" '
            'backgroundColor="#ff000000" />' % px_rect(*m["preview"]))


def guide_screen(theme, large, width, preview=False, over=False,
                 base_dir=None):
    """The programme guide grid (EpgGuideActivity): the panel, the
    heading, the time ruler and the grid (two MultiContent lists that
    plugin.py's VavooGuide draws), the details under them, the
    preview window when it is open, the four colour keys."""
    if not is_modern(theme):
        return None
    skin = _Skin(theme, large, width, base_dir)
    if not over:
        skin.background()
    skin.picture("guide_panel_over" if over else "guide_panel", 40, 30)
    m = guide_metrics(large, width, preview)
    colors = guide_colors(theme)

    def add(line):
        skin.lines.append("\t" + line)

    _guide_widgets(add, lambda *b: skin.rect(*b), m, colors, width,
                   skin.look["font"][0], m["details_font"],
                   skin.look["font_bold"][0])
    if over:
        # the keys over the video: a dark strip behind them
        skin.block((0, 975, 1920, 105), "#B0000000", z=0)
    skin.color_keys(KEY_NAMES)
    return skin.text("VavooGuide", transparent=over)


def guide_classic(width, large=True, preview=False, over=False):
    """guide_screen() for Classic, which has no file for this screen:
    the same boxes in Classic's colours, drawn with labels."""
    colors = guide_colors("classic")
    m = guide_metrics(large, width, preview)
    lines = []

    def px_rect(x, y, w, h):
        return (scaled(x, width), scaled(y, width),
                max(1, scaled(x + w, width) - scaled(x, width)),
                max(1, scaled(y + h, width) - scaled(y, width)))

    def rect(x, y, w, h, color, z):
        lines.append('\t<eLabel position="%d,%d" size="%d,%d" '
                     'backgroundColor="%s" zPosition="%d" />'
                     % (px_rect(x, y, w, h) + (color, z)))

    panel = e2_color(colors["guide_bg_over" if over else "guide_bg"])
    rect(40, 30, 1840, 940, panel, 0)
    for bx, by, bw, bh in ((40, 30, 1840, 3), (40, 967, 1840, 3),
                           (40, 30, 3, 940), (1877, 30, 3, 940)):
        rect(bx, by, bw, bh, colors["selected"], 1)
    _guide_widgets(lines.append, px_rect, m, colors, width,
                   CLASSIC_COLORS["font"], 26 * (1.2 if large else 1.0),
                   CLASSIC_COLORS["font"])
    # Classic's keys: the label and a coloured bar under it
    for index, (name, color) in enumerate(zip(
            KEY_NAMES, ("#ff0000", "#00ff00", "#ffff00", "#0000ff"))):
        x = (58, 355, 652, 948)[index]
        lines.append(
            '\t<widget name="%s" position="%d,%d" size="%d,%d" font="%s;%d" '
            'halign="center" valign="center" foregroundColor="#ffffff" '
            'backgroundColor="#181b2e" transparent="1" zPosition="3" />'
            % ((name,) + px_rect(x, 995, 297, 50) +
               (CLASSIC_COLORS["font"], max(8, scaled(30, width)))))
        rect(x, 1048, 300, 6, color, 3)
    height = int(round(width * BASE_HEIGHT / float(BASE_WIDTH)))
    back = "#ff000000" if over else "#181b2e"
    return ('<screen name="VavooGuide" position="0,0" size="%d,%d" '
            'backgroundColor="%s" flags="wfNoBorder">\n%s\n</screen>\n'
            % (width, height, back, "\n".join(lines)))


# Everything a caller can ask for by name (plugin.py's
# load_screen_skin(), the tests, the mock-ups).
BUILDERS = {
    "list": list_screen,
    "config": config_screen,
    "pick": pick_screen,
    "search": search_screen,
    "splash": splash_screen,
    "update": update_popup,
    "menu": menu_popup,
    "pin": pin_popup,
    "notify": notify_bar,
    "log": log_screen,
    "player": player_bar,
    "player_list": player_list,
    "player_menu": player_menu,
    "guide": guide_screen,
}
