#ifndef PANDANOTE_BLUETOOTH_H
#define PANDANOTE_BLUETOOTH_H
#include <QtCore/qstring.h>
#include <QtCore/qbytearray.h>
#include <QtCore/qelapsedtimer.h>
struct BluetoothReply {
 bool accepted;unsigned flags,grants,control,passkey,remainingMs,effectKind,fileBytes,eventId;QByteArray nonce,peer;
 BluetoothReply():accepted(false),flags(0),grants(0),control(0),passkey(0),remainingMs(0),effectKind(0),fileBytes(0),eventId(0){}
 bool pending()const{return flags&1;}bool approved()const{return flags&2;}bool active()const{return flags&4;}
};
class BluetoothClient {
public:
 BluetoothClient();~BluetoothClient();bool configure(const QString &path);bool configured()const{return !path_.isEmpty();}
 bool request(unsigned op,unsigned grants=0,bool allow=false,const QByteArray &nonce=QByteArray());
 bool ack(const QByteArray &nonce,unsigned eventId);bool poll();bool busy()const{return fd_>=0;}void cancel();
 const BluetoothReply &reply()const{return reply_;}QString error()const{return error_;}unsigned operation()const{return operation_;}bool ackRequest()const{return ack_;}
private:
 BluetoothClient(const BluetoothClient &);BluetoothClient &operator=(const BluetoothClient &);
 QString path_,error_;int fd_,sent_;bool connecting_,ack_;unsigned operation_;QByteArray request_,received_,expectedNonce_;QElapsedTimer clock_;BluetoothReply reply_;
 bool begin(const QByteArray &request);bool fail(const char *code);bool decode();
};
class BluetoothDelivery {
 QByteArray nonce_;unsigned id_;
public:
 BluetoothDelivery():id_(0){}bool applied(const BluetoothReply &r)const{return id_&&id_==r.eventId&&nonce_==r.nonce;}
 void remember(const BluetoothReply &r){nonce_=r.nonce;id_=r.eventId;}
 void observe(const BluetoothReply &r){if(r.nonce!=nonce_||(!r.approved()&&!r.active())){nonce_.clear();id_=0;}}
};
#endif
