# S31 channel exhaustion: direct evidence and capacity control

The bridge now logs **No more HCD channels available** during both failing
mixed CDC/MSC cases. Turning off the unused C6 makes the same workload pass
in both import orders, with no channel-exhaustion messages. The C6 is restored
after the comparison. The headroom job remains failed because its cleanup did
not restore the original topology; a separate recovery subsequently passes.
This identifies a real capacity boundary for this workload;
it does not implement general capacity scheduling.

| Physical population (three hubs in both cases) | Single Pico before/after | Two CDC consoles plus Pico MSC, both import orders | Exhaustion messages |
|---|---|---|---|
| Pico 2, Metro S3, unused C6 | Pass / pass | MSC fails; Pico console EIO; Metro survives | Four per mixed case, eight total |
| Pico 2, Metro S3; C6 verified off/absent | Pass / pass | Storage reads and both consoles pass | Zero |

Each successful storage round makes two matching uncached 4 KiB reads. Both
initial consoles answer before storage admission. HID and Metro MSC remain
unauthorized. Firmware is unchanged between the two instrumented comparisons:
bridge `bec1d71e1379e08e279327bdb222b3207456cebe`, Pico CP `6839890534`
with Zephyr `c6200e80ea`, and Metro `ea06dcb44e`. The exact Pico image and
sanitized phase counts/log hashes are recorded in the adjacent JSON. Captured
descriptors and initial interface admission match between both runs.

The source path is specific: `hcd_dwc.c` emits this message when
`usb_dwc_hal_chan_alloc` finds no free channel and returns
`ESP_ERR_NOT_SUPPORTED`. The bridge maps interface-claim failures to `-EIO`.
Other paths also return `ESP_ERR_NOT_SUPPORTED`, so that error alone is not
the discriminator. The explicit allocation log is.

Descriptor-based accounting predicts 17 channels for three hubs (control plus
interrupt), three leaf control endpoints, two CDC functions and Pico MSC;
removing the unused C6 predicts 16. That accounting is an inference consistent
with the controlled result, not a captured live counter. No claim is made that
all composite traffic fits or that the original historical failures share every
detail of this reproduction.

## Minimal reproduction

Use the revisions above with three hubs and three leaf devices. Prevent automatic
MSC/HID admission, import Pico and Metro in either order, admit CDC and verify
both consoles, then admit only Pico MSC. Capture bridge UART without explicit
DTR/RTS changes, recording uptime before opening and after closing it. Expect
the allocation message and failed MSC enumeration. Detach, repeat with the unused
third leaf physically off and verified absent while keeping all three hubs, then
repeat the single-Pico control. Restore all ports and interface defaults.

Plain UART opening was first qualified separately with advancing uptime and
unchanged inventory. Neither instrumented comparison resets the bridge. The
earlier failed modem-control capture is retained; its exact reset cause remains
unproved.

## Restoration and remaining work

Both runs take a fresh 4 MiB backup, temporarily install the USB-fixed Pico build,
verify the whole expected image, and restore original `9e153ad624` code with
whole expected-image verification. The first run also passes three radio checks.
After the headroom test, powering C6 back on is followed by other leaf devices
reappearing. The topology assertion fails; the firmware restore still passes
full-image verification, but its runtime console check times out. The job remains
failed. A separate recovery switches the other leaf ports off, verifies the
already-restored Pico runtime and three Wi-Fi/BLE checks, then restores Pico off.
It makes no firmware writes and does not reboot the bridge. Runtime data is
preserved outside the changed code sectors; this is not a claim of a bit-identical
pretest snapshot after a different build has run. Imports, interface defaults,
Pico/Metro off states and the C6 on/present state are restored. Private flash
backups and failed logs remain private and preserved.

[Bridge #20](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/20)
remains open for simultaneous capacity and admission behavior. Per-interface
claiming in draft #25 already improves the two-console case. This new result
supports capacity-aware admission and clear diagnostics; it does not justify
releasing an interface that still has transfers in flight. No firmware or
controller source changes are introduced by this evidence update.
