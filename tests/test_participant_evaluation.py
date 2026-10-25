import json
from pathlib import Path
from sandbox.participant_evaluation import case_payload
from sandbox.participant_evaluation import require_participant_gate
import hashlib,pytest


def test_participant_is_scored_as_output_under_test_with_one_case_per_conversation():
    case={'role':'caregiver','question':'Which language?','success':'The answer is English.'}
    payload=case_payload(case,'English, please.')
    assert payload['messages']==[{'role':'user','content':'Which language?'},{'role':'assistant','content':'English, please.'}]
    assert len(payload['criteria'])==1 and 'caregiver' in payload['criteria']['grounded_answer']


def test_corpus_covers_all_roles_and_every_case_has_a_valid_independent_contract():
    suite=json.loads((Path(__file__).parents[1]/'sandbox/scenarios/participant-regressions-v1.json').read_text())
    assert len({c['id'] for c in suite['cases']})==len(suite['cases'])==18
    assert {c['role'] for c in suite['cases']}=={'caregiver','hospital_insurance','billing','medical_records','implant_store','tpa','insurer'}
    for case in suite['cases']:assert len(case_payload(case,'Synthetic answer.')['messages'])==2


def test_audio_preflight_rejects_failed_or_stale_participant_evidence(tmp_path):
    project=Path(__file__).parents[1];suite=project/'sandbox/scenarios/participant-regressions-v1.json'
    cases=json.loads(suite.read_text())['cases'];image='sha256:'+'a'*64
    report={'scope':'TEXT_PARTICIPANT_ONLY','passed':True,'bolna_assistant_tested':False,'provider_image':image,
        'suite_sha256':hashlib.sha256(suite.read_bytes()).hexdigest(),
        'participant_implementation_sha256':__import__('sandbox.participant_evaluation',fromlist=['participant_fingerprint']).participant_fingerprint(project),
        'evaluation':{'independent_cases':True,'cases':[{'id':c['id'],'passed':True} for c in cases]}}
    path=tmp_path/'report.json';path.write_text(json.dumps(report))
    assert require_participant_gate(path,project,image)['cases']==len(cases)
    for change in ({'passed':False},{'participant_implementation_sha256':'old'},{'source_capture':'old-recording.json'},
                   {'evaluation':{'independent_cases':True,'cases':[]}}):
        path.write_text(json.dumps(report|change))
        with pytest.raises(RuntimeError):require_participant_gate(path,project,image)


def test_resume_requires_unchanged_fresh_generation_not_old_captures():
    from sandbox.participant_evaluation import resumable_answers,participant_fingerprint,exact_reference_result
    project=Path(__file__).parents[1];path=project/'sandbox/scenarios/participant-regressions-v1.json';suite=json.loads(path.read_text())
    source={'scope':'TEXT_PARTICIPANT_ONLY','synthetic':True,'bolna_assistant_tested':False,'institution_writes':False,
      'failure':{'type':'ProviderOperationError'},'provider_image':'image',
      'suite_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'participant_implementation_sha256':participant_fingerprint(project),
      'cases':[{'id':c['id'],'role':c['role'],'question':c['question'],'answer':'Natural generated answer.'} for c in suite['cases']],
      'model_calls':[{'operation':'persona','text':'Natural generated answer.'}]}
    for case,answer in zip(suite['cases'],source['cases']):
        exact=exact_reference_result(case,'')
        if exact is not None:answer['answer']=exact['expected_answer']
    assert len(resumable_answers(source,suite=suite,project=project,provider_image='image'))==len(suite['cases'])
    for patch in [{'source_capture':'old.json'},{'participant_implementation_sha256':'changed'},
                  {'failure':{'type':'ValueError'}},{'model_calls':[]},
                  {'evaluation':{'cases':[{'passed':False}]}}]:
        with pytest.raises(ValueError):resumable_answers(source|patch,suite=suite,project=project,provider_image='image')


def test_reference_scoring_is_exact_and_does_not_replace_status_evaluation():
 from sandbox.participant_evaluation import exact_reference_result
 case={'question':'Confirm admission ID A D M four two. Is that correct?','record':{'admission_id':'ADM42'}}
 assert exact_reference_result(case,'Yes, that exact reference matches our record.')['passed']
 assert not exact_reference_result(case,'No, the reference in our record is ADM43.')['passed']
 assert exact_reference_result(case|{'question':'Confirm admission ID ADM42 has received clearance?'},'Yes.') is None


def test_saved_reference_answer_cannot_resume_with_changed_characters():
 from sandbox.participant_evaluation import exact_reference_result
 case={'question':'Confirm initial request reference ENH18. Is that correct?','record':{'references':{'preauthorization':'PRE37','enhancement':'ENH18'}}}
 assert exact_reference_result(case,'No, the reference in our record is PRE37.')['passed']
 assert not exact_reference_result(case,'No, the reference in our record is ENH18.')['passed']
