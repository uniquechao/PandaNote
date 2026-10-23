import pytest
from manager.ota import OtaError
from manager.ota_store import identifier
from ota_fixtures import Fixture

@pytest.fixture
def flow(tmp_path):
    f=Fixture(tmp_path);release,candidate,directory,manifest=f.release();campaign=f.campaign(release);request=f.check();assert f.service.check('one',request)['retry_seconds']==60
    bundle=f.ready(request,candidate,directory);assert f.service.check('one',request)['status']=='update'
    return f,release,candidate,directory,manifest,campaign,request,bundle

def test_reports_idempotent_out_of_order_and_conflicting_terminal(flow):
    f,_,candidate,_,manifest,campaign,_,bundle=flow
    event=f.event(bundle,manifest);assert f.service.report('one',event)['ok'];assert f.service.report('one',event)['ok']
    late={**event,'event_id':identifier(),'state':'DOWNLOADING'};f.service.report('one',late)
    assert f.service.campaign(campaign)['campaign']['targets'][0]['phase']=='HEALTHY'
    view=f.service.device_view('one');assert view['observed']['state']=='HEALTHY'
    assert view['last_event']['event']['state']=='DOWNLOADING'
    with pytest.raises(OtaError) as raised:f.service.report('one',{**event,'state':'VERIFIED'})
    assert raised.value.code=='event_conflict'
    old=f.old;conflict={**event,'event_id':identifier(),'state':'ROLLED_BACK','error_code':'health_failed','active_native_sha256':old['native_sha256'],'boot_id':old['boot_id']};f.service.report('one',conflict)
    assert f.service.device_view('one')['alert']=='terminal_conflict'
    assert f.service.campaign(campaign)['campaign']['state']=='PAUSED'
    assert f.service.device_view('one')['confirmed']['package_sha256']==candidate

def test_two_round_complete_baselines_and_expired_historical_report(flow):
    f,_,candidate,directory,manifest,_,request,bundle=flow
    f.now+=3601
    with pytest.raises(OtaError) as e:f.service.check('one',request)
    assert e.value.code=='grant_expired'
    f.service.report('one',f.event(bundle,manifest))
    release2,candidate2,dir2,manifest2=f.release('newer',old_dir=directory);campaign2=f.campaign(release2)
    request2=f.check(package_sha=candidate,manifest=manifest);f.service.check('one',request2);bundle2=f.ready(request2,candidate2,dir2);assert f.service.check('one',request2)['status']=='update'
    event=f.event(bundle2,manifest2);event['sequence']=2;f.service.report('one',event)
    assert f.service.device_view('one')['confirmed']['package_sha256']==candidate2
    assert len(f.service.attempts('one')['attempts'])==2

def test_device_and_attempt_binding_wrong_health_identity(flow):
    f,_,_,_,manifest,_,_,bundle=flow
    event=f.event(bundle,manifest)
    with pytest.raises(OtaError) as e:f.service.report('two',event)
    assert e.value.code=='attempt_conflict'
    with pytest.raises(OtaError) as e:f.service.report('one',{**event,'active_native_sha256':'0'*64})
    assert e.value.code=='baseline_mismatch'
    f.service.report('one',{**event,'state':'DOWNLOADING'})
    with pytest.raises(OtaError) as e:f.service.report('one',{**event,'event_id':identifier(),'bundle_sha256':'f'*64})
    assert e.value.code=='attempt_conflict'

def test_cancel_preserves_issued_device_until_late_health(flow):
    f,release,_,_,manifest,campaign,_,bundle=flow
    f.service.campaign_action('admin',identifier(),campaign,'cancel',{'revision':2})
    assert f.service.device_view('one')['target']['active']==1
    with pytest.raises(OtaError):f.service.chunk('one',{'schema':1,'bundle_sha256':bundle,'index':0})
    f.service.report('one',f.event(bundle,manifest))
    assert f.service.campaign(campaign)['campaign']['state']=='CANCELLED'
    assert f.service.device_view('one')['target'] is None

