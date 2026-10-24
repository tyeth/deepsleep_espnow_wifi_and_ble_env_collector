/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/ztest.h>
#include <psa/crypto.h>
#include <mbedtls/ssl.h>

static psa_status_t agreement(uint8_t *output, size_t capacity, size_t *used)
{
	psa_key_attributes_t attr = PSA_KEY_ATTRIBUTES_INIT;
	mbedtls_svc_key_id_t key = MBEDTLS_SVC_KEY_ID_INIT;
	uint8_t public_key[65];
	size_t public_size;
	psa_status_t result;

	zassert_equal(psa_crypto_init(), PSA_SUCCESS);
	psa_set_key_usage_flags(&attr, PSA_KEY_USAGE_DERIVE | PSA_KEY_USAGE_EXPORT);
	psa_set_key_algorithm(&attr, PSA_ALG_ECDH);
	psa_set_key_type(&attr, PSA_KEY_TYPE_ECC_KEY_PAIR(PSA_ECC_FAMILY_SECP_R1));
	psa_set_key_bits(&attr, 256);
	zassert_equal(psa_generate_key(&attr, &key), PSA_SUCCESS);
	psa_reset_key_attributes(&attr);
	zassert_equal(psa_export_public_key(key, public_key, sizeof(public_key), &public_size),
		      PSA_SUCCESS);
	result = psa_raw_key_agreement(PSA_ALG_ECDH, key, public_key, public_size,
				       output, capacity, used);
	zassert_equal(psa_destroy_key(key), PSA_SUCCESS);
	return result;
}

ZTEST(p256_premaster, test_control_full_p256_output)
{
	uint8_t output[32];
	size_t used = 0;
	psa_status_t result = agreement(output, sizeof(output), &used);

	printk("CONTROL capacity=%zu status=%d used=%zu\n", sizeof(output), result, used);
	zassert_equal(result, PSA_SUCCESS);
	zassert_equal(used, 32);
}

ZTEST(p256_premaster, test_tls_premaster_capacity)
{
	uint8_t output[MBEDTLS_PREMASTER_SIZE];
	size_t used = 0;
	psa_status_t result = agreement(output, sizeof(output), &used);

	printk("TLS_PREMASTER p256m=%d ecp_max_bits=%d capacity=%zu status=%d used=%zu\n",
	       IS_ENABLED(CONFIG_MBEDTLS_PSA_P256M_DRIVER_ENABLED),
	       MBEDTLS_ECP_MAX_BITS, sizeof(output), result, used);
	zassert_equal(result, PSA_SUCCESS, "TLS premaster cannot hold a valid P-256 agreement");
	zassert_equal(used, 32);
}

ZTEST_SUITE(p256_premaster, NULL, NULL, NULL, NULL, NULL);
