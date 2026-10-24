#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read saved soak evidence without opening hardware or changing any files.

Exit 0: terminal recorder pass with consistent evidence; 2: provisional;
1: failed/inconsistent evidence. This does not establish the service stopped.
Memory summaries describe observations, not a statistical leak verdict.
"""
import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re


FATAL = re.compile(r"Traceback \(most recent|Guru Meditation|panic'ed|loop MemoryError|"
                   r"persistent errors|receiver dead|receive buffer corrupt|softAP dropped")


def stamp(value):
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Evidence timestamp lacks timezone")
    return result.timestamp()


def finite(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("Evidence metric is not finite numeric data")
    return value


def summary(values):
    values = [finite(v) for v in values]
    if not values:
        return {"samples": 0}
    return dict(samples=len(values), first=values[0], last=values[-1],
                minimum=min(values), maximum=max(values), delta=values[-1]-values[0])


def gap(times, start, end):
    times = [start] + sorted(t for t in times if start <= t <= end) + [end]
    return round(max(b-a for a, b in zip(times, times[1:])), 3)


def report(directory, required_hours=8):
    directory = Path(directory)
    hashes = {}
    issues = []
    provisional = False

    def read(name):
        data = (directory / name).read_bytes()
        hashes[name] = hashlib.sha256(data).hexdigest()
        return data.decode("utf-8")

    status = json.loads(read("status.json"))
    terminal = status["status"] not in ("starting", "running")
    provisional = not terminal

    def records(name):
        source = read(name)
        lines = source.splitlines()
        rows = []
        for index, line in enumerate(lines):
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # Only an incomplete last append can be tolerated during a run.
                if not terminal and index == len(lines)-1 and not source.endswith("\n"):
                    break
                raise ValueError(f"Invalid JSON record in {name} at line {index+1}") from None
        return rows

    start = stamp(status["started_utc"])
    elapsed = finite(status["elapsed_s"])
    duration = finite(status["duration_s"])
    if elapsed < 0 or duration <= 0:
        issues.append("invalid duration")
    if duration < required_hours * 3600:
        issues.append("configured duration shorter than required soak")
    end = stamp(status["finished_utc"]) if terminal else start + elapsed
    if end < start:
        issues.append("finish precedes start")
    if terminal and (status["status"] != "passed" or status.get("failures")):
        issues.append("recorder did not finish with a clean pass")
    if not terminal and status.get("failures"):
        issues.append("recorder already recorded failures")
    if terminal and (elapsed < duration or end-start < duration-1):
        issues.append("terminal evidence is shorter than configured duration")
    metrics = {}

    def compare(key, actual):
        if terminal and status.get(key) != actual:
            issues.append(f"{key} count differs between status and logs")

    if "normal_ca_trust" in status:
        mode = "trusted_https"
        rows = records("cycles.jsonl")
        compare("cycles", len(rows))
        failed = sum(row.get("status") != "passed" for row in rows)
        compare("errors", failed)
        if failed or status.get("errors"):
            issues.append("HTTPS request failures recorded")
        if (status.get("normal_ca_trust") is not True
                or status.get("hostname_checking") is not True
                or not status.get("host")
                or not re.fullmatch(r"[0-9a-f]{64}", status.get("leaf_sha256", ""))):
            issues.append("missing trusted HTTPS identity evidence")
        interval = finite(status["interval_s"])
        if interval != 120:
            issues.append("unexpected HTTPS observation interval")
        if not rows or (terminal and len(rows) < math.floor(duration / 120)):
            issues.append("insufficient HTTPS observations")
        previous = 0
        for index, row in enumerate(rows, 1):
            offset = finite(row["elapsed_s"])
            if row["cycle"] != index or not previous < offset <= elapsed + 1:
                issues.append("HTTPS sequence or elapsed time is inconsistent")
            previous = offset
            seconds = finite(row["seconds"])
            if not 0 < seconds <= 65:
                issues.append("HTTPS cycle exceeded its bound")
            if abs(stamp(row["utc"]) - start - (offset - seconds)) > 2:
                issues.append("HTTPS timestamp differs from elapsed evidence")
            if row.get("status") == "passed":
                responses = row.get("responses", [])
                if ([r.get("path") for r in responses]
                        != ["/api/latest", "/api/history", "/api/cert"]
                        or row.get("tls_version") not in ("TLSv1.2", "TLSv1.3")):
                    issues.append("incomplete HTTPS session evidence")
                for response in responses:
                    if (response.get("status") != 200
                            or not 0 < finite(response.get("bytes")) <= 65536
                            or not re.fullmatch(r"[0-9a-f]{64}", response.get("sha256", ""))):
                        issues.append("invalid HTTPS response evidence")
        metrics.update(cycles=len(rows), errors=failed,
                       seconds=summary([r["seconds"] for r in rows]),
                       max_cycle_gap_s=gap([r["elapsed_s"] for r in rows], 0, elapsed))
        if metrics["max_cycle_gap_s"] > 185:
            issues.append("HTTPS evidence gap exceeds recorder bound")
    elif "cycles" in status:
        mode = "wifi_ble_scan"
        rows = records("cycles.jsonl")
        compare("cycles", len(rows))
        if not rows:
            issues.append("no scan evidence")
        previous = 0
        zero_wifi = zero_ble = 0
        for index, row in enumerate(rows, 1):
            if row["cycle"] != index or finite(row["elapsed_s"]) <= previous:
                issues.append("scan sequence or elapsed time is not increasing")
            previous = row["elapsed_s"]
            if not 0 < finite(row["seconds"]) < 25:
                issues.append("scan exceeded the 25-second bound")
            for key in ("wifi", "ble", "gc_allocated", "gc_free_estimate"):
                if type(row[key]) is not int or row[key] < 0:
                    issues.append("invalid scan metric: " + key)
            zero_wifi = zero_wifi + 1 if row["wifi"] == 0 else 0
            zero_ble = zero_ble + 1 if row["ble"] == 0 else 0
            if max(zero_wifi, zero_ble) >= 3:
                issues.append("three consecutive empty radio scans")
        metrics["cycles"] = len(rows)
        for key in ("seconds", "wifi", "ble", "gc_allocated", "gc_free_estimate"):
            metrics[key] = summary([r[key] for r in rows])
        metrics["max_cycle_gap_s"] = gap([r["elapsed_s"] for r in rows], 0, elapsed)
        if metrics["max_cycle_gap_s"] > 95:
            issues.append("scan evidence gap exceeds maximum recorder bound")
        if status.get("revision") not in status.get("identity", {}).get("version", ""):
            issues.append("firmware identity does not contain expected revision")
        metrics["memory_note"] = "GC free is a port estimate, not measured physical free RAM."
    else:
        mode = "collector_node_application"
        config = json.loads(read("manifest.json"))
        counts = dict(confirmations=0, sleep_requests=0, true_sleep_wakes=0, collector_starts=0)
        deliveries = []
        fatal_lines = 0
        for board in config["boards"]:
            name = board["name"]
            if not re.fullmatch(r"[\w-]+", name):
                raise ValueError("Invalid board evidence filename")
            for line in read(name + ".log").splitlines():
                when, message = line.split(" ", 1)
                timestamp = stamp(when)
                fatal_lines += bool(FATAL.search(message))
                if "delivered: hub confirmed" in message:
                    counts["confirmations"] += 1
                    deliveries.append(timestamp)
                counts["sleep_requests"] += "deep sleep " in message
                counts["true_sleep_wakes"] += "wake:" in message and "ResetReason.DEEP_SLEEP_ALARM" in message
                counts["collector_starts"] += "collector running; portal:" in message
        for key, actual in counts.items():
            compare(key, actual)
        metrics.update(counts, fatal_lines=fatal_lines)
        if fatal_lines or counts["collector_starts"] > 1 or status.get("serial_errors", 0):
            issues.append("fatal log, collector restart or serial interruption")
        if terminal and (not counts["sleep_requests"] or (config.get("require_true_sleep", True) and not counts["true_sleep_wakes"])):
            issues.append("missing sleep evidence")
        if terminal and counts["confirmations"] < max(1, math.floor(duration/300)):
            issues.append("insufficient confirmed deliveries")
        http = records("http.jsonl")
        ble = records("ble.jsonl")
        http_ok = [r for r in http if "data" in r and "error" not in r]
        ble_ok = [r for r in ble if r["kind"] == "ble_ok"]
        for key, actual in (("http_ok", len(http_ok)), ("http_errors", len(http)-len(http_ok)),
                            ("ble_ok", len(ble_ok)), ("ble_errors", len(ble)-len(ble_ok))):
            metrics[key] = actual
            compare(key, actual)
        for key, times, limit in (("delivery", deliveries, config.get("max_delivery_gap_s", 300)),
                                  ("http", [stamp(r["utc"]) for r in http_ok], 120),
                                  ("ble", [stamp(r["utc"]) for r in ble_ok], 300)):
            if key == "ble" and not config.get("ble_name"):
                continue
            metrics["max_" + key + "_gap_s"] = gap(times, start, end)
            if metrics["max_" + key + "_gap_s"] > limit:
                issues.append(key + " evidence gap exceeds configured limit")
        metrics["ble_free_bytes"] = summary([r["data"]["mem"]["free"] for r in ble_ok])
        metrics["sensor"] = config.get("sensor", "unspecified")
    verdict = "inconsistent" if issues else "provisional" if provisional else "consistent"
    return dict(evidence_directory=directory.name, recorder_status=status["status"],
                evidence_verdict=verdict, mode=mode, elapsed_s=elapsed, duration_s=duration,
                metrics=metrics, issues=list(dict.fromkeys(issues)), sha256=hashes,
                note="Live snapshots are provisional. Service shutdown must be checked separately.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--required-hours", type=float, default=8)
    args = parser.parse_args()
    if not math.isfinite(args.required_hours) or args.required_hours <= 0:
        parser.error("required-hours must be positive and finite")
    try:
        result = report(args.directory, args.required_hours)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Avoid printing source data or private serial messages on malformed input.
        print(json.dumps({"evidence_verdict": "inconsistent", "error_type": type(exc).__name__}))
        return 1
    print(json.dumps(result, indent=2))
    return {"consistent": 0, "provisional": 2, "inconsistent": 1}[result["evidence_verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