def test_controlled_recovery_reconciles_without_erasing_evidence(flow):
    from manager.ota_publish import reconcile
    f,_,_,_,manifest,campaign,_,bundle=flow
    event=f.event(bundle,manifest,state='RECOVERY_REQUIRED');event['error_code']='recovery_required';f.service.report('one',event)
    target=f.service.device_view('one')['target'];assert target['active']==1
    reconcile(f.store,dict(device_id='one',target_id=target['target_id'],baseline=f.old_sha,recovery_verified=True,reason='测试夹具已核对完整旧包'))
    assert f.service.device_view('one')['alert'] is None and f.service.device_view('one')['target'] is None
    assert f.service.attempts('one')['attempts'][0]['state']=='RECOVERY_REQUIRED'
    assert len(f.service.attempts('one')['events'])==1

def test_illegal_error_state_combination_rejected(flow):
    f,_,_,_,manifest,_,_,bundle=flow;event=f.event(bundle,manifest,state='DOWNLOADING');event['error_code']='power_unsafe'
    with pytest.raises(OtaError) as e:f.service.report('one',event)
    assert e.value.code=='invalid_input'


def test_renewed_grant_retains_attempt_and_rejects_replacement(flow):
    f,_,candidate,_,manifest,_,request,bundle=flow
    offered=f.event(bundle,manifest,state='OFFERED');f.service.report('one',offered)
    f.now+=3601
    renewed=f.service.check('one',{**request,'request_nonce':identifier()*2})
    assert renewed['status']=='update'
    with pytest.raises(OtaError) as error:f.service.report('one',f.event(bundle,manifest))
    assert error.value.code=='attempt_conflict'
    healthy=f.event(bundle,manifest,attempt=offered['attempt_id']);f.service.report('one',healthy)
    f.service.report('one',{**offered,'event_id':identifier()})
    view=f.service.device_view('one');assert view['observed']['state']=='HEALTHY'
    assert view['confirmed']['package_sha256']==candidate
    assert len(f.service.attempts('one')['attempts'])==1


def test_historical_reports_do_not_replace_new_transaction(flow):
    f,_,candidate,directory,manifest,_,_,bundle=flow
    healthy=f.event(bundle,manifest);f.service.report('one',healthy)
    release2,candidate2,dir2,manifest2=f.release('newer',old_dir=directory);campaign=f.campaign(release2)
    request2=f.check(package_sha=candidate,manifest=manifest);f.service.check('one',request2);bundle2=f.ready(request2,candidate2,dir2);f.service.check('one',request2)
    downloading=f.event(bundle2,manifest2,state='DOWNLOADING');downloading['sequence']=2;f.service.report('one',downloading)
    f.service.report('one',{**healthy,'event_id':identifier(),'state':'OFFERED'})
    view=f.service.device_view('one');assert view['observed']['state']=='DOWNLOADING'
    assert view['confirmed']['package_sha256']==candidate
    assert f.service.campaign(campaign)['campaign']['targets'][0]['observed']['state']=='DOWNLOADING'


def test_campaign_progress_and_preparation_cancellation_reason(flow):
    f,_,_,_,manifest,campaign,_,bundle=flow
    event=f.event(bundle,manifest,state='WAITING_SAFE_WINDOW');f.service.report('one',event)
    f.service.report('one',{**event,'event_id':identifier(),'state':'OFFERED','error_code':'power_unsafe'})
    view=f.service.device_view('one');assert view['observed']['state']=='WAITING_SAFE_WINDOW'
    assert view['observed']['error_code']=='power_unsafe'
    target=f.service.campaign(campaign)['campaign']['targets'][0];assert target['observed']['error_code']=='power_unsafe'
    f.service.report('one',{**event,'event_id':identifier(),'state':'HEALTHY'})
    progress=f.service.campaign(campaign)['campaign']['progress'];assert not progress['can_advance']
    assert progress['ready_at']==f.now+86400
    f.now+=86400;assert f.service.campaign(campaign)['campaign']['progress']['can_advance']
