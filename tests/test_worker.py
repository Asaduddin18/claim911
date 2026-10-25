import json
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
import pytest

from coordinator.bolna import DispatchUnknown
from coordinator.worker import work_once,process_webhook_once,poll_once,stop_once,_phase_failure_diagnostic
from tests.test_environment import seed
from tests.test_coordinator import core_config, core, create, consent


def queued(core,env,cfg):
    id=create(core,seed(env,cfg));consent(core,id)
    p=core.post(f'/v1/incidents/{id}/participants',json={'role':'hospital','phone':'+919999999999',
        'verified':True,'demo_consent':'Synthetic fixture only; no real phone contact.'})
    assert p.status_code==201,p.text
    key=str(uuid4());body={'participant_id':p.json()['participant_id'],'purpose':'HOSPITAL_INITIAL'}
    j=core.post(f'/v1/incidents/{id}/call-jobs',json=body,headers={'Idempotency-Key':key})
    assert j.status_code==201,j.text
    replay=core.post(f'/v1/incidents/{id}/call-jobs',json=body,headers={'Idempotency-Key':key})
    assert replay.json()==j.json()
    return id,j.json()


def enabled(config):
    return config|{'live_calls_enabled':True,'bolna_api_key':'mock-only','bolna_agent_id':str(uuid4())}


def test_sandbox_phase_failure_keeps_only_allowlisted_diagnostics():
    stdout='debug private text\n'+json.dumps({'state':'REVIEW_REQUIRED','error_type':'AudioExecutionError',
        'boundary':{'operation':'transcribe','status':403,'failure':'secret-response-body'},
        'failure_location':{'file':'worker.py','function':'execute_phase','line':301,'path':'/private/key'}})
    result=_phase_failure_diagnostic(stdout,'',1)
    assert result=={'exit_code':1,'error_type':'AudioExecutionError',
                    'boundary':{'operation':'transcribe','status':403},
                    'failure_location':{'file':'worker.py','function':'execute_phase','line':301}}


class FakeProvider:
    def __init__(self,uncertain=False):
        self.count=0;self.uncertain=uncertain;self.execution_id=str(uuid4())
    def call(self,*args):
        self.count+=1
        if self.uncertain:
            raise DispatchUnknown('Synthetic lost response')
        return self.execution_id


def call_state(core,id):
    return core.get(f'/v1/incidents/{id}').json()['calls'][-1]


def test_worker_dispatch_persisted_and_not_repeated(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);p=FakeProvider()
    assert work_once(enabled(core_config),p,job['job_id'])
    assert call_state(core,id)['execution_id']==p.execution_id
    assert not work_once(enabled(core_config),p,job['job_id'])
    assert p.count==1


def test_uncertain_dispatch_blocks_further_calls(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);p=FakeProvider(True)
    work_once(enabled(core_config),p,job['job_id'])
    assert call_state(core,id)['state']=='DISPATCH_UNKNOWN'
    work_once(enabled(core_config),p,job['job_id'])
    assert p.count==1
    with psycopg.connect(core_config['dsn'],row_factory=dict_row) as conn:
        pid=conn.execute('SELECT participant_id FROM coordinator.calls WHERE id=%s',(job['call_id'],)).fetchone()['participant_id']
    r=core.post(f'/v1/incidents/{id}/call-jobs',json={'participant_id':str(pid),'purpose':'HOSPITAL_INITIAL'},
               headers={'Idempotency-Key':str(uuid4())})
    assert r.status_code==409


def test_revocation_before_dispatch_cancels_without_provider(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);consent(core,id,False);p=FakeProvider()
    assert call_state(core,id)['state']=='CANCELLED'
    work_once(enabled(core_config),p,job['job_id'])
    assert p.count==0
    consent(core,id,True)
    with psycopg.connect(core_config['dsn'],row_factory=dict_row) as conn:
        pid=conn.execute('SELECT participant_id FROM coordinator.calls WHERE id=%s',(job['call_id'],)).fetchone()['participant_id']
    retry=core.post(f'/v1/incidents/{id}/call-jobs',json={'participant_id':str(pid),'purpose':'HOSPITAL_INITIAL'},
                    headers={'Idempotency-Key':str(uuid4())})
    assert retry.status_code==201,retry.text


def test_disabled_live_calls_never_contact_provider(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);p=FakeProvider()
    work_once(core_config,p,job['job_id'])
    assert p.count==0 and call_state(core,id)['state']=='CANCELLED'


