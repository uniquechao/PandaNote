#include "../navigation.h"
#include <stdio.h>
static int failures=0, checks=0;
#define CHECK(name,condition) do { ++checks; if(!(condition)) { fprintf(stderr,"FAIL %s line %d\n",name,__LINE__); ++failures; } } while(0)
int main() {
    CHECK("home_opens_panel", navigate(Home,OpenPanel)==Panel && hitTest(Home,376,744)==OpenPanel);
    CHECK("home_apps_rectangle",actionRect(Home,OpenPanel)==QRect(344,724,112,56));
    CHECK("home_apps_literal_boundaries",hitTest(Home,344,724)==OpenPanel && hitTest(Home,455,779)==OpenPanel && hitTest(Home,343,752)==NoAction && hitTest(Home,456,752)==NoAction && hitTest(Home,376,723)==NoAction && hitTest(Home,376,780)==NoAction);
    CHECK("home_old_apps_position_is_inactive",hitTest(Home,240,734)==NoAction);
    CHECK("home_schedule_rectangle",actionRect(Home,OpenSchedule)==QRect(24,176,432,504));
    CHECK("home_schedule_literal_boundaries",hitTest(Home,24,176)==OpenSchedule && hitTest(Home,455,679)==OpenSchedule && hitTest(Home,23,300)==NoAction && hitTest(Home,456,300)==NoAction && hitTest(Home,240,175)==NoAction && hitTest(Home,240,680)==NoAction);
    CHECK("home_status_and_date_do_not_open_schedule",hitTest(Home,240,20)==NoAction && hitTest(Home,240,100)==NoAction);
    CHECK("panel_home_rectangle",actionRect(Panel,BackHome)==QRect(8,44,64,64));
    CHECK("panel_home_literal_boundaries",hitTest(Panel,8,44)==BackHome && hitTest(Panel,71,107)==BackHome && hitTest(Panel,7,76)==NoAction && hitTest(Panel,72,76)==NoAction && hitTest(Panel,40,43)==NoAction && hitTest(Panel,40,108)==NoAction);
    CHECK("panel_home_back_opens_home",navigate(Panel,BackHome)==Home && hitTest(Panel,40,76)==BackHome);
    const Action actions[]={OpenSchedule,OpenWords,OpenNotes,OpenControl,OpenInfo};
    const Page pages[]={Schedule,Words,Notes,Control,Info};
    const int xs[]={120,360,120,360,120}, ys[]={200,200,380,380,560};
    for(int i=0;i<5;++i) {
        CHECK("app_tile_rectangle",actionRect(Panel,actions[i])==QRect(24+(i%2)*224,184+(i/2)*168,208,152));
        const int left=24+(i%2)*224,top=184+(i/2)*168;
        CHECK("app_tile_literal_boundaries",hitTest(Panel,left,top)==actions[i] && hitTest(Panel,left+207,top+151)==actions[i] && hitTest(Panel,left-1,top+76)==NoAction && hitTest(Panel,left+208,top+76)==NoAction && hitTest(Panel,left+104,top-1)==NoAction && hitTest(Panel,left+104,top+152)==NoAction);
        CHECK("subpage_back_rectangle",actionRect(pages[i],BackToPanel)==QRect(8,44,64,64));
        CHECK("subpage_home_rectangle",actionRect(pages[i],BackHome)==QRect(408,44,64,64));
        CHECK("subpage_back_literal_boundaries",hitTest(pages[i],8,44)==BackToPanel && hitTest(pages[i],71,107)==BackToPanel && hitTest(pages[i],7,76)==NoAction && hitTest(pages[i],72,76)==NoAction && hitTest(pages[i],40,43)==NoAction && hitTest(pages[i],40,108)==NoAction);
        CHECK("subpage_home_literal_boundaries",hitTest(pages[i],408,44)==BackHome && hitTest(pages[i],471,107)==BackHome && hitTest(pages[i],407,76)==NoAction && hitTest(pages[i],472,76)==NoAction && hitTest(pages[i],440,43)==NoAction && hitTest(pages[i],440,108)==NoAction);
        CHECK("five_entries_open_and_return",hitTest(Panel,xs[i],ys[i])==actions[i] && navigate(Panel,actions[i])==pages[i]);
        CHECK("five_entries_return_to_panel",navigate(pages[i],BackToPanel)==Panel && hitTest(pages[i],40,76)==BackToPanel);
        CHECK("five_entries_return_home",navigate(pages[i],BackHome)==Home && hitTest(pages[i],440,76)==BackHome);
    }
    const Page all[]={Home,Panel,Schedule,Words,Notes,Control,Info};
    const int edge[][2]={{0,0},{479,799},{-1,100},{480,400},{100,800},{10,200},{470,200}};
    for(int p=0;p<7;++p) for(int e=0;e<7;++e)
        CHECK("edge_taps_do_not_navigate",hitTest(all[p],edge[e][0],edge[e][1])==NoAction);
    CHECK("panel_sixth_grid_is_empty",hitTest(Panel,360,560)==NoAction);
    CHECK("invalid_page_action_keeps_page",navigate(Home,OpenWords)==Home && navigate(Words,OpenControl)==Words);
    CHECK("page_enum_values_stable",Home==0 && Panel==1 && Schedule==2 && Words==3 && Notes==4 && Control==5 && Info==6);
    for(int p=0;p<7;++p) CHECK("global_system_settings_entry",navigate(all[p],OpenSystemControl)==Control);
    IdleNavigation restored;
    for(int p=0;p<7;++p) {
        restored.interact(OpenSystemControl,0);
        CHECK("restore_exact_origin_page",restored.restore(all[p],1000)==all[p] && restored.page()==all[p]);
        CHECK("restore_resets_idle_deadline",restored.expire(60999)==all[p]);
        CHECK("restore_expires_at_idle_deadline",restored.expire(61000)==Home);
    }
    restored.restore(Words,70000);
    CHECK("restored_page_uses_normal_navigation",restored.interact(BackToPanel,71000)==Panel);
    IdleNavigation idle;
    idle.interact(OpenPanel,1000);
    CHECK("idle_before_60000ms",idle.expire(60999)==Panel);
    CHECK("idle_returns_home_after_60000ms",idle.expire(61000)==Home);
    idle.interact(OpenPanel,70000);idle.interact(OpenSchedule,71000);idle.interact(NoAction,130000);
    CHECK("interaction_resets_idle",idle.expire(189999)==Schedule);
    CHECK("interaction_reset_expires",idle.expire(190000)==Home);
    idle.interact(OpenPanel,200000);idle.interact(OpenInfo,201000);
    CHECK("placeholder_idle_returns_home",idle.expire(261000)==Home);
    printf("%s navigation %d checks\n",failures?"FAIL":"PASS",checks);return failures?1:0;
}
