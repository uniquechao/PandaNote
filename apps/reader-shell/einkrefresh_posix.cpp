#include "einkrefresh.h"
#include "build-support/qws-display-lock.h"
#include <linux/fb.h>
#include <sys/ioctl.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <errno.h>
// Deliberately fixed to the already verified 966U2 display; no arbitrary paths.
static const char ModePath[]="/sys/devices/platform/jz-spi1.1/spi_master/spi1/spi1.0/eink_mode";
typedef char FbVarSize[sizeof(struct fb_var_screeninfo)==160?1:-1];
class DeviceRefreshIo:public EinkRefreshIo {
 int fb_,mode_;
 bool geometry(const fb_var_screeninfo &v) {
  return v.xres==800&&v.yres==480&&v.xres_virtual==800&&v.yres_virtual==960&&v.bits_per_pixel==16&&v.xoffset==0&&v.yoffset==0&&v.red.offset==11&&v.red.length==5&&v.green.offset==5&&v.green.length==6&&v.blue.offset==0&&v.blue.length==5;
 }
public:
 DeviceRefreshIo():fb_(-1),mode_(-1){}
 ~DeviceRefreshIo(){if(fb_>=0)::close(fb_);if(mode_>=0)::close(mode_);}
 bool ready(){
  fb_=::open("/dev/fb0",O_RDWR|O_CLOEXEC|O_NOFOLLOW);
  if(fb_<0)return false;
  fb_fix_screeninfo f;fb_var_screeninfo v;memset(&f,0,sizeof(f));memset(&v,0,sizeof(v));
  if(::ioctl(fb_,FBIOGET_FSCREENINFO,&f)||::ioctl(fb_,FBIOGET_VSCREENINFO,&v)||strncmp(f.id,"spi_fb",16)||f.line_length!=1600||f.smem_len<768000||!geometry(v))return false;
  mode_=::open(ModePath,O_RDWR|O_CLOEXEC|O_NOFOLLOW);return mode_>=0;
 }
 void grab(){pandanoteQwsGrabDisplay(true);}
 void ungrab(){pandanoteQwsUngrabDisplay();}
 bool readMode(int *mode){
  char b[8];if(::lseek(mode_,0,SEEK_SET)<0)return false;ssize_t n;
  do{n=::read(mode_,b,sizeof(b));}while(n<0&&errno==EINTR);
  if(n<1||n>2||b[0]<'0'||b[0]>'3'||(n==2&&b[1]!='\n'))return false;*mode=b[0]-'0';return true;
 }
 bool writeMode(int mode){
  if((mode!=0&&mode!=1)||::lseek(mode_,0,SEEK_SET)<0)return false;char b[2]={char('0'+mode),'\n'};ssize_t n;
  do{n=::write(mode_,b,2);}while(n<0&&errno==EINTR);return n==2;
 }
 bool pan(){
  fb_var_screeninfo v;memset(&v,0,sizeof(v));
  if(::ioctl(fb_,FBIOGET_VSCREENINFO,&v)||!geometry(v))return false;
  // Same visible buffer, dimensions and pixels; synchronous hardware waveform.
  return ::ioctl(fb_,FBIOPAN_DISPLAY,&v)==0;
 }
};
EinkRefreshResult performDeviceFullRefresh(){
 // QLock recursion cannot upgrade an already held read lock to a write lock.
 if(pandanoteQwsDisplayGrabbed())return EinkRefreshBusy;
 DeviceRefreshIo io;return performFullRefresh(io);
}
