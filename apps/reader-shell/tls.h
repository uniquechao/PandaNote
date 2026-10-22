#ifndef PANDANOTE_TLS_H
#define PANDANOTE_TLS_H
#include <QtCore/qbytearray.h>
#include <QtCore/qstring.h>
#include <QtCore/qglobal.h>
struct DeviceTlsState;
// Callbacks use nonblocking socket semantics: positive bytes, 0 EOF, or -1
// for EAGAIN. DeviceHttp owns the socket and enforces the whole request deadline.
class DeviceTls {
public:
 typedef int (*Io)(void *,unsigned char *,int);
 DeviceTls();~DeviceTls();
// DNS profiles pin one CA DER trust anchor and require its verified chain,
 // exact DNS SAN and SNI. Numeric profiles retain peer DER pin and IP SAN.
 bool configure(const QString &host,const QByteArray &pem,const QString &pin,qint64 epoch,void *context,Io send,Io recv,QString *error);
 int handshake(QString *error);int write(const unsigned char *,int);int read(unsigned char *,int);
 void trustEpoch(qint64 epoch);void reset();
private:DeviceTlsState *state_;
};
#endif
