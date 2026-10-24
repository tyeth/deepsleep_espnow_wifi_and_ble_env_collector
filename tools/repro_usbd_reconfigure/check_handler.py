#!/usr/bin/env python3
"""Compile the actual SET_CONFIGURATION handler with observable dependencies."""
from pathlib import Path
import argparse
import hashlib
import re
import subprocess
import tempfile

PRELUDE = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <errno.h>
#define LOG_DBG(...) ((void)0)
#define LOG_ERR(...) ((void)0)
#define USB_REQTYPE_RECIPIENT_DEVICE 0
#define USBD_STATE_DEFAULT 0
#define USBD_STATE_ADDRESS 1
#define USBD_STATE_CONFIGURED 2
#define USBD_MSG_CONFIGURATION 10
enum usbd_speed { USBD_SPEED_FS };
struct usb_setup_packet { uint16_t wValue, wLength; struct { int recipient; } RequestType; };
struct usbd_context { struct { int state; } ch9_data; };
static struct usb_setup_packet setup;
static int current, calls, result, published, published_value;
static bool exists;
static struct usb_setup_packet *usbd_get_setup_pkt(struct usbd_context *c) { (void)c; return &setup; }
static enum usbd_speed usbd_bus_speed(struct usbd_context *c) { (void)c; return USBD_SPEED_FS; }
static bool usbd_state_is_default(struct usbd_context *c) { return c->ch9_data.state == USBD_STATE_DEFAULT; }
static bool usbd_config_exist(struct usbd_context *c, enum usbd_speed s, uint8_t v) { (void)c;(void)s;(void)v; return exists; }
static int usbd_get_config_value(struct usbd_context *c) { (void)c; return current; }
static int usbd_config_set(struct usbd_context *c, uint8_t v) { (void)c;calls++; if(!result)current=v;return result; }
static void usbd_msg_pub_simple(struct usbd_context *c,int msg,int v) { (void)c;(void)msg;published++;published_value=v; }
'''
TESTS = r'''
static int failures, tests;
static void check(const char *name, bool ok) { tests++; if(!ok){failures++;printf("FAIL %s\n",name);} }
static struct usbd_context fresh(int old, int requested) {
 current=old; calls=result=published=published_value=0;exists=true;
 setup=(struct usb_setup_packet){.wValue=requested};
 return (struct usbd_context){.ch9_data={.state=old?USBD_STATE_CONFIGURED:USBD_STATE_ADDRESS}};
}
int main(void) {
 struct usbd_context c=fresh(1,1);int rc=sreq_set_configuration(&c);
 check("same nonzero configuration reinitializes",rc==0 && calls==1 && current==1 && published==1 && published_value==1 && c.ch9_data.state==USBD_STATE_CONFIGURED);
 c=fresh(1,1);result=-EIO;rc=sreq_set_configuration(&c);
 check("same configuration propagates backend failure",rc==-EIO && calls==1 && published==0);
 c=fresh(0,0);rc=sreq_set_configuration(&c);
 check("already unconfigured remains a no-op",rc==0 && calls==0 && published==0 && c.ch9_data.state==USBD_STATE_ADDRESS);
 c=fresh(0,1);rc=sreq_set_configuration(&c);
 check("first configuration",rc==0 && calls==1 && published==1 && c.ch9_data.state==USBD_STATE_CONFIGURED);
 c=fresh(1,0);rc=sreq_set_configuration(&c);
 check("unconfigure",rc==0 && calls==1 && published==1 && current==0 && c.ch9_data.state==USBD_STATE_ADDRESS);
 c=fresh(1,2);rc=sreq_set_configuration(&c);
 check("change configuration",rc==0 && calls==1 && current==2 && published_value==2);
 c=fresh(1,1);setup.wLength=1;rc=sreq_set_configuration(&c);
 check("reject nonzero length",rc==-ENOTSUP && calls==0 && published==0);
 c=fresh(1,256);rc=sreq_set_configuration(&c);
 check("reject value overflow",rc==-ENOTSUP && calls==0);
 c=fresh(1,1);setup.RequestType.recipient=2;rc=sreq_set_configuration(&c);
 check("reject endpoint recipient",rc==-ENOTSUP && calls==0);
 c=fresh(0,1);c.ch9_data.state=USBD_STATE_DEFAULT;rc=sreq_set_configuration(&c);
 check("reject default state",rc==-EPERM && calls==0);
 c=fresh(1,2);exists=false;rc=sreq_set_configuration(&c);
 check("reject missing configuration",rc==-EPERM && calls==0 && current==1);
 printf("%d tests, %d failures\n",tests,failures);return failures?1:0;
}
'''

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    args=parser.parse_args()
    text=args.source.read_text()
    match=re.search(r'^static int sreq_set_configuration\([^;]*?\)\s*\{',text,re.M)
    assert match
    start=text.index('{',match.start());end=start+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    function=text[match.start():end]
    print('source_sha256',hashlib.sha256(text.encode()).hexdigest(),flush=True)
    with tempfile.TemporaryDirectory() as tmp:
        source=Path(tmp)/'test.c';binary=Path(tmp)/'test'
        source.write_text(PRELUDE+function+TESTS)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True)
        return subprocess.run([str(binary)]).returncode

if __name__=='__main__':
    raise SystemExit(main())
