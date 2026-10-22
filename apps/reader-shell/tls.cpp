#include "tls.h"
#include "resolver.h"
#include "tlsclock.h"
#include <QtCore/qregexp.h>
#include <time.h>
#include <string.h>
#include <arpa/inet.h>
extern "C" {
#include <mbedtls/ssl.h>
#include <mbedtls/entropy.h>
#include <mbedtls/ctr_drbg.h>
#include <mbedtls/x509_crt.h>
#include <mbedtls/platform_time.h>
#include <mbedtls/sha256.h>
}
// One reader client in this process. No static Qt objects or wall-clock trust.
static qint64 trustedEpoch=0;static int64_t trustedBoot=-1;
static mbedtls_time_t tlsTime(mbedtls_time_t *out){int64_t epoch=tlsAdvanceEpoch(trustedEpoch,trustedBoot,tlsBootMs());mbedtls_time_t value=mbedtls_time_t(epoch);if(out)*out=value;return value;}

struct DeviceTlsState {
 mbedtls_ssl_context ssl;mbedtls_ssl_config config;mbedtls_x509_crt ca;mbedtls_entropy_context entropy;mbedtls_ctr_drbg_context random;
 void *context;DeviceTls::Io send,recv;QByteArray pin;QString host;bool domain;
 DeviceTlsState():context(0),send(0),recv(0),domain(false){mbedtls_ssl_init(&ssl);mbedtls_ssl_config_init(&config);mbedtls_x509_crt_init(&ca);mbedtls_entropy_init(&entropy);mbedtls_ctr_drbg_init(&random);}
 ~DeviceTlsState(){mbedtls_ssl_free(&ssl);mbedtls_ssl_config_free(&config);mbedtls_x509_crt_free(&ca);mbedtls_entropy_free(&entropy);mbedtls_ctr_drbg_free(&random);}
};
static int sendBio(void *p,const unsigned char *b,size_t n){DeviceTlsState *s=static_cast<DeviceTlsState *>(p);int r=s->send(s->context,const_cast<unsigned char *>(b),int(n));return r<0?MBEDTLS_ERR_SSL_WANT_WRITE:r;}
static int recvBio(void *p,unsigned char *b,size_t n){DeviceTlsState *s=static_cast<DeviceTlsState *>(p);int r=s->recv(s->context,b,int(n));return r<0?MBEDTLS_ERR_SSL_WANT_READ:r;}
DeviceTls::DeviceTls():state_(0){}DeviceTls::~DeviceTls(){reset();}void DeviceTls::reset(){delete state_;state_=0;}
void DeviceTls::trustEpoch(qint64 epoch){if(epoch<946684800LL||epoch>2147483646LL)return;trustedEpoch=epoch;trustedBoot=tlsBootMs();mbedtls_platform_set_time(tlsTime);}
bool DeviceTls::configure(const QString &host,const QByteArray &pem,const QString &pin,qint64 epoch,void *context,Io send,Io recv,QString *error){
 reset();struct in_addr addr;QByteArray hostBytes=host.toLatin1();bool numeric=::inet_pton(AF_INET,hostBytes.constData(),&addr)==1;bool domain=host==QString::fromLatin1(hostBytes)&&validDnsHost(hostBytes.constData());if(!send||!recv||pem.isEmpty()||pem.size()>16384||!QRegExp("[0-9a-f]{64}").exactMatch(pin)||epoch<946684800LL||epoch>2147483646LL||(!numeric&&!domain)){if(error)*error="tls-profile";return false;}
 state_=new DeviceTlsState;DeviceTlsState *s=state_;s->context=context;s->send=send;s->recv=recv;s->pin=QByteArray::fromHex(pin.toLatin1());s->host=host;s->domain=domain;trustEpoch(epoch);
 int r=mbedtls_x509_crt_parse(&s->ca,reinterpret_cast<const unsigned char *>(pem.constData()),pem.size()+1);
 if(!r&&domain){unsigned char hash[32];if(s->ca.next||!s->ca.MBEDTLS_PRIVATE(ca_istrue)||mbedtls_sha256(s->ca.raw.p,s->ca.raw.len,hash,0))r=-1;else{unsigned diff=0;for(unsigned i=0;i<32;i++)diff|=hash[i]^static_cast<unsigned char>(s->pin[i]);if(diff)r=-1;}}
 if(!r)r=mbedtls_ctr_drbg_seed(&s->random,mbedtls_entropy_func,&s->entropy,reinterpret_cast<const unsigned char *>("pandanote-reader-v1"),15);
 if(!r)r=mbedtls_ssl_config_defaults(&s->config,MBEDTLS_SSL_IS_CLIENT,MBEDTLS_SSL_TRANSPORT_STREAM,MBEDTLS_SSL_PRESET_DEFAULT);
 if(!r){mbedtls_ssl_conf_authmode(&s->config,MBEDTLS_SSL_VERIFY_REQUIRED);mbedtls_ssl_conf_ca_chain(&s->config,&s->ca,0);mbedtls_ssl_conf_rng(&s->config,mbedtls_ctr_drbg_random,&s->random);r=mbedtls_ssl_setup(&s->ssl,&s->config);}
 if(!r)r=mbedtls_ssl_set_hostname(&s->ssl,host.toLatin1().constData());if(r){reset();if(error)*error="tls-setup";return false;}mbedtls_ssl_set_bio(&s->ssl,s,sendBio,recvBio,0);if(error)error->clear();return true;
}
int DeviceTls::handshake(QString *error){
 if(!state_){if(error)*error="tls-unconfigured";return -1;}DeviceTlsState *s=state_;int r=mbedtls_ssl_handshake(&s->ssl);if(r==MBEDTLS_ERR_SSL_WANT_READ||r==MBEDTLS_ERR_SSL_WANT_WRITE)return 0;
 if(r||mbedtls_ssl_get_verify_result(&s->ssl)){if(error)*error="tls-peer-verification";return -1;}
 const mbedtls_x509_crt *peer=mbedtls_ssl_get_peer_cert(&s->ssl);if(!peer){if(error)*error="tls-peer-missing";return -1;}if(s->domain){
  QByteArray host=s->host.toLatin1();bool matched=false;
  for(const mbedtls_x509_sequence *p=&peer->subject_alt_names;p;p=p->next)if((p->buf.tag&0x1f)==MBEDTLS_X509_SAN_DNS_NAME&&p->buf.len==size_t(host.size())&&!memcmp(p->buf.p,host.constData(),host.size()))matched=true;
  if(!matched){if(error)*error="tls-dns-san";return -1;}
 }else{
  unsigned char hash[32];if(mbedtls_sha256(peer->raw.p,peer->raw.len,hash,0)){if(error)*error="tls-pin-hash";return -1;}
  unsigned diff=0;for(int i=0;i<32;++i)diff|=hash[i]^static_cast<unsigned char>(s->pin[i]);
  struct in_addr addr;::inet_pton(AF_INET,s->host.toLatin1().constData(),&addr);bool ipSan=false;for(const mbedtls_x509_sequence *p=&peer->subject_alt_names;p;p=p->next)if((p->buf.tag&0x1f)==MBEDTLS_X509_SAN_IP_ADDRESS&&p->buf.len==4&&!memcmp(p->buf.p,&addr,4))ipSan=true;
  if(diff||!ipSan){if(error)*error=diff?"tls-certificate-pin":"tls-ip-san";return -1;}
 }
 return 1;
}
int DeviceTls::write(const unsigned char *data,int n){if(!state_)return -2;int r=mbedtls_ssl_write(&state_->ssl,data,n);return r==MBEDTLS_ERR_SSL_WANT_READ||r==MBEDTLS_ERR_SSL_WANT_WRITE?-1:r<0?-2:r;}
int DeviceTls::read(unsigned char *data,int n){if(!state_)return -2;int r=mbedtls_ssl_read(&state_->ssl,data,n);return r==MBEDTLS_ERR_SSL_WANT_READ||r==MBEDTLS_ERR_SSL_WANT_WRITE?-1:r<0?-2:r;}
