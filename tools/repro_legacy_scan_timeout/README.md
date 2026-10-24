# Direct legacy scan-timeout reproduction

This standalone Zephyr application reproduces `tyeth/zephyr#9` without the
CircuitPython deadline workaround. It was physically tested on Pico 2 W with
Zephyr `7379648278ab49e391af00f1a62ec73387d4c519`, HAL Pico
`725e9e429eab65eda01762a1af9016426dee00ac` and HAL Infineon
`7f93dc60675126a63358ffa0780648d94fd2d634` from the existing integration.
Those pins include the shared-bus CYW43 HCI driver; an arbitrary upstream
checkout is not an interchangeable build environment.

From that configured west workspace, with its SDK and dependencies available:

```sh
west build -b rpi_pico2/rp2350a/m33/w -d build-legacy-timeout \
  -S cdc-acm-console /path/to/tools/repro_legacy_scan_timeout
```

Use a dedicated board with a verified full-flash backup and a tested recovery
path. The application does not mount a filesystem or enable persistent
Bluetooth settings. Install only its code region after checking image size
against the board's storage layout. Preserve the original code padding when
restoring a shorter diagnostic image to a larger production image.

Open its USB CDC console, assert DTR and wait for the complete
`LEGACY_READY ... g=run r=rom` line. Send `g` once. Three cases request timeout
values 300, 0 and 300 (10 ms units). Each observes six seconds of traffic,
then explicitly stops and checks for post-stop reports. A nearby advertiser
is required. A reproduced failure has successful starts, reports after 3.5 s,
zero timeout callbacks, and successful explicit stops. Zero advertisements
is an inconclusive fixture result, not evidence that timeout works.

The independent serial command thread accepts `r` to enter RP2350 ROM USB
mode. Test this before enabling Bluetooth. On later reconnects, wait for the
complete ready line before sending it and keep the connection open while the
device transitions. Do not assume that writing one byte proves ROM entry:
independently verify the physical ROM identity before programming anything.
Restore the original image, verify the full flash and perform runtime checks.

The recorded main job reproduced the bug but failed its final ROM transition;
a separate handshake-based recovery restored production exactly. See
[the evidence report](../../docs/legacy-ble-scan-timeout-2026-10-23.md).
No general Zephyr timeout fix is included here.
