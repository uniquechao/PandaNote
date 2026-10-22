#include "core.h"
#include <mbedtls/pk.h>
#include <mbedtls/ecp.h>
#include <mbedtls/sha256.h>
namespace Ota {
bool verifySignature(const std::string &pem,const std::string &message,const std::string &signature){if(pem.empty()||pem.size()>16384||signature.empty()||signature.size()>128)return false;mbedtls_pk_context key;mbedtls_pk_init(&key);unsigned char hash[32];bool ok=!mbedtls_pk_parse_public_key(&key,reinterpret_cast<const unsigned char*>(pem.c_str()),pem.size()+1)&&mbedtls_pk_can_do(&key,MBEDTLS_PK_ECDSA)&&mbedtls_pk_get_bitlen(&key)==256;if(ok){mbedtls_ecp_keypair *ec=mbedtls_pk_ec(key);ok=ec&&ec->MBEDTLS_PRIVATE(grp).id==MBEDTLS_ECP_DP_SECP256R1;}if(ok)ok=!mbedtls_sha256(reinterpret_cast<const unsigned char*>(message.data()),message.size(),hash,0)&&!mbedtls_pk_verify(&key,MBEDTLS_MD_SHA256,hash,32,reinterpret_cast<const unsigned char*>(signature.data()),signature.size());mbedtls_pk_free(&key);return ok;}
}
