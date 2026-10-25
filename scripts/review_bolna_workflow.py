"""Apply the shared voice prompt only against a known reviewed Bolna agent.

Preserves model, voice, tools, URLs and permissions. Saves an immutable backup,
reads back the provider result, then synchronizes the existing sandbox broker.
"""
import argparse,copy,json,sys
from datetime import datetime,timezone
from pathlib import Path
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordinator.agent_fingerprint import fingerprint
from coordinator.voice_prompt import PROMPT
from coordinator.gateway_preflight import check_gateway
from scripts.configure_sandbox_bolna import configure,_write_private


def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
 root=Path(args.runtime).resolve();path=root/'operational/coordinator.json';cfg=json.loads(path.read_text())
 if cfg['environment']!='operational':raise ValueError('Reviewed account profile required')
 ready=check_gateway(cfg)
 if not ready['ready']:raise RuntimeError('The reviewed gateway is unavailable; no remote configuration changed')
 with httpx.Client(base_url='https://api.bolna.ai',timeout=25,follow_redirects=False,
                   headers={'Authorization':'Bearer '+cfg['bolna_api_key']}) as client:
  response=client.get('/v2/agent/'+cfg['bolna_agent_id']);response.raise_for_status();old=response.json()
  if fingerprint(old)!=cfg['bolna_agent_config_sha256']:
   raise RuntimeError('Live agent changed outside the reviewed configuration')
  changed=copy.deepcopy(old)
  changed['agent_prompts']['task_1']['system_prompt']=PROMPT
  changed['composition_by_language']['en']=[{'type':'text','text':PROMPT}]
  if not args.apply:
   print(json.dumps({'prepared':True,'changes':['shared_prompt'],'provider_sessions_started':0}));return
  backup=root/'operational'/('bolna-before-workflow-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
  if backup.exists():raise RuntimeError('Preserve the existing configuration backup')
  _write_private(backup,old)
  payload={'agent_config':{k:changed[k] for k in ('agent_name','agent_type','tasks','agent_welcome_message','webhook_url','webhook_headers')},
           'agent_prompts':changed['agent_prompts'],'composition_by_language':changed['composition_by_language']}
  response=client.put('/v2/agent/'+cfg['bolna_agent_id'],json=payload);response.raise_for_status()
  response=client.get('/v2/agent/'+cfg['bolna_agent_id']);response.raise_for_status();saved=response.json()
  if fingerprint(saved)!=fingerprint(changed):raise RuntimeError('Remote readback differs; no local fingerprint adopted')
  _write_private(root/'operational/bolna-agent.json',saved)
  cfg['bolna_agent_config_sha256']=fingerprint(saved);_write_private(path,cfg)
 configure(root)
 print(json.dumps({'verified':True,'changes':['shared_prompt'],'assistant_config_sha256':fingerprint(saved),
                   'sandbox_profiles_synchronized':True,'provider_sessions_started':0}))


if __name__=='__main__':main()
