# ESP-NOW receive corruption and application guards

The baseline `cb5301b6fb` source reproduces a packet-publication race under a deterministic
interleave. After `recv_cb` writes the seven-byte header, the reader can consume
it before the callback writes the MAC and payload. The actual read function
raises `ValueError: Invalid buffer`. The producer resumes and appends the
remaining bytes; the next read also fails because those bytes are no longer
aligned to a packet header.

This is a native scheduling reproduction, not a measurement of how frequently
it happens on hardware. This initial reproduction did not include a driver fix. A subsequent candidate now passes two-thread native checks and ESP32/C6 builds; [see its evidence and hardware limits](espnow-rx-synchronization-2026-10-23.md). It extends the investigation
of existing [upstream #9816](https://github.com/adafruit/circuitpython/issues/9816),
which remains open. The exact ESP-NOW and ring-buffer blobs in the tested
`cb5301b6fb` checkout match upstream `main` fetched on 23 October 2026.

The harness compiles the actual `recv_cb`, `common_hal_espnow_read`, ring-buffer
implementation and packet declarations. A wrapper around the callback's
`ringbuf_put_n` yields to the reader immediately after the first write. Python
object creation and exception propagation are minimal host stubs. The harness
does not replace the packet or buffer algorithms.

Controls verify complete sequential delivery, exact-capacity acceptance,
whole-packet drop one byte below capacity, and recovery with a fresh buffer.
`sizeof(espnow_packet_t)` already includes the six-byte MAC; this evidence does
**not** support adding another six bytes to the size check. It also does not
exercise the separate non-atomic `used` counter race discussed upstream.

Use a checkout at `cb5301b6fb` for this original baseline-only harness. The newer candidate report has revision-selectable commands.

```sh
python3 tools/check_espnow_rx_interleaving.py /path/to/circuitpython \
  --output /tmp/espnow-interleaving.json
python3 tools/test_espnow_recovery.py
```

Eight fault-injected checks execute the actual application functions:

- Corrupt receive buffer with an AP active requests a reset without rebuilding
  or deinitializing the driver under the AP.
- Without an AP, corruption rebuilds the driver and clears stale peer state.
- A failed rebuild disables reception and requests a reset.
- A missing driver is not initialized while an AP is already active.
- Rotation through 32 peers holds the driver/cache to 16 and reuses an existing MAC.
- The node treats invalid receive data as unconfirmed delivery.
- Discovery passes the broadcast peer explicitly to `send`.
- Channel switching drops a connected station before moving the AP channel.

The [channel-selection #7903](https://github.com/adafruit/circuitpython/issues/7903)
and [broadcast #9380](https://github.com/adafruit/circuitpython/issues/9380)
trackers also remain open. Passing wrapper checks validates the project's
workarounds, not resolution of those firmware/API reports. Physical channel
and broadcast traffic on the latest ESP image, deliberate receive interleaving
on hardware remain further work. Source synchronization is now implemented in the candidate linked above.

See the [source hashes and results](espnow-targeted-investigation-2026-10-23.json).
