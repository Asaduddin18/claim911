"""Configure only the dedicated Claim911 agent; secrets remain in private runtime files."""
import argparse
import copy
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from coordinator.voice_contracts import append_common_closing


from coordinator.voice_prompt import PROMPT

def tool_config(base,token):
    definitions=[];params={}
    for name,path,description,props in [
        ('claim911_context','/voice/context','Fetch the current server-owned incident and call scope at the start and after any reference correction.',{}),
        ('claim911_record_statement','/voice/statement','Record a material statement confirmed by this participant. Never invent facts. Record a spoken correction before proceeding.',{
            'request_type':{'type':'string','enum':['PREAUTHORIZATION','FINAL_AUTHORIZATION'],'description':'Request actually discussed and confirmed by the participant. Initial approval is PREAUTHORIZATION, never FINAL_AUTHORIZATION.'},
            'predicate':{'type':'string','enum':['SUBMITTED','SUBMISSION_UNKNOWN','NOT_RECEIVED','DESTINATION','RECEIVED','REFERENCE_CORRECTION','ACCESS_REFUSED']},
            'reference':{'type':'string','description':'Exact reference confirmed by the participant for this request type. Do not substitute the current case reference for a different spoken reference.'},
            'fact_value':{'type':'string','description':'Confirmed destination, corrected reference, lookup scope, or concise submitted/received explanation.'}}),
        ('claim911_report_references','/voice/references','Record distinct initial, enhancement and final request references only after hospital staff confirm the readback. Submission is reported only, never verified receipt.',{
            'admission_id':{'type':'string'},'initial_reference':{'type':'string'},'enhancement_reference':{'type':'string'},'final_reference':{'type':'string'},
            'submission_status':{'type':'string','enum':['REPORTED_SUBMITTED','UNKNOWN']},'summary':{'type':'string'}}),
        ('claim911_report_query','/voice/query','Record a confirmed outstanding information request from the scoped claims discovery call. Obtain all fields from staff and read back before saving.',{
            'query_reference':{'type':'string'},'claim_reference':{'type':'string'},'admission_id':{'type':'string'},
            'enhancement_reference':{'type':'string'},'received_at':{'type':'string','description':'Confirmed original discharge-request receipt timestamp as ISO 8601 with timezone, e.g. 2026-10-23T10:20:00+05:30. Never infer time from the clock.'},
            'required_documents':{'type':'string','enum':['itemized_bill,signed_discharge_summary,implant_invoice'],'description':'Use only when staff explicitly confirm all three documents are required; otherwise ask for human review.'},
            'enhancement_linked':{'type':'string','enum':['true','false']}}),
        ('claim911_report_document','/voice/document',"Record this hospital desk's confirmed document availability. Cannot collect a document without matching uploaded proof.",{
            'document_kind':{'type':'string','enum':['itemized_bill','signed_discharge_summary','implant_invoice']},
            'document_reference':{'type':'string','description':'Exact identifier confirmed by staff. Preserve hyphens. Never append a version or suffix; put version information in summary.'},'ready':{'type':'string','enum':['true','false']},'summary':{'type':'string'}}),
        ('claim911_report_update','/voice/update','Record a concise confirmed desk update, blocker, dispatch identifier or agreed callback time. Does not verify any outcome.',{
            'summary':{'type':'string'},
            'dispatch_reference':{'type':'string','description':'Exact hospital dispatch identifier explicitly confirmed by staff. Use an empty string if none was confirmed; never infer it.'},
            'callback_at':{'type':'string','description':'Explicitly agreed callback time as ISO 8601 with timezone. Use an empty string if no exact time was agreed; never infer a commitment.'}}),
        ('claim911_propose_correction','/voice/propose','Ask backend to propose a routing correction after matching hospital dispatch evidence and recipient lookup are present. This cannot approve or execute it.',{}),
    ]:
        properties={'call_token':{'type':'string','description':'Internal auto-injected call_token from the prompt. Never ask the participant for it.'},**props}
        definitions.append({'name':name,'description':description,'pre_call_message':'Let me check the case record.',
            'parameters':{'type':'object','properties':properties,'required':list(properties)},'key':'custom_task'})
        params[name]={'method':'POST','url':base+path,'api_token':'Bearer '+token,'headers':{},
                      'param':json.dumps({k:f'%({k})s' for k in properties})}
    return {'tools':definitions,'tools_params':params}


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True);p.add_argument('--gateway-url',required=True)
    p.add_argument('--apply',action='store_true');args=p.parse_args()
    base=args.gateway_url.rstrip('/');parsed=urlparse(base)
    if parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.trycloudflare.com') or parsed.path:
        raise SystemExit('Use the HTTPS root of the dedicated temporary Cloudflare gateway.')
    runtime=Path(args.runtime);cfg=json.loads((runtime/'coordinator.json').read_text())
    with httpx.Client(base_url='https://api.bolna.ai',timeout=30,headers={'Authorization':'Bearer '+cfg['bolna_api_key']}) as client:
        r=client.get('/v2/agent/'+cfg['bolna_agent_id']);r.raise_for_status();original=r.json()
        if original['agent_name']!='Claim911 | Insurance Coordination Demo':
            raise SystemExit('Refusing to modify a different agent')
        tasks=copy.deepcopy(original['tasks']);tasks[0]['tools_config']['api_tools']=tool_config(base,cfg['gateway_token'])
        voice=cfg.get('voice_preferences')
        if voice:
            synth=tasks[0]['tools_config']['synthesizer']
            if voice['provider']!=synth['provider']:
                raise SystemExit('Voice preference must match the configured synthesizer provider')
            synth['provider_config'].update({k:voice[k] for k in ['voice','voice_id','speed']})
        tasks[0]['tools_config']['transcriber']['language']='en'
        tasks[0]['tools_config']['llm_agent']['llm_config']['max_tokens']=500
        tasks[0]['task_config']['call_terminate']=120
        tasks[0]['task_config']['auto_reschedule']=False
        payload={'agent_config':{'agent_name':original['agent_name'],'agent_type':original['agent_type'],'tasks':tasks,
            'agent_welcome_message':'{{claim911_greeting}}',
            'webhook_url':base+'/voice/webhook','webhook_headers':{'X-Webhook-Token':cfg['webhook_token']}},
            'agent_prompts':{'task_1':{'system_prompt':PROMPT}},
            'composition_by_language':{'en':[{'type':'text','text':PROMPT}]}}
        if not args.apply:
            print('Prepared dedicated-agent update: 6 scoped tools, English baseline, 120-second calls, authenticated webhook.')
            return
        backup=runtime/'bolna-agent-before-tools.json'
        if not backup.exists():backup.write_text(json.dumps(original,indent=2));backup.chmod(0o600)
        r=client.put('/v2/agent/'+cfg['bolna_agent_id'],json=payload)
        print('Agent update HTTP status:',r.status_code)
        if not r.is_success:
            # Provider error can echo secret values; retain privately rather than printing it.
            error=runtime/'bolna-config-error.txt';error.write_text(r.text);error.chmod(0o600)
            raise SystemExit('Provider rejected configuration. Details saved privately for inspection.')
        r=client.get('/v2/agent/'+cfg['bolna_agent_id']);r.raise_for_status();saved=r.json()
        tools=saved['tasks'][0]['tools_config'].get('api_tools') or {}
        assert len(tools.get('tools',[]))==7
        assert saved['tasks'][0]['tools_config']['transcriber']['language']=='en'
        assert saved['webhook_url']==base+'/voice/webhook'
        assert '{{call_token}}' in saved['agent_prompts']['task_1']['system_prompt']
        if voice:
            assert all(saved['tasks'][0]['tools_config']['synthesizer']['provider_config'][k]==voice[k] for k in ['voice','voice_id','speed'])
        (runtime/'bolna-agent.json').write_text(json.dumps(saved,indent=2));(runtime/'bolna-agent.json').chmod(0o600)
        cfg['gateway_url']=base
        (runtime/'coordinator.json').write_text(json.dumps(cfg,indent=2));(runtime/'coordinator.json').chmod(0o600)
        print('Saved agent verified: scoped tools, English baseline and gateway callback.')


if __name__=='__main__':main()
