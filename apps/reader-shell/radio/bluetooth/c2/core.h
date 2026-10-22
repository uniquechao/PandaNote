#ifndef PANDANOTE_C2_CORE_H
#define PANDANOTE_C2_CORE_H
#include <sys/types.h>
#include <stdint.h>
struct child { pid_t pid; int status; int reaped; };
int64_t c2_now(void);
int c2_spawn(struct child *, int executable_fd, char *const argv[], char *const env[], int logfd, unsigned memory_mb);
int c2_alive(struct child *);
int c2_stop(struct child *);
int c2_dir(int parent, const char *name);
int c2_file(int parent, const char *name, int create);
int c2_hash(int fd, const char *digest, unsigned limit);
int c2_empty(int fd);
int c2_erase(int fd,unsigned depth,unsigned *count,unsigned *bytes);
int c2_lock(int fd);
#endif
