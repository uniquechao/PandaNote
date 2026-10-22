#ifndef PANDANOTE_SHELL_H
#define PANDANOTE_SHELL_H
#include "content.h"
#include "navigation.h"
#include "sync.h"
#include "localapps.h"
#include "bluetooth.h"
#include "einkrefresh.h"
#include <QtGui/qwidget.h>
#include <QtGui/qimage.h>
class QPainter;
struct BluetoothUiState {
 BluetoothReply reply,deferred;BluetoothDelivery delivery;
 QString message,lastRendered,intendedPath;QByteArray queuedNonce,ackNonce;int timer;
 qint64 next,configureNext,windowUntil,pendingUntil,sessionUntil,operationStart;
 unsigned queuedOperation,selectedGrants,queuedGrants,appliedCount,fileBytes,ackId;
 bool queuedAllow,available,cancelRequested,deferredReady,wantEffect;
 BluetoothUiState():timer(0),next(0),configureNext(0),windowUntil(0),pendingUntil(0),sessionUntil(0),operationStart(0),queuedOperation(0),selectedGrants(0),queuedGrants(0),appliedCount(0),fileBytes(0),ackId(0),queuedAllow(false),available(false),cancelRequested(false),deferredReady(false),wantEffect(false){}
};
class ReaderShell:public QWidget {
public:
    explicit ReaderShell(const Content &content,QWidget *parent=0,RadioClient *radio=0);
    bool otaInstalling()const{return otaLocked_;}
    Page page() const { return navigation_.page(); }
    bool fontReady() const { return fontReady_; }
    bool standby()const{return standby_;}bool shuttingDown()const{return shutdownPending_;}
    void shortPowerPress();void longPowerPress();void systemStandbyCompleted(bool resumed);
    void setContent(const Content &content);
    bool setTrustedTime(qint64 serverEpoch);
    void clearTrustedTime();
    void setSyncFailed(bool failed);
    void refreshTime();
    void refreshStandbySnapshot();
    bool listNavigate(int direction);
    QString displayStatus() const;
    QDate displayDate() const;
    QString homeMessage() const;
    QString inputValue(int field) const;
    QString networkStatusText() const;
    bool configureWorkspace(const QString &path);
    QString workspaceStatus()const;
    bool configureBluetooth(const QString &path);
    QString bluetoothStatusText()const;QString bluetoothPasskey()const;
    bool bluetoothPending()const;bool bluetoothActive()const;
    unsigned bluetoothAppliedCount()const{return bt_.appliedCount;}
    unsigned bluetoothFileBytes()const{return bt_.fileBytes;}
    QString noteVisibleText()const;
    QString wordVisibleText()const;
    QString noteDraftVisibleText()const;
    int wordScrollOffset()const{return wordScroll_;}
    bool wordBackShowing()const{return wordBack_;}
    QString noteDraft()const{return noteDraft_;}
    bool inputActive() const { return inputField_>=0; }
    void setConnectionStatus(const QString &status);
    void setSyncActivity(bool active);
    void setEndpointLabel(const QString &endpoint) { inputEndpoint_=endpoint; }
    virtual bool configureSync(const QString &endpoint,const QByteArray &token);
    virtual void syncRequested();
    virtual bool otaTimeTrusted()const{return false;}
    virtual void contentPainted(const QString &version);
protected:
    void paintEvent(QPaintEvent *event);
    void mousePressEvent(QMouseEvent *event);
    void mouseReleaseEvent(QMouseEvent *event);
    void mouseMoveEvent(QMouseEvent *event);
    void wheelEvent(QWheelEvent *event);
    void timerEvent(QTimerEvent *event);
    virtual qint64 monotonicMs() const;
    virtual EinkRefreshResult fullRefreshRequested();
    virtual bool refreshBattery();
    virtual bool shutdownRequested();virtual void standbyChanged(bool);
    // Task3 may subclass to log navigation; source is release, wheel, or idle.
    virtual void navigationChanged(Page from,Page to,const char *source,int x,int y);
private:
    int otaTimer_,otaPaintCount_;bool otaLocked_,otaOffered_,otaDeferred_,otaPreparing_,otaSyncBusy_,otaProgress_,otaPressPrompt_;qint64 otaPrepareAt_;
    QString otaMessage_,otaVersion_,otaCurrent_,otaAttempt_,otaGeneration_,otaPressAttempt_,otaPressGeneration_;
    void otaInitialize();void otaTick();bool otaInput();void otaCommand(const char*);bool otaTap(int,int);void drawOta(QPainter &);
    bool otaGesture(int,int)const;bool otaPromptVisible()const{return !standby_&&!shutdownPending_&&otaOffered_&&!otaDeferred_&&!inputActive()&&!noteEditing_;}
    bool standby_,shutdownPending_;qint64 touchGuardUntil_;QString powerMessage_;
    bool persistPowerDraft();void drawPowerScreen(QPainter &);void drawStandbyAgenda(QPainter &);
    QString agendaFingerprint(int maximum) const;QString statusFingerprint() const;
    QString standbyFingerprint_,standbyStatusFingerprint_;
    // Every application update path (including Bluetooth) stops before Qt
    // records dirty regions while locked. Explicit snapshots bypass this gate.
    void update(){if(!standby_&&!shutdownPending_)QWidget::update();}
    void update(const QRect &r){if(!standby_&&!shutdownPending_)QWidget::update(r);}
    BluetoothClient bluetooth_;BluetoothUiState bt_;
    void drawBluetooth(QPainter &);void bluetoothTap(int,int);void bluetoothTick();
    void bluetoothAction(unsigned,bool allow=false);bool sendBluetooth(unsigned,unsigned=0,bool=false,const QByteArray &nonce=QByteArray());
    bool bluetoothSessionValid(const QByteArray &nonce)const;
    bool applyBluetoothEffect(const BluetoothReply &);
    LocalApps local_;QString localMessage_,noteDraft_,noteId_;int wordIndex_,wordScroll_,localOffset_,noteOffset_,noteScroll_;bool wordBack_,wordList_,noteEditing_,noteDelete_;
    void drawWords(QPainter &);void drawNotes(QPainter &);void localTap(int,int);bool scrollLocal(int);
    bool systemPanelOpen_,quickSyncPending_,pressSystem_,pressWasOpen_,systemReturnActive_,batteryCharging_,batteryEstimated_,batteryChargingKnown_;
    qint64 fullRefreshAllowedAt_;
    int batteryPercent_,batteryVoltageMv_,systemReturnInput_;Page systemReturnPage_;QString quickMessage_,statusClock_;
    void setSystemPanel(bool open);
    void systemPanelTap(int x,int y);
    void openSystemControl();
    QString compactSyncStatus() const;
    QString systemWifiStatus() const;
    void drawStatusBar(QPainter &);
    void drawSystemPanel(QPainter &);
    Content content_;TimeAnchor anchor_;IdleNavigation navigation_;
    QElapsedTimer monotonic_;QImage background_,defaultBackground_,landscapeBackground_;
    bool fontReady_,syncFailed_,pressActive_;Page pressPage_;int idleTimer_,scheduleOffset_;qint64 idleDeadline_;QPoint press_;
    QString fingerprint_,connectionStatus_,inputSsid_,inputPassword_,inputEndpoint_,inputToken_;
    RadioClient ownedRadio_;RadioClient *radio_;RadioReply radioReply_;QString radioAction_,wifiScanCode_,wifiDialogSecurity_,wifiSaveCode_;int wifiOffset_,wifiPressOffset_;bool wifiSwipe_,wifiListGesture_,wifiDialog_,wifiNetworkInfo_,wifiScanPending_;int radioTimer_,wifiStatusTimer_;qint64 wifiStatusDeadline_;bool wifiLinked_,wifiSyncLinked_;int settingsTab_,inputField_,keyboardMode_,selectedWifi_,selectedBluetooth_;bool uppercase_;
    QString &editValue();
    void settingsTap(int x,int y);
    void keyboardTap(int x,int y);
    void beginInput(int field);
    void clearSecrets();
    bool startRadio(const QString &action,const QString &value=QString(),const QString &password=QString());
    void watchWifiStatus(bool scan=false);
    void refreshWifiScan();
    int wifiRowAt(const QPoint &) const;
    bool scrollWifiList(const QPoint &);
    void drawWifiDialog(QPainter &);
    void requestWifiStatus();
    void finishRadio();
    QString wifiFeedback() const;
    QString wifiSaveFeedback() const;
    void drawSettings(QPainter &);
    void drawKeyboard(QPainter &);
    void drawInformation(QPainter &);
    QString displayClock() const;
    QList<Event> homeEvents() const;
    void resetIdle();
    void cancelGesture();
    void applyAction(Action action,const char *source,int x,int y);
    void scrollSchedule(int amount);
    void drawHome(QPainter &painter);
    void drawPanel(QPainter &painter);
    void drawSchedule(QPainter &painter);
    void drawPlaceholder(QPainter &painter);
    void drawButton(QPainter &painter,const QRect &rect,const QString &text);
    void drawEvent(QPainter &painter,const Event &event,const QRect &rect,bool showDate);
};
#endif
