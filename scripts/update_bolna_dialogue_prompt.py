"""Apply and verify the reviewed Claim911 caregiver dialogue prompt only."""
import argparse
import copy
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit,urlunsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordinator.agent_fingerprint import fingerprint, legacy_fingerprint, reviewed_config
from scripts.configure_bolna import PROMPT,tool_config
from scripts.configure_sandbox_bolna import _write_private


def prepare_dialogue_config(original):
    updated=copy.deepcopy(original)
    updated.setdefault('agent_prompts',{}).setdefault('task_1',{})['system_prompt']=PROMPT
    updated.setdefault('composition_by_language',{})['en']=[{'type':'text','text':PROMPT}]
    tools=updated['tasks'][0]['tools_config']['api_tools']
    matches=[tool for tool in tools['tools'] if tool['name']=='claim911_report_update']
    if len(matches)!=1:raise ValueError('One reviewed report-update tool is required')
    template=next(tool for tool in tool_config('https://synthetic.example.invalid','unused')['tools'] if tool['name']=='claim911_report_update')
    for key in ('dispatch_reference','callback_at'):
        matches[0]['parameters']['properties'][key]=template['parameters']['properties'][key]
        if key not in matches[0]['parameters']['required']:matches[0]['parameters']['required'].append(key)
    params=tools['tools_params']['claim911_report_update']
    body=json.loads(params['param'])
    body.update(dispatch_reference='%(dispatch_reference)s',callback_at='%(callback_at)s')
    params['param']=json.dumps(body)
    return updated


def prepare_gateway_config(original,base):
    target=urlsplit(base)
    if (target.scheme!='https' or not target.hostname or not target.hostname.endswith('.trycloudflare.com')
        or target.username or target.password or target.port not in (None,443)
        or target.path or target.query or target.fragment):
        raise ValueError('A dedicated temporary HTTPS gateway root is required')
    updated=copy.deepcopy(original)
    def replace(url):
        source=urlsplit(url)
        if source.scheme!='https' or not source.hostname or not source.hostname.endswith('.trycloudflare.com') or not source.path.startswith('/voice/'):
            raise ValueError('Refusing to rewrite a non-Claim911 endpoint')
        return urlunsplit((target.scheme,target.netloc,source.path,source.query,source.fragment))
    for task in updated['tasks']:
        for params in task['tools_config']['api_tools']['tools_params'].values():
            params['url']=replace(params['url'])
    updated['webhook_url']=replace(updated['webhook_url'])
    return updated


def prepare_efficient_model(original,model):
    if model not in {'azure/gpt-4.1-nano','azure/gpt-4.1-mini'}:
        raise ValueError('Only the reviewed small assistant models are allowed')
    updated=copy.deepcopy(original)
    for task in updated['tasks']:
        config=task['tools_config']['llm_agent']['llm_config']
        if config.get('provider')!='azure':raise ValueError('Existing Azure provider required')
        config['model']=model
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--scope',choices=['sandbox','all'],default='sandbox')
    parser.add_argument('--gateway-url')
    parser.add_argument('--assistant-model',choices=['azure/gpt-4.1-nano','azure/gpt-4.1-mini'])
    args = parser.parse_args()
    root = Path(args.runtime).resolve()
    operational_path = root / 'operational' / 'coordinator.json'
    broker_path = root / 'sandbox' / 'bolna-session-broker.json'
    operational = json.loads(operational_path.read_text())
    broker = json.loads(broker_path.read_text())
    agent_id = operational.get('bolna_agent_id')
    old_pin = broker.get('bolna_agent_config_sha256') if args.scope=='sandbox' else operational.get('bolna_agent_config_sha256')
    if (operational.get('environment') != 'operational' or not operational.get('browser_voice_enabled')
            or not agent_id or not operational.get('bolna_api_key') or not old_pin
            or broker.get('bolna_agent_id') != agent_id
            or broker.get('bolna_agent_config_sha256') != old_pin):
        raise SystemExit('The reviewed operational and sandbox Bolna profiles do not match.')

    with httpx.Client(base_url='https://api.bolna.ai', timeout=30, follow_redirects=False,
                      headers={'Authorization': 'Bearer ' + operational['bolna_api_key']}) as client:
        response = client.get('/v2/agent/' + agent_id)
        response.raise_for_status()
        original = response.json()
        if (original.get('id') != agent_id
                or original.get('agent_name') != 'Claim911 | Insurance Coordination Demo'
                or old_pin not in {fingerprint(original), legacy_fingerprint(original)}):
            raise SystemExit('The live assistant changed since review. Prompt update withheld.')
        updated = prepare_dialogue_config(original)
        if args.gateway_url:updated=prepare_gateway_config(updated,args.gateway_url.rstrip('/'))
        if args.assistant_model:updated=prepare_efficient_model(updated,args.assistant_model)
        new_pin = fingerprint(updated)
        if new_pin == old_pin:
            print('The reviewed caregiver dialogue prompt is already active.')
            return
        print('Prepared reviewed voice configuration. Model: '+(args.assistant_model or 'preserved')+'. Voice, output bound, permissions and transport are preserved.')
        if not args.apply:
            return

        backup = root / 'sandbox' / 'bolna-before-dialogue-prompt.json'
        if not backup.exists():
            _write_private(backup, original)
        response = client.put('/v2/agent/' + agent_id,
                              json={'agent_config': {
                                        'agent_name': updated['agent_name'],
                                        'agent_type': updated.get('agent_type'),
                                        'tasks': updated['tasks'],
                                        'agent_welcome_message': updated.get('agent_welcome_message'),
                                        'webhook_url': updated.get('webhook_url'),
                                        'webhook_headers': updated.get('webhook_headers', {}),
                                    },
                                    'agent_prompts': updated['agent_prompts'],
                                    'composition_by_language': updated['composition_by_language']})
        if not response.is_success:
            _write_private(root / 'sandbox' / 'bolna-dialogue-prompt-update-error.json',
                           {'status_code': response.status_code, 'body': response.text[:4000]})
            raise SystemExit('Bolna rejected the prompt update. The private response was preserved for review.')
        response = client.get('/v2/agent/' + agent_id)
        response.raise_for_status()
        saved = response.json()
        if reviewed_config(saved) != reviewed_config(updated):
            _write_private(root / 'sandbox' / 'bolna-dialogue-prompt-readback.json', saved)
            _write_private(root / 'sandbox' / 'bolna-dialogue-prompt-mismatch.json',
                           {'expected_fingerprint': new_pin,
                            'observed_fingerprint': fingerprint(saved)})
            raise SystemExit('Bolna saved a different configuration. New sessions must remain blocked.')

    pins=[(root/'sandbox'/'coordinator.json','sandbox_bolna_agent_config_sha256'),
          (broker_path,'bolna_agent_config_sha256')]
    if args.scope=='all':pins.append((operational_path,'bolna_agent_config_sha256'))
    if (root/'sandbox'/'product-profile.json').exists():pins.append((root/'sandbox'/'product-profile.json','sandbox_bolna_agent_config_sha256'))
    for path, key in pins:
        config = json.loads(path.read_text())
        config[key] = new_pin
        if args.gateway_url:config['gateway_url']=args.gateway_url.rstrip('/')
        _write_private(path, config)
    _write_private(root / 'sandbox' / 'bolna-agent-after-dialogue-prompt.json', saved)
    _write_private(root/'sandbox'/'bolna-agent.json',saved)
    print('The English prompt and locale composition were read back and fingerprinted. Restart the trusted services before another sandbox session.')


if __name__ == '__main__':
    main()
