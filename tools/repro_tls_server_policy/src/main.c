// SPDX-License-Identifier: MIT
#include <zephyr/ztest.h>
#include <mbedtls/ssl.h>
#include <mbedtls/x509_crt.h>
#include <mbedtls/pk.h>
#include <psa/crypto.h>
#include <string.h>
#include "credentials.h"

typedef struct {
    mbedtls_ssl_context ssl;
    mbedtls_ssl_config conf;
    mbedtls_x509_crt cacert;
    mbedtls_x509_crt cert;
    mbedtls_pk_context key;
} endpoint;
typedef struct {
    int (*crt_bundle_attach)(mbedtls_ssl_config *);
    const unsigned char *cacert_buf;
    size_t cacert_bytes;
} policy_context;
#include "policy.h"

static mbedtls_x509_crt roots;
static int attach_test_roots(mbedtls_ssl_config *conf) {
    mbedtls_ssl_conf_ca_chain(conf, &roots, NULL);
    return 0;
}
typedef struct { unsigned char data[65536]; size_t used; } queue;
typedef struct { queue *in; queue *out; } transport;
static queue c2s, s2c;
static int send_bytes(void *ctx, const unsigned char *data, size_t len) {
    transport *t = ctx;
    if (len > sizeof(t->out->data) - t->out->used) return MBEDTLS_ERR_SSL_WANT_WRITE;
    memcpy(t->out->data + t->out->used, data, len);
    t->out->used += len;
    return (int)len;
}
static int recv_bytes(void *ctx, unsigned char *data, size_t len) {
    transport *t = ctx;
    if (!t->in->used) return MBEDTLS_ERR_SSL_WANT_READ;
    len = MIN(len, t->in->used);
    memcpy(data, t->in->data, len);
    t->in->used -= len;
    memmove(t->in->data, t->in->data + len, t->in->used);
    return (int)len;
}
static void init_endpoint(endpoint *e) {
    memset(e, 0, sizeof(*e));
    mbedtls_ssl_init(&e->ssl);
    mbedtls_ssl_config_init(&e->conf);
    mbedtls_x509_crt_init(&e->cacert);
    mbedtls_x509_crt_init(&e->cert);
    mbedtls_pk_init(&e->key);
}
static void free_endpoint(endpoint *e) {
    mbedtls_ssl_free(&e->ssl);
    mbedtls_ssl_config_free(&e->conf);
    mbedtls_x509_crt_free(&e->cacert);
    mbedtls_x509_crt_free(&e->cert);
    mbedtls_pk_free(&e->key);
}
static void own_cert(endpoint *e, bool trusted) {
    const unsigned char *cert = trusted ? trusted_cert : untrusted_cert;
    const unsigned char *key = trusted ? trusted_key : untrusted_key;
    zassert_equal(mbedtls_x509_crt_parse(&e->cert, cert, strlen((const char *)cert) + 1), 0);
    zassert_equal(mbedtls_pk_parse_key(&e->key, key, strlen((const char *)key) + 1, NULL, 0), 0);
    zassert_equal(mbedtls_ssl_conf_own_cert(&e->conf, &e->cert, &e->key), 0);
}
static bool pending(int ret) {
    return ret == MBEDTLS_ERR_SSL_WANT_READ || ret == MBEDTLS_ERR_SSL_WANT_WRITE;
}
typedef struct { int server; int client; } result;
// CA mode: 0 default bundle, 1 explicit CA, 2 no CA.
static result handshake(bool fixed, int ca_mode, bool client_cert, bool trusted_client,
    bool trusted_server, const char *hostname) {
    endpoint server, client;
    init_endpoint(&server);
    init_endpoint(&client);
    zassert_equal(psa_crypto_init(), PSA_SUCCESS);
    mbedtls_x509_crt_init(&roots);
    zassert_equal(mbedtls_x509_crt_parse(&roots, trusted_cert, sizeof(trusted_cert)), 0);
    policy_context sp = {0}, cp = {.crt_bundle_attach = attach_test_roots};
    if (ca_mode == 0) sp.crt_bundle_attach = attach_test_roots;
    if (ca_mode == 1) { sp.cacert_buf = trusted_cert; sp.cacert_bytes = sizeof(trusted_cert); }
    int (*policy)(policy_context *, endpoint *, bool) = fixed ? policy_fixed : policy_baseline;
    zassert_equal(policy(&sp, &server, true), 0);
    zassert_equal(policy(&cp, &client, false), 0);
    own_cert(&server, trusted_server);
    if (client_cert) own_cert(&client, trusted_client);
    zassert_equal(mbedtls_ssl_setup(&server.ssl, &server.conf), 0);
    zassert_equal(mbedtls_ssl_setup(&client.ssl, &client.conf), 0);
    zassert_equal(mbedtls_ssl_set_hostname(&client.ssl, hostname), 0);
    c2s.used = s2c.used = 0;
    transport st = {.in=&c2s, .out=&s2c}, ct = {.in=&s2c, .out=&c2s};
    mbedtls_ssl_set_bio(&server.ssl, &st, send_bytes, recv_bytes, NULL);
    mbedtls_ssl_set_bio(&client.ssl, &ct, send_bytes, recv_bytes, NULL);
    result r = {MBEDTLS_ERR_SSL_WANT_READ, MBEDTLS_ERR_SSL_WANT_READ};
    for (int i = 0; i < 1000; ++i) {
        if (pending(r.client)) r.client = mbedtls_ssl_handshake(&client.ssl);
        if (pending(r.server)) r.server = mbedtls_ssl_handshake(&server.ssl);
        if ((!r.server && !r.client) || (r.server && !pending(r.server)) || (r.client && !pending(r.client))) break;
    }
    if (!r.server && !r.client) {
        const unsigned char request[] = "GET / HTTP/1.0\r\n\r\n";
        unsigned char received[sizeof(request)] = {0};
        zassert_equal(mbedtls_ssl_write(&client.ssl, request, sizeof(request)), sizeof(request));
        zassert_equal(mbedtls_ssl_read(&server.ssl, received, sizeof(received)), sizeof(request));
        zassert_mem_equal(request, received, sizeof(request));
    }
    printk("POLICY fixed=%d ca_mode=%d client_cert=%d trusted_client=%d trusted_server=%d hostname=%s server=%d client=%d\n", fixed, ca_mode, client_cert, trusted_client, trusted_server, hostname, r.server, r.client);
    free_endpoint(&server);
    free_endpoint(&client);
    mbedtls_x509_crt_free(&roots);
    return r;
}
#define NAME "envhub-test.invalid"
ZTEST(policy, test_baseline_default_demands_client) {
    result r = handshake(false, 0, false, true, true, NAME);
    zassert_equal(r.server, MBEDTLS_ERR_SSL_NO_CLIENT_CERTIFICATE);
}
ZTEST(policy, test_fixed_default_accepts_no_client) {
    result r = handshake(true, 0, false, true, true, NAME);
    zassert_equal(r.server, 0); zassert_equal(r.client, 0);
}
ZTEST(policy, test_explicit_ca_requires_client) {
    for (int fixed=0; fixed<2; ++fixed) {
        result r = handshake(fixed, 1, false, true, true, NAME);
        zassert_equal(r.server, MBEDTLS_ERR_SSL_NO_CLIENT_CERTIFICATE);
    }
}
ZTEST(policy, test_explicit_ca_accepts_trusted_client) {
    for (int fixed=0; fixed<2; ++fixed) {
        result r = handshake(fixed, 1, true, true, true, NAME);
        zassert_equal(r.server, 0); zassert_equal(r.client, 0);
    }
}
ZTEST(policy, test_explicit_ca_rejects_untrusted_client) {
    for (int fixed=0; fixed<2; ++fixed) {
        result r = handshake(fixed, 1, true, false, true, NAME);
        zassert_equal(r.server, MBEDTLS_ERR_X509_CERT_VERIFY_FAILED);
    }
}
ZTEST(policy, test_no_ca_accepts_no_client) {
    for (int fixed=0; fixed<2; ++fixed) {
        result r = handshake(fixed, 2, false, true, true, NAME);
        zassert_equal(r.server, 0); zassert_equal(r.client, 0);
    }
}
ZTEST(policy, test_client_rejects_wrong_hostname) {
    for (int fixed=0; fixed<2; ++fixed) {
        result r = handshake(fixed, 2, false, true, true, "wrong.invalid");
        zassert_equal(r.client, MBEDTLS_ERR_X509_CERT_VERIFY_FAILED);
    }
}
ZTEST(policy, test_client_rejects_untrusted_server) {
    for (int fixed=0; fixed<2; ++fixed) {
        result r = handshake(fixed, 2, false, true, false, NAME);
        zassert_equal(r.client, MBEDTLS_ERR_X509_CERT_VERIFY_FAILED);
    }
}
ZTEST_SUITE(policy, NULL, NULL, NULL, NULL, NULL);
