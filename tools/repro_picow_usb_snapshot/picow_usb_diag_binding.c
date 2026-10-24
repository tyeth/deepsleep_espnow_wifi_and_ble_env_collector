/* Temporary Env Hub instrumentation: passive snapshots, no USB operations. */
#include <zephyr/kernel.h>
#include <zephyr/irq.h>
#include <stdint.h>
#include <string.h>
#include "py/obj.h"
#include "py/runtime.h"

extern size_t envhub_udc_snapshot(uint32_t *out, size_t capacity);
static uint32_t snapshot_words[4 + 64 + 32 * 8];
static size_t snapshot_threads;
static void snapshot_thread(const struct k_thread *thread, void *unused) {
    (void)unused;
    if (snapshot_threads == 32) {
        return;
    }
    uint32_t *out = &snapshot_words[68 + snapshot_threads++ * 8];
    out[0] = (uintptr_t)thread;
    out[1] = (uintptr_t)thread->base.pended_on;
    out[2] = thread->callee_saved.psp;
    out[3] = (uintptr_t)thread->entry.pEntry;
    out[4] = (int32_t)thread->base.prio;
    out[5] = thread->base.thread_state;
    out[6] = thread->stack_info.start;
    out[7] = thread->stack_info.size;
}
static mp_obj_t envhub_snapshot(void) {
    memset(snapshot_words, 0, sizeof(snapshot_words));
    snapshot_threads = 0;
    unsigned int key = irq_lock();
    snapshot_words[0] = 0x454e5601;
    snapshot_words[1] = k_uptime_get_32();
    snapshot_words[2] = envhub_udc_snapshot(&snapshot_words[4], 64);
    k_thread_foreach(snapshot_thread, NULL);
    snapshot_words[3] = snapshot_threads;
    irq_unlock(key);
    return mp_obj_new_bytes((const byte *)snapshot_words, (68 + snapshot_threads * 8) * 4);
}
static MP_DEFINE_CONST_FUN_OBJ_0(envhub_snapshot_obj, envhub_snapshot);
static const mp_rom_map_elem_t envhub_globals_table[] = {
    {MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_envhub_usb_diag)},
    {MP_ROM_QSTR(MP_QSTR_snapshot), MP_ROM_PTR(&envhub_snapshot_obj)},
};
static MP_DEFINE_CONST_DICT(envhub_globals, envhub_globals_table);
const mp_obj_module_t envhub_usb_diag_module = {
    .base = {&mp_type_module},
    .globals = (mp_obj_dict_t *)&envhub_globals,
};
MP_REGISTER_MODULE(MP_QSTR_envhub_usb_diag, envhub_usb_diag_module);
