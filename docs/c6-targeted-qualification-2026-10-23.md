# Feather C6 targeted qualification — 23 October 2026

The bare Feather C6 now runs the ESP integration at `ea06dcb44e`. Programming
and an independent image digest check passed. This board has no attached
JD79667 display, RTC, SCD41 or SD card; those physical checks remain open.

| Check | Result and boundary |
|---|---|
| Five heavy-import/AP/BLE/ESP-NOW startup orderings | Passed after a software-requested MCU reset before each normal `code.py` boot. Initial uptime 2.175–2.178 s. All SPI-lock probes passed; final free heap 121,948–122,544 bytes. |
| Broadcast submission with AP, GATT advertising, TCP/UDP and BLE scan resident | 100 explicit-peer submissions per ordering; 500 total. Packet delivery was not measured in this check. |
| Connected GATT | 10,240 unpaced bytes received exactly; mid-burst disconnect returned in 2.252 s; reconnect delivered 1,024 exact bytes without stale data. |
| Post-GATT BLE restart | Disconnect settled after about 51 ms; adapter disable/re-enable and scan passed with 78 advertisements while Wi-Fi/ESP-NOW remained resident. |
| AP/DHCP and HTTP | ESP32 V2 peer acquired a lease and received five exact 1,024-byte HTTP payloads. |
| ESP-NOW with AP and BLE scan/advertising | 93/100 exact round trips, seven sender failures, zero malformed received payloads. C6 received 93 unique packets and successfully echoed all 93; 13 BLE advertisements observed. Final free heap 105,796 bytes. This is an integrity result with measured loss. |
| Absent SD card | Five `sdcardio.SDCard(board.SPI(), board.D10)` attempts returned `no SD card`; the SPI lock was available after each. No shared physical display wiring was present. |

## Reproduced default-peer send discrepancy

With only the broadcast peer registered, `en.send(payload, None)` fails with
`ESP_ERR_ESPNOW_NOT_FOUND` (`0x3069`), while passing that same peer explicitly
succeeds. Repeating the default call fails again. With only a unicast peer,
or with both peer types registered, default and explicit calls are accepted.
These are send-submission controls, not proof that every peer received data.

CircuitPython's binding documents `None` as all registered peers and passes
NULL to IDF unchanged. The [IDF send documentation](https://docs.espressif.com/projects/esp-idf/en/v5.2/esp32/api-reference/network/esp_now.html)
also describes all registered peers. A subsequent [standalone C-only IDF
probe](c6-espnow-idf-contract-2026-10-23.md) reproduces the same behavior in
three complete rounds. MicroPython already documents the broadcast exclusion;
the ESP integration now corrects CircuitPython's documentation. This is not
evidence of a new CircuitPython radio regression. Continue using an explicit
broadcast peer; an IDF documentation clarification remains upstreamable.

## Power and transport qualification

The five startup-order passes used `microcontroller.reset()` and checked low
uptime; they are not electrical cold-start tests. Original `code.py` was restored
exactly and temporary results removed afterward.

An earlier hub path reported off and lost USB enumeration while C6 uptime
continued, including a 30-second off interval. The user subsequently supplied
a corrected path and confirmed physical power-off. At that corrected path,
the new check held the port off for 30.023 seconds,
but its power-on polling failed because the hub path temporarily disappeared.
The bridge itself stayed running; the hubs and other devices returned with
ports on. A separate guarded observer re-isolated the other leaf ports and
read the C6 without issuing a reset: uptime 653.249 →
199.090 seconds, so **MCU uptime reset** during the interval.
The original power job remains failed; this is not a clean power-cycle pass.
Neither result establishes the cause of the earlier path/power discrepancy.
A subsequent settings read showed `restore_port_power=false`,
`enforce_per_port_switching=false` and `enum_timeout_ms=0`. Other ports
returning on after hub re-enumeration may therefore follow the configured
policy; it is not established as a restoration bug. Parent-hub disappearance
is tracked separately in [bridge issue 26](https://github.com/tyeth-ai-assisted/esp-usbip-bridge/issues/26).

With the larger USB inventory present, both REPL and a no-reset ROM probe
received no serial data. After other leaf ports were individually switched
off, the same connected-BLE test passed without a firmware change. Treat this
as a transport/resource investigation, not a CircuitPython radio regression.
No endpoint-capacity root cause is claimed. Failed jobs and private evidence
remain preserved; all completed test imports were detached.

A subsequent [physical controller-candidate check](controller-c6-physical-2026-10-23.md)
passed while explicitly tolerating the missing parent and on-but-disabled
state. Independent C6 uptime was 7.21 seconds afterward. The controller
service remains unchanged.

## Remaining limits

No low-MTU-23 qualification: the device reported `max_packet_length=253`;
Bleak's 23 value was a documented fallback warning. Display/SD shared wiring,
RTC retention, actual sensor operation, deliberate heap exhaustion and longer
mixed traffic remain unverified. The first traffic test failed at missing echo
6; the follow-up records losses instead of hiding them or claiming 100/100.

[Machine-readable results](c6-targeted-qualification-2026-10-23.json) and
[minimal bare-board edge probes](../tools/repro_c6_edges.py).
