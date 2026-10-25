#include "internal.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/* No root, TUN, nginx, or real network is needed. These tests run in native CI. */
static const char *json="{\"version\":1,\"id\":\"00000000-0000-0000-0000-000000000001\",\"address\":\"10.77.0.2\",\"key\":\"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\",\"endpoint\":\"wss://example.test/xpn/vpn\",\"mode\":\"psk\",\"fullTunnel\":false,\"routes\":[\"10.20.0.0/16\"]}";
static unsigned delivered;
static void receive_packet(void *opaque,const unsigned char *data,size_t length) { (void)opaque; (void)data; assert(length==20); delivered++; }
static void transfer(peer *from,peer *to) {
    unsigned char data[16384]; int n;
    while((n=BIO_read(SSL_get_wbio(from->ssl),data,sizeof(data)))>0) assert(core_receive(to,data,(size_t)n)==0);
}
static void handshake(int wrong) {
    xpn client={0},server={0}; peer a={.owner=&client},b={.owner=&server};
    assert(pthread_mutex_init(&client.lock,NULL)==0); assert(pthread_mutex_init(&server.lock,NULL)==0);
    server.server=1; assert(profile_parse(json,&client.config)==0); server.cached[0]=client.config; server.cached_count=1;
    if(wrong) server.cached[0].key[0]^=1;
    server.cb.packet=receive_packet;
    client.tls=SSL_CTX_new(TLS_method()); server.tls=SSL_CTX_new(TLS_method()); assert(client.tls&&server.tls);
    assert(SSL_CTX_set_min_proto_version(client.tls,TLS1_3_VERSION)); assert(SSL_CTX_set_min_proto_version(server.tls,TLS1_3_VERSION));
    assert(SSL_CTX_set_max_proto_version(client.tls,TLS1_3_VERSION)); assert(SSL_CTX_set_max_proto_version(server.tls,TLS1_3_VERSION));
    assert(SSL_CTX_set_ciphersuites(client.tls,"TLS_CHACHA20_POLY1305_SHA256")); assert(SSL_CTX_set_ciphersuites(server.tls,"TLS_CHACHA20_POLY1305_SHA256"));
    assert(SSL_CTX_set1_groups_list(server.tls,"X25519")); SSL_CTX_set_num_tickets(server.tls,0);
    client.peers[0]=&a; server.peers[0]=&b;
    assert(core_init(&a)==0&&core_init(&b)==0); assert(core_receive(&a,NULL,0)==0);
    if(wrong) {
        unsigned char data[16384]; int n=BIO_read(SSL_get_wbio(a.ssl),data,sizeof(data)); assert(n>0); assert(core_receive(&b,data,(size_t)n)==-1); assert(!b.authenticated);
    } else {
        for(unsigned i=0;i<10 && (!a.authenticated||!b.authenticated);i++) { transfer(&a,&b); transfer(&b,&a); }
        assert(a.authenticated&&b.authenticated);
        unsigned char packet[20]={0x45,0,0,20}; packet[12]=10;packet[13]=77;packet[15]=2;packet[16]=10;packet[17]=20;packet[19]=1;
        assert(core_send(&a,packet,sizeof(packet))==0); transfer(&a,&b); assert(delivered==1);
        packet[15]=3; assert(core_send(&a,packet,sizeof(packet))==0);
        unsigned char cipher[16384]; int n=BIO_read(SSL_get_wbio(a.ssl),cipher,sizeof(cipher)); assert(n>0); assert(core_receive(&b,cipher,(size_t)n)==-1);
    }
    core_free(&a);core_free(&b);SSL_CTX_free(client.tls);SSL_CTX_free(server.tls);pthread_mutex_destroy(&client.lock);pthread_mutex_destroy(&server.lock);
}
int main(void) {
    assert(xpn_global_init()==0);
    profile p; assert(profile_parse(json,&p)==0);
    unsigned char packet[20]={0x45,0,0,20}; packet[12]=10;packet[13]=77;packet[15]=2;packet[16]=10;packet[17]=20;packet[19]=1;
    assert(packet_allowed(&p,packet,20)); packet[17]=21;assert(!packet_allowed(&p,packet,20)); packet[17]=20;packet[15]=3;assert(!packet_allowed(&p,packet,20));
    assert(!packet_allowed(&p,packet,19));
    assert(profile_parse("{}",&p)==-1);
    handshake(0); handshake(1); puts("PSK mutual authentication, packet framing, spoof prevention and routing passed"); return 0;
}
