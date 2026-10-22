#include <stdint.h>
#include <stdio.h>
typedef int64_t qint64;
static qint64 bootMs=0,monoMs=0;
qint64 contentBootTimeMs(){return bootMs;}
class QElapsedTimer {
 bool valid_;qint64 at_;
public:
 QElapsedTimer():valid_(false),at_(0){}static bool isMonotonic(){return true;}
 void invalidate(){valid_=false;}void start(){valid_=true;at_=monoMs;}
 bool isValid()const{return valid_;}qint64 elapsed()const{return monoMs-at_;}
};
const qint64 MinEpoch=946684800LL,MaxEpoch=4133980800LL;
/* ACTUAL CLASS */
/* ACTUAL METHODS */
static int checks=0,failures=0;
#define CHECK(n,c) do{++checks;if(!(c)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
int main(){
 TimeAnchor anchor;qint64 now=-1;CHECK("not_trusted_before_auth",!anchor.nowEpoch(&now)&&now==-1);
 bootMs=1000000;monoMs=5000;CHECK("authenticated_anchor",anchor.establish(1792640000LL)&&anchor.nowEpoch(&now)&&now==1792640000LL);
 bootMs=2800123;monoMs=5123;CHECK("suspended_30_minutes_included",anchor.nowEpoch(&now)&&now==1792641800LL);
 bootMs=2800999;CHECK("subsecond_not_rounded_up",anchor.nowEpoch(&now)&&now==1792641800LL);
 bootMs=999999;CHECK("backward_boot_clock_rejected",!anchor.nowEpoch(&now));
 bootMs=-1;CHECK("unavailable_clock_rejected",!anchor.establish(1792640000LL)&&!anchor.nowEpoch(&now));
 bootMs=10;CHECK("reestablish_after_clock_returns",anchor.establish(1792640000LL));
 bootMs=-1;CHECK("unavailable_read_rejected",!anchor.nowEpoch(&now));
 bootMs=20;CHECK("invalid_epoch_does_not_retain_old_anchor",!anchor.establish(0)&&!anchor.nowEpoch(&now));
 bootMs=30;CHECK("near_max_anchor",anchor.establish(4133980799LL));bootMs=1030;CHECK("epoch_overflow_rejected",!anchor.nowEpoch(&now));
 bootMs=0;CHECK("zero_boottime_is_valid",anchor.establish(1792640000LL)&&anchor.nowEpoch(&now)&&now==1792640000LL);
 anchor.invalidate();CHECK("explicit_invalidation",!anchor.nowEpoch(&now));CHECK("null_output",!anchor.nowEpoch(0));
 printf("%d checks, %d failures\n",checks,failures);return failures?1:0;
}
