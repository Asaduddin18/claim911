"""Begin one persistent real-audio synthetic case. Full desk loop is still pending.

Run from the workspace root. Existing identity blocks blind repeat execution.
All private configuration stays under work/claim911-runtime.
"""
import argparse,base64,json,sys,wave
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parents[1]))
from coordinator.app import create_app
from coordinator.model_tools import ScopedToolModel
from simulator.app import create_app as institution_app
from sandbox.provider_control import DockerProvider
from sandbox.audio_gateway import AudioGateway
from sandbox.stdio_control import run_worker
from sandbox.checkpoints import CheckpointVerifier
from sandbox import runs
from sandbox.spend import reserve,settle
from sandbox.conversations import converse


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--continue-intake',action='store_true');args=parser.parse_args()
    root=Path('work/claim911-runtime');state=root/'sandbox/active_audio_case.json'
    if state.exists() and not args.continue_intake:raise RuntimeError('A persistent audio case already exists. Inspect it and resume its checkpoint; never start over blindly.')
    cfg=json.loads((root/'sandbox/coordinator.json').read_text());sim=json.loads((root/'sandbox/simulator.json').read_text())
    provider=DockerProvider(json.loads((root/'azure/provider.json').read_text()));active={}
    def db():return psycopg.connect(cfg['dsn'],row_factory=dict_row)
    with TestClient(create_app(cfg)) as core,TestClient(institution_app(sim)) as env:
        core.headers['Authorization']='Bearer '+cfg['operator_token']
        if args.continue_intake:
            identity=json.loads(state.read_text());id=identity['incident_id'];seed={'case_id':identity['institution_case_id']}
            current=core.get('/v1/incidents/'+id);current.raise_for_status();consent_version=current.json()['incident']['consent_version']
            with db() as conn:
                run=runs.get(conn,identity['run_id'])
                if run['state']!='PAUSED' or run['checkpoint']!=0:raise RuntimeError('Only a stopped, uncompleted intake can be explicitly continued')
                runs.control(conn,run['id'],'resume');leased=runs.claim(conn,run['id'])
        else:
            seed=env.post('/evaluator/complex-runs',headers={'Authorization':'Bearer '+sim['tokens']['evaluator']});seed.raise_for_status();seed=seed.json()
            intake=core.post('/v1/intakes',headers={'Idempotency-Key':str(uuid4())},json={'case_id':seed['case_id'],'patient_id':seed['patient_id'],
                'reference_known':False,'title':'Synthetic agent-led discharge coordination'});intake.raise_for_status();id=intake.json()['incident_id']
            consent=core.post(f'/v1/incidents/{id}/consent',json={'accepted':True,'confirmation':'Explicit synthetic caregiver-role fixture permits this isolated audio investigation; document sharing remains a separate approval.'});consent.raise_for_status();consent_version=consent.json()['consent_version']
            with db() as conn:
                runs.initialize(conn,environment='sandbox');run=runs.create(conn,origin='AUDIO_DEMONSTRATION')
                runs.attach_case(conn,run['id'],incident_id=id,institution_case_id=seed['case_id'],provider_configuration={
                    'model':'gpt-5-mini','model_version':'2025-08-07','speech_tier':'F0','transport':'PIPECAT_STDIO'})
                leased=runs.claim(conn,run['id'])
            identity={'run_id':str(run['id']),'incident_id':id,'institution_case_id':seed['case_id'],'stage':'CAREGIVER_INTAKE_STARTED'}
        if not leased:raise RuntimeError('Run was not claimed; review its consent, clock and recovery state')
        state.write_text(json.dumps(identity,indent=2));state.chmod(0o600)
        opened=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':'CAREGIVER_INTAKE','audio_provenance':'PIPECAT_STDIO'});opened.raise_for_status();call=opened.json()
        def permitted(run_id,case_id,version):
            with db() as conn:
                current=runs.get(conn,run['id'])
                incident=conn.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(id,)).fetchone()
            return current['state']=='RUNNING' and current['lease_token']==leased['lease_token'] and current['lease_until']>datetime.now(timezone.utc) and str(current['id'])==run_id and str(current['institution_case_id'])==case_id and incident['consent_active'] and incident['consent_version']==version
        def reserve_cost(request_id,run_id,operation):
            with db() as conn:
                reservation=reserve(conn,request_id=request_id,run_id=run_id,phase='development',operation=operation,maximum_micro=100000)
                if not reservation['new_reservation']:raise RuntimeError('Prior provider request needs reconciliation')
            active['request_id']=request_id
        def finish_cost(request_id):
            with db() as conn:settle(conn,request_id)
        bridge=ScopedToolModel(core,call['call_token'],lambda messages,tools:provider.request('reply',{'messages':messages,'tools':tools},reservation_id=active['request_id']),
            authorized=lambda:permitted(str(run['id']),seed['case_id'],consent_version))
        gateway=AudioGateway(speech=provider,model=bridge,reserve_cost=reserve_cost,finish_cost=finish_cost,consent_active=permitted)
        capability=gateway.issue(run_id=run['id'],case_id=seed['case_id'],role='caregiver',language='en',consent_version=consent_version,
            context='This is the caregiver intake. Record only their confirmed concern and preferred language. Investigation consent exists only as an explicit synthetic fixture; document disclosure is not approved.',ttl=600)
        def caregiver_reply(history):
            if not permitted(str(run['id']),seed['case_id'],consent_version):raise RuntimeError('Caregiver actor run lease is no longer current')
            request_id=str(uuid4());reserve_cost(request_id,str(run['id']),'persona')
            try:
                response=provider.request('reply',{'messages':[{'role':'developer','content':'You are the synthetic caregiver in a test. You prefer English. Your concern is: medically ready for discharge, but hospital says insurance approval is pending. You permit investigation as a synthetic fixture but have not approved document sharing. Answer only the latest question truthfully in one short sentence. If the agent reads back these facts accurately, explicitly confirm them. Do not invent hospital or insurance references.'}]+history},reservation_id=request_id)
                return response['text']
            finally:finish_cost(request_id)
        result=converse(gateway=gateway,capability=capability,speech=provider,actor_reply=caregiver_reply,
            initial_text='I am the caregiver. I prefer English. We are medically ready for discharge, but insurance approval is pending. I confirm this as my concern.',
            language='en',done=lambda:any(a['tool']=='claim911_report_update' for a in bridge.audit),max_turns=4)
        if not result['completed_objective']:raise RuntimeError('Caregiver confirmation did not produce a saved report within the bounded turns')
        recognized=next(e['text'] for e in result['events'] if e['operation']=='transcribe')
        finish=core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish',json={'turns':result['turns']});finish.raise_for_status()
        verifier=CheckpointVerifier(core,env,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']})
        check=verifier.inspect('caregiver_intake_confirmed',id)
        if not check['passed']:raise RuntimeError('Intake checkpoint did not verify: '+check['reason'])
        with db() as conn:
            verified=runs.complete_checkpoint(conn,run['id'],leased['lease_token'],'caregiver_intake_confirmed',check['evidence_references'],verify=verifier)
            runs.control(conn,run['id'],'pause');runs.acknowledge_stop(conn,run['id'],leased['lease_token'])
        gateway.revoke_run(run['id'])
        identity.update(stage='CAREGIVER_INTAKE_VERIFIED',checkpoint=verified['checkpoint'],call_id=call['call_id'],state='PAUSED_BETWEEN_IMPLEMENTATION_STAGES')
        state.write_text(json.dumps(identity,indent=2))
        for name,audio in [('Input',base64.b64decode(result['turns'][0]['pcm_base64'])),('Response',base64.b64decode(result['turns'][-1]['pcm_base64']))]:
            with wave.open('outputs/Claim911_Scenario_Intake_'+name+'.wav','wb') as wav:
                wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(audio)
        report={**identity,'provenance':'NATIVE_PIPECAT_AUDIO_AND_MODEL_SELECTED_REPORT_TOOL','synthetic':True,
            'recognized_text':recognized,'response':result['turns'][-1]['text'],'pipecat_turns':result['pipecat_turns'],'tool_audit':bridge.audit,'checkpoint_result':check,
            'worker_network':'none','credentials_sent_to_worker':False,'phone_dispatch':False,'full_case_completed':False}
        Path('outputs/Claim911_Scenario_Intake_Validation.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'run_id':identity['run_id'],'incident_id':id,'checkpoint':identity['checkpoint'],
                          'native_report_count':len(bridge.audit),'checkpoint_passed':check['passed'],'full_case_completed':False}))


if __name__=='__main__':main()
