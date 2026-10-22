// Temporary authorized device diagnostic; not a production service.
#include <stdio.h>
#include <unistd.h>
#include <fcntl.h>
#include <time.h>
#include <errno.h>
static double now(int id){struct timespec ts;if(clock_gettime(id,&ts))return -1;return ts.tv_sec+ts.tv_nsec/1e9;}
int main(){double m=now(CLOCK_MONOTONIC),b=now(CLOCK_BOOTTIME);printf("SUSPEND_PROBE_BEGIN mono=%.3f boot=%.3f\n",m,b);fflush(stdout);int fd=open("/sys/power/state",O_WRONLY|O_CLOEXEC);if(fd<0)return 2;errno=0;ssize_t n=write(fd,"mem\n",4);int e=errno;close(fd);printf("SUSPEND_PROBE_END written=%ld errno=%d mono_elapsed=%.3f boot_elapsed=%.3f\n",long(n),e,now(CLOCK_MONOTONIC)-m,now(CLOCK_BOOTTIME)-b);return n==4?0:1;}
