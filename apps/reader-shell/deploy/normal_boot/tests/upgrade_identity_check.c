/* Pure actual production checks; no device identity, kill, or mount invocation. */
#define PANDANOTE_FIXTURE
#define PANDANOTE_NORMAL_UPGRADE
#define main unused_apply_entry
#include "../apply_tool.c"
#undef main
int main(int argc,char**argv){
 if(argc==8&&!strcmp(argv[1],"stat")){char b[4096];FILE*f=fopen(argv[2],"rb");if(!f)return 2;size_t n=fread(b,1,sizeof b-1,f);fclose(f);b[n]=0;struct upgrade_process p;memset(&p,0,sizeof p);p.pid=atol(argv[3]);p.ppid=atol(argv[4]);p.pgid=atol(argv[5]);p.sid=atol(argv[6]);p.start=strtoull(argv[7],NULL,10);return upgrade_stat_fields(&p,b)?1:0;}
 if(argc==6&&!strcmp(argv[1],"argv")){unsigned char b[8192];FILE*f=fopen(argv[2],"rb");if(!f)return 2;size_t n=fread(b,1,sizeof b,f);fclose(f);if(!ishex(argv[4],24)||!ishex(argv[5],64))return 2;strcpy(upgrade_oldboot,argv[4]);strcpy(upgrade_oldnative,argv[5]);return upgrade_argv(atoi(argv[3]),b,n)?1:0;}
 return 2;
}
