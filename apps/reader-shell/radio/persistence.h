/* Included only by radio.c after the bounded request parser. No shell format. */
#include <sys/file.h>
#ifndef RADIO_USER_ROOT
#define RADIO_USER_ROOT "/user"
#endif
#ifndef RADIO_PERSIST_BLOCK
#define RADIO_PERSIST_BLOCK "/dev/mmcblk0p9"
#endif
#ifndef RADIO_PERSIST_MOUNTS
#define RADIO_PERSIST_MOUNTS "/proc/self/mounts"
#endif
#ifndef RADIO_STORE_UID
#define RADIO_STORE_UID 0
#endif
#define STORE_ROOT RADIO_USER_ROOT "/pandanote/config/wifi"
#define STORE_POINTER RADIO_LOCAL "/wifi-persistence"
#define STORE_MAX 512
#define STORE_CURRENT "requested.ini"
#define STORE_TEMP ".requested.tmp"
#define STORE_PREVIOUS ".previous.tmp"

struct saved_wifi {
    int enabled, directory, lock, present;
    size_t bytes;
    char previous[STORE_MAX + 1];
};

static int private_file(const struct stat *st) {
    return S_ISREG(st->st_mode) && st->st_uid == RADIO_STORE_UID &&
           (st->st_mode & 07777) == 0600 && st->st_nlink == 1 &&
           st->st_size > 0 && st->st_size <= STORE_MAX;
}
static int private_directory(int fd, int exact) {
    struct stat st;
    return !fstat(fd, &st) && S_ISDIR(st.st_mode) &&
           st.st_uid == RADIO_STORE_UID &&
           (exact ? (st.st_mode & 07777) == 0700 : !(st.st_mode & 0022));
}
/* Walk from a descriptor for /, never following an intermediate symlink.
 * The only writable ancestor exception is the root-owned sticky /tmp itself. */
