"""Runs only inside the verified offline image. All input/time is SIMULATED."""
import base64,json,os,re,resource,subprocess,time
from pathlib import Path
if os.environ.get('PANDANOTE_OFFLINE_GUARD_TEST')!='1': raise SystemExit('missing offline marker')
base=['/usr/bin/qemu-mipsel','-cpu','P5600','-L','/sample-qt/sysroot','-strace',
 '-E','QWS_NO_SHARE_FONTS=1','-E','HOME=/tmp','-E','TMPDIR=/tmp','-E','LD_LIBRARY_PATH=/opt/image/opt/Qtopia/lib:/lib:/usr/lib',
 '-E','LD_PRELOAD=/test-harness/libpandanote-fakefb.so','-E','QT_QWS_FONTDIR=/content-test/assets',
 '-E','QWS_DISPLAY=LinuxFb:nographicsmodeswitch:0','-E','QWS_KEYBOARD=none','-E','QWS_MOUSE_PROTO=none']
app='/content-test/reader-shell.mipsel';harness='/content-test/content.mipsel';traces=[];checks=0
start=time.monotonic()
def launch(args,name):
    file=open('/tmp/'+name+'.trace','wb');traces.append((name,file))
    return subprocess.Popen(base+args,stdout=subprocess.PIPE,stderr=file)
def finish(process,timeout=8):
    try: output,_=process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill();process.communicate();raise RuntimeError('unexpected bounded execution timeout')
    text=output.decode(errors='replace');print(text,end='');return process.returncode,text
def check(value,name):
    global checks
    checks+=1
    if not value: raise RuntimeError('FAIL '+name)
