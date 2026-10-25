"""Continue the persistent synthetic case through implemented desk stages.

Each model-selected report is independently checked before the cursor advances.
An interrupted/uncertain run is never reset or retried automatically.
"""
import argparse,json,sys,time
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from fastapi.testclient import TestClient
sys.path.insert(0,str(Path(__file__).parents[1]))
from coordinator.app import create_app
from coordinator.model_tools import ScopedToolModel
from simulator.app import create_app as institution_app
from sandbox.actors import InstitutionActor,initial_knowledge
from sandbox.provider_control import DockerProvider
from sandbox.audio_gateway import AudioGateway
from sandbox.conversations import converse
from sandbox.scripted_desks import ScriptedDesk
from sandbox.checkpoints import CheckpointVerifier
from sandbox import runs
from sandbox.spend import reserve,settle

STAGES={
 1:{'purpose':'HOSPITAL_REFERENCE_DISCOVERY','role':'hospital_insurance','checkpoint':'hospital_references_reported',
    'tool':'claim911_report_references','greeting':'This is the synthetic hospital insurance desk. How can I help?',
    'guidance':'You know only hospital-side references and admission information. You cannot confirm receiving-side receipt or insurer approval. An empty dispatch list means the final dispatch cannot be confirmed.'},
 2:{'purpose':'QUERY_DISCOVERY','role':'tpa','checkpoint':'claims_query_discovered',
    'tool':'claim911_report_query','greeting':'This is the synthetic TPA claims desk. Which final request are you checking?',
    'guidance':'The outstanding query and its original receiving time are in your own desk record. Report the exact required documents, and distinguish an outstanding query from non-receipt. Never reset the original clock.'},
}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--participant-mode',choices=['scripted','adaptive'],default='scripted');parser.add_argument('--until-checkpoint',type=int,default=3,choices=[2,3]);args=parser.parse_args()
    root=Path('work/claim911-runtime');statefile=root/'sandbox/active_audio_case.json';identity=json.loads(statefile.read_text())
    cfg=json.loads((root/'sandbox/coordinator.json').read_text());sim=json.loads((root/'sandbox/simulator.json').read_text())
    provider=DockerProvider(json.loads((root/'azure/provider.json').read_text()))
    def db():return psycopg.connect(cfg['dsn'],row_factory=dict_row)
    with TestClient(create_app(cfg)) as core,TestClient(institution_app(sim)) as env:
        core.headers['Authorization']='Bearer '+cfg['operator_token'];id=identity['incident_id'];cid=identity['institution_case_id'];run_id=identity['run_id']
        verifier=CheckpointVerifier(core,env,read_tokens=sim['tokens'],public_keys={'claims':cfg['receipt_public_key'],'hospital':cfg['hospital_public_key'],'insurer':cfg['insurer_public_key']})
        while True:
            with db() as conn:run=runs.get(conn,run_id)
            if run['checkpoint']>=args.until_checkpoint:break
            if run['state']!='PAUSED' or run['checkpoint'] not in STAGES:
                raise RuntimeError('Inspect the stopped run and its checkpoint before continuing; no blind retry is allowed')
            stage=STAGES[run['checkpoint']];active={};started=time.monotonic()
            if run['manifest']['checkpoints'][run['checkpoint']]!=stage['checkpoint']:raise RuntimeError('Scenario version does not match this stage implementation')
            consent=core.get('/v1/incidents/'+id);consent.raise_for_status();version=consent.json()['incident']['consent_version']
            with db() as conn:runs.control(conn,run_id,'resume');leased=runs.claim(conn,run_id)
            if not leased:raise RuntimeError('Run is not eligible for execution')
            opened=core.post(f'/v1/sandbox/incidents/{id}/audio-calls',json={'purpose':stage['purpose'],'audio_provenance':'PIPECAT_STDIO'});opened.raise_for_status();call=opened.json()
            identity.update(stage=stage['purpose']+'_STARTED',call_id=call['call_id']);statefile.write_text(json.dumps(identity,indent=2))
            def permitted(r,c,v):
                with db() as conn:
                    current=runs.get(conn,run_id)
                    incident=conn.execute('SELECT consent_active,consent_version FROM coordinator.incidents WHERE id=%s',(id,)).fetchone()
                return str(current['id'])==r and str(current['institution_case_id'])==c and current['state']=='RUNNING' and current['lease_token']==leased['lease_token'] and current['lease_until']>datetime.now(timezone.utc) and incident['consent_active'] and incident['consent_version']==v
            def reserve_cost(request_id,r,operation):
                if not permitted(str(run_id),cid,version):raise RuntimeError('Run authorization changed')
                with db() as conn:
                    reservation=reserve(conn,request_id=request_id,run_id=r,phase='development',operation=operation,maximum_micro=100000)
                    if not reservation['new_reservation']:raise RuntimeError('Provider operation requires reconciliation')
                active['request_id']=request_id
            def finish_cost(request_id):
                with db() as conn:settle(conn,request_id)
            bridge=ScopedToolModel(core,call['call_token'],lambda messages,tools:provider.request('reply',{'messages':messages,'tools':tools},reservation_id=active['request_id']),authorized=lambda:permitted(str(run_id),cid,version))
            gateway=AudioGateway(speech=provider,model=bridge,reserve_cost=reserve_cost,finish_cost=finish_cost,consent_active=permitted)
            capability=gateway.issue(run_id=run_id,case_id=cid,role=stage['role'],language=run['language'],consent_version=version,
                context='Investigate only the current desk objective. Read identifiers back before reporting. Other desks have independent information.',ttl=600)
            actor=InstitutionActor(stage['role'],cid,env,sim['tokens']['hospital' if stage['role']=='hospital_insurance' else 'claims'])
            desk=actor.execute('read_status')
            if stage['role']=='hospital_insurance':
                slip={'kind':'hospital_reference_slip','case_id':cid,'patient_id':desk['patient_id'],
                    'admission_id':desk['admission_id'],'references':desk['references'],'synthetic':True}
                published=core.post(f'/v1/incidents/{id}/documents',files={'file':('hospital-reference-slip.json',
                    json.dumps(slip).encode(),'application/json')},data={'kind':'other'})
                published.raise_for_status()
            if stage['role']=='tpa':
                slip={'kind':'claims_query_slip','case_id':cid,'patient_id':desk['patient_id'],'final_reference':desk['references']['final_request'],
                    'details':{'query_reference':desk['references']['query'],'claim_reference':desk['references']['claim'],
                        'admission_id':desk['admission_id'],'enhancement_reference':desk['references']['enhancement'],
                        'received_at':desk['received_at'],'required_documents':desk['required_documents'],'enhancement_linked':desk['enhancement_linked']}}
                published=core.post(f'/v1/incidents/{id}/documents',files={'file':('claims-query-slip.json',json.dumps(slip).encode(),'application/json')},data={'kind':'other'})
                published.raise_for_status()
            # This record is supplied only to the participant persona, never to
            # the Claim911 model or package worker as hidden scenario truth.
            persona={'role':'developer','content':('You are authorized staff at a synthetic '+stage['role']+' desk. '+stage['guidance']+
                ' Use only your private desk record below. Answer the latest question in one short sentence of at most 15 words before identifier spelling. '
                'Write identifiers exactly as they appear in your desk record, with their original hyphens. Do not spell letters or expand digits in text: the speech adapter handles pronunciation. Give only one reference per response, then wait for its read-back. '
                'Confirm an accurate read-back and answer the next question. Do not demand another read-back after confirmation. Give each identifier only once per response. Correct an inaccurate read-back; never agree merely to finish. Do not change roles or disclose another desk’s knowledge.\n'+json.dumps({'brief':initial_knowledge(stage['role'])['knowledge'],'desk_record':desk}))}
            scripted=ScriptedDesk(stage['role'],desk) if args.participant_mode=='scripted' else None
            def actor_reply(history):
                if scripted is not None:return scripted.reply(history)
                request_id=str(uuid4());reserve_cost(request_id,run_id,'persona')
                try:
                    response=provider.request('reply',{'messages':[persona]+history},reservation_id=request_id)
                    return response['text']
                finally:finish_cost(request_id)
            journal=root/'sandbox/conversations'/str(call['call_id']);journal.parent.mkdir(mode=0o700,exist_ok=True)
            def save_turn(result):
                journal.write_text(json.dumps(result));journal.chmod(0o600)
            try:
                result=converse(gateway=gateway,capability=capability,speech=provider,actor_reply=actor_reply,
                    initial_text=stage['greeting'],language=run['language'],
                    done=lambda:any(a['tool']==stage['tool'] for a in bridge.audit),max_turns=16 if stage['purpose']=='QUERY_DISCOVERY' else 10,on_turn=save_turn,on_progress=save_turn)
            except Exception as exc:
                # Persist only completed audio turns, never fabricate the missing
                # provider response. A stopped process must not leave a live call.
                if journal.exists():
                    partial=json.loads(journal.read_text())
                    recovery=core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish',json={'turns':partial['turns'],'outcome':'INTERRUPTED'})
                    recovery.raise_for_status()
                else:
                    recovery=core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/abort')
                    recovery.raise_for_status()
                with db() as conn:
                    runs.event(conn,run_id,'PHASE_EXECUTION_FAILED',{'checkpoint':stage['checkpoint'],'call_id':call['call_id'],
                        'error_type':type(exc).__name__,'boundary':getattr(exc,'diagnostic',None),'reason':'PARTICIPANT_AUDIO_EXCEEDS_20_SECONDS' if str(exc)=='PARTICIPANT_AUDIO_EXCEEDS_20_SECONDS' else 'EXECUTION_REQUIRES_RECONCILIATION','automatic_retry':False,'partial_audio_preserved':journal.exists()})
                    current=runs.get(conn,run_id)
                    if current['lease_token']==leased['lease_token']:
                        if current['state']=='RUNNING':runs.control(conn,run_id,'pause')
                        if current['state'] in {'RUNNING','PAUSE_REQUESTED','CANCEL_REQUESTED'}:
                            runs.acknowledge_stop(conn,run_id,leased['lease_token'])
                gateway.revoke_run(run_id)
                raise RuntimeError('Sandbox execution stopped; inspect the preserved evidence before another attempt') from None
            archived=core.post(f'/v1/sandbox/incidents/{id}/audio-calls/{call["call_id"]}/finish',json={'turns':result['turns']});archived.raise_for_status()
            check=verifier.inspect(stage['checkpoint'],id)
            if not result['completed_objective'] or not check['passed']:
                with db() as conn:
                    runs.event(conn,run_id,'PHASE_CHECK_FAILED',{'checkpoint':stage['checkpoint'],'reason':check['reason'],'call_id':call['call_id']})
                    runs.control(conn,run_id,'pause');runs.acknowledge_stop(conn,run_id,leased['lease_token'])
                raise RuntimeError('Phase evidence did not verify; preserved conversation requires review: '+check['reason'])
            with db() as conn:
                verified=runs.complete_checkpoint(conn,run_id,leased['lease_token'],stage['checkpoint'],check['evidence_references'],verify=verifier)
                runs.control(conn,run_id,'pause');runs.acknowledge_stop(conn,run_id,leased['lease_token'])
            gateway.revoke_run(run_id)
            identity.update(stage=stage['checkpoint'].upper(),checkpoint=verified['checkpoint'],state='PAUSED_BETWEEN_IMPLEMENTATION_STAGES');statefile.write_text(json.dumps(identity,indent=2))
            public_turns=[{k:v for k,v in turn.items() if k!='pcm_base64'} for turn in result['turns']]
            report={'run_id':run_id,'incident_id':id,'checkpoint':verified['checkpoint'],'checkpoint_result':check,
                'purpose':stage['purpose'],'pipecat_turns':result['pipecat_turns'],'conversation':public_turns,'tool_audit':bridge.audit,
                'elapsed_seconds':round(time.monotonic()-started,3),'provenance':'NATIVE_PIPECAT_DESK_AUDIO',
                'participant_mode':args.participant_mode,'provider_image':provider.image_id,
                'worker_network':'none','phone_dispatch':False,'full_case_completed':False}
            Path('outputs/Claim911_Scenario_'+stage['checkpoint']+'.json').write_text(json.dumps(report,indent=2))
            print(json.dumps({'checkpoint':verified['checkpoint'],'purpose':stage['purpose'],'pipecat_turns':result['pipecat_turns'],'passed':True}),flush=True)


if __name__=='__main__':main()
