// Pure protocol tests run only inside the retained disposable MIPS offline gate.
#include "../sync.h"
#include <QtCore/qcoreapplication.h>
#include <QtCore/qfile.h>
#include <QtCore/qdir.h>
#include <QtCore/qfileinfo.h>
#include <stdio.h>
static int checks=0,failures=0;
#define CHECK(n,c) do{++checks;if(!(c)){fprintf(stderr,"FAIL %s line %d\n",n,__LINE__);++failures;}}while(0)
static QByteArray read(const QString &p){QFile f(p);f.open(QIODevice::ReadOnly);return f.readAll();}
int main(int argc,char **argv){
 QCoreApplication app(argc,argv);QString error;DeviceManifest m;
 QByteArray raw=read("/content-test/fixtures/device-manifest.json");
 CHECK("valid_bounded_manifest",parseDeviceManifest(raw,&m,&error));
 CHECK("manifest_exact_three_resources",m.files.size()==3 && m.serverEpoch==1792458000LL);
 CHECK("duplicate_key_rejected",!parseDeviceManifest(raw.left(raw.size()-1)+",\"schema\":1}",&m,&error));
 CHECK("oversize_manifest_rejected",!parseDeviceManifest(QByteArray(65537,'x'),&m,&error));
 CHECK("cross_origin_resource_rejected",!parseDeviceManifest(QByteArray(raw).replace("/reader/v1/resources/","http://evil/"),&m,&error));
 CHECK("wrong_version_path_rejected",!parseDeviceManifest(QByteArray(raw).replace("resources/0123","resources/1123"),&m,&error));
 CHECK("negative_epoch_rejected",!parseDeviceManifest(QByteArray(raw).replace("1792458000","-1"),&m,&error));
 CHECK("file_count_rejected",!parseDeviceManifest(QByteArray(raw).replace("\"files\":[","\"files\":[{},"),&m,&error));
 HttpReply reply;CHECK("strict_http_ok",reply.feed("HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}",2,&error) && reply.complete() && reply.body()=="{}");
 HttpReply chunk;CHECK("chunked_rejected",!chunk.feed("HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n",100,&error));
 HttpReply dup;CHECK("duplicate_length_rejected",!dup.feed("HTTP/1.1 200 OK\r\nContent-Length: 1\r\nContent-Length: 2\r\n\r\nx",5,&error));
 HttpReply big;CHECK("body_bound_before_read",!big.feed("HTTP/1.1 200 OK\r\nContent-Length: 500\r\n\r\n",20,&error));
 HttpReply split;CHECK("fragment_header",split.feed("HTTP/1.1 200 OK\r\nContent-L",2,&error) && !split.complete());CHECK("fragment_body",split.feed("ength: 2\r\n\r\n{",2,&error) && !split.complete());CHECK("fragment_finish",split.feed("}",2,&error) && split.complete());
 DeviceEndpoint endpoint;CHECK("loopback_origin",parseDeviceEndpoint("http://127.0.0.1:8768",&endpoint,&error));
 CHECK("tls_numeric_origin",parseDeviceEndpoint("https://127.0.0.1:8768",&endpoint,&error) && endpoint.tls);CHECK("no_lan_token_cleartext",!parseDeviceEndpoint("http://192.168.1.2:8768",&endpoint,&error));
 CHECK("domain_https_origin",parseDeviceEndpoint("https://pandanote.example.invalid/pandanote/",&endpoint,&error)&&endpoint.host=="pandanote.example.invalid"&&endpoint.port==443&&endpoint.tls);
 CHECK("domain_prefix_canonical",endpoint.basePath=="/pandanote"&&deviceRequestTarget(endpoint,"/reader/v1/manifest")=="/pandanote/reader/v1/manifest");
 CHECK("prefix_once",deviceRequestTarget(endpoint,"/pandanote/reader/v1/manifest").isEmpty());
 const char *badOrigins[]={"http://pandanote.example.invalid/pandanote","https://secret@pandanote.example.invalid/pandanote","https://pandanote.example.invalid/pandanote?x=1","https://pandanote.example.invalid/pandanote#x","https://pandanote.example.invalid/pandanote/../reader/v1/manifest","https://pandanote.example.invalid//pandanote","https://pandanote.example.invalid/%70andanote","https://-bad.example/pandanote","https://pandanote.example.invalid./pandanote"};for(unsigned i=0;i<sizeof badOrigins/sizeof badOrigins[0];i++)CHECK("unsafe_origin_rejected",!parseDeviceEndpoint(badOrigins[i],&endpoint,&error));
 CHECK("new_domain_canonical",parseDeviceEndpoint("https://pandanote.example.invalid/pandanote",&endpoint,&error)&&endpoint.port==443&&endpoint.basePath=="/pandanote");
 CHECK("request_path_query_rejected",deviceRequestTarget(endpoint,"/reader/v1/manifest?x=1").isEmpty());
 CHECK("request_path_traversal_rejected",deviceRequestTarget(endpoint,"/reader/v1/../manifest").isEmpty());
 CHECK("no_url_credentials",!parseDeviceEndpoint("http://secret@127.0.0.1:8768",&endpoint,&error));
 RadioReply ssidReply;QByteArray ssidStatus="[reply]\nschema=1\nok=1\ncode=status\nmessage64=\n[status]\nwifi_state=COMPLETED\nwifi_ssid64=";
 CHECK("associated_ssid_noncanonical_base64_rejected",!parseRadioReply(ssidStatus+"Zh==\n",&ssidReply,&error));
 CHECK("associated_ssid_invalid_utf8_rejected",!parseRadioReply(ssidStatus+"/w==\n",&ssidReply,&error));
 CHECK("associated_ssid_oversize_rejected",!parseRadioReply(ssidStatus+QByteArray(33,'x').toBase64()+"\n",&ssidReply,&error));
 CHECK("associated_ssid_canonical_chinese_decoded",parseRadioReply(ssidStatus+"5rWL6K+V\ninterface_name=wlan0\ninterface_state=up\nnetmask=255.255.255.0\nmac=02:00:5e:00:53:01\ngateway=192.0.2.1\n",&ssidReply,&error)&&ssidReply.wifiSsid==QString::fromUtf8("测试"));
 QByteArray downSsid=ssidStatus;downSsid.replace("COMPLETED","DISCONNECTED");CHECK("disconnected_never_exposes_associated_ssid",parseRadioReply(downSsid+"5rWL6K+V\n",&ssidReply,&error)&&ssidReply.wifiSsid.isEmpty());
 RadioReply radio;CHECK("valid_radio_reply",parseRadioReply("[reply]\nschema=1\nok=1\ncode=ok\nmessage64=\n[status]\nwifi_state=disconnected\nipv4=\nbt_state=off\n[wifi0]\nssid64=TmV3IFdpRmk=\nsignal=-42\nsecurity=WPA2\n",&radio,&error));
 CHECK("radio_rows_decoded",radio.wifi.size()==1 && radio.wifi[0].ssid=="New WiFi");
 CHECK("radio_duplicates_rejected",!parseRadioReply("[reply]\nschema=1\nschema=1\nok=1\ncode=ok\nmessage64=\n",&radio,&error));
 CHECK("radio_bad_base64",!parseRadioReply("[reply]\nschema=1\nok=1\ncode=ok\nmessage64=!!!!\n",&radio,&error));
 QByteArray request=radioRequest("wifi-connect","New WiFi","PRIVATE_TEST_ONLY");CHECK("password_only_stdin_base64",!request.contains("PRIVATE_TEST_ONLY") && request.contains("password64=") && request.size()<16384);
 CHECK("unknown_radio_action",radioRequest("run-command","x","x").isEmpty());
 QByteArray wifiRaw="[reply]\nschema=1\nok=1\ncode=scan_requested\nmessage64=\n";
 const char *names[]={"Fixture Mesh","Fixture Other","Fixture Mesh","Fixture Mesh","Fixture Mesh","fixture mesh","Fixture Mesh","Fixture Other","e\314\201","\303\251","Fixture Mesh","Fixture Mesh"};
 const char *security[]={"wpa2","open","wpa","open","unsupported","wpa2","unknown","open","wpa2","wpa2","wpa2","wpa2-eap"};
 const char *rssiSamples[]={"-70","-50","-35","-20","-10","-30","-40","-15","-45","-46","-35","-25"};
 for(int i=0;i<12;++i)wifiRaw+="[wifi"+QByteArray::number(i)+"]\nssid64="+QByteArray(names[i]).toBase64()+"\nsignal="+rssiSamples[i]+"\nsecurity="+security[i]+"\n";
 RadioReply merged;CHECK("duplicate_ssid_groups_compatible_security_only",parseRadioReply(wifiRaw,&merged,&error)&&merged.wifi.size()==9);
 CHECK("duplicate_uses_strongest_personal_rssi_and_stable_tie",merged.wifi.size()>0&&merged.wifi[0].signal=="-35"&&merged.wifi[0].security=="wpa");
 CHECK("group_order_stays_first_seen_despite_later_strong_signal",merged.wifi.size()>1&&merged.wifi[1].ssid=="Fixture Other"&&merged.wifi[1].signal=="-15");
 CHECK("same_ssid_open_and_unsupported_remain_separate",merged.wifi.size()>3&&merged.wifi[2].security=="open"&&merged.wifi[3].security=="unsupported");
 CHECK("ssid_case_is_not_folded",merged.wifi.size()>4&&merged.wifi[4].ssid=="fixture mesh");
 CHECK("ssid_unicode_bytes_not_normalized",merged.wifi.size()>7&&merged.wifi[6].ssid.toUtf8()==QByteArray("e\314\201")&&merged.wifi[7].ssid.toUtf8()==QByteArray("\303\251"));
 QByteArray sixtyFour="[reply]\nschema=1\nok=1\ncode=scan_requested\nmessage64=\n";
 for(int i=0;i<64;++i)sixtyFour+="[wifi"+QByteArray::number(i)+"]\nssid64="+QByteArray("Repeated Fixture").toBase64()+"\nsignal="+QByteArray::number(-99+i)+"\nsecurity=wpa2\n";
 CHECK("64_raw_access_points_bounded_before_grouping",parseRadioReply(sixtyFour,&merged,&error)&&merged.wifi.size()==1&&merged.wifi[0].signal=="-36");
 CHECK("65_raw_access_points_rejected_even_if_same_group",!parseRadioReply(sixtyFour+"[wifi64]\nssid64=UmVwZWF0ZWQgRml4dHVyZQ==\nsignal=-20\nsecurity=wpa2\n",&merged,&error));
 QDir().mkdir("/tmp/device-cache");CHECK("private_cache_fixture",QFile::setPermissions("/tmp/device-cache",QFile::ReadOwner|QFile::WriteOwner|QFile::ExeOwner));DeviceSync sync("/tmp/device-cache");
 CHECK("empty_cache_offline",!sync.cachedContent().schema && sync.lastDisplayed().isEmpty());
 sync.refresh();CHECK("manifest_request",sync.request().path=="/reader/v1/manifest");
 CHECK("accept_manifest",sync.receive(200,raw));CHECK("fresh_server_time",sync.freshEpoch()==1792458000LL && sync.lastDisplayed().isEmpty());
 for(int i=0;i<3;++i){SyncRequest r=sync.request();CHECK("fixed_resource_path",r.path.startsWith("/reader/v1/resources/0123456789abcdef0123456789abcdef/"));CHECK("accept_resource",sync.receive(200,read("/content-test/fixtures/device/"+r.path.section('/',-1))));}
 Content update;CHECK("validated_update",sync.takeUpdate(&update));CHECK("download_not_ack",sync.request().path.isEmpty() && sync.lastDisplayed().isEmpty());
 sync.painted(update.version);CHECK("paint_then_ack",sync.request().method=="POST" && sync.request().path=="/reader/v1/ack");CHECK("ack_version",sync.request().body.contains(update.version.toLatin1()));sync.failed("ack-network-timeout");sync.refresh();CHECK("manifest_after_lost_ack",sync.receive(200,raw));CHECK("paint_ack_retry_without_repaint",sync.request().path=="/reader/v1/ack");CHECK("ack_success",sync.receive(200,"{}"));CHECK("displayed_separate",sync.lastDisplayed()==update.version);
 sync.refresh();CHECK("same_manifest_after_lost_ack",sync.receive(200,raw));
 sync.painted(update.version); // Already-painted version must not forge another paint.

 sync.refresh();CHECK("same_manifest_accepted",sync.receive(200,raw));CHECK("unchanged_no_download_repaint",sync.request().path.isEmpty() && !sync.takeUpdate(&update));
 sync.refresh();CHECK("bad_manifest_retains",!sync.receive(200,"{}") && sync.cachedContent().schema==1 && !sync.error().isEmpty());
 DeviceSync restart("/tmp/device-cache");CHECK("restart_last_good",restart.cachedContent().schema==1);CHECK("cached_time_not_fresh",restart.freshEpoch()==0);
 for(int n=2;n<=3;++n){restart.refresh();CHECK("next_version_manifest",restart.receive(200,read(QString("/content-test/fixtures/device-manifest%1.json").arg(n))));for(int i=0;i<3;++i){SyncRequest r=restart.request();CHECK("next_version_resource",restart.receive(200,read(QString("/content-test/fixtures/device%1/").arg(n)+r.path.section('/',-1))));}CHECK("next_version_update",restart.takeUpdate(&update));restart.painted(update.version);CHECK("next_version_ack",restart.receive(200,"{}"));}
 CHECK("bounded_two_version_cache",QDir("/tmp/device-cache").entryList(QDir::Dirs|QDir::NoDotAndDotDot).size()==2);
 CHECK("last_good_previous_retained",QFileInfo("/tmp/device-cache/22222222222222222222222222222222").isDir());
 printf("%s device protocol %d checks network=none input=SIMULATED\n",failures?"FAIL":"PASS",checks);return failures?1:0;
}
