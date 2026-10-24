// SPDX-License-Identifier: MIT
// Bounded ESP-NOW send(NULL) contract probe; no CircuitPython and no NVS writes.
#include <stdio.h>
#include <assert.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_now.h"
#include "esp_system.h"
#include "esp_wifi.h"

static const uint8_t broadcast[6] = {255,255,255,255,255,255};
static const uint8_t unicast[6] = {2,0,0,0,0,1};
static const uint8_t payload[] = "envhub-send-contract";
typedef struct {const char *mode; const char *call; int round; esp_err_t result;} result_t;
static result_t results[30];
static int result_count, current_round;


static void add(const uint8_t *mac) {
    esp_now_peer_info_t peer = {0};
    memcpy(peer.peer_addr, mac, 6);
    peer.ifidx = WIFI_IF_STA;
    peer.channel = 1;
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));
}

static void probe(const char *mode, const char *call, const uint8_t *mac) {
    esp_err_t result = esp_now_send(mac, payload, sizeof(payload)-1);
    assert(result_count < 30);
    results[result_count++] = (result_t){mode,call,current_round,result};
    vTaskDelay(pdMS_TO_TICKS(300));
}

void app_main(void) {
    // Let the host attach the console before the bounded test starts.
    vTaskDelay(pdMS_TO_TICKS(10000));
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT();
    config.nvs_enable = 0;
    ESP_ERROR_CHECK(esp_wifi_init(&config));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());
    ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
    ESP_ERROR_CHECK(esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE));
    const char *modes[] = {"broadcast_only", "unicast_only", "mixed"};
    for (int round = 0; round < 3; ++round) {
        current_round = round;
        for (int mode = 0; mode < 3; ++mode) {
            ESP_ERROR_CHECK(esp_now_init());
            if (mode != 1) add(broadcast);
            if (mode != 0) add(unicast);
            esp_now_peer_num_t peers;
            ESP_ERROR_CHECK(esp_now_get_peer_num(&peers));
            assert(peers.total_num == (mode==2 ? 2 : 1));
            probe(modes[mode], "null_before", NULL);
            if (mode != 1) probe(modes[mode], "explicit_broadcast", broadcast);
            if (mode != 0) probe(modes[mode], "explicit_unicast", unicast);
            probe(modes[mode], "null_after", NULL);
            ESP_ERROR_CHECK(esp_now_deinit());
        }
    }
    ESP_ERROR_CHECK(esp_wifi_stop());
    ESP_ERROR_CHECK(esp_wifi_deinit());
    // Separate the result dump from Wi-Fi initialization/deinitialization logs.
    vTaskDelay(pdMS_TO_TICKS(1000));
    assert(result_count==30);
    printf("SEND_START {\"idf\":\"%s\",\"nvs_enabled\":false}\n", esp_get_idf_version());
    fflush(stdout);
    vTaskDelay(pdMS_TO_TICKS(200));
    for (int i=0; i<result_count; ++i) {
        result_t *r=&results[i];
        printf("SEND_RESULT {\"mode\":\"%s\",\"call\":\"%s\",\"round\":%d,\"result\":%d,\"name\":\"%s\"}\n",
               r->mode,r->call,r->round,(int)r->result,esp_err_to_name(r->result));
        fflush(stdout);
        vTaskDelay(pdMS_TO_TICKS(200));
    }
    printf("SEND_DONE\n");
    fflush(stdout);
    // Keep a periodic completion marker for a late-attaching serial host.
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(10000));
        printf("SEND_IDLE\n");
        fflush(stdout);
    }
}
