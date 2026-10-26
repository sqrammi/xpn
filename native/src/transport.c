#include "internal.h"
#include <arpa/inet.h>
#include <curl/curl.h>
#include <openssl/crypto.h>
#include <openssl/err.h>
#include <openssl/rand.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <netdb.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <time.h>

static const struct lws_protocols protocols[] = {
    { "xpn-v1", xpn_callback, sizeof(peer), 16384, 0, NULL, 0 },
    { "xpn-v2", xpn_callback, sizeof(peer), 16384, 0, NULL, 0 },
    { "xpn-v3", xpn_callback, sizeof(peer), 16384, 0, NULL, 0 },
    { NULL, NULL, 0, 0, 0, NULL, 0 }
};
int socket_keepalive(int fd) {
    int on=1,seconds=XPN_KEEPALIVE_SECONDS,count=3;
    if (setsockopt(fd,SOL_SOCKET,SO_KEEPALIVE,&on,sizeof(on))) return -1;
#ifdef __APPLE__
    if (setsockopt(fd,IPPROTO_TCP,TCP_KEEPALIVE,&seconds,sizeof(seconds))) return -1;
#else
    if (setsockopt(fd,IPPROTO_TCP,TCP_KEEPIDLE,&seconds,sizeof(seconds))) return -1;
#endif
    return setsockopt(fd,IPPROTO_TCP,TCP_KEEPINTVL,&seconds,sizeof(seconds)) ||
        setsockopt(fd,IPPROTO_TCP,TCP_KEEPCNT,&count,sizeof(count)) ? -1 : 0;
}
int lookup_profile(xpn *x, const char *id, profile *out) {
    int result=-1; pthread_mutex_lock(&x->lock);
    for (size_t i=0;i<x->cached_count;i++) if (!strcmp(id,x->cached[i].id)) { *out=x->cached[i]; result=0; break; }
    pthread_mutex_unlock(&x->lock); return result;
}
static void refresh(xpn *x) {
    char *text=control_get(x->control,NULL); json_t *rows=text ? json_loads(text,JSON_REJECT_DUPLICATES,NULL) : NULL;
    profile *next=calloc(XPN_MAX_PEERS,sizeof(profile)); size_t count=0;
    if (!next) {
        pthread_mutex_lock(&x->lock); x->cached_count=0; OPENSSL_cleanse(x->cached,sizeof(x->cached)); pthread_mutex_unlock(&x->lock);
        if (rows) json_decref(rows);
        xpn_free(text); return;
    }
    if (json_is_array(rows) && json_array_size(rows)<XPN_MAX_PEERS) {
        for (size_t i=0;i<json_array_size(rows);i++) {
            char *row=json_dumps(json_array_get(rows,i),JSON_COMPACT);
            if (!row || profile_parse(row,&next[count])) { free(row); count=0; break; }
            xpn_free(row); count++;
        }
    }
    pthread_mutex_lock(&x->lock);
    OPENSSL_cleanse(x->cached,sizeof(x->cached)); memcpy(x->cached,next,count*sizeof(profile)); x->cached_count=count;
    pthread_mutex_unlock(&x->lock);
    OPENSSL_cleanse(next,XPN_MAX_PEERS*sizeof(profile)); free(next);
    if (rows) json_decref(rows);
    xpn_free(text);
}
static void *watch(void *arg) {
    xpn *x=arg;
    while (!atomic_load(&x->stop)) {
        refresh(x);
        struct timespec delay={0,100000000};
        for (unsigned i=0;i<10 && !atomic_load(&x->stop);i++) nanosleep(&delay,NULL);
    }
    return NULL;
}
static xpn *allocate(xpn_callbacks cb) {
    xpn *x=calloc(1,sizeof(*x)); if (!x) return NULL;
    x->cb=cb; atomic_init(&x->stop,0); atomic_init(&x->ready_links,0); atomic_init(&x->switch_count,0);
    if (pthread_mutex_init(&x->lock,NULL)) { free(x); return NULL; }
    x->queue=calloc(XPN_QUEUE,sizeof(struct queued));
    x->tls=SSL_CTX_new(TLS_method());
    if (!x->queue || !x->tls || !SSL_CTX_set_min_proto_version(x->tls,TLS1_3_VERSION) || !SSL_CTX_set_max_proto_version(x->tls,TLS1_3_VERSION) || !SSL_CTX_set_ciphersuites(x->tls,"TLS_CHACHA20_POLY1305_SHA256")) { xpn_destroy(x); return NULL; }
    SSL_CTX_set_options(x->tls,SSL_OP_NO_TICKET|SSL_OP_NO_COMPRESSION|SSL_OP_NO_RENEGOTIATION);
    SSL_CTX_clear_options(x->tls,SSL_OP_ALLOW_NO_DHE_KEX);
    SSL_CTX_set_num_tickets(x->tls,0); SSL_CTX_set_max_early_data(x->tls,0);
    SSL_CTX_set_session_cache_mode(x->tls,SSL_SESS_CACHE_OFF);
    return x;
}
static int context(xpn *x) {
    struct lws_context_creation_info info; memset(&info,0,sizeof(info));
    info.port=x->server ? x->port : CONTEXT_PORT_NO_LISTEN;
    info.iface=x->server ? "127.0.0.1" : NULL;
    info.protocols=protocols; info.user=x; info.options=LWS_SERVER_OPTION_DO_SSL_GLOBAL_INIT;
    /* Every new connection must present a certificate for the configured pin. */
    info.options |= LWS_SERVER_OPTION_DISABLE_TLS_SESSION_CACHE;
    if (!x->server) info.ssl_info_event_mask=SSL_CB_HANDSHAKE_START;
#ifdef __linux__
    /* Linux launcher installs IPv4 endpoint exceptions before full routes. */
    info.options |= LWS_SERVER_OPTION_DISABLE_IPV6;
#endif
    if (*xpn_ca_file) info.client_ssl_ca_filepath=xpn_ca_file;
    info.fd_limit_per_thread=1024;
    info.ka_time=XPN_KEEPALIVE_SECONDS; info.ka_probes=3; info.ka_interval=XPN_KEEPALIVE_SECONDS;
    x->context=lws_create_context(&info);
    return x->context ? 0 : -1;
}
xpn *xpn_server_new(int port, const char *socket, const char *path, xpn_callbacks cb) {
    if (port<1 || port>65535 || !socket || strlen(socket)>=1024 || !path || path[0]!='/' || strlen(path)>=2048) return NULL;
    xpn *x=allocate(cb); if (!x) return NULL;
    x->server=1; x->port=port; strcpy(x->control,socket); strcpy(x->path,path);
    /* Hybrid names are unavailable on OpenSSL <3.5. Fast PSK mode remains available. */
    if (!SSL_CTX_set1_groups_list(x->tls,"X25519MLKEM768:X25519") && !SSL_CTX_set1_groups_list(x->tls,"X25519")) { xpn_destroy(x); return NULL; }
    ERR_clear_error();
    refresh(x);
    if (context(x)) { xpn_destroy(x); return NULL; }
    return x;
}
xpn *xpn_client_new(const char *text, xpn_callbacks cb) {
    if (!text || strlen(text)>XPN_PROFILE_MAX) return NULL;
    xpn *x=allocate(cb); if (!x) return NULL;
    if (profile_parse(text,&x->config)) { xpn_destroy(x); return NULL; }
    CURLU *url=curl_url(); char *host=NULL,*path=NULL,*port=NULL,*query=NULL,*user=NULL;
    /* URL parsing must accept wss even if libcurl itself was built without its
     * optional WebSocket transport; libwebsockets owns the actual connection. */
    int ok=url && !curl_url_set(url,CURLUPART_URL,x->config.endpoint,CURLU_NON_SUPPORT_SCHEME) && !curl_url_get(url,CURLUPART_HOST,&host,0) && !curl_url_get(url,CURLUPART_PATH,&path,0);
    if (ok && (strlen(host)>=sizeof(x->host) || strlen(path)>=sizeof(x->path) || curl_url_get(url,CURLUPART_QUERY,&query,0)==CURLUE_OK || curl_url_get(url,CURLUPART_USER,&user,0)==CURLUE_OK)) ok=0;
    if (ok) { strcpy(x->host,host); strcpy(x->path,path); x->port=443;
        if (!curl_url_get(url,CURLUPART_PORT,&port,0)) { char *end=NULL; long n=strtol(port,&end,10); if (!end || *end || n<1 || n>65535) ok=0; else x->port=(int)n; }
    }
    curl_free(host); curl_free(path); curl_free(port); curl_free(query); curl_free(user); curl_url_cleanup(url);
    if (!ok || !SSL_CTX_set1_groups_list(x->tls,x->config.hybrid ? "X25519MLKEM768" : "X25519") || context(x)) { xpn_destroy(x); return NULL; }
    return x;
}
int xpn_client_set_address(xpn *x, const char *address) {
    unsigned char bytes[16];
    if (!x || x->server || x->client_wsi || x->generation || !address || strlen(address)>=sizeof(x->connect_address) ||
        (inet_pton(AF_INET,address,bytes)!=1 && inet_pton(AF_INET6,address,bytes)!=1)) return -1;
    strcpy(x->connect_address,address);
    return 0;
}
int xpn_client_set_encryption(xpn *x, int inner, int pq) {
    if (!x || x->server || x->client_wsi || x->generation || (inner!=0 && inner!=1) || (pq!=0 && pq!=1) ||
        (x->config.hybrid && (!inner || !pq))) return -1;
    if (pq && !SSL_CTX_set1_groups_list(x->tls,"X25519MLKEM768")) return -1;
    x->wire_v2=1; x->inner_encryption=inner; x->require_pq=pq;
    return 0;
}
int xpn_client_set_standby(xpn *x,int enabled) {
    if (!x || x->server || x->client_wsi || x->generation || (enabled!=0 && enabled!=1)) return -1;
    if (enabled && !x->wire_v2) {
        x->inner_encryption=1; x->require_pq=x->config.hybrid; x->wire_v2=1;
    }
    x->redundant=enabled;
    return 0;
}
int xpn_send(xpn *x, const unsigned char *data, size_t length) {
    uint32_t src,dst;
    if (!x || atomic_load(&x->stop) || !packet_valid(data,length,&src,&dst)) return -1;
    pthread_mutex_lock(&x->lock);
    if (x->count==XPN_QUEUE) { pthread_mutex_unlock(&x->lock); return 1; }
    struct queued *q=&x->queue[(x->head+x->count)%XPN_QUEUE]; q->length=length; memcpy(q->data,data,length); x->count++;
    pthread_mutex_unlock(&x->lock); lws_cancel_service(x->context); return 0;
}
static int flush(peer *p) {
    unsigned char buf[LWS_PRE+16387];
    int prefix=p->wire_v2 ? 3 : 0;
    int n=BIO_read(SSL_get_wbio(p->ssl),buf+LWS_PRE+prefix,16384);
    if (n>0 && p->wire_v2) {
        buf[LWS_PRE]=0; buf[LWS_PRE+1]=(unsigned char)(n>>8); buf[LWS_PRE+2]=(unsigned char)n; n+=3;
    } else if (n<=0 && p->plain_output) {
        n=core_read_plain_output(p,buf+LWS_PRE,16384);
        if (n<0) return -1;
    }
    if (n<=0) return 0;
    int written=lws_write(p->wsi,buf+LWS_PRE,(size_t)n,LWS_WRITE_BINARY);
    if (written<n) return -1;
    if (BIO_ctrl_pending(SSL_get_wbio(p->ssl)) || (p->plain_output && BIO_ctrl_pending(p->plain_output))) lws_callback_on_writable(p->wsi);
    return 0;
}
static void drain(xpn *x) {
    for (unsigned batch=0;batch<64;batch++) {
        struct queued q; pthread_mutex_lock(&x->lock);
        if (!x->count) { pthread_mutex_unlock(&x->lock); return; }
        q=x->queue[x->head]; x->head=(x->head+1)%XPN_QUEUE; x->count--;
        pthread_mutex_unlock(&x->lock);
        uint32_t src,dst; if (!packet_valid(q.data,q.length,&src,&dst)) continue;
        for (unsigned i=0;i<XPN_MAX_PEERS;i++) {
            peer *p=x->peers[i];
            if (!p || !p->authenticated || p->retired || (p->redundant && !p->active) || (x->server && p->config.ip!=dst)) continue;
            if (!x->server && !packet_allowed(&p->config,q.data,q.length)) continue;
            if (core_send(p,q.data,q.length)<0) lws_set_timeout(p->wsi,PENDING_TIMEOUT_USER_OK,LWS_TO_KILL_ASYNC);
            break;
        }
    }
    pthread_mutex_lock(&x->lock); int remains=x->count!=0; pthread_mutex_unlock(&x->lock);
    if (remains) lws_cancel_service(x->context);
}
int xpn_callback(struct lws *wsi, enum lws_callback_reasons reason, void *user, void *in, size_t length) {
    xpn *x=lws_context_user(lws_get_context(wsi)); peer *p=user;
    switch(reason) {
    case LWS_CALLBACK_SSL_INFO: {
        const struct lws_ssl_info *event=in;
        if (!x->server && x->wire_v2 && event && (event->where & SSL_CB_HANDSHAKE_START)) {
            SSL *outer=lws_get_ssl(wsi);
            if (!outer || !SSL_set_min_proto_version(outer,TLS1_3_VERSION) ||
                (x->require_pq && !SSL_set1_groups_list(outer,"X25519MLKEM768"))) return -1;
        }
        if (!x->server && *x->config.sni && event && (event->where & SSL_CB_HANDSHAKE_START)) {
            /* LWS couples its default SNI to HTTP Host. Override the SSL object
             * before ClientHello while retaining endpoint DNS and HTTP Host. */
            SSL *outer=lws_get_ssl(wsi);
            if (!outer || SSL_set_tlsext_host_name(outer,x->config.sni)!=1) return -1;
        }
        return 0;
    }
    case LWS_CALLBACK_OPENSSL_PERFORM_SERVER_CERT_VERIFICATION: {
        if (x->server || !x->config.certificate_pin_count) return 0;
        X509_STORE_CTX *verification=user;
        /* Check the leaf even when OpenSSL is currently visiting an issuer. */
        SSL *outer=verification ? X509_STORE_CTX_get_ex_data(verification,SSL_get_ex_data_X509_STORE_CTX_idx()) : NULL;
        const char *sni=outer ? SSL_get_servername(outer,TLSEXT_NAMETYPE_host_name) : NULL;
        if (!verification || (*x->config.sni && (!sni || strcmp(sni,x->config.sni))) || !certificate_matches(&x->config,X509_STORE_CTX_get0_cert(verification))) {
            if (verification) X509_STORE_CTX_set_error(verification,X509_V_ERR_APPLICATION_VERIFICATION);
            return 1;
        }
        /* Only an exact, provisioned, currently valid pin can override CA/name
         * errors. Never set LCCSCF_ALLOW_INSECURE / ALLOW_SELFSIGNED flags. */
        X509_STORE_CTX_set_error(verification,X509_V_OK);
        return 0;
    }
    case LWS_CALLBACK_CLIENT_FILTER_PRE_ESTABLISH: {
        if (x->wire_v2) {
            SSL *outer=lws_get_ssl(wsi);
            if (!outer || SSL_version(outer)!=TLS1_3_VERSION) return -1;
            if (x->require_pq) {
                const char *group=SSL_group_to_name(outer,SSL_get_negotiated_group(outer));
                if (!group || strcmp(group,"X25519MLKEM768")) return -1;
            }
        }
        if (!x->config.certificate_pin_count) return 0;
        SSL *outer=lws_get_ssl(wsi);
        X509 *leaf=outer ? SSL_get1_peer_certificate(outer) : NULL;
        const char *sni=outer ? SSL_get_servername(outer,TLSEXT_NAMETYPE_host_name) : NULL;
        int accepted=certificate_matches(&x->config,leaf) &&
            (!*x->config.sni || (sni && !strcmp(sni,x->config.sni)));
        X509_free(leaf);
        return accepted ? 0 : -1;
    }
    case LWS_CALLBACK_FILTER_PROTOCOL_CONNECTION: {
        char path[2048],origin[256];
        if (!x->server) return 0;
        if (lws_hdr_copy(wsi,path,sizeof(path),WSI_TOKEN_GET_URI)<=0 || strcmp(path,x->path)) return 1;
        /* Native clients omit Origin. Browser-based tunnel sessions are unsupported. */
        if (lws_hdr_copy(wsi,origin,sizeof(origin),WSI_TOKEN_ORIGIN)>0) return 1;
        unsigned count=0; for(unsigned i=0;i<XPN_MAX_PEERS;i++) count += x->peers[i]!=NULL;
        return count>=128;
    }
    case LWS_CALLBACK_ESTABLISHED:
    case LWS_CALLBACK_CLIENT_ESTABLISHED: {
        memset(p,0,sizeof(*p)); p->owner=x; p->wsi=wsi; p->born=p->checked=time(NULL);
        p->wire_v2=strcmp(lws_get_protocol(wsi)->name,"xpn-v1")!=0;
        p->redundant=!strcmp(lws_get_protocol(wsi)->name,"xpn-v3");
        if (!x->server && (p->wire_v2!=x->wire_v2 || p->redundant!=x->redundant)) return -1;
        if (socket_keepalive(lws_get_socket_fd(wsi))) return -1;
        if (!x->server && p->redundant) {
            struct client_link *link=lws_get_opaque_user_data(wsi);
            if (link!=&x->links[0] && link!=&x->links[1]) return -1;
            link->peer=p; link->failures=0;
            p->slot=link==&x->links[1]; p->generation=link->generation;
            memcpy(p->pair_id,x->pair_id,sizeof(p->pair_id));
        }
        unsigned i; for(i=0;i<XPN_MAX_PEERS;i++) if(!x->peers[i]) { x->peers[i]=p; break; }
        if (i==XPN_MAX_PEERS || core_init(p)) return -1;
        lws_set_timer_usecs(wsi,LWS_USEC_PER_SEC);
        return x->server ? 0 : core_receive(p,NULL,0);
    }
    case LWS_CALLBACK_RECEIVE:
    case LWS_CALLBACK_CLIENT_RECEIVE:
        if (!lws_frame_is_binary(wsi)) return -1;
        return core_receive_wire(p,in,length);
    case LWS_CALLBACK_SERVER_WRITEABLE:
    case LWS_CALLBACK_CLIENT_WRITEABLE:
        return p && p->ssl ? flush(p) : 0;
    case LWS_CALLBACK_TIMER: {
        time_t now=time(NULL);
        if (!p || !p->ssl || p->retired || (!p->authenticated && now-p->born>=10) || now-p->born>=XPN_SESSION_SECONDS) return -1;
        if (p->authenticated && x->server) {
            profile current;
            int invalid=lookup_profile(x,p->config.id,&current) || memcmp(&current,&p->config,sizeof(current));
            OPENSSL_cleanse(&current,sizeof(current)); if (invalid) return -1;
        }
        /* Keep TLS and nginx alive without introducing application plaintext. */
        if (p->authenticated && now-p->checked>=XPN_KEEPALIVE_SECONDS) {
            if (!SSL_key_update(p->ssl,SSL_KEY_UPDATE_NOT_REQUESTED)) return -1;
            if (core_receive(p,NULL,0)) return -1;
            p->checked=now;
        }
        lws_set_timer_usecs(wsi,LWS_USEC_PER_SEC); return 0;
    }
    case LWS_CALLBACK_EVENT_WAIT_CANCELLED: drain(x); return 0;
    case LWS_CALLBACK_CLIENT_CONNECTION_ERROR:
        if (x->redundant) { pair_closed(x,wsi,monotonic_ms()); return 0; }
        x->result=-1; atomic_store(&x->stop,1);
        if (x->cb.state) {
            char detail[256]; snprintf(detail,sizeof(detail),"WebSocket: %.220s",in ? (const char *)in : "connection failed");
            x->cb.state(x->cb.opaque,0,detail);
        }
        return 0;
    case LWS_CALLBACK_CLOSED:
    case LWS_CALLBACK_CLIENT_CLOSED:
        if (!x->server && x->redundant) pair_closed(x,wsi,monotonic_ms());
        for(unsigned i=0;i<XPN_MAX_PEERS;i++) if(x->peers[i]==p) x->peers[i]=NULL;
        if(p) core_free(p);
        if (!x->server && !x->redundant) {
            if(!atomic_load(&x->stop)) x->result=-1;
            atomic_store(&x->stop,1);
            if(x->cb.state) x->cb.state(x->cb.opaque,0,"Tunnel closed; reconnect to rekey");
        }
        return 0;
    case LWS_CALLBACK_HTTP: return -1;
    default: return 0;
    }
}
static void maintain(lws_sorted_usec_list_t *timer) {
    xpn *x=(xpn *)((char *)timer - offsetof(xpn,maintenance));
    if (atomic_load(&x->stop)) return;
    uint64_t now=monotonic_ms();
    if (pair_tick(x,now)) {
        x->result=-1; atomic_store(&x->stop,1);
        if (x->cb.state) x->cb.state(x->cb.opaque,0,"Both VPN connections unavailable; reconnect");
        return;
    }
    for (unsigned i=0;i<2;i++) {
        /* Finish initial lane authentication/activation before warming its
         * spare; this also avoids duplicating the initial network setup. */
        if (i==1 && !x->reported_ready) continue;
        struct client_link *link=&x->links[i];
        if (link->wsi || now<link->retry_at) continue;
        if (x->generation==UINT64_MAX) { xpn_stop(x); x->result=-1; return; }
        link->generation=++x->generation;
        struct lws_client_connect_info info; memset(&info,0,sizeof(info));
        info.context=x->context; info.address=*x->connect_address ? x->connect_address : x->host;
        info.port=x->port; info.path=x->path; info.host=x->host;
        info.protocol=info.local_protocol_name="xpn-v3";
        info.ssl_connection=LCCSCF_USE_SSL;
        if (x->config.certificate_pin_count) info.ssl_connection |= LCCSCF_SKIP_SERVER_CERT_HOSTNAME_CHECK;
        info.pwsi=&link->wsi; info.opaque_user_data=link;
        if (!lws_client_connect_via_info(&info) && link->retry_at<=now) link->retry_at=now+1000;
    }
    lws_sul_schedule(x->context,0,&x->maintenance,maintain,100000);
}
static int resolve_once(xpn *x) {
    if (*x->connect_address) return 0;
    struct addrinfo hints={0},*addresses=NULL;
    hints.ai_socktype=SOCK_STREAM;
#ifdef __linux__
    hints.ai_family=AF_INET;
#endif
    /* Replenishing a lane must not require DNS through the possibly stalled
     * tunnel. Resolve before the initial Connected callback installs routes. */
    if (getaddrinfo(x->host,NULL,&hints,&addresses)) return -1;
    int result=-1;
    for (struct addrinfo *a=addresses;a;a=a->ai_next) {
        const void *ip=a->ai_family==AF_INET ? (void *)&((struct sockaddr_in *)a->ai_addr)->sin_addr :
            a->ai_family==AF_INET6 ? (void *)&((struct sockaddr_in6 *)a->ai_addr)->sin6_addr : NULL;
        if (ip && inet_ntop(a->ai_family,ip,x->connect_address,sizeof(x->connect_address))) { result=0; break; }
    }
    freeaddrinfo(addresses); return result;
}
int xpn_run(xpn *x) {
    pthread_t watcher; int watching=0;
    if (x->server) {
        if (pthread_create(&watcher,NULL,watch,x)) return -1;
        watching=1;
    } else if (x->redundant) {
        if (resolve_once(x)) {
            if (x->cb.state) x->cb.state(x->cb.opaque,0,"Cannot resolve VPN endpoint before connecting");
            return -1;
        }
        unsigned char random[16]; const char *hex="0123456789abcdef";
        if (RAND_bytes(random,sizeof(random))!=1) return -1;
        for (unsigned i=0;i<16;i++) { x->pair_id[2*i]=hex[random[i]>>4]; x->pair_id[2*i+1]=hex[random[i]&15]; }
        x->pair_id[32]=0; OPENSSL_cleanse(random,sizeof(random));
        x->outage_since=monotonic_ms(); maintain(&x->maintenance);
    } else {
        struct lws_client_connect_info info; memset(&info,0,sizeof(info));
        info.context=x->context; info.address=*x->connect_address ? x->connect_address : x->host; info.port=x->port; info.path=x->path;
        info.host=x->host; info.protocol=x->wire_v2 ? "xpn-v2" : "xpn-v1"; info.local_protocol_name=info.protocol;
        info.ssl_connection=LCCSCF_USE_SSL;
        if (x->config.certificate_pin_count) info.ssl_connection |= LCCSCF_SKIP_SERVER_CERT_HOSTNAME_CHECK;
        info.pwsi=&x->client_wsi;
        if (!lws_client_connect_via_info(&info)) { atomic_store(&x->stop,1); x->result=-1; }
    }
    while(!atomic_load(&x->stop)) if(lws_service(x->context,100)<0) { x->result=-1; break; }
    atomic_store(&x->stop,1); lws_sul_cancel(&x->maintenance); if(watching) pthread_join(watcher,NULL);
    return x->result;
}
void xpn_stop(xpn *x) { if(x) { atomic_store(&x->stop,1); if(x->context) lws_cancel_service(x->context); } }
void xpn_destroy(xpn *x) {
    if(!x) return;
    if(x->context) lws_context_destroy(x->context);
    SSL_CTX_free(x->tls); pthread_mutex_destroy(&x->lock); free(x->queue);
    OPENSSL_cleanse(x,sizeof(*x)); free(x);
}
