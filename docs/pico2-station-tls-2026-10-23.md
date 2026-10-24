# Pico 2 station lifecycle and TLS verification

Pico 2 W now runs CircuitPython `9e153ad624`, the station lifecycle fix in
[PR 32](https://github.com/tyeth/circuitpython/pull/32), tracked by
[issue 40](https://github.com/tyeth/circuitpython/issues/40). A fresh private
4 MiB backup, full-flash readback and runtime verification passed. The
update preserved bytes after the candidate image; the private backup remains.

Three channel-6 connect/DHCP/ping/stop/reconnect cycles passed with an ESP32
Feather V2 peer at `ea06dcb44e-dirty`. Ping times were 9, 9 and 12 ms;
station stops took approximately 5, 5 and 4 ms. Each stop cleared the IP
address, retained the enabled radio, and was independently observed as a
departure by the peer AP. Repeated stop and starting from a disabled radio
passed. With roles reversed, the Pico AP on channel 11 retained its client
through station stop/start; the client then pinged it in 52 ms. Both devices
cleaned up and the transport topology was restored.

## Bounded TLS and BLE test

On the same installed image, two HTTPS responses of **20,495 bytes** matched
the expected SHA-256. During the first transfer the BLE scanner received
**316 advertisements**. The wrong hostname and an unrelated explicit CA each
rejected with `OSError(-9984)` (`MBEDTLS_ERR_X509_CERT_VERIFY_FAILED`). The
default trust bundle rejected the private self-signed issuer with
`OSError(-12288)` (`MBEDTLS_ERR_X509_FATAL_ERROR`), matching the pinned
`crt_verify_callback` unknown-issuer path. A final trusted transfer succeeded
after all three negative controls. The host fixture self-check, device radio
cleanup, fixture shutdown and import restoration passed. Heap snapshots were
86,432 and 84,032 bytes; two snapshots are not a memory-leak qualification.

Certificate `notBefore`/`notAfter` checks are deliberately disabled by this
build's shared mbedTLS configuration. This test does **not** establish expiry
or future-date protection. No firmware setting was changed to obtain a pass.
The generated Pico 2 device tree has no RTC alias, so the build tool's RTC
gate disables the `rtc` module despite `CONFIG_RTC=y`.

Three earlier failed attempts are retained: an unavailable `rtc` import,
the CPython-only `hashlib.sha256` constructor, and an incorrect expectation
that the default bundle would return the same error as explicit CA checking.
All three cleaned up successfully. These are test-harness failures; none is
presented as a passing TLS run or a demonstrated firmware defect.

## Minimal reproduction

For station lifecycle, use an independent disposable AP on channel 6. Start
the station, connect, verify a DHCP address and ping, then stop it. Check
`connected == False`, `ap_info is None`, the cleared address and the AP's
independently observed departure. Repeat stop and reconnect to the same
SSID. Repeat with the radio initially disabled. Then connect a client to a
Pico AP on channel 11 and verify that station stop/start preserves the AP,
client association and successful client ping.

For TLS, serve a known binary response over HTTPS using a fresh private
self-signed certificate with a DNS subjectAltName. On CircuitPython use
`ssl.create_default_context()` and `load_verify_locations(cadata=...)` to
trust it, connect using the matching `server_hostname`, and stream/hash the
body with `hashlib.new("sha256")`. Run a bounded BLE scan concurrently.
Separately try the wrong hostname with that trusted context, the correct
hostname with a default context, and the correct hostname with a context
trusting an unrelated certificate. Require the specific errors above, then
repeat the trusted transfer. Close each socket and stop scans/station/server
in cleanup. Credentials, keys and infrastructure addresses are excluded here.

## Limits and provenance

This is a short, private-certificate client TLS test, not a TLS soak, public
CA interoperability suite, connected-GATT load or server/client-auth test.
It does not cover driver-failure injection, MSC concurrency, storage-boundary
writes or a fresh BLE identity comparison. Earlier soaks retain their actual
firmware revisions. The [sanitized results](pico2-station-tls-2026-10-23.json)
include raw-evidence hashes; [build provenance](firmware-pico-station-9e153-2026-10-23.json)
pins the image and dependencies.

Pinned source context: [TLS date policy](https://github.com/tyeth-ai-assisted/circuitpython/blob/9e153ad624bcd1559211dfad8eb54ef8841f15e9/lib/mbedtls_config/mbedtls_config.h#L70), [bundle rejection path](https://github.com/tyeth-ai-assisted/circuitpython/blob/9e153ad624bcd1559211dfad8eb54ef8841f15e9/lib/mbedtls_config/crt_bundle.c#L138), and [RTC module gate](https://github.com/tyeth-ai-assisted/circuitpython/blob/9e153ad624bcd1559211dfad8eb54ef8841f15e9/ports/zephyr-cp/cptools/zephyr2cp.py#L2144).
