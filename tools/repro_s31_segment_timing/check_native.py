from pathlib import Path
import re,subprocess,argparse,tempfile
p=argparse.ArgumentParser();p.add_argument('bridge_checkout',type=Path)
r=p.parse_args().bridge_checkout.resolve()
workspace=tempfile.TemporaryDirectory(prefix='s31-timing-native-');s=Path(workspace.name)
server=(r/'main/usbip_server.c').read_text();backend=(r/'main/usb_backend.c').read_text();header=(r/'main/usb_backend.h').read_text()
def function(source,name):
 m=re.search(r'^static [^\n]+\b'+re.escape(name)+r'\([^)]*\)\n\{',source,re.M);assert m,name
 start=source.index('{',m.start());depth=0
 for pos in range(start,len(source)):
  depth+=(source[pos]=='{')-(source[pos]=='}')
  if not depth:return source[m.start():pos+1]
 raise ValueError(name)
req=header[header.index('typedef struct usb_backend_req '):header.index('\n/* Queue a transfer.')]
types=server[server.index('typedef struct {\n    uint64_t queued_us'):server.index('\n/* Free an in-flight slot')]
buf=server[server.index('typedef struct {\n    uint8_t *seg'):server.index('\nstatic size_t urb_buf_nsegs')]
preamble=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
#include <arpa/inet.h>
#include "usbip_protocol.h"
#define URB_SEG_SIZE 4096
#define URB_MAX_SEGS 256
typedef struct { uint8_t bytes[8]; } usb_setup_packet_t;
typedef struct urb_stream_ctx urb_stream_ctx_t;
'''
support=r'''
static uint64_t ticks;
static uint64_t esp_timer_get_time(void) { return ++ticks; }
static unsigned submitted,queued;
static void usb_backend_submit(usb_backend_req_t *req) { assert(req->in_capacity<=4096); submitted++; }
static void urb_queue_done(urb_work_item_t *item) { (void)item; queued++; }
typedef struct { usb_backend_req_t *req; bool completed; } xfer_t;
typedef struct { void *context; } usb_transfer_t;
'''
tests=r'''
static void init(urb_work_item_t *item, msc_urb_timing_t *timing) {
    memset(item,0,sizeof(*item)); memset(timing,0,sizeof(*timing));
    item->request.base.direction=htonl(USBIP_DIR_IN);
    item->in.len=65536; item->diagnostic=timing; item->req.diagnostic_timing=true;
    submitted=queued=0; ticks=0;
}
static void complete_segment(urb_work_item_t *item,int status,size_t n) {
    item->req.diagnostic_submitted_us=esp_timer_get_time();
    item->req.diagnostic_attempts=1;
    ticks+=100;
    xfer_t x={.req=&item->req};usb_transfer_t transfer={.context=&x};
    xfer_done_cb(&transfer); assert(x.completed);
    urb_backend_done(&item->req,status,n);
}
int main(void) {
    urb_work_item_t item; msc_urb_timing_t timing;
    init(&item,&timing);urb_submit_segment(&item);
    for(unsigned i=0;i<16;i++) {
        complete_segment(&item,0,4096);
        assert(timing.recorded==i+1 && timing.segments[i].attempts==1);
        const msc_segment_timing_t *p=&timing.segments[i];
        assert(p->queued_us<p->submitted_us && p->submitted_us<p->callback_us && p->callback_us<p->done_us);
        assert(p->bytes==4096 && p->status==0);
        assert(queued==(i==15));
    }
    assert(submitted==16 && item.in_len==65536 && item.status==0);
    init(&item,&timing);urb_submit_segment(&item);complete_segment(&item,0,100);
    assert(submitted==1 && queued==1 && item.in_len==100 && timing.recorded==1);
    init(&item,&timing);urb_submit_segment(&item);complete_segment(&item,0,4096);complete_segment(&item,-EIO,0);
    assert(submitted==2 && queued==1 && item.status==-EIO && item.in_len==0 && timing.recorded==2);
    assert(timing.segments[1].status==-EIO && timing.segments[0].bytes==4096);
    init(&item,&timing);urb_submit_segment(&item);item.req.cancel=true;complete_segment(&item,0,4096);
    assert(submitted==1 && queued==1 && item.status==-ECONNRESET && item.in_len==0);
    init(&item,&timing);item.diagnostic=NULL;item.req.diagnostic_timing=false;urb_submit_segment(&item);
    for(unsigned i=0;i<16;i++) urb_backend_done(&item.req,0,4096);
    assert(submitted==16 && queued==1 && item.in_len==65536 && timing.recorded==0 && ticks==0);
    xfer_t orphan={0};usb_transfer_t transfer={.context=&orphan};xfer_done_cb(&transfer);assert(orphan.completed);
    puts("PASS: full sixteen segments, short completion, error, cancel, untimed path and orphan callback");
}
'''
code=preamble+req+buf+types+support+'\n'.join(function(server,n) for n in ('urb_buf_nsegs','urb_buf_seg_len','urb_is_in','urb_submit_segment','urb_backend_done'))+'\n'+function(backend,'xfer_done_cb')+tests
source=s/'s31-msc-timing-native.c';binary=s/'s31-msc-timing-native';source.write_text(code)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g','-I',str(r/'main'),str(source),'-o',str(binary)],check=True)
subprocess.run([str(binary)],check=True)
