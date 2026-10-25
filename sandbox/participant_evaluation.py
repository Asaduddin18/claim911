"""Each role-player regression is its own conversation under Pipecat Evals."""
from sandbox.audio_worker.eval_contract import validate_payload
import hashlib,json
from pathlib import Path


def participant_fingerprint(project):
    digest=hashlib.sha256()
    for name in ('sandbox/participant_model.py','sandbox/participant_dialogue.py','sandbox/scripted_desks.py','sandbox/dialogue_quality.py','sandbox/readback_confirmation.py','sandbox/spoken_identifiers.py','coordinator/identifier_readbacks.py'):
        digest.update(name.encode()+b'\0'+(Path(project)/name).read_bytes())
    return digest.hexdigest()


def case_payload(case,answer):
    # The role player is the subject under test, so its answer is the
    # assistant output in the evaluator, irrespective of its live-call role.
    return validate_payload({'messages':[
        {'role':'user','content':case['question']},
        {'role':'assistant','content':answer}],
        'success':case['success'],
        'criteria':{'grounded_answer':'Evaluate the '+case['role']+' participant answer. '+case['success']}})


def exact_reference_result(case,answer):
    """Exact readbacks use a local comparison; conversation quality uses Evals."""
    from sandbox.readback_confirmation import reference_confirmation_reply,readback_evidence
    question=case['question']
    expected=reference_confirmation_reply(question,case['record'])
    if expected is None:return None
    return {'framework':'EXACT_ROLE_REFERENCE_COMPARISON','passed':answer==expected,
            'comparison':readback_evidence(question,case['record']),
            'expected_answer':expected,'actual_answer':answer,'provider_requests':0,
            'workflow_state_verified':False}


def require_participant_gate(report_path,project,provider_image):
    project=Path(project)
    try:
        report=json.loads(Path(report_path).read_text())
        suite_path=project/'sandbox/scenarios/participant-regressions-v1.json'
        suite=json.loads(suite_path.read_text());expected={c['id'] for c in suite['cases']}
        if (report.get('scope')!='TEXT_PARTICIPANT_ONLY' or report.get('passed') is not True
            or report.get('source_capture') or report.get('bolna_assistant_tested') is not False
            or report.get('provider_image')!=provider_image
            or report.get('suite_sha256')!=hashlib.sha256(suite_path.read_bytes()).hexdigest()
            or report.get('participant_implementation_sha256')!=participant_fingerprint(project)
            or report.get('evaluation',{}).get('independent_cases') is not True):
            raise ValueError('Participant evaluation is stale or incomplete')
        results=report['evaluation']['cases']
        if len(results)!=len(expected) or {c['id'] for c in results}!=expected or any(c.get('passed') is not True for c in results):
            raise ValueError('Every participant scenario must pass')
        return {'scope':report['scope'],'cases':len(expected),'report_sha256':hashlib.sha256(Path(report_path).read_bytes()).hexdigest()}
    except (OSError,KeyError,ValueError,TypeError) as exc:
        raise RuntimeError('A fresh passing participant text evaluation is required before automated Bolna audio testing') from exc


def resumable_answers(source,*,suite,project,provider_image):
    """Reuse only fresh generation interrupted by infrastructure, never old captures."""
    suite_path=Path(project)/'sandbox/scenarios/participant-regressions-v1.json'
    if (source.get('source_capture') or source.get('resumed_fresh_answers')
        or source.get('scope')!='TEXT_PARTICIPANT_ONLY' or source.get('synthetic') is not True
        or source.get('bolna_assistant_tested') is not False or source.get('institution_writes') is not False
        or source.get('failure',{}).get('type') not in {'ProviderOperationError','TimeoutError'}
        or source.get('provider_image')!=provider_image
        or source.get('suite_sha256')!=hashlib.sha256(suite_path.read_bytes()).hexdigest()
        or source.get('participant_implementation_sha256')!=participant_fingerprint(project)
        or any(c.get('passed') is not True for c in source.get('evaluation',{}).get('cases',[]))):
        raise ValueError('Only an unchanged fresh infrastructure-interrupted evaluation can resume')
    cases=source.get('cases',[])
    if len(cases)!=len(suite['cases']) or [c.get('id') for c in cases]!=[c['id'] for c in suite['cases']]:
        raise ValueError('Complete ordered generated answers required')
    generated={str(c.get('text','')).strip().replace('\u2014',',') for c in source.get('model_calls',[]) if c.get('operation')=='persona'}
    for case,answer in zip(suite['cases'],cases):
        exact=exact_reference_result(case,answer.get('answer'))
        supported=exact['passed'] if exact is not None else answer.get('answer') in generated
        if (answer.get('role')!=case['role'] or answer.get('question')!=case['question']
            or not supported):raise ValueError('Generated answer provenance mismatch')
    return {c['id']:c for c in cases}
