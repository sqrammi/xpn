#ifndef XPN_INTERNAL_H
#define XPN_INTERNAL_H
#include "xpn.h"
#include <jansson.h>
#include <openssl/ssl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#include <libwebsockets.h>

#define XPN_MAX_PEERS 256
#define XPN_QUEUE 512
#define XPN_TLS_LIMIT (128 * 1024)
#define XPN_SESSION_SECONDS 3600
#define XPN_KEEPALIVE_SECONDS 15
#define XPN_MAX_CERTIFICATE_PINS 4
typedef struct {
    char id[37], address[16], endpoint[2048];
    char sni[254];
    unsigned char certificate_pins[XPN_MAX_CERTIFICATE_PINS][32];
    unsigned certificate_pin_count;
    unsigned char key[32];
    uint32_t ip;
    int full, hybrid;
    unsigned routes_count;
    struct { uint32_t net, mask; } routes[32];
} profile;
typedef struct peer {
    struct xpn *owner;
    struct lws *wsi;
    SSL *ssl;
    profile config;
    int authenticated;
    int wire_v2, redundant, inner_encryption, require_pq;
    char identity[91], pair_id[33];
    unsigned slot;
    uint64_t generation, activation, ping_sent, last_pong, rtt, next_ping;
    int active, retired;
    BIO *plain_output;
    unsigned char wire_frame[16387];
    size_t wire_have;
    unsigned char frame[XPN_MTU + 2];
    size_t have;
    time_t born, checked;
    unsigned bytes_since_update;
} peer;
struct queued { size_t length; unsigned char data[XPN_MTU]; };
struct client_link { struct lws *wsi; peer *peer; uint64_t generation, retry_at; unsigned failures; };
struct xpn {
    int server, port;
    char control[1024], path[2048], host[256];
    char connect_address[64];
    profile config;
    profile cached[XPN_MAX_PEERS];
    size_t cached_count;
    xpn_callbacks cb;
    SSL_CTX *tls;
    struct lws_context *context;
    struct lws *client_wsi;
    peer *peers[XPN_MAX_PEERS];
    atomic_int stop;
    pthread_mutex_t lock;
    struct queued *queue;
    size_t head, count;
    int result;
    int wire_v2, redundant, inner_encryption, require_pq;
    char pair_id[33];
    struct client_link links[2];
    peer *active, *promoting;
    uint64_t generation, activation, promotion_started, last_switch, outage_since;
    int reported_ready;
    atomic_uint ready_links, switch_count;
    lws_sorted_usec_list_t maintenance;
};
int profile_parse(const char *, profile *);
int packet_valid(const unsigned char *, size_t, uint32_t *, uint32_t *);
int packet_allowed(const profile *, const unsigned char *, size_t);
int decode64(const char *, unsigned char *, size_t);
char *control_get(const char *, const char *);
int core_init(peer *);
int core_receive(peer *, const void *, size_t);
int core_receive_wire(peer *, const void *, size_t);
int core_read_plain_output(peer *, unsigned char *, size_t);
int core_control(peer *, unsigned char, uint64_t);
int core_send(peer *, const unsigned char *, size_t);
void core_free(peer *);
int xpn_callback(struct lws *, enum lws_callback_reasons, void *, void *, size_t);
int lookup_profile(struct xpn *, const char *, profile *);
int certificate_matches(const profile *, X509 *);
extern char xpn_ca_file[4096];
uint64_t monotonic_ms(void);
int pair_permitted(peer *, int);
int pair_authenticated(peer *);
int pair_control(peer *, unsigned char, uint64_t);
int pair_tick(xpn *, uint64_t);
void pair_closed(xpn *, struct lws *, uint64_t);
int pair_should_switch(const peer *, const peer *, uint64_t, uint64_t);
int socket_keepalive(int);
#endif
