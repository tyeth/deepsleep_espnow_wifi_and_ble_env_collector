# Pico W production qualification and station-stop finding

Pico W now runs production CircuitPython `6b117bdce5`, with no diagnostic
configuration overrides. The update used a fresh private 2 MiB backup,
preserved every byte outside the code update (including the final sector's
tail, settings, NVM and filesystem), and verified the entire resulting flash.
Runtime revision and retained BLE identity both passed.

On channels 1, 6 and 11, a real Feather ESP32 V2 station saw the requested
channel, acquired a DHCP lease, pinged the AP, appeared in the AP table with
matching MAC/IP, then departed. The AP stopped and restarted between cases.
Ping times were 17, 19 and 19 ms. With the AP and station active, ordinary BLE
scans received 95, 98 and 97 advertisements; rejecting `extended=True` did not
replace the original scan. Both radios' cleanup passed. The bridge's port
state was unchanged; the direct Pico USB interface remains authorized after
the update, with unused MSC/HID host drivers unbound.

See [sanitized evidence and hashes](picow-production-ap-qualification-2026-10-23.json).
Earlier soaks and TLS checks keep their original revisions; this result is not
a new long soak, sustained-throughput test or full USB stress qualification.

## Separate station-lifecycle gap

Before the update, `wifi.radio.stop_station()` returned but the connected flag
remained true. Both no-op station lifecycle functions also remain in current
upstream. The recorded physical run was on `7d4ef1aac7`; the production `6b117`
source retains the same bodies. [Fork issue #40](https://github.com/tyeth/circuitpython/issues/40)
contains the minimal reproduction and exact upstream blob identity.

Disabling the interface explicitly made the connected check false. A subsequent
console session reported a connection again; the re-enable path has not been
fully isolated. The final updater quiesced the radio in the same session as
the bootloader handoff. The first two guarded update attempts stopped before
any flash read/write, and their evidence remains preserved. This is a separate
unfinished station API issue, not a regression attributed to the DHCP fix.
