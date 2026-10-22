#ifndef PANDANOTE_STARTUP_SYNC_RETRY_H
#define PANDANOTE_STARTUP_SYNC_RETRY_H
#include <string.h>
// A process-lifetime startup grace period, measured only by monotonic elapsed
// milliseconds. It neither changes TLS validation nor creates requests itself.
class StartupSyncRetry {
public:
    StartupSyncRetry():started_(false),authenticated_(false),firstAttempt_(0),retries_(0),fastPending_(false),fastDeadline_(0),normalDeadline_(0){}
    void beginAttempt(long long now) {
        if(!started_){started_=true;firstAttempt_=now;}
    }
    long long delayAfterResult(long long now,const char *error,long long normalDelay,bool authenticatedContact) {
        fastPending_=false;
        if(authenticatedContact)authenticated_=true;
        // Exact transport codes only. In particular TLS, HTTP status, content
        // validation and unknown errors retain the ordinary poll interval.
        // http-send/truncated also represent fatal TLS record errors, so are
        // deliberately excluded rather than guessed to be transient transport.
        bool transport=error&&(!strcmp(error,"http-socket")||!strcmp(error,"http-connect")||!strcmp(error,"http-timeout"));
        if(!started_||authenticated_||!transport||now<firstAttempt_||retries_>=5)return normalDelay;
        const long long delays[]={2000,5000,10000,20000,30000};
        long long age=now-firstAttempt_,delay=delays[retries_];
        if(age>=90000||delay>90000-age)return normalDelay;
        fastPending_=true;fastDeadline_=now+delay;normalDeadline_=now+normalDelay;
        ++retries_;return delay;
    }
    long long pollDeadline(long long now,long long currentDeadline) {
        if(!fastPending_)return currentDeadline;
        // A manual refresh/configuration can replace nextPoll_. Only reconsider
        // the automatic deadline actually issued by this policy.
        if(currentDeadline!=fastDeadline_){fastPending_=false;return currentDeadline;}
        if(now>=firstAttempt_&&now-firstAttempt_>90000){
            fastPending_=false;return normalDeadline_;
        }
        return currentDeadline;
    }
private:
    bool started_,authenticated_;long long firstAttempt_;unsigned retries_;
    bool fastPending_;long long fastDeadline_,normalDeadline_;
};
#endif
