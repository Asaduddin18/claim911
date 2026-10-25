"""Text-first role-player evaluation using existing pytest/Pipecat Evals blocks.

No audio, Bolna session, institution write, or workflow checkpoint is involved.
Without --execute-provider this prints the suite inventory and spends nothing.
"""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime,timezone
import psycopg
from psycopg.rows import dict_row
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sandbox.participant_model import DeskParticipant,ReadOnlyRoleRecord
from sandbox.participant_dialogue import ParticipantDialogue
from sandbox.provider_control import DockerProvider
from sandbox.eval_control import run_evaluation
from sandbox.evaluation import classify
from sandbox.participant_evaluation import case_payload,participant_fingerprint,resumable_answers,exact_reference_result
from sandbox.spend import reserve,settle
from scripts.configure_sandbox_bolna import _write_private


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--runtime',required=True)
    parser.add_argument('--phase',choices=['development','integration','rehearsal'],default='development');parser.add_argument('--output',required=True);parser.add_argument('--capture');parser.add_argument('--resume-answers');parser.add_argument('--execute-provider',action='store_true');parser.add_argument('--publish-gate',action='store_true');parser.add_argument('--max-provider-requests',type=int,choices=range(1,65),default=44);parser.add_argument('--evaluation-phase',choices=['development','integration','rehearsal','reserve'],help='Optional separate existing budget allocation for evaluator requests');args=parser.parse_args()
    project=Path(__file__).resolve().parents[1];suite_path=project/'sandbox/scenarios/participant-regressions-v1.json'
    suite=json.loads(suite_path.read_text())
    if not args.execute_provider:print(json.dumps({'scope':suite['scope'],'cases':[c['id'] for c in suite['cases']],'provider_requests':0}));return
    output=Path(args.output).resolve()
    if output.exists():raise ValueError('Preserve prior evidence; choose a new output path')
    root=Path(args.runtime).resolve();cfg=json.loads((root/'sandbox/coordinator.json').read_text())
    if cfg.get('environment')!='sandbox' or cfg.get('bolna_api_key') or cfg.get('live_calls_enabled'):raise ValueError('Isolated non-phone sandbox required')
    from sandbox.local_preflight import run_local_preflight
    local_preflight=run_local_preflight(project)
    from sandbox.spend import require_testing
    with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:require_testing(conn)
    provider_cfg=json.loads((root/'azure/provider.json').read_text());provider=DockerProvider(provider_cfg)
    run_id=str(uuid4());requests=[];results=[]
    report={'run_id':run_id,'scope':suite['scope'],'suite_version':suite['version'],'synthetic':True,'bolna_assistant_tested':False,
        'audio_tested':False,'workflow_state_verified':False,'institution_writes':False,'passed':False,
        'local_preflight':local_preflight,
        'participant_model':provider_cfg['model']['model'],'provider_image':provider.image_id,
        'suite_sha256':hashlib.sha256(suite_path.read_bytes()).hexdigest(),
        'participant_implementation_sha256':participant_fingerprint(project),
        'cases':results,'started_at':datetime.now(timezone.utc).isoformat()}
    captures={}
    if args.capture and args.resume_answers:raise ValueError('Choose capture review or interrupted fresh evaluation')
    if args.resume_answers:
        raw=Path(args.resume_answers).read_bytes();source=json.loads(raw)
        captures=resumable_answers(source,suite=suite,project=project,provider_image=provider.image_id)
        if source.get('participant_model')!=report['participant_model']:raise ValueError('Participant model changed')
        report['resumed_fresh_answers']={'source_sha256':hashlib.sha256(raw).hexdigest(),'all_cases_rejudged':True,'generation_repeated':False}
    if args.capture:
        source=json.loads(Path(args.capture).read_text())
        if source.get('scope')!=suite['scope'] or source.get('suite_version')!=suite['version'] or source.get('bolna_assistant_tested') is not False:
            raise ValueError('A matching saved participant-only capture is required')
        captures={c['id']:c for c in source['cases']}
        if set(captures)!={c['id'] for c in suite['cases']}:raise ValueError('Complete saved participant suite required')
        report['source_capture']=str(Path(args.capture).resolve())
        report['participant_implementation_sha256']=source.get('participant_implementation_sha256','unknown_historical_capture')
    report['model_calls']=[]
    def invoke(messages,tools,*,operation='persona',output_schema=None):
        if tools:raise PermissionError('Text participant suite is read-only')
        if len(requests)>=args.max_provider_requests:raise RuntimeError('Participant test request limit reached; no automatic retry')
        id=str(uuid4())
        with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:
            hold=reserve(conn,request_id=id,run_id=run_id,phase=(args.evaluation_phase or args.phase) if operation=='judge' else args.phase,operation=operation,maximum_micro=20000)
        if not hold['new_reservation']:raise RuntimeError('Duplicate request requires reconciliation')
        requests.append(id)
        try:
            body={'messages':messages,'tools':[]}
            if output_schema is not None:body['output_schema']=output_schema
            result=provider.request('reply',body,reservation_id=id)
            from sandbox.model_usage import store_usage
            with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:store_usage(conn,id,result)
            report['model_calls'].append({'request_id':id,'operation':operation,'model':result.get('model'),'usage':result.get('usage'),'text':result.get('text')})
            _write_private(output,report)
            return result
        finally:
            with psycopg.connect(cfg['dsn'],row_factory=dict_row) as conn:settle(conn,id)
    _write_private(output,report)
    try:
        evaluations=[]
        for case in suite['cases']:
            record=case['record']|{'role':case['role'],'synthetic':True}
            participant=DeskParticipant(ReadOnlyRoleRecord(case['role'],record),invoke,authorized=lambda:True,
                brief='Answer as this synthetic person from your current record.')
            if captures:
                captured=captures[case['id']]
                if captured['role']!=case['role'] or captured['question']!=case['question']:raise ValueError('Saved question or role differs from this suite')
                answer=captured['answer'];DeskParticipant._text({'text':answer},record)
            else:answer=ParticipantDialogue(participant.reply).prepare(1,case['question']).answer
            results.append({'id':case['id'],'role':case['role'],'question':case['question'],'answer':answer})
            _write_private(output,report)
        image=subprocess.run(['docker','--context','colima-claim911-sandbox','image','inspect','--format','{{.Id}}','claim911-evals-worker:local'],
            capture_output=True,text=True,check=True,timeout=10).stdout.strip()
        report['evaluation']={'framework':'pipecat.evals','independent_cases':True,'cases':evaluations}
        for case,result in zip(suite['cases'],results):
            exact=exact_reference_result(case,result['answer'])
            if exact is not None:
                evaluations.append({'id':case['id'],'passed':exact['passed'],'result':exact})
                _write_private(output,report)
                continue
            judged=run_evaluation(case_payload(case,result['answer']),image_id=image,
                classify=lambda m:classify(m,invoke=lambda ms,ts,**kw:invoke(ms,ts,operation='judge',**kw)))
            passed=judged['goal']['verdict']=='yes' and all(m['passed'] for m in judged['metrics'])
            evaluations.append({'id':case['id'],'passed':passed,'result':judged})
            _write_private(output,report)
        report['passed']=all(e['passed'] for e in evaluations)
    except Exception as exc:
        report['failure']={'type':type(exc).__name__,'automatic_retry':False,'boundary':getattr(exc,'diagnostic',None)}
        raise
    finally:
        report.update(provider_requests=len(requests),maximum_reserved_usd=len(requests)/10,finished_at=datetime.now(timezone.utc).isoformat())
        _write_private(output,report)
    print(json.dumps({'scope':report['scope'],'passed':report['passed'],'cases':len(results),'provider_requests':len(requests),'output':str(output)}))
    if not report['passed']:raise SystemExit(1)
    if args.publish_gate:
        if args.capture:raise ValueError('Saved captures cannot publish an audio admission gate')
        # Immutable output remains the audit history; this private snapshot is
        # the standard last-successful admission record for UI and CLI runs.
        _write_private(root/'sandbox/participant-text-gate.json',report)


if __name__=='__main__':main()
