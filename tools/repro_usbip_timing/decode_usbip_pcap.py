"""Strict bounded non-ISO USB/IP capture decoder. Never exports disk payloads."""
import struct,hashlib,json
from collections import defaultdict,Counter
from pathlib import Path


def reassemble(parts):
    ordered=sorted(parts,key=lambda p:p[0]);base=ordered[0][0];buf=bytearray();ranges=[]
    for seq,stamp,data in ordered:
        offset=seq-base
        if offset>len(buf):raise ValueError('TCP gap')
        overlap=min(len(data),len(buf)-offset)
        if buf[offset:offset+overlap]!=data[:overlap]:raise ValueError('conflicting TCP overlap')
        buf.extend(data[overlap:]);ranges.append((offset,offset+len(data),stamp))
    def timestamp(offset):return min(t for lo,hi,t in ranges if lo<=offset<hi)
    def complete(start,stop):
        if not 0<=start<stop<=len(buf):raise ValueError('invalid completion interval')
        boundaries={start,stop}
        for lo,hi,stamp in ranges:
            if lo<stop and hi>start:
                boundaries.add(max(start,lo));boundaries.add(min(stop,hi))
        # Each subinterval has the same set of covering captured segments.
        # Its earliest arrival is the minimum timestamp among those segments.
        return max(min(stamp for lo,hi,stamp in ranges if lo<=point<hi)
                   for point in sorted(boundaries)[:-1])
    timestamp.complete=complete
    return bytes(buf),timestamp


def pcap_streams(data):
    endian={'d4c3b2a1':'<','a1b2c3d4':'>'}.get(data[:4].hex())
    if not endian:raise ValueError('unsupported pcap magic')
    link=struct.unpack_from(endian+'I',data,20)[0];offset=24;streams=defaultdict(lambda:defaultdict(list))
    while offset<len(data):
        sec,usec,n,original=struct.unpack_from(endian+'IIII',data,offset);offset+=16
        frame=data[offset:offset+n];offset+=n
        if n!=original or len(frame)!=n:raise ValueError('truncated packet')
        if link==276:proto=struct.unpack_from('!H',frame)[0];ip=frame[20:]
        elif link==113:proto=struct.unpack_from('!H',frame,14)[0];ip=frame[16:]
        elif link==1:proto=struct.unpack_from('!H',frame,12)[0];ip=frame[14:]
        else:raise ValueError('unsupported link '+str(link))
        if proto!=0x800 or ip[9]!=6:continue
        ihl=(ip[0]&15)*4;total=struct.unpack_from('!H',ip,2)[0]
        if struct.unpack_from('!H',ip,6)[0]&0x3fff:raise ValueError('IP fragment')
        tcp=ip[ihl:total];src,dst,seq=struct.unpack_from('!HHI',tcp)
        payload=tcp[(tcp[12]>>4)*4:]
        if not payload or 3240 not in (src,dst):continue
        direction='response' if src==3240 else 'request'
        key=(bytes(ip[16:20]),dst,bytes(ip[12:16]),src) if src==3240 else (bytes(ip[12:16]),src,bytes(ip[16:20]),dst)
        streams[key][direction].append((seq,sec+usec/1000000,payload))
    return streams


def decode_stream(request,reply,request_time=lambda _:0,reply_time=lambda _:0):
    if request[:8]!=bytes.fromhex('0111800300000000') or reply[:8]!=bytes.fromhex('0111000300000000'):
        raise ValueError('not a successful import session')
    reqs={};rows=[];offset=40
    while offset<len(request):
        if len(request)-offset<48:raise ValueError('short request header')
        command,seq,dev,direction,ep=struct.unpack_from('!IIIII',request,offset)
        if command not in (1,2):raise ValueError('bad command')
        row={'command':command,'seq':seq,'ep':ep,'direction':direction,'request_time':request_time(offset)}
        size=0
        if command==1:
            flags,length,frame,packets,interval=struct.unpack_from('!Iiiii',request,offset+20)
            if packets not in (-1,0) or length<0 or direction not in (0,1):raise ValueError('unsupported transfer')
            size=length if direction==0 else 0
            row.update(requested_bytes=length,setup=request[offset+40:offset+48].hex())
        else:row['unlink_seq']=struct.unpack_from('!I',request,offset+20)[0]
        payload=request[offset+48:offset+48+size]
        if len(payload)!=size:raise ValueError('short request payload')
        if ep==2 and direction==0 and len(payload)==31 and payload[:4]==b'USBC':
            row['cbw']={'tag':struct.unpack_from('<I',payload,4)[0],'transfer_bytes':struct.unpack_from('<I',payload,8)[0],
                        'direction':payload[12]>>7,'lun':payload[13],'cdb':payload[15:15+payload[14]].hex()}
        if seq in reqs:raise ValueError('duplicate USBIP sequence')
        reqs[seq]=row;rows.append(row);offset+=48+size
    offset=320
    while offset<len(reply):
        if len(reply)-offset<48:raise ValueError('short reply header')
        command,seq=struct.unpack_from('!II',reply,offset)
        if command not in (3,4) or seq not in reqs:raise ValueError('unmatched response')
        row=reqs[seq];status=struct.unpack_from('!i',reply,offset+20)[0]
        if 'status' in row:raise ValueError('duplicate reply')
        actual=struct.unpack_from('!I',reply,offset+24)[0] if command==3 else 0
        size=actual if command==3 and row['direction']==1 else 0
        payload=reply[offset+48:offset+48+size]
        if len(payload)!=size:raise ValueError('short reply payload')
        row.update(status=status,actual_bytes=actual,reply_time=reply_time(offset),reply_final_byte_time=reply_time(offset+47+size),reply_complete_time=reply_time.complete(offset,offset+48+size) if hasattr(reply_time,'complete') else None)
        if row['ep']==3 and row['direction']==1 and len(payload)==13 and payload[:4]==b'USBS':
            row['csw']={'tag':struct.unpack_from('<I',payload,4)[0],'residue':struct.unpack_from('<I',payload,8)[0],'status':payload[12]}
        offset+=48+size
    return rows


def decode(data):
    sessions=[]
    for value in pcap_streams(data).values():
        req,rt=reassemble(value['request']);rep,st=reassemble(value['response'])
        rows=decode_stream(req,rep,rt,st)
        sessions.append({'started_epoch':rt(0),'request_bytes':len(req),'response_bytes':len(rep),
          'command_count':len(rows),'status_counts':dict(Counter(str(x.get('status','pending')) for x in rows)),
          'control':[x for x in rows if x['command']==1 and x['ep']==0],
          'msc':[x for x in rows if x['command']==1 and ((x['ep']==2 and x['direction']==0) or (x['ep']==3 and x['direction']==1))],
          'cdc':[x for x in rows if x['command']==1 and ((x['ep']==1 and x['direction']==0) or (x['ep']==2 and x['direction']==1))],
          'unlinks':[x for x in rows if x['command']==2]})
    return {'pcap_sha256':hashlib.sha256(data).hexdigest(),'sessions':sorted(sessions,key=lambda x:x['started_epoch'])}


if __name__=='__main__':
    import sys
    p=Path(sys.argv[1]);result=decode(p.read_bytes())
    p.with_suffix('.decoded.json').write_text(json.dumps(result,indent=2))
    for i,row in enumerate(result['sessions']):
        print(json.dumps({'session':i,**{k:v for k,v in row.items() if k not in ('msc','control','unlinks')},
            'control':row['control'],'msc_count':len(row['msc']),'msc_first':row['msc'][:9],'msc_last':row['msc'][-8:],'unlinks':row['unlinks']}))
