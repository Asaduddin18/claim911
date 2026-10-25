"""Rotate only a reviewed voice gateway URL and retain immutable run lineage."""
import argparse,copy,hashlib,json,sys
from pathlib import Path
from datetime import datetime,timezone
import httpx,psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordinator.agent_fingerprint import fingerprint,reviewed_config
from coordinator.gateway_preflight import check_gateway
from scripts.configure_sandbox_bolna import configure,_write_private


def rotated(agent,old,new):
 result=copy.deepcopy(agent)
 if result.get('webhook_url')!=old+'/voice/webhook':raise ValueError('Unexpected reviewed webhook route')
 result['webhook_url']=new+'/voice/webhook'
 for task in result['tasks']:
  for item in task['tools_config']['api_tools']['tools_params'].values():
   if not item['url'].startswith(old+'/voice/'):raise ValueError('Unexpected reviewed tool route')
   item['url']=new+item['url'][len(old):]
 return result


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ('runtime','run-id','gateway-url'):p.add_argument('--'+key,required=True)
 p.add_argument('--apply',action='store_true');args=p.parse_args();root=Path(args.runtime).resolve()
 path=root/'operational/coordinator.json';cfg=json.loads(path.read_text());sb=json.loads((root/'sandbox/coordinator.json').read_text());old_url=cfg['gateway_url'].rstrip('/');new=args.gateway_url.rstrip('/')
 if cfg['environment']!='operational' or sb['environment']!='sandbox':raise ValueError('Reviewed isolated profiles required')
 if not check_gateway(cfg|{'gateway_url':new},include_sandbox=True)['ready']:raise ValueError('Replacement scoped gateway failed preflight')
 with psycopg.connect(sb['dsn'],row_factory=dict_row) as db:
  run=db.execute('SELECT * FROM coordinator.sandbox_runs WHERE id=%s',(args.run_id,)).fetchone()
  if not run or run['state'] not in {'PAUSED','UNCERTAIN'} or run['lease_token']:raise ValueError('A stopped run is required')
 with httpx.Client(base_url='https://api.bolna.ai',timeout=25,follow_redirects=False,headers={'Authorization':'Bearer '+cfg['bolna_api_key']}) as client:
  r=client.get('/v2/agent/'+cfg['bolna_agent_id']);r.raise_for_status();old=r.json()
  if fingerprint(old)!=cfg['bolna_agent_config_sha256']:raise ValueError('Live assistant differs from the reviewed configuration')
  updated=rotated(old,old_url,new)
  if reviewed_config(rotated(updated,new,old_url))!=reviewed_config(old):raise ValueError('The change is not URL-only')
  behavior=hashlib.sha256(json.dumps(reviewed_config(rotated(old,old_url,'https://gateway.invalid')),sort_keys=True).encode()).hexdigest()
  evidence={'gateway_only':True,'old_fingerprint':fingerprint(old),'new_fingerprint':fingerprint(updated),'old_gateway':old_url,'new_gateway':new,'behavior_sha256':behavior,'model_voice_prompt_permissions_unchanged':True}
  if not args.apply:print(json.dumps(evidence));return
  _write_private(root/('bolna-before-gateway-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json'),old)
  payload={'agent_config':{k:updated[k] for k in ('agent_name','agent_type','tasks','agent_welcome_message','webhook_url','webhook_headers')},'agent_prompts':updated['agent_prompts'],'composition_by_language':updated['composition_by_language']}
  r=client.put('/v2/agent/'+cfg['bolna_agent_id'],json=payload);r.raise_for_status()
  r=client.get('/v2/agent/'+cfg['bolna_agent_id']);r.raise_for_status();saved=r.json()
  if fingerprint(saved)!=evidence['new_fingerprint']:raise ValueError('Provider readback differs from reviewed update')
  cfg.update(gateway_url=new,bolna_agent_config_sha256=fingerprint(saved));_write_private(path,cfg);_write_private(root/'operational/bolna-agent.json',saved);configure(root)
 with psycopg.connect(sb['dsn'],row_factory=dict_row) as db:
  current=db.execute('SELECT state,provider_configuration FROM coordinator.sandbox_runs WHERE id=%s FOR UPDATE',(args.run_id,)).fetchone()
  if current['state'] not in {'PAUSED','UNCERTAIN'} or current['provider_configuration'].get('assistant_config_sha256')!=evidence['old_fingerprint']:raise ValueError('Run changed during reviewed gateway rotation')
  db.execute('UPDATE coordinator.sandbox_runs SET provider_configuration=%s WHERE id=%s',(Jsonb({'transport':'BOLNA_WEBRTC','assistant_config_sha256':evidence['new_fingerprint']}),args.run_id))
  db.execute("INSERT INTO coordinator.sandbox_run_events(run_id,type,payload) VALUES(%s,'BOLNA_GATEWAY_ROTATION_REVIEWED',%s)",(args.run_id,Jsonb(evidence)))
 print(json.dumps(evidence|{'readback_verified':True,'provider_sessions_started':0}))


if __name__=='__main__':main()
