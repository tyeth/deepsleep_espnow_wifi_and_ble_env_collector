# Temporary S31 segment timing reproduction

This is diagnostic instrumentation, not a firmware fix. Apply `bridge-timing.patch`
to `tyeth/esp-usbip-bridge` base `bec1d71e1379e08e279327bdb222b3207456cebe`.
It pins mDNS 1.14.0 to match the baseline, and records timestamps for 65,536-byte
IN requests on endpoint 3 only. It assumes 4 KiB segmentation; it does not
identify all MSC endpoints generically. The measured build used ESP-IDF
`ce2100de51a4d9a372f26578fd2ee763ca4b1279` and USB component
`a391e1fd7fa6b3a527897a4bfec9d9f51141e014` with the existing S31 board configuration.

Run host checks before building:

```sh
python3 -m unittest discover -s tools/repro_s31_segment_timing -p 'test_*.py'
python3 tools/repro_s31_segment_timing/check_native.py /path/to/patched/bridge
```

The native checker extracts the patched functions and tests sixteen segments,
short transfer, error, cancellation, untimed transfer and orphan callback with
AddressSanitizer/UBSan. It requires a C compiler; it does not emulate the USB host.

Use an isolated bench with no active soak or imports, enough USB host capacity,
a verified current bridge backup and a tested restore path. Keep the device
filesystem unmounted. Temporarily install the diagnostic using the board's normal
build/flash tooling; the patch does not automate flashing or erase runtime data.
Capture UART plus USB/IP network traffic and host USBmon. On the tested Pico 2 W,
the console stays open and the prefix is read with `dd if=DEVICE of=OUTPUT
bs=4096 count=64 iflag=direct`, then `bs=65536 count=4`, then the first command
again, using separate output files and a bounded timeout. Replace DEVICE only
after identifying the intended disk. These commands only read the device.
Compare exact lengths and SHA-256 values and check console responsiveness after
each read. Preserve failed outputs and capture cleanup status.

```sh
python3 tools/repro_s31_segment_timing/decode_s31_msc_timing.py uart.log
```

The parser rejects missing, duplicate, short or failed segment groups. It does
not prove capture completeness: match every 64 KiB network sequence and its
successful received reply to a complete group. `s` precedes the host-submit
call; `c` is client callback dispatch, not physical completion. `reply_us` is
after a send attempt, not reception proof. Retry counts must be inspected;
`s` holds the last attempt. Logging after reply can perturb subsequent requests.
Normal completion frees the diagnostic buffer; existing stuck/disconnected
request lifetime guards can retain context until completion.

Restore the original bridge application, verify the full expected image,
resume and check its API, detach imports, and restore the original topology.
Do not publish raw recovery images or private packet/UART contents.

The measured outcome and all segment timings are in
[the report](../../docs/pico2-s31-segment-timing-2026-10-24.md).
