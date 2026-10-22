#!/usr/bin/env python3
"""Pinned minimal source build; compile/static inspect only, never target execution.
Explicit profile replaces Autotools, not an assertion that configure was run.
Headers derive from official matching-runtime source templates and target ABI.
"""
import hashlib,json,re,subprocess,shutil,tarfile,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SHELL=ROOT.parents[1]
OUT=ROOT/'build/c1';EVIDENCE=ROOT/'evidence/c1'
CONTAINER='pandanote-mips-dev';WORK='/work/pandanote-bluetooth-c1';LIB=WORK+'/runtime'
STATE='/tmp/pandanote-connectivity/bluetooth/var/lib/bluetooth'
ABI=['-EL','-march=mips32r2','-mabi=32','-mhard-float','-mfp64','-mnan=2008','-fPIC']
COMMANDS=[]
PINS={'bluez-5.87.tar.xz':'26bdcf2cebd7310c6f598850606b037ef0c515fe6608ebc54d22c50c4c32b35f','glib-2.62.4.tar.xz':'4c84030d77fa9712135dfa8036ad663925655ae95b1d19399b6200e869925bbc','dbus-1.12.16.tar.gz':'54a22d2fa42f2eb2a871f32811c6005b531b9613b1b93a0d269b05e7549fec80'}
URLS={'bluez-5.87.tar.xz':'https://www.kernel.org/pub/linux/bluetooth/bluez-5.87.tar.xz','glib-2.62.4.tar.xz':'https://download.gnome.org/sources/glib/2.62/glib-2.62.4.tar.xz','dbus-1.12.16.tar.gz':'https://dbus.freedesktop.org/releases/dbus/dbus-1.12.16.tar.gz'}
def sources():
    for name,pin in PINS.items():
        base=ROOT/'build' if name.startswith('bluez') else OUT
        archive=base/name
        if not archive.exists():
            data=urllib.request.urlopen(URLS[name],timeout=30).read()
            if hashlib.sha256(data).hexdigest()!=pin:raise ValueError('official download hash mismatch '+name)
            archive.write_bytes(data)
        if sha(archive)!=pin:raise ValueError('source archive pin mismatch '+name)
        prefix=name.split('.tar.')[0];expected=set()
        with tarfile.open(archive) as tar:
            for item in tar:
                parts=Path(item.name).parts
                if not parts or parts[0]!=prefix or '..' in parts or Path(item.name).is_absolute():raise ValueError('unsafe source member')
                target=base/item.name
                if target.is_symlink() or any(x.is_symlink() for x in target.parents if x!=base.parent):raise ValueError('source symlink')
                if item.isdir():target.mkdir(parents=True,exist_ok=True)
                elif item.isfile():
                    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(tar.extractfile(item).read());target.chmod(item.mode&0o755);expected.add(item.name)
                elif not (item.issym() or item.islnk()):raise ValueError('special source member')
        actual={str(x.relative_to(base)) for x in (base/prefix).rglob('*') if x.is_file()}
        if actual!=expected:raise ValueError('unexpected unpacked source file '+str(actual-expected))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def call(args):
    p=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=60)
    COMMANDS.append({'argv':[str(x) for x in args],'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr})
    if p.returncode:raise RuntimeError('command failed: '+' '.join(str(x) for x in args)+'\n'+p.stdout+p.stderr)
    return p.stdout
def inside(args):return call(['docker','exec','-w',WORK,CONTAINER,*args])
def render(text,values):
    def sub(m):
        if m[1] not in values:raise ValueError('unreviewed template field '+m[1])
        return str(values[m[1]])
    text=re.sub(r'@([A-Za-z0-9_]+)@',sub,text)
    def meson(m):
        key=m[1]
        if key not in values:raise ValueError('unreviewed meson field '+key)
        return '#define '+key+' 1' if values[key] else '/* #undef '+key+' */'
    text=re.sub(r'#mesondefine ([A-Za-z0-9_]+)',meson,text)
    return '\n'.join(line.rstrip() for line in text.splitlines())+'\n'
def validate_abi(values):
    want={'pointer':4,'long':4,'int':4,'short':2,'long_long':8,'endian':'little'}
    if values!=want:raise ValueError('unreviewed ABI '+repr(values))
    return values
def config(path):
    if path!=STATE:raise ValueError('state must use exact reviewed tmpfs location')
    defines={k:1 for k in ['HAVE_DECL_BASENAME','HAVE_DLFCN_H','HAVE_EXPLICIT_BZERO','HAVE_GETRANDOM','HAVE_INTTYPES_H','HAVE_LINUX_IF_ALG_H','HAVE_LINUX_TYPES_H','HAVE_LINUX_UHID_H','HAVE_LINUX_UINPUT_H','HAVE_RAWMEMCHR','HAVE_STDARG_H','HAVE_STDINT_H','HAVE_STDIO_H','HAVE_STDLIB_H','HAVE_STRINGS_H','HAVE_STRING_H','HAVE_SYS_RANDOM_H','HAVE_SYS_STAT_H','HAVE_SYS_TYPES_H','HAVE_UNISTD_H','STDC_HEADERS']}
    defines.update({'EXTERNAL_PLUGINS':0,'CONFIGDIR':'"/tmp/pandanote-connectivity/bluetooth/etc"','STORAGEDIR':json.dumps(path),'MESH_STORAGEDIR':json.dumps(path+'/mesh'),'VERSION':'"5.87"','PACKAGE':'"bluez"','PACKAGE_NAME':'"bluez"','PACKAGE_VERSION':'"5.87"','PACKAGE_STRING':'"bluez 5.87"','PACKAGE_TARNAME':'"bluez"','PACKAGE_BUGREPORT':'""','PACKAGE_URL':'""','LT_OBJDIR':'".libs/"'})
    return '\n'.join('#define '+k+' '+str(v) for k,v in sorted(defines.items()))+'\n'
def expand(text,values):
    for _ in range(20):
        def sub(m):
            if m[1] not in values:raise ValueError('unknown source variable '+m[1])
            return values[m[1]]
        result=re.sub(r'\$\((\w+)\)',sub,text)
        if result==text:return result
        text=result
    raise ValueError('recursive source variables')
def variables(path):
    text=path.read_text().replace('\\\n',' ');result={}
    for name,value in re.findall(r'^(\w+)\s*=\s*(.*)$',text,re.M):result.setdefault(name,value)
    return result

def headers():
    validate_abi({'pointer':4,'long':4,'int':4,'short':2,'long_long':8,'endian':'little'})
    values={'gint16':'short','gint16_modifier':'"h"','gint16_format':'"hi"','guint16_format':'"hu"','gint32':'int','gint32_modifier':'""','gint32_format':'"i"','guint32_format':'"u"','glib_extension':'G_GNUC_EXTENSION ','gint64':'long long','gint64_constant':'(G_GNUC_EXTENSION (val##LL))','guint64_constant':'(G_GNUC_EXTENSION (val##ULL))','gint64_modifier':'"ll"','gint64_format':'"lli"','guint64_format':'"llu"','glib_void_p':4,'glib_long':4,'glib_size_t':4,'glib_ssize_t':4,'glib_size_type_define':'int','gsize_modifier':'""','gssize_modifier':'""','gsize_format':'"u"','gssize_format':'"i"','glib_msize_type':'INT','g_pollfd_format':'"%d"','glib_gpi_cast':'(gint)','glib_gpui_cast':'(guint)','glib_intptr_type_define':'int','gintptr_modifier':'""','gintptr_format':'"i"','guintptr_format':'"u"','GLIB_MAJOR_VERSION':2,'GLIB_MINOR_VERSION':62,'GLIB_MICRO_VERSION':4,'glib_os':'#define G_OS_UNIX','glib_vacopy':'#define G_VA_COPY va_copy','g_have_iso_c_varargs':'#ifndef __cplusplus\n#define G_HAVE_ISO_VARARGS 1\n#endif','g_have_iso_cxx_varargs':'#ifdef __cplusplus\n#define G_HAVE_ISO_VARARGS 1\n#endif','g_threads_impl_def':'POSIX','g_bs_native':'LE','g_bs_alien':'BE','glongbits':32,'gintbits':32,'gsizebits':32,'g_byte_order':'G_LITTLE_ENDIAN','g_pollin':1,'g_pollout':4,'g_pollpri':2,'g_pollhup':16,'g_pollerr':8,'g_pollnval':32,'g_module_suffix':'so','g_pid_type':'int','g_pid_format':'"i"','g_af_unix':1,'g_af_inet':2,'g_af_inet6':10,'g_msg_oob':1,'g_msg_peek':2,'g_msg_dontroute':4,'g_dir_separator':'/','g_searchpath_separator':':','GLIB_HAVE_ALLOCA_H':True,'GLIB_USING_SYSTEM_PRINTF':True,'GLIB_STATIC_COMPILATION':False,'GOBJECT_STATIC_COMPILATION':False,'G_HAVE_GROWING_STACK':False,'G_HAVE_GNUC_VISIBILITY':True,'G_ATOMIC_OP_MEMORY_BARRIER_NEEDED':True,'G_ATOMIC_LOCK_FREE':True}
    generated=OUT/'generated';generated.mkdir(exist_ok=True)
    (generated/'glibconfig.h').write_text(render((OUT/'glib-2.62.4/glib/glibconfig.h.in').read_text(),values))
    dbus={'DBUS_INT64_TYPE':'long long','DBUS_INT64_CONSTANT':'(val##LL)','DBUS_UINT64_CONSTANT':'(val##ULL)','DBUS_INT32_TYPE':'int','DBUS_INT16_TYPE':'short','DBUS_MAJOR_VERSION':1,'DBUS_MINOR_VERSION':12,'DBUS_MICRO_VERSION':16,'DBUS_VERSION':'1.12.16'}
    (generated/'dbus-arch-deps.h').write_text(render((OUT/'dbus-1.12.16/dbus/dbus-arch-deps.h.in').read_text(),dbus))
    (generated/'config.h').write_text(config(STATE))
    (generated/'builtin.h').write_text('extern const struct bluetooth_plugin_desc __bluetooth_builtin_gap;\nstatic const struct bluetooth_plugin_desc *__bluetooth_builtin[] = { &__bluetooth_builtin_gap, NULL };\n')
    # This is a compile-only ABI/config proof, not a runtime probe or test shim.
    (generated/'header-check.c').write_text('''#include <glib.h>
#include <dbus/dbus.h>
#include <sys/socket.h>
#include <poll.h>
#include <stdint.h>
#include <stddef.h>
_Static_assert(sizeof(void*)==4 && sizeof(long)==4 && sizeof(int)==4 && sizeof(short)==2 && sizeof(long long)==8,"target ABI");
_Static_assert(__BYTE_ORDER__==__ORDER_LITTLE_ENDIAN__,"little endian");
_Static_assert(sizeof(gsize)==4 && sizeof(gssize)==4 && sizeof(gintptr)==4,"GLib ABI");
_Static_assert(sizeof(gint64)==8 && sizeof(dbus_int64_t)==8 && sizeof(dbus_uint32_t)==4,"integer ABI");
_Static_assert(sizeof(GPollFD)==8 && offsetof(GPollFD,revents)==6,"GPollFD ABI");
_Static_assert(__GCC_ATOMIC_INT_LOCK_FREE==2 && __GCC_ATOMIC_POINTER_LOCK_FREE==2,"atomic ABI");
_Static_assert(AF_UNIX==1 && AF_INET==2 && AF_INET6==10 && POLLIN==1 && POLLOUT==4 && POLLPRI==2 && POLLHUP==16 && POLLERR==8 && POLLNVAL==32,"kernel constant ABI");
_Static_assert(MSG_OOB==1 && MSG_PEEK==2 && MSG_DONTROUTE==4,"message flags");
const unsigned header_abi[] = {sizeof(void*),sizeof(long),sizeof(gsize),sizeof(GPollFD),sizeof(DBusMessageIter),GLIB_MAJOR_VERSION,GLIB_MINOR_VERSION,GLIB_MICRO_VERSION,DBUS_MAJOR_VERSION,DBUS_MINOR_VERSION,DBUS_MICRO_VERSION};
''')
    return generated

def main():
    OUT.mkdir(exist_ok=True);EVIDENCE.mkdir(exist_ok=True)
    try:
        if call(['docker','inspect',CONTAINER,'--format','{{.State.Status}}']).strip()!='running':raise RuntimeError('trusted compiler stopped')
        sources()
        bluez=ROOT/'build/bluez-5.87';generated=headers()
        call(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/objects',LIB,WORK+'/generated',WORK+'/startup'])
        for path,dest in [(bluez,'bluez'),(OUT/'glib-2.62.4','glib'),(OUT/'dbus-1.12.16','dbus')]:
            call(['docker','exec',CONTAINER,'mkdir','-p',WORK+'/'+dest])
            call(['docker','cp',str(path)+'/.',CONTAINER+':'+WORK+'/'+dest])
        call(['docker','cp',ROOT/'c1/compat-stat.h',CONTAINER+':'+WORK+'/generated/compat-stat.h'])
        call(['docker','cp',ROOT/'c1/private_log.c',CONTAINER+':'+WORK+'/private_log.c'])
        call(['docker','cp',ROOT/'c1/compat-paths.h',CONTAINER+':'+WORK+'/generated/compat-paths.h'])
        for p in generated.iterdir():call(['docker','cp',p,CONTAINER+':'+WORK+'/generated/'+p.name])
        call(['docker','exec',CONTAINER,'cp',WORK+'/generated/builtin.h',WORK+'/bluez/src/builtin.h'])
        call(['docker','exec',CONTAINER,'cp',WORK+'/generated/dbus-arch-deps.h',WORK+'/dbus/dbus/dbus-arch-deps.h'])
        inputs=json.loads((ROOT/'c1/inputs.json').read_text());runtime={}
        reference=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')))
        image=reference/inputs['rootfs_image']
        if sha(image)!=inputs['rootfs_sha256']:raise ValueError('original image digest')
        call(['docker','cp',image,CONTAINER+':'+WORK+'/rootfs.img'])
        if inside(['sha256sum','rootfs.img']).split()[0]!=inputs['rootfs_sha256']:raise ValueError('compiler image copy digest')
        for filename,(path,pin) in inputs['runtime'].items():
            inside(['debugfs','-R','dump '+path+' '+LIB+'/'+filename,'rootfs.img'])
            if inside(['sha256sum',LIB+'/'+filename]).split()[0]!=pin:raise ValueError('stock runtime digest '+filename)
            runtime[filename]=pin
        for name in ['start.S','entry.h','csu.cpp','libio-init.c']:
            baseline=(Path(__import__('os').environ.get('PANDANOTE_REFERENCE_ROOT', 'external-inputs')) / 'pandanote-analysis/app-development-research/minimal-qt/build-support')/name
            if sha(SHELL/'build-support'/name)!=sha(baseline):raise ValueError('startup pin '+name)
            call(['docker','cp',SHELL/'build-support'/name,CONTAINER+':'+WORK+'/startup/'+name])
        flags=ABI+['-O2','-g','-ffunction-sections','-fdata-sections','-fstack-protector-strong','-fno-builtin-ffsll','-include','generated/compat-stat.h','-DHAVE_CONFIG_H','-DBLUETOOTH_PLUGIN_BUILTIN','-D_GNU_SOURCE=','-DPLUGINDIR=""','-Dopenlog=pandanote_private_openlog','-Dcloselog=pandanote_private_closelog','-Dvsyslog=pandanote_private_vsyslog','-Dsyslog=pandanote_private_syslog','-Igenerated','-Ibluez','-Ibluez/lib','-Iglib','-Iglib/glib','-Idbus','-isystem','/usr/mipsisa32r6el-linux-gnu/include']
        inside(['mipsel-linux-gnu-gcc',*flags,'-Werror','-c','generated/header-check.c','-o','header-check.o'])
        v=variables(bluez/'Makefile.am')
        selections=['lib_libbluetooth_internal_la_SOURCES','gdbus_libgdbus_internal_la_SOURCES','src_libshared_glib_la_SOURCES','bluetoothd_internal_sources']
        source=sorted({p for name in selections for p in expand(v[name],v).split() if p.endswith('.c')}|{'src/main.c','src/plugin.c','profiles/gap/gas.c'})
        (EVIDENCE/'profile.json').write_text(json.dumps({'method':'explicit source/config profile from pinned upstream Makefile.am; not an Autotools configure run','disabled':'all optional profiles/plugins except gap; no external plugins, mesh, ELL, OBEX, tools, audio profile plugin, udev/systemd','sources':{p:sha(bluez/p) for p in source},'generated':{p.name:sha(p) for p in generated.iterdir()},'adapters':{p.name:sha(p) for p in (ROOT/'c1').glob('*.h')},'runtime':runtime},indent=2)+'\n')
        # Always rebuild every selected unit. Avoid trusting mutable cached
        # object files or stale config/header identities for a review artifact.
        for i,p in enumerate(source):
            obj='objects/'+p.replace('/','_')+'.o'
            inside(['mipsel-linux-gnu-gcc',*flags,*(['-include','generated/compat-paths.h'] if p in {'lib/bluetooth/sdp.c','src/sdpd-server.c'} else []),'-c','bluez/'+p,'-o',obj])
            if i%20==0:print('compile',i+1,'/',len(source),p,flush=True)
        for p,obj,compiler in [('start.S','start.o','gcc'),('libio-init.c','libio.o','gcc'),('csu.cpp','csu.o','g++')]:inside(['mipsel-linux-gnu-'+compiler,*ABI,'-O2','-Istartup','-c','startup/'+p,'-o',obj])
        inside(['mipsel-linux-gnu-gcc',*flags,'-Wall','-Wextra','-Werror','-c','private_log.c','-o','private_log.o'])
        objects=['objects/'+p.replace('/','_')+'.o' for p in source]+['private_log.o']
        inside(['mipsel-linux-gnu-ld','-EL','-m','elf32ltsmip','-e','__start','--dynamic-linker','/lib/ld-linux-mipsn8.so.1','-rpath-link',LIB,'-L',LIB,'--no-allow-shlib-undefined','--gc-sections','-z','noexecstack','-z','relro','-z','now','start.o',*objects,'csu.o','libio.o','-l:libglib-2.0.so.0','-l:libdbus-1.so.3','-l:libdl.so.2','-l:librt.so.1','-l:libc.so.6','-l:ld-linux-mipsn8.so.1','-o','bluetoothd-5.87.mipsel'])
        inside(['mipsel-linux-gnu-strip','--strip-debug','-o','bluetoothd-5.87-stripped.mipsel','bluetoothd-5.87.mipsel'])
        elf=inside(['mipsel-linux-gnu-readelf','-h','-l','-A','-d','-V','--dyn-syms','--wide','bluetoothd-5.87-stripped.mipsel'])
        paths=inside(['mipsel-linux-gnu-strings','bluetoothd-5.87-stripped.mipsel'])
        absolute=[x for x in paths.splitlines() if x.startswith('/')]
        bad=[x for x in absolute if x.startswith('/var/') or x.startswith('/run/')]
        if bad:raise ValueError('unexpected global state path '+repr(bad))
        if STATE not in absolute:raise ValueError('volatile state path missing')
        if any(x in elf for x in ['(INIT_ARRAY)','(FINI_ARRAY)','GLIBC_2.30','GLIBC_2.33','GLIBC_2.34']):raise ValueError('unsupported runtime ABI')
        for marker in ['ELF32','little endian','mips32r2','nan2008','o32','Hard float (32-bit CPU, 64-bit FPU)']:
            if marker not in elf:raise ValueError('missing ELF ABI '+marker)
        for line in elf.splitlines():
            if ' UND ' in line and line.split()[-1].split('@')[0] in ('openlog','closelog','syslog','vsyslog','system','popen'):raise ValueError('global log/shell import '+line)
        (EVIDENCE/'compiled-paths.txt').write_text('\n'.join(absolute)+'\n')
        call(['docker','cp',CONTAINER+':'+WORK+'/bluetoothd-5.87-stripped.mipsel',OUT/'bluetoothd-5.87.mipsel']);(OUT/'bluetoothd-5.87.mipsel').chmod(0o600)
        (EVIDENCE/'daemon-elf.txt').write_text(elf)
        (EVIDENCE/'daemon-manifest.json').write_text(json.dumps({'execution_performed':False,'artifact_sha256':sha(OUT/'bluetoothd-5.87.mipsel'),'artifact_bytes':(OUT/'bluetoothd-5.87.mipsel').stat().st_size,'build_script_sha256':sha(Path(__file__)),'pins':PINS,'runtime':runtime,'STORAGEDIR':STATE,'adapter_sha256':{p.name:sha(p) for p in (ROOT/'c1').glob('*') if p.suffix in {'.h','.c'}},'rootfs_sha256':inputs['rootfs_sha256'],'offline_execution':'recorded separately; build script never executes target'},indent=2)+'\n')
        print('PASS source compile and strict link only; no target execution');return 0
    except Exception as e:print('FAIL',e);return 1
    finally:(EVIDENCE/'build-commands.json').write_text(json.dumps(COMMANDS,indent=2)+'\n')
if __name__=='__main__':raise SystemExit(main())
