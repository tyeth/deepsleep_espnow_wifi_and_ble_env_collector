"""Decode temporary S31 timing logs; raw UART stays private.

reply_us is after the socket-send attempt, not proof of reception. The caller
must match sequences to a successful network capture. submitted_us is the last
submission attempt; queue_to_submit_us includes earlier attempts when retried.
"""
import re,json
from pathlib import Path

def decode(text):
    ends={};segments={}
    for number,line in enumerate(text.splitlines(),1):
        if 'MSC_TIMING_ALLOCATION_FAILED' in line:
            raise ValueError('Timing allocation failed at line '+str(number))
        if 'MSC_TIMING_' not in line:
            continue
        end=re.search(r'MSC_TIMING_END seq=(\d+) status=(-?\d+) bytes=(\d+) segments=(\d+) reply_us=(\d+)',line)
        seg=re.search(r'MSC_TIMING_SEG seq=(\d+) index=(\d+) q=(\d+) s=(\d+) c=(\d+) d=(\d+) attempts=(\d+) status=(-?\d+) bytes=(\d+)',line)
        if end:
            seq,status,length,count,reply=map(int,end.groups())
            if seq in ends:raise ValueError('Duplicate timing END')
            ends[seq]={'seq':seq,'status':status,'bytes':length,'segments':count,'reply_us':reply,'end_line':number}
        elif seg:
            seq,index,q,s,c,d,attempts,status,length=map(int,seg.groups())
            rows=segments.setdefault(seq,{})
            if index in rows:raise ValueError('Duplicate segment')
            rows[index]={'index':index,'queued_us':q,'submitted_us':s,'callback_us':c,'done_us':d,'attempts':attempts,'status':status,'bytes':length,'line':number}
        else:raise ValueError('Malformed timing marker at line '+str(number))
    if not ends or set(segments)!=set(ends):raise ValueError('Missing END or segment groups')
    result=[]
    for seq,end in ends.items():
        rows=segments[seq];count=end['segments']
        if not 1<=count<=16 or set(rows)!=set(range(count)):raise ValueError('Incomplete or extra segment indices')
        if end['status']!=0 or end['bytes']!=65536 or count!=16:
            raise ValueError('Not a successful complete 64 KiB timing sample')
        ordered=[rows[i] for i in range(count)]
        for i,row in enumerate(ordered):
            q,s,c,d=(row[k] for k in ('queued_us','submitted_us','callback_us','done_us'))
            if not 0<q<=s<=c<=d<=end['reply_us']:raise ValueError('Missing or nonmonotonic timestamps')
            if i and q<ordered[i-1]['done_us']:raise ValueError('Segments overlap unexpectedly')
            if row['attempts']<1 or row['status'] or row['bytes']!=4096:raise ValueError('Failed or short segment')
            row.update(queue_to_submit_us=s-q,submit_to_callback_us=c-s,callback_to_done_us=d-c)
        result.append({**end,'total_to_reply_us':end['reply_us']-ordered[0]['queued_us'],
                       'last_done_to_reply_us':end['reply_us']-ordered[-1]['done_us'],'timing':ordered})
    return result

if __name__=='__main__':
    import sys
    print(json.dumps(decode(Path(sys.argv[1]).read_text(errors='replace')),indent=2))