static int walk_directory(const char *path) {
    char part[256], prefix[1024] = "";
    const char *p = path;
    int fd = -1;
    struct stat root_stat;
    if (!p || *p++ != '/' || strlen(path) >= sizeof(prefix)) return -1;
    fd = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return -1;
    if (fstat(fd, &root_stat) || !S_ISDIR(root_stat.st_mode) || root_stat.st_uid != 0 ||
        (root_stat.st_mode & 0022)) goto invalid;
    while (*p) {
        const char *end = strchr(p, '/');
        size_t length = end ? (size_t)(end - p) : strlen(p);
        struct stat st;
        int next;
        if (!length || length >= sizeof(part)) goto invalid;
        memcpy(part, p, length); part[length] = 0;
        if (!strcmp(part, ".") || !strcmp(part, "..")) goto invalid;
        strcat(prefix, "/"); strcat(prefix, part);
        next = openat(fd, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (next < 0) goto invalid;
        if (fstat(next, &st) || !S_ISDIR(st.st_mode) ||
            (st.st_uid != 0 && st.st_uid != RADIO_STORE_UID) ||
            ((st.st_mode & 0022) &&
             (strcmp(prefix, "/tmp") || st.st_uid != 0 || !(st.st_mode & S_ISVTX)))) {
            close(next); goto invalid;
        }
        close(fd); fd = next;
        if (!end) return fd;
        p = end + 1;
    }
    return fd;
invalid:
    close(fd); return -1;
}
/* 1 exists, 0 absent, -1 unsafe/error. O_NONBLOCK prevents FIFO opens hanging. */
static int read_private_at(int dir, const char *name, char *out, size_t *length) {
    struct stat st, before;
    int fd;
    ssize_t n, extra;
    char sentinel;
    if (fstatat(dir, name, &before, AT_SYMLINK_NOFOLLOW)) return errno == ENOENT ? 0 : -1;
    if (!private_file(&before)) return -1;
    fd = openat(dir, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    if (fd < 0) return -1;
    if (fstat(fd, &st) || !private_file(&st) || st.st_dev != before.st_dev ||
        st.st_ino != before.st_ino) { close(fd); return -1; }
    n = read(fd, out, (size_t)st.st_size);
    extra = read(fd, &sentinel, 1);
    close(fd);
    if (n != st.st_size || extra != 0 || memchr(out, 0, (size_t)n)) return -1;
    out[n] = 0; *length = (size_t)n;
    return 1;
}
static int mount_option(const char *options, const char *wanted) {
    size_t n = strlen(wanted);
    const char *p = options;
    while (*p) {
        const char *end = strchr(p, ',');
        size_t length = end ? (size_t)(end - p) : strlen(p);
        if (length == n && !memcmp(p, wanted, n)) return 1;
        if (!end) break;
        p = end + 1;
    }
    return 0;
}
/* Match actual p9 block identity plus one ext4 RW /user mount. Reject nested
 * mounts, duplicate/shadowed targets, malformed/oversized proc snapshots. */
static int user_mount(int directory) {
    char data[65537], *line, *next;
    size_t n = 0;
    int fd, matches = 0;
    struct stat block, user;
    if (lstat(RADIO_PERSIST_BLOCK, &block) || !S_ISBLK(block.st_mode) ||
        block.st_uid != RADIO_STORE_UID || block.st_nlink != 1 ||
        fstat(directory, &user) || block.st_rdev != user.st_dev) return 0;
    fd = open(RADIO_PERSIST_MOUNTS, O_RDONLY | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return 0;
    while (n < sizeof(data) - 1) {
        ssize_t got = read(fd, data + n, sizeof(data) - 1 - n);
        if (!got) break;
        if (got < 0) { close(fd); return 0; }
        n += (size_t)got;
    }
    close(fd);
    if (!n || n == sizeof(data) - 1 || data[n-1] != '\n' || memchr(data, 0, n)) return 0;
    data[n] = 0; line = data;
    while (*line) {
        char source[512], target[1024], type[64], options[1024], extra;
        unsigned dump, pass;
        next = strchr(line, '\n');
        if (!next || next-line > 3072) return 0;
        *next++ = 0;
        if (sscanf(line, "%511s %1023s %63s %1023s %u %u %c", source, target,
                   type, options, &dump, &pass, &extra) != 6 || strchr(target, '\\')) return 0;
        if (!strcmp(target, RADIO_USER_ROOT)) {
            if (++matches != 1 || strcmp(source, RADIO_PERSIST_BLOCK) || strcmp(type, "ext4") ||
                !mount_option(options, "rw") || mount_option(options, "ro")) return 0;
        } else if (!strncmp(target, RADIO_USER_ROOT "/", strlen(RADIO_USER_ROOT) + 1)) return 0;
        line = next;
    }
    return matches == 1;
}
static size_t canonical_wifi(char *out, size_t cap, const unsigned char *ssid, int ns,
                             const unsigned char *password, int np) {
    char ssid64[48], password64[88];
    int count;
    encode(ssid, (size_t)ns, ssid64); encode(password, (size_t)np, password64);
    count = snprintf(out, cap, "[request]\nschema=1\naction=wifi-connect\nssid64=%s\npassword64=%s\n", ssid64, password64);
    wipe(password64, sizeof(password64));
    return count > 0 && (size_t)count < cap ? (size_t)count : 0;
}
static int decode_saved(const char *raw, size_t n, unsigned char *ssid, int *ns,
                         unsigned char *password, int *np) {
    char copy[STORE_MAX + 1], canonical[STORE_MAX + 1];
    struct request r;
    size_t expected;
    int valid = 0;
    if (!n || n > STORE_MAX || raw[n-1] != '\n' || memchr(raw, 0, n)) return 0;
    memcpy(copy, raw, n); copy[n] = 0;
    if (!parse(copy, "wifi-connect", &r)) goto finish_saved;
    *ns = decode(r.ssid, ssid, 64); *np = decode(r.password, password, 64);
    if (!wifi_values_valid(ssid, *ns, password, *np)) goto finish_saved;
    expected = canonical_wifi(canonical, sizeof(canonical), ssid, *ns, password, *np);
    valid = expected == n && !memcmp(raw, canonical, n);
finish_saved:
    wipe(copy, sizeof(copy)); wipe(canonical, sizeof(canonical)); wipe(&r, sizeof(r));
    return valid;
}
static void saved_close(struct saved_wifi *saved) {
    if (saved->lock >= 0) close(saved->lock);
    if (saved->directory >= 0) close(saved->directory);
    saved->directory = saved->lock = -1;
    wipe(saved->previous, sizeof(saved->previous));
}
/* Return disabled(0), opted in(1), unsafe(-1). A bad pointer is never a
 * permission to silently downgrade to a different persistence location. */
static int saved_open(struct saved_wifi *saved) {
    struct stat pointer, lock_stat, user_stat, store_stat;
    char value[STORE_MAX + 1], expected[] = "schema=1\nstore=" STORE_ROOT "\n";
    unsigned char ssid[65], password[65];
    int runtime = -1, user = -1, dir = -1, next, state = -1, ns = 0, np = 0;
    size_t length = 0;
    const char *parts[] = {"pandanote", "config", "wifi"};
    unsigned i;
    memset(saved, 0, sizeof(*saved)); saved->directory = saved->lock = -1;
    if (lstat(STORE_POINTER, &pointer)) return errno == ENOENT ? 0 : -1;
    if (geteuid() != RADIO_STORE_UID || !private_file(&pointer)) return -1;
    runtime = walk_directory(RADIO_LOCAL);
    if (runtime < 0 || !private_directory(runtime, 1) ||
        read_private_at(runtime, "wifi-persistence", value, &length) != 1 ||
        length != sizeof(expected)-1 || memcmp(value, expected, length)) goto finish_open;
    user = walk_directory(RADIO_USER_ROOT);
    if (user < 0 || !private_directory(user, 0) || !user_mount(user) || fstat(user, &user_stat)) goto finish_open;
    dir = dup(user);
    if (dir < 0) goto finish_open;
    for (i = 0; i < sizeof(parts)/sizeof(parts[0]); i++) {
        next = openat(dir, parts[i], O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (next < 0) goto finish_open;
        close(dir); dir = next;
        if (!private_directory(dir, 1) || fstat(dir, &store_stat) || store_stat.st_dev != user_stat.st_dev) goto finish_open;
    }
    saved->directory = dir; dir = -1;
    if (!fstatat(saved->directory, ".lock", &lock_stat, AT_SYMLINK_NOFOLLOW)) {
        if (!S_ISREG(lock_stat.st_mode) || lock_stat.st_uid != RADIO_STORE_UID ||
            (lock_stat.st_mode & 07777) != 0600 || lock_stat.st_nlink != 1 ||
            lock_stat.st_size != 0) goto finish_open;
    } else if (errno != ENOENT) goto finish_open;
    saved->lock = openat(saved->directory, ".lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC, 0600);
    if (saved->lock < 0 || fstat(saved->lock, &lock_stat) || !S_ISREG(lock_stat.st_mode) ||
        lock_stat.st_uid != RADIO_STORE_UID || (lock_stat.st_mode & 07777) != 0600 ||
        lock_stat.st_nlink != 1 || lock_stat.st_size != 0 || flock(saved->lock, LOCK_EX | LOCK_NB)) goto finish_open;
    saved->present = read_private_at(saved->directory, STORE_CURRENT, saved->previous, &saved->bytes);
    if (saved->present < 0 || (saved->present && !decode_saved(saved->previous, saved->bytes, ssid, &ns, password, &np))) goto finish_open;
    saved->enabled = 1; state = 1;
finish_open:
    if (runtime >= 0) close(runtime);
    if (user >= 0) close(user);
    if (dir >= 0) close(dir);
    wipe(value, sizeof(value)); wipe(password, sizeof(password)); wipe(ssid, sizeof(ssid));
    if (state < 0) saved_close(saved);
    return state;
}
static int write_private_at(int directory, const char *name, const char *data, size_t length) {
    int fd = openat(directory, name, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    size_t n = 0;
    int ok = 0;
    struct stat st;
    if (fd < 0) return 0; /* Never remove or adopt a pre-existing transaction. */
    while (n < length) {
        ssize_t count = write(fd, data + n, length - n);
        if (count <= 0) goto finish_write;
        n += (size_t)count;
    }
    ok = !fstat(fd, &st) && private_file(&st) && st.st_size == (off_t)length && fsync(fd) == 0;
finish_write:
    if (close(fd)) ok = 0;
    if (!ok) unlinkat(directory, name, 0);
    return ok;
}
static int unchanged_saved(struct saved_wifi *saved) {
    char current[STORE_MAX + 1];
    size_t n = 0;
    int present = read_private_at(saved->directory, STORE_CURRENT, current, &n);
    int same = present == saved->present && (present == 0 ||
               (present == 1 && n == saved->bytes && !memcmp(current, saved->previous, n)));
    wipe(current, sizeof(current));
    return same;
}
/* Old bytes have a synced independent backup before replacement/deletion.
 * Ordinary write/rename/sync failure restores the old visible configuration.
 * If rollback or final backup cleanup fails, return uncertainty (-1).
 * A committed value does not establish durable removal of the old secret copy.
 * Stale fixed transaction names are preserved and cause a later save to refuse. */
static int saved_update(struct saved_wifi *saved, const char *data, size_t length, int forget) {
    int backup = 0, temporary = 0, committed = 0, ok = 0, rollback;
    struct stat leftover;
    if (!saved->enabled) return 1;
    if (!fstatat(saved->directory, STORE_TEMP, &leftover, AT_SYMLINK_NOFOLLOW) || errno != ENOENT) return 0;
    if (!fstatat(saved->directory, STORE_PREVIOUS, &leftover, AT_SYMLINK_NOFOLLOW) || errno != ENOENT) return 0;
    if (!unchanged_saved(saved)) return 0;
    if (saved->present) {
        if (!write_private_at(saved->directory, STORE_PREVIOUS, saved->previous, saved->bytes)) return 0;
        backup = 1;
    }
    if (!forget) {
        if (!write_private_at(saved->directory, STORE_TEMP, data, length)) goto finish_update;
        temporary = 1;
    }
    if (fsync(saved->directory) || !unchanged_saved(saved)) goto finish_update;
    if (forget) {
        if (saved->present && unlinkat(saved->directory, STORE_CURRENT, 0)) goto finish_update;
    } else if (renameat(saved->directory, STORE_TEMP, saved->directory, STORE_CURRENT)) goto finish_update;
    else temporary = 0;
    committed = 1;
    if (fsync(saved->directory)) {
        rollback = saved->present ? renameat(saved->directory, STORE_PREVIOUS, saved->directory, STORE_CURRENT) :
                                   unlinkat(saved->directory, STORE_CURRENT, 0);
        if (!rollback) { backup = 0; committed = 0; }
        if (rollback || fsync(saved->directory)) { ok = -1; goto finish_update; }
        goto finish_update;
    }
    ok = 1;
finish_update:
    if (temporary) unlinkat(saved->directory, STORE_TEMP, 0);
    if (backup && (!committed || ok == 1)) {
        if (unlinkat(saved->directory, STORE_PREVIOUS, 0) || fsync(saved->directory)) ok = -1;
    }
    return ok;
}
static int saved_store(struct saved_wifi *saved, const unsigned char *ssid, int ns,
                        const unsigned char *password, int np) {
    char canonical[STORE_MAX + 1];
    size_t n = canonical_wifi(canonical, sizeof(canonical), ssid, ns, password, np);
    int ok = n ? saved_update(saved, canonical, n, 0) : 0;
    wipe(canonical, sizeof(canonical));
    return ok;
}
