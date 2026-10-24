# USB/IP reply timing from a private pcap

Run `python3 -m unittest discover -s tools/repro_usbip_timing -v` for nine
reassembly, malformed-stream and arrival-order controls. Decode with
`python3 tools/repro_usbip_timing/decode_usbip_pcap.py /path/to/capture.pcap`.
The parser writes a metadata-only `.decoded.json` beside the input.

Capture the complete successful import handshake and both TCP directions on
port 3240. The decoder supports non-ISO USB/IP, IPv4 TCP and Ethernet or Linux
cooked pcap links. Gaps, conflicting overlaps, malformed payloads and unmatched
responses fail decoding. Pending requests at EOF are retained as pending; a
successful decode is not an all-requests-completed verdict. Inspect final
tcpdump drop statistics separately. Raw captures contain disk/serial data and
remain private; decoded rows omit raw data payloads.

`reply_time` is the earliest observed first reply-header byte. `reply_final_byte_time`
is the earliest observed final byte. `reply_complete_time` is the latest of
the earliest observed arrivals of every byte in the complete reply, including
the 48-byte header. Out-of-order arrival and identical retransmissions therefore
do not incorrectly shorten or lengthen completion time. For direct calls to
`decode_stream` with a plain timestamp callback lacking interval completion,
the completion field is unavailable (`None`). Full-PCAP decoding supplies it.

These are capture-interface arrival times, not receiver-application consumption
or bridge/device processing times. TCP sequence-number wraparound, ISO, IPv6,
pcapng and fragmented IP are unsupported. The decoder does not verify TCP
checksums. No capture command or device-control operation is performed by it.
