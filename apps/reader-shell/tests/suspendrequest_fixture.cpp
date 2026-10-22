#include "../powerrequest.h"
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdio.h>
#include <string.h>
#include <string>
static int checks=0,failures=0;
#define CHECK(n,x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
static void put(const std::string &p,const char *s){int f=open(p.c_str(),O_WRONLY|O_CREAT|O_TRUNC,0600);if(f>=0){write(f,s,strlen(s));close(f);}}
int main(int argc,char **argv){if(argc!=2)return 2;std::string d=argv[1];char gen[49];CHECK("missing_capability",!readSuspendGeneration(d.c_str(),gen));
put(d+"/suspend.ready","suspend-v1 581-106\n");CHECK("legacy_capability_rejected",!readSuspendGeneration(d.c_str(),gen));
put(d+"/suspend.ready","suspend-v2 581-106\n");CHECK("read_generation",readSuspendGeneration(d.c_str(),gen)&&!strcmp(gen,"581-106"));
CHECK("publish_suspend",publishSuspendRequest(d.c_str(),gen,"1120-1"));CHECK("never_overwrite",!publishSuspendRequest(d.c_str(),gen,"1120-2"));
CHECK("wake_intent_publish",publishSuspendWakeIntent(d.c_str(),gen,"1120-1"));
CHECK("wake_intent_idempotent",publishSuspendWakeIntent(d.c_str(),gen,"1120-1"));
CHECK("foreign_token_cannot_publish",!publishSuspendWakeIntent(d.c_str(),gen,"1120-2"));
CHECK("missing_input_ready",!suspendInputReady(d.c_str(),gen,"1120-1"));
CHECK("input_ack_requires_fresh_ready",!acknowledgeSuspendInput(d.c_str(),gen,"1120-1"));
put(d+"/suspend.input-ready-1120-1","input-ready-v2 581-106 1120-1\n");
CHECK("fresh_input_ready",suspendInputReady(d.c_str(),gen,"1120-1"));
CHECK("foreign_ready_generation",!suspendInputReady(d.c_str(),"581-107","1120-1"));
CHECK("fresh_input_ready_ack",acknowledgeSuspendInput(d.c_str(),gen,"1120-1"));
CHECK("input_ack_idempotent",acknowledgeSuspendInput(d.c_str(),gen,"1120-1"));
put(d+"/suspend.input-ready-1120-2","input-ready-v2 581-106 1120-1\n");
CHECK("input_ready_foreign_token_rejected",!acknowledgeSuspendInput(d.c_str(),gen,"1120-2"));
unlink((d+"/suspend.input-ready-1120-2").c_str());
CHECK("no_reply_yet",readSuspendReply(d.c_str(),gen,"1120-1")==NoSuspendReply);
put(d+"/resume.status","resume-v2 581-106 1120-2 resumed\n");CHECK("stale_token_ignored",readSuspendReply(d.c_str(),gen,"1120-1")==NoSuspendReply);
put(d+"/resume.status","resume-v2 582-106 1120-1 resumed\n");CHECK("stale_generation_ignored",readSuspendReply(d.c_str(),gen,"1120-1")==NoSuspendReply);
put(d+"/resume.status","resume-v2 581-106 1120-1 resumed\n");CHECK("matching_resume",readSuspendReply(d.c_str(),gen,"1120-1")==SuspendResumed);
CHECK("old_enum_values",NoSuspendReply==0&&SuspendResumed==1&&SuspendRejected==2);
put(d+"/resume.status","resume-v2 581-106 1120-1 timer\n");CHECK("matching_timer",readSuspendReply(d.c_str(),gen,"1120-1")==SuspendTimerResumed);
put(d+"/resume.status","resume-v1 581-106 1120-1 timer\n");CHECK("legacy_timer_rejected",readSuspendReply(d.c_str(),gen,"1120-1")==NoSuspendReply);
const char *reasons[]={"busy","unsafe","failed"};for(int i=0;i<3;++i){std::string s="resume-v2 581-106 1120-1 "+std::string(reasons[i])+"\n";put(d+"/resume.status",s.c_str());CHECK("rejection_terminal",readSuspendReply(d.c_str(),gen,"1120-1")==SuspendRejected);}
put(d+"/resume.status","resume-v2 581-106 1120-1 resumed\nextra\n");CHECK("extra_lines_ignored",readSuspendReply(d.c_str(),gen,"1120-1")==NoSuspendReply);
unlink((d+"/suspend.request").c_str());CHECK("bad_generation",!publishSuspendRequest(d.c_str(),"581-106\nX","1120-1"));CHECK("bad_token",!publishSuspendRequest(d.c_str(),gen,"1120-0"));CHECK("leading_zero",!publishSuspendRequest(d.c_str(),"0581-106","1120-1"));
unlink((d+"/suspend.ready").c_str());symlink("resume.status",(d+"/suspend.ready").c_str());CHECK("ready_symlink_rejected",!readSuspendGeneration(d.c_str(),gen));unlink((d+"/suspend.ready").c_str());
put(d+"/suspend.ready","suspend-v2 581-106\n");chmod((d+"/suspend.ready").c_str(),0644);CHECK("public_ready_rejected",!readSuspendGeneration(d.c_str(),gen));chmod((d+"/suspend.ready").c_str(),0600);
symlink("resume.status",(d+"/suspend.request").c_str());CHECK("symlink_final_rejected",!publishSuspendRequest(d.c_str(),"581-106","1120-1"));unlink((d+"/suspend.request").c_str());
chmod(d.c_str(),0755);CHECK("public_directory_rejected",!publishSuspendRequest(d.c_str(),"581-106","1120-1"));chmod(d.c_str(),0700);
unlink((d+"/resume.status").c_str());
put(d+"/suspend.request","suspend-v2 581-106 1120-1\n");put(d+"/suspend.active","suspend-v2 581-106 1120-1\n");
int lock=open((d+"/normal-install.lock").c_str(),O_RDWR|O_CREAT,0600);CHECK("lease_fixture",lock>=0&&flock(lock,LOCK_EX|LOCK_NB)==0);
CHECK("cancel_cannot_race_mem",!cancelSuspendRequest(d.c_str(),d.c_str(),"581-106","1120-1")&&access((d+"/suspend.active").c_str(),F_OK)==0);
flock(lock,LOCK_UN);close(lock);
CHECK("cancel_rejects_foreign_token",!cancelSuspendRequest(d.c_str(),d.c_str(),"581-106","1120-2"));
CHECK("cancel_under_lease",cancelSuspendRequest(d.c_str(),d.c_str(),"581-106","1120-1"));
CHECK("cancel_removes_both_queued_names",access((d+"/suspend.request").c_str(),F_OK)!=0&&access((d+"/suspend.active").c_str(),F_OK)!=0);
CHECK("cancel_removes_matching_wake_marker",access((d+"/suspend.wake-1120-1").c_str(),F_OK)!=0);
CHECK("cancel_removes_matching_input_handshake",access((d+"/suspend.input-ready-1120-1").c_str(),F_OK)!=0&&access((d+"/suspend.input-allow-1120-1").c_str(),F_OK)!=0);
printf("%s SUSPEND_REQUEST %d checks\n",failures?"FAIL":"PASS",checks);return failures?1:0;}
