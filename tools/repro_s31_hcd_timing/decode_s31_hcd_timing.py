"""Join v1 segment timing with HCD activation/retirement diagnostic records.

Activation precedes the HAL call; retirement follows descriptor parsing. Neither
is an electrical bus timestamp. Completion may occur before submit returns;
activation and return are intentionally not ordered relative to each other.
"""
import json,re
from pathlib import Path
from decode_s31_msc_timing import decode as decode_segments

def decode(text):
    groups=decode_segments(text);records={}
    for number,line in enumerate(text.splitlines(),1):
        if 'MSC_HCD_' not in line:continue
        m=re.search(r'MSC_HCD_SEG seq=(\d+) index=(\d+) r=(\d+) a=(\d+) h=(\d+)',line)
        if not m:raise ValueError('Malformed HCD record at line '+str(number))
        seq,index,returned,active,done=map(int,m.groups())
        if (seq,index) in records:raise ValueError('Duplicate HCD record')
        records[seq,index]={'submit_return_us':returned,'active_us':active,'hcd_done_us':done,'hcd_line':number}
    expected={(g['seq'],t['index']) for g in groups for t in g['timing']}
    if set(records)!=expected:raise ValueError('Missing or extra HCD records')
    for g in groups:
        for t in g['timing']:
            t.update(records[g['seq'],t['index']])
            s,c=t['submitted_us'],t['callback_us'];r,a,h=(t[k] for k in ('submit_return_us','active_us','hcd_done_us'))
            if t['attempts']!=1:raise ValueError('HCD analysis requires one submission attempt')
            if not s<=r<=c or not s<=a<=h<=c:raise ValueError('Missing or nonmonotonic HCD timestamps')
            t.update(submit_call_us=r-s,submit_to_active_us=a-s,active_to_hcd_done_us=h-a,hcd_done_to_callback_us=c-h)
    return groups

if __name__=='__main__':
    import sys
    print(json.dumps(decode(Path(sys.argv[1]).read_text(errors='replace')),indent=2))
