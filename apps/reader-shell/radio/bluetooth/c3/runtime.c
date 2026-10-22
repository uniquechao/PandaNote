#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "runtime.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static void wipe(void *v,size_t n){volatile unsigned char *p=v;
 while(n--)*p++=0;
 }
static void put32(unsigned char *p,uint32_t n){for(int i=0; i<4; i++)p[i]=(unsigned char)(n>>(8*i));
 }
static uint32_t get32(const unsigned char *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);
 }
static int random_bytes(unsigned char *out,size_t n){
 int fd=open("/dev/urandom",O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
 struct stat s;
 if(fd<0)return -1;
 if(fstat(fd,&s)||!S_ISCHR(s.st_mode)){close(fd);
 return -1;
 }
 size_t offset=0;
 unsigned attempts=0;
 while(offset<n&&attempts++<32){ssize_t got=read(fd,out+offset,n-offset);
 if(got>0)offset+=(size_t)got;
 else if(got<0&&errno==EINTR)continue;
 else break;
 }
 close(fd);
 if(offset!=n){wipe(out,n);
 return -1;
 }return 0;
}
void c3_init(struct c3 *s,unsigned char *b,size_t n,int dir){memset(s,0,sizeof *s);
 bt_policy_init(&s->policy,b,n);
 s->inbox_fd=dir;
 s->ack[0]=1;
 }
void c3_close(struct c3 *s){bt_policy_close(&s->policy);
 wipe(&s->effect,sizeof s->effect);
 wipe(s->record,sizeof s->record);
 wipe(s->last_fragment,sizeof s->last_fragment);
 memset(s->ack,0,sizeof s->ack);
 s->ack[0]=1;
 s->assembled=s->last_size=0;
 s->assembly_until=0;
 s->passkey=0;
 s->effect_generation=0;
 }
int c3_pair_request(struct c3 *s,const unsigned char peer[6],unsigned passkey,uint64_t now){
 unsigned char nonce[16];
 if(random_bytes(nonce,sizeof nonce))return 0;
 int result=bt_pair_request(&s->policy,peer,passkey,nonce,now);
 wipe(nonce,sizeof nonce);
 if(result)s->passkey=passkey;
 return result;
}
void c3_tick(struct c3 *s,uint64_t now){
 if((s->policy.active&&(now<s->policy.session_from||now>=s->policy.session_until))||
    (!s->policy.active&&(s->policy.pending||s->policy.approved)&&(now<s->policy.pending_from||now>=s->policy.pending_until))){c3_close(s);
 return;
 }
 if(s->assembled&&(now>=s->assembly_until||now<s->assembly_until-5000)){wipe(s->record,sizeof s->record);
 s->assembled=0;
 s->assembly_until=0;
 s->last_size=0;
 }
}
static int safe_name(const char *name){size_t n=strnlen(name,49);
 if(!n||n>48||name[0]=='.')return 0;
 for(size_t i=0; i<n; i++){unsigned char c=(unsigned char)name[i];
 if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||c=='_'||c=='-'||c=='.')||(i&&c=='.'&&name[i-1]=='.'))return 0;
 }return (n>4&&(!strcmp(name+n-4,".txt")||!strcmp(name+n-4,".pdf")))||(n>5&&!strcmp(name+n-5,".epub"));
 }
