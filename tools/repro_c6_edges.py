# Bare C6 only: expects no SD card on SPI/CS D10. Sends test radio frames.
import board,sys,wifi,espnow,gc,time,json,sdcardio
assert board.board_id=="adafruit_feather_esp32c6_4mbflash_nopsram" and "ea06dcb44e" in sys.version
result={"version":sys.version,"sd":[],"send_contract":[]}
spi=board.SPI()
try:
 for cycle in range(5):
  card=None;error=None
  try:card=sdcardio.SDCard(spi,board.D10)
  except Exception as exc:error=repr(exc)
  finally:
   if card is not None:card.deinit()
  available=spi.try_lock()
  if available:spi.unlock()
  result["sd"].append({"cycle":cycle,"error":error,"spi_lock_available":available})
  assert error is not None and available
finally:spi.deinit()
wifi.radio.start_station()
try:
 for mode in ("broadcast_only","unicast_only","mixed"):
  en=espnow.ESPNow()
  try:
   peers=[]
   if mode!="unicast_only":peers.append(espnow.Peer(b"\xff"*6))
   if mode!="broadcast_only":peers.append(espnow.Peer(b"\x02\x00\x00\x00\x00\x01"))
   for peer in peers:en.peers.append(peer)
   row={"mode":mode,"calls":[]}
   for label,peer in [("default_none",None)]+[("explicit_"+str(i),p) for i,p in enumerate(peers)]+[("default_none_again",None)]:
    try:
     value=en.send(b"envhub-send-contract",peer)
     row["calls"].append({"call":label,"accepted":True,"result":value})
    except Exception as exc:row["calls"].append({"call":label,"accepted":False,"error":repr(exc)})
    time.sleep(.1)
   result["send_contract"].append(row)
  finally:en.deinit()
finally:wifi.radio.stop_station()
gc.collect();result["heap_free"]=gc.mem_free()
print("EDGE_RESULT",json.dumps(result))
