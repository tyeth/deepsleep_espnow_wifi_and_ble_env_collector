import board,sys,envhub_bt_fault
assert board.board_id=="raspberrypi_rpi_pico_w_zephyr" and '6839890534' in sys.version
s=envhub_bt_fault.snapshot()
print("INITIAL",s)
assert s[0]==0 and not s[8],"Bluetooth already initialized before injection"

import errno,time,wifi
expected=getattr(errno,'EIO')
envhub_bt_fault.arm(3)
error=None
try:
 import _bleio
except OSError as exc:
 error=exc.args[0]
print("ERROR",3,error)
print("EXPECTED_ERRNO",expected)
assert error==expected
s=envhub_bt_fault.snapshot()
print("STATE",s)
assert s[0]==1 and s[1]==1 and s[2]==0 and s[3]==3 and s[4]==0 and s[6]==1 and s[7]==0 and not s[8]
nets=wifi.radio.start_scanning_networks()
try:
 count=sum(1 for entry in nets)
finally:
 wifi.radio.stop_scanning_networks()
print("WIFI_AFTER_ERROR",count)
assert count>0

import errno,time,wifi
expected=getattr(errno,'ETIMEDOUT')
envhub_bt_fault.arm(4)
error=None
try:
 import _bleio
except OSError as exc:
 error=exc.args[0]
print("ERROR",4,error)
print("EXPECTED_ERRNO",expected)
assert error==expected
s=envhub_bt_fault.snapshot()
print("STATE",s)
assert s[0]==2 and s[1]==2 and s[2]==0 and s[3]==4 and s[4]==0 and s[6]==2 and s[7]==0 and not s[8]
nets=wifi.radio.start_scanning_networks()
try:
 count=sum(1 for entry in nets)
finally:
 wifi.radio.stop_scanning_networks()
print("WIFI_AFTER_ERROR",count)
assert count>0

import errno,time,wifi
expected=getattr(errno,'ETIMEDOUT')
envhub_bt_fault.arm(5)
error=None
try:
 import _bleio
except OSError as exc:
 error=exc.args[0]
print("ERROR",5,error)
print("EXPECTED_ERRNO",expected)
assert error==expected
s=envhub_bt_fault.snapshot()
print("STATE",s)
assert s[0]==3 and s[1]==3 and s[2]==0 and s[3]==5 and s[4]==0 and s[6]==3 and s[7]==0 and not s[8]
nets=wifi.radio.start_scanning_networks()
try:
 count=sum(1 for entry in nets)
finally:
 wifi.radio.stop_scanning_networks()
print("WIFI_AFTER_ERROR",count)
assert count>0

import _bleio,wifi
s=envhub_bt_fault.snapshot()
print("RETRY",s)
assert s[0]==4 and s[1]==3 and s[2]==0 and s[6]==4 and s[7]==1 and s[8]
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
print("RETRY_COMPLETE")
