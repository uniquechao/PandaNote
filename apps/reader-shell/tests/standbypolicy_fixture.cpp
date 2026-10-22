#include "../standbypolicy.h"
#include <stdio.h>
static int failures=0,checks=0;
#define CHECK(n,c) do{++checks;if(!(c)){++failures;fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);}}while(0)
int main(){
 StandbyMaintenance p;CHECK("inactive_does_not_finish",!p.active()&&!p.finish(0,false,false));
 CHECK("invalid_clock_cannot_begin",!p.begin(-1)&&!p.active());
 CHECK("overflow_clock_cannot_begin",!p.begin(0x7fffffffffffffffLL-29999)&&!p.active());
 CHECK("timer_begins",p.begin(1000)&&p.active());CHECK("no_authentication_yet",!p.finish(1001,false,false));
 CHECK("transient_connect_waits",!p.finish(1001,false,false));CHECK("just_before_deadline_waits",!p.finish(30999,true,false));
 CHECK("deadline_ends_even_pending_dns_or_paint",p.finish(31000,true,false));
 p.begin(1000);p.authenticatedContact();CHECK("fresh_contact_waits_for_resources_paint_ack",!p.finish(1200,true,false));CHECK("pipeline_done_finishes",p.finish(1300,false,false));
 p.begin(0);CHECK("tls_or_protocol_failure_finishes_early",p.finish(10,false,true));CHECK("terminal_failure_still_drains_active_pipeline",!p.finish(10,true,true));
 p.begin(1000);CHECK("backward_clock_finishes_safely",p.finish(999,true,false));CHECK("failed_clock_finishes_safely",p.finish(-1,true,false));
 p.cancel();CHECK("human_wake_cancels_timer_state",!p.active()&&!p.finish(50000,false,true));p.authenticatedContact();CHECK("contact_cannot_start_maintenance",!p.active());
 p.begin(2000);CHECK("new_cycle_does_not_reuse_previous_contact",!p.finish(2001,false,false));
 printf("%d checks, %d failures\n",checks,failures);return failures?1:0;
}
