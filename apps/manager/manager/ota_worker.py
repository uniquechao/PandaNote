"""单独启动的持久候选 worker；只构建普通文件，绝不执行 ADB/helper。"""
import argparse
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from .ota_store import OtaStore, encode, strict_json, digest
from .ota_publish import materialize_package, materialize_tree, tool_module, import_package, files_contract
from .ota import OtaService, OtaError, json_column

class Worker:
    def __init__(self,store):self.store=store
    def claim(self):
        now=int(self.store.clock())
        with self.store.db(True) as db:
            if db.execute("SELECT 1 FROM ota_settings WHERE key='quarantined'").fetchone():return None
            exhausted=list(db.execute("SELECT j.* FROM ota_jobs j WHERE j.state='BUILDING' AND j.lease_until<=? AND j.tries>=3",(now,)))
            for row in exhausted:
                db.execute("UPDATE ota_jobs SET state='FAILED',error='build_unavailable' WHERE job_id=?",(row['job_id'],))
                db.execute("UPDATE ota_targets SET state='FAILED' WHERE target_id=?",(row['target_id'],))
                target=db.execute('SELECT * FROM ota_targets WHERE target_id=?',(row['target_id'],)).fetchone()
                OtaService(self.store,None).pause(db,target,'build_unavailable')
            if db.execute("SELECT 1 FROM ota_jobs WHERE state='BUILDING' AND lease_until>?",(now,)).fetchone():return None
            job=db.execute("SELECT j.* FROM ota_jobs j JOIN ota_targets t USING(target_id) JOIN ota_campaigns c USING(campaign_id) JOIN ota_releases r ON r.release_id=t.release_id WHERE (j.state='QUEUED' OR (j.state='BUILDING' AND j.lease_until<=?)) AND j.tries<3 AND t.active=1 AND t.batch=c.batch AND c.state='RUNNING' AND r.state='APPROVED' ORDER BY j.job_id LIMIT 1",(now,)).fetchone()
            if not job:return None
            db.execute("UPDATE ota_jobs SET state='BUILDING',generation=generation+1,lease_until=?,started_at=?,tries=tries+1 WHERE job_id=?",(now+120,now,job['job_id']))
            db.execute("UPDATE ota_targets SET state='BUILDING' WHERE target_id=? AND state='QUEUED'",(job['target_id'],))
            job=dict(db.execute('SELECT * FROM ota_jobs WHERE job_id=?',(job['job_id'],)).fetchone())
            target=db.execute('SELECT * FROM ota_targets WHERE target_id=?',(job['target_id'],)).fetchone()
            campaign=db.execute('SELECT revision FROM ota_campaigns WHERE campaign_id=?',(target['campaign_id'],)).fetchone()
            release=db.execute('SELECT revision FROM ota_releases WHERE release_id=?',(target['release_id'],)).fetchone()
            job['campaign_revision']=campaign[0];job['release_revision']=release[0]
            return job
    def renew(self,job):
        now=int(self.store.clock())
        with self.store.db(True) as db:
            changed=db.execute("UPDATE ota_jobs SET lease_until=? WHERE job_id=? AND generation=? AND state='BUILDING' AND lease_until>? AND started_at>?",(now+120,job['job_id'],job['generation'],now,now-600)).rowcount
            if changed!=1:raise ValueError('build_unavailable')
    def build(self,job,work):
        with self.store.db() as db:
            target=db.execute('SELECT * FROM ota_targets WHERE target_id=?',(job['target_id'],)).fetchone();release=db.execute('SELECT * FROM ota_releases WHERE release_id=?',(target['release_id'],)).fetchone();inputs=json_column(db.execute('SELECT * FROM ota_inputs WHERE input_sha256=?',(release['input_sha256'],)).fetchone(),'data');payload=json_column(release,'payload')
        request=strict_json(job['request'].encode());meta=inputs['meta']
        with self.store.db() as db:
            names=[item['sha256'] for tree in inputs['trees'].values() for item in tree.values()]
            names.extend(json_column(db.execute('SELECT * FROM ota_baselines WHERE package_sha256=?',(request['old_package_sha256'],)).fetchone(),'data')['files'].values())
            needed=sum(db.execute('SELECT bytes FROM ota_objects WHERE sha256=?',(sha,)).fetchone()[0] for sha in names)+48*1024*1024
        if needed>256*1024*1024:raise ValueError('storage_insufficient')
        for name,refs in inputs['trees'].items():materialize_tree(self.store,refs,work/name)
        materialize_package(self.store,request['old_package_sha256'],work/'old')
        module=tool_module(work/'snapshot','build')
        output=work/'candidate'
        module.build(work/'native',meta['native_sha256'],work/'reference',work/'radio'/meta['radio_binary'],output,native_source=work/'snapshot/apps/reader-shell',old_normal_package=work/'old',old_normal_package_sha256=request['old_package_sha256'],live_superblock_sha256=request['live_superblock_sha256'],suspend_helper_dir=work/'suspend',suspend_helper_sha256=meta['suspend_helper_sha256'])
        raw=(output/'manifest.json').read_bytes();manifest=strict_json(raw)
        actual=[{k:f[k] for k in ('path','mode','bytes','sha256','role')} for f in manifest['files']]
        files_contract(actual,manifest['native_sha256'],manifest['boot_id'])
        if actual!=payload['files'] or manifest['native_sha256']!=payload['native_sha256'] or manifest['boot_id']!=payload['boot_id']:raise ValueError('incompatible_release')
        wire,_=tool_module(work/'snapshot','normal_upgrade').capture_bundle(output,digest(raw))
        candidate=import_package(self.store,output,source='candidate',snapshot=work/'snapshot')
        bundle=self.store.put(wire,'wire')
        return candidate,bundle
    def commit(self,job,candidate,bundle):
        now=int(self.store.clock());conflict=False
        with self.store.db(True) as db:
            current=db.execute('SELECT * FROM ota_jobs WHERE job_id=?',(job['job_id'],)).fetchone()
            target=db.execute('SELECT * FROM ota_targets WHERE target_id=?',(job['target_id'],)).fetchone();campaign=db.execute('SELECT * FROM ota_campaigns WHERE campaign_id=?',(target['campaign_id'],)).fetchone();release=db.execute('SELECT * FROM ota_releases WHERE release_id=?',(target['release_id'],)).fetchone()
            if current['state']!='BUILDING' or current['generation']!=job['generation'] or current['lease_until']<=now or now-current['started_at']>=600:raise ValueError('build_unavailable')
            if campaign['state']!='RUNNING' or campaign['revision']!=job['campaign_revision'] or release['state']!='APPROVED' or release['revision']!=job['release_revision']:
                db.execute("UPDATE ota_jobs SET state='QUEUED',lease_until=0 WHERE job_id=?",(job['job_id'],));return
            previous=db.execute('SELECT * FROM ota_artifacts WHERE build_key=?',(job['build_key'],)).fetchone()
            if previous and (previous['candidate']!=candidate or previous['bundle']!=bundle):
                db.execute("INSERT OR REPLACE INTO ota_settings VALUES('quarantined','artifact_conflict')");db.execute("UPDATE ota_jobs SET state='FAILED',error='storage_failure' WHERE job_id=?",(job['job_id'],));conflict=True
            else:
                db.execute('INSERT OR IGNORE INTO ota_artifacts VALUES(?,?,?)',(job['build_key'],candidate,bundle));db.execute("UPDATE ota_jobs SET state='READY',lease_until=0 WHERE job_id=?",(job['job_id'],))
            self.store.audit(db,'worker','build.commit',job['job_id'],job['generation'],job['generation'],'artifact_conflict' if conflict else 'ok')
        if conflict:raise ValueError('storage_failure')
    def failed(self,job,code,temporary=False):
        with self.store.db(True) as db:
            row=db.execute('SELECT * FROM ota_jobs WHERE job_id=?',(job['job_id'],)).fetchone()
            if row['generation']!=job['generation'] or row['state']!='BUILDING':return
            retry=temporary and row['tries']<3
            db.execute('UPDATE ota_jobs SET state=?,error=?,lease_until=0 WHERE job_id=?',('QUEUED' if retry else 'FAILED',code,job['job_id']))
            if not retry:
                db.execute("UPDATE ota_targets SET state='FAILED' WHERE target_id=?",(job['target_id'],))
                target=db.execute('SELECT * FROM ota_targets WHERE target_id=?',(job['target_id'],)).fetchone();OtaService(self.store,None).pause(db,target,code)
    def run_once(self):
        job=self.claim()
        if not job:return False
        if shutil.disk_usage(self.store.root).free<1024**3+256*1024**2:
            self.failed(job,'storage_insufficient');return True
        with tempfile.TemporaryDirectory(dir=self.store.root/'staging') as work:
            work=Path(work);descriptor=work/'job.json';descriptor.write_bytes(encode(job));descriptor.chmod(0o600)
            command=[sys.executable,'-m','manager.ota_worker','--root',str(self.store.root),'--build-job',str(descriptor),'--work',str(work)]
            process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'})
            started=time.monotonic()
            try:
                while process.poll() is None:
                    try:process.wait(timeout=30)
                    except subprocess.TimeoutExpired:pass
                    self.renew(job)
                    if time.monotonic()-started>=600:raise ValueError('build_unavailable')
                result=strict_json((work/'result.json').read_bytes())
                if process.returncode or 'error' in result:
                    self.failed(job,result.get('error','build_unavailable'),result.get('temporary',False));return True
                self.commit(job,result['candidate'],result['bundle'])
            except (OSError,ValueError,sqlite3.Error):
                process.terminate()
                try:process.wait(timeout=5)
                except subprocess.TimeoutExpired:process.kill();process.wait()
                self.failed(job,'build_unavailable',True)
        return True

def main():
    parser=argparse.ArgumentParser(description='OTA 独立候选构建进程')
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--once',action='store_true');parser.add_argument('--build-job',type=Path);parser.add_argument('--work',type=Path)
    args=parser.parse_args();store=OtaStore(args.root);worker=Worker(store)
    if args.build_job:
        job=strict_json(args.build_job.read_bytes());result={}
        try:
            candidate,bundle=worker.build(job,args.work);result=dict(candidate=candidate,bundle=bundle)
        except ValueError as error:
            code=str(error);result=dict(error=code if code in {'baseline_mismatch','baseline_unsupported','incompatible_release','too_large','storage_insufficient'} else 'bundle_invalid',temporary=False)
        except (OSError,sqlite3.Error):result=dict(error='build_unavailable',temporary=True)
        (args.work/'result.json').write_bytes(encode(result));return
    store.verify()
    while True:
        worked=worker.run_once()
        if args.once:return
        if not worked:time.sleep(5)
if __name__=='__main__':main()
