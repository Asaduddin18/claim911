import json,os
from datetime import datetime,timezone,timedelta
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from coordinator.app import create_app
from coordinator.reasoning import propose
from coordinator.callbacks import schedule,claim,finish,reconcile


@pytest.fixture
def callback_case():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated sandbox profile required')
 cfg=json.loads((Path(root)/'sandbox/coordinator.json').read_text())|{'test_mode':True}
 with TestClient(create_app(cfg)) as client:
  client.headers['Authorization']='Bearer '+cfg['operator_token']
  id=client.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':str(uuid4()),'patient_id':'SYNTHETIC-CALLBACK','reference_known':False,'title':'[Integration test] Callback recovery'}).json()['incident_id']
  assert client.post('/v1/incidents/'+id+'/consent',json={'accepted':True,'confirmation':'Synthetic callback investigation permission.'}).status_code==200
  yield cfg,client,id


def snapshot(client,id):return client.get('/v1/incidents/'+id).json()


def test_duplicate_schedule_restart_and_two_attempt_limit(callback_case):
 cfg,client,id=callback_case;now=datetime.now(timezone.utc)
 s=snapshot(client,id);p=propose(s)[0]
 # Store on one connection, recover on new connections as after worker restart.
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  task=schedule(conn,s,p,now)
  again=schedule(conn,s,p,now+timedelta(hours=1))
  assert task['id']==again['id'] and again['available_at']==now
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  first=claim(conn,s,now)
  assert first['attempts']==1 and claim(conn,s,now) is None
  failed=finish(conn,first['id'],first['lease_token'],'failed','Desk unavailable',next_at=now+timedelta(seconds=10),now=now)
  assert failed['state']=='WAITING'
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  assert claim(conn,s,now+timedelta(seconds=9)) is None
  second=claim(conn,s,now+timedelta(seconds=10));assert second['attempts']==2
  result=finish(conn,second['id'],second['lease_token'],'failed','Still unavailable',now=now+timedelta(seconds=10))
  assert result['state']=='ESCALATED'
  assert claim(conn,s,now+timedelta(days=1)) is None


def test_lost_lease_requires_reconciliation_and_cannot_claim_verified_outcome(callback_case):
 cfg,client,id=callback_case;now=datetime.now(timezone.utc);s=snapshot(client,id)
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  schedule(conn,s,propose(s)[0],now);first=claim(conn,s,now)
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  assert claim(conn,s,now+timedelta(minutes=3)) is None
  current=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE id=%s',(first['id'],)).fetchone()
  assert current['state']=='UNCERTAIN' and current['attempts']==1
  with pytest.raises(HTTPException):finish(conn,first['id'],first['lease_token'],'reported','Late worker',now=now+timedelta(minutes=3))
  reconcile(conn,first['id'],'CONFIRMED_NO_EXECUTION',now=now+timedelta(minutes=3))
  second=claim(conn,s,now+timedelta(minutes=3));assert second['attempts']==2
  with pytest.raises(HTTPException):finish(conn,second['id'],second['lease_token'],'verified','Do not trust a runner verdict')
  finish(conn,second['id'],second['lease_token'],'reported','Spoken report only',now=now+timedelta(minutes=3))
 assert snapshot(client,id)['incident']['state']=='INVESTIGATING'


def test_original_clock_preserved_and_consent_revocation_cancels(callback_case):
 cfg,client,id=callback_case;now=datetime.now(timezone.utc);s=snapshot(client,id)
 s['complex_workflow']={'tasks':[{'kind':'itemized_bill','owner':'billing','state':'NEEDED'}],
  'query':{'received_at':(now-timedelta(hours=2)).isoformat(),'target_at':(now+timedelta(minutes=1)).isoformat()}}
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  task=schedule(conn,s,propose(s)[0],now)
  first=claim(conn,s,now)
  failed=finish(conn,first['id'],first['lease_token'],'failed','Awaiting corrected bill',next_at=now+timedelta(minutes=2),now=now)
  assert failed['original_received_at']==task['original_received_at']
  assert claim(conn,s,now+timedelta(minutes=2)) is None
  assert conn.execute('SELECT state FROM coordinator.workflow_callbacks WHERE id=%s',(task['id'],)).fetchone()['state']=='ESCALATED'
 # Separate task for revocation, including a leased worker.
 s=snapshot(client,id)
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  task=schedule(conn,s,propose(s)[0],now);leased=claim(conn,s,now)
 assert leased
 client.post('/v1/incidents/'+id+'/consent',json={'accepted':False,'confirmation':'Caregiver withdrew synthetic investigation permission.'})
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  row=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE id=%s',(task['id'],)).fetchone()
  assert row['state']=='CANCELLED' and row['lease_token'] is None
  assert claim(conn,snapshot(client,id),now) is None


def test_waiting_cancellation_is_case_bound_idempotent_and_prevents_claim(callback_case):
 from coordinator.callbacks import cancel_waiting
 cfg,client,id=callback_case;now=datetime.now(timezone.utc);s=snapshot(client,id)
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  task=schedule(conn,s,propose(s)[0],now)
  with pytest.raises(HTTPException) as error:cancel_waiting(conn,uuid4(),task['id'])
  assert error.value.status_code==404
  result=cancel_waiting(conn,id,task['id'])
  assert result['state']=='CANCELLED' and result['attempts']==0
  assert cancel_waiting(conn,id,task['id'])['state']=='CANCELLED'
  assert claim(conn,s,now) is None
  events=conn.execute("SELECT * FROM coordinator.events WHERE incident_id=%s AND type='FOLLOWUP_CANCELLED'",(id,)).fetchall()
  assert len(events)==1


def test_active_callback_cancellation_cannot_claim_the_transport_was_stopped(callback_case):
 from coordinator.callbacks import cancel_waiting
 cfg,client,id=callback_case;now=datetime.now(timezone.utc);s=snapshot(client,id)
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
  task=schedule(conn,s,propose(s)[0],now);leased=claim(conn,s,now)
  with pytest.raises(HTTPException) as error:cancel_waiting(conn,id,task['id'])
  assert error.value.status_code==409
  current=conn.execute('SELECT * FROM coordinator.workflow_callbacks WHERE id=%s',(task['id'],)).fetchone()
  assert current['state']=='RUNNING' and current['lease_token']==leased['lease_token']
