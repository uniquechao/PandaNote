// In-memory handshake harness; synthetic bytes only, no sockets.
#include "../tls.h"
#include <QtCore/qcoreapplication.h>
#include <QtCore/qfile.h>
#include <stdio.h>
struct Pipe {QByteArray incoming,outgoing;};
static int send(void *p,unsigned char *b,int n){static_cast<Pipe *>(p)->outgoing.append(reinterpret_cast<char *>(b),n);return n;}
static int receive(void *p,unsigned char *b,int n){Pipe *pipe=static_cast<Pipe *>(p);if(pipe->incoming.isEmpty())return -1;int count=qMin(n,pipe->incoming.size());memcpy(b,pipe->incoming.constData(),count);pipe->incoming.remove(0,count);return count;}
int main(int argc,char **argv){QCoreApplication app(argc,argv);if(argc!=5)return 2;QByteArray pem;QByteArray inputPem(argv[1]);if(inputPem.startsWith("pem64:"))pem=QByteArray::fromBase64(inputPem.mid(6));else{QFile f(argv[1]);if(!f.open(QIODevice::ReadOnly))return 2;pem=f.read(16385);}Pipe pipe;DeviceTls tls;QString error;if(!tls.configure(argv[2],pem,argv[3],QString(argv[4]).toLongLong(),&pipe,send,receive,&error)){printf("TLS_RESULT=fail:%s\n",error.toLatin1().constData());return 0;}
 for(int loops=0;loops<40;++loops){int result=tls.handshake(&error);if(result){printf("TLS_RESULT=%s:%s\n",result==1?"ok":"fail",error.toLatin1().constData());return 0;}printf("TLS_OUT=%s\n",pipe.outgoing.toHex().constData());fflush(stdout);pipe.outgoing.clear();char buffer[131073];if(!fgets(buffer,sizeof(buffer),stdin))return 3;QByteArray input(buffer);input=input.trimmed();if(!input.startsWith("TLS_IN="))return 3;pipe.incoming+=QByteArray::fromHex(input.mid(7));}
 return 4;
}
