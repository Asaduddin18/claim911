"""Apply one reviewed conversational timing profile to the dedicated Bolna agent.

Only timing fields change. The existing assistant, prompt, voice, tools and
authentication are preserved. Private backups and fingerprints are updated only
after the provider confirms the exact resulting configuration.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordinator.agent_fingerprint import fingerprint,reviewed_config
from scripts.configure_sandbox_bolna import _write_private


def prior_fingerprint(agent):
    safe=reviewed_config(agent)
    for task in safe['tasks']:task.pop('timing',None)
    return hashlib.sha256(json.dumps(safe,sort_keys=True,separators=(',',':'),ensure_ascii=False,default=str).encode()).hexdigest()


def timing_profile(agent,*,simulation=False):
    if agent.get('agent_name')!='Claim911 | Insurance Coordination Demo' or len(agent.get('tasks') or [])!=1:
        raise ValueError('Only the dedicated single-task Claim911 assistant may be tuned')
    updated=copy.deepcopy(agent)
    task=updated['tasks'][0]
    if task['tools_config']['transcriber'].get('provider')!='deepgram':
        raise ValueError('This timing profile was reviewed only for the current Deepgram transcriber')
    task['tools_config']['transcriber']['endpointing']=600
    task['task_config'].update(incremental_delay=600,optimize_latency=False)
    if simulation:
        task['tools_config']['transcriber']['endpointing']=1200
        task['task_config'].update(incremental_delay=1200,trigger_user_online_message_after=45,
            hangup_after_silence=60,call_terminate=300)
    return updated


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',required=True);parser.add_argument('--apply',action='store_true')
    parser.add_argument('--simulation',action='store_true');parser.add_argument('--scope',choices=['sandbox','all'],default='sandbox')
    args=parser.parse_args();root=Path(args.runtime).resolve()
    broker_path=root/'sandbox/bolna-session-broker.json';broker=json.loads(broker_path.read_text())
    if broker.get('environment')!='sandbox_bolna_broker':raise ValueError('Trusted sandbox broker profile required')
    with httpx.Client(base_url='https://api.bolna.ai',headers={'Authorization':'Bearer '+broker['bolna_api_key']},timeout=30,follow_redirects=False) as client:
        response=client.get('/v2/agent/'+broker['bolna_agent_id']);response.raise_for_status();original=response.json()
        if original.get('id')!=broker['bolna_agent_id'] or broker['bolna_agent_config_sha256'] not in {fingerprint(original),prior_fingerprint(original)}:
            raise ValueError('Assistant changed since its reviewed configuration; tuning withheld')
        updated=timing_profile(original,simulation=args.simulation)
        print('Reviewed timing: '+('bounded synthetic-participant timing, with 45-second idle check and 60-second silence cap.' if args.simulation else '600 ms endpointing, 600 ms incremental delay.'))
        if not args.apply:return
        _write_private(root/'sandbox/bolna-before-turn-timing.json',original)
        payload={'agent_config':{key:updated[key] for key in ['agent_name','agent_type','agent_welcome_message','tasks','webhook_url','webhook_headers']},
                 'agent_prompts':updated['agent_prompts']}
        if 'composition_by_language' in updated:payload['composition_by_language']=updated['composition_by_language']
        response=client.put('/v2/agent/'+broker['bolna_agent_id'],json=payload)
        if not response.is_success:raise RuntimeError('Bolna rejected the timing change; no local fingerprint updated')
        response=client.get('/v2/agent/'+broker['bolna_agent_id']);response.raise_for_status();saved=response.json()
        if reviewed_config(saved)!=reviewed_config(updated):raise RuntimeError('Provider configuration differs from reviewed timing profile; sessions must remain blocked')
        pin=fingerprint(saved)
        pins=[(broker_path,'bolna_agent_config_sha256'),(root/'sandbox/coordinator.json','sandbox_bolna_agent_config_sha256')]
        if (root/'sandbox/product-profile.json').exists():pins.append((root/'sandbox/product-profile.json','sandbox_bolna_agent_config_sha256'))
        if args.scope=='all':pins.append((root/'operational/coordinator.json','bolna_agent_config_sha256'))
        for path,key in pins:
            config=json.loads(path.read_text());config[key]=pin;_write_private(path,config)
        _write_private(root/'sandbox/bolna-after-turn-timing.json',saved)
        _write_private(root/'sandbox/bolna-agent.json',saved)
        print('Provider timing verified; assistant, voice, prompt and tool routes preserved. Restart trusted services to load the reviewed fingerprint.')


if __name__=='__main__':main()
