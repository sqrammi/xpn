#include "internal.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

static const char *json="{\"version\":1,\"id\":\"00000000-0000-0000-0000-000000000001\",\"address\":\"10.77.0.2\",\"key\":\"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\",\"endpoint\":\"wss://example.test/xpn/vpn\",\"mode\":\"psk\",\"fullTunnel\":false,\"routes\":[\"10.20.0.0/16\"]}";
static unsigned delivered;
static void receive_packet(void *unused,const unsigned char *packet,size_t length) {
    (void)unused; assert(length==20 && packet[15]==2); delivered++;
}
static SSL_CTX *context(void) {
    SSL_CTX *ctx=SSL_CTX_new(TLS_method()); assert(ctx);
    assert(SSL_CTX_set_min_proto_version(ctx,TLS1_3_VERSION));
    assert(SSL_CTX_set_max_proto_version(ctx,TLS1_3_VERSION));
    assert(SSL_CTX_set_ciphersuites(ctx,"TLS_CHACHA20_POLY1305_SHA256"));
    assert(SSL_CTX_set1_groups_list(ctx,"X25519")); SSL_CTX_set_num_tickets(ctx,0);
    return ctx;
}
static int fragments(peer *to,const unsigned char *bytes,size_t size) {
    for (size_t i=0;i<size;i++) if (core_receive_wire(to,bytes+i,1)) return -1;
    return 0;
}
static int transfer(peer *from,peer *to) {
    unsigned char buffer[16387]; int length;
    while ((length=BIO_read(SSL_get_wbio(from->ssl),buffer+3,16384))>0) {
        buffer[0]=0; buffer[1]=(unsigned char)(length>>8); buffer[2]=(unsigned char)length;
        if (fragments(to,buffer,(size_t)length+3)) return -1;
    }
    while ((length=core_read_plain_output(from,buffer,sizeof(buffer)))>0)
        if (fragments(to,buffer,(size_t)length)) return -1;
    return length<0 ? -1 : 0;
}
static void reject_replacement(peer *original,int wrong_key) {
    xpn client={0}; peer a={.owner=&client,.wire_v2=1,.redundant=1,.generation=2},b={.owner=original->owner,.wire_v2=1,.redundant=1};
    assert(!pthread_mutex_init(&client.lock,NULL));
    atomic_init(&client.ready_links,0);
    assert(!profile_parse(json,&client.config));
    client.inner_encryption=original->inner_encryption;
    if (wrong_key) client.config.key[0]^=1;
    strcpy(a.pair_id,wrong_key ? original->pair_id : "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb");
    client.tls=context(); client.peers[0]=&a; original->owner->peers[1]=&b;
    assert(!core_init(&a) && !core_init(&b)); assert(!core_receive(&a,NULL,0));
    int rejected=0;
    for (unsigned i=0;i<10 && !rejected;i++) rejected=transfer(&a,&b) || transfer(&b,&a);
    assert(rejected && !b.authenticated && original->active && !original->retired);
    original->owner->peers[1]=NULL;
    core_free(&a); core_free(&b); SSL_CTX_free(client.tls); pthread_mutex_destroy(&client.lock);
}
static void test(int inner,int require_hybrid,int redundant) {
    xpn client={0},server={0}; peer a={.owner=&client,.wire_v2=1},b={.owner=&server,.wire_v2=1};
    a.redundant=b.redundant=redundant;
    a.generation=1; strcpy(a.pair_id,"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
    atomic_init(&client.ready_links,0); atomic_init(&client.switch_count,0);
    assert(!pthread_mutex_init(&client.lock,NULL) && !pthread_mutex_init(&server.lock,NULL));
    assert(!profile_parse(json,&client.config));
    client.wire_v2=1; client.inner_encryption=inner;
    server.server=1; server.cached[0]=client.config; server.cached[0].hybrid=require_hybrid; server.cached_count=1;
    client.tls=context(); server.tls=context(); server.cb.packet=receive_packet;
    client.peers[0]=&a; server.peers[0]=&b;
    assert(!core_init(&a) && !core_init(&b));
    unsigned char packet[20]={0x45,0,0,20}; packet[12]=10; packet[13]=77; packet[15]=2; packet[16]=10; packet[17]=20; packet[19]=1;
    unsigned char raw[23]={1,0,20}; memcpy(raw+3,packet,20);
    assert(core_receive_wire(&b,raw,sizeof(raw))==-1); b.wire_have=0; /* pre-authentication injection */
    unsigned char invalid[3]={0,0,0};
    assert(core_receive_wire(&b,invalid,sizeof(invalid))==-1); b.wire_have=0;
    assert(!core_receive(&a,NULL,0));
    if (require_hybrid) {
        assert(transfer(&a,&b)==-1); assert(!b.authenticated);
    } else {
        for (unsigned i=0;i<10 && (!a.authenticated || !b.authenticated);i++) {
            assert(!transfer(&a,&b)); assert(!transfer(&b,&a));
        }
        assert(a.authenticated && b.authenticated && b.inner_encryption==inner);
        if (redundant) {
            assert(!a.active && !b.active);
            client.promoting=&a; client.activation=1;
            assert(!core_control(&a,3,1)); assert(!transfer(&a,&b)); assert(!transfer(&b,&a));
            assert(a.active && b.active && client.active==&a);
            reject_replacement(&b,1); reject_replacement(&b,0);
        }
        assert(!core_send(&a,packet,sizeof(packet)));
        if (inner) assert(BIO_ctrl_pending(a.plain_output)==0);
        else {
            char *bytes=NULL; assert(BIO_get_mem_data(a.plain_output,&bytes)==23);
            assert(!memcmp(bytes,raw,23)); /* no inner ciphertext for VPN packets */
        }
        unsigned before=delivered; assert(!transfer(&a,&b)); assert(delivered==before+1);
        if (!inner) {
            /* A full output batch followed by a KeyUpdate must not splice TLS
             * into a raw packet, even when 16384 is not a record-size multiple. */
            for (unsigned i=0;i<1000;i++) assert(!core_send(&a,packet,sizeof(packet)));
            unsigned char batch[16384]; int count=core_read_plain_output(&a,batch,sizeof(batch));
            assert(count>0 && count<16384 && count%23==0);
            before=delivered; assert(!fragments(&b,batch,(size_t)count));
            assert(!b.wire_have);
            assert(SSL_key_update(a.ssl,SSL_KEY_UPDATE_REQUESTED));
            assert(SSL_do_handshake(a.ssl)==1);
            assert(!transfer(&a,&b)); assert(delivered==before+1000);
            assert(!transfer(&b,&a));
        }
        if (inner) assert(core_receive_wire(&b,raw,sizeof(raw))==-1);
        else { raw[18]=3; assert(core_receive_wire(&b,raw,sizeof(raw))==-1); } /* source spoof */
    }
    core_free(&a); core_free(&b); SSL_CTX_free(client.tls); SSL_CTX_free(server.tls);
    pthread_mutex_destroy(&client.lock); pthread_mutex_destroy(&server.lock);
}
int main(void) {
    assert(!xpn_global_init()); test(0,0,0); test(1,0,0); test(0,1,0); test(1,1,0); test(0,0,1); test(1,0,1);
    puts("PASS: authenticated mode binding, single/double packet encryption, fragmentation, spoof/pre-auth rejection and policy minimums");
}
