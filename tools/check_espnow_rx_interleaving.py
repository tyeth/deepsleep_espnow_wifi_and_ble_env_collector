#!/usr/bin/env python3
"""Compile actual ESP-NOW/ringbuf functions and force a producer/reader interleave.

This is a deterministic scheduling reproduction, not hardware incidence data.
No CircuitPython source is modified. Requires a C compiler and source checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def function(text, name):
    import re
    start = re.search(r'^[\w *]+\b' + re.escape(name) + r'\([^;]*?\)\s*\{', text, re.M).start()
    opening = text.index('{', start)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('circuitpython', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.circuitpython.resolve()
    files = ['ports/espressif/common-hal/espnow/ESPNow.c', 'py/ringbuf.c', 'py/ringbuf.h']
    sources = {p: (root/p).read_text() for p in files}
    esp = sources[files[0]]
    ring = sources[files[1]]
    header = sources[files[2]].replace('#include "py/gc.h"', '').replace('#pragma once', '')
    types = esp[esp.index('typedef struct {'):esp.index('// --- The ESP-NOW send')]
    prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <setjmp.h>
#define ESPNOW_MAGIC 0x99
#define ESP_NOW_ETH_ALEN 6
#define ESP_NOW_MAX_DATA_LEN 250
#define m_malloc malloc
typedef uintptr_t mp_obj_t;
typedef int mp_obj_type_t;
static int espnow_packet_type_obj;
#define mp_const_none ((mp_obj_t)0)
#define MP_QSTR_buffer 1
#define MP_OBJ_NEW_SMALL_INT(v) ((mp_obj_t)(v))
static jmp_buf error_target;
static void mp_arg_error_invalid(int q) { (void)q; longjmp(error_target, 1); }
static uint8_t got_mac[6], got_payload[250];
static size_t got_length;
static int bytes_index;
static mp_obj_t mp_obj_new_bytes(const uint8_t *p, size_t n) {
 if (bytes_index++ == 0) { assert(n==6); memcpy(got_mac,p,n); }
 else { assert(n<=250); memcpy(got_payload,p,n); got_length=n; }
 return 1;
}
static mp_obj_t mp_obj_new_int(uint32_t n) { return n; }
static mp_obj_t namedtuple_make_new(const mp_obj_type_t *t, size_t n, size_t k, const mp_obj_t *e) {
 (void)t; (void)n; (void)k; (void)e; return 1;
}
static uint32_t mp_hal_ticks_ms(void) { return 123; }
'''
    middle = r'''
typedef struct { ringbuf_t *recv_buffer; unsigned read_failure,read_success; } espnow_obj_t;
static espnow_obj_t self;
#define MP_STATE_PORT(x) (&self)
typedef struct { int8_t rssi; } rx_ctrl_t;
typedef struct { const uint8_t *src_addr; rx_ctrl_t *rx_ctrl; } esp_now_recv_info_t;
static int read_errors, interrupted_read, put_calls, inject;
static int safe_read(void) {
 bytes_index=0;
 if (setjmp(error_target)) { read_errors++; return -1; }
 return common_hal_espnow_read(&self) ? 1 : 0;
}
static size_t scheduling_put(ringbuf_t *r,const uint8_t *b,size_t n) {
 size_t result=ringbuf_put_n(r,b,n);
 if (inject && ++put_calls==1) interrupted_read=safe_read();
 return result;
}
#define ringbuf_put_n scheduling_put
'''
    main_c = r'''
#undef ringbuf_put_n
static uint8_t storage[512];
static ringbuf_t rb;
static uint8_t mac[6]={2,3,4,5,6,7}, payload[20];
static rx_ctrl_t rx={-30};
static esp_now_recv_info_t info={mac,&rx};
static void reset_case(size_t capacity) {
 ringbuf_init(&rb,storage,capacity); self=(espnow_obj_t){.recv_buffer=&rb};
 inject=0; put_calls=0; read_errors=0; interrupted_read=0;
}
int main(void) {
 memset(payload,0x42,sizeof(payload));
 reset_case(sizeof(storage));
 recv_cb(&info,payload,sizeof(payload));
 assert(safe_read()==1 && got_length==sizeof(payload));
 assert(memcmp(got_payload,payload,sizeof(payload))==0 && memcmp(got_mac,mac,6)==0);
 assert(rb.used==0 && self.read_success==1);
 puts("PASS sequential_complete_packet");
 reset_case(sizeof(espnow_packet_t)+sizeof(payload));
 recv_cb(&info,payload,sizeof(payload));
 assert(self.read_success==1 && safe_read()==1 && rb.used==0);
 puts("PASS exact_capacity_includes_mac");
 reset_case(sizeof(espnow_packet_t)+sizeof(payload)-1);
 recv_cb(&info,payload,sizeof(payload));
 assert(self.read_failure==1 && self.read_success==0 && rb.used==0);
 puts("PASS insufficient_capacity_drops_whole_packet");
 reset_case(sizeof(storage)); inject=1;
 recv_cb(&info,payload,sizeof(payload));
 assert(interrupted_read==-1 && self.read_success==1 && rb.used==26);
 assert(safe_read()==-1 && read_errors==2);
 puts("REPRODUCED header_visible_before_packet_complete_and_followup_invalid");
 reset_case(sizeof(storage));
 recv_cb(&info,payload,sizeof(payload));
 assert(safe_read()==1 && read_errors==0);
 puts("PASS_fresh_buffer_recovers_sequential_control");
 return 0;
}
'''
    ring = ring.replace('#include "ringbuf.h"', '')
    # Read remains byte-for-byte; only the callback's put symbol is wrapped
    # to yield to the consumer after the header, modelling another task/core.
    code = prefix + header + types + ring
    code += '\ntypedef struct { ringbuf_t *recv_buffer; unsigned read_failure,read_success; } espnow_obj_t;\n'
    code += function(esp, 'common_hal_espnow_read')
    middle = middle.replace('typedef struct { ringbuf_t *recv_buffer; unsigned read_failure,read_success; } espnow_obj_t;', '')
    import re
    middle = re.sub(r'\bself\b', 'harness_obj', middle)
    main_c = re.sub(r'\bself\b', 'harness_obj', main_c)
    code += middle + function(esp, 'recv_cb') + main_c
    with tempfile.TemporaryDirectory(prefix='espnow-interleave-') as temp:
        src=Path(temp)/'repro.c';exe=Path(temp)/'repro'
        src.write_text(code)
        subprocess.run(['cc','-std=c11','-O0','-Wall','-Wextra','-Werror',str(src),'-o',str(exe)],check=True)
        result=subprocess.run([str(exe)],text=True,capture_output=True,check=True)
    manifest={'source_head':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),
              'source_sha256':{p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in files},
              'generated_c_sha256':hashlib.sha256(code.encode()).hexdigest(),
              'checks':result.stdout.splitlines(),
              'scope':'Actual callback, read and ringbuf source; injected deterministic scheduling after header publication. No physical incidence or production fix claimed.'}
    args.output.write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':
    main()
