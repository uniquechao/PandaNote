/* NORMAL-only wire/proof validation, also compiled into native clone tests. */
#define UPGRADE_BUSYBOX "38081195a5342faafac704f96bec8fb5b4de7a706f74dab88e5c184374f9a593"
static char upgrade_oldnative[65],upgrade_oldboot[25],upgrade_current[65],upgrade_sb[65];
static char upgrade_newnative[65],upgrade_newboot[25],upgrade_oldentry[65];
static struct item upgrade_checks[MAX_FILES];static unsigned upgrade_count;
struct upgrade_process {long pid,ppid,pgid,sid;unsigned long long start;char exe[65],cmd[65];};
static struct upgrade_process upgrade_processes[4];static char upgrade_cmdline[65];
static int upgrade_active_new,upgrade_handed_off;
static int upgrade_line(const unsigned char*b,size_t len,size_t*pos,char*line,size_t cap){size_t start=*pos;while(*pos<len&&b[*pos]!='\n'){if(!b[*pos])return -1;(*pos)++;}if(*pos==len||*pos-start>=cap)return -1;memcpy(line,b+start,*pos-start);line[*pos-start]=0;(*pos)++;return 0;}
static int upgrade_base(const unsigned char*b,size_t len,size_t*pos,const char*newboot,const char*newnative,const char*oldsha){
 char line[1024],tag[32],package[65],extra,system[96],release[128];unsigned n;
 if(upgrade_line(b,len,pos,line,sizeof line)||sscanf(line,"%31s %64s %64s %24s %64s %64s %u %c",tag,package,upgrade_oldnative,upgrade_oldboot,upgrade_current,upgrade_sb,&n,&extra)!=7||strcmp(tag,"BASE")||!ishex(package,64)||!ishex(upgrade_oldnative,64)||!ishex(upgrade_oldboot,24)||!ishex(upgrade_current,64)||!ishex(upgrade_sb,64)||n<4||n>MAX_FILES||!strcmp(upgrade_oldnative,newnative)||!strcmp(upgrade_oldboot,newboot))return -1;
 strcpy(upgrade_newboot,newboot);strcpy(upgrade_newnative,newnative);strcpy(upgrade_oldentry,oldsha);upgrade_count=n;
 snprintf(system,sizeof system,"/etc/pandanote-system/%s/",upgrade_oldboot);snprintf(release,sizeof release,"/user/pandanote/apps/releases/%s/",upgrade_oldnative);
 for(unsigned i=0;i<n;i++){struct item*t=&upgrade_checks[i];unsigned long z;unsigned mode;
  if(upgrade_line(b,len,pos,line,sizeof line)||sscanf(line,"%31s %o %lu %64s %511s %c",tag,&mode,&z,t->sha,t->path,&extra)!=5||strcmp(tag,"CHECK")||!safechar(t->path)||!ishex(t->sha,64)||z>MAX_BUNDLE)return -1;
  if(!strncmp(t->path,system,strlen(system))){if(mode!=0600)return -1;}else if(!strncmp(t->path,release,strlen(release))){if(mode!=0600&&mode!=0700)return -1;}else return -1;
  t->mode=mode;t->len=z;
  for(unsigned j=0;j<i;j++){size_t a=strlen(t->path),c=strlen(upgrade_checks[j].path);if(!strcmp(t->path,upgrade_checks[j].path)||(a<c&&!strncmp(t->path,upgrade_checks[j].path,a)&&upgrade_checks[j].path[a]=='/')||(c<a&&!strncmp(t->path,upgrade_checks[j].path,c)&&t->path[c]=='/'))return -1;}
 }
 char required[512];const char*names[]={"service.sh","SHA256SUMS"};
 for(unsigned i=0;i<2;i++){int found=0;snprintf(required,sizeof required,"%s%s",system,names[i]);for(unsigned j=0;j<n;j++)if(!strcmp(upgrade_checks[j].path,required))found=1;if(!found)return -1;}
 snprintf(required,sizeof required,"%sreader-shell.mipsel",release);for(unsigned j=0;j<n;j++)if(!strcmp(upgrade_checks[j].path,required))return 0;return -1;
}
static int upgrade_check_file(const struct item*t){int fd=regfd(t->path,0);struct stat s;SHA256_CTX c;unsigned char b[8192],h[32];char out[65];ssize_t n;size_t total=0;
 if(fd<0)return -1;if(fstat(fd,&s)||(s.st_mode&07777)!=t->mode||(uint64_t)s.st_size!=t->len){close(fd);return -1;}sha256_init(&c);
 while((n=read(fd,b,sizeof b))>0){total+=(size_t)n;if(total>t->len){close(fd);return -1;}sha256_update(&c,b,(size_t)n);}close(fd);if(n<0||total!=t->len)return -1;sha256_final(&c,h);for(unsigned i=0;i<32;i++)sprintf(out+2*i,"%02x",h[i]);out[64]=0;return strcmp(out,t->sha)?-1:0;
}
static const char*upgrade_elf(int newversion){char path[160];snprintf(path,sizeof path,"/user/pandanote/apps/releases/%s/reader-shell.mipsel",newversion?upgrade_newnative:upgrade_oldnative);struct item*set=newversion?items:upgrade_checks;unsigned n=newversion?count:upgrade_count;for(unsigned i=0;i<n;i++)if(!strcmp(set[i].path,path))return set[i].sha;return NULL;}
static int upgrade_proof(const char*path,const char*expected){struct stat s;int fd=open(path,O_RDONLY|O_NOFOLLOW|O_CLOEXEC);unsigned char buf[4096];size_t len=0,pos=0;char h[65],line[1024],tag[32],active[8],extra;const char*roles[]={"service","adbd","supervisor","native"};
 if(!ishex(expected,64)||fd<0)return -1;if(fstat(fd,&s)||!S_ISREG(s.st_mode)||!owner(&s)||s.st_nlink!=1||s.st_size<100||s.st_size>=sizeof buf){close(fd);return -1;}
 while(len<(size_t)s.st_size){ssize_t n=read(fd,buf+len,(size_t)s.st_size-len);if(n<=0){close(fd);return -1;}len+=(size_t)n;}close(fd);hex(buf,len,h);if(strcmp(h,expected))return -1;
 if(upgrade_line(buf,len,&pos,line,sizeof line)||sscanf(line,"%31s %7s %64s %c",tag,active,upgrade_cmdline,&extra)!=3||strcmp(tag,"PANDANOTE-NORMAL-PROOF-1")||!ishex(upgrade_cmdline,64))return -1;
 if(!strcmp(active,"new"))upgrade_active_new=1;else if(strcmp(active,"old"))return -1;if(upgrade_active_new&&!rollback_mode)return -1;
 const char*elf=upgrade_elf(upgrade_active_new);if(!elf)return -1;
 for(unsigned i=0;i<4;i++){struct upgrade_process*p=&upgrade_processes[i];
  if(upgrade_line(buf,len,&pos,line,sizeof line)||sscanf(line,"%31s %ld %ld %ld %ld %llu %64s %64s %c",tag,&p->pid,&p->ppid,&p->pgid,&p->sid,&p->start,p->exe,p->cmd,&extra)!=8||strchr(line,'-')||strcmp(tag,roles[i])||p->pid<2||p->pid>4194304||p->ppid<1||p->ppid>4194304||p->pgid<1||p->pgid>4194304||p->sid<1||p->sid>4194304||!p->start||!ishex(p->exe,64)||!ishex(p->cmd,64)||strcmp(p->exe,i==3?elf:UPGRADE_BUSYBOX))return -1;
  for(unsigned j=0;j<i;j++)if(p->pid==upgrade_processes[j].pid)return -1;
 }
 struct upgrade_process*srv=&upgrade_processes[0],*adb=&upgrade_processes[1],*app=&upgrade_processes[2],*native=&upgrade_processes[3];
 if(pos!=len||srv->ppid!=1||adb->ppid!=srv->pid||adb->pgid!=adb->pid||adb->sid!=adb->pid||app->ppid!=srv->pid||app->pgid!=app->pid||app->sid!=app->pid||native->ppid!=app->pid||native->pgid!=app->pid||native->sid!=app->pid)return -1;
 return 0;
}
static int upgrade_closure(void){for(unsigned i=0;i<upgrade_count;i++)if(upgrade_check_file(&upgrade_checks[i]))return -1;
 if(upgrade_active_new)for(unsigned i=0;i<count;i++)if((!strcmp(items[i].role,"system")||!strcmp(items[i].role,"release"))&&upgrade_check_file(&items[i]))return -1;
 return 0;
}
static int upgrade_pointer(void){size_t n;unsigned char*b=readreg("/user/pandanote/apps/current",&n,0);char h[65];if(!b)return -1;hex(b,n,h);free(b);int match=!strcmp(h,upgrade_current);if(rollback_mode)for(unsigned i=0;i<count;i++)if(!strcmp(items[i].role,"pointer")&&!strcmp(h,items[i].sha))match=1;if(!match)return -1;
 int fd=regfd("/user/pandanote/apps/current",0);struct stat s;if(fd<0)return -1;int bad=fstat(fd,&s)||(s.st_mode&07777)!=0600;close(fd);if(bad)return -1;
 b=readreg("/etc/inittab",&n,0);if(!b)return -1;hex(b,n,h);free(b);int entryfd=regfd("/etc/inittab",0);if(entryfd<0)return -1;bad=fstat(entryfd,&s)||(s.st_mode&07777)!=0644;close(entryfd);if(bad)return -1;match=!strcmp(h,upgrade_oldentry);if(rollback_mode)for(unsigned i=0;i<count;i++)if(!strcmp(items[i].role,"entry")&&!strcmp(h,items[i].sha))match=1;return match?0:-1;
}

