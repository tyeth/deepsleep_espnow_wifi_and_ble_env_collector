"""Compile exact HAL functions against fault-injected hardware hooks (not a board test)."""
import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path

def function(source, name):
    match = re.search(r"^[\w *]+\b" + name + r"\([^;]*?\)\s*\{", source, re.M)
    assert match, name
    start = match.start()
    depth = 1
    end = match.end()
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hal", type=Path)
    parser.add_argument("--baseline", default="HEAD^")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prefix = "src/rp2_common/pico_cyw43_driver/cybt_shared_bus/"
    def source(ref, file):
        return subprocess.check_output(["git", "-C", str(args.hal), "show", ref + ":" + prefix + file], text=True)
    startup_stub = r'''
#include <stdint.h>
#include <stdlib.h>
#include <assert.h>
typedef int cybt_result_t;
typedef int cyw43_ll_t;
#define CYBT_SUCCESS 0
#define CYBT_ERR_HCI_INIT_FAILED 99
#define CYW43_USE_HEX_BTFW 0
#define BTSDIO_FW_READY_POLLING_RETRY_COUNT 1
#define BTSDIO_FW_AWAKE_POLLING_RETRY_COUNT 1
#define cybt_error(...) ((void)0)
#define cybt_debug(...) ((void)0)
#define cybt_assert assert
static int fail_stage, reached, finished;
static const uint8_t cyw43_btfw_43439[]={0};
static const uint32_t cyw43_btfw_43439_len=1;
static void cybt_sharedbus_driver_init(cyw43_ll_t *s){(void)s;}
static int step(int n){reached=n;return fail_stage==n ? -n : 0;}
static int cybt_fw_download_prepare(uint8_t **a,uint8_t **b){(void)a;(void)b;return step(1);}
static int cybt_fw_download(const uint8_t *a,uint32_t b,uint8_t *c,uint8_t *d){(void)a;(void)b;(void)c;(void)d;return step(2);}
static void cybt_fw_download_finish(uint8_t *a,uint8_t *b){(void)a;(void)b;finished++;}
static int cybt_wait_bt_ready(int n){(void)n;return step(3);}
static int cybt_init_buffer(void){return step(4);}
static int cybt_wait_bt_awake(int n){(void)n;return step(5);}
static void cybt_set_host_ready(void){reached=6;}
static void cybt_toggle_bt_intr(void){reached=7;}
'''
    startup_main = r'''
int main(int argc,char **argv){
 assert(argc==2); fail_stage=atoi(argv[1]);
 int got=cyw43_btbus_init(NULL);
 int expected=fail_stage==0?0:(fail_stage==2||fail_stage==3?99:-fail_stage);
 assert(got==expected);
 assert(reached==(fail_stage?fail_stage:7));
 assert(finished==(fail_stage==1?0:1));
 return 0;
}
'''
    cache_stub = r'''
#include <stdint.h>
#include <assert.h>
typedef int cybt_result_t;
#define CYBT_SUCCESS 0
#define HOST_CTRL_REG_ADDR 16
#define cybt_debug(...) ((void)0)
static uint32_t host_ctrl_cache_reg, hardware;
static int reads,writes,drop;
static void *cyw43_ll;
static int cyw43_ll_write_backplane_reg(void *p,uint32_t a,uint32_t v){(void)p;(void)a;writes++;if(!drop)hardware=v;return drop?-1:0;}
static uint32_t cyw43_ll_read_backplane_reg(void *p,uint32_t a){(void)p;(void)a;reads++;return hardware;}
'''
    cache_main = r'''
int main(void){
 uint32_t value=0;
 assert(cybt_reg_write(HOST_CTRL_REG_ADDR,7)==0);
 assert(cybt_reg_read(HOST_CTRL_REG_ADDR,&value)==0);
 assert(value==7 && hardware==7 && reads==0 && writes==1);
 drop=1;
 assert(cybt_reg_write(HOST_CTRL_REG_ADDR,9)==0);
 assert(cybt_reg_read(HOST_CTRL_REG_ADDR,&value)==0);
 assert(value==9 && hardware==7 && reads==0 && writes==2);
 assert(cybt_reg_read(32,&value)==0);
 assert(value==7 && reads==1);
 hardware=3;
 assert(cybt_reg_read(HOST_CTRL_REG_ADDR,&value)==0);
 assert(value==9 && hardware==3 && reads==1);
 return 0;
}
'''
    result = {"scope":"Exact C functions with injected hardware hooks; no physical fault injection", "sources":{}, "startup":{}, "cache":{}}
    with tempfile.TemporaryDirectory() as directory:
        directory=Path(directory)
        for ref,label in [("HEAD","candidate"),(args.baseline,"baseline")]:
            raw=source(ref,"cybt_shared_bus.c")
            block=function(raw,"cyw43_btbus_init")
            result["sources"][label]={"commit":subprocess.check_output(["git","-C",str(args.hal),"rev-parse",ref],text=True).strip(),"function_sha256":hashlib.sha256(block.encode()).hexdigest()}
            c=directory/(label+".c"); binary=directory/label
            c.write_text(startup_stub+block+startup_main)
            subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror",str(c),"-o",str(binary)],check=True)
            outcomes=[]
            for stage in range(6):
                run=subprocess.run([str(binary),str(stage)],capture_output=True,text=True)
                outcomes.append({"stage":stage,"returncode":run.returncode,"stderr":run.stderr.strip()})
            result["startup"][label]=outcomes
        raw=source("HEAD","cybt_shared_bus_driver.c")
        block=function(raw,"cybt_reg_write")+"\n"+function(raw,"cybt_reg_read")
        c=directory/"cache.c";binary=directory/"cache"
        c.write_text(cache_stub+block+cache_main)
        subprocess.run(["cc","-std=c11","-Wall","-Wextra","-Werror",str(c),"-o",str(binary)],check=True)
        run=subprocess.run([str(binary)],capture_output=True,text=True)
        result["cache"]={"function_sha256":hashlib.sha256(block.encode()).hexdigest(),"returncode":run.returncode,"cases":4,"lost_write_divergence_reproduced":run.returncode==0,"physical_lost_write_observed":False}
    args.output.write_text(json.dumps(result,indent=2)+"\n")
    assert all(item["returncode"]==0 for item in result["startup"]["candidate"])
    assert [item["returncode"]==0 for item in result["startup"]["baseline"]]==[True,True,True,False,False,False]
    assert result["cache"]["returncode"]==0
    print("PASS: six candidate startup paths; three baseline assertion failures; four cache controls/divergence checks")

if __name__=="__main__":main()