def test_webhooks_deduplicate_and_do_not_regress_terminal(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);p=FakeProvider();work_once(enabled(core_config),p,job['job_id'])
    headers={'X-Webhook-Token':core_config['webhook_token']}
    completed={'id':p.execution_id,'status':'completed','transcript':'participant: Request sent.',
               'recording_url':'https://example.invalid/not-used.wav'}
    assert core.post('/v1/webhooks/bolna',json=completed,headers=headers).status_code==202
    assert core.post('/v1/webhooks/bolna',json=completed,headers=headers).status_code==202
    assert process_webhook_once(core_config,execution_id=p.execution_id)
    row=call_state(core,id)
    assert row['state']=='COMPLETED' and row['transcript']
    assert row['recording_url'] is None
    assert 'tool_token_hash' not in row
    core.post('/v1/webhooks/bolna',json={'id':p.execution_id,'status':'ringing'},headers=headers)
    process_webhook_once(core_config,execution_id=p.execution_id)
    assert call_state(core,id)['state']=='COMPLETED'
    events=core.get(f'/v1/incidents/{id}').json()['events']
    assert len([e for e in events if e['type']=='CALL_STATUS_UPDATED'])==2


def test_expired_dispatch_lease_becomes_unknown(core,env,cfg,core_config):
    id,job=queued(core,env,cfg)
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("UPDATE coordinator.jobs SET state='DISPATCHING',lease_until=now()-interval '1 second' WHERE id=%s",(job['job_id'],))
        conn.execute("UPDATE coordinator.calls SET state='DISPATCHING' WHERE id=%s",(job['call_id'],))
    p=FakeProvider();work_once(enabled(core_config),p,job['job_id'])
    assert p.count==0 and call_state(core,id)['state']=='DISPATCH_UNKNOWN'


