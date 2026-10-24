import time,supervisor,json
deadline=time.monotonic()+10
while not supervisor.runtime.serial_connected and time.monotonic()<deadline:
 time.sleep(.05)
time.sleep(1)
print("SCAN_ORDER_BEGIN")
supervisor.runtime.ble_workflow=False
import _bleio
a=_bleio.adapter
a.enabled=True
a.stop_advertising();a.stop_scan()
print("SCAN_ORDER_ADDRESS_TYPE",a.address.type)
def probe(label,window):
 row={"label":label,"advertising":a.advertising,"window":window}
 start=time.monotonic()
 try:
  scan=a.start_scan(timeout=1.0,buffer_size=512,interval=.1,window=window,active=False)
  row["count"]=sum(1 for entry in scan)
  row["result"]="pass"
 except Exception as exc:
  row["result"]="error";row["error"]=type(exc).__name__+": "+str(exc)
 finally:a.stop_scan()
 row["elapsed_s"]=time.monotonic()-start
 print("SCAN_ORDER_CASE",json.dumps(row))
a.start_advertising(b"\x02\x01\x06\x05\x09TEST",connectable=True)
probe("connectable_first",.1)
probe("connectable_first_half_window",.05)
a.stop_advertising()
probe("no_advertising_prime",.1)
a.start_advertising(b"\x02\x01\x06\x05\x09TEST",connectable=True)
probe("connectable_after_prime",.1)
a.stop_advertising();a.stop_scan()
print("SCAN_ORDER_DONE")
while True:time.sleep(.1)
