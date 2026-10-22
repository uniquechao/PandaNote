/* Retained glibc2.29 exports __[flx]xstat, not glibc>=2.33 public aliases.
 * MIPS o32 version3 layout validated against retained converters and compile
 * assertions below; no 64-bit-time/file-offset mode is enabled by this build. */
#ifndef PANDANOTE_BLUEZ_COMPAT_STAT_H
#define PANDANOTE_BLUEZ_COMPAT_STAT_H
#include <sys/stat.h>
#include <stddef.h>
#if !defined(__mips__) || !defined(__linux__)
#error target-only glibc2.29 adapter
#endif
#if defined(__USE_TIME_BITS64) || defined(__USE_FILE_OFFSET64)
#error unreviewed stat layout
#endif
_Static_assert(sizeof(struct stat)==144,"MIPS Linux version3 stat size");
_Static_assert(offsetof(struct stat,st_mode)==20,"stat mode");
_Static_assert(offsetof(struct stat,st_uid)==28,"stat uid");
_Static_assert(offsetof(struct stat,st_size)==48,"stat size field");
_Static_assert(offsetof(struct stat,st_atim)==56,"stat time");
_Static_assert(offsetof(struct stat,st_blksize)==80,"stat block size");
_Static_assert(offsetof(struct stat,st_blocks)==84,"stat blocks");
extern int __xstat(int,const char *,struct stat *);
extern int __lxstat(int,const char *,struct stat *);
extern int __fxstat(int,int,struct stat *);
#define stat(path,buf) __xstat(3,path,buf)
#define lstat(path,buf) __lxstat(3,path,buf)
#define fstat(fd,buf) __fxstat(3,fd,buf)
#endif
