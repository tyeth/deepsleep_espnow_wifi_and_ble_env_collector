# CircuitPython TLS server certificate policy reproduction

This native Zephyr test compiles the **unmodified certificate-policy blocks**
extracted from `shared-module/ssl/SSLSocket.c` at CircuitPython alpha.2 and the
carried fix. It performs real Mbed TLS 1.2 ECDHE/ECDSA handshakes over in-memory
transport callbacks, then transfers and checks encrypted application data on
each successful connection. It does not flash or connect to any device.

The baseline defaults to requesting a client certificate because its server
context inherits the default root bundle. The carried fix allows an ordinary
client when the server only loaded its own certificate and key. Explicit
`load_verify_locations()` retains client-certificate verification.

## Run

Use the configured Zephyr workspace/dependencies from CircuitPython PR #32
(tested CP `7d4ef1aac72bf322f1bcead966a8d3eac0acb2af`, Zephyr
`7379648278ab49e391af00f1a62ec73387d4c519`) with its Python environment activated.
The checked-in `src/policy.h`, `src/credentials.h` and source manifest make the
recorded test self-contained. The credentials are **public test fixtures**;
they must never be used for a deployed service.

From the configured Zephyr workspace:

```sh
export ZEPHYR_TOOLCHAIN_VARIANT=host
west twister -T /absolute/path/to/tools/repro_tls_server_policy \
  -p native_sim/native/64 --outdir /tmp/tls-server-policy-repro -j 2
```

Use a fresh output directory. To regenerate the source extracts and disposable
credentials first (requires Git, Python and OpenSSL):

```sh
python3 /absolute/path/to/tools/repro_tls_server_policy/prepare.py \
  --circuitpython /absolute/path/to/circuitpython \
  --baseline 11.0.0-alpha.2 \
  --fixed 7d4ef1aac72bf322f1bcead966a8d3eac0acb2af
```

Regeneration records exact commit, source blob and extracted policy SHA-256.
It changes the disposable certificates, so fixture hashes will differ.

## Expected results

Eight cases, fourteen handshakes, all assertions pass:

- Baseline default server: no client certificate fails with
  `MBEDTLS_ERR_SSL_NO_CLIENT_CERTIFICATE` (`-29824`, `-0x7480`). This case
  deliberately asserts the old failure; a green suite does not mean the
  baseline is fixed.
- Fixed default server: no client certificate succeeds, including encrypted
  application data transfer.
- Both policies, explicit CA: no client certificate fails, a trusted client
  succeeds and an untrusted client fails verification.
- Both policies, no server CA: an ordinary client succeeds.
- Both policies, client verification: an untrusted server and wrong hostname
  fail with `MBEDTLS_ERR_X509_CERT_VERIFY_FAILED` (`-9984`).

This tests the actual shared-module policy and real cryptography, not the
whole CircuitPython interpreter or a physical socket/board. The default bundle
attachment uses the fixture CA through Mbed TLS's normal CA-chain API; it does
not reproduce CircuitPython's compressed root-bundle storage implementation.
The p256-m provider remains disabled, matching the existing integration
workaround; its independent sizing defect is covered by `repro_p256_premaster`.
