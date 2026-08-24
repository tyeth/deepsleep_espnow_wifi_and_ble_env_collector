# SPDX-FileCopyrightText: 2026 Adafruit Industries
# SPDX-License-Identifier: MIT
"""
alerts - classify metric values against thresholds and track how long each
zone/metric has been out of spec.

States: 0 = OK, 1 = WARN (yellow), 2 = BAD (red).

Threshold dicts (from config.json) support upper bounds ("warn"/"bad") and
optional lower bounds ("lo_warn"/"lo_bad") for range metrics like temp/rh.
"""

import time

OK = 0
WARN = 1
BAD = 2

STATE_NAMES = ("ok", "warn", "bad")


def classify(value, th):
    """Return OK/WARN/BAD for value against a threshold dict (or OK if none)."""
    if value is None or th is None:
        return OK
    if "bad" in th and value >= th["bad"]:
        return BAD
    if "lo_bad" in th and value <= th["lo_bad"]:
        return BAD
    if "warn" in th and value >= th["warn"]:
        return WARN
    if "lo_warn" in th and value <= th["lo_warn"]:
        return WARN
    return OK


class AlertTracker:
    """Tracks (source, metric) alert states and transition timestamps.

    on_event(event_dict) is called on every state change so the datastore can
    log it (and force-flush to SD for BAD transitions). Event dict:
      {"ts": epoch, "src": name, "metric": key, "state": "warn",
       "prev": "ok", "value": v, "held_s": seconds_in_previous_state}
    """

    def __init__(self, thresholds, on_event=None):
        self.thresholds = thresholds
        self.on_event = on_event
        # (src, metric) -> [state, since_epoch]
        self._states = {}

    def update(self, src, metrics, now=None):
        """Feed the latest metric dict for a source. Returns worst state."""
        now = now if now is not None else int(time.time())
        worst = OK
        for key, value in metrics.items():
            th = self.thresholds.get(key)
            if th is None:
                continue
            state = classify(value, th)
            worst = max(worst, state)
            slot = self._states.get((src, key))
            if slot is None:
                self._states[(src, key)] = [state, now]
                if state != OK and self.on_event:
                    self.on_event({
                        "ts": now, "src": src, "metric": key,
                        "state": STATE_NAMES[state], "prev": "ok",
                        "value": value, "held_s": 0,
                    })
            elif slot[0] != state:
                if self.on_event:
                    self.on_event({
                        "ts": now, "src": src, "metric": key,
                        "state": STATE_NAMES[state],
                        "prev": STATE_NAMES[slot[0]],
                        "value": value, "held_s": now - slot[1],
                    })
                slot[0] = state
                slot[1] = now
        return worst

    def state_of(self, src, metric):
        slot = self._states.get((src, metric))
        return slot[0] if slot else OK

    def worst_for(self, src):
        worst = OK
        for (s, _), slot in self._states.items():
            if s == src:
                worst = max(worst, slot[0])
        return worst

    def active_abnormal(self, now=None):
        """List of dicts for everything currently out of spec, worst first."""
        now = now if now is not None else int(time.time())
        out = []
        for (src, metric), (state, since) in self._states.items():
            if state != OK:
                out.append({
                    "src": src, "metric": metric,
                    "state": STATE_NAMES[state],
                    "for_s": now - since,
                })
        out.sort(key=lambda e: (e["state"] != "bad", -e["for_s"]))
        return out


def fmt_duration(seconds):
    """Compact human duration: 95 -> '1m35', 8100 -> '2h15'."""
    seconds = int(seconds)
    if seconds < 60:
        return "%ds" % seconds
    if seconds < 3600:
        return "%dm%02d" % (seconds // 60, seconds % 60)
    if seconds < 86400:
        return "%dh%02d" % (seconds // 3600, (seconds % 3600) // 60)
    return "%dd%02d" % (seconds // 86400, (seconds % 86400) // 3600)
