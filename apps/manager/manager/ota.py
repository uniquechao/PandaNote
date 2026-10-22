"""OTA 业务状态机；内容 ACK 与软件健康确认始终独立。"""
import hashlib
import hmac
import os
from pathlib import Path
import re
import sqlite3
import time
from .ota_store import OtaStore, encode, digest, identifier, hex_value, strict_json, MAX_SEQUENCE
from .ota_signer import SignerClient, payload_contract, b64

STATES=('IDLE','CHECKING','OFFERED','DOWNLOADING','VERIFIED','WAITING_SAFE_WINDOW','APPLYING','COMMITTED_PENDING_REBOOT','BOOT_VERIFYING','HEALTHY','ROLLED_BACK','RECOVERY_REQUIRED')
TERMINAL={'HEALTHY','ROLLED_BACK','RECOVERY_REQUIRED'}
ERRORS={'none','network_failure','signature_invalid','authorization_expired','baseline_mismatch','bundle_invalid','storage_insufficient','power_unsafe','window_busy','prepare_cancelled','proof_invalid','apply_failed','reboot_failed','health_failed','recovery_required','internal_error'}
ERROR_STATES={
 'network_failure':{'CHECKING','OFFERED','DOWNLOADING'},
 'signature_invalid':{'CHECKING','OFFERED','DOWNLOADING','VERIFIED','RECOVERY_REQUIRED'},
 'authorization_expired':{'CHECKING','OFFERED','DOWNLOADING','VERIFIED','WAITING_SAFE_WINDOW'},
 'baseline_mismatch':{'CHECKING','OFFERED','VERIFIED','WAITING_SAFE_WINDOW','APPLYING','RECOVERY_REQUIRED'},
 'bundle_invalid':{'OFFERED','DOWNLOADING','VERIFIED','RECOVERY_REQUIRED'},
 'storage_insufficient':{'OFFERED','DOWNLOADING','VERIFIED','WAITING_SAFE_WINDOW','APPLYING','RECOVERY_REQUIRED'},
 'power_unsafe':{'WAITING_SAFE_WINDOW'},'window_busy':{'WAITING_SAFE_WINDOW'},
 'prepare_cancelled':{'WAITING_SAFE_WINDOW'},'proof_invalid':{'WAITING_SAFE_WINDOW','APPLYING','RECOVERY_REQUIRED'},
 'apply_failed':{'APPLYING','ROLLED_BACK','RECOVERY_REQUIRED'},
 'reboot_failed':{'COMMITTED_PENDING_REBOOT','BOOT_VERIFYING','RECOVERY_REQUIRED'},
 'health_failed':{'BOOT_VERIFYING','ROLLED_BACK','RECOVERY_REQUIRED'},
 'recovery_required':{'RECOVERY_REQUIRED'},'internal_error':set(STATES)-{'HEALTHY'},
}
CHECK_FIELDS={'schema','request_nonce','model','channel','ota_abi','old_package_sha256','old_native_sha256','old_boot_id','old_inittab_sha256','old_current_sha256','live_superblock_sha256','highest_sequence'}
OLD_FIELDS=('old_package_sha256','old_native_sha256','old_boot_id','old_inittab_sha256','old_current_sha256','live_superblock_sha256')

class OtaError(Exception):
    def __init__(self,code,status=409):self.code=code;self.status=status

def fail(code,status=409):raise OtaError(code,status)
def fields(value,required,optional=()):
    if not isinstance(value,dict) or set(value)-set(required)-set(optional) or not set(required)<=set(value):fail('invalid_input',400)
def number(value,low=0,high=MAX_SEQUENCE):
    if type(value) is not int or not low<=value<=high:fail('invalid_input',400)
    return value

def row_json(row):return dict(row) if row else None
def json_column(row,column):return strict_json(row[column].encode(),4*1024*1024)

def load_service(root,clock=time.time):
    """显式私有配置存在且 enabled=true 时启用；错误配置只关闭 OTA。"""
    path=Path(root)/'ota-config.json'
    if not path.exists():return None
    try:
        from .ota_publish import regular
        import stat
        if stat.S_IMODE(path.stat().st_mode)!=0o600:raise ValueError('invalid_input')
        config=strict_json(regular(path,16384));fields(config,{'schema','enabled','root','signer_socket','signer_uid','key_id'}, {'local_device_id'})
        if type(config['schema']) is not int or config['schema']!=1 or type(config['enabled']) is not bool or type(config['signer_uid']) is not int or config['signer_uid']<0 or config['signer_uid']==os.geteuid():raise ValueError('invalid_input')
        if not config['enabled']:return None
        configured=Path(config['root']).absolute();expected=(Path(root)/'ota').absolute()
        if configured!=expected or not Path(config['signer_socket']).is_absolute() or not isinstance(config['key_id'],str) or not re.fullmatch('[A-Za-z0-9._-]{1,64}',config['key_id']):raise ValueError('invalid_input')
        store=OtaStore(configured,clock)
        with store.db():pass
        return OtaService(store,SignerClient(config['signer_socket'],config['signer_uid']),config,clock)
    except (OSError,ValueError,sqlite3.Error,OtaError):return None

