"""Inspect an existing Bolna transcript without starting or advancing any call.

Default is a no-cost inventory. Explicit --execute-provider performs one bounded
text classification, preserving the failed run and reporting no checkpoint pass.
"""
import argparse,hashlib,json,sys
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sandbox.dialogue_quality import evaluate_dialogue
from sandbox.provider_control import DockerProvider
from sandbox.spend import reserve,settle
from scripts.configure_sandbox_bolna import _write_private


def parse_transcript(text):
    import re
    turns=[]
    for line in text.splitlines():
        match=re.match(r'^\s*(assistant|agent|user|human)\s*:\s*(.*)$',line,re.I)
        if match:
            speaker='assistant' if match[1].lower() in {'assistant','agent'} else 'participant'
            if turns and turns[-1]['speaker']==speaker:turns[-1]['text']+=' '+match[2]
            else:turns.append({'speaker':speaker,'text':match[2]})
        elif line.strip() and turns:turns[-1]['text']+=' '+line.strip()
    return turns


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('runtime','report','facts','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--execute-provider',action='store_true');a=p.parse_args()
    source=Path(a.report).resolve();saved=json.loads(source.read_text());facts=json.loads(Path(a.facts).read_text())
    if saved.get('transport')!='BOLNA_WEBRTC' or saved.get('synthetic') is not True or saved.get('phone_dispatch') is not False:
        raise ValueError('Synthetic Bolna browser evidence required')
    if facts.get('synthetic') is not True or facts.get('role')!=saved.get('participant_role'):raise ValueError('Role-bounded synthetic facts required')
    exchanges=[{k:t[k] for k in ('assistant_text','participant_text')} for t in saved['turns']]
    transcript=parse_transcript(saved['provider_transcript'])
    if not a.execute_provider:
        print(json.dumps({'provider_requests':0,'turns':len(transcript),'role':saved['participant_role'],'state_advanced':False}));return
    output=Path(a.output).resolve()
    if output.exists():raise ValueError('Existing evaluation evidence must be preserved')
    root=Path(a.runtime).resolve();cfg=json.loads((root/'sandbox/coordinator.json').read_text())
    if cfg.get('environment')!='sandbox' or cfg.get('live_calls_enabled'):raise ValueError('Non-phone sandbox required')
    provider=DockerProvider(json.loads((root/'azure/provider.json').read_text()))
    result={'scope':'SAVED_BOLNA_DIALOGUE_REVIEW','source_report_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
        'new_bolna_session':False,'checkpoint_eligible':False,'state_advanced':False,'provider_requests':0}
    def invoke(messages,tools,*,output_schema=None):
        if tools:raise PermissionError('Saved dialogue review cannot execute tools')
        request=str(uuid4())
        with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
            hold=reserve(conn,request_id=request,run_id=saved['run_id'],phase='rehearsal',operation='judge',maximum_micro=100000)
        if not hold['new_reservation']:raise RuntimeError('Uncertain duplicate request')
        result['provider_requests']+=1
        try:
            reply=provider.request('reply',{'messages':messages,'tools':[],'output_schema':output_schema},reservation_id=request)
            result['model_usage']=reply.get('usage');return reply
        finally:
            with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:settle(conn,request)
    try:
        result['evaluation']=evaluate_dialogue(transcript=transcript,participant_role=saved['participant_role'],
            known_facts=facts,invoke=invoke,assistant_provider='BOLNA_WEBRTC',expected_exchanges=exchanges)
    finally:_write_private(output,result)
    print(json.dumps(result))
    if not result['evaluation']['conversation_quality_passed']:raise SystemExit(1)


if __name__=='__main__':main()
