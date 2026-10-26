#include "internal.h"
#include <openssl/crypto.h>
#include <openssl/err.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

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
    if (p->wire_v2) {
        memcpy(p->identity,p->config.id,36); p->identity[36]='|';
        p->identity[37]=p->inner_encryption ? (p->require_pq ? 'h' : 'e') : (p->require_pq ? 'q' : 't');
        if (p->redundant) {
            char mode=p->identity[37];
            snprintf(p->identity,sizeof(p->identity),"%s|%c|%s|%u|%016llx",p->config.id,mode,p->pair_id,p->slot,(unsigned long long)p->generation);
        }
        *id=(unsigned char *)p->identity; *length=p->redundant ? 90 : 38;
    } else { *id=(unsigned char *)p->config.id; *length=36; }
    *s = session(ssl,p->config.key); return *s != NULL;
}
static int find_psk(SSL *ssl, const unsigned char *id, size_t length, SSL_SESSION **s) {
    peer *p = SSL_get_app_data(ssl); char text[37];
    if (length != (p->redundant ? 90U : p->wire_v2 ? 38U : 36U)) return 0;
    memcpy(text,id,36); text[36]=0;
    if (lookup_profile(p->owner,text,&p->config)) return 0;
    p->inner_encryption=1; p->require_pq=p->config.hybrid;
    if (p->wire_v2) {
        if (id[36]!='|' || !strchr("ehqt",id[37]) || !id[37]) return 0;
        p->inner_encryption=id[37]=='e' || id[37]=='h';
        p->require_pq=id[37]=='h' || id[37]=='q';
        /* An administrator's hybrid requirement is a minimum, never a hint. */
        if (p->config.hybrid && (!p->require_pq || !p->inner_encryption)) return 0;
    }
    if (p->redundant) {
        if (id[38]!='|' || id[71]!='|' || id[73]!='|' || (id[72]!='0' && id[72]!='1')) return 0;
        const char *hex="0123456789abcdef";
        for (unsigned i=0;i<32;i++) if (!id[39+i] || !strchr(hex,id[39+i])) return 0;
        memcpy(p->pair_id,id+39,32); p->pair_id[32]=0; p->slot=id[72]-'0'; p->generation=0;
        for (unsigned i=0;i<16;i++) {
            const char *digit=id[74+i] ? strchr(hex,id[74+i]) : NULL;
            if (!digit) return 0;
            p->generation=p->generation*16+(uint64_t)(digit-hex);
        }
        if (!p->generation) return 0;
    }
    if (pair_permitted(p,0)) return 0;
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
    if (p->wire_v2 && !(p->plain_output=BIO_new(BIO_s_mem()))) return -1;
    if (p->owner->server) { SSL_set_accept_state(p->ssl); SSL_set_psk_find_session_callback(p->ssl,find_psk); }
    else {
        p->config=p->owner->config;
        p->inner_encryption=p->wire_v2 ? p->owner->inner_encryption : 1;
        p->require_pq=p->wire_v2 ? p->owner->require_pq : p->config.hybrid;
        if (!SSL_set1_groups_list(p->ssl,p->require_pq ? "X25519MLKEM768" : "X25519")) return -1;
        SSL_set_connect_state(p->ssl); SSL_set_psk_use_session_callback(p->ssl,use_psk);
    }
    return 0;
}
static int pending(peer *p) {
    size_t queued=BIO_ctrl_pending(SSL_get_wbio(p->ssl)) + (p->plain_output ? BIO_ctrl_pending(p->plain_output) : 0);
    if (queued > XPN_TLS_LIMIT) return -1;
    if (p->wsi && queued) lws_callback_on_writable(p->wsi);
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
        if (p->require_pq) {
            const char *name = SSL_group_to_name(p->ssl,SSL_get_negotiated_group(p->ssl));
            if (!name || strcmp(name,"X25519MLKEM768")) return -1;
        }
        /* Find-PSK can run on several unauthenticated sockets. Recheck identity
         * uniqueness after Finished to close the simultaneous-handshake race. */
        if (p->owner->server && pair_permitted(p,1)) return -1;
        p->authenticated=1;
        if (p->redundant) { if (pair_authenticated(p)) return -1; }
        else if (!p->owner->server && p->owner->cb.state) p->owner->cb.state(p->owner->cb.opaque,1,"TLS 1.3 PSK authenticated");
    }
    for (;;) {
        size_t want = 2;
        if (p->have >= 2) {
            want = 2 + ((size_t)p->frame[0]<<8 | p->frame[1]);
            if ((want < 22 && !(p->redundant && want==11)) || want > sizeof(p->frame)) return -1;
        }
        if (p->have == want) {
            if (p->redundant && want==11) {
                uint64_t value=0;
                for (unsigned i=3;i<11;i++) value=(value<<8)|p->frame[i];
                if (pair_control(p,p->frame[2],value)) return -1;
                p->have=0; continue;
            }
            if (p->wire_v2 && !p->inner_encryption) return -1;
            uint32_t src,dst;
            if (!packet_valid(p->frame+2,want-2,&src,&dst)) return -1;
            if (p->owner->server && !packet_allowed(&p->config,p->frame+2,want-2)) return -1;
            if (!p->owner->server && dst != p->config.ip) return -1;
            if ((!p->redundant || (p->active && !p->retired)) && p->owner->cb.packet) p->owner->cb.packet(p->owner->cb.opaque,p->frame+2,want-2);
            p->have=0; continue;
        }
        size_t got=0;
        ERR_clear_error();
        int rc=SSL_read_ex(p->ssl,p->frame+p->have,want-p->have,&got);
        if (rc != 1) {
            int err=SSL_get_error(p->ssl,rc);
            return err == SSL_ERROR_WANT_READ || err == SSL_ERROR_WANT_WRITE ? pending(p) : -1;
        }
        if (p->wire_v2 && !p->redundant && !p->inner_encryption) return -1;
        p->have += got;
    }
}
int core_control(peer *p,unsigned char type,uint64_t value) {
    if (!p->redundant || !p->authenticated || p->retired ||
        BIO_ctrl_pending(SSL_get_wbio(p->ssl))>XPN_TLS_LIMIT-256) return -1;
    unsigned char frame[11]={0,9,type};
    for (unsigned i=0;i<8;i++) frame[10-i]=(unsigned char)(value>>(i*8));
    size_t written=0;
    ERR_clear_error();
    if (!SSL_write_ex(p->ssl,frame,sizeof(frame),&written) || written!=sizeof(frame)) return -1;
    return pending(p);
}
int core_send(peer *p, const unsigned char *data, size_t length) {
    if (!p->authenticated || length < 20 || length > XPN_MTU) return -1;
    /* Drop under bounded backpressure; never let a slow connection consume unbounded memory. */
    size_t queued=BIO_ctrl_pending(SSL_get_wbio(p->ssl)) + (p->plain_output ? BIO_ctrl_pending(p->plain_output) : 0);
    if (queued > XPN_TLS_LIMIT - XPN_MTU - 256) return 1;
    if (p->wire_v2 && !p->inner_encryption) {
        unsigned char raw[XPN_MTU+3]={1,(unsigned char)(length>>8),(unsigned char)length};
        memcpy(raw+3,data,length);
        if (BIO_write(p->plain_output,raw,(int)length+3)!=(int)length+3) return -1;
        return pending(p);
    }
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
int core_read_plain_output(peer *p, unsigned char *output, size_t capacity) {
    char *bytes=NULL;
    long available=p->plain_output ? BIO_get_mem_data(p->plain_output,&bytes) : 0;
    size_t batch=0;
    /* Finish every raw record before allowing a TLS control record to precede
     * the next batch. Cutting a record here would splice TLS into its payload. */
    while (available>0 && batch<(size_t)available) {
        if ((size_t)available-batch<3) return -1;
        const unsigned char *record=(const unsigned char *)bytes+batch;
        size_t size=3+((size_t)record[1]<<8|record[2]);
        if (record[0]!=1 || size<23 || size>XPN_MTU+3 || size>(size_t)available-batch) return -1;
        if (size>capacity-batch) break;
        batch+=size;
    }
    if (!batch) return available>0 ? -1 : 0;
    return BIO_read(p->plain_output,output,(int)batch);
}
int core_receive_wire(peer *p, const void *input, size_t length) {
    if (!p->wire_v2) return core_receive(p,input,length);
    const unsigned char *bytes=input;
    while (length) {
        size_t want=3;
        if (p->wire_have>=3) {
            size_t payload=((size_t)p->wire_frame[1]<<8)|p->wire_frame[2];
            if (!payload || payload>16384 || p->wire_frame[0]>1) return -1;
            want+=payload;
        }
        size_t take=want-p->wire_have; if (take>length) take=length;
        memcpy(p->wire_frame+p->wire_have,bytes,take); p->wire_have+=take; bytes+=take; length-=take;
        if (p->wire_have==3 && (p->wire_frame[0]>1 || (!p->wire_frame[1] && !p->wire_frame[2]) ||
            (((size_t)p->wire_frame[1]<<8)|p->wire_frame[2])>16384)) return -1;
        if (p->wire_have==want && want>3) {
            const unsigned char *packet=p->wire_frame+3; size_t size=want-3;
            if (!p->wire_frame[0]) {
                if (core_receive(p,packet,size)) return -1;
            } else {
                uint32_t src,dst;
                if (!p->authenticated || p->inner_encryption || !packet_valid(packet,size,&src,&dst) ||
                    (p->owner->server ? !packet_allowed(&p->config,packet,size) : dst!=p->config.ip)) return -1;
                if ((!p->redundant || (p->active && !p->retired)) && p->owner->cb.packet) p->owner->cb.packet(p->owner->cb.opaque,packet,size);
            }
            p->wire_have=0;
        }
    }
    return 0;
}
void core_free(peer *p) { SSL_free(p->ssl); p->ssl=NULL; BIO_free(p->plain_output); p->plain_output=NULL; OPENSSL_cleanse(&p->config,sizeof(p->config)); }
