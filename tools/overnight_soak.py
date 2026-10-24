#!/usr/bin/env python3
"""Observe an uninterrupted collector/node run; never reset a stalled DUT.

Config JSON: boards=[{name, role: collector|node, port, uart: true}],
url="http://192.168.4.1", hours=8, max_delivery_gap_s=300.
Requires pyserial. Run under systemd on the host, not in an SSH session.
Raw serial logs, HTTP samples and atomic status.json remain in --output.
Synthetic sensor data must be labelled in the config (sensor="sim").
"""
import argparse
import asyncio
import datetime
import json
import math
from pathlib import Path
import queue
import re
import threading
import time
import urllib.request

import serial


FATAL = re.compile(r"Traceback \(most recent|Guru Meditation|panic'ed|loop MemoryError|"
                   r"persistent errors|receiver dead|receive buffer corrupt|softAP dropped")


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def serial_reader(board, events, stop):
    """One open per DUT. Reconnects are recorded as failures, never hidden."""
    while not stop.is_set():
        try:
            port = serial.Serial(port=None, baudrate=115200, timeout=0.5, exclusive=True)
            port.port = board['port']
            port.dtr = not board.get('uart', True)
            port.rts = False
            with port:
                pending = b''
                while not stop.is_set():
                    pending += port.read(max(1, min(4096, port.in_waiting)))
                    # CP consoles may emit CRCRLF. Preserve nonempty lines.
                    lines = re.split(b'[\r\n]+', pending)
                    pending = lines.pop()
                    for line in lines:
                        if line:
                            events.put(('serial', board['name'], line.decode('utf8', 'replace')))
                    if len(pending) > 16384:
                        events.put(('serial', board['name'], pending.decode('utf8', 'replace')))
                        pending = b''
        except (OSError, serial.SerialException) as exc:
            events.put(('serial_error', board['name'], str(exc)))
            stop.wait(5)