/* Pure production process/argv predicates: exercised with fabricated proc streams. */
static int upgrade_stat_fields(const struct upgrade_process*p,const char*input){
 char copy[4096],*tail,*save,*token,*end;unsigned index=0;long reported,values[3]={0};unsigned long long begun=0;
 if(strlen(input)>=sizeof copy||sscanf(input,"%ld",&reported)!=1||reported!=p->pid)return -1;strcpy(copy,input);tail=strrchr(copy,')');if(!tail)return -1;
 for(token=strtok_r(tail+1," \n",&save);token;token=strtok_r(NULL," \n",&save),index++){
  if(index==0){if(strlen(token)!=1||strchr("ZXTt",*token))return -1;}
  else if(index<=3){errno=0;long value=strtol(token,&end,10);if(errno||*end||value<1)return -1;values[index-1]=value;}
  else if(index==19){errno=0;begun=strtoull(token,&end,10);if(errno||*end||*token=='-'||!begun)return -1;break;}
 }
 return index!=19||values[0]!=p->ppid||values[1]!=p->pgid||values[2]!=p->sid||begun!=p->start?-1:0;
}
static int upgrade_argv(unsigned role,const unsigned char*cmd,size_t cmdlen){
 if(role>3)return -1;char want[256];const char*boot=upgrade_active_new?upgrade_newboot:upgrade_oldboot;const char*native=upgrade_active_new?upgrade_newnative:upgrade_oldnative;
 if(role<3){char expected[512],script[160];size_t len=0;const char*args[]={"/bin/busybox","sh",NULL,"/run/pandanote-normal",role==1?"adbd":"app"};snprintf(script,sizeof script,"/etc/pandanote-system/%s/%s",boot,role==0?"service.sh":"child-supervisor.sh");args[2]=script;
  for(unsigned i=0;i<(role==0?3u:5u);i++){size_t z=strlen(args[i])+1;memcpy(expected+len,args[i],z);len+=z;}return cmdlen<len||memcmp(cmd,expected,len)||(role==0&&cmdlen!=len)?-1:0;
 }
 snprintf(want,sizeof want,"/user/pandanote/apps/releases/%s/reader-shell.mipsel",native);size_t z=strlen(want)+1;return cmdlen<z||memcmp(cmd,want,z)?-1:0;
}
