#include "internal.h"
#include <openssl/crypto.h>
#include <stdio.h>
#include <string.h>

/* These control records are always inside authenticated inner TLS, including
 * when VPN packet data uses only the outer TLS layer. */
enum { PROBE=1, REPLY=2, ACTIVATE=3, ACTIVATED=4 };
uint64_t monotonic_ms(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC,&t);
    return (uint64_t)t.tv_sec*1000+(uint64_t)t.tv_nsec/1000000;
}
static int same_device(const peer *a,const peer *b) { return !strcmp(a->config.id,b->config.id); }
static void retire(peer *p) {
    p->retired=1; p->active=0;
    if (p->wsi) lws_set_timeout(p->wsi,PENDING_TIMEOUT_USER_OK,LWS_TO_KILL_ASYNC);
}
int pair_permitted(peer *p,int finished) {
    xpn *x=p->owner;
    for (unsigned i=0;i<XPN_MAX_PEERS;i++) {
        peer *other=x->peers[i];
        if (!other || other==p || !other->authenticated || other->retired || !same_device(p,other)) continue;
        /* A different process/device holding the same profile cannot steal a
         * live tunnel. Only the authenticated random pair ID may add a lane. */
        if (!p->redundant || !other->redundant || strcmp(p->pair_id,other->pair_id) ||
            p->inner_encryption!=other->inner_encryption || p->require_pq!=other->require_pq ||
            (p->slot==other->slot && p->generation<=other->generation)) return -1;
    }
    if (finished && p->redundant) for (unsigned i=0;i<XPN_MAX_PEERS;i++) {
        peer *other=x->peers[i];
        if (!other || other==p || !other->authenticated || other->retired || !same_device(p,other)) continue;
        if (other->activation>p->activation) p->activation=other->activation;
        /* Never evict until the replacement has proved possession of its PSK. */
        if (p->slot==other->slot) retire(other);
    }
    return 0;
}
int pair_authenticated(peer *p) {
    if (p->owner->server) return 0;
    atomic_fetch_add(&p->owner->ready_links,1);
    p->next_ping=monotonic_ms();
    fprintf(stderr,"XPN standby: lane %u authenticated\n",p->slot);
    return 0;
}
int pair_control(peer *p,unsigned char type,uint64_t value) {
    xpn *x=p->owner; uint64_t now=monotonic_ms();
    if (!p->redundant || !p->authenticated || p->retired || !value) return -1;
    if (x->server) {
        if (type==PROBE) return core_control(p,REPLY,value);
        if (type!=ACTIVATE) return -1;
        uint64_t latest=p->activation;
        for (unsigned i=0;i<XPN_MAX_PEERS;i++) {
            peer *other=x->peers[i];
            if (other && other->authenticated && !other->retired && same_device(p,other) && other->activation>latest) latest=other->activation;
        }
        if (value<=latest) return -1;
        for (unsigned i=0;i<XPN_MAX_PEERS;i++) {
            peer *other=x->peers[i];
            if (other && other->authenticated && !other->retired && same_device(p,other)) {
                other->active=0; other->activation=value;
            }
        }
        p->active=1; p->activation=value;
        return core_control(p,ACTIVATED,value);
    }
    if (type==REPLY) {
        if (!p->ping_sent || p->ping_sent!=value || now<value) return -1;
        p->rtt=now-value; p->last_pong=now; p->ping_sent=0;
        return 0;
    }
    if (type!=ACTIVATED || x->promoting!=p || value!=x->activation) return -1;
    peer *old=x->active;
    x->active=p; x->promoting=NULL; p->active=1; p->activation=value;
    x->last_switch=x->reported_ready ? now : 0; x->outage_since=0;
    if (old && old!=p) retire(old);
    if (x->reported_ready) atomic_fetch_add(&x->switch_count,1);
    fprintf(stderr,"XPN standby: lane %u active, epoch %llu\n",p->slot,(unsigned long long)value);
    if (!x->reported_ready) {
        x->reported_ready=1;
        if (x->cb.state) x->cb.state(x->cb.opaque,1,"Authenticated active/standby tunnel ready");
    }
    return 0;
}
int pair_should_switch(const peer *active,const peer *spare,uint64_t now,uint64_t last_switch) {
    if (!active || !spare || !spare->authenticated || spare->retired || !spare->last_pong ||
        now<spare->last_pong || now-spare->last_pong>1500 || spare->rtt>=500 ||
        now<last_switch || now-last_switch<5000) return 0;
    uint64_t latency=active->rtt;
    if (active->ping_sent && now>=active->ping_sent && now-active->ping_sent>latency) latency=now-active->ping_sent;
    return latency>=500 && spare->rtt+100<latency;
}
static int promote(xpn *x,peer *p,uint64_t now) {
    if (x->activation==UINT64_MAX) return -1;
    x->promoting=p; x->promotion_started=now; x->activation++;
    return core_control(p,ACTIVATE,x->activation);
}
int pair_tick(xpn *x,uint64_t now) {
    if (x->server || !x->redundant) return 0;
    if (x->promoting && now-x->promotion_started>=2000) {
        retire(x->promoting); x->promoting=NULL;
    }
    for (unsigned i=0;i<2;i++) {
        peer *p=x->links[i].peer;
        if (!p || !p->authenticated || p->retired) continue;
        if (!p->ping_sent && now>=p->next_ping) {
            p->ping_sent=now; p->next_ping=now+1000;
            if (core_control(p,PROBE,now)) retire(p);
        }
        /* Give a recovered active lane a chance to take over, but do not keep
         * an unresponsive standby or a dead active stream indefinitely. */
        if (p->ping_sent && now-p->ping_sent>=5000) {
            retire(p);
            if (x->active==p) x->active=NULL;
        }
    }
    if (x->active && x->active->retired) x->active=NULL;
    if (!x->active) {
        if (!x->outage_since) x->outage_since=now;
        if (now-x->outage_since>=10000) return -1;
        if (!x->promoting) for (unsigned i=0;i<2;i++) {
            peer *p=x->links[i].peer;
            if (p && p->authenticated && !p->retired) return promote(x,p,now);
        }
    } else if (!x->promoting) {
        peer *spare=x->links[1-x->active->slot].peer;
        if (pair_should_switch(x->active,spare,now,x->last_switch)) return promote(x,spare,now);
    }
    return 0;
}
void pair_closed(xpn *x,struct lws *wsi,uint64_t now) {
    for (unsigned i=0;i<2;i++) if (x->links[i].wsi==wsi) {
        struct client_link *link=&x->links[i]; peer *p=link->peer;
        if (p && p->authenticated) atomic_fetch_sub(&x->ready_links,1);
        if (p && x->active==p) { x->active=NULL; if (!x->outage_since) x->outage_since=now; }
        if (p && x->promoting==p) x->promoting=NULL;
        link->peer=NULL; link->wsi=NULL;
        if (link->failures<4) link->failures++;
        link->retry_at=now+(250U<<link->failures);
    }
}