def request_json(url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


async def ble_probe(name):
    from bleak import BleakClient, BleakScanner
    device = await BleakScanner.find_device_by_filter(
        lambda d, ad: (ad.local_name or d.name or '') == name, timeout=12)
    if device is None:
        raise TimeoutError('BLE advertisement not found: ' + name)
    lines = asyncio.Queue()
    pending = bytearray()

    def notify(_, data):
        pending.extend(data)
        while b'\n' in pending:
            line, _, rest = bytes(pending).partition(b'\n')
            pending[:] = rest
            lines.put_nowait(line)

    result = {}
    async with BleakClient(device, timeout=20) as client:
        await client.start_notify('6e400003-b5a3-f393-e0a9-e50e24dcca9e', notify)
        for command in ('mem', 'latest'):
            await client.write_gatt_char('6e400002-b5a3-f393-e0a9-e50e24dcca9e',
                                        (command + '\n').encode(), response=False)
            result[command] = json.loads(await asyncio.wait_for(lines.get(), 20))
    return result


def ble_reader(name, events, stop):
    while not stop.is_set():
        try:
            events.put(('ble_ok', 'ble', asyncio.run(ble_probe(name))))
        except Exception as exc:
            events.put(('ble_error', 'ble', str(exc)))
        stop.wait(120)


def run(config, output):
    output.mkdir(parents=True, exist_ok=False)
    (output / 'manifest.json').write_text(json.dumps(config, indent=2))
    duration = float(config.get('hours', 8)) * 3600
    if duration <= 0:
        raise ValueError('hours must be positive')
    names = [b['name'] for b in config['boards']]
    if len(names) != len(set(names)):
        raise ValueError('board names must be unique')
    events, stop = queue.Queue(), threading.Event()
    start = time.monotonic()
    state = dict(started_utc=utc(), status='running', duration_s=duration,
                 sensor=config.get('sensor', 'unspecified'), elapsed_s=0,
                 confirmations=0, sleep_requests=0, http_ok=0, http_errors=0,
                 collector_starts=0, serial_errors=0, true_sleep_wakes=0,
                 ble_ok=0, ble_errors=0, failures=[], last_delivery_utc=None)
    logs = {name: (output / (name + '.log')).open('a', buffering=1) for name in names}
    http_log = (output / 'http.jsonl').open('a', buffering=1)
    ble_log = (output / 'ble.jsonl').open('a', buffering=1)
    threads = [threading.Thread(target=serial_reader, args=(b, events, stop), daemon=True)
               for b in config['boards']]
    if config.get('ble_name'):
        threads.append(threading.Thread(target=ble_reader,
                       args=(config['ble_name'], events, stop), daemon=True))
    for thread in threads:
        thread.start()
    next_http = next_status = start
    last_delivery = last_http = last_ble = start
    synced = False

    def fail(reason):
        if reason not in state['failures']:
            state['failures'].append(reason)

    def save():
        state['elapsed_s'] = round(time.monotonic() - start, 1)
        tmp = output / 'status.tmp'
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(output / 'status.json')

    try:
        while time.monotonic() - start < duration:
            now = time.monotonic()
            try:
                kind, name, line = events.get(timeout=0.1)
                if kind.startswith('ble_'):
                    ble_log.write(json.dumps(dict(utc=utc(), kind=kind, data=line)) + '\n')
                    if kind == 'ble_ok':
                        state['ble_ok'] += 1
                        last_ble = now
                    else:
                        state['ble_errors'] += 1
                else:
                    logs[name].write(utc() + ' ' + line + '\n')
                if kind == 'serial_error':
                    state['serial_errors'] += 1
                    fail(name + ': serial connection interrupted')
                elif kind == 'serial':
                    if FATAL.search(line):
                        fail(name + ': ' + line[-300:])
                    if 'delivered: hub confirmed' in line:
                        state['confirmations'] += 1
                        last_delivery = now
                        state['last_delivery_utc'] = utc()
                    if 'deep sleep ' in line:
                        state['sleep_requests'] += 1
                    if 'wake:' in line and 'ResetReason.DEEP_SLEEP_ALARM' in line:
                        state['true_sleep_wakes'] += 1
                    if 'collector running; portal:' in line:
                        state['collector_starts'] += 1
                        synced = False
                        if state['collector_starts'] > 1:
                            fail('collector restarted during the run')
            except queue.Empty:
                pass
            if now >= next_http:
                next_http = now + 30
                try:
                    if not synced:
                        request_json(config['url'].rstrip('/') + '/api/time',
                                     {'epoch': int(time.time()), 'tz_offset_min': 0})
                        synced = True
                    data = request_json(config['url'].rstrip('/') + '/api/latest')
                    http_log.write(json.dumps(dict(utc=utc(), data=data)) + '\n')
                    state['http_ok'] += 1
                    last_http = now
                except Exception as exc:
                    state['http_errors'] += 1
                    http_log.write(json.dumps(dict(utc=utc(), error=str(exc))) + '\n')
            gap = float(config.get('max_delivery_gap_s', 300))
            if now - last_delivery > gap:
                fail('no confirmed delivery for more than %gs' % gap)
            if now - last_http > 120:
                fail('HTTP unavailable for more than 120s')
            if config.get('ble_name') and now - last_ble > 300:
                fail('BLE unavailable for more than 300s')
            if now >= next_status:
                next_status = now + 10
                save()
        if state['confirmations'] < max(1, math.floor(duration / 300)):
            fail('insufficient confirmed deliveries for the run duration')
        if not state['sleep_requests']:
            fail('no node sleep requests observed')
        if config.get('require_true_sleep', True) and not state['true_sleep_wakes']:
            fail('no true deep-sleep wake observed')
        state['status'] = 'failed' if state['failures'] else 'passed'
        state['finished_utc'] = utc()
    except BaseException:
        state['status'] = 'interrupted'
        raise
    finally:
        stop.set()
        for thread in threads:
            thread.join(timeout=2)
        save()
        for log in logs.values():
            log.close()
        http_log.close()
        ble_log.close()
    return 0 if state['status'] == 'passed' else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(json.loads(args.config.read_text()), args.output))
