# Reproduce the p256-m TLS 1.2 premaster size defect

This is an **intentional failure reproduction**, not an ordinary passing CI
suite. It targets [tyeth/zephyr#10](https://github.com/tyeth/zephyr/issues/10).
It uses Zephyr's native simulator, the actual Mbed TLS public header and real
PSA key generation/export/ECDH. It does not emulate a successful TLS handshake
or touch a physical device.

From a configured Zephyr workspace with Mbed TLS and TF-PSA-Crypto modules:

```sh
export ZEPHYR_TOOLCHAIN_VARIANT=host
west twister -T /absolute/path/to/tools/repro_p256_premaster \
  -p native_sim/native/64 --outdir /tmp/p256-premaster-repro -j 2
```

Use a fresh output directory to preserve prior evidence. The test configuration
enables a real TLS 1.2 ECDHE/ECDSA cipher suite and P-256. `MBEDTLS_PK_WRITE_C`
supplies the ASN.1 writer required by this provider configuration. No manual
override of ECP size or private crypto build symbols is used.

Expected on the affected implementation:

| Provider | Explicit 32-byte ECDH control | TLS `MBEDTLS_PREMASTER_SIZE` output |
|---|---|---|
| p256-m enabled | success, 32 bytes | capacity 1, status -138 (`PSA_ERROR_BUFFER_TOO_SMALL`), test fails |
| p256-m disabled | success, 32 bytes | capacity 32, success, test passes |

The suite should therefore report one failed scenario and three of four passing
cases. Treat compilation errors as an invalid reproduction, not confirmation.
A future upstream fix should make all four cases pass with p256-m still enabled.

Recorded 22 October 2026 with Zephyr `7379648278ab49e391af00f1a62ec73387d4c519`,
Mbed TLS `098e120afb51877ed814bdc04443890ae12e0642` and TF-PSA-Crypto
`fa92349590a54959ee2efc21b668e5afdb144726`. The relevant headers are byte-identical
to the current upstream copies checked during this run. See
[the evidence summary](../../docs/p256-premaster-reproduction-2026-10-22.json).
