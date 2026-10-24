// Generated from actual CircuitPython source, without rewriting the policy.
static int policy_baseline(policy_context *self, endpoint *o, bool server_side) {
    int ret = mbedtls_ssl_config_defaults(&o->conf,
        server_side ? MBEDTLS_SSL_IS_SERVER : MBEDTLS_SSL_IS_CLIENT,
        MBEDTLS_SSL_TRANSPORT_STREAM,
        MBEDTLS_SSL_PRESET_DEFAULT);
    if (ret != 0) {
        goto cleanup;
    }

    if (self->crt_bundle_attach != NULL) {
        mbedtls_ssl_conf_authmode(&o->conf, MBEDTLS_SSL_VERIFY_REQUIRED);
        self->crt_bundle_attach(&o->conf);
    } else if (self->cacert_buf && self->cacert_bytes) {
        ret = mbedtls_x509_crt_parse(&o->cacert, self->cacert_buf, self->cacert_bytes);
        if (ret != 0) {
            goto cleanup;
        }
        mbedtls_ssl_conf_authmode(&o->conf, MBEDTLS_SSL_VERIFY_REQUIRED);
        mbedtls_ssl_conf_ca_chain(&o->conf, &o->cacert, NULL);

    } else {
        mbedtls_ssl_conf_authmode(&o->conf, MBEDTLS_SSL_VERIFY_NONE);
    }

cleanup:
    return ret;
}

static int policy_fixed(policy_context *self, endpoint *o, bool server_side) {
    int ret = mbedtls_ssl_config_defaults(&o->conf,
        server_side ? MBEDTLS_SSL_IS_SERVER : MBEDTLS_SSL_IS_CLIENT,
        MBEDTLS_SSL_TRANSPORT_STREAM,
        MBEDTLS_SSL_PRESET_DEFAULT);
    if (ret != 0) {
        goto cleanup;
    }

    if (server_side && !(self->cacert_buf && self->cacert_bytes)) {
        // On a server the CA store is about authenticating *clients*. A
        // context that only had load_cert_chain() called on it -- the normal
        // HTTPS-server setup -- must not demand a client certificate, which is
        // what the default root bundle turned into: every handshake failed
        // with MBEDTLS_ERR_SSL_NO_CLIENT_CERTIFICATE. Match CPython, where a
        // server-side context defaults to CERT_NONE; a program that loads its
        // own CA with load_verify_locations() still gets client verification.
        mbedtls_ssl_conf_authmode(&o->conf, MBEDTLS_SSL_VERIFY_NONE);
    } else if (self->crt_bundle_attach != NULL) {
        mbedtls_ssl_conf_authmode(&o->conf, MBEDTLS_SSL_VERIFY_REQUIRED);
        self->crt_bundle_attach(&o->conf);
    } else if (self->cacert_buf && self->cacert_bytes) {
        ret = mbedtls_x509_crt_parse(&o->cacert, self->cacert_buf, self->cacert_bytes);
        if (ret != 0) {
            goto cleanup;
        }
        mbedtls_ssl_conf_authmode(&o->conf, MBEDTLS_SSL_VERIFY_REQUIRED);
        mbedtls_ssl_conf_ca_chain(&o->conf, &o->cacert, NULL);

    } else {
        mbedtls_ssl_conf_authmode(&o->conf, MBEDTLS_SSL_VERIFY_NONE);
    }

cleanup:
    return ret;
}
