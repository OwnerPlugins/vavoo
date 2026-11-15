#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dev-time script: draws the pictures the modern themes' skins use
(Prism, Halo, Orbit - see vavoo_theme.py) into
skin/themes/<theme>/<hd|fhd|wqhd>/*.png.

    python3 make_theme_assets.py            # every theme and resolution
    python3 make_theme_assets.py prism fhd  # one of each
    python3 make_theme_assets.py --check    # only say what is missing

Nothing to install: plain Python (2.7 or 3), no Pillow. What to draw
and how big comes from vavoo_theme.asset_specs() /
asset_pixel_size() - the very functions the skins are built from, so
a skin cannot ask for a picture or a size that was not drawn.

The shapes are the Android app's (ui/skin/SkinViews.kt): a rounded
box with an optional outline, the same box filled with a left-to-right
gradient (the selected row), and a colour key (a dark rounded key
with its colour as a stripe on the left edge). Edges are smoothed by
how much of each pixel the shape covers.

Not drawn here: the backgrounds (skin/themes/<theme>/bg*.jpg). They
are the app's own pictures (its tools/make_theme_backgrounds.py),
converted to JPEG at 1920x1080 and 1280x720.
"""
from __future__ import absolute_import, print_function

import os
import struct
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import vavoo_theme as theme_data    # noqa: E402


# ---------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------
def _coverage(px, py, x0, y0, x1, y1, radius):
    """How much of the pixel whose centre is (px, py) lies inside the
    rounded rectangle x0..x1, y0..y1: 0.0 to 1.0, from its distance
    to the edge (exact for straight edges, very close on the arcs)."""
    half_w = (x1 - x0) / 2.0
    half_h = (y1 - y0) / 2.0
    if half_w <= 0 or half_h <= 0:
        return 0.0
    radius = max(0.0, min(radius, half_w, half_h))
    qx = abs(px - (x0 + x1) / 2.0) - half_w + radius
    qy = abs(py - (y0 + y1) / 2.0) - half_h + radius
    outside = (max(qx, 0.0) ** 2 + max(qy, 0.0) ** 2) ** 0.5
    distance = outside + min(max(qx, qy), 0.0) - radius
    if distance <= -0.5:
        return 1.0
    if distance >= 0.5:
        return 0.0
    return 0.5 - distance


def _premultiplied(color):
    red, green, blue, opacity = theme_data.parse_color(color)
    alpha = opacity / 255.0
    return (red / 255.0 * alpha, green / 255.0 * alpha,
            blue / 255.0 * alpha, alpha)


def _over(dst, src, amount):
    """Paint premultiplied `src`, `amount` (0..1) of it, over `dst`."""
    if amount <= 0.0 or src[3] <= 0.0:
        return dst
    keep = 1.0 - src[3] * amount
    return (src[0] * amount + dst[0] * keep, src[1] * amount + dst[1] * keep,
            src[2] * amount + dst[2] * keep, src[3] * amount + dst[3] * keep)


class _Layer(object):
    """One shape of a picture, in real pixels."""

    def __init__(self, spec, scale):
        self.kind = spec[0]

        def edge(value):
            # Whole pixels: a box's straight edges stay crisp at 1280
            # and 2560 instead of smearing over two pixels.
            return float(int(round(value * scale)))

        self.x0, self.y0 = edge(spec[1]), edge(spec[2])
        self.x1, self.y1 = edge(spec[1] + spec[3]), edge(spec[2] + spec[4])
        self.stroke = None
        self.stroke_w = 0.0
        self.stripe = None
        self.stripe_x = self.x0
        self.fill2 = None
        if self.kind == "box":
            self.fill = _premultiplied(spec[5])
            self.stroke = _premultiplied(spec[6])
            self.stroke_w = self._line(spec[7], scale)
            self.radius = spec[8] * scale
        elif self.kind == "grad":
            self.fill = _premultiplied(spec[5])
            self.fill2 = _premultiplied(spec[6])
            self.radius = spec[7] * scale
        elif self.kind == "key":
            self.fill = _premultiplied(spec[5])
            self.stroke = _premultiplied(spec[6])
            self.stroke_w = self._line(spec[7], scale)
            self.radius = spec[8] * scale
            self.stripe = _premultiplied(spec[9])
            self.stripe_x = self.x0 + float(max(2, int(round(spec[10] * scale))))
        elif self.kind == "hole":
            self.fill = None
            self.radius = spec[5] * scale
        else:
            raise ValueError("unknown layer %r" % (self.kind,))
        # (never rounder than the box is small - a key at 1280)
        self.radius = min(self.radius, (self.x1 - self.x0) / 2.0,
                          (self.y1 - self.y0) / 2.0)
        if self.stroke is not None and self.stroke[3] <= 0.0:
            self.stroke_w = 0.0
        # Rows further than this from the top and bottom edges all
        # look the same (see render()).
        self.band = self.radius + self.stroke_w + 2.0

    @staticmethod
    def _line(width, scale):
        return 0.0 if width <= 0 else float(max(1, int(round(width * scale))))

    def row_class(self, y):
        """What a row at height y looks like, as far as this layer
        goes: the same value for two rows = the same pixels."""
        py = y + 0.5
        if py < self.y0 - 1 or py > self.y1 + 1:
            return "out"
        if py - self.y0 < self.band or self.y1 - py < self.band:
            return y
        return "in"

    def paint(self, pixel, px, py):
        cover = _coverage(px, py, self.x0, self.y0, self.x1, self.y1,
                          self.radius)
        if cover <= 0.0:
            return pixel
        if self.kind == "hole":
            keep = 1.0 - cover
            return (pixel[0] * keep, pixel[1] * keep, pixel[2] * keep,
                    pixel[3] * keep)
        if self.kind == "grad":
            t = (px - self.x0) / max(1.0, self.x1 - self.x0)
            t = min(1.0, max(0.0, t))
            color = tuple(self.fill[i] + (self.fill2[i] - self.fill[i]) * t
                          for i in range(4))
            return _over(pixel, color, cover)
        if self.kind == "key":
            pixel = _over(pixel, self.stripe if px < self.stripe_x
                          else self.fill, cover)
        else:
            # (as Android's GradientDrawable: the fill ends half-way
            # under the outline)
            inset = self.stroke_w / 2.0
            pixel = _over(pixel, self.fill, cover if inset <= 0.0 else _coverage(
                px, py, self.x0 + inset, self.y0 + inset, self.x1 - inset,
                self.y1 - inset, self.radius - inset))
        if self.stroke_w > 0.0:
            inner = _coverage(
                px, py, self.x0 + self.stroke_w, self.y0 + self.stroke_w,
                self.x1 - self.stroke_w, self.y1 - self.stroke_w,
                self.radius - self.stroke_w)
            pixel = _over(pixel, self.stroke, max(0.0, cover - inner))
        return pixel


def _byte(value):
    return max(0, min(255, int(value * 255.0 + 0.5)))


def render(layers, width, height, region=None):
    """The picture as a list of rows of RGBA bytes. `region` =
    (left, top, w, h) draws only that part of it.

    A box's rows are all alike except near its top and bottom, so a
    row is drawn once per "kind of row" and reused: the big panels
    cost a few hundred rows of arithmetic, not a million pixels.
    """
    left, top, w, h = region or (0, 0, width, height)
    rows = []
    drawn = {}
    for y in range(top, top + h):
        key = tuple(layer.row_class(y) for layer in layers)
        row = drawn.get(key)
        if row is None:
            out = bytearray()
            py = y + 0.5
            for x in range(left, left + w):
                pixel = (0.0, 0.0, 0.0, 0.0)
                px = x + 0.5
                for layer in layers:
                    pixel = layer.paint(pixel, px, py)
                alpha = pixel[3]
                if alpha <= 0.0:
                    out.extend(b"\x00\x00\x00\x00")
                else:
                    out.extend(bytearray((
                        _byte(pixel[0] / alpha), _byte(pixel[1] / alpha),
                        _byte(pixel[2] / alpha), _byte(alpha))))
            row = drawn[key] = bytes(out)
        rows.append(row)
    return rows


def write_png(path, width, rows):
    """An RGBA PNG, 8 bits a channel."""
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body +
                struct.pack(">I", zlib.crc32(kind + body) & 0xffffffff))

    raw = b"".join(b"\x00" + row for row in rows)
    data = (b"\x89PNG\r\n\x1a\n" +
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, len(rows), 8, 6,
                                       0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(raw, 9)) +
            chunk(b"IEND", b""))
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


# ---------------------------------------------------------------------
# One picture
# ---------------------------------------------------------------------
def draw(theme, name, width):
    """(pixel width, rows) of one theme picture for a desktop `width`
    wide."""
    spec = theme_data.asset_specs(theme)[name]
    scale = width / float(theme_data.BASE_WIDTH)
    out_w, out_h = theme_data.asset_pixel_size(theme, name, width)

    if "corner" in spec:
        # The frame picture again, with a rounded hole where the
        # video is, cut down to one corner of the video - everything
        # placed in real pixels, as the skin places it.
        layout = theme_data.frame_layout(theme, width)
        frame_left, frame_top, frame_w, frame_h = layout["frame"]
        layers = [_Layer(layer, scale) for layer in spec["layers"]]
        left, top, video_w, video_h = layout["video"]
        hole = _Layer(("hole", 0, 0, 1, 1, 0), 1.0)
        hole.x0, hole.y0 = float(left - frame_left), float(top - frame_top)
        hole.x1, hole.y1 = hole.x0 + video_w, hole.y0 + video_h
        hole.radius = layout["radius"]
        hole.band = hole.radius + 2.0
        layers.append(hole)
        corner_left, corner_top, size = layout["corners"][spec["corner"]]
        return size, render(layers, frame_w, frame_h, (
            corner_left - frame_left, corner_top - frame_top, size, size))

    full_w = theme_data.asset_pixels(spec["size"][0], width)
    full_h = theme_data.asset_pixels(spec["size"][1], width)
    layers = [_Layer(layer, scale) for layer in spec["layers"]]
    if "row" in spec:
        # A listbox's selection bar: exactly one row of that listbox
        # high, whatever the rounding of the Full HD size gave.
        for layer in layers:
            layer.y1 = float(out_h)
            layer.radius = min(layer.radius, out_h / 2.0)
        full_h = out_h
    return out_w, render(layers, full_w, full_h, (0, 0, out_w, out_h))


def main(argv):
    check_only = "--check" in argv
    wanted = [a for a in argv if not a.startswith("-")]
    themes = [t for t in theme_data.MODERN_THEMES if not wanted or t in wanted
              or not any(w in theme_data.MODERN_THEMES for w in wanted)]
    resolutions = [(tag, w) for tag, w in theme_data.RESOLUTIONS
                   if not wanted or tag in wanted
                   or not any(w2 in dict(theme_data.RESOLUTIONS) for w2 in wanted)]
    missing = 0
    total = 0
    for theme in themes:
        for tag, width in resolutions:
            for name in sorted(theme_data.asset_specs(theme)):
                path = theme_data.asset_path(theme, name, width, HERE)
                if check_only:
                    if not os.path.isfile(path):
                        missing += 1
                        print("missing: " + os.path.relpath(path, HERE))
                    continue
                out_w, rows = draw(theme, name, width)
                total += write_png(path, out_w, rows)
            if not check_only:
                print("%s %s: %d pictures" % (
                    theme, tag, len(theme_data.asset_specs(theme))))
        for plain in (False, True):
            for width in (1280, 1920):
                path = theme_data.background_path(theme, width, plain, HERE)
                if not os.path.isfile(path):
                    missing += 1
                    print("missing background: " + os.path.relpath(path, HERE))
    if check_only:
        print("nothing missing" if not missing else "%d missing" % missing)
        return 1 if missing else 0
    print("%.1f KB of PNG written" % (total / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
