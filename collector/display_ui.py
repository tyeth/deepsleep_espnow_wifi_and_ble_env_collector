# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
display_ui - PERSISTENT dashboard for the quad/tri eInk panels.

The displayio tree is built ONCE (Dashboard) and every refresh mutates
label text / palette colors in place. On the no-PSRAM C6 with the BLE
stack resident (~24KB free heap) a full rebuild-per-refresh could not
allocate; in-place updates peak at one small label bitmap at a time.

Layout rules from the project spec:
  * Local room values LARGE, yellow (warn) / red (bad) cell highlight
    (tri palette has no yellow: red text + "!" marks warn).
  * Remote nodes in tiny text, abnormal lines highlighted, worst first.
  * Battery warnings as a WATERMARK behind the data + !BATT! corner tag.
  * Footer shows how long each zone has been out of spec.
"""

import displayio
import terminalio
import vectorio

# bitmap_label renders one bitmap per label (IDF heap) but keeps the Python
# heap small; label.Label was measured to cost MORE overall on the C6
# (dashboard 33.5 KB vs 39.5 KB gc free) -- keep bitmap_label.
try:
    from adafruit_display_text import bitmap_label as label
except ImportError:
    from adafruit_display_text import label

import alerts
import envproto

BLACK = 0x000000
WHITE = 0xFFFFFF
YELLOW = 0xFFFF00
RED = 0xFF0000

_CW, _CH = 6, 12  # terminalio glyph cell

_BIG_METRICS = ("co2", "pm25", "tc", "rh", "voc", "nox")
_TREND_CHARS = {1: "^", -1: "v", 0: ""}


def _pal(color):
    p = displayio.Palette(1)
    p[0] = color
    return p


def _rect(x, y, w, h, color):
    pal = _pal(color)
    return vectorio.Rectangle(pixel_shader=pal, width=w, height=h,
                              x=x, y=y), pal


def _text(txt, x, y, color=BLACK, scale=1):
    return label.Label(terminalio.FONT, text=txt, color=color,
                       x=x, y=y, scale=scale)


def _fmt_value(key, value):
    if value is None:
        return "--"
    if key in ("tc", "rh", "pm25", "pm1", "pm4", "pm10"):
        return "%.1f" % value
    if key == "vb":
        return "%.2f" % value
    return "%d" % value


class Dashboard:
    def __init__(self, width, height, palette_mode="quad", lite=False):
        """lite=True (low-RAM boards, e.g. C6 with BLE resident): no big
        watermark label and at most 3 node lines -- battery warnings still
        show via the !BATT! corner tag and the node strip."""
        self.w = width
        self.h = height
        self.tri = palette_mode == "tri"
        self.warn_bg = None if self.tri else YELLOW
        root = displayio.Group()
        _bg, _ = _rect(0, 0, width, height, WHITE)
        root.append(_bg)

        # watermark layer (behind content); corner tag always exists
        self.wm = None
        if not lite:
            self.wm = _text("", 0, 0, YELLOW, 2)
            self.wm.anchor_point = (0.5, 0.5)
            self.wm.anchored_position = (width // 2, height // 2)
            self.wm.hidden = True
            root.append(self.wm)
        self.wm_tag = _text("!BATT!", width - 6 * _CW - 2, 6, RED)
        self.wm_tag.hidden = True
        root.append(self.wm_tag)

        # no-SD glyph (storage degraded)
        self.sd_glyph = displayio.Group(x=width - 14, y=1)
        for r, _p in (_rect(0, 3, 10, 10, BLACK), _rect(0, 0, 7, 4, BLACK),
                      _rect(2, 6, 6, 5, WHITE)):
            self.sd_glyph.append(r)
        _slash = vectorio.Polygon(pixel_shader=_pal(RED),
                                  points=[(0, 12), (2, 14), (12, 2), (10, 0)],
                                  x=-1, y=-1)
        self.sd_glyph.append(_slash)
        self.sd_glyph.hidden = True
        root.append(self.sd_glyph)

        # header
        self.title = _text(" " * 20, 2, 6)
        root.append(self.title)
        self.status = _text(" " * ((width // _CW) - 14), 2, height - 6)
        root.append(self.status)

        # big metric cells
        grid_top = 16
        if height >= 150:
            self.shown, rows, grid_h = _BIG_METRICS, 2, 92
        else:
            self.shown, rows, grid_h = _BIG_METRICS[:3], 1, 48
        cols = 3
        cw = width // cols
        ch = grid_h // rows
        self.cells = []
        for i, key in enumerate(self.shown):
            cx = (i % cols) * cw
            cy = grid_top + (i // cols) * ch
            bg, bg_pal = _rect(cx + 1, cy, cw - 2, ch - 1, WHITE)
            root.append(bg)
            name = _text("%s %s" % (envproto.METRIC_LABELS.get(key, key),
                                    envproto.METRIC_UNITS.get(key, "")),
                         cx + 4, cy + 8)
            root.append(name)
            val = _text("--", cx + 4, cy + 8 + 20, BLACK, 2)
            root.append(val)
            self.cells.append((key, bg_pal, name, val))

        # node strip: fixed line slots
        strip_top = grid_top + grid_h + 4
        strip_bottom = height - 24
        self.node_lines = []
        y = strip_top
        while y + _CH <= strip_bottom and len(self.node_lines) < (3 if lite else 6):
            bg, bg_pal = _rect(0, y - 1, width, _CH, WHITE)
            root.append(bg)
            lbl = _text("", 2, y + 4)
            root.append(lbl)
            self.node_lines.append((bg_pal, lbl))
            y += _CH

        # footer (out-of-spec durations)
        fbg, self.footer_pal = _rect(0, height - 22, width, 12, WHITE)
        root.append(fbg)
        self.footer = _text("", 2, height - 16)
        root.append(self.footer)

        self.root = root

    # ------------------------------------------------------------------
    def _set(self, lbl, txt, color=None):
        if lbl.text != txt:
            lbl.text = txt
        if color is not None and lbl.color != color:
            lbl.color = color

    def update(self, *, latest, tracker, zones, host_batt,
               node_batt_warnings, trends, status_line, now,
               storage_mode="sd"):
        tri = self.tri

        # watermark
        wm_texts = []
        wm_red = False
        if host_batt.get("unplugged"):
            v = host_batt.get("v")
            wm_texts.append("ON BATT" + ("" if v is None else " %.2fV" % v))
            wm_red = wm_red or host_batt.get("crit", False)
        for name, volts, crit in node_batt_warnings:
            wm_texts.append("%s BATT %.2fV" % (name.upper(), volts))
            wm_red = wm_red or crit
        if wm_texts:
            if self.wm is not None:
                wm = " * ".join(wm_texts)[: self.w // (_CW * 2)]
                self._set(self.wm, wm, RED if (wm_red or tri) else YELLOW)
                self.wm.hidden = False
            self.wm_tag.hidden = False
        else:
            if self.wm is not None:
                self.wm.hidden = True
            self.wm_tag.hidden = True

        self.sd_glyph.hidden = storage_mode == "sd"

        # header + status
        try:
            import time as _t
            t = _t.localtime(now)
            clock = "%02d:%02d" % (t[3], t[4])
        except (OverflowError, OSError):
            clock = "--:--"
        self._set(self.title, "%s  %s" % (zones.get("local", "Room"), clock))
        self._set(self.status, status_line[: (self.w // _CW) - 14])

        # big cells
        lm = latest.get("local", {}).get("m", {})
        local_trends = trends.get("local", {})
        for key, bg_pal, name, val in self.cells:
            state = tracker.state_of("local", key)
            if state == alerts.BAD:
                bg, fg = RED, WHITE
            elif state == alerts.WARN and not tri:
                bg, fg = YELLOW, BLACK
            elif state == alerts.WARN:
                bg, fg = WHITE, RED  # tri palette: red text marks warn
            else:
                bg, fg = WHITE, BLACK
            if bg_pal[0] != bg:
                bg_pal[0] = bg
            txt = _fmt_value(key, lm.get(key))
            txt += _TREND_CHARS.get(local_trends.get(key, 0), "")
            if state == alerts.WARN and tri:
                txt += "!"
            self._set(val, txt, fg)
            if name.color != fg:
                name.color = fg

        # node strip (worst first so abnormal never falls off)
        srcs = sorted((s for s in latest if s != "local"),
                      key=lambda s: -tracker.worst_for(s))
        for i, (bg_pal, lbl) in enumerate(self.node_lines):
            if i >= len(srcs):
                if i == 0 and not srcs:
                    self._set(lbl, "no nodes heard yet", BLACK)
                    bg_pal[0] = WHITE
                else:
                    self._set(lbl, "")
                    bg_pal[0] = WHITE
                continue
            src = srcs[i]
            entry = latest[src]
            m = entry.get("m", {})
            worst = tracker.worst_for(src)
            parts = [zones.get(src, src)[:10]]
            for key in ("co2", "pm25", "tc", "rh"):
                if m.get(key) is not None:
                    parts.append("%s%s" % (_fmt_value(key, m[key]),
                                           envproto.METRIC_UNITS.get(key, "")))
            if entry.get("vb") is not None:
                parts.append("%.2fV" % entry["vb"])
            parts.append(alerts.fmt_duration(max(0, now - entry.get("ts", now))))
            line = " ".join(parts)
            if worst == alerts.BAD:
                bg_pal[0] = RED
                fg = WHITE
            elif worst == alerts.WARN and not tri:
                bg_pal[0] = YELLOW
                fg = BLACK
            elif worst == alerts.WARN:
                bg_pal[0] = WHITE
                fg = RED
                line = "! " + line
            else:
                bg_pal[0] = WHITE
                fg = BLACK
            self._set(lbl, line[: self.w // _CW], fg)

        # footer
        active = tracker.active_abnormal(now)
        if active:
            bits = ["%s %s %s %s" % (zones.get(a["src"], a["src"])[:8],
                                     a["metric"], a["state"],
                                     alerts.fmt_duration(a["for_s"]))
                    for a in active[:4]]
            worst_bad = any(a["state"] == "bad" for a in active)
            if worst_bad:
                self.footer_pal[0] = RED
                fg = WHITE
            elif not tri:
                self.footer_pal[0] = YELLOW
                fg = BLACK
            else:
                self.footer_pal[0] = WHITE
                fg = RED
            self._set(self.footer, ("OUT: " + "; ".join(bits))[: self.w // _CW],
                      fg)
        else:
            self.footer_pal[0] = WHITE
            self._set(self.footer, "")
        return self.root
