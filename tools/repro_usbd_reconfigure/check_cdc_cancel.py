from pathlib import Path
import argparse, re, subprocess, tempfile, hashlib

HEADER=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <errno.h>
#define LOG_WRN(...) ((void)0)
#define LOG_ERR(...) ((void)0)
#define LOG_HEXDUMP_INF(...) ((void)0)
#define K_MSEC(x) (x)
#define K_NO_WAIT 0
#define CONFIG_USBD_CDC_ACM_TX_DELAY_MS 10
#define CDC_ACM_RX_FIFO_BUSY 1
#define CDC_ACM_TX_FIFO_BUSY 2
struct device { void *data; };
struct usbd_context { int unused; };
struct usbd_class_data { struct device *dev; };
struct net_buf { unsigned len; uint8_t *data; };
struct udc_buf_info { uint8_t ep; };
struct work { int unused; };
struct cdc_acm_uart_data {
 unsigned state;void *cb;bool echo_mitigated;int notif_sem;
 struct {void *rb;} rx_fifo,tx_fifo;
 struct work irq_cb_work,rx_fifo_work,tx_fifo_work;
};
static struct usbd_context context;
static struct udc_buf_info info;
static int freed,queued,queued_before_free,scheduled,sem_resets;
static struct cdc_acm_uart_data data;
static struct usbd_context *usbd_class_get_ctx(struct usbd_class_data *c){(void)c;return &context;}
static const struct device *usbd_class_get_private(struct usbd_class_data *c){return c->dev;}
static struct udc_buf_info *udc_get_buf_info(struct net_buf *b){(void)b;return &info;}
static uint8_t cdc_acm_get_bulk_out(struct usbd_class_data *c){(void)c;return 1;}
static uint8_t cdc_acm_get_bulk_in(struct usbd_class_data *c){(void)c;return 0x82;}
static uint8_t cdc_acm_get_int_in(struct usbd_class_data *c){(void)c;return 0x81;}
static void atomic_clear_bit(unsigned *s,int bit){*s&=~(1U<<bit);}
static void k_sem_reset(int *s){*s=0;sem_resets++;}
static void k_sem_give(int *s){(*s)++;}
static size_t ring_buf_put(void *r,uint8_t *p,size_t n){(void)r;(void)p;return n;}
static bool ring_buf_is_empty(void *r){(void)r;return true;}
static void cdc_acm_work_submit(struct work *w){if(w==&data.rx_fifo_work){queued++;queued_before_free+=!freed;}}
static void cdc_acm_work_schedule(struct work *w,int delay){(void)w;(void)delay;scheduled++;}
static int usbd_ep_buf_free(struct usbd_context *c,struct net_buf *b){(void)c;(void)b;freed++;return 0;}
'''
TESTS=r'''
static int tests,failed;
static void check(const char *name,bool ok){tests++;if(!ok){failed++;printf("FAIL %s\n",name);}}
static void run(int endpoint,int error){
 data=(struct cdc_acm_uart_data){.state=(1U<<CDC_ACM_RX_FIFO_BUSY)|(1U<<CDC_ACM_TX_FIFO_BUSY)};
 freed=queued=queued_before_free=scheduled=sem_resets=0;info.ep=endpoint;
 struct device dev={.data=&data};struct usbd_class_data cls={.dev=&dev};struct net_buf buf={0};
 int rc=usbd_cdc_acm_request(&cls,&buf,error);check("buffer freed exactly once",rc==0 && freed==1);
}
int main(void){
 run(1,-ECONNABORTED);
 check("cancelled OUT clears busy",!(data.state&(1U<<CDC_ACM_RX_FIFO_BUSY)));
 check("cancelled OUT rearms",queued==1);
 check("cancelled OUT returns buffer before rearm",queued==1 && queued_before_free==0);
 run(1,-EIO);check("other OUT errors unchanged",queued==0 && !(data.state&(1U<<CDC_ACM_RX_FIFO_BUSY)));
 run(0x82,-ECONNABORTED);check("cancelled IN does not rearm OUT",queued==0 && !(data.state&(1U<<CDC_ACM_TX_FIFO_BUSY)));
 run(0x81,-ECONNABORTED);check("notification cancellation unchanged",queued==0 && sem_resets==1);
 run(1,0);check("successful OUT still rearms",queued==1 && !(data.state&(1U<<CDC_ACM_RX_FIFO_BUSY)));
 printf("%d tests, %d failures\n",tests,failed);return failed?1:0;
}
'''

def main():
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);args=p.parse_args()
    text=args.source.read_text();m=re.search(r'^static int usbd_cdc_acm_request\([^;]*?\)\s*\{',text,re.M);assert m
    start=text.index('{',m.start());end=start+1;depth=1
    while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
    print('source_sha256',hashlib.sha256(text.encode()).hexdigest(),flush=True)
    with tempfile.TemporaryDirectory() as td:
        src=Path(td)/'test.c';binary=Path(td)/'test';src.write_text(HEADER+text[m.start():end]+TESTS)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(src),'-o',str(binary)],check=True)
        return subprocess.run([str(binary)]).returncode
if __name__=='__main__':raise SystemExit(main())
