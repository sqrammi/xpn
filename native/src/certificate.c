#include "internal.h"
#include <openssl/crypto.h>
#include <time.h>

/* Pins identify the exact leaf certificate DER, not an issuer or a name. TLS
 * still proves possession of its private key. Certificate validity dates are
 * enforced independently of the CA/hostname verification result. */
int certificate_matches(const profile *config, X509 *leaf) {
    if (!leaf || !config->certificate_pin_count || config->certificate_pin_count>XPN_MAX_CERTIFICATE_PINS) return 0;
    ASN1_TIME *now=ASN1_TIME_set(NULL,time(NULL)); if (!now) return 0;
    int before=ASN1_TIME_compare(X509_get0_notBefore(leaf),now);
    int after=ASN1_TIME_compare(X509_get0_notAfter(leaf),now);
    ASN1_TIME_free(now);
    if (before==-2 || before>0 || after<=0) return 0;
    unsigned char digest[EVP_MAX_MD_SIZE]; unsigned int length=0;
    if (!X509_digest(leaf,EVP_sha256(),digest,&length) || length!=32) return 0;
    int matched=0;
    for (unsigned i=0;i<config->certificate_pin_count;i++) matched |= CRYPTO_memcmp(digest,config->certificate_pins[i],32)==0;
    return matched;
}
