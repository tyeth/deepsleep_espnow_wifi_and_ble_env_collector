#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Observe an uninterrupted CircuitPython Wi-Fi/BLE scan soak over a USB or UART raw REPL.

No firmware or filesystem writes and no automatic reset/reconnect. A failure
ends the run as failed; only the full requested duration can produce a pass.
Requires pyserial and serial_deploy.py beside this script.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time

SETUP = '''import sys, board, gc, time, wifi, _bleio, json
_bleio.adapter.enabled=True
wifi.radio.stop_station()
wifi.radio.start_station()
def _envhub_cycle():
 gc.collect()
 started=time.monotonic()
 ble=_bleio.adapter.start_scan(timeout=5,buffer_size=1024)
 try:
  aps=0
  for network in wifi.radio.start_scanning_networks():
   aps+=1
  wifi.radio.stop_scanning_networks()
  adverts=0
  for entry in ble:
   adverts+=1
 finally:
  wifi.radio.stop_scanning_networks()
  _bleio.adapter.stop_scan()
 del ble
 gc.collect()
 return {"wifi":aps,"ble":adverts,"seconds":time.monotonic()-started,"gc_allocated":gc.mem_alloc(),"gc_free_estimate":gc.mem_free()}
print("ENVHUB_IDENTITY",json.dumps({"version":sys.version,"board":board.board_id}))
'''
CYCLE = 'print("ENVHUB_CYCLE",json.dumps(_envhub_cycle()))'


def record_from_output(output, marker):
    records = [line[len(marker) + 1:] for line in output.splitlines()
               if line.startswith(marker + " ")]
    if len(records) != 1:
        raise ValueError(f"Expected one {marker} record, got {len(records)}")
    result = json.loads(records[0])
    if not isinstance(result, dict):
        raise ValueError("Record must be an object")
    return result


def validate_cycle(record):
    for key in ("wifi", "ble", "gc_allocated", "gc_free_estimate"):
        if type(record.get(key)) is not int or record[key] < 0:
            raise ValueError(f"Invalid cycle metric: {key}")
    seconds = record.get("seconds")
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0 < seconds < 25:
        raise ValueError("Scan cycle exceeded its 25-second bound")
    return record


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_status(directory, status):
    temporary = directory / "status.tmp"
    temporary.write_text(json.dumps(status, indent=2) + "\n")
    temporary.replace(directory / "status.json")


def select_console(ports, serial_number, vid):
    matches = [port for port in ports
               if port.serial_number == serial_number and port.vid == vid]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one selected CircuitPython console, found {len(matches)}")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial-number", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--usb-vid", type=lambda value: int(value, 0), default=0x1209,
                        help="USB vendor ID of the selected console (default: 0x1209)")
    parser.add_argument("--uart", action="store_true",
                        help="Keep UART bridge DTR/RTS deasserted to avoid a reset")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hours", type=float, default=8)
    parser.add_argument("--interval", type=float, default=30)
    args = parser.parse_args()
    if not math.isfinite(args.hours) or args.hours <= 0 or not 10 <= args.interval <= 60:
        parser.error("hours must be positive and interval must be 10..60 seconds")
    from serial.tools import list_ports
    from serial_deploy import Repl
    port = select_console(list_ports.comports(), args.serial_number, args.usb_vid)
    args.output.mkdir(parents=True, exist_ok=False)
    status = dict(status="starting", created_utc=utc_now(), duration_s=args.hours * 3600,
                  serial_number=args.serial_number, port=port.device, usb_vid=args.usb_vid, uart=args.uart,
                  revision=args.revision, cycles=0, failures=[],
                  note="GC free includes a port estimate; it is not measured physical free RAM.")
    save_status(args.output, status)
    repl = None
    started = None
    try:
        repl = Repl(port.device, uart_bridge=args.uart)
        repl.enter_raw()
        identity = record_from_output(repl.exec(SETUP, timeout=30), "ENVHUB_IDENTITY")
        if args.revision not in identity.get("version", ""):
            raise RuntimeError(f"Unexpected firmware version: {identity}")
        status.update(identity=identity, status="running", started_utc=utc_now())
        started = time.monotonic()
        deadline = started + status["duration_s"]
        last_finished = started
        empty_wifi = empty_ble = 0
        with (args.output / "cycles.jsonl").open("a", buffering=1) as log:
            while time.monotonic() < deadline:
                cycle_started = time.monotonic()
                output = repl.exec(CYCLE, timeout=35)
                sample = validate_cycle(record_from_output(output, "ENVHUB_CYCLE"))
                finished = time.monotonic()
                gap = finished - last_finished
                if gap > args.interval + 35:
                    raise RuntimeError(f"Observer cycle gap {gap:.1f}s")
                last_finished = finished
                empty_wifi = empty_wifi + 1 if sample["wifi"] == 0 else 0
                empty_ble = empty_ble + 1 if sample["ble"] == 0 else 0
                if max(empty_wifi, empty_ble) >= 3:
                    raise RuntimeError("Three consecutive cycles received no Wi-Fi or BLE results")
                status["cycles"] += 1
                sample.update(cycle=status["cycles"], utc=utc_now(), elapsed_s=round(finished-started, 2))
                log.write(json.dumps(sample) + "\n")
                status.update(last_cycle=sample, elapsed_s=sample["elapsed_s"], updated_utc=utc_now())
                save_status(args.output, status)
                print(json.dumps(sample), flush=True)
                time.sleep(max(0, min(deadline, cycle_started + args.interval) - time.monotonic()))
        if not status["cycles"]:
            raise RuntimeError("No complete scan cycles observed")
        status.update(status="passed", elapsed_s=round(time.monotonic()-started, 2))
    except BaseException as exc:
        status.update(status="failed", updated_utc=utc_now())
        status["failures"].append(f"{type(exc).__name__}: {exc}")
        if started is not None:
            status["elapsed_s"] = round(time.monotonic()-started, 2)
        save_status(args.output, status)
        raise
    finally:
        cleanup_error = None
        if repl is not None:
            for operation in (repl.exit_raw, repl.close):
                try:
                    operation()
                except Exception as exc:
                    cleanup_error = exc
                    status["status"] = "failed"
                    status["failures"].append(f"Console cleanup: {type(exc).__name__}: {exc}")
        status["finished_utc"] = utc_now()
        save_status(args.output, status)
        if cleanup_error is not None:
            raise RuntimeError("Console cleanup failed; see status.json") from cleanup_error
    print("PICO_RADIO_SOAK_PASS", json.dumps(status), flush=True)


if __name__ == "__main__":
    main()
