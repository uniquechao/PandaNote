/* Startup ABI marker matching GNU glibc 2.29 csu/init.c.
 * Reference: https://github.com/bminor/glibc/blob/glibc-2.29/csu/init.c
 * Presence of this exported object selects the modern libio stdio ABI.
 */
const int _IO_stdin_used = 0x20001;
