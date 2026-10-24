import board,sys,envhub_bt_fault
assert board.board_id=="raspberrypi_rpi_pico_w_zephyr" and '6839890534' in sys.version
s=envhub_bt_fault.snapshot()
print("INITIAL",s)
assert s[0]==0 and not s[8],"Bluetooth already initialized before injection"

import _bleio,wifi
s=envhub_bt_fault.snapshot()
print("CLEAN_START",s)
assert s[0]==1 and s[1]==0 and s[2]==0 and s[6]==1 and s[7]==1 and s[8]
assert _bleio.adapter.enabled
print("BLE_ID",bytes(_bleio.adapter.address.address_bytes).hex())
for i in range(3):
 scan=_bleio.adapter.start_scan(timeout=2,buffer_size=2048)
 try:
  count=sum(1 for entry in scan)
 finally:
  _bleio.adapter.stop_scan()
 print("BLE_SCAN",i,count)
 assert count>0
print("CLEAN_START_COMPLETE")
