/* Target-only glibc2.29 stat-at alias; same pinned MIPS o32 version3 layout
 * established by C1 compat-stat.h. Retained __fxstatat passes its version to
 * the same __xstatconv at e880c as retained stat/fstat converters. */
#ifndef PANDANOTE_C3_COMPAT_STAT_AT_H
#define PANDANOTE_C3_COMPAT_STAT_AT_H
#include <sys/stat.h>
#ifndef PANDANOTE_BLUEZ_COMPAT_STAT_H
#error include reviewed C1 stat layout adapter first
#endif
extern int __fxstatat(int,int,const char *,struct stat *,int);
#define fstatat(dir,path,buf,flags) __fxstatat(3,dir,path,buf,flags)
#endif
