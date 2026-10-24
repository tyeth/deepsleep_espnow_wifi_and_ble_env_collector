import unittest,struct
from decode_picow_usb_diag import decode,summarize
class DecodeTests(unittest.TestCase):
 def fixture(self):
  w=[0]*84;w[:4]=[0x454e5601,1000,56,2];w[4:20]=[1,1000,0x20000100,0x20000200,0,0,2,4,0,7,0,0,0,0,0,85]
  for i in range(8):w[20+i*5]=i//2|(0x80 if i%2 else 0)
  w[68:76]=[0x20000100,0x20000400,0x20001000,0x10001001,0xfffffff8,2,0x20000800,4096]
  w[76:84]=[0x20000500,0,0x20003000,0x10002001,0,0,0x20002000,4096]
  return w
 def pack(self,w):return struct.pack('<'+'I'*len(w),*w)
 def test_priority_and_endpoint(self):
  v=decode(self.pack(self.fixture()));self.assertEqual(v['threads'][0]['priority'],-8);self.assertEqual(v['endpoints'][-1]['endpoint'],0x83)
 def test_truncation(self):
  raw=self.pack(self.fixture())
  for end in (0,270,271,len(raw)-1,len(raw)-4):
   with self.assertRaises(ValueError):decode(raw[:end])
 def test_schema(self):
  for index,value in ((0,0),(2,64),(3,33),(4,2),(60,1),(20,1)):
   w=self.fixture();w[index]=value
   with self.assertRaises(ValueError):decode(self.pack(w))
 def test_duplicate_thread(self):
  w=self.fixture();w[76]=w[68]
  with self.assertRaises(ValueError):decode(self.pack(w))
 def test_missing_udc(self):
  w=self.fixture();w[6]=0x20000444
  with self.assertRaises(ValueError):decode(self.pack(w))
 def test_time_series(self):
  a=self.fixture();b=self.fixture();b[1]+=300
  rows=[{'data_hex':self.pack(w).hex()} for w in (a,b)]
  self.assertEqual(len(summarize(rows)),2)
  with self.assertRaises(ValueError):summarize(rows[::-1])
if __name__=='__main__':unittest.main()
