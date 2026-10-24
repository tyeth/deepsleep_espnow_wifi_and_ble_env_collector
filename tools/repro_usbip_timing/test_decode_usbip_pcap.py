import struct,unittest
from decode_usbip_pcap import reassemble,decode_stream

class Tests(unittest.TestCase):
 def test_reordered_overlap(self):
  b,t=reassemble([(103,2,b'def'),(100,1,b'abcde'),(100,3,b'abcde')]);self.assertEqual(b,b'abcdef');self.assertEqual(t(3),1)
 def test_gap(self):
  with self.assertRaisesRegex(ValueError,'gap'):reassemble([(1,1,b'a'),(3,2,b'c')])
 def test_conflict(self):
  with self.assertRaisesRegex(ValueError,'conflicting'):reassemble([(1,1,b'ab'),(2,2,b'x')])
 def fixture(self):
  req=bytes.fromhex('0111800300000000')+bytes(32)
  req+=struct.pack('!IIIIIIiiii8s',1,7,1,1,3,0,13,0,-1,0,bytes(8))
  rep=bytes.fromhex('0111000300000000')+bytes(312)
  # RET header's direction/ep are zero; request association determines payload length.
  rep+=struct.pack('!IIIIIiIiii8s',3,7,0,0,0,0,13,0,-1,0,bytes(8))
  rep+=b'USBS'+struct.pack('<II',123,0)+bytes([0])
  return req,rep
 def test_response_direction_from_request(self):
  rows=decode_stream(*self.fixture());self.assertEqual(rows[0]['csw'],{'tag':123,'residue':0,'status':0})
 def test_truncated(self):
  req,rep=self.fixture()
  with self.assertRaisesRegex(ValueError,'short reply payload'):decode_stream(req,rep[:-1])
 def test_unknown_reply(self):
  req,rep=self.fixture();rep=rep[:324]+struct.pack('!I',99)+rep[328:]
  with self.assertRaisesRegex(ValueError,'unmatched'):decode_stream(req,rep)



class CompletionTests(unittest.TestCase):
 fixture=Tests.fixture
 def test_last_byte_before_missing_middle(self):
  req,rep=self.fixture()
  data,stamp=reassemble([(0,1,rep[:368]),(368,4,rep[368:373]),(373,3,rep[373:])])
  row,=decode_stream(req,data,reply_time=stamp)
  self.assertEqual((row['reply_time'],row['reply_final_byte_time'],row['reply_complete_time']),(1,3,4))
 def test_late_identical_retransmission(self):
  req,rep=self.fixture()
  data,stamp=reassemble([(0,1,rep[:368]),(368,2,rep[368:]),(368,9,rep[368:])])
  row,=decode_stream(req,data,reply_time=stamp)
  self.assertEqual(row['reply_complete_time'],2)
 def test_single_packet(self):
  req,rep=self.fixture()
  data,stamp=reassemble([(0,5,rep)])
  row,=decode_stream(req,data,reply_time=stamp)
  self.assertEqual(row['reply_complete_time'],row['reply_time'])
if __name__=='__main__':unittest.main()
