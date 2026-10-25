#include "internal.h"
#include <openssl/crypto.h>
#include <openssl/err.h>
#include <stdlib.h>
#include <string.h>

/* External PSK sessions are ephemeral callback objects, never resumption tickets.
 * OpenSSL consumes the returned session reference. The only cipher uses SHA-256. */
static SSL_SESSION *session(SSL *ssl, const unsigned char key[32]) {
    const unsigned char id[] = {0x13,0x03};
    const SSL_CIPHER *cipher = SSL_CIPHER_find(ssl,id);
    SSL_SESSION *s = SSL_SESSION_new();
    if (!s || !cipher || !SSL_SESSION_set1_master_key(s,key,32) || !SSL_SESSION_set_cipher(s,cipher) || !SSL_SESSION_set_protocol_version(s,TLS1_3_VERSION)) { SSL_SESSION_free(s); return NULL; }
    return s;
}
static int use_psk(SSL *ssl, const EVP_MD *md, const unsigned char **id, size_t *length, SSL_SESSION **s) {
    peer *p = SSL_get_app_data(ssl);
    if (md && EVP_MD_get_type(md) != NID_sha256) return 0;
    *id = (unsigned char *)p->config.id; *length = 36; *s = session(ssl,p->config.key); return *s != NULL;
}
static int find_psk(SSL *ssl, const unsigned char *id, size_t length, SSL_SESSION **s) {
    peer *p = SSL_get_app_data(ssl); char text[37];
    if (length != 36) return 0;
    memcpy(text,id,36); text[36]=0;
    if (lookup_profile(p->owner,text,&p->config)) return 0;
    /* Reject concurrent sessions for one identity. Nothing may evict a live peer
     * until the new peer has authenticated; reject instead to prevent hijacking. */
    for (unsigned i=0;i<XPN_MAX_PEERS;i++) {
        peer *other = p->owner->peers[i];
        if (other && other != p && other->authenticated && !strcmp(other->config.id,text)) return 0;
    }
    *s = session(ssl,p->config.key); return *s != NULL;
}
int core_init(peer *p) {
    p->ssl = SSL_new(p->owner->tls);
    if (!p->ssl) return -1;
    SSL_set_app_data(p->ssl,p);
    BIO *input=BIO_new(BIO_s_mem()), *output=BIO_new(BIO_s_mem());
    if (!input || !output) { BIO_free(input); BIO_free(output); return -1; }
    BIO_set_mem_eof_return(input,-1); BIO_set_mem_eof_return(output,-1);
    SSL_set_bio(p->ssl,input,output);
    if (p->owner->server) { SSL_set_accept_state(p->ssl); SSL_set_psk_find_session_callback(p->ssl,find_psk); }
    else {
        p->config=p->owner->config;
        if (!SSL_set1_groups_list(p->ssl,p->config.hybrid ? "X25519MLKEM768" : "X25519")) return -1;
        SSL_set_connect_state(p->ssl); SSL_set_psk_use_session_callback(p->ssl,use_psk);
    }
    return 0;
}
static int pending(peer *p) {
    if (BIO_ctrl_pending(SSL_get_wbio(p->ssl)) > XPN_TLS_LIMIT) return -1;
    if (p->wsi && BIO_ctrl_pending(SSL_get_wbio(p->ssl))) lws_callback_on_writable(p->wsi);
    return 0;
}
int core_receive(peer *p, const void *input, size_t length) {
    if (length > 65536 || BIO_ctrl_pending(SSL_get_rbio(p->ssl)) + length > XPN_TLS_LIMIT) return -1;
    if (length && BIO_write(SSL_get_rbio(p->ssl),input,(int)length) != (int)length) return -1;
    if (!p->authenticated) {
        ERR_clear_error();
        int rc = SSL_do_handshake(p->ssl);
        if (rc != 1) { int err=SSL_get_error(p->ssl,rc); return err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE ? pending(p) : -1; }
        if (!SSL_session_reused(p->ssl) || SSL_version(p->ssl) != TLS1_3_VERSION || !SSL_get_negotiated_group(p->ssl)) return -1;
        if (p->config.hybrid) {
            const char *name = SSL_group_to_name(p->ssl,SSL_get_negotiated_group(p->ssl));
            if (!name || strcmp(name,"X25519MLKEM768")) return -1;
        }
        /* Find-PSK can run on several unauthenticated sockets. Recheck identity
         * uniqueness after Finished to close the simultaneous-handshake race. */
        if (p->owner->server) for (unsigned i=0;i<XPN_MAX_PEERS;i++) {
            peer *other=p->owner->peers[i];
            if (other && other!=p && other->authenticated && !strcmp(other->config.id,p->config.id)) return -1;
        }
        p->authenticated=1;
        if (!p->owner->server && p->owner->cb.state) p->owner->cb.state(p->owner->cb.opaque,1,"TLS 1.3 PSK authenticated");
    }
    for (;;) {
        size_t want = 2;
        if (p->have >= 2) {
            want = 2 + ((size_t)p->frame[0]<<8 | p->frame[1]);
            if (want < 22 || want > sizeof(p->frame)) return -1;
        }
        if (p->have == want) {
            uint32_t src,dst;
            if (!packet_valid(p->frame+2,want-2,&src,&dst)) return -1;
            if (p->owner->server && !packet_allowed(&p->config,p->frame+2,want-2)) return -1;
            if (!p->owner->server && dst != p->config.ip) return -1;
            if (p->owner->cb.packet) p->owner->cb.packet(p->owner->cb.opaque,p->frame+2,want-2);
            p->have=0; continue;
        }
        size_t got=0;
        ERR_clear_error();
        int rc=SSL_read_ex(p->ssl,p->frame+p->have,want-p->have,&got);
        if (rc != 1) {
            int err=SSL_get_error(p->ssl,rc);
            return err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE ? pending(p) : -1;
        }
        p->have += got;
    }
}
int core_send(peer *p, const unsigned char *data, size_t length) {
    if (!p->authenticated || length < 20 || length > XPN_MTU) return -1;
    /* Drop under bounded backpressure; never let a slow connection consume unbounded memory. */
    if (BIO_ctrl_pending(SSL_get_wbio(p->ssl)) > XPN_TLS_LIMIT - XPN_MTU - 256) return 1;
    unsigned char frame[XPN_MTU+2]; frame[0]=(unsigned char)(length>>8); frame[1]=(unsigned char)length;
    memcpy(frame+2,data,length); size_t written=0;
    ERR_clear_error();
    if (!SSL_write_ex(p->ssl,frame,length+2,&written) || written != length+2) return -1;
    p->bytes_since_update += (unsigned)length;
    if (p->bytes_since_update >= 1024U*1024U*1024U) {
        if (!SSL_key_update(p->ssl,SSL_KEY_UPDATE_REQUESTED)) return -1;
        p->bytes_since_update=0;
    }
    return pending(p);
}
void core_free(peer *p) { SSL_free(p->ssl); p->ssl=NULL; OPENSSL_cleanse(&p->config,sizeof(p->config)); }
