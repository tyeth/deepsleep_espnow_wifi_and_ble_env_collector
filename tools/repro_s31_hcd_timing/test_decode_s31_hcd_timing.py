import unittest
from decode_s31_hcd_timing import decode
from test_decode_s31_msc_timing import fixture

def sample():
    lines=fixture().splitlines()
    for i in range(16):
        q=1+100*i
        lines.append(f'MSC_HCD_SEG seq=11 index={i} r={q+5} a={q+3} h={q+70}')
    return '\n'.join(lines)

class HcdTests(unittest.TestCase):
    def test_complete_and_exact(self):
        r,=decode(sample())
        self.assertEqual([(t['submit_call_us'],t['submit_to_active_us'],t['active_to_hcd_done_us'],t['hcd_done_to_callback_us']) for t in r['timing']],[(3,1,67,10)]*16)
    def test_activation_after_return_allowed(self):
        self.assertEqual(decode(sample().replace('a=4 ','a=8 '))[0]['timing'][0]['submit_to_active_us'],5)
    def test_completion_before_return_allowed(self):
        self.assertEqual(decode(sample().replace('r=6 ','r=75 '))[0]['timing'][0]['submit_call_us'],72)
    def test_missing_extra_duplicate(self):
        for raw in ('\n'.join(sample().splitlines()[:-1]),sample()+'\nMSC_HCD_SEG seq=12 index=0 r=6 a=4 h=71',sample()+'\n'+sample().splitlines()[-1]):
            with self.assertRaises(ValueError):decode(raw)
    def test_clocks(self):
        for old,new in [('r=6 ','r=0 '),('a=4 ','a=0 '),('h=71','h=0'),('r=6 ','r=82 '),('h=71','h=82')]:
            with self.assertRaises(ValueError):decode(sample().replace(old,new))
    def test_retries_rejected(self):
        with self.assertRaises(ValueError):decode(sample().replace('attempts=1','attempts=2',1))
    def test_malformed_and_no_records(self):
        for raw in (fixture(),sample()+'\nMSC_HCD_SEG bad'):
            with self.assertRaises(ValueError):decode(raw)

if __name__=='__main__':unittest.main()
