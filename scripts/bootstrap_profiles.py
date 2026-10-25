"""Create separate operational and sandbox databases, without touching legacy records."""
import argparse,base64,json,secrets,sys,re
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo,conninfo_to_dict
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
sys.path.insert(0,str(Path(__file__).parent))
from migrate_institution_keys import install


def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--admin-profile');p.add_argument('--suffix',default='');p.add_argument('--operational-port',type=int,default=8113);p.add_argument('--sandbox-port',type=int,default=8114);args=p.parse_args()
 if not all(1024<=port<=65535 for port in (args.operational_port,args.sandbox_port)) or args.operational_port==args.sandbox_port:raise ValueError('Distinct unprivileged institution ports required')
 if args.suffix and not re.fullmatch(r'[a-z0-9]{1,20}',args.suffix):raise ValueError('Lowercase alphanumeric setup suffix required')
 root=Path(args.runtime);legacy=json.loads(Path(args.admin_profile or root/'simulator.json').read_text());admin=legacy['admin_dsn']
 if args.suffix and conninfo_to_dict(admin).get('host') not in {'127.0.0.1','localhost','::1'}:raise ValueError('Namespaced rehearsal requires local PostgreSQL')
 suffix='_'+args.suffix if args.suffix else ''
 for profile,port in [('operational',args.operational_port),('sandbox',args.sandbox_port)]:
  folder=root/profile;name='claim911_'+profile+suffix;prefix='c911_'+profile+suffix
  if (folder/'coordinator.json').exists():
   existing=json.loads((folder/'coordinator.json').read_text())
   if conninfo_to_dict(existing['dsn']).get('dbname')!=name or existing.get('environment')!=profile:
    raise SystemExit('Existing profile does not match requested database namespace; choose a separate runtime directory.')
   print(profile+': existing private configuration retained');continue
  passwords={x:secrets.token_urlsafe(32) for x in ['hospital','claims','core']}
  with psycopg.connect(admin,autocommit=True) as conn:
   # Check every collision before creating anything. A partially recovered
   # setup must never silently rotate roles or add more orphan credentials.
   if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone():
    raise SystemExit('Profile database exists without configuration; recover explicitly.')
   for role in passwords:
    if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s',(prefix+'_'+role,)).fetchone():
     raise SystemExit('Profile role exists without configuration; recover explicitly, never rotate silently.')
   for role,password in passwords.items():
    conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(prefix+'_'+role),sql.Literal(password)))
   conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
   conn.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM PUBLIC').format(sql.Identifier(name)))
   for role in passwords:
    conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(name),sql.Identifier(prefix+'_'+role)))
  admin_profile=make_conninfo(admin,dbname=name)
  with psycopg.connect(admin_profile) as conn:
   schema=(Path(__file__).parents[1]/'simulator/schema.sql').read_text()
   for role in passwords:schema=schema.replace('claim911_'+role,prefix+'_'+role)
   conn.execute(schema)
  folder.mkdir(mode=0o700,parents=True,exist_ok=True)
  private=Ed25519PrivateKey.generate()
  private_bytes=private.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption())
  public_bytes=private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
  sim={'environment':profile,'admin_dsn':admin_profile,'hospital_dsn':make_conninfo(admin_profile,user=prefix+'_hospital',password=passwords['hospital']),
       'claims_dsn':make_conninfo(admin_profile,user=prefix+'_claims',password=passwords['claims']),
       'tokens':{x:secrets.token_urlsafe(32) for x in ['hospital','claims','insurer','agent','evaluator']},
       'signing_private_key':base64.b64encode(private_bytes).decode()}
  core={'dsn':make_conninfo(admin_profile,user=prefix+'_core',password=passwords['core']),
        'simulator_url':f'http://127.0.0.1:{port}','simulator_agent_token':sim['tokens']['agent'],
        'receipt_public_key':base64.b64encode(public_bytes).decode(),
        'operator_token':secrets.token_urlsafe(32),'webhook_token':secrets.token_urlsafe(32),'gateway_token':secrets.token_urlsafe(32),
        'environment':profile,'test_mode':profile=='sandbox','live_calls_enabled':False,'outbound_paused':True,
        'call_pause_reason':'Phone calls remain on hold during the product redesign.','bolna_api_key':None}
  if profile=='sandbox':
   sim['tokens']['sandbox_runner']=secrets.token_urlsafe(32)
   core['sandbox_seed_token']=sim['tokens']['sandbox_runner']
   core['sandbox_execution_enabled']=False
  for file,data in [('simulator.json',sim),('coordinator.json',core)]:
   f=folder/file;f.write_text(json.dumps(data,indent=2));f.chmod(0o600)
  install(folder)
  print(profile+': isolated database and private service configuration created')


if __name__=='__main__':main()
