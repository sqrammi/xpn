#include "internal.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static const char *base="{\"version\":2,\"id\":\"00000000-0000-0000-0000-000000000001\",\"address\":\"10.77.0.2\",\"key\":\"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\",\"endpoint\":\"wss://vpn.example.test/xpn/vpn\",\"mode\":\"psk\",\"fullTunnel\":true,\"routes\":[],\"sni\":\"app.jeffhansen.com\",\"certificatePins\":[\"abababababababababababababababababababababababababababababababab\"]}";
static int parse(json_t *j, profile *p) {
    char *text=json_dumps(j,JSON_COMPACT); assert(text);
    int result=profile_parse(text,p); free(text); return result;
}
static X509 *certificate(EVP_PKEY *key,long before,long after,long serial) {
    X509 *cert=X509_new(); assert(cert);
    assert(X509_set_version(cert,2)); assert(ASN1_INTEGER_set(X509_get_serialNumber(cert),serial));
    assert(X509_gmtime_adj(X509_getm_notBefore(cert),before)); assert(X509_gmtime_adj(X509_getm_notAfter(cert),after));
    assert(X509_set_pubkey(cert,key));
    X509_NAME *name=X509_NAME_new(); assert(name);
    assert(X509_NAME_add_entry_by_txt(name,"CN",MBSTRING_ASC,(const unsigned char *)"unrelated.example.test",-1,-1,0));
    assert(X509_set_subject_name(cert,name)); assert(X509_set_issuer_name(cert,name)); X509_NAME_free(name);
    assert(X509_sign(cert,key,EVP_sha256())); return cert;
}
static void pin(profile *p, X509 *cert,unsigned index) {
    unsigned length; assert(X509_digest(cert,EVP_sha256(),p->certificate_pins[index],&length)); assert(length==32);
}
int main(void) {
    profile p; json_t *j=json_loads(base,0,NULL); assert(j && !parse(j,&p));
    assert(!strcmp(p.sni,"app.jeffhansen.com") && p.certificate_pin_count==1 && p.certificate_pins[0][0]==0xab);
    json_object_set_new(j,"version",json_integer(1)); assert(parse(j,&p)==-1);
    json_object_set_new(j,"version",json_real(2)); assert(parse(j,&p)==-1);
    json_object_set_new(j,"version",json_integer(3)); assert(parse(j,&p)==-1);
    json_object_set_new(j,"version",json_integer(2));
    const char *bad_sni[]={"app.test:443","https://app.test","127.0.0.1","::1","-app.test","app-.test","app..test","app.test.","*.test","a/b"};
    for(unsigned i=0;i<sizeof(bad_sni)/sizeof(*bad_sni);i++) { json_object_set_new(j,"sni",json_string(bad_sni[i])); assert(parse(j,&p)==-1); }
    json_object_set_new(j,"sni",json_stringn("app\0.test",9)); assert(parse(j,&p)==-1);
    json_object_set_new(j,"sni",json_string("")); assert(!parse(j,&p));
    json_object_set_new(j,"certificatePins",json_pack("[s]","not-a-fingerprint")); assert(parse(j,&p)==-1);
    json_object_set_new(j,"certificatePins",json_array()); assert(parse(j,&p)==-1);
    json_object_set_new(j,"version",json_integer(1)); assert(!parse(j,&p));
    json_decref(j);

    EVP_PKEY *key=EVP_PKEY_Q_keygen(NULL,NULL,"EC","prime256v1"); assert(key);
    X509 *valid=certificate(key,-60,3600,1), *replacement=certificate(key,-60,3600,2);
    X509 *expired=certificate(key,-3600,-60,3), *future=certificate(key,3600,7200,4);
    memset(&p,0,sizeof(p)); p.certificate_pin_count=1; pin(&p,valid,0);
    assert(certificate_matches(&p,valid)); assert(!certificate_matches(&p,replacement));
    assert(!certificate_matches(&p,NULL));
    p.certificate_pin_count=2; pin(&p,replacement,1); assert(certificate_matches(&p,replacement));
    pin(&p,expired,0); assert(!certificate_matches(&p,expired));
    pin(&p,future,0); assert(!certificate_matches(&p,future));
    p.certificate_pin_count=0; assert(!certificate_matches(&p,replacement));
    X509_free(valid); X509_free(replacement); X509_free(expired); X509_free(future); EVP_PKEY_free(key);
    puts("Profile downgrade prevention, exact certificate pinning, rotation and validity dates passed"); return 0;
}
