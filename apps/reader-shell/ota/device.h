#ifndef PANDANOTE_OTA_DEVICE_H
#define PANDANOTE_OTA_DEVICE_H
#include "core.h"
namespace Ota {
bool loadJson(const std::string &,Json &,size_t limit=786432);
bool loadConfig(Json &);bool baseline(Json &,std::string &raw);bool request(const Json &,Json &,std::string &error);
bool loadAttempt(const std::string &,const Json &,Authorization &,Json &,std::string &error,bool allowExpired=false);
std::string attemptPath(const std::string &);
bool prepareValid(const std::string &,const std::string &,Process *native=0);bool noPowerRequest();
}
extern "C" int pandanote_ota_gate(int *argc,char ***argv);
extern "C" int pandanote_ota_final_check(void);
#endif
