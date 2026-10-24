# ESP-NOW receive race: physical baseline and candidate comparison

The current-board baseline `cb5301b6fb` reproduced repeated invalid-buffer
errors on every tested channel. With the synchronized `ea06dcb44e` receiver,
the identical test passes payload integrity, order, accepted/read accounting,
empty-buffer completion and cleanup. The sender remains `cb5301b6fb`.
This is a custom comparison of integration commits, not the HIL standard
published-release-versus-hosted-PR-artifact matrix.

A real Feather ESP32-S3 sent 1,000 packets per phase to a real Feather ESP32 V2.
Payload lengths alternate between 12, 64 and 250 bytes; each packet carries
a sequence number and deterministic content. The receiver uses the default
526-byte ring and repeatedly calls `read()` without sleeping. Channel 6 uses
an explicit broadcast peer; channels 1/11 use unicast. The receiver stops
after ten invalid-buffer errors or its 25-second observation deadline.

| Channel / mode | Baseline intact reads | Baseline invalid-buffer errors | Candidate intact reads | Candidate invalid-buffer errors | Candidate buffer-full drops |
|---|---:|---:|---:|---:|---:|
| 1 / unicast | 2 | 10 | 1000 | 0 | 0 |
| 6 / broadcast | 2 | 10 | 957 | 0 | 0 |
| 11 / unicast | 0 | 10 | 1000 | 0 | 0 |

The candidate received all 2,000 unicast packets. Its broadcast phase received
957 of 1,000 submissions, with zero ring-buffer drops or corruption; the
location/cause of those 43 missing deliveries was not isolated. This is not
a lossless-broadcast claim.

Baseline failures occurred within the first few received packets, before any
buffer-full drop was reported at the failure snapshot. The sender completed
all 3,000 submissions. After the receiver exits early, it no longer drains
later traffic, so its baseline snapshot is not a final 1,000-packet accounting
record. Both runs passed radio cleanup and restored the original bridge ports
and USB/IP imports. The original failing run remains failed and preserved.

The guarded update took a fresh 8 MiB backup and verified it against the DUT.
It replaced only the active application, preserving the bootloader, partition
table, OTA metadata, settings and filesystem, including the last erased
sector's tail. The entire expected flash passed esptool verification before
resume; the running board reported `ea06dcb44e`. Eleven host fault-injection
checks cover rollback, changed inputs and OTA/partition guards.

## Minimal two-board reproduction

Use disposable test boards with no active AP/STA workload. On both ESP boards:

```python
import espnow, wifi, time, struct
wifi.radio.start_station()
en = espnow.ESPNow(buffer_size=526)
wifi.radio.start_ap("EHQ-RX", password="bench-ephemeral", channel=6)
```

Use `EHQ-TX` as the sender's AP name. Start the receiver loop first:

```python
end = time.monotonic() + 25
try:
    while time.monotonic() < end:
        packet = en.read()  # baseline can raise ValueError: Invalid buffer
finally:
    wifi.radio.stop_ap()
    deadline = time.monotonic() + 10
    while wifi.radio.ap_active and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not wifi.radio.ap_active
    en.deinit()
```

While it runs, transmit on the sender:

```python
peer = espnow.Peer(b"\xff" * 6, channel=0)
en.peers.append(peer)
for seq in range(1000):
    size = (12, 64, 250)[seq % 3]
    payload = b"EHRX" + struct.pack("<I", seq)
    payload += bytes((seq + k) % 251 for k in range(size - 8))
    en.send(payload, peer)
wifi.radio.stop_ap()
deadline = time.monotonic() + 10
while wifi.radio.ap_active and time.monotonic() < deadline:
    time.sleep(0.01)
assert not wifi.radio.ap_active
en.deinit()
```

The farm test additionally checks every payload, sequence and source address,
records counters, caps repeated errors, and verifies cleanup. The [native
reproduction](espnow-rx-synchronization-2026-10-23.md) forces the precise
interleaving and tests error paths; the radio run supplies physical evidence.

This validates one ESP32 receiver/S3 sender pairing. C6 and other variants,
connected BLE/GATT, display/sensor load, multiple senders and teardown fault
injection remain unverified at this revision. The ESP32-C6 candidate builds
but is not installed. Earlier soak results retain their earlier revisions.
See [exact results and evidence hashes](espnow-physical-comparison-2026-10-23.json).

## Short pacing and BLE scan controls

A later run on the same candidate retained the packet checks and tested three
additional 1,000-packet phases:

| Mode | Intact packets captured | Sender success/failure callbacks | BLE advertisements retained |
|---|---:|---:|---:|
| Channel 6 broadcast, unpaced repeat | 948 | 1000 / 0 | not scanning |
| Channel 6 broadcast, 2 ms pacing | 952 | 1000 / 0 | not scanning |
| Channel 11 unicast during BLE scan | 996 | 993 / 7 | 13 |

All captured packets matched their sequence and payload, with zero invalid
buffers, order errors or ring-buffer drops. Accepted/read counts reconciled,
and all buffers drained. Cleanup and original transport restoration passed.
The broadcast gap persisted with pacing; this single control does not establish
its cause or justify a pacing workaround. During BLE scanning, receiver delivery
and sender callback outcomes differ, so neither counter is substituted for the
other. This is functional simultaneous BLE/ESP-NOW evidence, not lossless
coexistence or connected-GATT qualification. See the `followup` section in the
JSON evidence for exact counters, elapsed times and hashes.
