/* Production pure SB/identity checks only; never call capture/kill/remount. */
#define PANDANOTE_FIXTURE
#define main unused_apply_entry
#include "../apply_tool.c"
#undef main
int main(int argc,char**argv){
 if(argc==4&&!strcmp(argv[1],"distinct"))return distinct_supervisors(atoi(argv[2]),atoi(argv[3]))?0:1;
 if(argc==4&&!strcmp(argv[1],"superblock")){unsigned char b[1024];FILE*f=fopen(argv[2],"rb");if(!f)return 2;size_t n=fread(b,1,sizeof b,f);fclose(f);return n==1024&&superblock_compatible(b,atoi(argv[3]))?0:1;}
 if(argc==8&&!strcmp(argv[1],"supervisor")){char statbuf[4096];unsigned char cmd[1024];unsigned long long start=0;FILE*f=fopen(argv[4],"r");if(!f)return 2;size_t n=fread(statbuf,1,sizeof statbuf-1,f);fclose(f);statbuf[n]=0;f=fopen(argv[6],"rb");if(!f)return 2;n=fread(cmd,1,sizeof cmd,f);fclose(f);int r=supervisor_fields(atoi(argv[2]),atoi(argv[3]),statbuf,argv[5],cmd,n,strtoull(argv[7],NULL,10),&start);printf("result=%d start=%llu\n",r,start);return r?1:0;}
 return 2;
}
