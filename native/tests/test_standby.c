#include "internal.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <unistd.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>

static void keepalive(void) {
    int fd=socket(AF_INET,SOCK_STREAM,0); assert(fd>=0);
    assert(!socket_keepalive(fd));
    int value=0; socklen_t size=sizeof(value);
    /* Darwin may return the option bit (8), Linux returns 1; both mean on. */
    assert(!getsockopt(fd,SOL_SOCKET,SO_KEEPALIVE,&value,&size) && value!=0);
#ifdef __APPLE__
    int idle=TCP_KEEPALIVE;
#else
    int idle=TCP_KEEPIDLE;
#endif
    assert(!getsockopt(fd,IPPROTO_TCP,idle,&value,&size) && value==15);
    assert(!getsockopt(fd,IPPROTO_TCP,TCP_KEEPINTVL,&value,&size) && value==15);
    assert(!getsockopt(fd,IPPROTO_TCP,TCP_KEEPCNT,&value,&size) && value==3);
    close(fd);
}
static void association(void) {
    xpn server={.server=1};
    peer old={.owner=&server,.redundant=1,.authenticated=1,.active=1,.inner_encryption=1,.generation=1};
    peer spare=old; spare.authenticated=0; spare.active=0; spare.slot=1; spare.generation=2;
    strcpy(old.config.id,"00000000-0000-0000-0000-000000000001"); strcpy(spare.config.id,old.config.id);
    memset(old.pair_id,'a',32); old.pair_id[32]=0; strcpy(spare.pair_id,old.pair_id);
    server.peers[0]=&old; server.peers[1]=&spare;
    assert(!pair_permitted(&spare,0) && !old.retired && old.active);
    spare.pair_id[0]='b'; assert(pair_permitted(&spare,0)==-1); spare.pair_id[0]='a';
    spare.inner_encryption=0; assert(pair_permitted(&spare,0)==-1); spare.inner_encryption=1;
    spare.require_pq=1; assert(pair_permitted(&spare,0)==-1); spare.require_pq=0;
    spare.redundant=0; assert(pair_permitted(&spare,0)==-1); spare.redundant=1;
    spare.slot=0; spare.generation=1; assert(pair_permitted(&spare,0)==-1);
    spare.generation=2;
    assert(!pair_permitted(&spare,0) && !old.retired && old.active);
    /* Replacement may retire the old lane only after Finished was verified. */
    assert(!pair_permitted(&spare,1) && old.retired && !old.active);
}
static void threshold(void) {
    peer active={.authenticated=1,.rtt=499};
    peer spare={.authenticated=1,.rtt=40,.last_pong=9900};
    assert(!pair_should_switch(&active,&spare,10000,0));
    active.rtt=500; assert(pair_should_switch(&active,&spare,10000,0));
    spare.rtt=450; assert(!pair_should_switch(&active,&spare,10000,0));
    spare.rtt=40; spare.last_pong=8000; assert(!pair_should_switch(&active,&spare,10000,0));
    spare.last_pong=9900; assert(!pair_should_switch(&active,&spare,10000,6000));
    active.rtt=40; active.ping_sent=9500; assert(pair_should_switch(&active,&spare,10000,0));
    spare.authenticated=0; assert(!pair_should_switch(&active,&spare,10000,0));
}
int main(void) {
    keepalive(); association(); threshold();
    puts("PASS: actual TCP 15-second keepalives, authenticated pair association, no pre-auth eviction, 500ms threshold and anti-flapping policy");
}
