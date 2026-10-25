"""Short-lived trusted worker presence, separate from successful-run evidence."""
from threading import Event,Thread
from uuid import uuid4
import psycopg


def available(conn):
 return bool(conn.execute('SELECT 1 FROM coordinator.sandbox_workers WHERE expires_at>now() LIMIT 1').fetchone())


class Heartbeat:
 def __init__(self,config):
  if config.get('environment')!='sandbox' or config.get('bolna_api_key') or config.get('live_calls_enabled'):
   raise PermissionError('Isolated non-phone worker required')
  self.dsn=config['dsn'];self.id=uuid4();self.stop=Event();self.thread=None

 def pulse(self):
  with psycopg.connect(self.dsn) as conn:
   conn.execute("INSERT INTO coordinator.sandbox_workers(id,expires_at) VALUES(%s,now()+interval '15 seconds') ON CONFLICT(id) DO UPDATE SET expires_at=excluded.expires_at",(self.id,))

 def start(self):
  self.pulse()
  def repeat():
   while not self.stop.wait(5):
    try:self.pulse()
    except Exception:pass # Readiness expires instead of claiming an unhealthy worker.
  self.thread=Thread(target=repeat,daemon=True);self.thread.start()

 def close(self):
  self.stop.set()
  if self.thread:self.thread.join(timeout=6)
  with psycopg.connect(self.dsn) as conn:conn.execute('DELETE FROM coordinator.sandbox_workers WHERE id=%s',(self.id,))
