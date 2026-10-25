import json,os
from pathlib import Path
import psycopg
from psycopg.rows import dict_row
import pytest
from sandbox.readiness import Heartbeat,available
from sandbox.runs import initialize


def test_worker_presence_expires_and_cannot_use_phone_profile():
 root=os.environ.get('CLAIM911_PROFILE_ROOT')
 if not root:pytest.skip('Isolated runtime required')
 cfg=json.loads((Path(root)/'sandbox/coordinator.json').read_text());pulse=Heartbeat(cfg)
 with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:initialize(conn,environment='sandbox')
 pulse.start()
 try:
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   assert available(conn)
   conn.execute("UPDATE coordinator.sandbox_workers SET expires_at=now()-interval '1 second' WHERE id=%s",(pulse.id,))
  with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
   assert not conn.execute('SELECT 1 FROM coordinator.sandbox_workers WHERE id=%s AND expires_at>now()',(pulse.id,)).fetchone()
 finally:pulse.close()
 with pytest.raises(PermissionError):Heartbeat({**cfg,'live_calls_enabled':True})
