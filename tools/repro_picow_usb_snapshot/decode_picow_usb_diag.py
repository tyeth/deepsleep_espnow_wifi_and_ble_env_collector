"""Decode passive Env Hub snapshots; does not access hardware."""
import struct
UDC_FIELDS=('version','uptime_ms','thread','mutex','mutex_owner','mutex_depth','events','xfer_new','xfer_finished','sof','sie_status','buffer_status','interrupts','abort','abort_done','device_address')
THREAD_FIELDS=('address','pended_on','psp','entry','priority','state','stack_start','stack_size')
def decode(raw):
 if len(raw)<272 or len(raw)%4:raise ValueError('Truncated or unaligned snapshot')
 words=struct.unpack('<'+'I'*(len(raw)//4),raw)
 magic,uptime,nudc,nthreads=words[:4]
 if magic!=0x454e5601 or nudc!=56 or not 0<nthreads<=32:raise ValueError('Unknown snapshot schema')
 if len(words)!=68+nthreads*8:raise ValueError('Invalid snapshot length')
 if any(words[60:68]):raise ValueError('Nonzero reserved words')
 udc=dict(zip(UDC_FIELDS,words[4:20]))
 if udc['version']!=1:raise ValueError('Unknown UDC schema')
 endpoints=[]
 for i in range(8):
  ep,bufctrl,state,buf,length=words[20+5*i:25+5*i]
  if ep!=(i//2 | (0x80 if i%2 else 0)):raise ValueError('Endpoint order mismatch')
  endpoints.append({'endpoint':ep,'buffer_control':bufctrl,'busy':bool(state&1),'halted':bool(state&2),'queued_buffer':buf,'queued_length':length})
 threads=[]
 for i in range(nthreads):
  t=dict(zip(THREAD_FIELDS,words[68+8*i:76+8*i]))
  if t['priority']>=0x80000000:t['priority']-=0x100000000
  threads.append(t)
 if len({x['address'] for x in threads})!=nthreads:raise ValueError('Duplicate thread')
 if udc['thread'] not in {x['address'] for x in threads}:raise ValueError('UDC thread absent')
 return {'uptime_ms':uptime,'udc':udc,'endpoints':endpoints,'threads':threads}
def summarize(samples):
 decoded=[decode(bytes.fromhex(x['data_hex'])) for x in samples]
 if not decoded:raise ValueError('Empty capture')
 times=[x['uptime_ms'] for x in decoded]
 if any(b<=a for a,b in zip(times,times[1:])):raise ValueError('Non-increasing timestamps')
 return decoded
