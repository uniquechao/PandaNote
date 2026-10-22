import pytest
from manager.ota import OtaError
from manager.ota_store import identifier
from manager.ota_publish import import_package,files_contract
from manager.ota_worker import Worker
from ota_fixtures import Fixture

@pytest.fixture
def f(tmp_path):return Fixture(tmp_path)

def test_release_sequence_revision_and_irreversible_revoke(f):
    release,_,_,_=f.release();key=identifier();value={'revision':3,'reason':'测试撤回'}
    assert f.service.release_action('admin',key,release,'revoke',value)['ok']
    assert f.service.release_action('admin',key,release,'revoke',value)['ok']
    with pytest.raises(OtaError):f.service.release_action('admin',identifier(),release,'approve',{'revision':4})
    next_release,_,_,_=f.release('next');assert f.service.release(next_release)['release']['sequence']==2
    assert f.store.verify()

def test_complete_closure_missing_or_extra_file_rejected(f):
    target=f.old_dir/'files/etc/inittab';original=target.read_bytes();target.write_bytes(b'bad')
    with pytest.raises(ValueError):import_package(f.store,f.old_dir,reviewed=True,snapshot=f.snapshot)
    target.write_bytes(original);target.chmod(0o644);(f.old_dir/'extra').write_text('unexpected')
    with pytest.raises(ValueError):import_package(f.store,f.old_dir,reviewed=True,snapshot=f.snapshot)

def test_build_lease_fences_lost_worker_and_pause_revision(f):
    release,candidate,directory,_=f.release();campaign=f.campaign(release);request=f.check();f.service.check('one',request)
    worker=Worker(f.store);job=worker.claim();f.now+=121;new=worker.claim();assert new['generation']==job['generation']+1
    wire,_=__import__('manager.ota_publish',fromlist=['tool_module']).tool_module(f.snapshot,'normal_upgrade').capture_bundle(directory,candidate);bundle=f.store.put(wire,'wire')
    with pytest.raises(ValueError):worker.commit(job,candidate,bundle)
    f.service.campaign_action('admin',identifier(),campaign,'pause',{'revision':2});worker.commit(new,candidate,bundle)
    with f.store.db() as db:assert not db.execute('SELECT 1 FROM ota_artifacts').fetchone()

def test_all_devices_prechecked_fixed_batches_and_no_early_advance(f):
    release,_,_,_=f.release();campaign=f.campaign(release,['one','two'])
    with pytest.raises(OtaError) as e:f.service.campaign_action('admin',identifier(),campaign,'advance',{'revision':2})
    assert e.value.code=='observation_pending'
    assert f.service.check('two',f.check())['status']=='no_update'
    with pytest.raises(OtaError):f.campaign(release)

def test_revocation_during_signing_never_exposes_grant(f):
    release,candidate,directory,_=f.release();campaign=f.campaign(release);request=f.check();f.service.check('one',request);f.ready(request,candidate,directory)
    def hook(kind):
        if kind=='deployment':f.service.release_action('admin',identifier(),release,'revoke',{'revision':3,'reason':'测试并发撤回'})
    f.signer.hook=hook
    with pytest.raises(OtaError):f.service.check('one',request)
    with f.store.db() as db:assert not db.execute('SELECT 1 FROM ota_grants WHERE envelope IS NOT NULL').fetchone()

def test_nonce_conflict_and_boolean_sequence(f):
    release,_,_,_=f.release();f.campaign(release);request=f.check();f.service.check('one',request)
    with pytest.raises(OtaError) as e:f.service.check('one',{**request,'highest_sequence':1})
    assert e.value.code=='nonce_conflict'
    with pytest.raises(OtaError):f.service.check('one',{**request,'highest_sequence':True})

def test_worker_subprocess_orchestration_keeps_complete_candidate(f):
    """使用合成构建器验证子进程交接；真实 NORMAL 构建另需受控硬件参考输入。"""
    import shutil
    from manager.ota_publish import import_tree
    from manager.ota_store import encode,digest
    builder=f.snapshot/'apps/reader-shell/deploy/normal_boot/build.py'
    builder.write_text('from pathlib import Path\nimport shutil,json\ndef build(native,native_sha,reference,radio,output,**kwargs):\n shutil.copytree(reference,output)\n manifest=json.loads((output/"manifest.json").read_bytes())\n for item in manifest["files"]:(output/item["source"]).chmod(item["mode"])\n return manifest\n')
    release,candidate,directory,_=f.release();f.campaign(release)
    # 只在测试维护夹具中导入合成完整参考包。
    with f.store.db() as db:
        row=db.execute('SELECT * FROM ota_releases WHERE release_id=?',(release,)).fetchone();input_key=row['input_sha256'];data=__import__('manager.ota_store',fromlist=['strict_json']).strict_json(db.execute('SELECT data FROM ota_inputs WHERE input_sha256=?',(input_key,)).fetchone()[0].encode())
    data['trees'].update(reference=import_tree(f.store,directory),native={},radio={},suspend={});data['meta']['radio_binary']='fixture'
    raw=encode(data);new_key=f.store.put(raw,'release_input')
    with f.store.db(True) as db:
        db.execute('INSERT INTO ota_inputs VALUES(?,?)',(new_key,raw.decode()));db.execute('UPDATE ota_releases SET input_sha256=? WHERE release_id=?',(new_key,release))
    request=f.check();assert f.service.check('one',request)['retry_seconds']==60
    assert Worker(f.store).run_once()
    offer=f.service.check('one',request)
    assert offer['status']=='update'
    with f.store.db() as db:assert db.execute('SELECT candidate FROM ota_artifacts').fetchone()[0]==candidate

def test_exhausted_crashed_job_is_paused(f):
    release,_,_,_=f.release();campaign=f.campaign(release);f.service.check('one',f.check());worker=Worker(f.store);job=worker.claim()
    with f.store.db(True) as db:db.execute('UPDATE ota_jobs SET tries=3,lease_until=0')
    assert worker.claim() is None
    result=f.service.campaign(campaign)['campaign']
    assert result['state']=='PAUSED' and result['targets'][0]['state']=='FAILED'

def test_later_batch_timeout_starts_only_when_activated(f):
    release,_,_,_=f.release();campaign=f.campaign(release,['one','two'])
    f.now+=2*86400
    with f.store.db(True) as db:
        db.execute("UPDATE ota_targets SET state='SUCCEEDED',active=0,healthy_at=? WHERE campaign_id=? AND batch=0",(f.now-86400,campaign))
    f.service.expire()
    targets=f.service.campaign(campaign)['campaign']['targets']
    assert targets[1]['state']=='QUEUED'
    f.service.campaign_action('admin',identifier(),campaign,'advance',{'revision':2})
    current=f.service.campaign(campaign)['campaign']
    assert current['state']=='RUNNING' and current['batch']==1
    assert current['targets'][1]['state']=='QUEUED'
    f.now+=86401
    current=f.service.campaign(campaign)['campaign']
    assert current['state']=='PAUSED' and current['targets'][1]['state']=='UNKNOWN'


def test_resume_gives_current_batch_a_new_report_deadline(f):
    release,_,_,_=f.release();campaign=f.campaign(release);f.now+=86401
    current=f.service.campaign(campaign)['campaign'];assert current['state']=='PAUSED'
    f.service.campaign_action('admin',identifier(),campaign,'resume',{'revision':current['revision']})
    resumed=f.service.campaign(campaign)['campaign']
    assert resumed['state']=='RUNNING' and resumed['targets'][0]['state']=='QUEUED'
    f.now+=86401
    assert f.service.campaign(campaign)['campaign']['state']=='PAUSED'
