#ifndef PANDANOTE_POWER_KEYS_H
#define PANDANOTE_POWER_KEYS_H
#include <stdint.h>
enum PowerAction { NoPowerAction,ShortPowerPress,LongPowerPress };
// Policy uses kernel event timestamps and CLOCK_MONOTONIC milliseconds only.
class PowerKeyPolicy {
public:
 PowerKeyPolicy();void baseline(bool held);void cancel();
 PowerAction observe(int value,int64_t eventMs);PowerAction tick(int64_t nowMs);
private:
 bool blocked_,down_,longSent_;int64_t pressedAt_,lastEvent_;
};
struct PowerKeyEvent { int type,code,value;int64_t milliseconds; };
enum { PowerInputSyn=0,PowerInputKey=1,PowerSyncReport=0,PowerSyncDropped=3,PowerKeyF11=87,PowerKeyPageUp=104,PowerKeyPageDown=109,PowerReadAgain=-2 };
struct PowerKeyHeldState { bool power,previous,next; };
// Narrow syscall boundary. Tests link fixture definitions, never native devices.
int powerKeyOpenCandidate(int index,bool *held);
int powerKeyOpenCandidate(int index,PowerKeyHeldState *held);
int powerKeyReadEvents(int fd,PowerKeyEvent *events,unsigned capacity);
bool powerKeyHeld(int fd,bool *held);
bool powerKeyHeld(int fd,PowerKeyHeldState *held);
// Snapshot through a separately opened, identity-checked evdev client. GETKEY
// must never flush the original client's unread human input during reset.
bool powerKeySnapshotHeld(int originalFd,bool *held);
bool powerKeySnapshotHeld(int originalFd,PowerKeyHeldState *held);
int64_t powerKeyNowMs();void powerKeyClose(int fd);
class PowerKeys {
public:
 PowerKeys();~PowerKeys();bool open();PowerAction poll();bool available()const;
 // Discard actions, drain old input, snapshot a separate client, then drain
 // raced old-client edges to establish hold/activity without replaying actions.
 // False disconnects the input; no historical edge may produce an action.
 bool resetAfterResume();
 // Any F11 edge/repeat or dropped stream makes human intent take precedence.
 int takeListNavigation(); // -1 previous/up, +1 next/down, 0 empty.
 bool takeActivity(){bool value=activity_;activity_=false;return value;}
private:
 PowerKeys(const PowerKeys &);PowerKeys &operator=(const PowerKeys &);
 void disconnect();bool enqueue(PowerAction);void navigationKey(int code,int value);
 enum { QueueSize=16 };int fd_;bool dropped_,activity_;PowerKeyPolicy policy_;
 PowerAction queue_[QueueSize];unsigned head_,count_;
 int navigationQueue_[QueueSize];unsigned navigationHead_,navigationCount_;bool navigationHeld_[2];
};
#endif