class OtaService:
    def __init__(self,store,signer,config=None,clock=time.time):
        self.store=store;self.signer=signer;self.config=config or {};self.clock=clock
    def now(self):return int(self.clock())
    def quarantine(self):
        with self.store.db(True) as db:
            db.execute("INSERT OR REPLACE INTO ota_settings VALUES('quarantined','storage_failure')")
            db.execute("UPDATE ota_campaigns SET state='PAUSED',revision=revision+1 WHERE state='RUNNING'")
            self.store.audit(db,'system','storage.quarantine','ota',result='storage_failure')
    def available(self,db):
        if db.execute("SELECT 1 FROM ota_settings WHERE key='quarantined'").fetchone():fail('storage_failure',503)
    def get(self,db,table,column,key):
        row=db.execute('SELECT * FROM '+table+' WHERE '+column+'=?',(key,)).fetchone()
        if row is None:fail('not_found',404)
        return row
    def idempotent(self,actor,operation,key,body,action):
        hex_value(key,32);body_sha=digest(encode(body))
        with self.store.db(True) as db:
            self.available(db)
            row=db.execute('SELECT * FROM ota_idempotency WHERE actor=? AND operation=? AND key=?',(actor,operation,key)).fetchone()
            if row:
                if row['body_sha256']!=body_sha:fail('idempotency_conflict')
                return strict_json(row['result'].encode(),1024*1024)
            result=action(db)
            db.execute('INSERT INTO ota_idempotency VALUES(?,?,?,?,?)',(actor,operation,key,body_sha,encode(result).decode()))
            return result
    def list(self,kind,cursor='',limit=20):
        if kind not in {'releases','campaigns','inputs'}:fail('not_found',404)
        number(limit,1,100)
        table,column={'releases':('ota_releases','release_id'),'campaigns':('ota_campaigns','campaign_id'),'inputs':('ota_inputs','input_sha256')}[kind]
        if cursor:hex_value(cursor,64 if kind=='inputs' else 32)
        self.expire()
        with self.store.db() as db:
            rows=list(db.execute('SELECT * FROM '+table+' WHERE '+column+'>? ORDER BY '+column+' LIMIT ?',(cursor,limit+1)))
            items=[]
            for row in rows[:limit]:
                if kind=='inputs':
                    data=json_column(row,'data');items.append(dict(input_sha256=row['input_sha256'],**data['meta']))
                elif kind=='releases':items.append(self.release_view(row))
                else:items.append(self.campaign_view(db,row))
        return dict(schema=1,ok=True,items=items,next_cursor=rows[limit-1][column] if len(rows)>limit else None)
    def release_view(self,row):
        data={k:row[k] for k in ('release_id','model','channel','sequence','version','input_sha256','state','revision','error','reason')}
        if row['payload']:data['payload']=json_column(row,'payload')
        return data
    def release(self,key):
        hex_value(key,32)
        with self.store.db() as db:return dict(schema=1,ok=True,release=self.release_view(self.get(db,'ota_releases','release_id',key)))
    def create_release(self,actor,key,value):
        fields(value,{'input_sha256','model','channel','version'});hex_value(value['input_sha256'])
        for name in ('model','channel','version'):
            if not isinstance(value[name],str) or not re.fullmatch('[A-Za-z0-9._-]{1,64}',value[name]):fail('invalid_input',400)
        def action(db):
            inputs=json_column(self.get(db,'ota_inputs','input_sha256',value['input_sha256']),'data')
            if any(inputs['meta'][k]!=value[k] for k in ('model','channel','version')):fail('incompatible_release')
            seq=db.execute('SELECT next_sequence FROM ota_sequences WHERE model=? AND channel=?',(value['model'],value['channel'])).fetchone();sequence=seq[0] if seq else 1
            number(sequence,1,MAX_SEQUENCE)
            db.execute('INSERT INTO ota_sequences VALUES(?,?,?) ON CONFLICT(model,channel) DO UPDATE SET next_sequence=excluded.next_sequence',(value['model'],value['channel'],sequence+1))
            release_id=identifier();db.execute('INSERT INTO ota_releases(release_id,model,channel,sequence,version,input_sha256,state) VALUES(?,?,?,?,?,?,?)',(release_id,value['model'],value['channel'],sequence,value['version'],value['input_sha256'],'DRAFT'))
            self.store.audit(db,actor,'release.create',release_id,None,1)
            return dict(schema=1,ok=True,release_id=release_id)
        return self.idempotent(actor,'release.create',key,value,action)
    def validate_release(self,release,inputs):
        package=self.store.read(inputs['target'],262144);manifest=strict_json(package)
        with self.store.db() as db:package_data=json_column(self.get(db,'ota_baselines','package_sha256',inputs['target']),'data')
        for item in manifest['files']:
            raw=self.store.read(package_data['files'][item['source']])
            if digest(raw)!=item['sha256'] or len(raw)!=item['bytes']:fail('baseline_mismatch')
        for tree in inputs['trees'].values():
            for item in tree.values():self.store.read(item['sha256'],256*1024*1024)
        payload=dict(schema=1,model=release['model'],channel=release['channel'],sequence=release['sequence'],version=release['version'],native_sha256=manifest['native_sha256'],boot_id=manifest['boot_id'],ota_abi=1,workspace_schema=1,files=[{k:f[k] for k in ('path','mode','bytes','sha256','role')} for f in manifest['files']]);payload_contract('release',encode(payload))
        return payload
    def release_action(self,actor,key,release_id,action,value):
        hex_value(key,32);hex_value(release_id,32);fields(value,{'revision'}, {'reason'} if action=='revoke' else ());number(value['revision'],1)
        if action not in {'validate','approve','revoke'}:fail('not_found',404)
        if action=='revoke' and (not isinstance(value.get('reason'),str) or not 1<=len(value['reason'])<=512):fail('invalid_input',400)
        # 审核与签名在长事务之外，最终提交必须仍然匹配原 revision。
        with self.store.db() as db:
            previous=db.execute('SELECT * FROM ota_idempotency WHERE actor=? AND operation=? AND key=?',(actor,'release.'+release_id+'.'+action,key)).fetchone()
            if previous:
                if previous['body_sha256']!=digest(encode(value)):fail('idempotency_conflict')
                return strict_json(previous['result'].encode())
            release=self.get(db,'ota_releases','release_id',release_id)
            if release['revision']!=value['revision']:fail('revision_conflict')
            inputs=json_column(self.get(db,'ota_inputs','input_sha256',release['input_sha256']),'data')
        payload=None;envelope=None
        if action=='validate':
            if release['state']!='DRAFT':fail('invalid_state')
            try:payload=self.validate_release(release,inputs)
            except (ValueError,OSError,KeyError,OtaError) as error:
                if isinstance(error,OSError) or str(error)=='storage_failure':self.quarantine()
                with self.store.db(True) as db:
                    db.execute("UPDATE ota_releases SET error='baseline_mismatch' WHERE release_id=? AND revision=? AND state='DRAFT'",(release_id,release['revision']))
                    self.store.audit(db,actor,'release.validate',release_id,release['revision'],release['revision'],'baseline_mismatch')
                fail('baseline_mismatch')
        elif action=='approve':
            if release['state']!='VALIDATED':fail('invalid_state')
            try:envelope=self.signer.sign('release',release_id,release['revision'],release['payload'].encode())
            except (OSError,ValueError):fail('signing_unavailable',503)
            if self.config.get('key_id') and envelope['key_id']!=self.config['key_id']:fail('signing_unavailable',503)
        elif release['state'] not in {'DRAFT','VALIDATED','APPROVED'}:fail('invalid_state')
        def commit(db):
            current=self.get(db,'ota_releases','release_id',release_id)
            if current['revision']!=release['revision'] or current['state']!=release['state']:fail('revision_conflict')
            state={'validate':'VALIDATED','approve':'APPROVED','revoke':'REVOKED'}[action]
            db.execute('UPDATE ota_releases SET state=?,revision=revision+1,payload=COALESCE(?,payload),envelope=COALESCE(?,envelope),reason=?,error=NULL WHERE release_id=?',(state,encode(payload).decode() if payload else None,encode(envelope).decode() if envelope else None,value.get('reason'),release_id))
            if action=='revoke':
                db.execute("UPDATE ota_campaigns SET state='PAUSED',revision=revision+1 WHERE release_id=? AND state='RUNNING'",(release_id,))
            self.store.audit(db,actor,'release.'+action,release_id,release['revision'],release['revision']+1)
            return dict(schema=1,ok=True,release_id=release_id)
        return self.idempotent(actor,'release.'+release_id+'.'+action,key,value,commit)
    def campaign_view(self,db,row):
        result=dict(row);result['policy']=json_column(row,'policy')
        result['counts']={item['state']:item['n'] for item in db.execute('SELECT state,COUNT(*) n FROM ota_targets WHERE campaign_id=? GROUP BY state',(row['campaign_id'],))}
        return result
    def campaign(self,key):
        hex_value(key,32);self.expire()
        with self.store.db() as db:
            result=self.campaign_view(db,self.get(db,'ota_campaigns','campaign_id',key))
            result['targets']=[dict(r) for r in db.execute('SELECT * FROM ota_targets WHERE campaign_id=? ORDER BY batch,device_id',(key,))]
            return dict(schema=1,ok=True,campaign=result)
    def create_campaign(self,actor,key,value):
        fields(value,{'release_id','device_ids','batches'}, {'policy'});hex_value(value['release_id'],32)
        devices=value['device_ids'];batches=value['batches']
        if not isinstance(devices,list) or not 1<=len(devices)<=32 or any(not isinstance(d,str) for d in devices) or len(set(devices))!=len(devices):fail('invalid_input',400)
        if not isinstance(batches,list) or not batches or any(not isinstance(b,list) or not b for b in batches):fail('invalid_input',400)
        flattened=[d for batch in batches for d in batch]
        if len(flattened)!=len(devices) or any(not isinstance(d,str) for d in flattened) or set(flattened)!=set(devices):fail('invalid_input',400)
        policy=value.get('policy',{})
        fields(policy,set(),{'observation_seconds','report_timeout_seconds'})
        policy=dict(observation_seconds=number(policy.get('observation_seconds',86400),86400,604800),report_timeout_seconds=number(policy.get('report_timeout_seconds',86400),3600,604800))
        def action(db):
            release=self.get(db,'ota_releases','release_id',value['release_id'])
            if release['state']!='APPROVED':fail('incompatible_release')
            for device_id in devices:
                device=db.execute('SELECT * FROM ota_devices WHERE device_id=?',(device_id,)).fetchone()
                if not device:fail('ota_not_enrolled')
                config=json_column(device,'config')
                allowed=getattr(self,'authorized_devices',None)
                if allowed is not None and (device_id not in allowed or (allowed[device_id] is not None and allowed[device_id]!=config['credential_sha256'])):fail('ota_not_enrolled')
                if config['model']!=release['model'] or release['channel'] not in config['channels'] or config['ota_abi']!=1 or device['alert']:fail('incompatible_release')
                baseline=db.execute('SELECT * FROM ota_baselines WHERE package_sha256=? AND reviewed=1',(device['baseline'],)).fetchone()
                if not baseline:fail('baseline_unsupported')
                if release['sequence']<device['highest_sequence']:fail('incompatible_release')
                if db.execute('SELECT 1 FROM ota_targets WHERE device_id=? AND (active=1 OR release_id=?)',(device_id,release['release_id'])).fetchone():fail('attempt_conflict')
            campaign_id=identifier();db.execute('INSERT INTO ota_campaigns(campaign_id,release_id,state,policy,created_at) VALUES(?,?,?,?,?)',(campaign_id,release['release_id'],'DRAFT',encode(policy).decode(),self.now()))
            for index,batch in enumerate(batches):
                for device_id in batch:db.execute('INSERT INTO ota_targets(target_id,campaign_id,release_id,device_id,batch,state) VALUES(?,?,?,?,?,?)',(identifier(),campaign_id,release['release_id'],device_id,index,'QUEUED'))
            self.store.audit(db,actor,'campaign.create',campaign_id,None,1)
            return dict(schema=1,ok=True,campaign_id=campaign_id)
        return self.idempotent(actor,'campaign.create',key,value,action)
    def campaign_action(self,actor,key,campaign_id,action,value):
        hex_value(campaign_id,32);fields(value,{'revision'});number(value['revision'],1);self.expire()
        def change(db):
            row=self.get(db,'ota_campaigns','campaign_id',campaign_id)
            if row['revision']!=value['revision']:fail('revision_conflict')
            release=self.get(db,'ota_releases','release_id',row['release_id'])
            transitions={'start':('DRAFT','RUNNING'),'pause':('RUNNING','PAUSED'),'resume':('PAUSED','RUNNING')}
            batch=row['batch'];state=row['state']
            if action in transitions:
                old,state=transitions[action]
                if row['state']!=old or (state=='RUNNING' and release['state']!='APPROVED'):fail('invalid_state')
                if state=='RUNNING' and db.execute('SELECT 1 FROM ota_targets WHERE campaign_id=? AND alert IS NOT NULL',(campaign_id,)).fetchone():fail('attempt_conflict')
            elif action=='advance':
                if state!='RUNNING':fail('invalid_state')
                current=list(db.execute('SELECT * FROM ota_targets WHERE campaign_id=? AND batch=?',(campaign_id,batch)))
                if not current or any(t['state']!='SUCCEEDED' or t['alert'] or not t['healthy_at'] or self.now()-t['healthy_at']<json_column(row,'policy')['observation_seconds'] for t in current):fail('observation_pending')
                if not db.execute('SELECT 1 FROM ota_targets WHERE campaign_id=? AND batch>?',(campaign_id,batch)).fetchone():state='FINISHED'
                else:batch+=1
            elif action=='cancel':
                if state not in {'DRAFT','RUNNING','PAUSED'}:fail('invalid_state')
                state='CANCELLED'
                db.execute("UPDATE ota_targets SET state='CANCELLED',active=0 WHERE campaign_id=? AND NOT EXISTS(SELECT 1 FROM ota_grants g WHERE g.target_id=ota_targets.target_id AND g.envelope IS NOT NULL)",(campaign_id,))
            else:fail('not_found',404)
            if action=='resume':
                # 恢复等待观测的目标，不降低 attempt 阶段或释放设备占用。
                db.execute("UPDATE ota_targets SET state=CASE WHEN phase IS NOT NULL THEN 'OBSERVING' WHEN EXISTS(SELECT 1 FROM ota_grants g WHERE g.target_id=ota_targets.target_id AND g.envelope IS NOT NULL) THEN 'AUTHORIZED' ELSE 'QUEUED' END WHERE campaign_id=? AND batch=? AND active=1 AND state='UNKNOWN'",(campaign_id,batch))
            if state=='RUNNING' and action in {'start','resume','advance'}:
                timer='batch_started:'+campaign_id+':'+str(batch)
                db.execute('INSERT OR REPLACE INTO ota_settings VALUES(?,?)',(timer,str(self.now())))
            db.execute('UPDATE ota_campaigns SET state=?,batch=?,revision=revision+1 WHERE campaign_id=?',(state,batch,campaign_id))
            self.store.audit(db,actor,'campaign.'+action,campaign_id,row['revision'],row['revision']+1)
            return dict(schema=1,ok=True,campaign_id=campaign_id)
        return self.idempotent(actor,'campaign.'+campaign_id+'.'+action,key,value,change)
    def device(self,device_id,credential=None):
        with self.store.db() as db:row=db.execute('SELECT * FROM ota_devices WHERE device_id=?',(device_id,)).fetchone()
        if row is None:fail('ota_not_enrolled')
        config=json_column(row,'config')
        if credential is not None and not hmac.compare_digest(config['credential_sha256'],hashlib.sha256(credential.encode()).hexdigest()):fail('ota_not_enrolled')
        return row
    def check(self,device_id,value,credential=None):
        fields(value,CHECK_FIELDS)
        if type(value['schema']) is not int or value['schema']!=1 or type(value['ota_abi']) is not int or value['ota_abi']!=1:fail('invalid_input',400)
        number(value['highest_sequence']);hex_value(value['request_nonce'])
        for name in OLD_FIELDS:hex_value(value[name],24 if name=='old_boot_id' else 64)
        device=self.device(device_id,credential);config=json_column(device,'config')
        if value['model']!=config['model'] or value['channel'] not in config['channels']:fail('incompatible_release')
        self.expire()
        with self.store.db(True) as db:
            self.available(db)
            previous=db.execute('SELECT * FROM ota_grants WHERE device_id=? AND nonce=?',(device_id,value['request_nonce'])).fetchone()
            if previous:
                if previous['request_sha256']!=digest(encode(value)):fail('nonce_conflict')
                grant_id=previous['grant_id']
            else:
                current=self.get(db,'ota_devices','device_id',device_id)
                if current['alert']:fail('baseline_mismatch')
                target=db.execute('SELECT t.* FROM ota_targets t JOIN ota_campaigns c USING(campaign_id) JOIN ota_releases r ON r.release_id=t.release_id WHERE t.device_id=? AND t.active=1 AND c.state=\'RUNNING\' AND t.batch=c.batch AND r.state=\'APPROVED\'',(device_id,)).fetchone()
                if not target:return dict(schema=1,status='no_update')
                release=self.get(db,'ota_releases','release_id',target['release_id'])
                if release['sequence']<max(value['highest_sequence'],current['highest_sequence']):return dict(schema=1,status='no_update')
                baseline=db.execute('SELECT * FROM ota_baselines WHERE package_sha256=? AND reviewed=1',(value['old_package_sha256'],)).fetchone()
                if not baseline:fail('baseline_unsupported')
                old=json_column(baseline,'data')['manifest'];old_files={f['path']:f for f in old['files']}
                expected=dict(old_package_sha256=baseline['package_sha256'],old_native_sha256=old['native_sha256'],old_boot_id=old['boot_id'],old_inittab_sha256=old_files['/etc/inittab']['sha256'],old_current_sha256=old_files['/user/pandanote/apps/current']['sha256'])
                if current['baseline']!=value['old_package_sha256'] or any(value[k]!=v for k,v in expected.items()):fail('baseline_mismatch')
                prior=db.execute('SELECT request FROM ota_grants WHERE target_id=? AND envelope IS NOT NULL LIMIT 1',(target['target_id'],)).fetchone()
                if prior and any(strict_json(prior[0].encode())[k]!=value[k] for k in OLD_FIELDS):fail('baseline_mismatch')
                inputs=json_column(self.get(db,'ota_inputs','input_sha256',release['input_sha256']),'data')
                build_key=digest(encode(dict(release_sha256=digest(release['payload'].encode()),input_sha256=release['input_sha256'],toolchain_sha256=inputs['meta']['toolchain_sha256'],**{k:value[k] for k in OLD_FIELDS})))
                job=db.execute('SELECT * FROM ota_jobs WHERE build_key=?',(build_key,)).fetchone()
                if not job:
                    if db.execute("SELECT COUNT(*) FROM ota_jobs WHERE state IN ('QUEUED','BUILDING')").fetchone()[0]>=64:fail('build_unavailable',503)
                    if db.execute("SELECT 1 FROM ota_jobs WHERE target_id=? AND state IN ('QUEUED','BUILDING')",(target['target_id'],)).fetchone():fail('build_unavailable',503)
                    job_id=identifier();db.execute('INSERT INTO ota_jobs(job_id,build_key,target_id,request,state) VALUES(?,?,?,?,?)',(job_id,build_key,target['target_id'],encode(value).decode(),'QUEUED'))
                else:job_id=job['job_id']
                grant_id=identifier();db.execute('INSERT INTO ota_grants(grant_id,device_id,nonce,request_sha256,request,target_id,job_id,state,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(grant_id,device_id,value['request_nonce'],digest(encode(value)),encode(value).decode(),target['target_id'],job_id,'PENDING',self.now()))
        return self.offer(grant_id)
    def offer(self,grant_id):
        with self.store.db() as db:
            grant=self.get(db,'ota_grants','grant_id',grant_id);target=self.get(db,'ota_targets','target_id',grant['target_id']);campaign=self.get(db,'ota_campaigns','campaign_id',target['campaign_id']);release=self.get(db,'ota_releases','release_id',target['release_id']);job=self.get(db,'ota_jobs','job_id',grant['job_id'])
            if release['state']=='REVOKED':fail('release_revoked')
            if campaign['state']=='CANCELLED':return dict(schema=1,status='no_update')
            if grant['envelope']:
                if grant['expires_at']<=self.now():fail('grant_expired')
                return self.offer_view(db,grant,release)
            if campaign['state']!='RUNNING' or target['batch']!=campaign['batch']:return dict(schema=1,status='no_update')
            if job['state']=='FAILED':fail(job['error'] or 'build_unavailable',503)
            artifact=db.execute('SELECT * FROM ota_artifacts WHERE build_key=?',(job['build_key'],)).fetchone()
            if not artifact:return dict(schema=1,retry_seconds=60)
            request=json_column(grant,'request');device=self.get(db,'ota_devices','device_id',grant['device_id']);config=json_column(device,'config')
            if device['alert']:fail('baseline_mismatch')
            revision=campaign['revision'];release_revision=release['revision'];now=self.now()
            bundle=self.get(db,'ota_objects','sha256',artifact['bundle'])
            payload=dict(schema=1,device_id=grant['device_id'],request_nonce=grant['nonce'],release_sha256=digest(release['payload'].encode()),sequence=release['sequence'],candidate_sha256=artifact['candidate'],bundle_sha256=artifact['bundle'],bundle_bytes=bundle['bytes'],helper_sha256=config['helper_sha256'],issued_at=now,expires_at=now+3600,**{k:request[k] for k in OLD_FIELDS})
        try:envelope=self.signer.sign('deployment',grant_id,revision,encode(payload))
        except (OSError,ValueError):fail('signing_unavailable',503)
        if self.config.get('key_id') and envelope['key_id']!=self.config['key_id']:fail('signing_unavailable',503)
        with self.store.db(True) as db:
            self.available(db);latest=self.get(db,'ota_campaigns','campaign_id',campaign['campaign_id']);current=self.get(db,'ota_releases','release_id',release['release_id']);grant=self.get(db,'ota_grants','grant_id',grant_id)
            if latest['revision']!=revision or latest['state']!='RUNNING' or current['revision']!=release_revision or current['state']!='APPROVED':fail('revision_conflict')
            if not grant['envelope']:
                db.execute("UPDATE ota_grants SET state='AUTHORIZED',envelope=?,expires_at=? WHERE grant_id=?",(encode(envelope).decode(),payload['expires_at'],grant_id))
                db.execute("UPDATE ota_targets SET state='AUTHORIZED',candidate=?,bundle=? WHERE target_id=? AND state IN ('QUEUED','BUILDING','AUTHORIZED')",(artifact['candidate'],artifact['bundle'],target['target_id']))
                db.execute('UPDATE ota_devices SET highest_sequence=MAX(highest_sequence,?) WHERE device_id=?',(release['sequence'],grant['device_id']))
                self.store.audit(db,'signer','grant.issue',grant_id,revision,revision)
            return self.offer_view(db,self.get(db,'ota_grants','grant_id',grant_id),current)
    def offer_view(self,db,grant,release):
        job=self.get(db,'ota_jobs','job_id',grant['job_id']);artifact=self.get(db,'ota_artifacts','build_key',job['build_key'])
        response=dict(schema=1,status='update',release=json_column(release,'envelope'),deployment=json_column(grant,'envelope'),candidate_b64=b64(self.store.read(artifact['candidate'],262144)))
        if len(encode(response))>768*1024:fail('response_too_large',503)
        return response
    def chunk(self,device_id,value,credential=None):
        fields(value,{'schema','bundle_sha256','index'})
        if type(value['schema']) is not int or value['schema']!=1:fail('invalid_input',400)
        hex_value(value['bundle_sha256']);number(value['index'],0,95);self.device(device_id,credential)
        with self.store.db() as db:
            self.available(db)
            row=db.execute("SELECT 1 FROM ota_grants g JOIN ota_targets t USING(target_id) JOIN ota_campaigns c USING(campaign_id) JOIN ota_releases r ON r.release_id=t.release_id WHERE g.device_id=? AND t.bundle=? AND g.envelope IS NOT NULL AND g.expires_at>? AND c.state NOT IN ('CANCELLED') AND r.state='APPROVED'",(device_id,value['bundle_sha256'],self.now())).fetchone()
            if not row:fail('not_found',404)
        return self.store.chunk(value['bundle_sha256'],value['index'])
    def pause(self,db,target,alert):
        db.execute('UPDATE ota_targets SET alert=? WHERE target_id=?',(alert,target['target_id']))
        db.execute('UPDATE ota_devices SET alert=? WHERE device_id=?',(alert,target['device_id']))
        db.execute("UPDATE ota_campaigns SET state='PAUSED',revision=revision+1 WHERE campaign_id=? AND state='RUNNING'",(target['campaign_id'],))
    def report(self,device_id,value,credential=None):
        fields(value,{'schema','attempt_id','event_id','sequence','bundle_sha256','active_native_sha256','state','error_code','boot_id'})
        if type(value['schema']) is not int or value['schema']!=1:fail('invalid_input',400)
        number(value['sequence'],1)
        for k in ('attempt_id','event_id'):hex_value(value[k],32)
        for k in ('bundle_sha256','active_native_sha256'):hex_value(value[k])
        hex_value(value['boot_id'],24)
        if not isinstance(value['state'],str) or not isinstance(value['error_code'],str) or value['state'] not in STATES or value['error_code'] not in ERRORS:fail('invalid_input',400)
        state=value['state'];error=value['error_code']
        if error!='none' and state not in ERROR_STATES[error]:fail('invalid_input',400)
        if state=='HEALTHY' and error!='none' or state=='RECOVERY_REQUIRED' and error=='none' or state=='ROLLED_BACK' and error=='none':fail('invalid_input',400)
        self.device(device_id,credential);sha=digest(encode(value));now=self.now()
        with self.store.db(True) as db:
            existing=db.execute('SELECT body_sha256 FROM ota_events WHERE device_id=? AND event_id=?',(device_id,value['event_id'])).fetchone()
            if existing:
                if existing[0]!=sha:fail('event_conflict')
                return dict(schema=1,ok=True)
            grant=db.execute('SELECT g.* FROM ota_grants g JOIN ota_targets t USING(target_id) JOIN ota_releases r ON r.release_id=t.release_id WHERE g.device_id=? AND t.bundle=? AND r.sequence=? AND g.envelope IS NOT NULL ORDER BY g.created_at LIMIT 1',(device_id,value['bundle_sha256'],value['sequence'])).fetchone()
            if not grant:fail('attempt_conflict')
            target=self.get(db,'ota_targets','target_id',grant['target_id']);release=self.get(db,'ota_releases','release_id',target['release_id']);payload=json_column(release,'payload');old=json_column(grant,'request')
            if state in {'HEALTHY','ROLLED_BACK'}:
                native=payload['native_sha256'] if state=='HEALTHY' else old['old_native_sha256'];boot=payload['boot_id'] if state=='HEALTHY' else old['old_boot_id']
                if value['active_native_sha256']!=native or value['boot_id']!=boot:
                    self.pause(db,target,'baseline_mismatch')
                    self.store.audit(db,device_id,'report.identity_conflict',value['event_id'],result=encode(value).decode())
                    # 拒绝 ACK，但保留身份冲突证据及暂停策略。
                    db.commit()
                    fail('baseline_mismatch')
            attempt=db.execute('SELECT * FROM ota_attempts WHERE device_id=? AND attempt_id=?',(device_id,value['attempt_id'])).fetchone()
            if attempt and (attempt['target_id']!=target['target_id'] or attempt['bundle']!=value['bundle_sha256'] or attempt['sequence']!=value['sequence']):fail('attempt_conflict')
            if not attempt:
                if db.execute('SELECT 1 FROM ota_attempts WHERE target_id=?',(target['target_id'],)).fetchone():fail('attempt_conflict')
                db.execute('INSERT INTO ota_attempts(device_id,attempt_id,target_id,sequence,bundle,state) VALUES(?,?,?,?,?,?)',(device_id,value['attempt_id'],target['target_id'],value['sequence'],value['bundle_sha256'],'IDLE'))
            previous=attempt['state'] if attempt else 'IDLE'
            conflict=previous in TERMINAL and state in TERMINAL and state!=previous
            db.execute('INSERT INTO ota_events(device_id,event_id,attempt_id,body_sha256,raw,created_at) VALUES(?,?,?,?,?,?)',(device_id,value['event_id'],value['attempt_id'],sha,encode(value).decode(),now))
            db.execute('UPDATE ota_devices SET last_report=?,observed=? WHERE device_id=?',(now,encode(value).decode(),device_id));db.execute('UPDATE ota_targets SET last_report=? WHERE target_id=?',(now,target['target_id']))
            if conflict:
                db.execute('UPDATE ota_attempts SET alert=? WHERE device_id=? AND attempt_id=?',('terminal_conflict',device_id,value['attempt_id']));self.pause(db,target,'terminal_conflict')
                other=db.execute('SELECT * FROM ota_targets WHERE device_id=? AND active=1 AND target_id!=?',(device_id,target['target_id'])).fetchone()
                if other:self.pause(db,other,'terminal_conflict')
                else:db.execute('UPDATE ota_targets SET active=1 WHERE target_id=?',(target['target_id'],))
            elif state not in {'IDLE','CHECKING'} and previous not in TERMINAL and STATES.index(state)>STATES.index(previous):
                db.execute('UPDATE ota_attempts SET state=? WHERE device_id=? AND attempt_id=?',(state,device_id,value['attempt_id']))
                db.execute('UPDATE ota_targets SET phase=?,state=? WHERE target_id=?',(state,'SUCCEEDED' if state=='HEALTHY' else 'FAILED' if state in TERMINAL else 'OBSERVING',target['target_id']))
                if state=='HEALTHY':
                    candidate=self.get(db,'ota_baselines','package_sha256',target['candidate'])
                    # 候选闭包已在 worker 提交前独立核验并完整落盘。
                    if not candidate:fail('storage_failure',503)
                    db.execute('UPDATE ota_baselines SET reviewed=1 WHERE package_sha256=?',(target['candidate'],))
                    db.execute('UPDATE ota_devices SET baseline=? WHERE device_id=?',(target['candidate'],device_id))
                    db.execute('UPDATE ota_targets SET healthy_at=?,active=0 WHERE target_id=?',(now,target['target_id']))
                elif state in TERMINAL:self.pause(db,target,state.lower())
            if error in {'signature_invalid','baseline_mismatch','bundle_invalid'}:self.pause(db,target,error)
        return dict(schema=1,ok=True)
    def expire(self):
        now=self.now()
        with self.store.db(True) as db:
            for row in db.execute("SELECT t.*,c.policy,c.created_at FROM ota_targets t JOIN ota_campaigns c USING(campaign_id) WHERE t.active=1 AND t.batch=c.batch AND c.state IN ('RUNNING','PAUSED') AND t.state IN ('QUEUED','AUTHORIZED','OBSERVING','BUILDING')"):
                timer=db.execute('SELECT value FROM ota_settings WHERE key=?',('batch_started:'+row['campaign_id']+':'+str(row['batch']),)).fetchone()
                activated=int(timer[0]) if timer else row['created_at']
                last_observation=max(row['last_report'] or 0,activated)
                if now-last_observation>json_column(row,'policy')['report_timeout_seconds']:
                    db.execute("UPDATE ota_targets SET state='UNKNOWN' WHERE target_id=?",(row['target_id'],))
                    db.execute("UPDATE ota_campaigns SET state='PAUSED',revision=revision+1 WHERE campaign_id=? AND state='RUNNING'",(row['campaign_id'],))
    def device_view(self,device_id):
        self.expire()
        with self.store.db() as db:
            row=db.execute('SELECT * FROM ota_devices WHERE device_id=?',(device_id,)).fetchone()
            if not row:return dict(schema=1,ok=True,enrolled=False,device_id=device_id)
            config=json_column(row,'config');baseline=self.get(db,'ota_baselines','package_sha256',row['baseline']);manifest=json_column(baseline,'data')['manifest']
            target=db.execute('SELECT * FROM ota_targets WHERE device_id=? AND active=1',(device_id,)).fetchone()
            return dict(schema=1,ok=True,enrolled=True,device_id=device_id,model=config['model'],channels=config['channels'],ota_abi=config['ota_abi'],helper_sha256=config['helper_sha256'],bootstrap_version=config['bootstrap_version'],confirmed=dict(package_sha256=row['baseline'],native_sha256=manifest['native_sha256'],boot_id=manifest['boot_id']),last_report=row['last_report'],observed=json_column(row,'observed') if row['observed'] else None,alert=row['alert'],target=row_json(target),automatic_install=None)
    def attempts(self,device_id,cursor=0,limit=20,attempt_cursor=''):
        number(cursor);number(limit,1,100)
        if attempt_cursor:hex_value(attempt_cursor,32)
        with self.store.db() as db:
            events=list(db.execute('SELECT * FROM ota_events WHERE device_id=? AND received>? ORDER BY received LIMIT ?',(device_id,cursor,limit+1)))
            attempts=[dict(r) for r in db.execute('SELECT * FROM ota_attempts WHERE device_id=? AND attempt_id>? ORDER BY attempt_id LIMIT ?',(device_id,attempt_cursor,limit+1))]
            next_attempt_cursor=attempts[limit-1]['attempt_id'] if len(attempts)>limit else None
            attempts=attempts[:limit]
            for attempt in attempts:
                target=self.get(db,'ota_targets','target_id',attempt['target_id']);release=self.get(db,'ota_releases','release_id',target['release_id']);job=db.execute('SELECT build_key FROM ota_jobs WHERE target_id=? AND state=\'READY\' ORDER BY job_id LIMIT 1',(target['target_id'],)).fetchone()
                attempt['recovery']=dict(candidate_sha256=target['candidate'],bundle_sha256=target['bundle'],input_sha256=release['input_sha256'],build_key=job[0] if job else None)
            return dict(schema=1,ok=True,attempts=attempts,next_attempt_cursor=next_attempt_cursor,events=[dict(received=e['received'],created_at=e['created_at'],event=json_column(e,'raw')) for e in events[:limit]],next_cursor=events[limit-1]['received'] if len(events)>limit else None)
