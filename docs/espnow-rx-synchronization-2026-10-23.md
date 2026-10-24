# ESP-NOW receive synchronization candidate

Commit `ea06dcb44e` fixes the demonstrated packet-publication race in the
ESP integration [draft PR #31](https://github.com/tyeth/circuitpython/pull/31).
The Wi-Fi callback previously made a header visible before its MAC address
and payload. A reader could consume the header and then fail, leaving the
remaining bytes misaligned for subsequent reads. This supplies a concrete
source-level explanation for the symptom in [upstream #9816](https://github.com/adafruit/circuitpython/issues/9816),
without proving that every reported hardware occurrence has that cause.

A shared ESP-IDF critical section now covers the complete enqueue/dequeue
and the ring buffer's non-atomic counters. `len`, boolean readiness and stream
polling use the same protected availability accessor. Python allocation and
exceptions occur after unlocking. Reads use a fixed maximum-size stack buffer
rather than a length taken from an unchecked packet header. Oversized or
negative callback lengths are dropped without publishing partial data.

The native harness compiles actual source functions and maps critical sections
to pthread mutexes. It deliberately schedules another thread after header
publication: `cb5301b6fb` raises invalid-buffer twice; the candidate reader
waits and receives the complete packet. Reverse-direction dequeue and
readiness interleavings also pass. This extends the earlier single-thread
injection to exercise both ends of the synchronization.

Ten check groups pass, including empty/error unlock paths, lengths 0/1/250,
exact capacity, buffer-full drops, 400 variable-length wraparound iterations,
malformed/truncated packets and a 20,000-packet concurrent producer/consumer
run. That deliberately saturated run delivered 3,384 intact, ordered packets
and counted 16,616 full-buffer drops: totals reconcile exactly. It is not a
no-loss throughput claim. All Python object/exception stubs assert the lock
has been released.

Run from the CircuitPython candidate checkout:

```sh
python tools/check_espnow_rx_lock.py . --output /tmp/candidate.json
python tools/check_espnow_rx_lock.py . --revision cb5301b6fb9ede7442d84e8aba72baad87430a80 --expect-race --output /tmp/baseline.json
```

Fresh Feather ESP32 V2 and Feather ESP32-C6 builds pass with ESP-IDF
`29d36039e5`. Generated versions are `11.0.0-alpha.2-16-gea06dcb44e-dirty`;
the existing checkout's submodule deviations were retained and are recorded
in the [artifact manifest](firmware-espnow-rx-ea06-2026-10-23.json). The frozen
MPU6050 dependency's actual revision is recorded separately. This is not a
claim of a clean dependency checkout.

The Feather ESP32 V2 image is now installed and the physical baseline/candidate comparison passes: the old image reproduces invalid-buffer on channels 1/6/11, while the candidate passes the identical payload/accounting test. See [the physical report](espnow-physical-comparison-2026-10-23.md). C6 is not installed; real radio coexistence, latency and other variants remain unverified. Callback teardown lifetime is unchanged; this fix
does not add a general corrupt-buffer recovery API or implement the separate
channel/broadcast feature requests. Existing failed hardware evidence and
older soak attribution remain unchanged.

See [native results and source hashes](espnow-rx-synchronization-2026-10-23.json).
