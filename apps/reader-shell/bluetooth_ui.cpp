#include "shell.h"
#include <QtGui/qpainter.h>
#include <QtGui/qfontmetrics.h>
static QString btText(const char *s){return QString::fromUtf8(s);}
static QFont btFont(const QFont &base,int size,bool bold=false){QFont f(base);f.setPixelSize(size);f.setBold(bold);return f;}
static QString peerText(const QByteArray &peer){QString s;for(int i=0;i<peer.size();++i){if(i)s+=':';s+=QString("%1").arg(uchar(peer[i]),2,16,QChar('0'));}return s.toUpper();}
bool ReaderShell::configureBluetooth(const QString &path){
 if(bt_.timer)killTimer(bt_.timer);bt_=BluetoothUiState();bool ok=bluetooth_.configure(path);
 // A syntactically valid intended path may precede service startup. Only the
 // strict client may promote it to configured; the UI never creates its parent.
 if(ok||bluetooth_.error()=="bluetooth-private-directory"){
  bt_.intendedPath=path;bt_.configureNext=monotonicMs()+1000;
 }
 bt_.message=ok?btText("等待联系本地蓝牙服务"):btText("蓝牙入口不可用；等待本机私有服务目录");
 if(!bt_.intendedPath.isEmpty())bt_.timer=startTimer(25);update();return ok;
}
bool ReaderShell::bluetoothPending()const{return bt_.available&&bt_.reply.pending()&&monotonicMs()<bt_.pendingUntil&&!bt_.cancelRequested;}
bool ReaderShell::bluetoothActive()const{return bt_.available&&bt_.reply.active()&&monotonicMs()<bt_.sessionUntil;}
QString ReaderShell::bluetoothPasskey()const{return bluetoothPending()?QString("%1").arg(bt_.reply.passkey,6,10,QChar('0')):QString();}
QString ReaderShell::bluetoothStatusText()const{
 if(!bluetooth_.configured())return btText("未配置本地蓝牙服务入口");
 if(!bt_.available)return btText("蓝牙服务暂不可联系 · 状态未核验");
 if(bt_.cancelRequested)return btText("正在关闭配对窗口或手机会话");
 if(bluetoothPending())return btText("等待本机确认 · ")+QString::number(qMax(qint64(0),bt_.pendingUntil-monotonicMs()+999)/1000)+btText(" 秒");
 if(bluetoothActive())return btText("手机会话活动（服务报告）");
 if(bt_.reply.approved())return btText("已在本机允许 · 等待安全连接");
 if(bt_.windowUntil>monotonicMs())return btText("配对窗口 · 剩余 ")+QString::number((bt_.windowUntil-monotonicMs()+999)/1000)+btText(" 秒");
 return btText("无已确认手机会话");
}
bool ReaderShell::sendBluetooth(unsigned op,unsigned grants,bool allow,const QByteArray &nonce){
 bt_.operationStart=monotonicMs();bool ok=bluetooth_.request(op,grants,allow,nonce);
 if(!ok){bt_.available=false;bt_.next=monotonicMs()+1000;bt_.message=btText("无法联系蓝牙服务；请确认服务已由设备环境启动");if(op==4){bt_.cancelRequested=false;bt_.message=btText("关闭请求未送达；请重试或等待会话自行超时");}}
 return ok;
}
void ReaderShell::bluetoothAction(unsigned op,bool allow){
 if(!bluetooth_.configured()){bt_.message=btText("未配置蓝牙服务；应用不会自行启动无线硬件或守护进程");update();return;}
 if(op==3){if(!bluetoothPending())return;if(allow&&!bt_.selectedGrants){bt_.message=btText("请先选择允许的控制或文件权限");update();return;}bt_.queuedNonce=bt_.reply.nonce;bt_.queuedGrants=allow?bt_.selectedGrants:0;bt_.queuedAllow=allow;}
 if(bt_.cancelRequested&&op!=4)return;
 if(op==4){bluetooth_.cancel();bt_.cancelRequested=true;bt_.windowUntil=0;bt_.deferredReady=false;bt_.ackId=0;}
 bt_.queuedOperation=op;bt_.next=0;bluetoothTick();update();
}
bool ReaderShell::bluetoothSessionValid(const QByteArray &nonce)const{return bt_.available&&!bt_.cancelRequested&&bt_.reply.active()&&bt_.sessionUntil>0&&monotonicMs()<bt_.sessionUntil&&nonce==bt_.reply.nonce;}
bool ReaderShell::applyBluetoothEffect(const BluetoothReply &r){
 if(!bluetoothSessionValid(r.nonce))return false;
 if(r.effectKind==1){
  if(r.control==1){if(noteEditing_){bt_.message=btText("手机请求返回首页；请先保存或取消笔记草稿");return false;}applyAction(BackHome,"bluetooth-home",-1,-1);if(page()!=Home)return false;}
  else if(r.control==2)syncRequested();
  bt_.message=r.control==0?btText("已处理手机状态请求"):r.control==1?btText("已处理手机首页请求"):btText("已请求刷新日历；同步结果另行确认");
 }else if(r.effectKind==5){bt_.fileBytes=r.fileBytes;bt_.message=btText("已接收并校验文件；等待手动查看或导入");}
 else return false;
 ++bt_.appliedCount;return true;
}
void ReaderShell::bluetoothTick(){
 const qint64 now=monotonicMs();
 if(!bluetooth_.configured()&&!bt_.intendedPath.isEmpty()&&now>=bt_.configureNext){
  bt_.configureNext=now+1000;
  if(bluetooth_.configure(bt_.intendedPath)){
   bt_.next=now;bt_.message=btText("等待联系本地蓝牙服务");
  }
 }
 if(bluetooth_.busy()&&bluetooth_.poll()){
  unsigned op=bluetooth_.operation();bool ack=bluetooth_.ackRequest();
  if(!bluetooth_.error().isEmpty()){
   bt_.available=false;bt_.message=btText("蓝牙服务响应失败；保留应用与笔记，可稍后重试");bt_.next=now+1000;
   if(bluetooth_.error()=="bluetooth-session-expired"&&op!=4){bt_.windowUntil=bt_.pendingUntil=bt_.sessionUntil=0;bt_.deferredReady=false;bt_.ackId=0;bt_.ackNonce.clear();bt_.queuedOperation=4;bt_.cancelRequested=true;bt_.next=now;}
   if(op==4){bt_.cancelRequested=false;bt_.message=btText("关闭请求未确认；请重试或等待会话自行超时");}
  }else{
   BluetoothReply reply=bluetooth_.reply();bool sameNonce=reply.nonce==bt_.reply.nonce;
   bt_.reply=reply;bt_.available=true;bt_.delivery.observe(reply);
   if(reply.pending()){
    qint64 until=bt_.operationStart+reply.remainingMs;
    if(!sameNonce||!bt_.pendingUntil){bt_.pendingUntil=until;bt_.selectedGrants=0;}else bt_.pendingUntil=qMin(bt_.pendingUntil,until);
   }else bt_.pendingUntil=0;
   if(reply.active()){
    qint64 until=bt_.operationStart+reply.remainingMs;bt_.sessionUntil=sameNonce&&bt_.sessionUntil?qMin(bt_.sessionUntil,until):until;
   }else bt_.sessionUntil=0;
   if(reply.approved()||reply.active())bt_.windowUntil=0;
   if(!reply.active()||(!sameNonce&&bt_.deferredReady))bt_.deferredReady=false;
   if(op==1&&reply.accepted){bt_.windowUntil=bt_.operationStart+60000;bt_.selectedGrants=0;bt_.message=btText("已开启 60 秒配对窗口，请在手机上连接");}
   if(op==3){bt_.message=reply.accepted?btText("本机已允许所选权限；等待服务确认安全连接"):reply.pending()?btText("确认未通过；请重新核对当前手机和验证码"):btText("已拒绝，或确认请求已过期");}
   if(op==4){bt_.cancelRequested=false;if(reply.accepted){bt_.windowUntil=0;bt_.ackId=0;bt_.message=btText("配对窗口与手机会话已关闭");}}
   if(op==5&&ack){bt_.ackId=0;bt_.ackNonce.clear();}
   if(op==5&&!ack&&reply.effectKind&&bluetoothSessionValid(reply.nonce)){
    if(bt_.delivery.applied(reply)){bt_.ackId=reply.eventId;bt_.ackNonce=reply.nonce;}
    else if(applyBluetoothEffect(reply)){bt_.delivery.remember(reply);bt_.ackId=reply.eventId;bt_.ackNonce=reply.nonce;}
    else{bt_.deferred=reply;bt_.deferredReady=true;}
   }
   bt_.next=now+500;if(bt_.ackId)bt_.next=now;
  }
 }
 const qint64 expiryNow=monotonicMs();bool expired=(bt_.windowUntil&&expiryNow>=bt_.windowUntil)||(bt_.reply.pending()&&bt_.pendingUntil&&expiryNow>=bt_.pendingUntil)||(bt_.reply.active()&&bt_.sessionUntil&&expiryNow>=bt_.sessionUntil);
 if(expired&&!bt_.cancelRequested){bt_.windowUntil=bt_.pendingUntil=bt_.sessionUntil=0;bt_.deferredReady=false;bt_.ackId=0;bt_.ackNonce.clear();bt_.queuedOperation=4;bt_.cancelRequested=true;bt_.next=now;}
 if(bt_.deferredReady&&bluetoothSessionValid(bt_.deferred.nonce)){
  if(applyBluetoothEffect(bt_.deferred)){bt_.delivery.remember(bt_.deferred);bt_.ackId=bt_.deferred.eventId;bt_.ackNonce=bt_.deferred.nonce;bt_.deferredReady=false;bt_.next=now;}
 }
 if(!bluetooth_.busy()){
  if(bt_.queuedOperation){unsigned op=bt_.queuedOperation;bt_.queuedOperation=0;
   if(op!=3||(bluetoothPending()&&bt_.queuedNonce==bt_.reply.nonce))sendBluetooth(op,op==3?bt_.queuedGrants:0,op==3&&bt_.queuedAllow,op==3?bt_.queuedNonce:QByteArray());
   else bt_.message=btText("请求已变化或过期，请重新核对手机和验证码");
  }else if(bluetooth_.configured()&&now>=bt_.next){
   if(bt_.ackId){if(!bluetoothSessionValid(bt_.ackNonce)){bt_.ackId=0;bt_.ackNonce.clear();bt_.next=now;}else{bt_.operationStart=now;if(!bluetooth_.ack(bt_.ackNonce,bt_.ackId)){bt_.available=false;bt_.next=now+1000;}}}
   else{unsigned op=bt_.available&&bt_.reply.active()&&bt_.wantEffect?5:2;bt_.wantEffect=!bt_.wantEffect;sendBluetooth(op);}
  }
 }
 QString rendered=bluetoothStatusText()+bt_.message+QString::number(bt_.fileBytes)+bluetoothPasskey()+bt_.reply.peer.toHex()+QString::number(bt_.reply.grants);if(page()==Control&&settingsTab_==1&&rendered!=bt_.lastRendered)update();bt_.lastRendered=rendered;
}
void ReaderShell::drawBluetooth(QPainter &p){
 drawButton(p,QRect(16,256,208,54),btText("开启 60 秒配对"));drawButton(p,QRect(256,256,208,54),btText("关闭窗口 / 会话"));
 p.setFont(btFont(font(),18));p.drawText(QRect(24,325,432,64),Qt::TextWordWrap,bt_.message.isEmpty()?btText("仅允许手机控制和文件接收；不会配置 Wi-Fi。请在本机核对验证码后选择权限。"):bt_.message);
 if(bluetoothPending()){
  p.drawText(QRect(24,397,432,32),Qt::AlignCenter,btText("手机：")+peerText(bt_.reply.peer));p.setFont(btFont(font(),42,true));p.drawText(QRect(24,439,432,64),Qt::AlignCenter,bluetoothPasskey());
  drawButton(p,QRect(16,516,208,54),(bt_.selectedGrants&1?btText("已选 控制"):btText("未选 控制")));drawButton(p,QRect(256,516,208,54),(bt_.selectedGrants&4?btText("已选 文件"):btText("未选 文件")));
  drawButton(p,QRect(16,586,208,54),btText("允许所选权限"));drawButton(p,QRect(256,586,208,54),btText("拒绝"));
 }else{p.setFont(btFont(font(),21));p.drawText(QRect(24,405,432,180),Qt::TextWordWrap,bluetoothActive()?btText("服务已确认手机会话活动。权限：")+(bt_.reply.grants&1?btText("控制 "):QString())+(bt_.reply.grants&4?btText("文件"):QString()):btText("当前没有待确认的手机。需要设备环境已启动蓝牙服务；此页面不会启动守护进程或无线硬件。"));}
 p.setFont(btFont(font(),18));p.drawText(QRect(24,667,432,110),Qt::TextWordWrap,(bt_.fileBytes?btText("最近收到文件：")+QString::number(bt_.fileBytes)+btText(" 字节；不自动执行或导入。\n"):QString())+btText("手机硬件连通与实际配对仍需真机验收。"));
}
void ReaderShell::bluetoothTap(int x,int y){
 if(QRect(16,256,208,54).contains(x,y)){bluetoothAction(1);return;}
 if(QRect(256,256,208,54).contains(x,y)){bluetoothAction(4);return;}
 if(!bluetoothPending())return;
 if(QRect(16,516,208,54).contains(x,y))bt_.selectedGrants^=1;
 else if(QRect(256,516,208,54).contains(x,y))bt_.selectedGrants^=4;
 else if(QRect(16,586,208,54).contains(x,y))bluetoothAction(3,true);
 else if(QRect(256,586,208,54).contains(x,y))bluetoothAction(3,false);update();
}