def test_call_token_is_scoped_and_revoked(core,env,cfg,core_config):
    id,job=queued(core,env,cfg)
    with psycopg.connect(core_config['dsn'],row_factory=dict_row) as conn:
        token=conn.execute('SELECT payload FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()['payload']['user_data']['call_token']
    assert core.get('/v1/tools/context',headers={'X-Call-Token':token}).status_code==403
    work_once(enabled(core_config),FakeProvider(),job['job_id'])
    context=core.get('/v1/tools/context',headers={'X-Call-Token':token})
    assert context.status_code==200 and context.json()['incident_id']==id
    # A hospital call cannot impersonate a claims-desk report.
    body={'predicate':'NOT_RECEIVED','value':{'found':False},'reference':'HOSP-FINAL-1042','request_type':'FINAL_AUTHORIZATION'}
    assert core.post('/v1/tools/statements',json=body,headers={'X-Call-Token':token}).status_code==403
    consent(core,id,False)
    assert core.get('/v1/tools/context',headers={'X-Call-Token':token}).status_code==403


def test_webhook_requires_auth(core):
    assert core.post('/v1/webhooks/bolna',json={'id':str(uuid4()),'status':'completed'}).status_code==403


def test_poll_reconciles_a_missing_webhook(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);p=FakeProvider();work_once(enabled(core_config),p,job['job_id'])
    p.execution=lambda execution_id:{'id':execution_id,'status':'completed','transcript':'participant: Synthetic test response.'}
    assert poll_once(enabled(core_config),p,job['call_id'])
    assert process_webhook_once(core_config,execution_id=p.execution_id)
    assert call_state(core,id)['state']=='COMPLETED'


def test_poll_rejects_other_execution(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);p=FakeProvider();work_once(enabled(core_config),p,job['job_id'])
    p.execution=lambda execution_id:{'id':str(uuid4()),'status':'completed','transcript':'Wrong call'}
    assert poll_once(enabled(core_config),p,job['call_id'])
    row=call_state(core,id)
    assert row['state']=='QUEUED' and row['poll_failures']==1


def test_uncertain_execution_recovery_requires_provider_call_binding(core,env,cfg,core_config,monkeypatch):
    id,job=queued(core,env,cfg);provider=FakeProvider(True)
    work_once(enabled(core_config),provider,job['job_id'])
    with psycopg.connect(core_config['dsn'],row_factory=dict_row) as conn:
        token=conn.execute('SELECT payload FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()['payload']['user_data']['call_token']
    execution_id=str(uuid4())
    payload={'id':execution_id,'status':'completed','transcript':'Synthetic recovered call','context_details':{'recipient_data':{'call_token':'wrong'}}}
    monkeypatch.setattr('coordinator.app.Bolna.execution',lambda self,execution:payload.copy())
    url=f'/v1/incidents/{id}/calls/{job["call_id"]}/reconcile'
    assert core.post(url,json={'execution_id':execution_id}).status_code==422
    assert call_state(core,id)['state']=='DISPATCH_UNKNOWN'
    payload['context_details']['recipient_data']['call_token']=token
    result=core.post(url,json={'execution_id':execution_id})
    assert result.status_code==200,result.text
    assert core.post(url,json={'execution_id':execution_id}).json()==result.json()
    assert provider.count==1
    assert process_webhook_once(core_config,execution_id=execution_id)
    assert call_state(core,id)['state']=='COMPLETED'
    assert call_state(core,id)['execution_id']==execution_id
    assert not work_once(enabled(core_config),provider,job['job_id'])
    assert provider.count==1
    detail=core.get(f'/v1/incidents/{id}').json()
    assert len([e for e in detail['events'] if e['type']=='CALL_EXECUTION_RECONCILED'])==1


@pytest.mark.parametrize('confirmed',[True,False])
def test_revocation_stops_provider_call_only_when_confirmed(core,env,cfg,core_config,confirmed):
    id,job=queued(core,env,cfg);p=FakeProvider()
    work_once(enabled(core_config),p,job['job_id'])
    consent(core,id,False)
    assert call_state(core,id)['state']=='QUEUED'
    attempts=[]
    def stop(execution):
        attempts.append(execution)
        if not confirmed:
            raise RuntimeError('Provider cannot stop an in-progress call')
        return {'execution_id':execution,'status':'stopped'}
    p.stop=stop
    # Outbound worker cannot accidentally dial a stop job.
    with psycopg.connect(core_config['dsn']) as conn:
        stop_job=conn.execute("SELECT id FROM coordinator.jobs WHERE kind='STOP_CALL' AND payload->>'call_id'=%s",(job['call_id'],)).fetchone()[0]
    assert not work_once(enabled(core_config),p,stop_job)
    assert stop_once(enabled(core_config),p,job['call_id'])
    assert attempts==[p.execution_id] and p.count==1
    assert call_state(core,id)['state']==('CANCELLED' if confirmed else 'QUEUED')
    events=core.get(f'/v1/incidents/{id}').json()['events']
    assert events[-1]['type']==('CALL_STOP_CONFIRMED' if confirmed else 'CALL_STOP_UNCONFIRMED')


def test_revocation_during_dispatch_enqueues_stop_after_identity_saved(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);p=FakeProvider()
    original=p.call
    def revoked_call(*args):
        consent(core,id,False)
        return original(*args)
    p.call=revoked_call
    work_once(enabled(core_config),p,job['job_id'])
    p.stop=lambda execution:{'execution_id':execution,'status':'stopped'}
    assert stop_once(enabled(core_config),p,job['call_id'])
    assert call_state(core,id)['state']=='CANCELLED'
    assert p.count==1


def test_observation_worker_never_enters_outbound_dispatch(monkeypatch):
    from coordinator import worker
    seen=[]
    for operation in ['stop_once','process_webhook_once','poll_once','work_once']:
        monkeypatch.setattr(worker,operation,lambda config,op=operation:seen.append(op) or False)
    worker.tick({},observe_only=True)
    assert seen==['stop_once','process_webhook_once','poll_once']
    seen.clear()
    worker.tick({},observe_only=False)
    assert seen==['stop_once','process_webhook_once','poll_once','work_once']


def test_active_correction_tools_stop_when_reference_changes(core,env,cfg,core_config):
    from tests.test_coordinator import evidence,action,authorize
    case=seed(env,cfg);id=create(core,case);consent(core,id)
    aid=action(core,id,evidence(core,env,cfg,id,case));assert authorize(core,id,aid).status_code==200
    participant=core.post(f'/v1/incidents/{id}/participants',json={'role':'hospital','phone':'+919999999999',
        'verified':True,'demo_consent':'Synthetic fixture only, no real phone contact.'}).json()['participant_id']
    job=core.post(f'/v1/incidents/{id}/call-jobs',json={'participant_id':participant,'purpose':'CORRECTION_REQUEST','action_id':aid},
        headers={'Idempotency-Key':str(uuid4())}).json()
    work_once(enabled(core_config),FakeProvider(),job['job_id'])
    with psycopg.connect(core_config['dsn'],row_factory=dict_row) as conn:
        token=conn.execute('SELECT payload FROM coordinator.jobs WHERE id=%s',(job['job_id'],)).fetchone()['payload']['user_data']['call_token']
    headers={'X-Call-Token':token}
    assert core.get('/v1/tools/context',headers=headers).status_code==200
    result=core.post('/v1/tools/statements',headers=headers,json={'predicate':'REFERENCE_CORRECTION',
        'reference':'HOSP-FINAL-1042','request_type':'FINAL_AUTHORIZATION','value':{'corrected_reference':'HOSP-FINAL-1043'}})
    assert result.status_code==201,result.text
    assert core.get('/v1/tools/context',headers=headers).status_code==403
    assert core.get(f'/v1/incidents/{id}').json()['actions'][0]['state']=='STALE'


def test_persistent_call_hold_blocks_queue_and_worker(core,env,cfg,core_config):
    from fastapi.testclient import TestClient
    from coordinator.app import create_app
    id,job=queued(core,env,cfg);p=FakeProvider()
    paused=enabled(core_config)|{'environment':'operational','outbound_paused':True,'call_pause_reason':'Waiting for participant readiness.'}
    assert not work_once(paused,p,job['job_id'])
    assert p.count==0 and call_state(core,id)['state']=='SCHEDULED'
    with TestClient(create_app(paused)) as held:
        held.headers['Authorization']='Bearer '+paused['operator_token']
        status=held.get('/v1/calling-status').json()
        assert status=={'configured':True,'paused':True,'can_queue_calls':False,'reason':'Waiting for participant readiness.'}
        participants=held.get(f'/v1/incidents/{id}/participants').json()
        response=held.post(f'/v1/incidents/{id}/call-jobs',json={'participant_id':participants[0]['id'],'purpose':'HOSPITAL_INITIAL'},
            headers={'Idempotency-Key':str(uuid4())})
        assert response.status_code==409
    # Existing scheduled job remains intact and can run only after explicit unpause.
    assert work_once(enabled(core_config),p,job['job_id'])
    assert p.count==1


def test_nested_provider_recording_import_requires_consent(core,env,cfg,core_config):
    id,job=queued(core,env,cfg);p=FakeProvider();work_once(enabled(core_config),p,job['job_id'])
    payload={'id':p.execution_id,'status':'completed','transcript':'Synthetic fixture','telephony_data':{'recording_url':'https://example.invalid/fixture.wav'}}
    core.post('/v1/webhooks/bolna',headers={'X-Webhook-Token':core_config['webhook_token']},json=payload)
    assert process_webhook_once(core_config,execution_id=p.execution_id)
    assert call_state(core,id)['recording_url'] is None
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute('UPDATE coordinator.calls SET recording_consent=true WHERE id=%s',(job['call_id'],))
    payload['summary']='New fixture event after explicit recording consent'
    core.post('/v1/webhooks/bolna',headers={'X-Webhook-Token':core_config['webhook_token']},json=payload)
    assert process_webhook_once(core_config,execution_id=p.execution_id)
    assert call_state(core,id)['recording_url']=='https://example.invalid/fixture.wav'


def test_dead_public_gateway_cancels_before_provider_dispatch(core,env,cfg,core_config,monkeypatch):
    id,job=queued(core,env,cfg)
    with psycopg.connect(core_config['dsn']) as conn:
        conn.execute("UPDATE coordinator.calls SET mode='BOLNA' WHERE id=%s",(job['call_id'],))
    monkeypatch.setattr('coordinator.gateway_preflight.check_gateway',lambda config:
        {'ready':False,'reason':'Public voice gateway unreachable; restore the tunnel before calling'})
    def forbidden_provider(*args,**kwargs):
        raise AssertionError('Provider must not be instantiated when its gateway is unreachable')
    monkeypatch.setattr('coordinator.worker.Bolna',forbidden_provider)
    assert work_once(enabled(core_config),job_id=job['job_id'])
    detail=core.get(f'/v1/incidents/{id}').json()
    call=next(c for c in detail['calls'] if c['id']==job['call_id'])
    assert call['state']=='CANCELLED' and call['execution_id'] is None
    event=next(e for e in detail['events'] if e['type']=='CALL_CANCELLED_BEFORE_DISPATCH')
    assert 'gateway unreachable' in event['payload']['reason']