def records(text): return [json.loads(x) for x in text.splitlines() if x.startswith('{')]
try:
    code,text=finish(launch([harness],'runtime'))
    check(code==0 and 'PASS production runtime' in text,'actual Qt runtime checks')
    logs=records(text)
    check(any(x['event']=='CONTENT_LOADED' and not x['success'] and x['retained'] for x in logs),'bad package logs retention')
    check(any(x['event']=='NAVIGATION' and x['source']=='release' for x in logs),'release navigation log')
    check(any(x['event']=='NAVIGATION' and x['source']=='idle' for x in logs),'idle navigation log')
    for args in [['--developer-timeout-ms','200'],['--developer-mode'],['--developer-mode','--developer-timeout-ms','0'],['--developer-simulated-epoch','1792458000'],['--workspace-dir','relative'],['--workspace-dir'],['--workspace-dir','/'],['--bluetooth-ipc'],['--bluetooth-ipc','relative'],['--bluetooth-ipc','/'],['--sync-cache-dir'],['--sync-cache-dir','relative'],['--sync-cache-dir','/'],['--sync-cache-dir','/tmp/../bad'],['--sync-cache-dir','/tmp//bad'],['--sync-cache-dir','/tmp/bad/']]:
        code,text=finish(launch([app]+args,'invalid-'+str(checks)))
        check(code==2 and records(text)[0]['reason']=='invalid_arguments','invalid development args rejected before Qt')
    code,text=finish(launch([app,'--qws-server','--content-dir','/content-test/fixtures/valid','--developer-mode','--developer-timeout-ms','250'],'production-standalone'))
    check(code==0,'production standalone QWS server exits zero')
    check(any(x.get('reason')=='developer_timeout' for x in records(text)),'standalone exit uses developer reason')
    Path('/tmp/runtime-workspace').mkdir(mode=0o700)
    code,text=finish(launch([app,'--qws-server','--workspace-dir','/tmp/runtime-workspace','--content-dir','/content-test/fixtures/valid','--developer-mode','--developer-timeout-ms','150'],'production-workspace'))
    check(code==0 and Path('/tmp/runtime-workspace/notes').is_dir() and Path('/tmp/runtime-workspace/words').is_dir(),'explicit workspace production startup')
    check(not Path('/tmp/runtime-workspace/notes/data').exists(),'startup does not manufacture notes')
    code,text=finish(launch([app,'--qws-server','--bluetooth-ipc','/tmp/runtime-workspace/missing.sock','--content-dir','/content-test/fixtures/valid','--developer-mode','--developer-timeout-ms','180'],'production-bt-unavailable'))
    check(code==0,'configured but absent Bluetooth service keeps app usable')
    # The harness created a real immutable cache. Its explicit production CLI
    # must load it before falling back to the deliberately absent content dir.
    code,text=finish(launch([app,'--qws-server','--sync-cache-dir','/tmp/runtime-persistent-cache','--content-dir','/tmp/absent-content','--developer-mode','--developer-timeout-ms','150'],'production-persistent-cache'))
    check(code==0 and not any(x['event']=='CONTENT_LOADED' for x in records(text)),'explicit production cache resumes stored content')
    Path('/tmp/cache-parent-alias').symlink_to('/tmp/runtime-persistent-cache',target_is_directory=True)
    for unsafe in ['/tmp/cache-parent-alias/cache','/tmp/runtime-public/cache','/tmp/missing-parent/cache']:
        code,text=finish(launch([app,'--sync-cache-dir',unsafe],'production-unsafe-cache-'+str(checks)))
        check(code==4 and records(text)[0]['reason']=='sync_cache_unavailable','unsafe cache fails before Qt without creating paths')
    check(not Path('/tmp/runtime-public/cache').exists() and not Path('/tmp/missing-parent').exists(),'invalid cache paths not created')
    # A test-only stock-QWS server allows exercising the unchanged client entry.
    server=launch([harness,'--serve-only'],'qws-server')
    try:
        deadline=time.monotonic()+3
        while not list(Path('/tmp').glob('qtembedded-*/QtEmbedded-*')):
            if server.poll() is not None or time.monotonic()>deadline: raise RuntimeError('QWS fixture server not ready')
            time.sleep(.02)
        code,text=finish(launch([app,'--content-dir','/content-test/fixtures/valid','--developer-mode','--developer-timeout-ms','350','--developer-simulated-epoch','1792458000'],'production-developer'))
        check(code==0,'production developer exit zero')
        logs=records(text)
        check(any(x.get('time_source')=='SIMULATED' for x in logs),'fixture time labeled simulated')
        check([x.get('reason') for x in logs if x['event']=='EXIT_REASON']==['developer_timeout'],'timeout reason unambiguous')
        ordinary=launch([app,'--content-dir','/content-test/fixtures/valid'],'production-ordinary')
        time.sleep(.7);check(ordinary.poll() is None,'ordinary production has no short auto timeout')
        ordinary.terminate();code,text=finish(ordinary)
        check(any(x['event']=='CONTENT_LOADED' and x['success'] for x in records(text)),'ordinary production entered Qt')
        check(not any(x['event']=='EXIT_REASON' and x.get('reason')=='developer_timeout' for x in records(text)),'ordinary lifetime no developer exit')
    finally:
        server.terminate();finish(server)
    print('PASS offline production %d checks input=SIMULATED'%checks)
finally:
    combined=[]
    for name,file in traces:
        file.close();trace=Path('/tmp/'+name+'.trace').read_text(errors='replace');combined.append(name+'\n'+trace)
        if re.search(r'\b(mount|umount2|execve|reboot)\(|socket\((?:PF_|AF_)?INET',trace): raise RuntimeError('unexpected guest syscall: '+name)
    qsf_files=list(Path('/tmp').rglob('*.qsf'))
    qpf_records=sum(trace.count('QFontEngineQPF getFontFileName') for trace in combined)
    print('FONT_CACHE QWS_NO_SHARE_FONTS=1 qsf_files=%d qpf_records=%d'%(len(qsf_files),qpf_records))
    check(not qsf_files and not qpf_records,'shared font cache disabled')
    for path in sorted(Path('/tmp').glob('*.png')):
        print('PANDANOTE_FRAME_BASE64='+path.stem+':'+base64.b64encode(path.read_bytes()).decode())
    print('MONITOR duration_seconds=%.3f max_host_qemu_rss_kib=%d physical_reader_rss=UNMEASURED network=none hardware_access=false input=SIMULATED'%(time.monotonic()-start,resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss))
    print('PANDANOTE_TRACE_BASE64='+base64.b64encode('\n'.join(combined).encode()).decode())
