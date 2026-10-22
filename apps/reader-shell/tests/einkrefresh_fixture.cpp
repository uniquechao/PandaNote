#include "../einkrefresh.h"
#include <stdio.h>
#include <string>
using std::string;
struct Fake: EinkRefreshIo {
 string calls; bool available,locked,armFail,panFail,restoreFail,wrongArm,wrongRestore; int mode;
 Fake():available(true),locked(false),armFail(false),panFail(false),restoreFail(false),wrongArm(false),wrongRestore(false),mode(0){}
 bool ready(){calls+="ready;";return available;}
 void grab(){calls+="lock;";locked=true;}
 void ungrab(){calls+="unlock;";locked=false;}
 bool readMode(int *m){calls+="read;";*m=mode;return true;}
 bool writeMode(int m){calls+=m?"arm;":"restore;";if(m){mode=wrongArm?0:1;return !armFail;}mode=wrongRestore?1:0;return !restoreFail;}
 bool pan(){calls+="pan;";return !panFail;}
};
static int failures=0,checks=0;
#define CHECK(x) do{++checks;if(!(x)){++failures;fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);}}while(0)
int main(){
 {Fake f;CHECK(performFullRefresh(f)==EinkRefreshOk);CHECK(f.calls=="ready;lock;read;arm;read;pan;restore;read;unlock;");CHECK(f.mode==0&&!f.locked);}
 {Fake f;f.available=false;CHECK(performFullRefresh(f)==EinkRefreshUnavailable);CHECK(f.calls=="ready;");}
 for(int mode=1;mode<=3;++mode){Fake f;f.mode=mode;CHECK(performFullRefresh(f)==EinkRefreshBusy);CHECK(f.mode==mode&&!f.locked);CHECK(f.calls=="ready;lock;read;unlock;");}
 {Fake f;f.armFail=true;CHECK(performFullRefresh(f)==EinkRefreshArmFailed);CHECK(f.mode==0&&!f.locked);CHECK(f.calls.find("pan;")==string::npos);CHECK(f.calls.find("restore;")!=string::npos);}
 {Fake f;f.wrongArm=true;CHECK(performFullRefresh(f)==EinkRefreshArmFailed);CHECK(f.mode==0&&!f.locked);CHECK(f.calls.find("pan;")==string::npos);}
 {Fake f;f.panFail=true;CHECK(performFullRefresh(f)==EinkRefreshPanFailed);CHECK(f.mode==0&&!f.locked);CHECK(f.calls.find("pan;restore;read;unlock;")!=string::npos);}
 {Fake f;f.restoreFail=true;CHECK(performFullRefresh(f)==EinkRefreshRestoreFailed);CHECK(!f.locked);}
 {Fake f;f.wrongRestore=true;CHECK(performFullRefresh(f)==EinkRefreshRestoreFailed);CHECK(!f.locked);}
 printf("%s EINK_POLICY %d checks\n",failures?"FAIL":"PASS",checks);return failures?1:0;
}
