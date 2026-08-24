# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
display_ui - layout for the 3.52" quad-color (black/white/yellow/red) eInk.

Design rules from the project spec:
  * Local room values LARGE, with a yellow (warn) or red (bad) highlight
    behind any metric that is out of spec.
  * Remote nodes in tiny text at the bottom -- unless abnormal, in which case
    that node's line gets a colored highlight.
  * Battery warnings (node batteries, or host running unplugged) render as a
    WATERMARK: a big pale layer BEHIND the content, visually obvious without
    ruining the data display.
  * Footer shows how long each zone has been out of spec.

The screen is rebuilt as a fresh displayio.Group per refresh (2 min default)
-- cheap at this cadence, and gc.collect() in the main loop reclaims it.
"""

import displayio
import terminalio
import vectorio

# bitmap_label renders each string into ONE small bitmap instead of
# per-glyph tilegrids -- far less RAM/fragmentation on no-PSRAM boards
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

# Quad palette (3.52") has yellow for WARN; tri palette (2.9" red/black/
# white) has no yellow, so WARN renders as red accent bars + "!" markers
# instead of a filled cell.
_STATE_FG = {alerts.OK: BLACK, alerts.WARN: BLACK, alerts.BAD: WHITE}


def _state_bg(palette_mode):
    if palette_mode == "tri":
        return {alerts.WARN: None, alerts.BAD: RED}
    return {alerts.WARN: YELLOW, alerts.BAD: RED}

# terminalio.FONT glyph cell
_CW, _CH = 6, 12

# Local metrics shown as big cells, in priority order
_BIG_METRICS = ("co2", "pm25", "tc", "rh", "voc", "nox")

_TREND_CHARS = {1: "^", -1: "v", 0: ""}


def _palette(color):
    pal = displayio.Palette(1)
    pal[0] = color
    return pal


def _rect(x, y, w, h, color):
    return vectorio.Rectangle(
        pixel_shader=_palette(color), width=w, height=h, x=x, y=y
    )


def _text(txt, x, y, color=BLACK, scale=1):
    return label.Label(
        terminalio.FONT, text=txt, color=color, x=x, y=y, scale=scale
    )


def _fmt_value(key, value):
    if value is None:
        return "--"
    if key in ("tc", "rh", "pm25", "pm1", "pm4", "pm10"):
        return "%.1f" % value
    if key == "vb":
        return "%.2f" % value
    return "%d" % value


def _no_sd_glyph(root, x, y):
    """Tiny (10x13) SD-card silhouette with a red slash: storage degraded."""
    root.append(_rect(x, y + 3, 10, 10, BLACK))          # card body
    root.append(_rect(x, y, 7, 4, BLACK))                # body top, notched
    root.append(_rect(x + 2, y + 6, 6, 5, WHITE))        # contact window
    root.append(vectorio.Polygon(
        pixel_shader=_palette(RED),
        points=[(0, 12), (2, 14), (12, 2), (10, 0)],
        x=x - 1, y=y - 1,
    ))


def _batt_watermark_texts(host_batt, node_batt_warnings):
    texts = []
    worst_red = False
    if host_batt.get("unplugged"):
        v = host_batt.get("v")
        texts.append("ON BATT" + ("" if v is None else " %.2fV" % v))
        worst_red = worst_red or host_batt.get("crit", False)
    for name, volts, crit in node_batt_warnings:
        texts.append("%s BATT %.2fV" % (name.upper(), volts))
        worst_red = worst_red or crit
    return texts, worst_red


def build_screen(*, width, height, latest, tracker, zones, host_batt,
                 node_batt_warnings, trends, status_line, now,
                 palette_mode="quad", storage_mode="sd"):
    """Build the full screen Group.

    latest: datastore.latest ({src: {"ts","m","vb",...}})
    tracker: alerts.AlertTracker
    zones: {src: display name}
    host_batt: battery.BatteryMonitor.status() dict
    node_batt_warnings: [(name, volts, crit_bool), ...]
    trends: {src: {metric: -1|0|1}}
    status_line: short str e.g. "W:ok SD:ok B:adv 192.168.1.7"
    now: epoch seconds
    palette_mode: "quad" (has yellow) or "tri" (black/white/red only)
    """
    state_bg = _state_bg(palette_mode)
    warn_color = RED if palette_mode == "tri" else YELLOW
    root = displayio.Group()
    root.append(_rect(0, 0, width, height, WHITE))

    # ---- watermark layer (behind everything else) ----
    wm_texts, wm_red = _batt_watermark_texts(host_batt, node_batt_warnings)
    if wm_texts:
        wm_color = RED if wm_red else warn_color
        wm = " * ".join(wm_texts)
        wm_scale = 3 if len(wm) * _CW * 3 <= width else 2
        wm_label = _text(wm[: width // (_CW * wm_scale)], 0, 0, wm_color, wm_scale)
        wm_label.anchor_point = (0.5, 0.5)
        wm_label.anchored_position = (width // 2, height // 2)
        root.append(wm_label)
        # small always-legible strip too, top-right corner
        root.append(_text("!BATT!", width - 6 * _CW - 2, 6, wm_color))

    # ---- storage indicator: tiny crossed SD glyph when not on SD ----
    if storage_mode != "sd":
        gx = width - 14 - ((6 * _CW + 6) if wm_texts else 0)
        _no_sd_glyph(root, gx, 1)

    # ---- header ----
    t = None
    try:
        import time as _time
        t = _time.localtime(now)
    except (OverflowError, OSError):
        pass
    clock = "%02d:%02d" % (t[3], t[4]) if t else "--:--"
    local_name = zones.get("local", "Room")
    root.append(_text("%s  %s" % (local_name, clock), 2, 6, BLACK))
    root.append(_text(status_line[: (width // _CW) - 14], 2, height - 6, BLACK))

    # ---- local metric cells (3x2 on big panels, 3x1 on the 2.9") ----
    local = latest.get("local", {})
    lm = local.get("m", {})
    grid_top = 16
    if height >= 150:
        shown, rows, grid_h = _BIG_METRICS, 2, 92
    else:
        shown, rows, grid_h = _BIG_METRICS[:3], 1, 48
    cols = 3
    cell_w = width // cols
    cell_h = grid_h // rows
    local_trends = trends.get("local", {})
    for i, key in enumerate(shown):
        cx = (i % cols) * cell_w
        cy = grid_top + (i // cols) * cell_h
        state = tracker.state_of("local", key)
        bg = state_bg.get(state)
        if bg is not None:
            root.append(_rect(cx + 1, cy, cell_w - 2, cell_h - 1, bg))
            fg = _STATE_FG[state]
        elif state != alerts.OK:
            # tri palette WARN: red accent bars + "!" instead of yellow fill
            root.append(_rect(cx + 1, cy, cell_w - 2, 3, RED))
            root.append(_rect(cx + 1, cy + cell_h - 4, cell_w - 2, 3, RED))
            fg = BLACK
        else:
            fg = _STATE_FG[state]
        name = envproto.METRIC_LABELS.get(key, key)
        unit = envproto.METRIC_UNITS.get(key, "")
        mark = "!" if (state != alerts.OK and bg is None) else ""
        root.append(_text("%s %s%s" % (name, unit, mark), cx + 4, cy + 8, fg))
        val = _fmt_value(key, lm.get(key))
        # trend arrow folded into the value string (one label, not two)
        val += _TREND_CHARS.get(local_trends.get(key, 0), "")
        root.append(_text(val, cx + 4, cy + 8 + 20, fg, scale=2))

    # ---- remote node strip (tiny text; abnormal lines highlighted) ----
    strip_top = grid_top + grid_h + 4
    strip_bottom = height - 24
    line_h = _CH
    y = strip_top
    node_srcs = sorted(s for s in latest if s != "local")
    # abnormal nodes first so they never fall off the bottom
    node_srcs.sort(key=lambda s: -tracker.worst_for(s))
    for src in node_srcs:
        if y + line_h > strip_bottom:
            root.append(_text("+%d more" % (len(node_srcs) - node_srcs.index(src)),
                              width - 9 * _CW, y + 4, BLACK))
            break
        entry = latest[src]
        m = entry.get("m", {})
        worst = tracker.worst_for(src)
        age = alerts.fmt_duration(max(0, now - entry.get("ts", now)))
        parts = [zones.get(src, src)[:10]]
        for key in ("co2", "pm25", "tc", "rh"):
            if m.get(key) is not None:
                parts.append("%s%s" % (_fmt_value(key, m[key]),
                                       envproto.METRIC_UNITS.get(key, "")))
        if entry.get("vb") is not None:
            parts.append("%.2fV" % entry["vb"])
        parts.append(age)
        line = " ".join(parts)
        fg = _STATE_FG[worst]
        if worst != alerts.OK:
            bg = state_bg.get(worst)
            if bg is not None:
                root.append(_rect(0, y - 1, width, line_h, bg))
            else:  # tri palette WARN
                root.append(_rect(0, y + line_h - 2, width, 2, RED))
                line = "! " + line
                fg = BLACK
        root.append(_text(line[: width // _CW], 2, y + 4, fg))
        y += line_h

    if not node_srcs:
        root.append(_text("no nodes heard yet", 2, strip_top + 4, BLACK))

    # ---- footer: active out-of-spec durations ----
    active = tracker.active_abnormal(now)
    if active:
        bits = []
        for a in active[:4]:
            bits.append("%s %s %s %s" % (
                zones.get(a["src"], a["src"])[:8], a["metric"],
                a["state"], alerts.fmt_duration(a["for_s"]),
            ))
        line = "OUT: " + "; ".join(bits)
        worst_bad = any(a["state"] == "bad" for a in active)
        if worst_bad or palette_mode != "tri":
            root.append(_rect(0, height - 22, width, 12,
                              RED if worst_bad else warn_color))
            root.append(_text(line[: width // _CW], 2, height - 16,
                              WHITE if worst_bad else BLACK))
        else:  # tri palette warn footer: red text on white
            root.append(_text(line[: width // _CW], 2, height - 16, RED))
    return root
