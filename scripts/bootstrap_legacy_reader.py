import argparse,json,secrets
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
parser=argparse.ArgumentParser();parser.add_argument('--runtime',required=True);args=parser.parse_args()
p=Path(args.runtime);sim=json.loads((p/'simulator.json').read_text());op=json.loads((p/'operational/coordinator.json').read_text())
if 'legacy_read_dsn' not in op:
 password=secrets.token_urlsafe(32);role='c911_legacy_reader'
 with psycopg.connect(sim['admin_dsn'],autocommit=True) as conn:
  if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(role,)).fetchone():raise SystemExit('Recover existing reader credentials explicitly')
  conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(role),sql.Literal(password)))
  conn.execute(sql.SQL('GRANT USAGE ON SCHEMA coordinator TO {}').format(sql.Identifier(role)))
  conn.execute(sql.SQL('GRANT SELECT ON coordinator.incidents,coordinator.calls,coordinator.documents,coordinator.events TO {}').format(sql.Identifier(role)))
 op['legacy_read_dsn']=make_conninfo(sim['admin_dsn'],user=role,password=password)
 f=p/'operational/coordinator.json';f.write_text(json.dumps(op,indent=2));f.chmod(0o600)
 print('Legacy read-only credential installed; no institution access or write grants')
else:print('Existing legacy read-only credential retained')
