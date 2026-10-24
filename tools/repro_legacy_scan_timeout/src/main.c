/* SPDX-License-Identifier: MIT */
#include <zephyr/kernel.h>
#include <zephyr/bluetooth/bluetooth.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/sys/atomic.h>
#include <pico/bootrom.h>

static const struct device *console = DEVICE_DT_GET(DT_CHOSEN(zephyr_console));
K_SEM_DEFINE(start_request, 0, 1);
static atomic_t reports, late_reports, timeouts;
static int64_t started;

static void received(const struct bt_le_scan_recv_info *info, struct net_buf_simple *data)
{
 ARG_UNUSED(info); ARG_UNUSED(data);
 atomic_inc(&reports);
 if (k_uptime_get() - started >= 3500) { atomic_inc(&late_reports); }
}
static void timed_out(void) { atomic_inc(&timeouts); }
static struct bt_le_scan_cb callbacks = {.recv = received, .timeout = timed_out};

/* Keep ROM recovery responsive independently of the scanner's thread. */
static void commands(void *a, void *b, void *c)
{
 ARG_UNUSED(a); ARG_UNUSED(b); ARG_UNUSED(c);
 while (!device_is_ready(console)) { k_sleep(K_MSEC(100)); }
 for (;;) {
  unsigned char ch;
  if (uart_poll_in(console, &ch) == 0) {
   if (ch == 'g') { k_sem_give(&start_request); }
   if (ch == 'r') { reset_usb_boot(0, 0); }
  }
  k_sleep(K_MSEC(10));
 }
}
K_THREAD_DEFINE(command_thread, 1536, commands, NULL, NULL, NULL, 1, 0, 0);

int main(void)
{
 bool enabled = false;
 for (;;) {
  printk("LEGACY_READY build=1 ext_adv=%d privacy=%d g=run r=rom\n",
         IS_ENABLED(CONFIG_BT_EXT_ADV), IS_ENABLED(CONFIG_BT_PRIVACY));
  if (k_sem_take(&start_request, K_SECONDS(2)) != 0) { continue; }
  if (!enabled) {
   int err = bt_enable(NULL);
   printk("LEGACY_ENABLE err=%d\n", err);
   if (err) { continue; }
   bt_le_scan_cb_register(&callbacks); enabled = true;
  }
  const uint16_t durations[] = {300, 0, 300};
  for (size_t i = 0; i < ARRAY_SIZE(durations); ++i) {
   struct bt_le_scan_param p = {
    .type=BT_LE_SCAN_TYPE_PASSIVE, .options=0,
    .interval=BT_GAP_SCAN_FAST_INTERVAL, .window=BT_GAP_SCAN_FAST_WINDOW,
    .timeout=durations[i],
   };
   atomic_set(&reports,0); atomic_set(&late_reports,0); atomic_set(&timeouts,0);
   started=k_uptime_get();
   int err=bt_le_scan_start(&p,NULL);
   printk("LEGACY_START case=%u timeout_units=%u err=%d\n", (unsigned)i,p.timeout,err);
   if (err) { continue; }
   for (int second=1; second<=6; ++second) {
    k_sleep(K_SECONDS(1));
    printk("LEGACY_SAMPLE case=%u elapsed_ms=%lld reports=%ld late=%ld callbacks=%ld\n",
           (unsigned)i,(long long)(k_uptime_get()-started),(long)atomic_get(&reports),
           (long)atomic_get(&late_reports),(long)atomic_get(&timeouts));
   }
   err=bt_le_scan_stop();
   k_sleep(K_MSEC(250));
   atomic_val_t stopped=atomic_get(&reports);
   k_sleep(K_MSEC(750));
   printk("LEGACY_RESULT case=%u timeout_units=%u reports=%ld late=%ld callbacks=%ld stop_err=%d post_stop=%ld\n",
          (unsigned)i,p.timeout,(long)atomic_get(&reports),(long)atomic_get(&late_reports),
          (long)atomic_get(&timeouts),err,(long)(atomic_get(&reports)-stopped));
  }
  printk("LEGACY_DONE\n");
 }
}