int c3_store(int dir,const char *name,const unsigned char *data,size_t size){
 struct stat parent,owned;
 memset(&owned,0,sizeof owned);
 int owned_valid=0;
 if(!name||!data||!size||size>BT_FILE_MAX||!safe_name(name)||fstat(dir,&parent)||!S_ISDIR(parent.st_mode)||parent.st_uid!=geteuid()||(parent.st_mode&07777)!=0700)return -1;
 unsigned char entropy[16];
 if(random_bytes(entropy,sizeof entropy))return -1;
 char temp[44]=".pending-";
 for(size_t i=0; i<sizeof entropy; i++)snprintf(temp+9+2*i,3,"%02x",entropy[i]);
 wipe(entropy,sizeof entropy);
 int fd=openat(dir,temp,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
 if(fd<0)return -1;
 int result=-1;
 size_t offset=0;
 if(fstat(fd,&owned)||!S_ISREG(owned.st_mode)||owned.st_uid!=geteuid()||owned.st_nlink!=1||(owned.st_mode&07777)!=0600||owned.st_dev!=parent.st_dev)goto done;
 owned_valid=1;
 while(offset<size){ssize_t n=write(fd,data+offset,size-offset);
 if(n>0)offset+=(size_t)n;
 else if(n<0&&errno==EINTR)continue;
 else goto done;
 }
 if(fsync(fd)||linkat(dir,temp,dir,name,0))goto done;
 /* Once published, a failed directory fsync is uncertain durability, never ACK success. */
 result=-2;
 if(unlinkat(dir,temp,0)||fsync(dir))goto done;
 result=0;
 done:
 if(result==-1&&owned_valid){struct stat now;
 if(!fstatat(dir,temp,&now,AT_SYMLINK_NOFOLLOW)&&now.st_ino==owned.st_ino&&now.st_dev==owned.st_dev)(void)unlinkat(dir,temp,0);
 }
 close(fd);
 return result;
}
static int ack(struct c3 *s,int status,uint32_t sequence,size_t offset){s->ack[0]=1;
 s->ack[1]=(unsigned char)status;
 put32(s->ack+2,sequence);
 s->ack[6]=(unsigned char)offset;
 s->ack[7]=(unsigned char)(offset>>8);
 put32(s->ack+8,s->policy.next_sequence);
 return status==0?0:status==1?1:-1;
 }
int c3_fragment(struct c3 *s,const unsigned char *f,size_t n,unsigned mtu,uint64_t now){
 c3_tick(s,now);
 if(!s->policy.active||!f||n<5||mtu<23||mtu>517||n>mtu-3||n>sizeof s->last_fragment||(f[0]&~3))return ack(s,2,0,s->assembled);
 if(n==s->last_size&&!memcmp(f,s->last_fragment,n))return s->last_result;
 size_t offset=(size_t)f[2]|((size_t)f[3]<<8),payload=n-4;
 if(f[0]&1){if(offset||s->effect.kind||now>UINT64_MAX-5000)return ack(s,2,0,s->assembled);
 if(s->effect_generation>=65535){c3_close(s);return ack(s,2,0,0);}
 wipe(s->record,sizeof s->record);
 s->assembled=0;
 s->assembly_until=now+5000;
 s->fragment_id=f[1];
 }
 if(!s->assembly_until||now>=s->assembly_until||f[1]!=s->fragment_id||offset!=s->assembled||payload>sizeof s->record-s->assembled)return ack(s,2,0,s->assembled);
 memcpy(s->record+s->assembled,f+4,payload);
 s->assembled+=payload;
 uint32_t sequence=s->assembled>=6?get32(s->record+2):0;
 int result=ack(s,0,sequence,s->assembled);
 if(f[0]&2){
  struct bt_effect effect;
 int accepted=bt_frame(&s->policy,s->record,s->assembled,now,&effect);
 int status=accepted?1:2;
  if(accepted&&effect.kind==5){if(c3_store(s->inbox_fd,effect.filename,s->policy.buffer,effect.file_bytes)){status=3;
 bt_effect_clear(&effect);
 }bt_file_release(&s->policy);
 }
  if(accepted&&status==1){
 if(effect.kind==1||effect.kind==5)s->effect_generation++;
 s->effect=effect;
 }
  bt_effect_clear(&effect);
 result=ack(s,status,sequence,s->assembled);
 wipe(s->record,sizeof s->record);
 s->assembled=0;
 s->assembly_until=0;
 }
 memcpy(s->last_fragment,f,n);
 s->last_size=n;
 s->last_result=result;
 return result;
}
int c3_take_effect(struct c3 *s,struct bt_effect *out){if(!out)return 0;
 *out=s->effect;
 bt_effect_clear(&s->effect);
 return out->kind!=0;
 }
