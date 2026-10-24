import unittest
from decode_s31_msc_timing import decode

def fixture(seq=11):
    # END is intentionally emitted before its buffered per-segment records.
    lines=[f'log MSC_TIMING_END seq={seq} status=0 bytes=65536 segments=16 reply_us=1605']
    for i in range(16):
        q=1+i*100
        lines.append(f'log MSC_TIMING_SEG seq={seq} index={i} q={q} s={q+2} c={q+80} d={q+90} attempts=1 status=0 bytes=4096')
    return '\n'.join(lines)

class TimingTests(unittest.TestCase):
    def test_valid_and_exact_delays(self):
        r,=decode('unrelated uart\n'+fixture())
        self.assertEqual((r['total_to_reply_us'],r['last_done_to_reply_us']),(1604,14))
        self.assertEqual([(x['queue_to_submit_us'],x['submit_to_callback_us'],x['callback_to_done_us']) for x in r['timing']],[(2,78,10)]*16)
    def test_missing_and_duplicate(self):
        for raw in ('\n'.join(fixture().splitlines()[:-1]),fixture()+'\n'+fixture().splitlines()[1],fixture()+'\n'+fixture().splitlines()[0]):
            with self.assertRaises(ValueError):decode(raw)
    def test_invalid_clock_and_short(self):
        for raw in (fixture().replace('s=3','s=0'),fixture().replace('d=91','d=2'),fixture().replace('bytes=4096','bytes=100',1)):
            with self.assertRaises(ValueError):decode(raw)
    def test_failure_allocation_and_malformed(self):
        for raw in (fixture().replace('status=0','status=-5',1),fixture()+'\nMSC_TIMING_ALLOCATION_FAILED','MSC_TIMING_SEG truncated'):
            with self.assertRaises(ValueError):decode(raw)
    def test_interleaved_groups(self):
        a,b=fixture(11).splitlines(),fixture(12).splitlines()
        self.assertEqual([x['seq'] for x in decode('\n'.join(z for pair in zip(a,b) for z in pair))],[11,12])
    def test_retry_counts_preserved_and_zero_rejected(self):
        r,=decode(fixture().replace('attempts=1','attempts=3',1))
        self.assertEqual(r['timing'][0]['attempts'],3)
        with self.assertRaises(ValueError):decode(fixture().replace('attempts=1','attempts=0',1))
    def test_bad_segment_and_end_shape(self):
        rows=fixture().splitlines()
        rows[1]=rows[1].replace('status=0','status=-5')
        for raw in ('\n'.join(rows),fixture().replace('segments=16','segments=17'),
                    fixture().replace('bytes=65536','bytes=65535'),
                    fixture().replace('index=15','index=16'),
                    fixture().replace('reply_us=1605','reply_us=1500')):
            with self.assertRaises(ValueError):decode(raw)

if __name__=='__main__':unittest.main()
