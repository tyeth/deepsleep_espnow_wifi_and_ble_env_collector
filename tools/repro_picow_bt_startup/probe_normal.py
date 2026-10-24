import board, sys, wifi, _bleio
assert board.board_id in ('raspberrypi_rpi_pico_w_zephyr', 'raspberrypi_rpi_pico2_w_zephyr')
assert '0d545efdcf' in sys.version
assert _bleio.adapter.enabled
assert not wifi.radio.connected and not wifi.radio.ap_active and not _bleio.adapter.connected
identity = bytes(_bleio.adapter.address.address_bytes)
print('BLE_ID', identity.hex())
print('NORMAL_START', sys.version)
for i in range(3):
    if _bleio.adapter.advertising:
        _bleio.adapter.stop_advertising()
    _bleio.adapter.enabled = False
    assert not _bleio.adapter.enabled
    _bleio.adapter.enabled = True
    assert _bleio.adapter.enabled
    assert bytes(_bleio.adapter.address.address_bytes) == identity
    networks = wifi.radio.start_scanning_networks()
    try:
        wifi_count = sum(1 for entry in networks)
    finally:
        wifi.radio.stop_scanning_networks()
    scan = _bleio.adapter.start_scan(timeout=2, buffer_size=2048)
    try:
        ble_count = sum(1 for entry in scan)
    finally:
        _bleio.adapter.stop_scan()
    assert wifi_count > 0 and ble_count > 0
    print('NORMAL_RADIO', i, wifi_count, ble_count)
wifi.radio.stop_station()
print('NORMAL_BLE_COMPLETE')
