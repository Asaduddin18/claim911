import json,os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import pytest
from fastapi.testclient import TestClient
from experience.app import create_app
from sandbox.runs import event


def test_run_stream_resumes_cursor_and_omits_private_payload():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated runtime required')
 cfg=json.loads((Path(root)/'sandbox/coordinator.json').read_text())
 with TestClient(create_app(cfg)) as client:
  assert client.get('/v2/sandbox/runs/00000000-0000-0000-0000-000000000000/events').status_code==401
  client.post('/v2/sessions',json={'role':'sandbox','credential':cfg['operator_token']})
  run=client.post('/v2/sandbox/runs',json={}).json();path='/v2/sandbox/runs/'+run['id']+'/events'
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   cursor=conn.execute('SELECT max(sequence) AS sequence FROM coordinator.sandbox_run_events WHERE run_id=%s',(run['id'],)).fetchone()['sequence']
   event(conn,run['id'],'SAFE_STATUS_CHANGED',{'private':'must-not-reach-browser'})
  assert client.get(path,headers={'Last-Event-ID':'invalid'}).status_code==422
  response=client.get(path,headers={'Last-Event-ID':str(cursor)})
  assert response.status_code==200 and response.headers['content-type'].startswith('text/event-stream')
  assert 'SAFE_STATUS_CHANGED' in response.text and 'RUN_PREPARED' not in response.text
  assert 'must-not-reach-browser' not in response.text and 'event: run-update' in response.text
